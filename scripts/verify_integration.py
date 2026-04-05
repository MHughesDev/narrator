"""CI: protocol, settings defaults, dual-queue hotkey registration (no audio, no mic, no hooks running)."""

from __future__ import annotations

import queue
import sys


def main() -> int:
    from narrator.hotkey import build_listener
    from narrator.listen import listen_worker_loop
    from narrator.protocol import LISTEN_SESSION_ENDED, LISTEN_TOGGLE, SHUTDOWN, SPEAK_TOGGLE
    from narrator.settings import RuntimeSettings, build_runtime_settings
    from narrator.speak_preprocess import prepare_speak_text
    from narrator.tts_piper import DEFAULT_PIPER_VOICE_ID
    from narrator import worker

    assert SPEAK_TOGGLE == "speak_toggle"
    assert LISTEN_TOGGLE == "listen_toggle"
    assert SHUTDOWN == "shutdown"
    assert LISTEN_SESSION_ENDED == "listen_session_ended"

    r = RuntimeSettings()
    assert r.speak_hotkey == "ctrl+alt+s"
    assert r.listen_hotkey == "ctrl+alt+l"
    assert r.speak_engine == "winrt"
    assert r.piper_voice == DEFAULT_PIPER_VOICE_ID
    assert r.speak_exclude_hyperlinks is True
    assert r.speak_exclude_math is True
    assert r.speak_exclude_markup is True
    assert r.speak_exclude_citations is True
    assert r.speak_exclude_technical is True
    assert r.speak_exclude_chrome is True
    assert r.speak_exclude_emoji is True
    assert r.speak_insert_line_pauses is True
    assert r.speak_pause_between_lines is False
    assert r.speak_winrt_use_ssml_breaks is True
    assert r.speak_pause_line_ms == 320
    assert r.speak_pause_paragraph_ms == 520
    assert r.live_rate_resume_slack_ms == 280.0
    assert r.post_waveout_close_drain_s == 0.35
    assert r.live_rate_safe_chunk_discard is True
    assert r.live_rate_defer_during_playback is False
    assert r.live_rate_in_play_engine == "wsola"
    assert r.pcm_edge_fade_ms == 8.0
    assert r.live_rate_settle_ms == 45.0
    assert r.live_rate_extreme_ratio_threshold == 1.12
    assert r.live_rate_min_handoff_interval_s == 0.0
    assert r.live_rate_resynth_remainder is True
    assert r.audio_output_backend == "waveout"
    assert r.segment_crossfade_ms == 24.0
    assert r.pcm_peak_normalize is True
    assert r.post_reset_silence_ms == 12.0
    assert r.segment_transition_preset == "engine"

    assert "http" not in prepare_speak_text("see [a](https://ex.com)", exclude_hyperlinks=True, exclude_math=False).lower()
    assert prepare_speak_text(r"$\frac{1}{2}$", exclude_hyperlinks=False, exclude_math=True) == ""

    built = build_runtime_settings(
        config_explicit=None,
        voice=None,
        rate=None,
        volume=None,
        speak_hotkey=None,
        listen_hotkey=None,
        legacy_hotkey=None,
        silent=False,
        verbose=False,
    )
    assert built.speak_hotkey == "ctrl+alt+s"
    assert built.listen_hotkey == "ctrl+alt+l"
    assert built.speak_engine == "winrt"

    sq: queue.Queue = queue.Queue()
    lq: queue.Queue = queue.Queue()
    build_listener(sq, lq)

    assert callable(worker.speak_worker_loop)
    assert callable(listen_worker_loop)

    print("OK: integration imports and dual-queue hotkey build")
    return 0


if __name__ == "__main__":
    sys.exit(main())
