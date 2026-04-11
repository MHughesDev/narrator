"""
Optional cold-start mitigation for neural TTS (VoxCPM-style warmup).

OpenBMB/VoxCPM runs a short ``generate()`` after loading weights so ``torch.compile`` and CUDA
kernels pay compile cost before user interaction (see ``VoxCPM.__init__`` in upstream ``core.py``).

Narrator cannot compile WinRT/Piper/XTTS the same way, but we can **preload** heavy models and
optionally run one **tiny synthesis** so the first hotkey avoids the worst first-inference stall.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from narrator.settings import RuntimeSettings

logger = logging.getLogger(__name__)

_WARMUP_TEXT = "Hi."


def warmup_speak_stack(settings: "RuntimeSettings") -> None:
    """
    Best-effort background warmup for the configured ``speak_engine``.

    Safe to call from a daemon thread. Skips if engine is WinRT (STA / UI-thread concerns) or
    if optional deps are missing.
    """
    eng = str(getattr(settings, "speak_engine", "winrt")).strip().lower()
    if eng == "xtts":
        _warmup_xtts(settings)
    elif eng == "piper":
        _warmup_piper(settings)
    else:
        logger.debug("speak warmup: skipped for engine=%s", eng)


def _warmup_xtts(settings: "RuntimeSettings") -> None:
    from narrator.tts_xtts import get_tts, is_xtts_available, synthesize_xtts_to_path

    if not is_xtts_available():
        return
    try:
        get_tts(settings)
    except Exception as e:
        logger.debug("speak warmup: XTTS load: %s", e)
        return
    if not bool(getattr(settings, "speak_warmup_synthesize", True)):
        logger.info("Speak warmup: XTTS model loaded (synthesis warmup disabled)")
        return
    fd, name = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    path = Path(name)
    try:
        synthesize_xtts_to_path(path, _WARMUP_TEXT, settings)
        logger.info("Speak warmup: XTTS load + short synthesis ok")
    except Exception as e:
        logger.debug("speak warmup: XTTS synthesis: %s", e)
    finally:
        path.unlink(missing_ok=True)


def _warmup_piper(settings: "RuntimeSettings") -> None:
    from narrator.tts_piper import ensure_piper_voice_loaded, is_piper_available, synthesize_piper_to_path

    if not is_piper_available():
        return
    try:
        ensure_piper_voice_loaded(settings)
    except Exception as e:
        logger.debug("speak warmup: Piper load: %s", e)
        return
    if not bool(getattr(settings, "speak_warmup_synthesize", True)):
        logger.info("Speak warmup: Piper voice loaded (synthesis warmup disabled)")
        return
    fd, name = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    path = Path(name)
    try:
        synthesize_piper_to_path(path, _WARMUP_TEXT, settings)
        logger.info("Speak warmup: Piper load + short synthesis ok")
    except Exception as e:
        logger.debug("speak warmup: Piper synthesis: %s", e)
    finally:
        path.unlink(missing_ok=True)
