#!/usr/bin/env python3
"""Image Fidelity Lab: reproducible full-reference image-quality comparison.

Dependencies: numpy, opencv-python (Python 3.9+). No model downloads or network.
Uses normalized sRGB samples in [0, 1]; not colour-managed or HDR-aware.
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional, Sequence

import cv2
import numpy as np

__version__ = "1.0.0"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
BT601 = (0.299, 0.587, 0.114)
MS_SSIM_WEIGHTS = (0.0448, 0.2856, 0.3001, 0.2363, 0.1333)


@dataclass
class LoadedImage:
    rgb: np.ndarray
    alpha: Optional[np.ndarray]
    width: int
    height: int
    bit_depth: int
    channels: int
    file_size_bytes: int
    path: str


def read_image(path: Path) -> LoadedImage:
    """Read byte- or 16-bit image with Unicode-safe paths and preserve alpha."""
    if not path.is_file():
        raise FileNotFoundError(f"Image does not exist: {path}")
    try:
        image_bytes = np.fromfile(str(path), dtype=np.uint8)
        image = cv2.imdecode(image_bytes, cv2.IMREAD_UNCHANGED)
    except (OSError, cv2.error) as exc:
        raise ValueError(f"Cannot read {path}: {exc}") from exc
    if image is None:
        raise ValueError(f"Unsupported or corrupt image: {path}")
    if image.dtype not in (np.dtype("uint8"), np.dtype("uint16")):
        raise ValueError(f"Only uint8/uint16 SDR samples are supported; {path} is {image.dtype}")
    maximum = float(np.iinfo(image.dtype).max)
    if image.ndim == 2:
        image = image[:, :, None]
    channels = image.shape[2]
    normalized = image.astype(np.float32) / maximum
    if channels == 1:
        rgb = np.repeat(normalized, 3, axis=2)
        alpha = None
    elif channels == 2:  # Rare grayscale+alpha decoder output.
        rgb = np.repeat(normalized[:, :, :1], 3, axis=2)
        alpha = normalized[:, :, 1]
    elif channels == 3:
        rgb = normalized[:, :, ::-1].copy()  # BGR -> RGB
        alpha = None
    elif channels == 4:
        rgb = normalized[:, :, [2, 1, 0]]
        alpha = normalized[:, :, 3]
    else:
        raise ValueError(f"Unsupported channel count ({channels}) in {path}")
    h, w = rgb.shape[:2]
    return LoadedImage(rgb, alpha, w, h, int(maximum).bit_length(), channels,
                       path.stat().st_size, str(path))


def render_rgb(image: LoadedImage, alpha_mode: str, background: str) -> np.ndarray:
    rgb = image.rgb
    if image.alpha is not None and alpha_mode == "composite":
        bg = 1.0 if background == "white" else 0.0
        alpha = image.alpha[:, :, None]
        rgb = rgb * alpha + bg * (1.0 - alpha)
    return np.ascontiguousarray(rgb, dtype=np.float32)


def luminance(rgb: np.ndarray) -> np.ndarray:
    """BT.601 luma Y' calculated on gamma-encoded R'G'B', not linear light."""
    return (BT601[0] * rgb[:, :, 0] + BT601[1] * rgb[:, :, 1]
            + BT601[2] * rgb[:, :, 2]).astype(np.float32)


def psnr_from_mse(mse: float) -> Optional[float]:
    """None encodes +infinity in strict JSON output; zero MSE is perfect."""
    if mse == 0.0:
        return None
    return float(-10.0 * math.log10(mse))  # Data range is normalized to 1.


def _valid_interior(mask: np.ndarray) -> np.ndarray:
    valid = np.zeros(mask.shape, dtype=bool)
    if min(mask.shape) < 11:
        return valid
    valid[5:-5, 5:-5] = True
    if not np.all(mask):
        eroded = cv2.erode(mask.astype(np.uint8), np.ones((11, 11), np.uint8))
        valid &= eroded.astype(bool)
    return valid


def ssim_maps(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Wang-style Gaussian SSIM and contrast-structure components on [0,1].

    Uses 11x11 Gaussian (sigma=1.5), population covariance, K1=.01, K2=.03.
    Discards 5px boundaries when averaging, per common SSIM implementations.
    """
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    blur = lambda x: cv2.GaussianBlur(x, (11, 11), 1.5,
                                      borderType=cv2.BORDER_REFLECT_101)
    mu_a, mu_b = blur(a), blur(b)
    aa, bb, ab = mu_a * mu_a, mu_b * mu_b, mu_a * mu_b
    sigma_a = np.maximum(blur(a * a) - aa, 0.0)
    sigma_b = np.maximum(blur(b * b) - bb, 0.0)
    cov = blur(a * b) - ab
    c1, c2 = 0.01**2, 0.03**2
    contrast_structure = (2 * cov + c2) / (sigma_a + sigma_b + c2)
    ssim = ((2 * ab + c1) / (aa + bb + c1)) * contrast_structure
    return ssim, contrast_structure


def mean_ssim(a: np.ndarray, b: np.ndarray,
              mask: np.ndarray) -> tuple[Optional[float], Optional[np.ndarray], Optional[float]]:
    valid = _valid_interior(mask)
    if not np.any(valid):
        return None, None, None
    smap, cmap = ssim_maps(a, b)
    score = float(np.clip(np.mean(smap[valid], dtype=np.float64), -1.0, 1.0))
    cs_score = float(np.mean(cmap[valid], dtype=np.float64))
    return score, smap, cs_score


def multiscale_ssim_y(y1: np.ndarray, y2: np.ndarray,
                       mask: np.ndarray) -> Optional[float]:
    """5-scale luminance MS-SSIM; returns None for images <176 px on a side.

    Standard weights and Gaussian SSIM/CS formula. Downsampling via pyrDown.
    Masked borders are excluded from scores, then downsampled conservatively.
    """
    if min(y1.shape) < 176:
        return None
    components: list[float] = []
    for level, weight in enumerate(MS_SSIM_WEIGHTS):
        score, _, cs = mean_ssim(y1, y2, mask)
        if score is None or cs is None:
            return None
        components.append(max(0.0, min(1.0, score if level == 4 else cs)) ** weight)
        if level != 4:
            y1 = cv2.pyrDown(y1)
            y2 = cv2.pyrDown(y2)
            # A downsampled pixel is considered valid only when its 2x2
            # source footprint is valid; SSIM excludes further 5px margins.
            small = cv2.resize(mask.astype(np.float32),
                               (y1.shape[1], y1.shape[0]),
                               interpolation=cv2.INTER_AREA)
            mask = small >= 1.0 - 1e-7
    return float(math.prod(components))


def align_candidate(reference: np.ndarray, candidate: np.ndarray,
                    mode: str) -> tuple[np.ndarray, np.ndarray, Optional[dict[str, Any]]]:
    h, w = reference.shape[:2]
    valid = np.ones((h, w), dtype=bool)
    if mode == "none":
        return candidate, valid, None
    if min(h, w) < 32:
        raise ValueError("ECC alignment requires images at least 32x32")
    modes = {"translation": cv2.MOTION_TRANSLATION,
             "euclidean": cv2.MOTION_EUCLIDEAN,
             "affine": cv2.MOTION_AFFINE}
    warp = np.eye(2, 3, dtype=np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 150, 1e-6)
    try:
        corr, warp = cv2.findTransformECC(luminance(reference),
                                          luminance(candidate), warp,
                                          modes[mode], criteria)
    except cv2.error as exc:
        raise ValueError("ECC alignment failed to converge; compare unaligned "
                         "images or use a different alignment mode") from exc
    flags = cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP
    aligned = cv2.warpAffine(candidate, warp, (w, h), flags=flags,
                             borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
    # Include only pixels with a complete interpolation footprint.
    validity = np.ones((h, w), dtype=np.uint8)
    valid = cv2.warpAffine(validity, warp, (w, h), flags=flags,
                            borderMode=cv2.BORDER_CONSTANT) == 1
    valid = cv2.erode(valid.astype(np.uint8),
                      np.ones((3, 3), np.uint8)).astype(bool)
    return aligned, valid, {"ecc_correlation": float(corr),
                            "warp_matrix": warp.tolist(),
                            "valid_fraction": float(valid.mean())}


def calculate_metrics(reference: np.ndarray, candidate: np.ndarray,
                      mask: Optional[np.ndarray] = None,
                      tolerance_8bit: float = 0.0,
                      include_maps: bool = False) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    """Full-reference assessment on RGB float32 arrays in [0,1]."""
    if reference.shape != candidate.shape or reference.ndim != 3 or reference.shape[2] != 3:
        raise ValueError(f"Expected identical HxWx3 image arrays: {reference.shape} vs {candidate.shape}")
    if not np.isfinite(reference).all() or not np.isfinite(candidate).all():
        raise ValueError("Images contain NaN or infinite samples")
    if np.min(reference) < 0 or np.max(reference) > 1 or np.min(candidate) < 0 or np.max(candidate) > 1:
        raise ValueError("Image samples must be in [0,1]")
    h, w = reference.shape[:2]
    if mask is None:
        mask = np.ones((h, w), dtype=bool)
    if mask.shape != (h, w) or mask.dtype != bool or not mask.any():
        raise ValueError("The validity mask must be boolean, match HxW, and contain valid pixels")
    if tolerance_8bit < 0:
        raise ValueError("Tolerance cannot be negative")

    diff = reference.astype(np.float64) - candidate.astype(np.float64)
    included = diff[mask]  # Nx3
    abs_diff = np.abs(included)
    mse = float(np.mean(np.square(included)))
    mae = float(np.mean(abs_diff))
    max_abs = float(np.max(abs_diff))
    changed = np.max(abs_diff, axis=1) > (tolerance_8bit / 255.0)
    y1, y2 = luminance(reference), luminance(candidate)
    luma_diff = (y1.astype(np.float64) - y2.astype(np.float64))[mask]
    y_mse = float(np.mean(np.square(luma_diff)))

    rgb_ssim_by_channel: dict[str, Optional[float]] = {}
    for idx, channel_name in enumerate("RGB"):
        result, _, _ = mean_ssim(reference[:, :, idx], candidate[:, :, idx], mask)
        rgb_ssim_by_channel[channel_name] = result
    ssim_rgb = (float(np.mean(list(rgb_ssim_by_channel.values())))
                if all(v is not None for v in rgb_ssim_by_channel.values()) else None)
    ssim_y, y_ssim_map, _ = mean_ssim(y1, y2, mask)
    ms_ssim_y = multiscale_ssim_y(y1, y2, mask)

    # CIELAB conversion requires nonlinear sRGB floats in range [0,1].
    lab1 = cv2.cvtColor(reference, cv2.COLOR_RGB2LAB).astype(np.float64)
    lab2 = cv2.cvtColor(candidate, cv2.COLOR_RGB2LAB).astype(np.float64)
    delta_e = np.linalg.norm(lab1 - lab2, axis=2)

    # Edge/texture error: compare gradient magnitudes of luminance.
    def gradient_magnitude(a: np.ndarray) -> np.ndarray:
        dx = cv2.Sobel(a, cv2.CV_32F, 1, 0, ksize=3) / 4.0
        dy = cv2.Sobel(a, cv2.CV_32F, 0, 1, ksize=3) / 4.0
        return cv2.magnitude(dx, dy)
    grad_error = (np.zeros_like(y1) if np.array_equal(y1, y2) else
                  np.abs(gradient_magnitude(y1) - gradient_magnitude(y2)))

    channel_mse = np.mean(np.square(included), axis=0)
    metrics: dict[str, Any] = {
        "width": w,
        "height": h,
        "valid_pixels": int(mask.sum()),
        "valid_fraction": float(mask.mean()),
        "identical_in_valid_area": bool(np.all(included == 0)),
        "rgb_mse_normalized": mse,
        "rgb_mse_8bit_equivalent": mse * 255.0**2,
        "rgb_rmse_normalized": math.sqrt(mse),
        "rgb_mae_normalized": mae,
        "rgb_mae_8bit_equivalent": mae * 255.0,
        "max_absolute_error_8bit_equivalent": max_abs * 255.0,
        "rgb_psnr_db": psnr_from_mse(mse),
        "luma_psnr_db": psnr_from_mse(y_mse),
        "rgb_ssim": ssim_rgb,
        "luma_ssim": ssim_y,
        "luma_ms_ssim_5_scale": ms_ssim_y,
        "mean_delta_e_76": float(delta_e[mask].mean()),
        "p95_delta_e_76": float(np.percentile(delta_e[mask], 95)),
        "luma_gradient_magnitude_mae": float(grad_error[mask].mean()),
        "changed_pixel_percent": float(100.0 * np.mean(changed)),
        "changed_pixel_tolerance_8bit": float(tolerance_8bit),
        "channel_psnr_db": {key: psnr_from_mse(float(channel_mse[i]))
                            for i, key in enumerate("RGB")},
        "channel_ssim": rgb_ssim_by_channel,
    }
    maps: dict[str, np.ndarray] = {}
    if include_maps:
        maps["absolute_error_rgb"] = np.abs(reference - candidate)
        if y_ssim_map is not None:
            maps["luma_ssim"] = y_ssim_map
    return metrics, maps



@lru_cache(maxsize=1)
def _get_lpips_model():
    """Load pretrained LPIPS on CPU on demand. May need a one-time weight download."""
    try:
        import torch
        import lpips
    except ImportError as exc:
        raise ValueError("LPIPS is optional: install it with 'pip install torch lpips' "
                         "and rerun with --lpips") from exc
    model = lpips.LPIPS(net="alex", verbose=False)
    model.eval()
    return model, torch


def calculate_lpips(reference: np.ndarray, candidate: np.ndarray,
                    mask: np.ndarray, max_side: int) -> tuple[Optional[float], dict[str, Any]]:
    """AlexNet LPIPS (lower is better), standardized to [0,1] RGB inputs."""
    if max_side < 64:
        raise ValueError("--lpips-max-side must be at least 64")
    h, w = reference.shape[:2]
    if min(h, w) < 64:
        return None, {"note": "LPIPS requires both dimensions >=64 px"}
    model, torch = _get_lpips_model()
    if not np.all(mask):
        # Avoid penalizing ECC-alignment border fill. Convolutions near the
        # boundary can still depend on fill, so note non-standard masking.
        reference = np.where(mask[:, :, None], reference, 0.5)
        candidate = np.where(mask[:, :, None], candidate, 0.5)
    scale = min(1.0, max_side / max(h, w))
    # Preserve aspect ratio; never force a thin dimension to exactly 64px
    # independently of the other dimension.
    scale = min(1.0, max(scale, 64.0 / min(h, w)))
    if scale != 1.0:
        new_size = (max(64, round(w * scale)), max(64, round(h * scale)))
        reference = cv2.resize(reference, new_size, interpolation=cv2.INTER_AREA)
        candidate = cv2.resize(candidate, new_size, interpolation=cv2.INTER_AREA)
    a = torch.from_numpy(np.ascontiguousarray(reference.transpose(2, 0, 1))).float()[None]
    b = torch.from_numpy(np.ascontiguousarray(candidate.transpose(2, 0, 1))).float()[None]
    with torch.no_grad():
        score = model(a, b, normalize=True).item()
    return float(score), {"backbone": "alex", "max_side": max_side,
                          "evaluated_width": int(reference.shape[1]),
                          "evaluated_height": int(reference.shape[0]),
                          "masked_fill_applied": bool(not np.all(mask)),
                          "lower_is_better": True}


def mark_pareto_by_psnr(results: list[dict[str, Any]]) -> int:
    """Mark rate-distortion Pareto candidates (min bytes, max RGB PSNR)."""
    ranked = sorted(results, key=lambda r: r["candidate_file_bytes"])
    best_better_size = -math.inf
    frontier = 0
    for size, group in itertools.groupby(ranked, key=lambda r: r["candidate_file_bytes"]):
        group_items = list(group)
        max_quality_same_size = max(
            math.inf if item["metrics"]["rgb_psnr_db"] is None else
            item["metrics"]["rgb_psnr_db"] for item in group_items)
        for item in group_items:
            quality = (math.inf if item["metrics"]["rgb_psnr_db"] is None else
                       item["metrics"]["rgb_psnr_db"])
            optimal = quality == max_quality_same_size and quality > best_better_size
            item["pareto_optimal_psnr_vs_file_size"] = optimal
            frontier += int(optimal)
        best_better_size = max(best_better_size, max_quality_same_size)
    return frontier


def write_png(path: Path, pixels: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(".png", pixels)
    if not ok:
        raise OSError(f"Unable to encode {path}")
    encoded.tofile(str(path))


def save_visualizations(ref: np.ndarray, cand: np.ndarray,
                        mask: np.ndarray, maps: dict[str, np.ndarray],
                        destination: Path) -> dict[str, Any]:
    """Write lossless image maps and an overview; auto-scaled heatmap noted."""
    destination.mkdir(parents=True, exist_ok=True)
    err = np.mean(maps["absolute_error_rgb"], axis=2)
    max_error = float(np.percentile(err[mask], 99.5))
    scale = max(max_error, 1.0 / 65535.0)
    heat = np.uint8(np.clip(err / scale * 255, 0, 255))
    heat_bgr = cv2.applyColorMap(heat, cv2.COLORMAP_TURBO)
    heat_bgr[~mask] = 0
    write_png(destination / "error_heatmap.png", heat_bgr)

    # A fixed 4x gain makes small differences easier to see than raw abs diff.
    amplified_rgb = np.uint8(np.clip(maps["absolute_error_rgb"] * (255 * 4), 0, 255))
    amplified_rgb[~mask] = 0
    write_png(destination / "difference_x4.png", cv2.cvtColor(amplified_rgb, cv2.COLOR_RGB2BGR))

    ref8 = np.uint8(np.clip(np.round(ref * 255), 0, 255))
    cmp8 = np.uint8(np.clip(np.round(cand * 255), 0, 255))
    montage_rgb = np.concatenate((ref8, cmp8, heat_bgr[:, :, ::-1]), axis=1)
    montage_bgr = cv2.cvtColor(montage_rgb, cv2.COLOR_RGB2BGR)
    for i, caption in enumerate(("Reference", "Candidate", "Error heatmap")):
        px = i * ref.shape[1] + 12
        cv2.putText(montage_bgr, caption, (px, 27), cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(montage_bgr, caption, (px, 27), cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, (255, 255, 255), 1, cv2.LINE_AA)
    write_png(destination / "comparison.png", montage_bgr)

    if "luma_ssim" in maps:
        loss = np.clip((1 - maps["luma_ssim"]) / 2, 0, 1)
        loss_bgr = cv2.applyColorMap(np.uint8(loss * 255), cv2.COLORMAP_TURBO)
        loss_bgr[~mask] = 0
        write_png(destination / "ssim_loss_map.png", loss_bgr)
    return {"directory": str(destination), "error_heatmap_scale_normalized": scale,
            "heatmap_scale": "99.5th percentile of mean RGB absolute error",
            "difference_magnification": 4}


def compare(reference_path: Path, candidate_path: Path,
            *, resize: bool = False, align: str = "none",
            alpha_mode: str = "composite", background: str = "white",
            roi: Optional[Sequence[int]] = None, tolerance: float = 0.0,
            visuals_dir: Optional[Path] = None,
            use_lpips: bool = False, lpips_max_side: int = 1024) -> dict[str, Any]:
    a = read_image(reference_path)
    b = read_image(candidate_path)
    reference = render_rgb(a, alpha_mode, background)
    candidate = render_rgb(b, alpha_mode, background)
    changes: list[str] = []
    if reference.shape != candidate.shape:
        if not resize:
            raise ValueError(f"Dimensions differ: reference={a.width}x{a.height}, "
                             f"candidate={b.width}x{b.height}; use --resize explicitly")
        interpolation = cv2.INTER_AREA if (b.width > a.width or b.height > a.height) else cv2.INTER_LANCZOS4
        candidate = cv2.resize(candidate, (a.width, a.height), interpolation=interpolation)
        candidate = np.clip(candidate, 0, 1).astype(np.float32)
        changes.append("Candidate resized to reference; scores are resampling-dependent")
    candidate, mask, alignment = align_candidate(reference, candidate, align)
    if alignment is not None:
        changes.append("ECC alignment applied; invalid boundary pixels excluded from metrics")
    if roi is not None:
        x, y, width, height = roi
        if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > a.width or y + height > a.height:
            raise ValueError(f"ROI x,y,w,h={roi} lies outside reference {a.width}x{a.height}")
        reference = reference[y:y+height, x:x+width, :].copy()
        candidate = candidate[y:y+height, x:x+width, :].copy()
        mask = mask[y:y+height, x:x+width].copy()
        changes.append(f"Metrics restricted to ROI {x},{y},{width},{height}")
    metrics, maps = calculate_metrics(reference, candidate, mask, tolerance,
                                    include_maps=visuals_dir is not None)
    result: dict[str, Any] = {
        "reference": a.path, "candidate": b.path,
        "reference_file_bytes": a.file_size_bytes,
        "candidate_file_bytes": b.file_size_bytes,
        "candidate_size_percent_of_reference": 100 * b.file_size_bytes / a.file_size_bytes,
        "storage_saving_percent": 100 * (1 - b.file_size_bytes / a.file_size_bytes),
        "reference_bit_depth": a.bit_depth,
        "candidate_bit_depth": b.bit_depth,
        "reference_channels": a.channels,
        "candidate_channels": b.channels,
        "alpha_mode": alpha_mode,
        "background": background if alpha_mode == "composite" else None,
        "alignment": alignment,
        "processing_notes": changes,
        "metrics": metrics,
    }
    if use_lpips:
        value, details = calculate_lpips(reference, candidate, mask, lpips_max_side)
        result["metrics"]["lpips_alex"] = value
        result["lpips_details"] = details
    if visuals_dir is not None:
        result["visualizations"] = save_visualizations(reference, candidate, mask,
                                                       maps, visuals_dir)
    return result


def discover_pairs(originals: Path, candidates: Path, recursive: bool
                  ) -> tuple[list[tuple[Path, Path, Path]], list[dict[str, str]]]:
    """Match files by relative filename, then by unique relative stem."""
    walker = originals.rglob("*") if recursive else originals.glob("*")
    source_files = sorted(p for p in walker if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)
    if not source_files:
        raise ValueError(f"No supported images found in {originals}")
    pairs: list[tuple[Path, Path, Path]] = []
    errors: list[dict[str, str]] = []
    for source in source_files:
        rel = source.relative_to(originals)
        exact = candidates / rel
        if exact.is_file():
            target = exact
        else:
            parent = candidates / rel.parent
            choices = sorted(p for p in parent.glob("*") if p.is_file()
                             and p.stem.casefold() == source.stem.casefold()
                             and p.suffix.lower() in IMAGE_SUFFIXES) if parent.is_dir() else []
            if len(choices) != 1:
                issue = "No matching candidate" if not choices else "Ambiguous matching candidates"
                errors.append({"reference": str(source), "error": issue})
                continue
            target = choices[0]
        pairs.append((source, target, rel))
    return pairs, errors


def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in data.items():
        full = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(_flatten(value, full + "."))
        elif isinstance(value, (list, tuple)):
            flat[full] = json.dumps(value, ensure_ascii=False)
        else:
            flat[full] = value
    return flat


def write_report(path: Path, items: list[dict[str, Any]],
                 errors: list[dict[str, str]]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    report = {"tool": "Image Fidelity Lab", "version": __version__,
              "psnr_infinite_encoded_as_null": True,
              "results": items, "errors": errors}
    (path / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2,
                                                   allow_nan=False), encoding="utf-8")
    rows = [_flatten(item) for item in items]
    if rows:
        fields = sorted({field for row in rows for field in row})
        with (path / "results.csv").open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)


def pretty(value: Optional[float], digits: int = 4) -> str:
    return "+infinity (identical)" if value is None else f"{value:.{digits}f}"


def report_to_console(result: dict[str, Any]) -> None:
    m = result["metrics"]
    print(f"\n{Path(result['reference']).name} -> {Path(result['candidate']).name}")
    print(f"  Pixels evaluated : {m['valid_pixels']:,} / {m['width'] * m['height']:,}")
    print(f"  RGB PSNR         : {pretty(m['rgb_psnr_db'])} dB")
    print(f"  Luma PSNR        : {pretty(m['luma_psnr_db'])} dB")
    print(f"  RGB SSIM         : {pretty(m['rgb_ssim'])}")
    print(f"  Luma SSIM        : {pretty(m['luma_ssim'])}")
    print(f"  Luma MS-SSIM     : {pretty(m['luma_ms_ssim_5_scale']) if m['luma_ms_ssim_5_scale'] is not None else 'N/A (needs >=176x176)'}")
    print(f"  RGB MSE [0,1]    : {m['rgb_mse_normalized']:.9f}")
    print(f"  CIE Delta E 1976 : {m['mean_delta_e_76']:.4f} (mean)")
    print(f"  Changed pixels   : {m['changed_pixel_percent']:.2f}%")
    print(f"  File saving      : {result['storage_saving_percent']:+.2f}%")
    if "lpips_alex" in m:
        print(f"  LPIPS (AlexNet)  : {m['lpips_alex']:.5f}" if m['lpips_alex'] is not None else
              "  LPIPS (AlexNet)  : N/A (image too small)")
    for note in result["processing_notes"]:
        print(f"  WARNING          : {note}")


def run(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare reference and candidate images with PSNR, SSIM, MS-SSIM, Delta E and visual error maps.")
    parser.add_argument("reference", type=Path, help="Reference image or directory")
    parser.add_argument("candidate", type=Path, help="Candidate image or directory")
    parser.add_argument("--output-dir", type=Path, help="Write JSON/CSV results to this directory")
    parser.add_argument("--visualize", action="store_true", help="Save comparison montage and error maps (requires --output-dir)")
    parser.add_argument("--recursive", action="store_true", help="Recurse into subdirectories for directory comparisons")
    parser.add_argument("--sweep", action="store_true", help="Compare one reference file with every image in candidate directory; mark rate-distortion Pareto frontier")
    parser.add_argument("--lpips", action="store_true", help="Optional pretrained AlexNet LPIPS (pip install torch lpips); may download model weights")
    parser.add_argument("--lpips-max-side", type=int, default=1024, help="Resize LPIPS inputs to at most this dimension (default 1024)")
    parser.add_argument("--resize", action="store_true", help="Explicitly resize candidate to reference dimensions")
    parser.add_argument("--align", choices=("none", "translation", "euclidean", "affine"), default="none")
    parser.add_argument("--alpha-mode", choices=("composite", "ignore"), default="composite")
    parser.add_argument("--background", choices=("white", "black"), default="white")
    parser.add_argument("--roi", type=int, nargs=4, metavar=("X", "Y", "WIDTH", "HEIGHT"))
    parser.add_argument("--tolerance", type=float, default=0.0,
                        help="Tolerance for changed-pixel percentage in 8-bit code levels (default: 0)")
    parser.add_argument("--min-psnr", type=float, help="Fail with exit status 2 below this RGB PSNR in dB")
    parser.add_argument("--min-ssim", type=float, help="Fail with exit status 2 below this RGB SSIM")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    if args.tolerance < 0 or (args.min_ssim is not None and not -1 <= args.min_ssim <= 1):
        parser.error("--tolerance must be >=0 and --min-ssim must be in [-1,1]")
    if args.visualize and args.output_dir is None:
        parser.error("--visualize requires --output-dir")
    if args.sweep:
        if not (args.reference.is_file() and args.candidate.is_dir()):
            parser.error("--sweep requires a reference FILE and a candidate DIRECTORY")
    elif args.reference.is_dir() != args.candidate.is_dir():
        parser.error("reference and candidate must both be files or both directories")
    if args.lpips and args.lpips_max_side < 64:
        parser.error("--lpips-max-side must be >=64")
    if not args.reference.exists() or not args.candidate.exists():
        parser.error("reference and candidate must exist")
    try:
        if args.sweep:
            walker = args.candidate.rglob("*") if args.recursive else args.candidate.glob("*")
            candidates = sorted(p for p in walker if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)
            if not candidates:
                raise ValueError(f"No supported candidate images found in {args.candidate}")
            pairs = [(args.reference, target, target.relative_to(args.candidate)) for target in candidates]
            errors = []
        elif args.reference.is_dir():
            pairs, errors = discover_pairs(args.reference, args.candidate, args.recursive)
        else:
            pairs = [(args.reference, args.candidate, Path(args.reference.name))]
            errors = []
        results: list[dict[str, Any]] = []
        gate_failed = False
        for source, target, relative in pairs:
            try:
                visuals = None
                if args.visualize:
                    visuals = args.output_dir / "visuals" / relative.parent / relative.name
                result = compare(source, target, resize=args.resize, align=args.align,
                                 alpha_mode=args.alpha_mode, background=args.background,
                                 roi=args.roi, tolerance=args.tolerance,
                                 visuals_dir=visuals, use_lpips=args.lpips,
                                 lpips_max_side=args.lpips_max_side)
                results.append(result)
                if not args.quiet:
                    report_to_console(result)
                m = result["metrics"]
                if args.min_psnr is not None and m["rgb_psnr_db"] is not None and m["rgb_psnr_db"] < args.min_psnr:
                    gate_failed = True
                    print(f"QUALITY GATE FAILED: {source} RGB PSNR < {args.min_psnr}", file=sys.stderr)
                if args.min_ssim is not None and (m["rgb_ssim"] is None or m["rgb_ssim"] < args.min_ssim):
                    gate_failed = True
                    print(f"QUALITY GATE FAILED: {source} RGB SSIM < {args.min_ssim}", file=sys.stderr)
            except (OSError, ValueError, cv2.error) as exc:
                errors.append({"reference": str(source), "candidate": str(target), "error": str(exc)})
                print(f"ERROR: {source}: {exc}", file=sys.stderr)
        for error in errors:
            if "candidate" not in error:
                print(f"ERROR: {error['reference']}: {error['error']}", file=sys.stderr)
        if args.sweep and results:
            count = mark_pareto_by_psnr(results)
            if not args.quiet:
                print(f"Pareto-efficient candidates (file size vs RGB PSNR): {count} / {len(results)}")
        if args.output_dir is not None:
            write_report(args.output_dir, results, errors)
            if not args.quiet:
                print(f"\nReports saved to {args.output_dir.resolve()}")
        if len(pairs) > 1 or args.reference.is_dir() or args.sweep:
            print(f"Finished: {len(results)} comparisons, {len(errors)} errors")
        return 1 if errors or not results else (2 if gate_failed else 0)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(run())
