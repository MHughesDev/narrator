"""Unit tests for scripts/audio_inference_selftest.py."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import audio_inference_selftest as ais  # noqa: E402


class TestTextMetrics(unittest.TestCase):
    def test_normalize_transcript_text(self) -> None:
        s = "Hello, WORLD! 42% sure."
        self.assertEqual(ais.normalize_transcript_text(s), "hello world 42 sure")

    def test_word_error_rate_exact_match(self) -> None:
        m = ais.compute_text_metrics("alpha beta", "alpha beta")
        self.assertEqual(m["word_error_rate"], 0.0)
        self.assertEqual(m["token_recall"], 1.0)
        self.assertEqual(m["token_precision"], 1.0)

    def test_word_error_rate_mismatch(self) -> None:
        m = ais.compute_text_metrics("alpha beta gamma", "alpha")
        self.assertGreater(m["word_error_rate"], 0.0)
        self.assertLess(m["token_recall"], 1.0)

    def test_evaluate_metrics(self) -> None:
        m = {
            "word_error_rate": 0.2,
            "token_recall": 0.8,
            "token_precision": 0.7,
        }
        passed, checks = ais.evaluate_metrics(
            m,
            max_wer=0.3,
            min_token_recall=0.7,
            min_token_precision=0.7,
        )
        self.assertTrue(passed)
        self.assertEqual(len(checks), 3)

        passed2, _ = ais.evaluate_metrics(
            m,
            max_wer=0.1,
            min_token_recall=0.9,
            min_token_precision=0.9,
        )
        self.assertFalse(passed2)


class TestMainFlow(unittest.TestCase):
    def test_main_success_with_expected_text(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            audio_path = Path(td) / "fixture.wav"
            json_path = Path(td) / "report.json"
            audio_path.write_bytes(b"fakewav")

            argv = [
                "audio_inference_selftest.py",
                "--audio-path",
                str(audio_path),
                "--expected-text",
                "zero",
                "--json-out",
                str(json_path),
            ]
            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(ais, "transcribe_audio_fixture", return_value="zero"),
            ):
                rc = ais.main()

            self.assertEqual(rc, 0)
            self.assertTrue(json_path.is_file())
            report = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertTrue(report["passed"])
            self.assertEqual(report["transcript"], "zero")

    def test_main_threshold_failure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            audio_path = Path(td) / "fixture.wav"
            audio_path.write_bytes(b"fakewav")
            argv = [
                "audio_inference_selftest.py",
                "--audio-path",
                str(audio_path),
                "--expected-text",
                "zero",
                "--max-wer",
                "0.0",
            ]
            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(ais, "transcribe_audio_fixture", return_value="one"),
            ):
                rc = ais.main()
            self.assertEqual(rc, 4)

    def test_main_missing_audio_returns_2(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "missing.wav"
            argv = [
                "audio_inference_selftest.py",
                "--audio-path",
                str(missing),
            ]
            with mock.patch.object(sys, "argv", argv):
                rc = ais.main()
            self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
