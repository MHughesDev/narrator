"""Unit tests for segment transition presets."""

from __future__ import annotations

import unittest

from narrator.segment_transitions import resolve_playback_transition
from narrator.settings import RuntimeSettings


class TestResolvePlaybackTransition(unittest.TestCase):
    def _engine(self, name: str) -> RuntimeSettings:
        r = RuntimeSettings()
        r.speak_engine = name
        r.segment_transition_preset = "engine"
        return r

    def test_engine_winrt(self) -> None:
        t = resolve_playback_transition(self._engine("winrt"))
        self.assertGreaterEqual(t.pcm_edge_fade_ms, 8.0)
        self.assertGreaterEqual(t.segment_crossfade_ms, 28.0)
        self.assertTrue(t.pcm_peak_normalize)

    def test_engine_piper(self) -> None:
        t = resolve_playback_transition(self._engine("piper"))
        self.assertGreaterEqual(t.segment_crossfade_ms, 30.0)

    def test_custom_uses_settings(self) -> None:
        r = RuntimeSettings()
        r.segment_transition_preset = "custom"
        r.pcm_edge_fade_ms = 1.0
        r.segment_crossfade_ms = 5.0
        r.pcm_peak_normalize = False
        t = resolve_playback_transition(r)
        self.assertEqual(t.pcm_edge_fade_ms, 1.0)
        self.assertEqual(t.segment_crossfade_ms, 5.0)
        self.assertFalse(t.pcm_peak_normalize)

    def test_minimal(self) -> None:
        r = RuntimeSettings()
        r.segment_transition_preset = "minimal"
        t = resolve_playback_transition(r)
        self.assertGreater(t.segment_crossfade_ms, 0.0)
        self.assertTrue(t.pcm_peak_normalize)


if __name__ == "__main__":
    unittest.main()
