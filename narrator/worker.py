"""Queue-driven worker: toggle -> capture -> synthesize -> interruptible play."""

from __future__ import annotations

import logging
import queue
import tempfile
import winsound
from enum import Enum, auto
from pathlib import Path

from uiautomation import InitializeUIAutomationInCurrentThread, UninitializeUIAutomationInCurrentThread

from narrator import audio_debug, capture, speech
from narrator.speak_chunking import iter_tts_chunks
from narrator.speak_preprocess import prepare_speak_text_from_settings
from narrator.speak_prosody import apply_speak_prosody
from narrator.protocol import SHUTDOWN, SPEAK_RATE_DOWN, SPEAK_RATE_UP, SPEAK_TOGGLE
from narrator.wav_play_win32 import apply_speak_rate_queue_message
from narrator.settings import RuntimeSettings

logger = logging.getLogger(__name__)


class Phase(Enum):
    IDLE = auto()
    SYNTHESIZING = auto()
    PLAYING = auto()


def _drain_cancel_or_shutdown(q: queue.Queue, settings: RuntimeSettings) -> tuple[bool, bool]:
    cancel = False
    shutdown = False
    try:
        while True:
            m = q.get_nowait()
            if m == SPEAK_TOGGLE:
                cancel = True
            elif m == SHUTDOWN:
                shutdown = True
            elif m in (SPEAK_RATE_UP, SPEAK_RATE_DOWN):
                apply_speak_rate_queue_message(settings, m)
    except queue.Empty:
        pass
    return cancel, shutdown


def _beep_failure() -> None:
    try:
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception as e:
        logger.debug("MessageBeep: %s", e)


def speak_worker_loop(event_queue: queue.Queue, settings: RuntimeSettings) -> None:
    """UI Automation (COM) must be initialized on this thread before ControlFromPoint etc."""
    InitializeUIAutomationInCurrentThread()
    try:
        _speak_worker_loop_impl(event_queue, settings)
    finally:
        UninitializeUIAutomationInCurrentThread()


def _speak_worker_loop_impl(event_queue: queue.Queue, settings: RuntimeSettings) -> None:
    phase = Phase.IDLE

    def set_phase(p: Phase) -> None:
        nonlocal phase
        phase = p
        logger.debug("phase -> %s", p.name)

    while True:
        msg = event_queue.get()
        if msg == SHUTDOWN:
            speech.stop_playback()
            logger.info("Speak worker shutdown")
            return
        if msg in (SPEAK_RATE_UP, SPEAK_RATE_DOWN):
            apply_speak_rate_queue_message(settings, msg)
            continue
        if msg != SPEAK_TOGGLE:
            continue

        set_phase(Phase.SYNTHESIZING)
        raw = capture.capture_at_cursor()
        if not raw:
            logger.warning("No text to speak — hover over content with a UIA text provider and try again.")
            if settings.beep_on_failure:
                _beep_failure()
            set_phase(Phase.IDLE)
            continue

        text = prepare_speak_text_from_settings(raw, settings)
        if not text:
            logger.warning(
                "No text left after speak preprocessing — hover over readable prose and try again."
            )
            if settings.beep_on_failure:
                _beep_failure()
            set_phase(Phase.IDLE)
            continue
        if text != raw and settings.verbose:
            logger.debug("Speak preprocess: %d -> %d chars", len(raw), len(text))

        chunks = list(iter_tts_chunks(text, settings.speak_chunk_max_chars))
        if not chunks:
            logger.warning(
                "No speak segments after chunking — hover over readable prose and try again."
            )
            if settings.beep_on_failure:
                _beep_failure()
            set_phase(Phase.IDLE)
            continue

        if len(chunks) > 1:
            logger.info(
                "Long document: %d characters in %d segment(s) (speak_chunk_max_chars=%s).",
                len(text),
                len(chunks),
                settings.speak_chunk_max_chars or "off",
            )

        any_played = False
        for seg_idx, chunk in enumerate(chunks):
            set_phase(Phase.SYNTHESIZING)
            prosody = apply_speak_prosody(chunk, settings)
            if not prosody.strip():
                continue

            any_played = True
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp.close()
            wav_path = Path(tmp.name)

            ok, shutdown_now = speech.synthesize_with_queue_cancel(prosody, wav_path, settings, event_queue)
            if shutdown_now:
                speech.stop_playback()
                wav_path.unlink(missing_ok=True)
                logger.info("Speak worker shutdown")
                return
            if not ok:
                wav_path.unlink(missing_ok=True)
                set_phase(Phase.IDLE)
                break

            cancel, do_shutdown = _drain_cancel_or_shutdown(event_queue, settings)
            if do_shutdown:
                speech.stop_playback()
                wav_path.unlink(missing_ok=True)
                logger.info("Speak worker shutdown")
                return
            if cancel:
                logger.info("Cancelled before playback")
                wav_path.unlink(missing_ok=True)
                set_phase(Phase.IDLE)
                break

            set_phase(Phase.PLAYING)
            if len(chunks) > 1:
                logger.info(
                    "Playing segment %d/%d (%d chars)",
                    seg_idx + 1,
                    len(chunks),
                    len(prosody),
                )
            else:
                logger.info("Playing (%d chars)", len(prosody))

            if audio_debug.is_enabled():
                first_line = prosody.split("\n", 1)[0].strip().replace("\r", "")
                if len(first_line) > 200:
                    first_line = first_line[:197] + "..."
                n_lines = prosody.count("\n") + 1
                audio_debug.log_kv(
                    "speak text to TTS (direct string output)",
                    n_text_lines=n_lines,
                    text_chars=len(prosody),
                    segment=f"{seg_idx + 1}/{len(chunks)}",
                    first_line_preview=first_line or "(empty)",
                )
            audio_debug.log_kv(
                "worker play_wav_interruptible call",
                text_chars=len(prosody),
                wav_path=str(wav_path),
                segment=f"{seg_idx + 1}/{len(chunks)}",
            )
            played_through = speech.play_wav_interruptible(
                wav_path,
                event_queue,
                settings=settings,
                rate_baked_in_wav=float(settings.speaking_rate),
            )
            audio_debug.log_kv(
                "worker play_wav_interruptible returned",
                wav_path=str(wav_path),
                segment=f"{seg_idx + 1}/{len(chunks)}",
            )

            cancel, do_shutdown = _drain_cancel_or_shutdown(event_queue, settings)
            if do_shutdown:
                speech.stop_playback()
                logger.info("Speak worker shutdown")
                return
            if not played_through:
                logger.info("Playback stopped; remaining speak segments skipped")
                set_phase(Phase.IDLE)
                break
            if cancel:
                logger.info("Cancelled during playback")
                set_phase(Phase.IDLE)
                break

            set_phase(Phase.IDLE)

        if not any_played:
            logger.warning(
                "No speakable text after prosody on any segment — hover over readable prose and try again."
            )
            if settings.beep_on_failure:
                _beep_failure()
            set_phase(Phase.IDLE)
