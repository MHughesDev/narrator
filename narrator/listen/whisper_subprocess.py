"""Windows: run faster-whisper in a child process.

CTranslate2 / model load can hard-exit the interpreter with no traceback. Isolating inference keeps the
narrator process (hotkeys, WinRT TTS) alive.
"""

from __future__ import annotations

import atexit
import logging
import multiprocessing as mp
import os
import sys
import tempfile
from pathlib import Path
from multiprocessing.connection import Connection
from typing import Any, Optional

from narrator.listen.whisper_listen import whisper_transcribe_kwargs
from narrator.settings import RuntimeSettings

logger = logging.getLogger(__name__)

_worker: Optional[mp.Process] = None
_parent_conn: Optional[Connection] = None
_worker_settings_key: Optional[tuple[Any, ...]] = None
_atexit_registered: bool = False


def _worker_main(conn: Connection) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    log = logging.getLogger(__name__ + ".worker")
    model = None
    try:
        msg = conn.recv()
        if not isinstance(msg, tuple) or msg[0] != "init":
            conn.send(("error", "bad first message"))
            return
        settings: RuntimeSettings = msg[1]
        from narrator.listen.whisper_listen import _get_model

        model = _get_model(settings)
        conn.send(("ready",))
    except Exception:
        log.exception("Whisper worker failed during model load")
        try:
            conn.send(("error", "model load failed"))
        except Exception:
            pass
        return

    while True:
        try:
            msg = conn.recv()
        except (EOFError, BrokenPipeError, OSError):
            return
        if msg == ("quit",):
            return
        if not isinstance(msg, tuple) or msg[0] != "transcribe":
            try:
                conn.send(("error", "bad request"))
            except Exception:
                pass
            continue
        path = msg[1]
        try:
            segments, info = model.transcribe(path, **whisper_transcribe_kwargs(settings))
            text = "".join(seg.text for seg in segments).strip()
            conn.send(
                (
                    "ok",
                    text,
                    float(info.duration),
                    getattr(info, "language", None),
                )
            )
        except Exception:
            log.exception("Whisper transcribe failed")
            try:
                conn.send(("error", "transcribe failed"))
            except Exception:
                pass


def _settings_key(settings: RuntimeSettings) -> tuple[Any, ...]:
    return (
        (settings.whisper_model or "").strip().lower(),
        (settings.whisper_device or "").strip().lower(),
        settings.listen_whisper_refine_punctuation,
        int(settings.whisper_beam_size),
        (settings.whisper_initial_prompt or "").strip(),
        bool(settings.whisper_greedy),
    )


def shutdown_worker() -> None:
    global _worker, _parent_conn, _worker_settings_key
    if _parent_conn is not None:
        try:
            _parent_conn.send(("quit",))
        except Exception:
            pass
        _parent_conn = None
    if _worker is not None:
        _worker.join(timeout=8.0)
        if _worker.is_alive():
            _worker.terminate()
            _worker.join(timeout=3.0)
        _worker = None
    _worker_settings_key = None


def ensure_worker(settings: RuntimeSettings) -> Connection:
    global _worker, _parent_conn, _worker_settings_key, _atexit_registered
    key = _settings_key(settings)
    if (
        _worker is not None
        and _worker.is_alive()
        and _parent_conn is not None
        and _worker_settings_key == key
    ):
        return _parent_conn

    shutdown_worker()

    if not _atexit_registered:
        atexit.register(shutdown_worker)
        _atexit_registered = True

    ctx = mp.get_context("spawn")
    parent_c, child_c = ctx.Pipe(duplex=True)
    proc = ctx.Process(target=_worker_main, args=(child_c,), name="narrator-whisper-worker", daemon=False)
    proc.start()
    _worker = proc
    _parent_conn = parent_c
    _worker_settings_key = key

    try:
        parent_c.send(("init", settings))
    except Exception as e:
        logger.error("Could not send init to Whisper worker: %s", e)
        shutdown_worker()
        raise

    try:
        resp = parent_c.recv()
    except EOFError:
        logger.error(
            "Whisper worker exited while loading the model (often a native crash in CTranslate2). "
            "Try VC++ Redistributable x64, or use --listen-engine winrt.",
        )
        shutdown_worker()
        raise RuntimeError("Whisper worker died during model load") from None

    if not isinstance(resp, tuple) or not resp:
        shutdown_worker()
        raise RuntimeError("Whisper worker sent an invalid response")
    if resp[0] == "error":
        shutdown_worker()
        raise RuntimeError(f"Whisper worker failed: {resp[1]}")
    if resp[0] != "ready":
        shutdown_worker()
        raise RuntimeError(f"Whisper worker unexpected message: {resp!r}")

    return parent_c


def _whisper_listen_session_windows_chunked(stop_event: Any, settings: RuntimeSettings) -> None:
    """Transcribe each timed slice in the child process (same as one-shot, repeated)."""
    from narrator.listen.whisper_listen import (
        WHISPER_SAMPLE_RATE,
        _write_wav_pcm16,
        apply_whisper_text_to_focus,
        iter_whisper_audio_chunks,
    )

    try:
        conn = ensure_worker(settings)
    except Exception as e:
        logger.error("Whisper: could not start isolated worker: %s", e)
        return

    for _chunk in iter_whisper_audio_chunks(stop_event, settings, settings.whisper_chunk_interval_seconds):
        fd, path_str = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        tmp = Path(path_str)
        try:
            _write_wav_pcm16(tmp, _chunk, WHISPER_SAMPLE_RATE)
            try:
                conn.send(("transcribe", str(tmp)))
            except Exception as e:
                logger.error("Whisper: could not send transcribe job: %s", e)
                return
            try:
                resp = conn.recv()
            except EOFError:
                logger.error(
                    "Whisper worker died during transcription. Restart narrator and try again, "
                    "or use --listen-engine winrt.",
                )
                shutdown_worker()
                return
            if not isinstance(resp, tuple) or not resp:
                logger.error("Whisper: invalid worker response: %r", resp)
                return
            if resp[0] == "error":
                logger.error("Whisper: transcribe failed: %s", resp[1])
                return
            if resp[0] != "ok":
                logger.error("Whisper: unexpected worker message: %r", resp)
                return
            text = resp[1]
            dur = float(resp[2]) if len(resp) > 2 else 0.0
            lang = resp[3] if len(resp) > 3 else None
            if text:
                logger.info("Whisper: chunk transcribed (~%.1fs audio, lang=%s).", dur, lang)
                apply_whisper_text_to_focus(text, settings, refine_punctuation=False)
            else:
                logger.debug("Whisper: empty chunk skipped.")
        finally:
            tmp.unlink(missing_ok=True)


def whisper_listen_session_windows(stop_event: Any, settings: RuntimeSettings) -> None:
    if sys.platform != "win32":
        return
    if settings.whisper_chunk_interval_seconds > 0:
        _whisper_listen_session_windows_chunked(stop_event, settings)
        return

    from narrator.listen.whisper_listen import apply_whisper_text_to_focus, record_whisper_session_to_wav

    try:
        conn = ensure_worker(settings)
    except Exception as e:
        logger.error("Whisper: could not start isolated worker: %s", e)
        return

    tmp = record_whisper_session_to_wav(stop_event, settings)
    if tmp is None:
        return

    path_str = str(tmp)
    try:
        try:
            conn.send(("transcribe", path_str))
        except Exception as e:
            logger.error("Whisper: could not send transcribe job: %s", e)
            return

        try:
            resp = conn.recv()
        except EOFError:
            logger.error(
                "Whisper worker died during transcription. Restart narrator and try again, "
                "or use --listen-engine winrt.",
            )
            shutdown_worker()
            return

        if not isinstance(resp, tuple) or not resp:
            logger.error("Whisper: invalid worker response: %r", resp)
            return
        if resp[0] == "error":
            logger.error("Whisper: transcribe failed: %s", resp[1])
            return
        if resp[0] != "ok":
            logger.error("Whisper: unexpected worker message: %r", resp)
            return

        text = resp[1]
        dur = float(resp[2]) if len(resp) > 2 else 0.0
        lang = resp[3] if len(resp) > 3 else None
        if not text:
            logger.info("Whisper: empty transcript.")
            return
        logger.info("Whisper: transcribed (~%.1fs audio, lang=%s).", dur, lang)
        apply_whisper_text_to_focus(text, settings)
    finally:
        tmp.unlink(missing_ok=True)
