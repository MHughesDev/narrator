"""Optional PortAudio playback (``pip install sounddevice``). In-play rate nudges apply to the *next* utterance only."""

from __future__ import annotations

import logging
import queue
import time
from typing import TYPE_CHECKING

import numpy as np

from narrator import audio_debug
from narrator.playback_result import PlayWavResult
from narrator.protocol import SHUTDOWN, SPEAK_RATE_DOWN, SPEAK_RATE_UP, SPEAK_TOGGLE
from narrator.wav_play_win32 import (
    WAVEOUT_PCM_MAX_CHUNK_BYTES,
    _drain_coalesce_speak_rates,
    _pcm_chunks,
    apply_speak_rate_queue_message,
)

if TYPE_CHECKING:
    from narrator.settings import RuntimeSettings

logger = logging.getLogger(__name__)


def play_prepared_pcm_sounddevice(
    pcm: bytes,
    channels: int,
    sampwidth: int,
    framerate: int,
    event_queue: queue.Queue,
    settings: "RuntimeSettings",
    rate_baked_in_wav: float,
    *,
    utterance_text: str | None = None,
) -> PlayWavResult:
    """
    Play prepared 16-bit PCM via PortAudio. **Ctrl+Alt+±** updates persisted rate for the **next**
    synthesis (no WSOLA handoff — same effective behavior as ``live_rate_defer_during_playback``).
    """
    try:
        import sounddevice as sd
    except ImportError:
        raise

    _ = utterance_text
    _ = rate_baked_in_wav

    if sampwidth != 2 or channels < 1:
        logger.error("sounddevice backend expects 16-bit PCM")
        return PlayWavResult.cancelled()

    _, chunks = _pcm_chunks(
        pcm,
        channels=channels,
        sampwidth=sampwidth,
        framerate=framerate,
        max_chunk_bytes=WAVEOUT_PCM_MAX_CHUNK_BYTES,
    )
    if not chunks:
        return PlayWavResult.cancelled()

    bpf = channels * sampwidth

    if audio_debug.is_enabled():
        audio_debug.log_kv(
            "sounddevice play",
            n_chunks=len(chunks),
            pcm_bytes=len(pcm),
        )

    try:
        with sd.RawOutputStream(
            samplerate=framerate,
            channels=channels,
            dtype="int16",
            blocksize=0,
        ) as stream:
            for chunk in chunks:
                while True:
                    try:
                        msg = event_queue.get_nowait()
                    except queue.Empty:
                        break
                    if msg == SHUTDOWN or msg == SPEAK_TOGGLE:
                        return PlayWavResult.cancelled()
                    if msg in (SPEAK_RATE_UP, SPEAK_RATE_DOWN):
                        apply_speak_rate_queue_message(settings, msg)
                        _drain_coalesce_speak_rates(event_queue, settings)
                    else:
                        event_queue.put(msg)
                        break

                arr = np.frombuffer(chunk, dtype=np.int16)
                if channels > 1:
                    arr = arr.reshape(-1, channels)
                stream.write(arr)

        tail_s = (len(pcm) / bpf) / framerate if bpf and framerate else 0.0
        time.sleep(min(0.6, max(0.08, tail_s * 0.08)))
    except Exception as e:
        logger.error("sounddevice playback: %s", e)
        return PlayWavResult.cancelled()

    return PlayWavResult.complete()
