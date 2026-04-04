"""High-quality listen path: record microphone, transcribe with faster-whisper, type result.

Install: ``pip install "narrator[listen-whisper]"`` (recommended with ``narrator[listen]`` for punctuation refine).
"""

from __future__ import annotations

import builtins
import contextlib
import logging
import os
import sys
import tempfile
import threading
import wave
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator, Optional

from pynput.keyboard import Controller

if TYPE_CHECKING:
    from narrator.settings import RuntimeSettings

logger = logging.getLogger(__name__)

_model_cache: dict[tuple[str, str, str], Any] = {}
_torch_dll_warn_emitted: bool = False
# Set when torch raises OSError (e.g. WinError 1114 on c10.dll). CUDA Whisper init can then hard-crash Python.
_force_whisper_cpu: bool = False
_whisper_cpu_forced_logged: bool = False
_win32_auto_cpu_logged: bool = False

WHISPER_SAMPLE_RATE = 16000
# Reject only pathological clips; shorter than ~0.25s was dropping quick phrases.
WHISPER_MIN_SAMPLES = 800  # 0.05 s at 16 kHz mono
# Periodic Whisper chunks: need enough audio per slice so the model is not useless.
WHISPER_STREAM_MIN_SAMPLES = WHISPER_SAMPLE_RATE  # 1.0 s at 16 kHz mono


@contextlib.contextmanager
def _torch_import_oserror_means_optional() -> Iterator[None]:
    """CTranslate2's optional ``torch`` import only catches ``ImportError``; Windows DLL errors use ``OSError``.

    Whisper inference uses the CTranslate2 runtime and does not need PyTorch tensors. Map ``OSError`` to
    ``ImportError`` so the stack loads and ``torch_is_available`` is false in ``ctranslate2.specs``.
    """
    real_import = builtins.__import__

    def _shim(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
        global _torch_dll_warn_emitted, _force_whisper_cpu
        if name == "torch" or name.startswith("torch."):
            try:
                return real_import(name, globals, locals, fromlist, level)
            except OSError as e:
                _force_whisper_cpu = True
                if not _torch_dll_warn_emitted:
                    _torch_dll_warn_emitted = True
                    logger.warning(
                        "PyTorch native libraries failed to load (%s). Continuing without PyTorch — CTranslate2 "
                        "Whisper does not require them. Install VC++ Redistributable x64 or reinstall CPU torch if "
                        "you need other features.",
                        e,
                    )
                raise ImportError("torch native library load failed (treated as optional)") from e
        return real_import(name, globals, locals, fromlist, level)

    builtins.__import__ = _shim
    try:
        yield
    finally:
        builtins.__import__ = real_import


def _preload_torch_dll_paths_windows() -> None:
    """Register ``torch/lib`` on the DLL search path before ``import torch`` (Windows, Python 3.8+)."""
    if sys.platform != "win32":
        return
    try:
        import site
        import sysconfig
    except ImportError:
        return
    roots: list[Path] = []
    try:
        u = site.getusersitepackages()
        if u:
            roots.append(Path(u))
    except Exception:
        pass
    try:
        roots.extend(Path(p) for p in site.getsitepackages())
    except Exception:
        pass
    try:
        roots.append(Path(sysconfig.get_path("purelib")))
    except Exception:
        pass
    seen: set[str] = set()
    for base in roots:
        lib = base / "torch" / "lib"
        try:
            key = str(lib.resolve())
        except OSError:
            continue
        if key in seen or not lib.is_dir():
            continue
        seen.add(key)
        if not (lib / "c10.dll").exists():
            continue
        try:
            os.add_dll_directory(str(lib))
        except OSError:
            continue


def _log_windows_torch_dll_failure(exc: BaseException) -> None:
    """Explain WinError 1114 / c10.dll issues (VC++ runtime, Python version, reinstall)."""
    low = str(exc).lower()
    if sys.platform == "win32" and (
        "1114" in low or "c10.dll" in low or ("dll" in low and "load" in low)
    ):
        logger.error(
            "PyTorch failed to load native DLLs (Whisper uses faster-whisper → CTranslate2 → PyTorch). "
            "Try in order:\n"
            "  1) Install/update Microsoft Visual C++ Redistributable (x64): "
            "https://aka.ms/vs/17/release/vc_redist.x64.exe\n"
            "  2) Prefer Python 3.12 or 3.11 — PyTorch for 3.14 is often experimental: "
            "py -3.12 -m venv .venv && .venv\\Scripts\\activate && pip install -e \".[listen-whisper]\"\n"
            "  3) Reinstall CPU PyTorch: "
            "pip install --force-reinstall torch --index-url https://download.pytorch.org/whl/cpu\n"
            "Original error: %s",
            exc,
        )
    else:
        logger.error("Could not import Whisper / PyTorch dependencies: %s", exc)


def _cuda_available() -> bool:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        pass
    try:
        import torch

        return bool(torch.cuda.is_available())
    except (ImportError, OSError):
        return False


def _pick_device(settings: "RuntimeSettings") -> str:
    """Resolve device; force CPU if PyTorch DLLs failed; on Windows, ``auto`` defaults to CPU (CUDA can hard-crash)."""
    global _whisper_cpu_forced_logged, _win32_auto_cpu_logged
    d = settings.whisper_device
    if _force_whisper_cpu:
        if d == "cuda":
            logger.warning(
                "Whisper: using CPU instead of cuda — PyTorch/native DLLs failed to load; CUDA inference can crash "
                "the app on this machine.",
            )
            return "cpu"
        if d == "auto" and not _whisper_cpu_forced_logged:
            _whisper_cpu_forced_logged = True
            logger.info(
                "Whisper: using CPU (PyTorch failed to load; avoiding CUDA for stability). Override with a working "
                "PyTorch install if you need GPU.",
            )
        return "cpu"
    if d != "auto":
        return d
    # Windows: CTranslate2 + CUDA frequently takes down the whole process (no traceback) on broken drivers / stacks.
    if sys.platform == "win32":
        if not _win32_auto_cpu_logged:
            _win32_auto_cpu_logged = True
            logger.info(
                "Whisper: device=cpu (default on Windows for stability). Pass --whisper-device cuda to use the GPU.",
            )
        return "cpu"
    return "cuda" if _cuda_available() else "cpu"


def _compute_types_for_device(device: str) -> list[str]:
    """Prefer fast dtypes; CUDA may not support float16 on some GPUs/drivers — try fallbacks."""
    if device == "cuda":
        return ["float16", "int8_float16", "float32", "int8"]
    # Windows CPU: prefer int8_float32 over float32 for speed; fall back if load fails.
    if sys.platform == "win32":
        return ["int8_float32", "float32", "int8"]
    return ["int8"]


def _get_model(settings: "RuntimeSettings") -> Any:
    _preload_torch_dll_paths_windows()
    try:
        with _torch_import_oserror_means_optional():
            from faster_whisper import WhisperModel
    except OSError as e:
        _log_windows_torch_dll_failure(e)
        raise

    device = _pick_device(settings)
    name = settings.whisper_model.strip() or "base"
    compute_candidates = _compute_types_for_device(device)
    for compute_type in compute_candidates:
        key = (name, device, compute_type)
        if key in _model_cache:
            return _model_cache[key]
        logger.info(
            "Loading Whisper model %r (device=%s, compute_type=%s); first run may download weights.",
            name,
            device,
            compute_type,
        )
        try:
            model = WhisperModel(name, device=device, compute_type=compute_type)
        except (ValueError, RuntimeError, OSError) as e:
            err = str(e).lower()
            if device == "cuda" and (
                "float16" in err or "compute type" in err or "backend" in err
            ):
                logger.info("Whisper: retrying with next compute type (%s).", e)
                continue
            # CPU: try next compute type in the list (Windows often needs float32 before int8).
            if device == "cpu" and compute_type != compute_candidates[-1]:
                logger.info("Whisper: retrying with next compute type (%s).", e)
                continue
            raise
        _model_cache[key] = model
        return model
    raise RuntimeError(f"Whisper: could not load model {name!r} on {device}")


def whisper_transcribe_kwargs(settings: "RuntimeSettings") -> dict[str, Any]:
    """Arguments for ``WhisperModel.transcribe`` from :class:`~narrator.settings.RuntimeSettings`."""
    beam = max(1, min(20, int(settings.whisper_beam_size)))
    kw: dict[str, Any] = {
        "language": "en",
        "beam_size": beam,
        "vad_filter": False,
        # Dictation-only: skip timestamp token path for faster inference.
        "without_timestamps": True,
    }
    p = (settings.whisper_initial_prompt or "").strip()
    if p:
        kw["initial_prompt"] = p
    if settings.whisper_greedy:
        kw["temperature"] = (0.0,)
    return kw


def _write_wav_pcm16(path: Path, samples: Any, sample_rate: int) -> None:
    import numpy as np

    samples = np.clip(samples.astype(np.float64), -1.0, 1.0)
    pcm = (samples * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())


def record_whisper_session_to_wav(stop_event: threading.Event, settings: "RuntimeSettings") -> Optional[Path]:
    """
    Capture from the default microphone until ``stop_event`` is set; write a temp WAV (16 kHz mono PCM16).

    Returns ``None`` on failure or too-short audio. Used by the in-process and Windows subprocess Whisper paths.
    """
    try:
        import numpy as np
        import sounddevice as sd
    except ImportError as e:
        logger.error(
            "Whisper listen requires optional packages. Install with: pip install \"narrator[listen-whisper]\" (%s)",
            e,
        )
        return None

    chunks: list[Any] = []

    def callback(indata: Any, frames: int, _time: Any, status: Any) -> None:
        if status:
            logger.warning("Audio input: %s", status)
        chunks.append(indata.copy().flatten())

    logger.info(
        "Whisper: recording — speak toward the mic; press the listen hotkey again to transcribe and insert.",
    )

    try:
        default_in = sd.query_devices(kind="input")
        logger.info(
            "Whisper: default input device: %s (index %s)",
            default_in.get("name", "?"),
            default_in.get("index", "?"),
        )
    except Exception as e:
        logger.debug("Could not query audio input device: %s", e)

    try:
        with sd.InputStream(
            samplerate=WHISPER_SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=1024,
            callback=callback,
        ):
            _whisper_cue_beep(settings, start=True)
            stop_event.wait()
    except OSError as e:
        logger.error(
            "Microphone open failed: %s — check Windows Settings → Privacy → Microphone (allow Python / terminal).",
            e,
        )
        return None

    _whisper_cue_beep(settings, start=False)

    if not chunks:
        logger.error(
            "Whisper: no audio captured. If you only pressed the listen hotkey once, press it again after speaking "
            "to stop recording and run transcription.",
        )
        return None

    audio = np.concatenate(chunks)
    dur_s = float(audio.size) / WHISPER_SAMPLE_RATE
    logger.info("Whisper: captured ~%.2f s of audio (%d samples).", dur_s, int(audio.size))
    if audio.size < WHISPER_MIN_SAMPLES:
        logger.warning(
            "Recording too short (<%d ms of audio); skipping transcription. Hold the listen session a bit longer.",
            int(1000 * WHISPER_MIN_SAMPLES / WHISPER_SAMPLE_RATE),
        )
        return None

    fd, path_str = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    tmp = Path(path_str)
    try:
        _write_wav_pcm16(tmp, audio, WHISPER_SAMPLE_RATE)
        return tmp
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def iter_whisper_audio_chunks(
    stop_event: threading.Event,
    settings: "RuntimeSettings",
    chunk_interval_sec: float,
) -> Iterator[Any]:
    """
    Capture mic until ``stop_event`` is set (second listen hotkey = end session, not "transcribe now").

    While recording, yields each **new** slice of audio (float32 mono 16 kHz) on a timer — at least ~1 s per
    periodic slice. After ``stop_event``, yields a final shorter slice of any **unprocessed** tail.

    Yields numpy 1-D float32 arrays (requires numpy + sounddevice, same as non-streaming capture).
    """
    try:
        import numpy as np
        import sounddevice as sd
    except ImportError as e:
        logger.error(
            "Whisper listen requires optional packages. Install with: pip install \"narrator[listen-whisper]\" (%s)",
            e,
        )
        return

    if chunk_interval_sec <= 0:
        return

    chunks: list[Any] = []
    chunk_lock = threading.Lock()

    def callback(indata: Any, frames: int, _time: Any, status: Any) -> None:
        if status:
            logger.warning("Audio input: %s", status)
        with chunk_lock:
            chunks.append(indata.copy().flatten())

    logger.info(
        "Whisper: chunked recording — text is typed automatically every ~%.1fs of new audio. "
        "Press the listen hotkey again only to end the session (remaining audio is transcribed, then stop).",
        chunk_interval_sec,
    )

    try:
        default_in = sd.query_devices(kind="input")
        logger.info(
            "Whisper: default input device: %s (index %s)",
            default_in.get("name", "?"),
            default_in.get("index", "?"),
        )
    except Exception as e:
        logger.debug("Could not query audio input device: %s", e)

    last_processed = 0

    def _concat_locked() -> Any:
        with chunk_lock:
            if not chunks:
                return np.empty(0, dtype=np.float32)
            return np.concatenate(chunks)

    try:
        with sd.InputStream(
            samplerate=WHISPER_SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=1024,
            callback=callback,
        ):
            _whisper_cue_beep(settings, start=True)
            while True:
                if stop_event.wait(timeout=chunk_interval_sec):
                    break
                audio = _concat_locked()
                new = audio[last_processed:]
                if int(new.size) >= WHISPER_STREAM_MIN_SAMPLES:
                    yield new
                    last_processed = int(audio.size)

        audio = _concat_locked()
        new = audio[last_processed:]
        if int(new.size) >= WHISPER_MIN_SAMPLES:
            yield new
    except OSError as e:
        logger.error(
            "Microphone open failed: %s — check Windows Settings → Privacy → Microphone (allow Python / terminal).",
            e,
        )
        return

    _whisper_cue_beep(settings, start=False)

    if not chunks:
        logger.error(
            "Whisper: no audio captured. If you only pressed the listen hotkey once, press it again after speaking "
            "to stop recording.",
        )


def apply_whisper_text_to_focus(
    text: str,
    settings: "RuntimeSettings",
    *,
    refine_punctuation: Optional[bool] = None,
) -> None:
    """Optional neural refine, then type into the focused field."""
    if not text.strip():
        return
    kb = Controller()
    do_refine = settings.listen_whisper_refine_punctuation if refine_punctuation is None else refine_punctuation
    if do_refine:
        try:
            from narrator.listen.punctuate_neural import neural_punctuation_active, restore_document

            if neural_punctuation_active():
                refined = restore_document(text).strip()
                if refined:
                    text = refined
        except Exception as e:
            logger.debug("Optional punctuation refine: %s", e)

    from narrator.listen.session import _type_into_focus

    _type_into_focus(kb, text)
    if text and not text.endswith(("\n", " ")):
        kb.type(" ")


def _transcribe_wav_path_with_model(model: Any, wav_path: Path, settings: "RuntimeSettings") -> str:
    segments, _info = model.transcribe(str(wav_path), **whisper_transcribe_kwargs(settings))
    return "".join(seg.text for seg in segments).strip()


def transcribe_numpy_to_text_inplace(model: Any, audio: Any, settings: "RuntimeSettings") -> str:
    """Write *audio* to a temp WAV, run ``model.transcribe``, delete file; return stripped text."""
    fd, path_str = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    tmp = Path(path_str)
    try:
        _write_wav_pcm16(tmp, audio, WHISPER_SAMPLE_RATE)
        return _transcribe_wav_path_with_model(model, tmp, settings)
    finally:
        tmp.unlink(missing_ok=True)


def _whisper_cue_beep(settings: "RuntimeSettings", *, start: bool) -> None:
    """Short Windows beeps so the two-step listen hotkey is obvious (respects ``beep_on_failure``)."""
    if not settings.beep_on_failure:
        return
    if sys.platform != "win32":
        return
    try:
        import winsound

        winsound.Beep(880 if start else 523, 70)
    except Exception:
        pass


def whisper_listen_session(stop_event: threading.Event, settings: "RuntimeSettings") -> None:
    """
    Record from the default microphone until ``stop_event`` is set, transcribe, optionally
    refine punctuation, then type into the focused field.

    If ``settings.whisper_chunk_interval_seconds`` > 0, transcribe and type periodically while
    recording (see :func:`iter_whisper_audio_chunks`). On Windows the isolated Whisper worker
    handles chunked mode the same way (repeated transcribe jobs).
    """
    if sys.platform == "win32":
        from narrator.listen import whisper_subprocess

        whisper_subprocess.whisper_listen_session_windows(stop_event, settings)
        return

    if settings.whisper_chunk_interval_seconds > 0:
        try:
            model = _get_model(settings)
        except OSError:
            return
        except Exception as e:
            logger.exception("Whisper: could not load model: %s", e)
            return

        for chunk in iter_whisper_audio_chunks(stop_event, settings, settings.whisper_chunk_interval_seconds):
            text = transcribe_numpy_to_text_inplace(model, chunk, settings)
            if text:
                logger.info("Whisper: chunk transcribed (~%.2fs audio).", float(chunk.size) / WHISPER_SAMPLE_RATE)
                apply_whisper_text_to_focus(text, settings, refine_punctuation=False)
            else:
                logger.debug("Whisper: empty chunk skipped.")
        return

    try:
        model = _get_model(settings)
    except OSError:
        return
    except Exception as e:
        logger.exception("Whisper: could not load model: %s", e)
        return

    tmp = record_whisper_session_to_wav(stop_event, settings)
    if tmp is None:
        return
    try:
        segments, info = model.transcribe(str(tmp), **whisper_transcribe_kwargs(settings))
        text = "".join(seg.text for seg in segments).strip()
        if not text:
            logger.info("Whisper: empty transcript.")
            return
        logger.info(
            "Whisper: transcribed (~%.1fs audio, lang=%s).",
            info.duration,
            info.language,
        )
        apply_whisper_text_to_focus(text, settings)
    finally:
        tmp.unlink(missing_ok=True)
