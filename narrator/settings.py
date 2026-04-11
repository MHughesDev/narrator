"""Runtime settings (CLI + optional TOML config). Later config files override earlier ones."""

from __future__ import annotations

import os
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional

from narrator.speak_chunking import clamp_chunk_max_chars
from narrator.speak_text_llm import DEFAULT_SPEAK_TEXT_LLM_MODEL
from narrator.tts_piper import DEFAULT_PIPER_VOICE_ID
from narrator.tts_xtts import DEFAULT_XTTS_MODEL_ID


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
    xtts_model: str = DEFAULT_XTTS_MODEL_ID
    xtts_speaker: str = "Ana Florence"
    xtts_language: str = "en"
    xtts_device: str = "auto"
    xtts_speaker_wav: Optional[str] = None
    # Coqui ``tts_to_file(..., split_sentences=True)`` runs one forward pass per sentence (higher latency).
    # Narrator already chunks text in ``synthesize_xtts_to_path`` — default **false** = fewer GPU round-trips.
    xtts_split_sentences: bool = False
    # Wrap XTTS synthesis in ``torch.inference_mode()`` when available (slightly less autograd overhead).
    xtts_torch_inference_mode: bool = True
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
    # Extra TTS text cleanup (see narrator/speak_preprocess.py).
    speak_expand_tech_abbreviations: bool = True
    speak_strip_arxiv_metadata: bool = True
    speak_strip_toc_leader_lines: bool = True
    speak_strip_contents_pages: bool = True
    # Strip lines that look like figure colour legends / timeline year rows (PDF figure dump).
    speak_strip_figure_legend_lines: bool = True
    # Replace long comma-separated author-style lists with “see names” (keeps affiliation+email blocks).
    speak_collapse_long_name_lists: bool = True
    speak_long_name_list_max: int = 4
    # When True, drop everything before the first ``Abstract`` section (research-paper style).
    speak_start_at_abstract: bool = True
    # Preprocess only an initial raw-text bundle first; rest in parallel — faster time-to-first-chunk.
    speak_preprocess_streaming: bool = True
    # Rough number of TTS-chunk equivalents to include in the first preprocess bundle (paragraph-bounded).
    speak_preprocess_initial_chunks: int = 3
    # Local OpenAI-compatible LLM to ready text (see narrator/speak_text_llm.py). Piper/XTTS force this on at runtime.
    speak_text_llm_enabled: bool = False
    speak_text_llm_base_url: str = "http://127.0.0.1:11434/v1"
    speak_text_llm_model: str = ""
    speak_text_llm_api_key: Optional[str] = None
    speak_text_llm_timeout_s: float = 120.0
    speak_text_llm_max_chunk_chars: int = 6000
    # Send this many consecutive TTS chunks in one LLM request (TOC / section context). 1 = one chunk per request.
    speak_text_llm_bundle_chunks: int = 1
    # Soft cap on total characters per bundled LLM request (sum of per-chunk bodies after max_chunk_chars trim).
    speak_text_llm_bundle_max_chars: int = 16000
    # Keep neural (Piper/XTTS) default "LLM on" behavior; set False to allow fully disabling LLM for speed.
    speak_text_llm_force_for_neural: bool = True
    # ``heuristic_then_llm`` = full preprocess then LLM per chunk; ``llm_primary`` = minimal strip then LLM.
    speak_text_llm_mode: str = "heuristic_then_llm"
    speak_text_llm_rules: str = ""
    speak_text_llm_rules_file: Optional[str] = None
    # Merge packaged default_speak_text_llm_rules.txt into the LLM system prompt (disable for a fully custom rules file).
    speak_text_llm_builtin_rules: bool = True
    # Prefetch / synthesis pipeline (see narrator/worker.py).
    speak_synth_max_ahead: int = 0
    speak_synth_worker_threads: int = 1
    speak_keep_wav_in_memory: bool = False
    # Structural pauses before TTS (see narrator/speak_prosody.py). Standard = paragraph breaks only.
    speak_insert_line_pauses: bool = True
    speak_pause_between_lines: bool = False
    speak_winrt_use_ssml_breaks: bool = True
    speak_pause_line_ms: int = 320
    speak_pause_paragraph_ms: int = 520
    # Split long documents into multiple synthesize/play passes (0 = disable; see narrator/speak_chunking.py).
    speak_chunk_max_chars: int = 8000
    # Prepend tail of previous chunk to next synthesis for smoother prosody; trim duplicated audio after (see speech.py).
    speak_chunk_context_enabled: bool = True
    speak_chunk_context_max_chars: int = 120
    # ``fixed_ms`` = trim first N ms (default: fast; no extra XTTS pass). ``duration_probe`` = second synth of context to measure trim (slower, can ~2x XTTS work per segment).
    speak_chunk_context_trim_mode: str = "fixed_ms"
    speak_chunk_context_trim_ms: float = 400.0
    # How many upcoming WAV segments to buffer while playing (worker producer queue; env NARRATOR_SPEAK_PREFETCH_DEPTH).
    speak_prefetch_depth: int = 4
    # Multi-segment speaks: merge segment WAVs into one PCM stream (VoxCPM-style decode-then-concat) before playback.
    # Default ``false``: prefetch + chained play matches VoxCPM-style *streaming* time-to-first-audio better than compiling all segments first.
    speak_audio_stream_compile: bool = False
    # After startup: preload neural TTS (Piper/XTTS) and optionally run a tiny synthesis (VoxCPM-style post-load warmup).
    speak_warmup_on_start: bool = True
    speak_warmup_synthesize: bool = True
    # VoxCPM-like text stages before TTS (markdown/emoji cleanup + optional wetext ``normalize``); see voxcpm_text_pipeline.py.
    speak_voxcpm_text_pipeline: bool = True
    speak_voxcpm_text_normalize: bool = False
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
    # Fade in at clip start + fade out at clip end (16-bit PCM) to reduce clicks between segments.
    pcm_edge_fade_ms: float = 8.0
    # After a live-rate hotkey, wait this long (and extend on each extra hotkey) to coalesce bursts
    # before handoff — reduces chained WSOLA passes. 0 = off.
    live_rate_settle_ms: float = 45.0
    # If max(ratio, 1/ratio) exceeds this, in-play handoff uses ``resample`` instead of WSOLA/phase_vocoder
    # (less chorus on large speed jumps). Set very high (e.g. 99) to always use ``live_rate_in_play_engine``.
    live_rate_extreme_ratio_threshold: float = 1.12
    # Minimum wall time between in-play handoffs (reduces chained stretches). 0 = off.
    live_rate_min_handoff_interval_s: float = 0.0
    # Re-synthesize unread text at new rate instead of WSOLA on the tail (higher quality, extra latency).
    live_rate_resynth_remainder: bool = True
    live_rate_resynth_min_remainder_chars: int = 12
    # Lead silence after device reset before playing stretched tail (reduces perceived overlap). 0 = off.
    post_reset_silence_ms: float = 12.0
    # Peak-normalize PCM before edge fades (reduces level jumps between segments).
    pcm_peak_normalize: bool = True
    pcm_peak_normalize_level: float = 0.92
    # Optional playback high-pass (rumble / DC) before peak normalize — see docs/TTS_VOICE_CLEANING.md.
    speak_voice_clean_enabled: bool = False
    speak_voice_clean_highpass_hz: float = 72.0
    # Overlap-add crossfade between multi-segment speaks (ms). 0 = off. Used when preset is ``custom``.
    segment_crossfade_ms: float = 24.0
    # Segment boundary smoothing: ``engine`` = per speak_engine (default); ``custom`` = use pcm_* keys; ``minimal``.
    segment_transition_preset: str = "engine"
    # ``waveout`` (default winmm) or ``sounddevice`` (PortAudio; optional ``pip install sounddevice``).
    audio_output_backend: str = "waveout"


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
    speak_text_llm_force_for_neural: Optional[bool] = None,
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
    pcm_edge_fade_ms: Optional[float] = None,
    live_rate_settle_ms: Optional[float] = None,
    live_rate_extreme_ratio_threshold: Optional[float] = None,
    speak_chunk_max_chars: Optional[int] = None,
    speak_prefetch_depth: Optional[int] = None,
) -> RuntimeSettings:
    cfg = merged_config(config_explicit)

    voice_e = voice if voice is not None else cfg.get("voice")
    # Speaking tempo is fixed at 1.0 (no CLI/config/hotkey rate for now).
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

    def _bool_cfg_env(
        key: str,
        *,
        default: bool,
        env_name: str,
    ) -> bool:
        v = bool(cfg.get(key, default))
        ev = os.environ.get(env_name, "").strip().lower()
        if ev in ("1", "true", "yes", "on"):
            return True
        if ev in ("0", "false", "no", "off"):
            return False
        return v

    speak_expand_tech_abbreviations = _bool_cfg_env(
        "speak_expand_tech_abbreviations",
        default=True,
        env_name="NARRATOR_SPEAK_EXPAND_TECH_ABBREVIATIONS",
    )
    speak_strip_arxiv_metadata = _bool_cfg_env(
        "speak_strip_arxiv_metadata",
        default=True,
        env_name="NARRATOR_SPEAK_STRIP_ARXIV_METADATA",
    )
    speak_strip_toc_leader_lines = _bool_cfg_env(
        "speak_strip_toc_leader_lines",
        default=True,
        env_name="NARRATOR_SPEAK_STRIP_TOC_LEADER_LINES",
    )
    speak_strip_contents_pages = _bool_cfg_env(
        "speak_strip_contents_pages",
        default=True,
        env_name="NARRATOR_SPEAK_STRIP_CONTENTS_PAGES",
    )
    speak_start_at_abstract = _bool_cfg_env(
        "speak_start_at_abstract",
        default=True,
        env_name="NARRATOR_SPEAK_START_AT_ABSTRACT",
    )
    speak_strip_figure_legend_lines = _bool_cfg_env(
        "speak_strip_figure_legend_lines",
        default=True,
        env_name="NARRATOR_SPEAK_STRIP_FIGURE_LEGEND_LINES",
    )
    speak_collapse_long_name_lists = _bool_cfg_env(
        "speak_collapse_long_name_lists",
        default=True,
        env_name="NARRATOR_SPEAK_COLLAPSE_LONG_NAME_LISTS",
    )
    try:
        speak_long_name_list_max_i = int(cfg.get("speak_long_name_list_max", 4))
    except (TypeError, ValueError):
        speak_long_name_list_max_i = 4
    speak_long_name_list_max_i = max(1, min(32, speak_long_name_list_max_i))
    _ev_lnmax = os.environ.get("NARRATOR_SPEAK_LONG_NAME_LIST_MAX", "").strip()
    if _ev_lnmax:
        try:
            speak_long_name_list_max_i = max(1, min(32, int(_ev_lnmax)))
        except ValueError:
            pass
    speak_preprocess_streaming = _bool_cfg_env(
        "speak_preprocess_streaming",
        default=True,
        env_name="NARRATOR_SPEAK_PREPROCESS_STREAMING",
    )
    try:
        speak_preprocess_initial_chunks_i = int(cfg.get("speak_preprocess_initial_chunks", 3))
    except (TypeError, ValueError):
        speak_preprocess_initial_chunks_i = 3
    speak_preprocess_initial_chunks_i = max(1, min(32, speak_preprocess_initial_chunks_i))
    _ev_spic = os.environ.get("NARRATOR_SPEAK_PREPROCESS_INITIAL_CHUNKS", "").strip()
    if _ev_spic:
        try:
            speak_preprocess_initial_chunks_i = max(1, min(32, int(_ev_spic)))
        except ValueError:
            pass

    speak_text_llm_enabled = _bool_cfg_env(
        "speak_text_llm_enabled",
        default=False,
        env_name="NARRATOR_SPEAK_TEXT_LLM_ENABLED",
    )
    if speak_text_llm_force_for_neural is None:
        speak_text_llm_force_for_neural_b = _bool_cfg_env(
            "speak_text_llm_force_for_neural",
            default=True,
            env_name="NARRATOR_SPEAK_TEXT_LLM_FORCE_NEURAL",
        )
    else:
        speak_text_llm_force_for_neural_b = bool(speak_text_llm_force_for_neural)
    st_llm_base = str(cfg.get("speak_text_llm_base_url", "http://127.0.0.1:11434/v1") or "").strip()
    _ev_lb = os.environ.get("NARRATOR_SPEAK_TEXT_LLM_BASE_URL", "").strip()
    if _ev_lb:
        st_llm_base = _ev_lb
    st_llm_model = str(cfg.get("speak_text_llm_model", "") or "").strip()
    _ev_lm = os.environ.get("NARRATOR_SPEAK_TEXT_LLM_MODEL", "").strip()
    if _ev_lm:
        st_llm_model = _ev_lm
    st_llm_key = cfg.get("speak_text_llm_api_key")
    if st_llm_key is None or str(st_llm_key).strip() == "":
        st_llm_key = os.environ.get("NARRATOR_SPEAK_TEXT_LLM_API_KEY", "").strip() or None
    else:
        st_llm_key = str(st_llm_key).strip() or None
    try:
        st_llm_to = float(cfg.get("speak_text_llm_timeout_s", 120.0))
    except (TypeError, ValueError):
        st_llm_to = 120.0
    st_llm_to = max(5.0, min(600.0, st_llm_to))
    _ev_lto = os.environ.get("NARRATOR_SPEAK_TEXT_LLM_TIMEOUT_S", "").strip()
    if _ev_lto:
        try:
            st_llm_to = max(5.0, min(600.0, float(_ev_lto)))
        except ValueError:
            pass
    try:
        st_llm_mcc = int(cfg.get("speak_text_llm_max_chunk_chars", 6000))
    except (TypeError, ValueError):
        st_llm_mcc = 6000
    st_llm_mcc = max(256, min(200_000, st_llm_mcc))
    st_llm_mode = str(cfg.get("speak_text_llm_mode", "heuristic_then_llm") or "").strip().lower()
    if st_llm_mode not in ("heuristic_then_llm", "llm_primary"):
        st_llm_mode = "heuristic_then_llm"
    _ev_lmode = os.environ.get("NARRATOR_SPEAK_TEXT_LLM_MODE", "").strip().lower()
    if _ev_lmode in ("heuristic_then_llm", "llm_primary"):
        st_llm_mode = _ev_lmode
    st_llm_rules = str(cfg.get("speak_text_llm_rules", "") or "")
    rf = cfg.get("speak_text_llm_rules_file")
    st_llm_rules_file = str(rf).strip() if rf else None
    st_llm_builtin_rules = _bool_cfg_env(
        "speak_text_llm_builtin_rules",
        default=True,
        env_name="NARRATOR_SPEAK_TEXT_LLM_BUILTIN_RULES",
    )
    try:
        st_llm_bun_n = int(cfg.get("speak_text_llm_bundle_chunks", 1))
    except (TypeError, ValueError):
        st_llm_bun_n = 4
    st_llm_bun_n = max(1, min(64, st_llm_bun_n))
    try:
        st_llm_bun_mc = int(cfg.get("speak_text_llm_bundle_max_chars", 16000))
    except (TypeError, ValueError):
        st_llm_bun_mc = 16000
    st_llm_bun_mc = max(1024, min(200_000, st_llm_bun_mc))

    try:
        synth_max_ahead_i = int(cfg.get("speak_synth_max_ahead", 0))
    except (TypeError, ValueError):
        synth_max_ahead_i = 0
    synth_max_ahead_i = max(0, min(512, synth_max_ahead_i))
    _ev_sma = os.environ.get("NARRATOR_SPEAK_SYNTH_MAX_AHEAD", "").strip()
    if _ev_sma:
        try:
            synth_max_ahead_i = max(0, min(512, int(_ev_sma)))
        except ValueError:
            pass
    try:
        synth_workers_i = int(cfg.get("speak_synth_worker_threads", 1))
    except (TypeError, ValueError):
        synth_workers_i = 1
    synth_workers_i = max(1, min(16, synth_workers_i))
    _ev_sw = os.environ.get("NARRATOR_SPEAK_SYNTH_WORKER_THREADS", "").strip()
    if _ev_sw:
        try:
            synth_workers_i = max(1, min(16, int(_ev_sw)))
        except ValueError:
            pass
    keep_wav_mem = _bool_cfg_env(
        "speak_keep_wav_in_memory",
        default=False,
        env_name="NARRATOR_SPEAK_KEEP_WAV_IN_MEMORY",
    )

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

    pef = pcm_edge_fade_ms
    if pef is None:
        pef = cfg.get("pcm_edge_fade_ms", 8.0)
    try:
        pef_f = float(pef)
    except (TypeError, ValueError):
        pef_f = 8.0
    pef_f = max(0.0, min(50.0, pef_f))

    lrs = live_rate_settle_ms
    if lrs is None:
        lrs = cfg.get("live_rate_settle_ms", 45.0)
    try:
        lrs_f = float(lrs)
    except (TypeError, ValueError):
        lrs_f = 45.0
    lrs_f = max(0.0, min(500.0, lrs_f))

    lret = live_rate_extreme_ratio_threshold
    if lret is None:
        lret = cfg.get("live_rate_extreme_ratio_threshold", 1.12)
    try:
        lret_f = float(lret)
    except (TypeError, ValueError):
        lret_f = 1.12
    lret_f = max(1.0, min(10.0, lret_f))

    try:
        lr_min_iv_f = float(cfg.get("live_rate_min_handoff_interval_s", 0.0))
    except (TypeError, ValueError):
        lr_min_iv_f = 0.0
    lr_min_iv_f = max(0.0, min(5.0, lr_min_iv_f))

    lr_resynth = bool(cfg.get("live_rate_resynth_remainder", True))
    try:
        lr_resynth_min_i = int(cfg.get("live_rate_resynth_min_remainder_chars", 12))
    except (TypeError, ValueError):
        lr_resynth_min_i = 12
    lr_resynth_min_i = max(1, min(10_000, lr_resynth_min_i))

    try:
        post_rst_ms_f = float(cfg.get("post_reset_silence_ms", 12.0))
    except (TypeError, ValueError):
        post_rst_ms_f = 12.0
    post_rst_ms_f = max(0.0, min(200.0, post_rst_ms_f))

    pcm_norm_b = bool(cfg.get("pcm_peak_normalize", True))
    try:
        pcm_norm_lvl_f = float(cfg.get("pcm_peak_normalize_level", 0.92))
    except (TypeError, ValueError):
        pcm_norm_lvl_f = 0.92
    pcm_norm_lvl_f = max(0.1, min(1.0, pcm_norm_lvl_f))

    svc_en = _bool_cfg_env(
        "speak_voice_clean_enabled",
        default=False,
        env_name="NARRATOR_SPEAK_VOICE_CLEAN_ENABLED",
    )
    try:
        svc_hp = float(cfg.get("speak_voice_clean_highpass_hz", 72.0))
    except (TypeError, ValueError):
        svc_hp = 72.0
    svc_hp = max(20.0, min(500.0, svc_hp))
    _ev_svc_hp = os.environ.get("NARRATOR_SPEAK_VOICE_CLEAN_HIGHPASS_HZ", "").strip()
    if _ev_svc_hp:
        try:
            svc_hp = max(20.0, min(500.0, float(_ev_svc_hp)))
        except ValueError:
            pass

    try:
        seg_xf_ms_f = float(cfg.get("segment_crossfade_ms", 24.0))
    except (TypeError, ValueError):
        seg_xf_ms_f = 24.0
    seg_xf_ms_f = max(0.0, min(80.0, seg_xf_ms_f))

    aud_be_s = str(cfg.get("audio_output_backend", "waveout")).strip().lower()
    if aud_be_s not in ("waveout", "sounddevice"):
        aud_be_s = "waveout"

    stp_s = str(cfg.get("segment_transition_preset", "engine")).strip().lower()
    if stp_s not in ("engine", "custom", "minimal"):
        stp_s = "engine"

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

    # Default behavior keeps neural engines on local LLM cleanup for speech-ready text.
    # Advanced users can disable this for lower latency via config/env.
    if se_resolved in ("piper", "xtts") and speak_text_llm_force_for_neural_b:
        speak_text_llm_enabled = True
        if not (st_llm_model or "").strip():
            st_llm_model = DEFAULT_SPEAK_TEXT_LLM_MODEL

    xm = xtts_model if xtts_model is not None else cfg.get("xtts_model", DEFAULT_XTTS_MODEL_ID)
    xs = xtts_speaker if xtts_speaker is not None else cfg.get("xtts_speaker", "Ana Florence")
    xl = xtts_language if xtts_language is not None else cfg.get("xtts_language", "en")
    xd = xtts_device if xtts_device is not None else cfg.get("xtts_device", "auto")
    xd_s = str(xd).strip().lower()
    if xd_s not in ("auto", "cpu", "cuda"):
        xd_s = "auto"
    xsw = xtts_speaker_wav if xtts_speaker_wav is not None else cfg.get("xtts_speaker_wav")
    xsw_e = str(xsw).strip() if xsw else None

    xtts_ss = bool(cfg.get("xtts_split_sentences", False))
    _ev_xss = os.environ.get("NARRATOR_XTTS_SPLIT_SENTENCES", "").strip().lower()
    if _ev_xss in ("1", "true", "yes", "on"):
        xtts_ss = True
    elif _ev_xss in ("0", "false", "no", "off"):
        xtts_ss = False

    xtts_im = bool(cfg.get("xtts_torch_inference_mode", True))
    _ev_xim = os.environ.get("NARRATOR_XTTS_TORCH_INFERENCE_MODE", "").strip().lower()
    if _ev_xim in ("0", "false", "no", "off"):
        xtts_im = False
    elif _ev_xim in ("1", "true", "yes", "on"):
        xtts_im = True

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

    _ev_pef = os.environ.get("NARRATOR_PCM_EDGE_FADE_MS", "").strip()
    if _ev_pef:
        try:
            pef_f = max(0.0, min(50.0, float(_ev_pef)))
        except ValueError:
            pass
    _ev_lrs = os.environ.get("NARRATOR_LIVE_RATE_SETTLE_MS", "").strip()
    if _ev_lrs:
        try:
            lrs_f = max(0.0, min(500.0, float(_ev_lrs)))
        except ValueError:
            pass
    _ev_lret = os.environ.get("NARRATOR_LIVE_RATE_EXTREME_RATIO", "").strip()
    if _ev_lret:
        try:
            lret_f = max(1.0, min(10.0, float(_ev_lret)))
        except ValueError:
            pass

    _ev_minh = os.environ.get("NARRATOR_LIVE_RATE_MIN_HANDOFF_S", "").strip()
    if _ev_minh:
        try:
            lr_min_iv_f = max(0.0, min(5.0, float(_ev_minh)))
        except ValueError:
            pass
    _ev_resynth = os.environ.get("NARRATOR_LIVE_RATE_RESYNTH", "").strip().lower()
    if _ev_resynth in ("1", "true", "yes", "on"):
        lr_resynth = True
    elif _ev_resynth in ("0", "false", "no", "off"):
        lr_resynth = False

    _ev_backend = os.environ.get("NARRATOR_AUDIO_BACKEND", "").strip().lower()
    if _ev_backend in ("waveout", "sounddevice"):
        aud_be_s = _ev_backend

    _ev_stp = os.environ.get("NARRATOR_SEGMENT_TRANSITION_PRESET", "").strip().lower()
    if _ev_stp in ("engine", "custom", "minimal"):
        stp_s = _ev_stp

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

    spd = speak_prefetch_depth
    if spd is None:
        spd = cfg.get("speak_prefetch_depth", 4)
    try:
        spd_i = int(spd)
    except (TypeError, ValueError):
        spd_i = 3
    _ev_spd = os.environ.get("NARRATOR_SPEAK_PREFETCH_DEPTH", "").strip()
    if _ev_spd:
        try:
            spd_i = int(_ev_spd)
        except ValueError:
            pass
    spd_final = max(1, min(32, spd_i))

    sac_compile = bool(cfg.get("speak_audio_stream_compile", False))
    _ev_sac = os.environ.get("NARRATOR_SPEAK_AUDIO_STREAM_COMPILE", "").strip().lower()
    if _ev_sac in ("0", "false", "no", "off"):
        sac_compile = False
    elif _ev_sac in ("1", "true", "yes", "on"):
        sac_compile = True

    warm_on = bool(cfg.get("speak_warmup_on_start", True))
    _ev_warm = os.environ.get("NARRATOR_SPEAK_WARMUP_ON_START", "").strip().lower()
    if _ev_warm in ("0", "false", "no", "off"):
        warm_on = False
    elif _ev_warm in ("1", "true", "yes", "on"):
        warm_on = True

    warm_syn = bool(cfg.get("speak_warmup_synthesize", True))
    _ev_wsyn = os.environ.get("NARRATOR_SPEAK_WARMUP_SYNTHESIZE", "").strip().lower()
    if _ev_wsyn in ("0", "false", "no", "off"):
        warm_syn = False
    elif _ev_wsyn in ("1", "true", "yes", "on"):
        warm_syn = True

    sv_pipe = bool(cfg.get("speak_voxcpm_text_pipeline", True))
    _ev_svp = os.environ.get("NARRATOR_SPEAK_VOXCPM_TEXT_PIPELINE", "").strip().lower()
    if _ev_svp in ("0", "false", "no", "off"):
        sv_pipe = False
    elif _ev_svp in ("1", "true", "yes", "on"):
        sv_pipe = True

    sv_norm = bool(cfg.get("speak_voxcpm_text_normalize", False))
    _ev_svn = os.environ.get("NARRATOR_SPEAK_VOXCPM_TEXT_NORMALIZE", "").strip().lower()
    if _ev_svn in ("1", "true", "yes", "on"):
        sv_norm = True
    elif _ev_svn in ("0", "false", "no", "off"):
        sv_norm = False

    scc_en = bool(cfg.get("speak_chunk_context_enabled", True))
    _ev_scc = os.environ.get("NARRATOR_SPEAK_CHUNK_CONTEXT_ENABLED", "").strip().lower()
    if _ev_scc in ("1", "true", "yes", "on"):
        scc_en = True
    elif _ev_scc in ("0", "false", "no", "off"):
        scc_en = False

    scc_max = cfg.get("speak_chunk_context_max_chars", 120)
    try:
        scc_max_i = int(scc_max)
    except (TypeError, ValueError):
        scc_max_i = 120
    scc_max_i = max(20, min(500, scc_max_i))
    _ev_sccm = os.environ.get("NARRATOR_SPEAK_CHUNK_CONTEXT_MAX_CHARS", "").strip()
    if _ev_sccm:
        try:
            scc_max_i = max(20, min(500, int(_ev_sccm)))
        except ValueError:
            pass

    scc_mode = str(cfg.get("speak_chunk_context_trim_mode", "fixed_ms")).strip().lower()
    if scc_mode not in ("duration_probe", "fixed_ms"):
        scc_mode = "fixed_ms"
    _ev_sccmode = os.environ.get("NARRATOR_SPEAK_CHUNK_CONTEXT_TRIM_MODE", "").strip().lower()
    if _ev_sccmode in ("duration_probe", "fixed_ms"):
        scc_mode = _ev_sccmode

    scc_tms = cfg.get("speak_chunk_context_trim_ms", 400.0)
    try:
        scc_tms_f = float(scc_tms)
    except (TypeError, ValueError):
        scc_tms_f = 400.0
    scc_tms_f = max(0.0, min(5000.0, scc_tms_f))
    _ev_scct = os.environ.get("NARRATOR_SPEAK_CHUNK_CONTEXT_TRIM_MS", "").strip()
    if _ev_scct:
        try:
            scc_tms_f = max(0.0, min(5000.0, float(_ev_scct)))
        except ValueError:
            pass

    return RuntimeSettings(
        voice_name=str(voice_e).strip() if voice_e else None,
        speaking_rate=rate_e,
        audio_volume=float(vol_e),
        speak_hotkey=str(speak_hk).strip() or "ctrl+alt+s",
        listen_hotkey=str(listen_hk).strip() or "ctrl+alt+l",
        beep_on_failure=beep_e,
        verbose=verbose,
        speak_engine=se_resolved,
        xtts_model=str(xm).strip() or DEFAULT_XTTS_MODEL_ID,
        xtts_speaker=str(xs).strip() or "Ana Florence",
        xtts_language=str(xl).strip() or "en",
        xtts_device=xd_s,
        xtts_speaker_wav=xsw_e,
        xtts_split_sentences=xtts_ss,
        xtts_torch_inference_mode=xtts_im,
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
        speak_expand_tech_abbreviations=speak_expand_tech_abbreviations,
        speak_strip_arxiv_metadata=speak_strip_arxiv_metadata,
        speak_strip_toc_leader_lines=speak_strip_toc_leader_lines,
        speak_strip_contents_pages=speak_strip_contents_pages,
        speak_strip_figure_legend_lines=speak_strip_figure_legend_lines,
        speak_collapse_long_name_lists=speak_collapse_long_name_lists,
        speak_long_name_list_max=speak_long_name_list_max_i,
        speak_start_at_abstract=speak_start_at_abstract,
        speak_preprocess_streaming=speak_preprocess_streaming,
        speak_preprocess_initial_chunks=speak_preprocess_initial_chunks_i,
        speak_text_llm_enabled=speak_text_llm_enabled,
        speak_text_llm_base_url=st_llm_base or "http://127.0.0.1:11434/v1",
        speak_text_llm_model=st_llm_model,
        speak_text_llm_api_key=st_llm_key,
        speak_text_llm_timeout_s=st_llm_to,
        speak_text_llm_max_chunk_chars=st_llm_mcc,
        speak_text_llm_bundle_chunks=st_llm_bun_n,
        speak_text_llm_bundle_max_chars=st_llm_bun_mc,
        speak_text_llm_force_for_neural=speak_text_llm_force_for_neural_b,
        speak_text_llm_mode=st_llm_mode,
        speak_text_llm_rules=st_llm_rules,
        speak_text_llm_rules_file=st_llm_rules_file,
        speak_text_llm_builtin_rules=st_llm_builtin_rules,
        speak_synth_max_ahead=synth_max_ahead_i,
        speak_synth_worker_threads=synth_workers_i,
        speak_keep_wav_in_memory=keep_wav_mem,
        speak_insert_line_pauses=silp,
        speak_pause_between_lines=spbl,
        speak_winrt_use_ssml_breaks=swsb,
        speak_pause_line_ms=splm_i,
        speak_pause_paragraph_ms=sppm_i,
        speak_chunk_max_chars=scm_final,
        speak_chunk_context_enabled=bool(scc_en),
        speak_chunk_context_max_chars=scc_max_i,
        speak_chunk_context_trim_mode=scc_mode,
        speak_chunk_context_trim_ms=scc_tms_f,
        speak_prefetch_depth=spd_final,
        speak_audio_stream_compile=sac_compile,
        speak_warmup_on_start=warm_on,
        speak_warmup_synthesize=warm_syn,
        speak_voxcpm_text_pipeline=sv_pipe,
        speak_voxcpm_text_normalize=sv_norm,
        live_rate_resume_slack_ms=lr_slack_f,
        post_waveout_close_drain_s=pw_drain_f,
        live_rate_safe_chunk_discard=bool(lr_safe),
        live_rate_defer_during_playback=bool(lr_defer),
        live_rate_in_play_engine=str(lr_eng),
        pcm_edge_fade_ms=pef_f,
        live_rate_settle_ms=lrs_f,
        live_rate_extreme_ratio_threshold=lret_f,
        live_rate_min_handoff_interval_s=lr_min_iv_f,
        live_rate_resynth_remainder=lr_resynth,
        live_rate_resynth_min_remainder_chars=lr_resynth_min_i,
        post_reset_silence_ms=post_rst_ms_f,
        pcm_peak_normalize=pcm_norm_b,
        pcm_peak_normalize_level=pcm_norm_lvl_f,
        speak_voice_clean_enabled=svc_en,
        speak_voice_clean_highpass_hz=svc_hp,
        segment_crossfade_ms=seg_xf_ms_f,
        segment_transition_preset=stp_s,
        audio_output_backend=aud_be_s,
    )
