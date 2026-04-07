"""Tests for scripts/analyze_audio_recordings.py quality metrics."""

from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import analyze_audio_recordings as aar  # noqa: E402


def _write_wav(path: Path, x: np.ndarray, sr: int = 16000) -> None:
    y = np.clip(x.astype(np.float32), -1.0, 1.0)
    pcm = (y * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


class TestAnalyzeAudioRecordings(unittest.TestCase):
    def test_analyze_wav_basic_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "tone.wav"
            sr = 16000
            t = np.arange(0, sr * 1.0, dtype=np.float32) / sr
            x = 0.1 * np.sin(2.0 * np.pi * 220.0 * t)
            _write_wav(p, x, sr=sr)
            out = aar.analyze_wav(p)
            self.assertIn("echo_likelihood_0_1", out)
            self.assertIn("overlap_likelihood_0_1", out)
            self.assertIn("dropout_likelihood_0_1", out)
            self.assertIn("clip_likelihood_0_1", out)
            self.assertIn("instability_likelihood_0_1", out)
            self.assertIn("quality_risk_0_1", out)
            self.assertGreater(out["duration_s"], 0.5)

    def test_dropout_metric_detects_long_silence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "dropout.wav"
            sr = 16000
            t = np.arange(0, sr * 0.5, dtype=np.float32) / sr
            voiced = 0.15 * np.sin(2.0 * np.pi * 180.0 * t)
            silence = np.zeros(int(sr * 0.8), dtype=np.float32)
            x = np.concatenate([voiced, silence, voiced])
            _write_wav(p, x, sr=sr)
            out = aar.analyze_wav(p)
            self.assertGreaterEqual(out["longest_silent_run_s"], 0.6)
            self.assertGreater(out["dropout_likelihood_0_1"], 0.2)

    def test_quality_gate_checks(self) -> None:
        m_ok = {
            "echo_likelihood_0_1": 0.1,
            "overlap_likelihood_0_1": 0.1,
            "clip_likelihood_0_1": 0.0,
            "dropout_likelihood_0_1": 0.1,
            "instability_likelihood_0_1": 0.2,
            "quality_risk_0_1": 0.2,
        }
        ok, checks = aar._quality_gate_checks(
            m_ok,
            max_echo=0.7,
            max_overlap=0.7,
            max_clip=0.3,
            max_dropout=0.6,
            max_instability=0.75,
            max_quality_risk=0.7,
        )
        self.assertTrue(ok)
        self.assertEqual(len(checks), 6)

        m_bad = dict(m_ok)
        m_bad["clip_likelihood_0_1"] = 0.95
        ok2, checks2 = aar._quality_gate_checks(
            m_bad,
            max_echo=0.7,
            max_overlap=0.7,
            max_clip=0.3,
            max_dropout=0.6,
            max_instability=0.75,
            max_quality_risk=0.7,
        )
        self.assertFalse(ok2)
        self.assertTrue(any((c["name"] == "clip_likelihood_0_1" and not c["passed"]) for c in checks2))


if __name__ == "__main__":
    unittest.main()
