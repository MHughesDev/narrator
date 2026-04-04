"""Orchestrate listen hotkey: WinRT dictation + typing into the focused field."""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from typing import TYPE_CHECKING

from pynput.keyboard import Controller, Key

from narrator.protocol import LISTEN_SESSION_ENDED, LISTEN_TOGGLE, SHUTDOWN

from . import stt_winrt
from .punctuate_heuristic import soften_misleading_title_case, trailing_punctuation_to_add
from .punctuate_neural import neural_punctuation_active, restore_document, restore_phrase

if TYPE_CHECKING:
    from narrator.settings import RuntimeSettings

logger = logging.getLogger(__name__)


def _type_into_focus(kb: Controller, text: str) -> None:
    """Type Unicode text; expand newlines to Enter."""
    if not text:
        return
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = t.split("\n")
    for i, line in enumerate(lines):
        if i > 0:
            kb.tap(Key.enter)
        if line:
            kb.type(line)


class _StreamingPhrase:
    """
    Live partial dictation: type only new characters as hypotheses grow, and finish the
    phrase on final result without duplicating text already typed from hypotheses.

    Raw phrase text is buffered for a **full-session** neural pass on stop (best quality on
    long runs). Session length is tracked from completed finals only for safe replace.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_partial: str = ""
        self._last_final_text: str = ""
        self._last_final_mono: float = 0.0
        self._raw_segments: list[str] = []
        self._session_typed_len: int = 0

    def on_hypothesis(self, kb: Controller, text: str | None) -> None:
        t = text or ""
        with self._lock:
            if t.startswith(self._last_partial):
                suffix = t[len(self._last_partial) :]
                suffix = soften_misleading_title_case(self._last_partial, suffix)
                if suffix:
                    _type_into_focus(kb, suffix)
                self._last_partial = t
                return
            for _ in range(len(self._last_partial)):
                kb.tap(Key.backspace)
            self._last_partial = ""
            if t:
                _type_into_focus(kb, t)
                self._last_partial = t

    def on_final_result(self, kb: Controller, text: str | None) -> None:
        """Append any remaining characters for this phrase, then a word-separator space."""
        f = text or ""
        with self._lock:
            if not f.strip():
                self._last_partial = ""
                return
            # WinRT occasionally delivers the same final twice back-to-back; skip duplicate.
            now = time.monotonic()
            if f == self._last_final_text and (now - self._last_final_mono) < 0.12:
                logger.debug("Skipping duplicate final result within 120ms")
                return
            self._last_final_text = f
            self._last_final_mono = now

            raw = f.strip()
            if raw:
                self._raw_segments.append(raw)

            f = restore_phrase(f)
            if not f.strip():
                self._last_partial = ""
                return

            if f.startswith(self._last_partial):
                suffix = f[len(self._last_partial) :]
                suffix = soften_misleading_title_case(self._last_partial, suffix)
                if suffix:
                    _type_into_focus(kb, suffix)
            else:
                for _ in range(len(self._last_partial)):
                    kb.tap(Key.backspace)
                _type_into_focus(kb, f)
            self._last_partial = ""
            extra = ""
            if not neural_punctuation_active():
                extra = trailing_punctuation_to_add(f)
                if extra:
                    kb.type(extra)
            kb.tap(Key.space)
            self._session_typed_len += len(f) + len(extra) + 1

    def finalize_session(self, kb: Controller) -> None:
        """After dictation stops: one full-context neural pass + replace session text (max quality)."""
        with self._lock:
            if not neural_punctuation_active() or not self._raw_segments:
                return
            joined = " ".join(self._raw_segments).strip()
            if not joined:
                return
            polished = restore_document(joined)
            if not polished.strip():
                return
            if self._session_typed_len <= 0:
                return
            if polished.strip() == joined.strip():
                logger.debug("Full-session punctuation unchanged; skipping replace.")
                return
            logger.info(
                "Applying full-session punctuation pass (%d chars raw -> %d chars).",
                len(joined),
                len(polished),
            )
            for _ in range(self._session_typed_len):
                kb.tap(Key.backspace)
            _type_into_focus(kb, polished)


async def _dictation_loop(stop_event: threading.Event, settings: "RuntimeSettings") -> None:
    kb = Controller()
    stream = _StreamingPhrase()

    await stt_winrt.run_continuous_dictation(
        stop_event,
        settings,
        on_hypothesis_text=lambda t: stream.on_hypothesis(kb, t),
        on_result_text=lambda t: stream.on_final_result(kb, t),
    )
    stream.finalize_session(kb)


def listen_worker_loop(listen_queue: queue.Queue, settings: "RuntimeSettings") -> None:
    """Toggle listen: start/stop continuous dictation in a dedicated thread."""
    listening = False
    stop_event = threading.Event()
    rec_thread: threading.Thread | None = None

    def run_session() -> None:
        try:
            if settings.listen_engine == "whisper":
                from .whisper_listen import whisper_listen_session

                whisper_listen_session(stop_event, settings)
            else:
                asyncio.run(_dictation_loop(stop_event, settings))
        except Exception as e:
            logger.exception("Listen session crashed: %s", e)
        finally:
            try:
                listen_queue.put(LISTEN_SESSION_ENDED)
            except Exception:
                pass

    while True:
        msg = listen_queue.get()
        if msg == SHUTDOWN:
            stop_event.set()
            if rec_thread is not None:
                rec_thread.join(timeout=30.0)
            logger.info("Listen worker shutdown")
            return
        if msg == LISTEN_SESSION_ENDED:
            listening = False
            rec_thread = None
            logger.debug("Listen session thread exited")
            continue
        if msg != LISTEN_TOGGLE:
            continue

        if not listening:
            listening = True
            stop_event.clear()
            # Non-daemon so a clean shutdown can wait for STT work; hook/speak threads keep the process alive.
            rec_thread = threading.Thread(target=run_session, daemon=False, name="narrator-listen-stt")
            rec_thread.start()
            if settings.listen_engine == "whisper":
                if settings.whisper_chunk_interval_seconds > 0:
                    logger.info(
                        "Listening (Whisper, chunked) — focus the target field. After the start beep, text is typed "
                        "automatically every ~%.1fs (no extra hotkey presses for that). Press the listen hotkey again "
                        "only to stop: remaining audio is transcribed, then the session ends.",
                        settings.whisper_chunk_interval_seconds,
                    )
                else:
                    logger.info(
                        "Listening (Whisper) — focus the target field, wait for the start beep, speak, then press the "
                        "listen hotkey again (you should hear a second beep) to transcribe. Nothing types until you stop.",
                    )
            else:
                logger.info("Listening (WinRT) — focus a text field; press the listen hotkey again to stop.")
        else:
            listening = False
            stop_event.set()
            if rec_thread is not None:
                rec_thread.join(timeout=30.0)
                rec_thread = None
            logger.info("Listen stopped")
