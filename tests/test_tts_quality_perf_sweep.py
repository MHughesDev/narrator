"""Tests for scripts/tts_quality_perf_sweep.py."""

from __future__ import annotations

import unittest
from pathlib import Path

import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import tts_quality_perf_sweep as sweep  # noqa: E402


class TestSweepHelpers(unittest.TestCase):
    def test_profile_matrix_contains_expected_variants(self) -> None:
        profiles = sweep._profile_matrix(
            engines=["winrt", "piper", "xtts"],
            xtts_devices=["auto", "cpu"],
            piper_modes=["cpu", "cuda"],
        )
        names = [p.name for p in profiles]
        self.assertIn("winrt-default", names)
        self.assertIn("piper-cpu", names)
        self.assertIn("piper-cuda", names)
        self.assertIn("xtts-auto", names)
        self.assertIn("xtts-cpu", names)

    def test_quality_thresholds_strict_tightens(self) -> None:
        class _Args:
            strict = True
            max_echo = 0.8
            max_overlap = 0.8
            max_clip = 0.5
            max_dropout = 0.9
            max_instability = 0.9
            max_quality_risk = 0.9

        q = sweep._normalize_quality_thresholds(_Args())
        self.assertLessEqual(q["max_echo"], 0.55)
        self.assertLessEqual(q["max_clip"], 0.20)
        self.assertLessEqual(q["max_quality_risk"], 0.55)

    def test_quality_thresholds_non_strict_keeps_values(self) -> None:
        class _Args:
            strict = False
            max_echo = 0.61
            max_overlap = 0.62
            max_clip = 0.23
            max_dropout = 0.44
            max_instability = 0.55
            max_quality_risk = 0.49

        q = sweep._normalize_quality_thresholds(_Args())
        self.assertEqual(q["max_echo"], 0.61)
        self.assertEqual(q["max_overlap"], 0.62)
        self.assertEqual(q["max_clip"], 0.23)
        self.assertEqual(q["max_dropout"], 0.44)
        self.assertEqual(q["max_instability"], 0.55)
        self.assertEqual(q["max_quality_risk"], 0.49)


if __name__ == "__main__":
    unittest.main()
