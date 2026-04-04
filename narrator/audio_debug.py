"""Opt-in tracing for echo / stacked-voice diagnosis. Set ``NARRATOR_DEBUG_AUDIO=1``."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger("narrator.audio_debug")


def is_enabled() -> bool:
    return os.environ.get("NARRATOR_DEBUG_AUDIO", "").strip().lower() in ("1", "true", "yes", "on")


def log(msg: str, *args: Any) -> None:
    if is_enabled():
        logger.info(msg, *args)


def log_kv(msg: str, **kwargs: Any) -> None:
    if is_enabled():
        tail = " ".join(f"{k}={v!r}" for k, v in kwargs.items())
        logger.info(
            "%s | %s | pid=%s tid=%s t=%.6f",
            msg,
            tail,
            os.getpid(),
            threading.get_ident(),
            time.perf_counter(),
        )
