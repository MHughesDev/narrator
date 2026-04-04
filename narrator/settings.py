"""Runtime settings (CLI + optional TOML config). Later config files override earlier ones."""

from __future__ import annotations

import os
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional

from narrator.speak_chunking import clamp_chunk_max_chars
from narrator.tts_piper import DEFAULT_PIPER_VOICE_ID
from narrator.user_state import clamp_speaking_rate, load_persisted_speaking_rate


@dataclass
class RuntimeSettings:
    """Effective options for one process run."""

    voice_name: Optional[str] = None
    speaking_rate: float = 1.0
    audio_volume: float = 1.0
    speak_hotkey: str = "ctrl+alt+s"
    listen_hotkey: str = "ctrl+alt+l"
    beep_on_failure: bool = True
    verbose: bool = False
    # Resolved speak backend: "winrt", "xtts", or "piper" (set by build_runtime_settings; never "auto" here).
    speak_engine: str = "winrt"
    xtts_model: str = "tts_models/multilingual/multi-dataset/xtts_v2"
    xtts_speaker: str = "Ana Florence"
    xtts_language: str = "en"
    xtts_device: str = "auto"
    xtts_speaker_wav: Optional[str] = None
    # Piper TTS (optional extra speak-piper): ONNX + JSON from rhasspy/piper-voices.
    piper_voice: str = DEFAULT_PIPER_VOICE_ID
    piper_model_dir: Optional[str] = None
    piper_model_path: Optional[str] = None
    piper_cuda: bool = False
    # Listen: "winrt" = live Windows dictation; "whisper" = record then faster-whisper (higher quality).
    listen_engine: str = "winrt"
    whisper_model: str = "base"
    whisper_device: str = "auto"
    listen_whisper_refine_punctuation: bool = True
    # faster-whisper transcribe() tuning (listen-engine=whisper only)
    whisper_beam_size: int = 3
    whisper_initial_prompt: Optional[str] = None
    whisper_greedy: bool = False
    # Whisper: while recording, transcribe and type every N seconds (0 = one transcript when you stop).
    whisper_chunk_interval_seconds: float = 0.0
    # Speak: preprocess captured text before TTS (see narrator/speak_preprocess.py).
    speak_exclude_hyperlinks: bool = True
    speak_exclude_math: bool = True
    speak_exclude_markup: bool = True
    speak_exclude_citations: bool = True
    speak_exclude_technical: bool = True
    speak_exclude_chrome: bool = True
    speak_exclude_emoji: bool = True
    # Structural pauses before TTS (see narrator/speak_prosody.py). Standard = paragraph breaks only.
    speak_insert_line_pauses: bool = True
    speak_pause_between_lines: bool = False
    speak_winrt_use_ssml_breaks: bool = True
    speak_pause_line_ms: int = 320
    speak_pause_paragraph_ms: int = 520
    # Split long documents into multiple synthesize/play passes (0 = disable; see narrator/speak_chunking.py).
    speak_chunk_max_chars: int = 8000
    # Live speaking-rate hotkeys during playback (see narrator/wav_play_win32.py). Env overrides TOML.
    live_rate_resume_slack_ms: float = 280.0
    post_waveout_close_drain_s: float = 0.35
    # Default True: resume at chunk boundary (waveOutGetPosition often lags the DAC → echo if False).
    live_rate_safe_chunk_discard: bool = True
    # If True: Ctrl+Alt+/- updates rate for the *next* utterance only (no in-play handoff).
    live_rate_defer_during_playback: bool = False
    # In-play tempo engine when defer is False: ``wsola`` (default, pitch-preserving, audiotsm),
    # ``phase_vocoder`` (librosa; may chorus), ``resample`` (tape-speed, pitch shifts).
    live_rate_in_play_engine: str = "wsola"


def load_toml_file(path: Path) -> dict[str, Any]:
    import tomllib

    text = path.read_text(encoding="utf-8")
    return tomllib.loads(text)


def config_paths_last_wins(explicit: Optional[Path]) -> Iterator[Path]:
    """Home, then %%LOCALAPPDATA%%\\narrator, then ``--config`` — last file wins per key."""
    yield Path.home() / ".config" / "narrator" / "config.toml"
    la = os.environ.get("LOCALAPPDATA", "")
    if la:
        yield Path(la) / "narrator" / "config.toml"
    if explicit is not None:
        yield explicit


def merged_config(explicit: Optional[Path]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for path in config_paths_last_wins(explicit):
        if path.is_file():
            try:
                merged.update(load_toml_file(path))
            except OSError:
                continue
    return merged


def _resolve_speak_engine(requested: str, *, piper_onnx: Optional[Path]) -> str:
    """
    ``auto``: XTTS if Coqui is installed, else Piper if ``piper-tts`` is installed and an ONNX model exists, else WinRT.
    ``piper``: Piper if available and model exists, else WinRT with a warning.
    ``xtts``: XTTS if available, otherwise WinRT with a warning.
    ``winrt``: always WinRT.
    """
    r = (requested or "auto").strip().lower()
    if r not in ("winrt", "xtts", "piper", "auto"):
        r = "auto"

    from narrator.tts_piper import is_piper_available
    from narrator.tts_xtts import is_xtts_available

    piper_ok = is_piper_available() and piper_onnx is not None
    xtts_ok = is_xtts_available()

    if r == "auto":
        if xtts_ok:
            return "xtts"
        if piper_ok:
            return "piper"
        return "winrt"
    if r == "piper":
        if not is_piper_available():
            warnings.warn(
                "speak_engine is piper but piper-tts is not installed; using WinRT. "
                "Install: pip install narrator[speak-piper]",
                UserWarning,
                stacklevel=2,
            )
            return "winrt"
        if piper_onnx is None:
            warnings.warn(
                "speak_engine is piper but no Piper ONNX model was found; using WinRT. "
                "Run: python scripts/prefetch_piper_voice.py - or set piper_model_path / piper_model_dir.",
                UserWarning,
                stacklevel=2,
            )
            return "winrt"
        return "piper"
    if r == "xtts":
        if xtts_ok:
            return "xtts"
        warnings.warn(
            "speak_engine is xtts but coqui-tts is not installed; using WinRT. "
            "Install: pip install narrator[speak-xtts]",
            UserWarning,
            stacklevel=2,
        )
        return "winrt"
    return "winrt"


def build_runtime_settings(
    *,
    config_explicit: Optional[Path],
    voice: Optional[str],
    rate: Optional[float],
    volume: Optional[float],
    speak_hotkey: Optional[str],
    listen_hotkey: Optional[str],
    legacy_hotkey: Optional[str],
    silent: bool,
    verbose: bool,
    speak_engine: Optional[str] = None,
    xtts_model: Optional[str] = None,
    xtts_speaker: Optional[str] = None,
    xtts_language: Optional[str] = None,
    xtts_device: Optional[str] = None,
    xtts_speaker_wav: Optional[str] = None,
    piper_voice: Optional[str] = None,
    piper_model_dir: Optional[str] = None,
    piper_model_path: Optional[str] = None,
    piper_cuda: Optional[bool] = None,
    listen_engine: Optional[str] = None,
    whisper_model: Optional[str] = None,
    whisper_device: Optional[str] = None,
    listen_whisper_refine_punctuation: Optional[bool] = None,
    whisper_beam_size: Optional[int] = None,
    whisper_initial_prompt: Optional[str] = None,
    whisper_greedy: Optional[bool] = None,
    whisper_chunk_interval_seconds: Optional[float] = None,
    speak_exclude_hyperlinks: Optional[bool] = None,
    speak_exclude_math: Optional[bool] = None,
    speak_exclude_markup: Optional[bool] = None,
    speak_exclude_citations: Optional[bool] = None,
    speak_exclude_technical: Optional[bool] = None,
    speak_exclude_chrome: Optional[bool] = None,
    speak_exclude_emoji: Optional[bool] = None,
    speak_insert_line_pauses: Optional[bool] = None,
    speak_pause_between_lines: Optional[bool] = None,
    speak_winrt_use_ssml_breaks: Optional[bool] = None,
    speak_pause_line_ms: Optional[int] = None,
    speak_pause_paragraph_ms: Optional[int] = None,
    live_rate_resume_slack_ms: Optional[float] = None,
    post_waveout_close_drain_s: Optional[float] = None,
    live_rate_safe_chunk_discard: Optional[bool] = None,
    live_rate_defer_during_playback: Optional[bool] = None,
    live_rate_in_play_engine: Optional[str] = None,
    speak_chunk_max_chars: Optional[int] = None,
) -> RuntimeSettings:
    cfg = merged_config(config_explicit)

    voice_e = voice if voice is not None else cfg.get("voice")
    # CLI --rate wins; else last hotkey-adjusted value (user_state); else config.toml rate.
    if rate is not None:
        rate_e = clamp_speaking_rate(float(rate))
    else:
        persisted = load_persisted_speaking_rate()
        if persisted is not None:
            rate_e = persisted
        else:
            raw_r = cfg.get("rate", 1.0)
            try:
                rate_e = clamp_speaking_rate(float(raw_r))
            except (TypeError, ValueError):
                rate_e = 1.0
    vol_e = volume if volume is not None else cfg.get("volume", 1.0)

    speak_hk = speak_hotkey if speak_hotkey is not None else cfg.get("speak_hotkey")
    listen_hk = listen_hotkey if listen_hotkey is not None else cfg.get("listen_hotkey")
    legacy = legacy_hotkey if legacy_hotkey is not None else cfg.get("hotkey")

    if legacy_hotkey is not None:
        warnings.warn(
            "--hotkey is deprecated; use --speak-hotkey instead.",
            DeprecationWarning,
            stacklevel=2,
        )
    elif cfg.get("hotkey") is not None and cfg.get("speak_hotkey") is None:
        warnings.warn(
            "Config key 'hotkey' is deprecated; use 'speak_hotkey' instead.",
            DeprecationWarning,
            stacklevel=2,
        )

    if not speak_hk and legacy:
        speak_hk = legacy
    if not speak_hk:
        speak_hk = "ctrl+alt+s"
    if not listen_hk:
        listen_hk = "ctrl+alt+l"

    if silent:
        beep_e = False
    else:
        beep_e = bool(cfg.get("beep_on_failure", True))

    le = listen_engine if listen_engine is not None else cfg.get("listen_engine", "winrt")
    le_s = str(le).strip().lower()
    if le_s not in ("winrt", "whisper"):
        le_s = "winrt"

    wm = whisper_model if whisper_model is not None else cfg.get("whisper_model", "base")
    wd = whisper_device if whisper_device is not None else cfg.get("whisper_device", "auto")
    wd_s = str(wd).strip().lower()
    if wd_s not in ("auto", "cpu", "cuda"):
        wd_s = "auto"

    wrp = listen_whisper_refine_punctuation
    if wrp is None:
        wrp = bool(cfg.get("listen_whisper_refine_punctuation", True))

    wbeam = whisper_beam_size if whisper_beam_size is not None else cfg.get("whisper_beam_size", 3)
    try:
        wbeam_i = int(wbeam)
    except (TypeError, ValueError):
        wbeam_i = 3
    wbeam_i = max(1, min(20, wbeam_i))

    wip = whisper_initial_prompt if whisper_initial_prompt is not None else cfg.get("whisper_initial_prompt")
    wip_s = str(wip).strip() if wip else None

    wgreedy = whisper_greedy
    if wgreedy is None:
        wgreedy = bool(cfg.get("whisper_greedy", False))

    wchunk = whisper_chunk_interval_seconds
    if wchunk is None:
        wchunk = cfg.get("whisper_chunk_interval_seconds", 0.0)
    try:
        wchunk_f = float(wchunk)
    except (TypeError, ValueError):
        wchunk_f = 0.0
    if wchunk_f < 0:
        wchunk_f = 0.0
    elif wchunk_f > 0:
        wchunk_f = max(1.0, min(120.0, wchunk_f))

    seh = speak_exclude_hyperlinks
    if seh is None:
        seh = bool(cfg.get("speak_exclude_hyperlinks", True))
    sem = speak_exclude_math
    if sem is None:
        sem = bool(cfg.get("speak_exclude_math", True))

    def _b(name: str, v: Optional[bool], default: bool = True) -> bool:
        if v is not None:
            return bool(v)
        return bool(cfg.get(name, default))

    smk = _b("speak_exclude_markup", speak_exclude_markup)
    sci = _b("speak_exclude_citations", speak_exclude_citations)
    ste = _b("speak_exclude_technical", speak_exclude_technical)
    sch = _b("speak_exclude_chrome", speak_exclude_chrome)
    semo = _b("speak_exclude_emoji", speak_exclude_emoji)

    silp = _b("speak_insert_line_pauses", speak_insert_line_pauses)
    spbl = _b("speak_pause_between_lines", speak_pause_between_lines, default=False)
    swsb = _b("speak_winrt_use_ssml_breaks", speak_winrt_use_ssml_breaks)
    splm = speak_pause_line_ms if speak_pause_line_ms is not None else cfg.get("speak_pause_line_ms", 320)
    sppm = speak_pause_paragraph_ms if speak_pause_paragraph_ms is not None else cfg.get("speak_pause_paragraph_ms", 520)
    try:
        splm_i = int(splm)
    except (TypeError, ValueError):
        splm_i = 320
    try:
        sppm_i = int(sppm)
    except (TypeError, ValueError):
        sppm_i = 520
    splm_i = max(50, min(2000, splm_i))
    sppm_i = max(80, min(3000, sppm_i))

    lr_slack = live_rate_resume_slack_ms
    if lr_slack is None:
        lr_slack = cfg.get("live_rate_resume_slack_ms", 280.0)
    try:
        lr_slack_f = float(lr_slack)
    except (TypeError, ValueError):
        lr_slack_f = 280.0
    lr_slack_f = max(0.0, min(2000.0, lr_slack_f))

    pw_drain = post_waveout_close_drain_s
    if pw_drain is None:
        pw_drain = cfg.get("post_waveout_close_drain_s", 0.35)
    try:
        pw_drain_f = float(pw_drain)
    except (TypeError, ValueError):
        pw_drain_f = 0.35
    pw_drain_f = max(0.0, min(2.0, pw_drain_f))

    lr_safe = live_rate_safe_chunk_discard
    if lr_safe is None:
        lr_safe = bool(cfg.get("live_rate_safe_chunk_discard", True))

    lr_defer = live_rate_defer_during_playback
    if lr_defer is None:
        lr_defer = bool(cfg.get("live_rate_defer_during_playback", False))

    lr_eng = live_rate_in_play_engine
    if lr_eng is None:
        lr_eng = str(cfg.get("live_rate_in_play_engine", "wsola")).strip().lower()
    if lr_eng not in ("wsola", "phase_vocoder", "resample"):
        lr_eng = "wsola"
    if cfg.get("live_rate_in_play_use_phase_vocoder") is True:
        lr_eng = "phase_vocoder"

    se = speak_engine if speak_engine is not None else cfg.get("speak_engine", "auto")
    se_s = str(se).strip().lower()
    if se_s not in ("winrt", "xtts", "piper", "auto"):
        se_s = "auto"

    pvoice = piper_voice if piper_voice is not None else cfg.get("piper_voice", DEFAULT_PIPER_VOICE_ID)
    pdir = piper_model_dir if piper_model_dir is not None else cfg.get("piper_model_dir")
    ppath = piper_model_path if piper_model_path is not None else cfg.get("piper_model_path")
    pcuda = piper_cuda if piper_cuda is not None else bool(cfg.get("piper_cuda", False))

    from narrator.tts_piper import effective_piper_voice_id, resolve_piper_onnx_path

    vid = effective_piper_voice_id(
        str(voice_e).strip() if voice_e else None,
        str(pvoice).strip() if pvoice else DEFAULT_PIPER_VOICE_ID,
    )
    onnx_path = resolve_piper_onnx_path(
        voice_id=vid,
        piper_model_dir=str(pdir).strip() if pdir else None,
        piper_model_path=str(ppath).strip() if ppath else None,
    )
    # e.g. voice requests a Piper id whose ONNX is missing — fall back to piper_voice.
    if onnx_path is None:
        fb = str(pvoice).strip() if pvoice else DEFAULT_PIPER_VOICE_ID
        if fb != vid:
            onnx_path = resolve_piper_onnx_path(
                voice_id=fb,
                piper_model_dir=str(pdir).strip() if pdir else None,
                piper_model_path=None,
            )

    se_resolved = _resolve_speak_engine(se_s, piper_onnx=onnx_path)

    xm = xtts_model if xtts_model is not None else cfg.get("xtts_model", "tts_models/multilingual/multi-dataset/xtts_v2")
    xs = xtts_speaker if xtts_speaker is not None else cfg.get("xtts_speaker", "Ana Florence")
    xl = xtts_language if xtts_language is not None else cfg.get("xtts_language", "en")
    xd = xtts_device if xtts_device is not None else cfg.get("xtts_device", "auto")
    xd_s = str(xd).strip().lower()
    if xd_s not in ("auto", "cpu", "cuda"):
        xd_s = "auto"
    xsw = xtts_speaker_wav if xtts_speaker_wav is not None else cfg.get("xtts_speaker_wav")
    xsw_e = str(xsw).strip() if xsw else None

    # Env overrides TOML/CLI for live-rate playback tuning (see wav_play_win32).
    _ev_slack = os.environ.get("NARRATOR_LIVE_RATE_SLACK_MS", "").strip()
    if _ev_slack:
        try:
            lr_slack_f = max(0.0, min(2000.0, float(_ev_slack)))
        except ValueError:
            pass
    _ev_drain = os.environ.get("NARRATOR_POST_WAVEOUT_CLOSE_DRAIN_S", "").strip()
    if _ev_drain:
        try:
            pw_drain_f = max(0.0, min(2.0, float(_ev_drain)))
        except ValueError:
            pass
    _ev_safe = os.environ.get("NARRATOR_LIVE_RATE_SAFE", "").strip()
    if _ev_safe:
        lr_safe = _ev_safe.lower() in ("1", "true", "yes", "on")

    _ev_def = os.environ.get("NARRATOR_LIVE_RATE_DEFER", "").strip().lower()
    if _ev_def in ("1", "true", "yes", "on"):
        lr_defer = True
    elif _ev_def in ("0", "false", "no", "off"):
        lr_defer = False

    _ev_eng = os.environ.get("NARRATOR_LIVE_RATE_ENGINE", "").strip().lower()
    if _ev_eng in ("wsola", "phase_vocoder", "resample"):
        lr_eng = _ev_eng
    _ev_pv = os.environ.get("NARRATOR_LIVE_RATE_PHASE_VOCODER", "").strip().lower()
    if _ev_pv in ("1", "true", "yes", "on"):
        lr_eng = "phase_vocoder"
    elif _ev_pv in ("0", "false", "no", "off"):
        pass

    scm = speak_chunk_max_chars
    if scm is None:
        scm = cfg.get("speak_chunk_max_chars", 8000)
    try:
        scm_i = int(scm)
    except (TypeError, ValueError):
        scm_i = 8000
    _ev_scm = os.environ.get("NARRATOR_SPEAK_CHUNK_MAX_CHARS", "").strip()
    if _ev_scm:
        try:
            scm_i = int(_ev_scm)
        except ValueError:
            pass
    scm_final = clamp_chunk_max_chars(scm_i) if scm_i > 0 else 0

    return RuntimeSettings(
        voice_name=str(voice_e).strip() if voice_e else None,
        speaking_rate=rate_e,
        audio_volume=float(vol_e),
        speak_hotkey=str(speak_hk).strip() or "ctrl+alt+s",
        listen_hotkey=str(listen_hk).strip() or "ctrl+alt+l",
        beep_on_failure=beep_e,
        verbose=verbose,
        speak_engine=se_resolved,
        xtts_model=str(xm).strip() or "tts_models/multilingual/multi-dataset/xtts_v2",
        xtts_speaker=str(xs).strip() or "Ana Florence",
        xtts_language=str(xl).strip() or "en",
        xtts_device=xd_s,
        xtts_speaker_wav=xsw_e,
        piper_voice=str(pvoice).strip() if pvoice else DEFAULT_PIPER_VOICE_ID,
        piper_model_dir=str(pdir).strip() if pdir else None,
        piper_model_path=str(ppath).strip() if ppath else None,
        piper_cuda=bool(pcuda),
        listen_engine=le_s,
        whisper_model=str(wm).strip() or "base",
        whisper_device=wd_s,
        listen_whisper_refine_punctuation=bool(wrp),
        whisper_beam_size=wbeam_i,
        whisper_initial_prompt=wip_s,
        whisper_greedy=bool(wgreedy),
        whisper_chunk_interval_seconds=wchunk_f,
        speak_exclude_hyperlinks=bool(seh),
        speak_exclude_math=bool(sem),
        speak_exclude_markup=smk,
        speak_exclude_citations=sci,
        speak_exclude_technical=ste,
        speak_exclude_chrome=sch,
        speak_exclude_emoji=semo,
        speak_insert_line_pauses=silp,
        speak_pause_between_lines=spbl,
        speak_winrt_use_ssml_breaks=swsb,
        speak_pause_line_ms=splm_i,
        speak_pause_paragraph_ms=sppm_i,
        speak_chunk_max_chars=scm_final,
        live_rate_resume_slack_ms=lr_slack_f,
        post_waveout_close_drain_s=pw_drain_f,
        live_rate_safe_chunk_discard=bool(lr_safe),
        live_rate_defer_during_playback=bool(lr_defer),
        live_rate_in_play_engine=str(lr_eng),
    )
