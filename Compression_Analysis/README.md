# Image Fidelity Lab

A reproducible full-reference image quality evaluator for Python 3.9+ using **NumPy + OpenCV**, evolving a simple grayscale-PSNR comparison into a quality-analysis, visualization, and compression-optimization tool.

## Installation

```bash
python -m pip install numpy opencv-python
```

Optional perceptual-network scoring (downloads/prepares pretrained weights on first use as needed):

```bash
python -m pip install torch lpips
```

No GPU, models, or network connection are required for the core functionality. To verify:

```bash
python -m unittest -v test_image_fidelity_lab.py
```

## Quick start

```bash
python image_fidelity_lab.py original.png compressed.jpg
python image_fidelity_lab.py original.png compressed.jpg --output-dir fidelity_reports --visualize
python image_fidelity_lab.py original.png compressed.jpg --min-psnr 35 --min-ssim 0.95
python image_fidelity_lab.py original.png compressed.jpg --align translation --roi 50 50 256 256
python image_fidelity_lab.py originals/ compressed/ --recursive --output-dir batch_report
python image_fidelity_lab.py original.png compressed_variants/ --sweep --output-dir frontier --visualize
python image_fidelity_lab.py original.png compressed.jpg --lpips --output-dir perceptual_results
```

Use `python image_fidelity_lab.py --help` for the complete parameter list.

### Direct Python API

```python
from pathlib import Path
from image_fidelity_lab import compare, calculate_metrics

result = compare(Path("original.png"), Path("compressed.png"))
print(result["metrics"]["rgb_psnr_db"])
print(result["metrics"]["rgb_ssim"])

# For normalized float32 RGB arrays of identical dimensions:
# metrics, optional_maps = calculate_metrics(reference_rgb, candidate_rgb)
```

## Metrics included

| Metric | Field | Interpretation |
| --- | --- | --- |
| RGB PSNR | `rgb_psnr_db` | Larger is better; calculated over all R/G/B samples, 1.0 peak |
| Luma PSNR | `luma_psnr_db` | Larger is better; uses BT.601 Y' = .299 R' + .587 G' + .114 B' |
| RGB MSE | `rgb_mse_normalized` | Smaller is better, on normalized 0–1 samples |
| RGB MSE, 8-bit equiv. | `rgb_mse_8bit_equivalent` | Normalized RGB MSE multiplied by 255² |
| RGB MAE | `rgb_mae_normalized` | Smaller is better |
| RGB SSIM | `rgb_ssim` | Larger is better; average of SSIM per RGB channel |
| Luma SSIM | `luma_ssim` | Larger is better; one luminance plane |
| 5-scale luma MS-SSIM | `luma_ms_ssim_5_scale` | Larger is better; only for images >=176×176 |
| CIE ΔE76 mean / P95 | `mean_delta_e_76`, `p95_delta_e_76` | Smaller is better; color difference; **not** ΔE2000 |
| Edge gradient magnitude MAE | `luma_gradient_magnitude_mae` | Smaller is better; detects edge/texture degradation |
| Changed pixels | `changed_pixel_percent` | Pixels with any RGB channel difference greater than tolerance |
| Per-channel PSNR/SSIM | `channel_psnr_db`, `channel_ssim` | Identify channel-specific losses |
| File size | `storage_saving_percent` | Positive when candidate file contains fewer bytes |
| Optional LPIPS (AlexNet) | `lpips_alex` | Smaller is typically better; learned perceptual differences |

SSIM uses 11×11 Gaussian weighting (sigma=1.5), population covariance, and a 5-pixel border exclusion; this tracks the Wang-style configuration described by scikit-image. Five-scale MS-SSIM uses the standard 5 weights and Gaussian pyramid reduction. The specific resizing, mask, and implementation can still produce differences from other libraries.

**PSNR of identical compared pixels is +infinity.** For strict JSON compatibility, `null` represents +infinity here, with `identical_in_valid_area: true`. `null` also occurs for unavailable SSIM/MS-SSIM/LPIPS, so check the matching availability field or condition before treating it as infinity.

## Output files

`--output-dir DIR` creates:

- `results.json`: structured metadata, dimensions, RGB/luma scores, processing warnings, errors, optional Pareto flags.
- `results.csv`: a flattened table suitable for experiments, spreadsheets, and plots.
- With `--visualize`: `visuals/<reference-or-candidate-filename>/comparison.png` (reference | candidate | error heatmap), `difference_x4.png`, `error_heatmap.png`, `ssim_loss_map.png` when supported.

The heatmap auto-scales to the 99.5th percentile of mean absolute RGB error and **is not directly comparable in visual intensity between different image pairs**. The actual heatmap scale is included in JSON. `difference_x4.png` uses fixed 4× amplification and clips at white.

For directory-to-directory processing, source and candidate files are matched first by relative path, then by a unique same-stem file in the corresponding destination directory. Different file extensions may therefore be compared. `--recursive` enables subdirectory discovery.

## Compression sweep and Pareto frontier

Use one original against a directory of JPEG/PNG/WebP/etc. alternatives:

```bash
python image_fidelity_lab.py reference.png candidate_images/ --sweep --output-dir sweep_report
```

The resulting CSV includes `pareto_optimal_psnr_vs_file_size`. A candidate is efficient if no other candidate has a smaller/equal byte size with an equal/better RGB PSNR and at least one strict improvement. The comparison considers actual encoded file bytes (including container overhead), not encoder bitstream alone.

## Validation and CI

Use gates to detect image-quality regressions:

```bash
python image_fidelity_lab.py gold.png output.webp --min-psnr 35 --min-ssim 0.93
```

Exit status: `0` = success, `1` = invalid input/comparison errors, `2` = quality gate failed. This can be used in a graphics regression-test pipeline. There is no universally valid PSNR/SSIM threshold: calibrate against your assets and visual review.

## Alignment, alpha, and resizing: important assumptions

- Matching dimensions are required by default. `--resize` resamples the **candidate** to the reference dimensions; score changes also reflect interpolation.
- `--align translation|euclidean|affine` runs OpenCV ECC optimization. It can fail to converge, and it excludes warped border pixels. Alignment changes what is being measured; usually **do not align** exact pixelwise compression comparisons.
- RGBA images are by default composited over white before evaluation. `--background black` selects black, and `--alpha-mode ignore` ignores alpha and includes hidden RGB. Alpha itself is **not** separately scored.
- `--roi X Y WIDTH HEIGHT` evaluates a user-specified rectangular region after registration/resizing.
- `--tolerance N` defines only the changed-pixel statistic (in 8-bit code-value equivalents); it does not change PSNR, SSIM, or ΔE.
- LPIPS is opt-in via `--lpips`, runs on CPU, and can trigger a one-time model weight download. It downsizes longer sides above `--lpips-max-side` (default 1024), so those scores reflect the resized input. If ECC alignment leaves invalid pixels, LPIPS fills them identically with gray; convolution near the mask boundary can affect the score.

## Methodological boundaries

1. Measurements operate on the supplied files as gamma-encoded, normalized **sRGB-like SDR samples**. There is no ICC profile conversion, scene-linear radiance evaluation, HDR support, or explicit video colorimetry conversion. Only uint8/uint16 inputs are supported. For scientific/production colour pipelines, linear-light and calibrated color-managed analyses can be more appropriate.
2. The engine uses complete decoded image arrays, so memory usage increases with image resolution (4K/8K can require substantial RAM). It is not a streaming codec or tiled out-of-core implementation.
3. CIE ΔE76 is an older, convenient color-space distance; it is not perceptually uniform in all regions. LPIPS, PSNR, SSIM, and MS-SSIM are not guaranteed to predict human judgments for arbitrary content or tasks.
4. Scores from differently sized masks, ROI, alpha compositing, interpolation, or LPIPS scale settings **should not be interpreted as directly equivalent**.
5. A higher PSNR does not automatically mean a better visual rendering, sharper texture, or better compression experience.

## Research and documentation

- Wang et al. (2004), *Image Quality Assessment: From Error Visibility to Structural Similarity*: https://ece.uwaterloo.ca/~z70wang/publications/ssim.pdf
- scikit-image `structural_similarity` documentation (Gaussian weighting and data ranges): https://scikit-image.org/docs/stable/api/skimage.metrics.html
- OpenCV ECC spatial registration: https://docs.opencv.org/4.x/dc/d6b/group__video__track.html
- Zhang et al. (2018), *The Unreasonable Effectiveness of Deep Features as a Perceptual Metric* (LPIPS): https://openaccess.thecvf.com/content_cvpr_2018/html/Zhang_The_Unreasonable_Effectiveness_CVPR_2018_paper.html
- Breger et al. (2025), *A Study of Why We Need to Reassess Full Reference Image Quality Assessment with Medical Images*: https://link.springer.com/article/10.1007/s10278-025-01462-1

MIT or other licensing is not automatically asserted; adapt licensing to your own repository policy.
