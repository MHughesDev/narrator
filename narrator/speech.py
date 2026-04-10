"""WinRT offline speech synthesis + interruptible WAV playback (Win32 ``waveOut``; ``winsound`` for legacy purge)."""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import winsound
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Tuple, Union
from xml.sax.saxutils import escape

from winrt.windows.media.speechsynthesis import SpeechSynthesizer
from winrt.windows.storage.streams import DataReader, InputStreamOptions

from narrator.protocol import SHUTDOWN, SPEAK_RATE_DOWN, SPEAK_RATE_UP, SPEAK_TOGGLE
from narrator.voxcpm_text_pipeline import apply_voxcpm_style_text_for_tts

if TYPE_CHECKING:
    from narrator.playback_result import PlayWavResult
    from narrator.settings import RuntimeSettings

logger = logging.getLogger(__name__)

# After chunk-context trim, ramp the first ~12 ms to avoid a hard edge at the cut.
_CHUNK_CONTEXT_POST_TRIM_FADE_MS = 12.0


def _clamp_volume(v: float) -> float:
    return max(0.0, min(1.0, v))


def _infer_ssml_lang(voice_name: str) -> str:
    n = voice_name.lower()
    if "united kingdom" in n or "en-gb" in n or " (uk)" in n:
        return "en-GB"
    return "en-US"


def _build_ssml(text: str, voice_name: Optional[str], lang: str = "en-US") -> str:
    safe = escape(text, {'"': "&quot;", "'": "&apos;", "<": "&lt;", ">": "&gt;", "&": "&amp;"})
    if voice_name:
        vn = escape(voice_name, {'"': "&quot;", "&": "&amp;"})
        return (
            f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' "
            f"xml:lang='{lang}'><voice name=\"{vn}\">{safe}</voice></speak>"
        )
    return f"<speak version='1.0' xml:lang='{lang}'>{safe}</speak>"


def _norm_voice_key(s: str) -> str:
    return " ".join(s.split()).lower()


def _resolve_voice_information(name: str):
    """Map user ``--voice`` string to a WinRT ``VoiceInformation`` from ``SpeechSynthesizer.all_voices``."""
    from winrt.windows.media.speechsynthesis import SpeechSynthesizer

    raw = name.strip()
    if not raw:
        return None

    vs = SpeechSynthesizer.all_voices
    items = [vs.get_at(i) for i in range(vs.size)]
    key = _norm_voice_key(raw)

    for v in items:
        if v.display_name.strip() == raw:
            return v
    for v in items:
        desc = (v.description or "").strip()
        if desc == raw:
            return v

    for v in items:
        if _norm_voice_key(v.display_name) == key:
            return v
    for v in items:
        desc = (v.description or "").strip()
        if _norm_voice_key(desc) == key:
            return v

    for v in items:
        vid = v.id or ""
        tail = vid.rsplit("\\", 1)[-1]
        if raw == vid or raw == tail or _norm_voice_key(tail) == key:
            return v

    partial_matches = []
    for v in items:
        dn = _norm_voice_key(v.display_name)
        dd = _norm_voice_key(v.description or "")
        if key in dn or key in dd or dn in key or (dd and key in dd):
            partial_matches.append(v)
    if len(partial_matches) == 1:
        return partial_matches[0]
    if len(partial_matches) > 1:
        for v in partial_matches:
            if (v.language or "").lower().startswith("en-us"):
                return v
        return partial_matches[0]

    return None


async def _synthesize_to_bytes(
    text: str,
    *,
    settings: "RuntimeSettings",
) -> bytes:
    from narrator.speak_prosody import build_winrt_ssml_with_breaks

    voice_name = settings.voice_name
    audio_volume = settings.audio_volume

    synth = SpeechSynthesizer()
    opts = synth.options
    # Neutral WinRT tempo; ``wav_speaking_rate`` applies user rate without pitch shift.
    opts.speaking_rate = 1.0
    opts.audio_volume = _clamp_volume(audio_volume)

    use_ssml_pauses = bool(
        getattr(settings, "speak_insert_line_pauses", True)
        and getattr(settings, "speak_winrt_use_ssml_breaks", True)
    )

    if use_ssml_pauses:
        line_ms = max(50, min(2000, int(getattr(settings, "speak_pause_line_ms", 320))))
        para_ms = max(80, min(3000, int(getattr(settings, "speak_pause_paragraph_ms", 520))))
        between_lines = bool(getattr(settings, "speak_pause_between_lines", False))
        lang = _infer_ssml_lang(voice_name) if voice_name else "en-US"
        if voice_name:
            resolved = _resolve_voice_information(voice_name)
            if resolved is not None:
                synth.voice = resolved
                logger.info(
                    "TTS voice: %s | %s | %s",
                    resolved.display_name,
                    resolved.language,
                    (resolved.description or "").strip(),
                )
                ssml = build_winrt_ssml_with_breaks(
                    text,
                    voice_name=None,
                    lang=lang,
                    line_ms=line_ms,
                    paragraph_ms=para_ms,
                    between_lines=between_lines,
                )
                stream = await synth.synthesize_ssml_to_stream_async(ssml)
            else:
                logger.warning(
                    "Voice %r is not in WinRT AllVoices — you are almost certainly hearing the DEFAULT voice, "
                    "not this one. Natural/Neural voices (e.g. Narrator's list) are often missing from AllVoices; "
                    "use names from `python -m narrator --list-voices` (WinRT section) for reliable switching.",
                    voice_name,
                )
                ssml = build_winrt_ssml_with_breaks(
                    text,
                    voice_name=voice_name,
                    lang=lang,
                    line_ms=line_ms,
                    paragraph_ms=para_ms,
                    between_lines=between_lines,
                )
                stream = await synth.synthesize_ssml_to_stream_async(ssml)
        else:
            ssml = build_winrt_ssml_with_breaks(
                text,
                voice_name=None,
                lang="en-US",
                line_ms=line_ms,
                paragraph_ms=para_ms,
                between_lines=between_lines,
            )
            stream = await synth.synthesize_ssml_to_stream_async(ssml)
    elif voice_name:
        resolved = _resolve_voice_information(voice_name)
        if resolved is not None:
            synth.voice = resolved
            logger.info(
                "TTS voice: %s | %s | %s",
                resolved.display_name,
                resolved.language,
                (resolved.description or "").strip(),
            )
            stream = await synth.synthesize_text_to_stream_async(text)
        else:
            logger.warning(
                "Voice %r is not in WinRT AllVoices — you are almost certainly hearing the DEFAULT voice, "
                "not this one. Natural/Neural voices (e.g. Narrator's list) are often missing from AllVoices; "
                "use names from `python -m narrator --list-voices` (WinRT section) for reliable switching.",
                voice_name,
            )
            ssml = _build_ssml(text, voice_name, _infer_ssml_lang(voice_name))
            stream = await synth.synthesize_ssml_to_stream_async(ssml)
    else:
        stream = await synth.synthesize_text_to_stream_async(text)

    size = stream.size
    reader = DataReader(stream)
    reader.input_stream_options = InputStreamOptions.READ_AHEAD
    await reader.load_async(size)
    buf = bytearray(size)
    reader.read_bytes(buf)
    return bytes(buf)


async def _synthesize_to_bytes_cancellable(
    text: str,
    cancel_event: threading.Event,
    *,
    settings: "RuntimeSettings",
) -> bytes:
    task: asyncio.Task[bytes] = asyncio.create_task(
        _synthesize_to_bytes(
            text,
            settings=settings,
        )
    )
    while not task.done():
        await asyncio.sleep(0.05)
        if cancel_event.is_set():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                raise
    return await task


def _apply_pitch_preserving_speaking_rate(path: Path, settings: "RuntimeSettings") -> None:
    from narrator.wav_speaking_rate import apply_pitch_preserving_speaking_rate

    apply_pitch_preserving_speaking_rate(path, settings.speaking_rate)


def _apply_speak_rate_from_queue(settings: "RuntimeSettings", msg: object) -> None:
    from narrator.wav_play_win32 import apply_speak_rate_queue_message

    apply_speak_rate_queue_message(settings, msg)


def _synthesize_winrt_with_queue_cancel(
    text: str,
    path: Path,
    settings: "RuntimeSettings",
    event_queue: queue.Queue,
) -> Tuple[bool, bool]:
    """WinRT TTS: async synthesis in a thread (cancel via asyncio task)."""
    cancel_event = threading.Event()
    result: dict[str, object] = {"exc": None, "cancelled": False}

    def run_synth() -> None:
        async def main() -> None:
            try:
                data = await _synthesize_to_bytes_cancellable(
                    text,
                    cancel_event,
                    settings=settings,
                )
                path.write_bytes(data)
            except asyncio.CancelledError:
                result["cancelled"] = True
            except Exception as e:
                result["exc"] = e

        try:
            asyncio.run(main())
        except Exception as e:
            if result["exc"] is None and not result.get("cancelled"):
                result["exc"] = e

    synth_thread = threading.Thread(target=run_synth, daemon=True, name="narrator-synth")
    synth_thread.start()

    shutdown_requested = False
    while synth_thread.is_alive():
        try:
            msg = event_queue.get(timeout=0.05)
        except queue.Empty:
            continue
        if msg == SPEAK_TOGGLE:
            cancel_event.set()
        elif msg == SHUTDOWN:
            cancel_event.set()
            shutdown_requested = True
        else:
            _apply_speak_rate_from_queue(settings, msg)

    synth_thread.join(timeout=120.0)

    if result.get("exc"):
        logger.error("Synthesis failed: %s", result["exc"])
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return False, shutdown_requested

    if result.get("cancelled"):
        logger.info("Synthesis cancelled")
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return False, shutdown_requested

    if not path.is_file() or path.stat().st_size == 0:
        return False, shutdown_requested

    return True, shutdown_requested


def _synthesize_piper_with_queue_cancel(
    text: str,
    path: Path,
    settings: "RuntimeSettings",
    event_queue: queue.Queue,
) -> Tuple[bool, bool]:
    """Piper ONNX TTS: blocking synthesis in a thread (cancel is best-effort before playback)."""
    cancel_event = threading.Event()
    result: dict[str, object] = {"exc": None, "cancelled": False}

    def run_synth() -> None:
        try:
            from narrator.tts_piper import synthesize_piper_to_path

            synthesize_piper_to_path(path, text, settings)
        except ImportError as e:
            result["exc"] = ImportError(
                "Piper requires optional dependencies. Install with: pip install narrator[speak-piper] (%s)" % e
            )
        except Exception as e:
            result["exc"] = e

    synth_thread = threading.Thread(target=run_synth, daemon=True, name="narrator-synth-piper")
    synth_thread.start()

    shutdown_requested = False
    while synth_thread.is_alive():
        try:
            msg = event_queue.get(timeout=0.05)
        except queue.Empty:
            continue
        if msg == SPEAK_TOGGLE:
            cancel_event.set()
        elif msg == SHUTDOWN:
            cancel_event.set()
            shutdown_requested = True
        else:
            _apply_speak_rate_from_queue(settings, msg)

    synth_thread.join(timeout=600.0)

    if result.get("exc"):
        logger.error("Synthesis failed: %s", result["exc"])
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return False, shutdown_requested

    if cancel_event.is_set():
        logger.info("Piper: cancelled during synthesis; discarding output")
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return False, shutdown_requested

    if not path.is_file() or path.stat().st_size == 0:
        return False, shutdown_requested

    return True, shutdown_requested


def _synthesize_xtts_with_queue_cancel(
    text: str,
    path: Path,
    settings: "RuntimeSettings",
    event_queue: queue.Queue,
) -> Tuple[bool, bool]:
    """Coqui XTTS: blocking synthesis in a thread (cancel is best-effort before playback)."""
    cancel_event = threading.Event()
    result: dict[str, object] = {"exc": None, "cancelled": False}

    def run_synth() -> None:
        try:
            from narrator.tts_xtts import synthesize_xtts_to_path

            synthesize_xtts_to_path(path, text, settings)
        except ImportError as e:
            result["exc"] = ImportError(
                "XTTS requires optional dependencies. Install with: pip install narrator[speak-xtts] (%s)" % e
            )
        except Exception as e:
            result["exc"] = e

    synth_thread = threading.Thread(target=run_synth, daemon=True, name="narrator-synth-xtts")
    synth_thread.start()

    shutdown_requested = False
    while synth_thread.is_alive():
        try:
            msg = event_queue.get(timeout=0.05)
        except queue.Empty:
            continue
        if msg == SPEAK_TOGGLE:
            cancel_event.set()
        elif msg == SHUTDOWN:
            cancel_event.set()
            shutdown_requested = True
        else:
            _apply_speak_rate_from_queue(settings, msg)

    synth_thread.join(timeout=600.0)

    if result.get("exc"):
        err = result["exc"]
        logger.error("Synthesis failed: %s", err)
        es = str(err)
        if "400 tokens" in es or "maximum of 400" in es:
            logger.error(
                "XTTS allows ~400 tokens per segment; ensure narrator is up to date (speak chunk cap for XTTS)."
            )
        if "CUDA" in es or "device-side assert" in es:
            logger.error(
                "XTTS GPU synthesis failed (often oversized or PDF-artifact text). Try "
                "`xtts_device = \"cpu\"` or set `NARRATOR_XTTS_DEVICE=cpu`; long PDFs should use "
                "the default XTTS segment cap (Coqui en ~250 char tokenizer limit)."
            )
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return False, shutdown_requested

    if cancel_event.is_set():
        logger.info("XTTS: cancelled during synthesis; discarding output")
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return False, shutdown_requested

    if not path.is_file() or path.stat().st_size == 0:
        return False, shutdown_requested

    return True, shutdown_requested


def apply_chunk_context_trim(
    path: Path,
    context_prefix: str | None,
    settings: "RuntimeSettings",
) -> None:
    """
    After synthesizing ``context_prefix + utterance`` into ``path``, remove the audio that corresponds
    to ``context_prefix`` so playback is only the new chunk. Uses ``fixed_ms`` trim or a **duration_probe**
    pass (synthesize context-only WAV and drop that many frames) per ``speak_chunk_context_trim_mode``.
    """
    import tempfile

    from narrator import audio_pcm

    if not context_prefix or not str(context_prefix).strip():
        return
    if not getattr(settings, "speak_chunk_context_enabled", False):
        return
    cp = context_prefix.strip()
    mode = str(getattr(settings, "speak_chunk_context_trim_mode", "fixed_ms")).strip().lower()
    if mode == "fixed_ms":
        if audio_pcm.wav_trim_head_ms(path, float(getattr(settings, "speak_chunk_context_trim_ms", 400.0))):
            audio_pcm.wav_fade_in_head_ms(path, _CHUNK_CONTEXT_POST_TRIM_FADE_MS)
        return

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    probe = Path(tmp.name)
    try:
        if not synthesize_to_path_prefetch(cp, probe, settings, context_prefix=None):
            logger.warning("Chunk context probe synthesis failed; skipping trim")
            return
        n_probe = audio_pcm.wav_frame_count(probe)
        n_main = audio_pcm.wav_frame_count(path)
        if n_probe <= 0 or n_probe >= n_main:
            logger.warning(
                "Chunk context trim skipped: probe_frames=%s main_frames=%s",
                n_probe,
                n_main,
            )
            return
        if not audio_pcm.wav_trim_head_frames(path, n_probe):
            logger.warning("Chunk context trim: failed to strip overlap from WAV")
        else:
            audio_pcm.wav_fade_in_head_ms(path, _CHUNK_CONTEXT_POST_TRIM_FADE_MS)
    finally:
        probe.unlink(missing_ok=True)


def synthesize_to_path_prefetch(
    text: str,
    path: Path,
    settings: "RuntimeSettings",
    *,
    context_prefix: str | None = None,
) -> bool:
    """
    Blocking synthesis + speaking-rate post-process (same as a successful
    ``synthesize_with_queue_cancel``), without polling ``event_queue``.

    Used to generate the *next* WAV while the current segment plays so playback can stay continuous.
    """
    text = apply_voxcpm_style_text_for_tts(text, settings)
    try:
        if settings.speak_engine == "piper":
            from narrator.tts_piper import synthesize_piper_to_path

            synthesize_piper_to_path(path, text, settings)
        elif settings.speak_engine == "xtts":
            from narrator.tts_xtts import synthesize_xtts_to_path

            synthesize_xtts_to_path(path, text, settings)
        else:

            async def _winrt_main() -> None:
                data = await _synthesize_to_bytes(text, settings=settings)
                path.write_bytes(data)

            asyncio.run(_winrt_main())
    except ImportError as e:
        logger.error("Synthesis failed: %s", e)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    except Exception as e:
        logger.error("Synthesis failed: %s", e)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return False

    if not path.is_file() or path.stat().st_size == 0:
        return False

    try:
        if settings.speak_engine != "piper":
            _apply_pitch_preserving_speaking_rate(path, settings)
    except Exception as e:
        logger.error("Speaking-rate post-process failed: %s", e)
        return False

    try:
        apply_chunk_context_trim(path, context_prefix, settings)
    except Exception as e:
        logger.warning("Chunk context trim failed: %s", e)

    return True


def synthesize_with_queue_cancel(
    text: str,
    path: Path,
    settings: "RuntimeSettings",
    event_queue: queue.Queue,
    *,
    context_prefix: str | None = None,
) -> Tuple[bool, bool]:
    """
    Synthesize in a background thread; caller (worker) polls the same ``event_queue`` for
    ``speak_toggle``/``shutdown`` and sets a cancel event.

    Returns:
        ``(success, shutdown_requested)`` — success False if cancelled or error; shutdown True if shutdown seen.
    """
    text = apply_voxcpm_style_text_for_tts(text, settings)
    if settings.speak_engine == "piper":
        ok, shutdown_requested = _synthesize_piper_with_queue_cancel(text, path, settings, event_queue)
    elif settings.speak_engine == "xtts":
        ok, shutdown_requested = _synthesize_xtts_with_queue_cancel(text, path, settings, event_queue)
    else:
        ok, shutdown_requested = _synthesize_winrt_with_queue_cancel(text, path, settings, event_queue)

    if ok and not shutdown_requested:
        try:
            # Piper bakes tempo in ``SynthesisConfig.length_scale`` — skip librosa whole-file stretch
            # (phase vocoder) so rate changes do not add persistent chorus on later utterances.
            if settings.speak_engine != "piper":
                _apply_pitch_preserving_speaking_rate(path, settings)
            apply_chunk_context_trim(path, context_prefix, settings)
        except Exception as e:
            logger.error("Speaking-rate post-process or chunk trim failed: %s", e)

    return ok, shutdown_requested


def stop_playback() -> None:
    """Best-effort: purge legacy ``winsound`` playback; TTS uses :mod:`narrator.wav_play_win32`."""
    try:
        winsound.PlaySound(None, winsound.SND_PURGE | winsound.SND_NODEFAULT)
    except Exception as e:
        logger.debug("SND_PURGE: %s", e)


def play_wav_interruptible(
    path: Union[Path, bytes],
    event_queue: queue.Queue,
    *,
    settings: "RuntimeSettings",
    rate_baked_in_wav: float,
    utterance_text: str | None = None,
    crossfade_prev_pcm: bytes | None = None,
) -> "PlayWavResult":
    """PCM via winmm ``waveOut`` (or optional PortAudio); ``waveOutReset`` stops audio reliably."""
    from narrator import audio_debug
    from narrator.wav_play_win32 import play_wav_interruptible as _play

    audio_debug.log_kv(
        "speech.play_wav_interruptible enter",
        path="(bytes)" if isinstance(path, bytes) else str(path),
    )
    try:
        return _play(
            path,
            event_queue,
            settings=settings,
            rate_baked_in_wav=rate_baked_in_wav,
            utterance_text=utterance_text,
            crossfade_prev_pcm=crossfade_prev_pcm,
        )
    finally:
        audio_debug.log_kv(
            "speech.play_wav_interruptible leave",
            path="(bytes)" if isinstance(path, bytes) else str(path),
        )
