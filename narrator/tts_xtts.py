"""Optional Coqui XTTS neural TTS (``pip install narrator[speak-xtts]``)."""

from __future__ import annotations

import inspect
import logging
import os
import sys
import tempfile
import threading
import wave
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from narrator.settings import RuntimeSettings

logger = logging.getLogger(__name__)

# Smaller / lighter than xtts_v2 (Coqui registry: multilingual XTTS v1.1). Override via `xtts_model` in config.
DEFAULT_XTTS_MODEL_ID = "tts_models/multilingual/multi-dataset/xtts_v1.1"


def is_xtts_available() -> bool:
    """True if ``coqui-tts`` can be imported and loads (import check only; does not download weights)."""
    try:
        import TTS  # noqa: F401
        return True
    except Exception:
        # ImportError if missing; OSError if torch DLLs break on this machine.
        return False


_lock = threading.Lock()
_clone_ref_lock = threading.Lock()
_tts = None
_cached_model: Optional[str] = None
_cached_gpu: Optional[bool] = None

# XTTS v1.1 has no built-in named speakers (unlike v2’s speakers_xtts.pth). Cloning needs ~3–10s of reference audio.
_XTTS_CLONE_REF_TEXT = "Hello. This short clip is the default voice reference for speech synthesis."
_XTTS_CLONE_REF_NAME = "xtts_clone_reference.wav"


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

    # Coqui may block on stdin for CPML unless agreed (breaks GUI / hotkey apps).
    if not (os.environ.get("COQUI_TOS_AGREED") or "").strip():
        os.environ["COQUI_TOS_AGREED"] = "1"
        logger.info(
            "Set COQUI_TOS_AGREED=1 for non-interactive download/load; see https://coqui.ai/cpml "
            "(non-commercial or commercial license)."
        )

    from TTS.api import TTS

    model = settings.xtts_model.strip() or DEFAULT_XTTS_MODEL_ID
    gpu = _gpu_flag(settings)
    with _lock:
        if _tts is not None and _cached_model == model and _cached_gpu == gpu:
            return _tts
        logger.info(
            "Loading XTTS model %r (gpu=%s). First run downloads a large checkpoint; this can take several minutes.",
            model,
            gpu,
        )
        if not gpu:
            logger.warning(
                "XTTS will use CPU only (PyTorch reports no CUDA) — expect high CPU and near-idle GPU in "
                "Task Manager. On NVIDIA hardware, install CUDA PyTorch: pip install --upgrade --force-reinstall "
                "torch torchaudio --index-url https://download.pytorch.org/whl/cu124 "
                "(see docs/SETUP.md).",
            )
        _tts = TTS(model_name=model, gpu=gpu, progress_bar=False)
        try:
            import torch

            dev = "cuda" if gpu and torch.cuda.is_available() else "cpu"
            _tts = _tts.to(dev)
        except Exception as e:
            logger.debug("Coqui TTS .to(device) skipped: %s", e)
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


def _default_xtts_clone_ref_dir() -> Path:
    if sys.platform == "win32":
        la = os.environ.get("LOCALAPPDATA", "")
        if la:
            return Path(la) / "narrator" / "xtts"
    return Path.home() / ".local" / "share" / "narrator" / "xtts"


def _ensure_xtts_clone_reference_wav(settings: "RuntimeSettings") -> Path:
    """
    XTTS v1.x often exposes no ``speakers`` list — inference uses ``speaker_wav`` only.
    If Piper is installed, synthesize a short reference once and cache it under local app data.
    """
    outp = _default_xtts_clone_ref_dir() / _XTTS_CLONE_REF_NAME
    with _clone_ref_lock:
        if outp.is_file() and outp.stat().st_size > 2000:
            return outp
        from narrator.tts_piper import (
            is_piper_available,
            resolve_piper_onnx_path_from_settings,
            synthesize_piper_to_path,
        )

        if not is_piper_available():
            raise RuntimeError(
                "This XTTS checkpoint has no built-in speakers (typical for xtts_v1.1). "
                "Either set xtts_speaker_wav to a short WAV for cloning, install Piper and prefetch a voice "
                "(so Narrator can build a default reference), or set xtts_model to "
                "tts_models/multilingual/multi-dataset/xtts_v2 for named speakers like Ana Florence."
            )
        onnx = resolve_piper_onnx_path_from_settings(settings)
        if onnx is None:
            raise RuntimeError(
                "XTTS needs a clone reference WAV. Piper ONNX not found — run scripts/prefetch_piper_voice.py "
                "or set xtts_speaker_wav / xtts_model=xtts_v2."
            )
        outp.parent.mkdir(parents=True, exist_ok=True)
        tmp = outp.with_suffix(".tmp.wav")
        try:
            synthesize_piper_to_path(tmp, _XTTS_CLONE_REF_TEXT, settings)
            tmp.replace(outp)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        logger.info("Wrote default XTTS clone reference (via Piper): %s", outp)
        return outp


# Blend micro-segments so naive sample joins do not click / thud between Coqui runs.
_XTTS_CROSSFADE_MS = 24.0


def _crossfade_join_int16_segments(
    segments: list,
    *,
    sample_rate: int,
    channels: int,
    crossfade_ms: float = _XTTS_CROSSFADE_MS,
) -> object:
    """Join int16 PCM segments with linear crossfade at each boundary (mono or interleaved stereo)."""
    import numpy as np

    if not segments:
        return np.array([], dtype=np.int16)
    if len(segments) == 1:
        return segments[0]

    n_frames = max(4, int(sample_rate * (crossfade_ms / 1000.0)))
    fade_len = n_frames * channels  # int16 sample count (interleaved)

    def _join_pair(a: object, b: object) -> object:
        a = np.asarray(a, dtype=np.float32).ravel()
        b = np.asarray(b, dtype=np.float32).ravel()
        if len(a) < fade_len + 8 or len(b) < fade_len + 8:
            return np.concatenate([a, b])
        n = fade_len
        a_tail = a[-n:]
        b_head = b[:n]
        b_rest = b[n:]
        at = a[:-n]
        if channels == 1:
            t = np.linspace(0.0, 1.0, n, dtype=np.float32)
        else:
            ramp = np.linspace(0.0, 1.0, n_frames, dtype=np.float32)
            t = np.repeat(ramp, channels)
        blended = a_tail * (1.0 - t) + b_head * t
        return np.concatenate([at, blended, b_rest])

    acc = segments[0]
    for seg in segments[1:]:
        acc = _join_pair(acc, seg)
    return np.clip(np.round(acc), -32768, 32767).astype(np.int16)


def _concat_wav_files(paths: list[Path], out: Path) -> None:
    """Concatenate PCM WAVs (same rate/channels/width) with short crossfades between parts."""
    import numpy as np

    if not paths:
        raise ValueError("no WAV paths to concatenate")
    segments: list = []
    params: tuple[int, int, int] | None = None
    for p in paths:
        with wave.open(str(p), "rb") as wf:
            nch, sw, fr = wf.getnchannels(), wf.getsampwidth(), wf.getframerate()
            if params is None:
                params = (nch, sw, fr)
            elif (nch, sw, fr) != params:
                raise ValueError("WAV format mismatch in XTTS concat")
            raw = wf.readframes(wf.getnframes())
            if sw != 2:
                raise ValueError("XTTS concat expects 16-bit PCM")
            segments.append(np.frombuffer(raw, dtype=np.int16))
    nch, sw, fr = params  # type: ignore[misc]
    if nch not in (1, 2):
        x = np.concatenate(segments) if segments else np.array([], dtype=np.int16)
    else:
        x = _crossfade_join_int16_segments(segments, sample_rate=fr, channels=nch)
    with wave.open(str(out), "wb") as wf:
        wf.setnchannels(nch)
        wf.setsampwidth(sw)
        wf.setframerate(fr)
        wf.writeframes(np.asarray(x, dtype=np.int16).tobytes())


def _tts_to_file_one(
    tts,
    text: str,
    out_path: Path,
    *,
    speaker: Optional[str],
    spath: Optional[Path],
    lang: str,
    split_sentences: bool,
    use_inference_mode: bool,
) -> None:
    common: dict = dict(
        text=text,
        file_path=str(out_path),
        language=lang,
        split_sentences=split_sentences,
    )
    if "speed" in inspect.signature(tts.tts_to_file).parameters:
        common["speed"] = 1.0

    def _run() -> None:
        if spath is not None:
            tts.tts_to_file(speaker_wav=str(spath), **common)
        else:
            tts.tts_to_file(speaker=speaker, **common)

    if use_inference_mode:
        try:
            import torch

            with torch.inference_mode():
                _run()
        except Exception:
            _run()
    else:
        _run()


def synthesize_xtts_to_path(path: Path, text: str, settings: "RuntimeSettings") -> None:
    """Write synthesized speech to ``path`` (WAV). Uses built-in speakers (v2), ``speaker_wav``, or a Piper-built ref for v1.1."""
    from narrator.speak_chunking import XTTS_MAX_CHARS_PER_SEGMENT, iter_tts_chunks

    tts = get_tts(settings)
    speaker_wav = (settings.xtts_speaker_wav or "").strip() or None

    if speaker_wav:
        spath = Path(speaker_wav)
        if not spath.is_file():
            raise FileNotFoundError(f"xtts_speaker_wav not found: {spath}")
        speaker = None
    else:
        names = list_speakers(settings)
        if names:
            spath = None
            speaker = (settings.voice_name or "").strip() or (settings.xtts_speaker or "").strip() or "Ana Florence"
        else:
            # v1.1 (and similar): no Ana Florence — clone from Piper ref or user wav only.
            spath = _ensure_xtts_clone_reference_wav(settings)
            speaker = None

    lang = (settings.xtts_language or "en").strip() or "en"

    logger.info(
        "XTTS synthesize: speaker=%r language=%s (clone=%s); tempo via post-process stretch",
        speaker if spath is None else f"wav:{spath.name}",
        lang,
        bool(spath),
    )

    # Coqui enforces ~400 tokens per call; academic PDFs blow past that below 768 chars. Micro-split here
    # so every forward pass stays under budget, then concatenate WAVs (worker chunking is coarse).
    cap = XTTS_MAX_CHARS_PER_SEGMENT
    pieces = [p for p in iter_tts_chunks(text.strip(), cap, min_chunk_floor=40) if p.strip()]
    if not pieces:
        raise ValueError("empty text for XTTS")

    coqui_split = bool(getattr(settings, "xtts_split_sentences", False))
    infer_mode = bool(getattr(settings, "xtts_torch_inference_mode", True))

    if len(pieces) == 1:
        _tts_to_file_one(
            tts,
            pieces[0],
            path,
            speaker=speaker,
            spath=spath,
            lang=lang,
            split_sentences=coqui_split,
            use_inference_mode=infer_mode,
        )
    else:
        tmp_paths: list[Path] = []
        try:
            for piece in pieces:
                fd, name = tempfile.mkstemp(suffix=".wav")
                os.close(fd)
                tp = Path(name)
                tmp_paths.append(tp)
                _tts_to_file_one(
                    tts,
                    piece,
                    tp,
                    speaker=speaker,
                    spath=spath,
                    lang=lang,
                    split_sentences=coqui_split,
                    use_inference_mode=infer_mode,
                )
            _concat_wav_files(tmp_paths, path)
        finally:
            for tp in tmp_paths:
                tp.unlink(missing_ok=True)

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
