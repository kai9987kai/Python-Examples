"""Unit and integration regression checks for Image Fidelity Lab.
Run: python -m unittest -v test_image_fidelity_lab.py
"""
import json
import math
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from image_fidelity_lab import (calculate_metrics, compare, discover_pairs,
                                luminance, mean_ssim, multiscale_ssim_y,
                                read_image, run, write_report, mark_pareto_by_psnr)


class ImageFidelityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        rng = np.random.default_rng(42)
        self.rgb = rng.integers(0, 256, (256, 256, 3), dtype=np.uint8)
        self.ref = self.root / "reference.png"
        cv2.imwrite(str(self.ref), cv2.cvtColor(self.rgb, cv2.COLOR_RGB2BGR))

    def tearDown(self):
        self.temp.cleanup()

    def test_luminance_uses_correct_green_coefficient(self):
        rgb = np.array([[[0.0, 1.0, 0.0]]], dtype=np.float32)
        self.assertAlmostEqual(float(luminance(rgb)[0, 0]), 0.587, places=6)

    def test_identical_is_infinite_psnr_and_unity_ssim(self):
        img = self.rgb.astype(np.float32) / 255
        metric, _ = calculate_metrics(img, img)
        self.assertIsNone(metric["rgb_psnr_db"])
        self.assertIsNone(metric["luma_psnr_db"])
        self.assertEqual(metric["changed_pixel_percent"], 0.0)
        self.assertTrue(metric["identical_in_valid_area"])
        self.assertAlmostEqual(metric["rgb_ssim"], 1.0, places=5)
        self.assertAlmostEqual(metric["luma_ms_ssim_5_scale"], 1.0, places=5)

    def test_rgb_psnr_matches_opencv_reference(self):
        candidate = np.clip(self.rgb.astype(np.int16) + 8, 0, 255).astype(np.uint8)
        a = self.rgb.astype(np.float32) / 255
        b = candidate.astype(np.float32) / 255
        metric, _ = calculate_metrics(a, b)
        expected = cv2.PSNR(self.rgb, candidate)
        self.assertAlmostEqual(metric["rgb_psnr_db"], expected, places=4)

    def test_rgb_psnr_across_16_bit_conversion(self):
        a = self.rgb.astype(np.float32) / 255
        b16 = (self.rgb.astype(np.uint16) * 257)
        path = self.root / "ref16.png"
        cv2.imwrite(str(path), cv2.cvtColor(b16, cv2.COLOR_RGB2BGR))
        loaded = read_image(path)
        self.assertEqual(loaded.bit_depth, 16)
        metric, _ = calculate_metrics(a, loaded.rgb)
        self.assertLess(metric["rgb_mse_normalized"], 1e-13)

    def test_changed_pixels_with_tolerance(self):
        a = np.zeros((20, 20, 3), dtype=np.float32)
        b = a.copy()
        b[10, 10, 0] = 1 / 255
        metric, _ = calculate_metrics(a, b)
        self.assertAlmostEqual(metric["changed_pixel_percent"], 0.25)
        metric, _ = calculate_metrics(a, b, tolerance_8bit=1.1)
        self.assertEqual(metric["changed_pixel_percent"], 0)

    def test_different_dimensions_are_rejected(self):
        smaller = self.root / "small.png"
        cv2.imwrite(str(smaller), np.zeros((100, 100, 3), dtype=np.uint8))
        with self.assertRaisesRegex(ValueError, "Dimensions differ"):
            compare(self.ref, smaller)
        got = compare(self.ref, smaller, resize=True)
        self.assertTrue(got["processing_notes"])

    def test_small_image_has_unavailable_ssim_not_crash(self):
        a = np.zeros((5, 5, 3), dtype=np.float32)
        score, _ = calculate_metrics(a, a)
        self.assertIsNone(score["rgb_ssim"])
        self.assertIsNone(score["luma_ssim"])
        self.assertIsNone(score["luma_ms_ssim_5_scale"])

    def test_25_pixel_image_has_ssim_but_not_ms_ssim(self):
        a = np.ones((25, 25, 3), dtype=np.float32) * 0.2
        score, _ = calculate_metrics(a, a)
        self.assertAlmostEqual(score["rgb_ssim"], 1.0, places=4)
        self.assertIsNone(score["luma_ms_ssim_5_scale"])

    def test_delta_e_is_zero_on_identical(self):
        a = self.rgb.astype(np.float32) / 255
        score, _ = calculate_metrics(a, a)
        self.assertEqual(score["mean_delta_e_76"], 0)
        self.assertEqual(score["luma_gradient_magnitude_mae"], 0)

    def test_alpha_compositing_ignores_invisible_rgb(self):
        ref = np.zeros((32, 32, 4), dtype=np.uint8)
        candidate = ref.copy()
        candidate[:, :, 0] = 255
        p1, p2 = self.root / "alpha_orig.png", self.root / "alpha_candidate.png"
        cv2.imwrite(str(p1), ref)
        cv2.imwrite(str(p2), candidate)
        result_composite = compare(p1, p2)
        self.assertIsNone(result_composite["metrics"]["rgb_psnr_db"])
        result_ignore = compare(p1, p2, alpha_mode="ignore")
        self.assertIsNotNone(result_ignore["metrics"]["rgb_psnr_db"])

    def test_roi_is_restricted(self):
        candidate = self.rgb.copy()
        candidate[0, 0, :] = 255 - candidate[0, 0, :]
        path = self.root / "roi.png"
        cv2.imwrite(str(path), cv2.cvtColor(candidate, cv2.COLOR_RGB2BGR))
        roi_score = compare(self.ref, path, roi=(32, 32, 128, 128))
        self.assertIsNone(roi_score["metrics"]["rgb_psnr_db"])
        total_score = compare(self.ref, path)
        self.assertIsNotNone(total_score["metrics"]["rgb_psnr_db"])

    def test_visualization_files_are_created(self):
        vis = self.root / "visuals"
        scores = compare(self.ref, self.ref, visuals_dir=vis)
        for name in ("error_heatmap.png", "comparison.png", "difference_x4.png", "ssim_loss_map.png"):
            self.assertTrue((vis / name).is_file(), name)
        self.assertIn("visualizations", scores)

    def test_json_is_valid_with_infinite_psnr(self):
        scores = compare(self.ref, self.ref)
        write_report(self.root / "report", [scores], [])
        with (self.root / "report" / "results.json").open(encoding="utf-8") as fp:
            output = json.load(fp)
        self.assertIsNone(output["results"][0]["metrics"]["rgb_psnr_db"])
        self.assertTrue((self.root / "report" / "results.csv").is_file())

    def test_directory_matching_can_change_extension(self):
        originals = self.root / "originals"
        candidates = self.root / "candidates"
        originals.mkdir()
        candidates.mkdir()
        (originals / "sample.png").write_bytes(b"a")
        (candidates / "sample.webp").write_bytes(b"a")
        pair, issues = discover_pairs(originals, candidates, False)
        self.assertEqual(len(pair), 1)
        self.assertEqual(issues, [])

    def test_cli_quality_gate_detects_damage(self):
        altered = self.root / "black.png"
        cv2.imwrite(str(altered), np.zeros_like(self.rgb))
        self.assertEqual(run([str(self.ref), str(altered), "--quiet", "--min-psnr", "99"]), 2)
        self.assertEqual(run([str(self.ref), str(self.ref), "--quiet", "--min-psnr", "99"]), 0)

    def test_corrupt_file_is_reported_without_abort(self):
        candidate = self.root / "corrupt.png"
        candidate.write_text("no image", encoding="utf-8")
        self.assertEqual(run([str(self.ref), str(candidate), "--quiet"]), 1)

    def test_sweep_marks_pareto_and_exports(self):
        originals = self.root / "candidates"
        originals.mkdir()
        cv2.imwrite(str(originals / "low.jpg"), cv2.cvtColor(self.rgb, cv2.COLOR_RGB2BGR),
                    [cv2.IMWRITE_JPEG_QUALITY, 20])
        cv2.imwrite(str(originals / "high.jpg"), cv2.cvtColor(self.rgb, cv2.COLOR_RGB2BGR),
                    [cv2.IMWRITE_JPEG_QUALITY, 90])
        path = self.root / "sweep_report"
        exit_code = run([str(self.ref), str(originals), "--sweep", "--output-dir",
                         str(path), "--quiet"])
        self.assertEqual(exit_code, 0)
        results = json.loads((path / "results.json").read_text(encoding="utf-8"))["results"]
        self.assertEqual(len(results), 2)
        self.assertTrue(any(r["pareto_optimal_psnr_vs_file_size"] for r in results))

    def test_pareto_frontier_handles_equal_size_ties(self):
        def record(bytes_, psnr):
            return {"candidate_file_bytes": bytes_, "metrics": {"rgb_psnr_db": psnr}}
        cases = [record(100, 20.0), record(100, 20.0),
                 record(150, 19.0), record(180, 25.0), record(200, 24.0)]
        self.assertEqual(mark_pareto_by_psnr(cases), 3)
        self.assertEqual([c["pareto_optimal_psnr_vs_file_size"] for c in cases],
                         [True, True, False, True, False])

    def test_batch_directory_missing_candidate_gives_error(self):
        root = self.root / "originals"
        missing = self.root / "candidates"
        root.mkdir()
        missing.mkdir()
        (root / "sample.png").write_bytes(self.ref.read_bytes())
        self.assertEqual(run([str(root), str(missing), "--quiet"]), 1)

    def test_alignment_improves_translated_image(self):
        # ECC works on an image with sufficiently rich spatial detail.
        shifted = cv2.warpAffine(self.rgb, np.float32([[1, 0, 3], [0, 1, 2]]),
                                 (256, 256), borderMode=cv2.BORDER_CONSTANT)
        path = self.root / "shifted.png"
        cv2.imwrite(str(path), cv2.cvtColor(shifted, cv2.COLOR_RGB2BGR))
        raw = compare(self.ref, path)
        aligned = compare(self.ref, path, align="translation")
        self.assertGreater(aligned["metrics"]["rgb_psnr_db"], raw["metrics"]["rgb_psnr_db"])
        self.assertLess(aligned["metrics"]["valid_fraction"], 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
