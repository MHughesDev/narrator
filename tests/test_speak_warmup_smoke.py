"""Smoke test: speak_warmup module imports and skips WinRT."""

from __future__ import annotations

import unittest

from narrator.settings import RuntimeSettings
from narrator.speak_warmup import warmup_speak_stack


class TestSpeakWarmup(unittest.TestCase):
    def test_winrt_noop(self) -> None:
        s = RuntimeSettings()
        s.speak_engine = "winrt"
        warmup_speak_stack(s)  # should not raise


if __name__ == "__main__":
    unittest.main()
