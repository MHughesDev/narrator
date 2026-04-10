"""Tests for VoxCPM-aligned text stages (narrator.voxcpm_text_pipeline)."""

from __future__ import annotations

import unittest

from narrator.settings import RuntimeSettings
from narrator.voxcpm_text_pipeline import apply_voxcpm_style_text_for_tts


class TestVoxcpmStyleText(unittest.TestCase):
    def test_disabled_returns_unchanged(self) -> None:
        s = RuntimeSettings()
        s.speak_voxcpm_text_pipeline = False
        raw = "Hello  \n\n  world"
        self.assertEqual(apply_voxcpm_style_text_for_tts(raw, s), raw)

    def test_neural_collapses_whitespace(self) -> None:
        s = RuntimeSettings()
        s.speak_engine = "xtts"
        s.speak_voxcpm_text_pipeline = True
        s.speak_voxcpm_text_normalize = False
        out = apply_voxcpm_style_text_for_tts("  foo\n\nbar\tbaz  ", s)
        self.assertEqual(out, "foo bar baz")

    def test_winrt_preserves_newlines_for_ssml(self) -> None:
        s = RuntimeSettings()
        s.speak_engine = "winrt"
        s.speak_winrt_use_ssml_breaks = True
        s.speak_insert_line_pauses = True
        s.speak_voxcpm_text_pipeline = True
        s.speak_voxcpm_text_normalize = False
        out = apply_voxcpm_style_text_for_tts("line one\n\nline two", s)
        self.assertIn("\n", out)
        self.assertIn("line one", out)
        self.assertIn("line two", out)


if __name__ == "__main__":
    unittest.main()
