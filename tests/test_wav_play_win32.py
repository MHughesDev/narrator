"""Unit tests for live-rate resume offset math (no winmm device required)."""

from __future__ import annotations

import unittest

from narrator.wav_play_win32 import compute_live_rate_resume_offset
from narrator.wav_speaking_rate import (
    apply_live_in_play_tempo,
    tempo_change_resample_int16_interleaved,
    tempo_change_wsola_int16_interleaved,
)


class TestComputeLiveRateResumeOffset(unittest.TestCase):
    def test_api_error_falls_back_to_chunk_end(self) -> None:
        off, reason = compute_live_rate_resume_offset(
            pcm_len=10000,
            bpf=2,
            chunk_boundary=4000,
            chunk_end_exclusive=5000,
            framerate=22050,
            slack_ms=120.0,
            api_ok=False,
            raw_cb_bytes=0,
        )
        self.assertEqual(off, 5000)
        self.assertEqual(reason, "api_error")

    def test_ok_adds_slack(self) -> None:
        # 22050 Hz, 2 bpf -> 22050 bytes/s; 120 ms -> 2646 bytes slack
        bpf = 2
        fr = 22050
        slack_ms = 120.0
        slack_b = int(fr * bpf * slack_ms / 1000)
        off, reason = compute_live_rate_resume_offset(
            pcm_len=10000,
            bpf=bpf,
            chunk_boundary=4000,
            chunk_end_exclusive=5000,
            framerate=fr,
            slack_ms=slack_ms,
            api_ok=True,
            raw_cb_bytes=4400,
        )
        self.assertEqual(reason, "ok")
        self.assertEqual(off, 4400 + slack_b)

    def test_sanity_low_position_falls_back(self) -> None:
        off, reason = compute_live_rate_resume_offset(
            pcm_len=10000,
            bpf=2,
            chunk_boundary=4000,
            chunk_end_exclusive=5000,
            framerate=22050,
            slack_ms=120.0,
            api_ok=True,
            raw_cb_bytes=1000,
        )
        self.assertEqual(reason, "sanity_fallback")
        self.assertEqual(off, 5000)

    def test_sanity_high_position_falls_back(self) -> None:
        off, reason = compute_live_rate_resume_offset(
            pcm_len=10000,
            bpf=2,
            chunk_boundary=4000,
            chunk_end_exclusive=5000,
            framerate=22050,
            slack_ms=120.0,
            api_ok=True,
            raw_cb_bytes=9000,
        )
        self.assertEqual(reason, "sanity_fallback")
        self.assertEqual(off, 5000)

    def test_clamp_pcm_len(self) -> None:
        off, reason = compute_live_rate_resume_offset(
            pcm_len=5000,
            bpf=2,
            chunk_boundary=4000,
            chunk_end_exclusive=5000,
            framerate=22050,
            slack_ms=120.0,
            api_ok=True,
            raw_cb_bytes=4998,
        )
        self.assertEqual(reason, "ok")
        self.assertLessEqual(off, 5000)

    def test_bpf_nonpositive(self) -> None:
        off, reason = compute_live_rate_resume_offset(
            pcm_len=100,
            bpf=0,
            chunk_boundary=0,
            chunk_end_exclusive=50,
            framerate=8000,
            slack_ms=120.0,
            api_ok=True,
            raw_cb_bytes=0,
        )
        self.assertEqual(reason, "bpf_nonpositive")
        self.assertEqual(off, 50)


class TestWsolaLive(unittest.TestCase):
    def test_wsola_long_mono_changes_length(self) -> None:
        import numpy as np

        n = 20000
        pcm = np.arange(n, dtype=np.int16).tobytes()
        out = tempo_change_wsola_int16_interleaved(pcm, 1, 1.2)
        self.assertGreater(len(out), 0)
        self.assertNotEqual(len(out), len(pcm))

    def test_apply_live_wsola_matches_engine(self) -> None:
        import numpy as np

        n = 20000
        pcm = np.zeros(n, dtype=np.int16).tobytes()
        a = apply_live_in_play_tempo(pcm, channels=1, sampwidth=2, rate_ratio=1.1, engine="wsola")
        b = tempo_change_wsola_int16_interleaved(pcm, 1, 1.1)
        self.assertEqual(a, b)

    def test_apply_live_resample_engine(self) -> None:
        import numpy as np

        n = 400
        pcm = np.arange(n, dtype=np.int16).tobytes()
        r = apply_live_in_play_tempo(pcm, channels=1, sampwidth=2, rate_ratio=2.0, engine="resample")
        self.assertEqual(len(r), (n // 2) * 2)


class TestTempoResampleLive(unittest.TestCase):
    def test_double_speed_halves_mono_pcm_length(self) -> None:
        import numpy as np

        n = 400
        pcm = np.arange(n, dtype=np.int16).tobytes()
        out = tempo_change_resample_int16_interleaved(pcm, 1, 2.0)
        self.assertEqual(len(out), (n // 2) * 2)

    def test_stereo_length_matches_mono_rule(self) -> None:
        import numpy as np

        n_frames = 100
        pcm = np.zeros(n_frames * 2, dtype=np.int16)
        pcm[0::2] = 1000
        pcm[1::2] = -1000
        out = tempo_change_resample_int16_interleaved(pcm.tobytes(), 2, 2.0)
        self.assertEqual(len(out), n_frames * 2)


if __name__ == "__main__":
    unittest.main()
