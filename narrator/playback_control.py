"""Single-flight control for TTS PCM playback (``winmm`` ``waveOut`` or optional PortAudio).

The speak worker calls :func:`narrator.speech.play_wav_interruptible` on one thread; that
function must not run re-entrantly. A process-wide lock ensures only one playback session exists at
a time, so speed hotkeys cannot start a second stream alongside the first.

By default, speed hotkeys adjust the **remainder** of the current clip (``live_rate_in_play_engine``,
usually WSOLA). ``live_rate_defer_during_playback`` makes hotkeys apply only to the **next** utterance.
``audio_output_backend = sounddevice`` uses PortAudio and defers in-play stretch (next utterance only).
Optional remainder **re-synthesis** on rate change: ``live_rate_resynth_remainder``.
All in-play handling is inside ``play_wav_interruptible`` — not separate threads or processes.

Use :func:`playback_gate_held` instead of acquiring :data:`playback_gate` directly so
``NARRATOR_DEBUG_AUDIO=1`` can log acquire/release (see :file:`docs/DEBUG_MULTIPLE_VOICES.md`).
"""

from __future__ import annotations

import contextlib
import logging
import os
import threading
import time

from narrator import audio_debug

logger = logging.getLogger(__name__)

playback_gate = threading.Lock()


@contextlib.contextmanager
def playback_gate_held():
    """Acquire :data:`playback_gate`; log when ``NARRATOR_DEBUG_AUDIO=1``."""
    tid = threading.get_ident()
    pid = os.getpid()
    t0 = time.perf_counter()
    if audio_debug.is_enabled():
        logger.info("playback_gate waiting pid=%s tid=%s", pid, tid)
    playback_gate.acquire()
    if audio_debug.is_enabled():
        logger.info(
            "playback_gate acquired pid=%s tid=%s wait_s=%.6f",
            pid,
            tid,
            time.perf_counter() - t0,
        )
    try:
        yield
    finally:
        playback_gate.release()
        if audio_debug.is_enabled():
            logger.info("playback_gate released pid=%s tid=%s", pid, tid)
