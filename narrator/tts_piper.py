"""Optional Piper neural TTS (``pip install narrator[speak-piper]``).

Uses ``piper-tts`` (ONNX) with voices from https://huggingface.co/rhasspy/piper-voices .
Download a voice with ``python scripts/prefetch_piper_voice.py`` or ``python -m piper.download_voices``.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import wave
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from narrator.settings import RuntimeSettings

logger = logging.getLogger(__name__)

# Default ONNX voice id (rhasspy/piper-voices). Prefer *-high over *-medium for clearer speech.
DEFAULT_PIPER_VOICE_ID = "en_US-ryan-high"

_piper_unavailable_reason: Optional[str] = None

_PIPER_VOICE_RE = re.compile(
    r"^[a-z]{2}_[A-Z]{2}-[a-zA-Z0-9_.-]+-(low|medium|high|x_low)$",
)


def default_piper_data_dir() -> Path:
    """Default directory for ``<voice>.onnx`` and ``<voice>.onnx.json``."""
    if sys.platform == "win32":
        la = os.environ.get("LOCALAPPDATA", "")
        if la:
            return Path(la) / "narrator" / "piper"
    return Path.home() / ".local" / "share" / "narrator" / "piper"


def piper_unavailable_reason() -> Optional[str]:
    """Last import error from :func:`is_piper_available` (e.g. onnxruntime DLL failure on Windows)."""
    return _piper_unavailable_reason


def is_piper_available() -> bool:
    """True if ``piper.voice`` imports. Catches all exceptions — ONNX runtime often raises ``OSError``, not ``ImportError``."""
    global _piper_unavailable_reason
    try:
        from piper.voice import PiperVoice  # noqa: F401

        _piper_unavailable_reason = None
        return True
    except Exception as e:
        _piper_unavailable_reason = f"{type(e).__name__}: {e}"
        return False


def effective_piper_voice_id(voice_name: Optional[str], piper_voice: str) -> str:
    """If ``--voice`` looks like a Piper voice id (e.g. en_US-ryan-high), use it; else ``piper_voice``."""
    vn = (voice_name or "").strip()
    if vn and _PIPER_VOICE_RE.match(vn):
        return vn
    return (piper_voice or DEFAULT_PIPER_VOICE_ID).strip()


def resolve_piper_onnx_path(
    *,
    voice_id: str,
    piper_model_dir: Optional[str],
    piper_model_path: Optional[str],
) -> Optional[Path]:
    """Return an existing ``.onnx`` path, or ``None``.

    If ``piper_model_path`` is set but missing, we still search known directories (stale config should not
    hide models in the default data dir).
    """
    vid = voice_id.strip()
    if piper_model_path and str(piper_model_path).strip():
        p = Path(piper_model_path.strip())
        if p.is_file():
            return p
        logger.warning(
            "Piper piper_model_path does not exist (%s); searching piper_model_dir and default data dir.",
            p,
        )

    bases: list[Path] = []
    if piper_model_dir and str(piper_model_dir).strip():
        bases.append(Path(piper_model_dir.strip()))
    bases.append(default_piper_data_dir())
    seen: set[str] = set()
    for base in bases:
        try:
            key = str(base.resolve())
        except OSError:
            key = str(base)
        if key in seen:
            continue
        seen.add(key)
        cand = base / f"{vid}.onnx"
        if cand.is_file():
            return cand
    return None


_voice_cache: dict[tuple[str, bool], Any] = {}


def ensure_piper_voice_loaded(settings: "RuntimeSettings") -> None:
    """Load the Piper ONNX voice into the process cache (no synthesis). For cold-start warmup."""
    _get_piper_voice(settings)


def _get_piper_voice(settings: "RuntimeSettings") -> Any:
    from piper.voice import PiperVoice

    vid = effective_piper_voice_id(settings.voice_name, settings.piper_voice)
    path = resolve_piper_onnx_path_from_settings(settings)
    if path is None:
        raise FileNotFoundError(
            f"Piper model not found for voice {vid!r}. "
            f"Expected {default_piper_data_dir() / (vid + '.onnx')} or set piper_model_path in config. "
            "Run: python scripts/prefetch_piper_voice.py",
        )
    key = (str(path.resolve()), bool(settings.piper_cuda))
    if key not in _voice_cache:
        _voice_cache[key] = PiperVoice.load(str(path), use_cuda=bool(settings.piper_cuda))
    return _voice_cache[key]


def resolve_piper_onnx_path_from_settings(settings: "RuntimeSettings") -> Optional[Path]:
    vid = effective_piper_voice_id(settings.voice_name, settings.piper_voice)
    return resolve_piper_onnx_path(
        voice_id=vid,
        piper_model_dir=settings.piper_model_dir,
        piper_model_path=settings.piper_model_path,
    )


def _piper_length_scale_for_speaking_rate(speaking_rate: float) -> float:
    """Map user rate (0.5–3.0, 1.0 = default) to Piper ``length_scale``. Higher scale = slower speech."""
    r = max(0.5, min(3.0, float(speaking_rate)))
    if abs(r - 1.0) < 1e-4:
        return 1.0
    # Faster speech => shorter durations => lower length_scale (see Piper / onnx docs).
    return 1.0 / r


def synthesize_piper_to_path(path: Path, text: str, settings: "RuntimeSettings") -> None:
    """Synthesize ``text`` to a PCM WAV file at ``path``.

    Speaking tempo is baked in via ``SynthesisConfig.length_scale`` so we do **not** need the
    librosa phase-vocoder pass in :mod:`narrator.wav_speaking_rate` (which sounded chorusy on every
    new utterance after the user changed rate once).
    """
    from piper.config import SynthesisConfig

    voice = _get_piper_voice(settings)
    ls = _piper_length_scale_for_speaking_rate(settings.speaking_rate)
    syn = SynthesisConfig(
        length_scale=ls,
        volume=max(0.0, min(1.0, float(settings.audio_volume))),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        voice.synthesize_wav(text, wav, syn_config=syn)
