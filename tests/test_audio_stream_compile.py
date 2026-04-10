"""Tests for VoxCPM-style segment PCM merge (narrator.audio_stream_compile)."""

from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from narrator.audio_stream_compile import (
    CompiledUtteranceState,
    combined_utterance_label,
    merge_segment_wav_into_state,
)
from narrator.settings import RuntimeSettings


def _write_sine_wav(path: Path, *, fr: int = 22050, n_frames: int = 8000, amp: int = 5000) -> None:
    t = np.arange(n_frames, dtype=np.float32)
    x = (amp * np.sin(2.0 * np.pi * 440.0 * t / fr)).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(fr)
        w.writeframes(x.tobytes())


class TestMergeSegments(unittest.TestCase):
    def test_two_segments_longer_than_one(self) -> None:
        settings = RuntimeSettings()
        settings.segment_transition_preset = "minimal"  # short crossfade for test speed

        import os

        fd1, p1 = tempfile.mkstemp(suffix=".wav")
        fd2, p2 = tempfile.mkstemp(suffix=".wav")
        os.close(fd1)
        os.close(fd2)
        a = Path(p1)
        b = Path(p2)
        try:
            _write_sine_wav(a, n_frames=5000)
            _write_sine_wav(b, n_frames=5000)
            st = CompiledUtteranceState()
            merge_segment_wav_into_state(st, a, settings)
            merge_segment_wav_into_state(st, b, settings)
            bpf = st.channels * st.sampwidth
            self.assertEqual(st.segments_merged, 2)
            self.assertGreater(len(st.pcm), 5000 * bpf)
        finally:
            a.unlink(missing_ok=True)
            b.unlink(missing_ok=True)

    def test_combined_label(self) -> None:
        items = [
            ("s1", "Hello", None, "1"),
            ("s2", "World", None, "2"),
        ]
        self.assertIn("Hello", combined_utterance_label(items))
        self.assertIn("World", combined_utterance_label(items))
