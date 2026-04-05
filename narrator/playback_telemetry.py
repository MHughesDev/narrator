"""Optional counters for live-rate handoffs (``NARRATOR_AUDIO_STATS=1`` or debug audio)."""

from __future__ import annotations

import os
import threading
_lock = threading.Lock()
_counts: dict[str, int] = {
    "live_rate_handoff": 0,
    "live_rate_resynth_remainder": 0,
}


def is_stats_enabled() -> bool:
    return os.environ.get("NARRATOR_AUDIO_STATS", "").strip().lower() in ("1", "true", "yes", "on")


def record(event: str, *, n: int = 1) -> None:
    from narrator import audio_debug

    if not is_stats_enabled() and not audio_debug.is_enabled():
        return
    with _lock:
        _counts[event] = _counts.get(event, 0) + n
    if audio_debug.is_enabled():
        audio_debug.log_kv("playback_telemetry", event=event, total=_counts.get(event, 0))


def snapshot() -> dict[str, int]:
    with _lock:
        return dict(_counts)


def reset() -> None:
    with _lock:
        for k in list(_counts.keys()):
            _counts[k] = 0
