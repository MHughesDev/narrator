"""Unit tests for narrator.audio_pcm helpers."""

from __future__ import annotations

import os
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from narrator.audio_pcm import (
    pcm_ensure_standard_sample_rate,
    pcm_extract_tail_s16,
    pcm_highpass_sosfilt_s16,
    pcm_peak_normalize_s16,
    wav_fade_in_head_ms,
    wav_frame_count,
    wav_trim_head_frames,
)


class TestPeakNormalize(unittest.TestCase):
    def test_scales_to_peak(self) -> None:
        pcm = np.array([1000, -2000], dtype=np.int16).tobytes()
        out = pcm_peak_normalize_s16(pcm, channels=1, sampwidth=2, peak=0.5)
        x = np.frombuffer(out, dtype=np.int16)
        self.assertAlmostEqual(float(np.max(np.abs(x))), 0.5 * 32767.0, delta=2.0)


class TestExtractTail(unittest.TestCase):
    def test_tail_length(self) -> None:
        # 22050 Hz mono s16: 22050 samples/s * 2 bytes * 0.1 s = 4410 bytes for 100 ms
        n = 22050 * 2
        pcm = np.ones(n, dtype=np.int16).tobytes()
        t = pcm_extract_tail_s16(pcm, channels=1, sampwidth=2, framerate=22050, ms=100)
        self.assertEqual(len(t), 4410)


class TestEnsureRate(unittest.TestCase):
    def test_keeps_common(self) -> None:
        self.assertEqual(pcm_ensure_standard_sample_rate(22050), 22050)

    def test_snaps_near(self) -> None:
        self.assertIn(pcm_ensure_standard_sample_rate(22100), (22050, 24000, 44100, 48000))


class TestHighpass(unittest.TestCase):
    def test_skips_short_buffer(self) -> None:
        pcm = np.zeros(120, dtype=np.int16).tobytes()
        out = pcm_highpass_sosfilt_s16(
            pcm, channels=1, sampwidth=2, framerate=22050, cutoff_hz=72.0
        )
        self.assertEqual(out, pcm)

    def test_reduces_dc_offset(self) -> None:
        try:
            import scipy.signal  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("scipy required")
        n = 12000
        pcm = (np.ones(n, dtype=np.int16) * 4000).tobytes()
        out = pcm_highpass_sosfilt_s16(
            pcm, channels=1, sampwidth=2, framerate=22050, cutoff_hz=72.0
        )
        y = np.frombuffer(out, dtype=np.int16).astype(np.float64)
        self.assertLess(abs(float(y.mean())), 800.0)


class TestWavTrimHead(unittest.TestCase):
    def test_trim_reduces_frames(self) -> None:
        fd, name = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        path = Path(name)
        try:
            fr = 8000
            n = 400
            pcm = np.zeros(n, dtype=np.int16).tobytes()
            with wave.open(str(path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(fr)
                w.writeframes(pcm)
            self.assertEqual(wav_frame_count(path), n)
            self.assertTrue(wav_trim_head_frames(path, 100))
            self.assertEqual(wav_frame_count(path), n - 100)
        finally:
            path.unlink(missing_ok=True)


class TestWavFadeInHead(unittest.TestCase):
    def test_fade_softens_first_samples(self) -> None:
        fd, name = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        path = Path(name)
        try:
            fr = 8000
            n = 800
            pcm = (np.ones(n, dtype=np.int16) * 8000).tobytes()
            with wave.open(str(path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(fr)
                w.writeframes(pcm)
            wav_fade_in_head_ms(path, 50.0)
            with wave.open(str(path), "rb") as w:
                out = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
            self.assertLess(int(out[0]), 200)
            self.assertGreater(int(out[-1]), 7500)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
