"""Optional Coqui XTTS neural TTS (``pip install narrator[speak-xtts]``)."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from narrator.settings import RuntimeSettings

logger = logging.getLogger(__name__)


def is_xtts_available() -> bool:
    """True if ``coqui-tts`` can be imported and loads (import check only; does not download weights)."""
    try:
        import TTS  # noqa: F401
        return True
    except Exception:
        # ImportError if missing; OSError if torch DLLs break on this machine.
        return False


_lock = threading.Lock()
_tts = None
_cached_model: Optional[str] = None
_cached_gpu: Optional[bool] = None


def _gpu_flag(settings: "RuntimeSettings") -> bool:
    import torch

    if settings.xtts_device == "cpu":
        return False
    if settings.xtts_device == "cuda":
        if not torch.cuda.is_available():
            logger.warning("CUDA requested for XTTS but not available; using CPU.")
        return torch.cuda.is_available()
    # auto
    return torch.cuda.is_available()


def get_tts(settings: "RuntimeSettings"):
    """Load and cache ``TTS`` model (first call downloads checkpoints)."""
    global _tts, _cached_model, _cached_gpu

    from TTS.api import TTS

    model = settings.xtts_model.strip() or "tts_models/multilingual/multi-dataset/xtts_v2"
    gpu = _gpu_flag(settings)
    with _lock:
        if _tts is not None and _cached_model == model and _cached_gpu == gpu:
            return _tts
        logger.info(
            "Loading XTTS model %r (gpu=%s). First run downloads a large checkpoint; this can take several minutes.",
            model,
            gpu,
        )
        _tts = TTS(model_name=model, gpu=gpu, progress_bar=False)
        _cached_model = model
        _cached_gpu = gpu
        return _tts


def list_speakers(settings: "RuntimeSettings") -> list[str]:
    """Return Coqui speaker names for the configured model (loads model)."""
    tts = get_tts(settings)
    sp = getattr(tts, "speakers", None)
    if sp is None:
        return []
    return list(sp)


def synthesize_xtts_to_path(path: Path, text: str, settings: "RuntimeSettings") -> None:
    """Write synthesized speech to ``path`` (WAV). Uses built-in speaker or ``speaker_wav`` clone."""
    tts = get_tts(settings)
    speaker_wav = (settings.xtts_speaker_wav or "").strip() or None

    if speaker_wav:
        spath = Path(speaker_wav)
        if not spath.is_file():
            raise FileNotFoundError(f"xtts_speaker_wav not found: {spath}")
        speaker = None
    else:
        spath = None
        speaker = (settings.voice_name or "").strip() or (settings.xtts_speaker or "").strip() or "Ana Florence"

    lang = (settings.xtts_language or "en").strip() or "en"

    logger.info(
        "XTTS synthesize: speaker=%r language=%s (clone=%s); tempo via post-process stretch",
        speaker if spath is None else f"wav:{spath}",
        lang,
        bool(spath),
    )

    def _run(with_speed: bool) -> None:
        common = dict(
            text=text,
            file_path=str(path),
            language=lang,
            split_sentences=True,
        )
        if with_speed:
            common["speed"] = 1.0
        if spath is not None:
            tts.tts_to_file(speaker_wav=str(spath), **common)
        else:
            tts.tts_to_file(speaker=speaker, **common)

    try:
        _run(with_speed=True)
    except TypeError:
        _run(with_speed=False)

    vol = float(settings.audio_volume)
    if vol < 0.99:
        _apply_volume_to_wav(path, vol)


def _apply_volume_to_wav(path: Path, volume: float) -> None:
    import wave

    import numpy as np

    with wave.open(str(path), "rb") as wf:
        nch = wf.getnchannels()
        sw = wf.getsampwidth()
        fr = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    if sw != 2:
        logger.debug("Volume adjust skipped: sample width %s", sw)
        return
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) * volume
    np.clip(x, -32768, 32767, out=x)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(nch)
        wf.setsampwidth(sw)
        wf.setframerate(fr)
        wf.writeframes(x.astype(np.int16).tobytes())
