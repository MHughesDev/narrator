"""CLI entry: ``python -m narrator``."""

from __future__ import annotations

import argparse
import ctypes
import logging
import os
import queue
import sys
import threading
from ctypes import wintypes
from pathlib import Path

# Windows: import torch/onnx before WinRT (pulled in by listen/stt_winrt, speech, etc.) or native DLL
# init fails with WinError 1114 when loading torch\lib\c10.dll (loader / CRT interaction).
if sys.platform == "win32":
    try:
        import torch  # noqa: F401
    except Exception:
        pass
    try:
        import onnxruntime  # noqa: F401
    except Exception:
        pass

from narrator import __version__
from narrator import dpi

# Import ``narrator.speech`` and ``narrator.worker`` only after :func:`build_runtime_settings` (see below).
# Loading WinRT (speech) or ``uiautomation`` (worker) before ``onnxruntime`` / Piper breaks ONNX DLL
# initialization on Windows.
from narrator.hotkey import build_listener, parse_hotkey_spec
from narrator.listen import listen_worker_loop
from narrator.protocol import SHUTDOWN
from narrator.settings import build_runtime_settings
from narrator.tts_piper import DEFAULT_PIPER_VOICE_ID
from narrator.voices import format_voice_table, list_installed_voices, list_winrt_voices
from narrator.win_console import hide_console_window

_ERROR_ALREADY_EXISTS = 183


def _exit_if_second_instance() -> None:
    """Two ``python -m narrator`` processes both play TTS — sounds like multiple voices."""
    if sys.platform != "win32":
        return
    if (os.environ.get("NARRATOR_ALLOW_MULTI") or "").strip().lower() in ("1", "true", "yes", "on"):
        try:
            from narrator import audio_debug

            if audio_debug.is_enabled():
                audio_debug.log_kv("single-instance check skipped", NARRATOR_ALLOW_MULTI=True)
        except Exception:
            pass
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.GetLastError.argtypes = []
    kernel32.GetLastError.restype = wintypes.DWORD
    h = kernel32.CreateMutexW(None, False, "Local\\NarratorHoverSpeakSingleInstance")
    if h and kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
        print(
            "Narrator is already running. A second copy plays speech on top of the first "
            "(sounds like multiple voices). Close the other instance or end duplicate python.exe "
            "tasks in Task Manager. To allow more than one instance, set NARRATOR_ALLOW_MULTI=1.",
            file=sys.stderr,
        )
        sys.exit(0)
    try:
        from narrator import audio_debug

        if audio_debug.is_enabled():
            audio_debug.log_kv("single-instance mutex ok", pid=os.getpid())
    except Exception:
        pass


def main() -> None:
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    _exit_if_second_instance()
    parser = argparse.ArgumentParser(
        description=(
            "Windows narrator: default Ctrl+Alt+S reads hovered text aloud; default Ctrl+Alt+L toggles speech-to-text "
            "into the focused field. Both chords are configurable. Speak and listen use separate workers and do "
            "not cancel each other; they may run at the same time."
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="TOML config file (also searches %%LOCALAPPDATA%%\\narrator\\config.toml)",
    )
    parser.add_argument(
        "--voice",
        default=None,
        metavar="NAME",
        help=f"WinRT: name from --list-voices. XTTS: Coqui speaker. Piper: voice id (e.g. {DEFAULT_PIPER_VOICE_ID}).",
    )
    parser.add_argument("--volume", type=float, default=None, help="Audio volume 0.0–1.0 (default 1.0)")
    parser.add_argument(
        "--speak-hotkey",
        default=None,
        metavar="CHORD",
        help="Toggle hover-and-speak (default from config or ctrl+alt+s)",
    )
    parser.add_argument(
        "--listen-hotkey",
        default=None,
        metavar="CHORD",
        help="Toggle speech-to-text into focused field (default from config or ctrl+alt+l)",
    )
    parser.add_argument(
        "--hotkey",
        default=None,
        metavar="CHORD",
        help="Deprecated: same as --speak-hotkey for backward compatibility",
    )
    parser.add_argument("--silent", action="store_true", help="Do not beep when no text is captured")
    parser.add_argument(
        "--no-speak-exclude-hyperlinks",
        action="store_true",
        help="Do not strip URLs / markdown links from captured text before TTS (default: exclude)",
    )
    parser.add_argument(
        "--no-speak-exclude-math",
        action="store_true",
        help="Do not strip LaTeX / dollar-math / Unicode math letters before TTS (default: exclude)",
    )
    parser.add_argument(
        "--no-speak-exclude-markup",
        action="store_true",
        help="Keep code fences, HTML, markdown markers, image-alt patterns (default: strip)",
    )
    parser.add_argument(
        "--no-speak-exclude-citations",
        action="store_true",
        help="Keep bracket refs / parenthetical citations (default: strip)",
    )
    parser.add_argument(
        "--no-speak-exclude-technical",
        action="store_true",
        help="Keep UUIDs, hex, hashes, paths, emails (default: strip)",
    )
    parser.add_argument(
        "--no-speak-exclude-chrome",
        action="store_true",
        help="Keep page n of m, figure/table line labels, dot-leader TOC lines (default: strip)",
    )
    parser.add_argument(
        "--no-speak-exclude-emoji",
        action="store_true",
        help="Keep emoji and related symbols (default: strip)",
    )
    parser.add_argument(
        "--no-speak-insert-line-pauses",
        action="store_true",
        help="Disable structural pauses (default: paragraph pauses on)",
    )
    parser.add_argument(
        "--speak-pause-between-lines",
        action="store_true",
        help="Also pause between single-newline lines within a block (comma / short SSML break); "
        "default is paragraph-only pauses",
    )
    parser.add_argument(
        "--no-speak-winrt-ssml-breaks",
        action="store_true",
        help="WinRT: use comma/period pauses instead of SSML <break/> (default: SSML breaks)",
    )
    parser.add_argument(
        "--speak-pause-line-ms",
        type=int,
        default=None,
        metavar="MS",
        help="WinRT SSML pause between lines within a block (50–2000, default 320)",
    )
    parser.add_argument(
        "--speak-pause-paragraph-ms",
        type=int,
        default=None,
        metavar="MS",
        help="WinRT SSML pause between paragraphs (80–3000, default 520)",
    )
    parser.add_argument(
        "--speak-chunk-max-chars",
        type=int,
        default=None,
        metavar="N",
        help="Split long documents into multiple TTS passes of at most N characters (default 8000; 0 = no splitting). "
        "Env: NARRATOR_SPEAK_CHUNK_MAX_CHARS. Config: speak_chunk_max_chars.",
    )
    parser.add_argument(
        "--list-voices",
        action="store_true",
        help="Print WinRT (Narrator) synthesis voices and registry tokens, then exit",
    )
    parser.add_argument(
        "--hide-console",
        action="store_true",
        help="Hide the console window (Windows; use with python.exe; pythonw has no console)",
    )
    parser.add_argument(
        "--tray",
        action="store_true",
        help="System tray icon with Quit (install: pip install narrator[tray])",
    )
    parser.add_argument(
        "--listen-engine",
        choices=["winrt", "whisper"],
        default=None,
        metavar="ENGINE",
        help='Speech-to-text backend: "winrt" (live dictation, default) or "whisper" (record, then '
        "faster-whisper; install: pip install narrator[listen-whisper])",
    )
    parser.add_argument(
        "--whisper-model",
        default=None,
        metavar="NAME",
        help='Whisper model when --listen-engine=whisper (e.g. tiny, base, small, medium, large-v3). Default: base (faster than small; use small/medium for accuracy).',
    )
    parser.add_argument(
        "--whisper-device",
        choices=["auto", "cpu", "cuda"],
        default=None,
        help='Whisper device: auto (Linux: pick GPU if available; Windows: CPU for stability), cpu, or cuda.',
    )
    parser.add_argument(
        "--no-whisper-punct-refine",
        action="store_true",
        help="Do not run neural punctuation refine after Whisper (only if narrator[listen] installed).",
    )
    parser.add_argument(
        "--whisper-beam-size",
        type=int,
        default=None,
        metavar="N",
        help="Whisper beam width (1–20, default 3). Higher can help difficult audio; slower.",
    )
    parser.add_argument(
        "--whisper-prompt",
        default=None,
        metavar="TEXT",
        help="Optional bias text for the first decoding window (names, jargon). Helps a bit with specialized vocabulary.",
    )
    parser.add_argument(
        "--whisper-greedy",
        action="store_true",
        help="Use temperature 0 only (more literal decoding; can reduce nonsense when reading lists or UI text aloud).",
    )
    parser.add_argument(
        "--whisper-chunk-interval",
        type=float,
        default=None,
        metavar="SEC",
        help="Whisper only: transcribe and type every SEC seconds while recording (1–120; e.g. 4). "
        "Omit or 0 = one full transcript when you stop. Config: whisper_chunk_interval_seconds.",
    )
    parser.add_argument(
        "--speak-engine",
        choices=["auto", "winrt", "xtts", "piper"],
        default=None,
        metavar="ENGINE",
        help='Speak TTS: "auto" prefers XTTS if coqui-tts is installed, else Piper if speak-piper + ONNX voice '
        "on disk, else WinRT. Use winrt, xtts, or piper to force.",
    )
    parser.add_argument(
        "--xtts-model",
        default=None,
        metavar="NAME",
        help="XTTS model id when using --speak-engine=xtts (default: tts_models/multilingual/multi-dataset/xtts_v1.1).",
    )
    parser.add_argument(
        "--xtts-speaker",
        default=None,
        metavar="NAME",
        help="Built-in Coqui speaker if --voice is unset (default: Ana Florence).",
    )
    parser.add_argument(
        "--xtts-language",
        default=None,
        metavar="CODE",
        help="XTTS language code (default: en).",
    )
    parser.add_argument(
        "--xtts-device",
        choices=["auto", "cpu", "cuda"],
        default=None,
        help="Torch device for XTTS (default: auto).",
    )
    parser.add_argument(
        "--xtts-speaker-wav",
        default=None,
        metavar="PATH",
        help="Reference WAV for XTTS voice cloning (optional; overrides built-in speaker).",
    )
    parser.add_argument(
        "--list-xtts-speakers",
        action="store_true",
        help="Load XTTS and list built-in speaker names (slow; may download the model).",
    )
    parser.add_argument(
        "--piper-voice",
        default=None,
        metavar="ID",
        help=f"Piper voice id when using --speak-engine=piper (default: {DEFAULT_PIPER_VOICE_ID}). Same as --voice if "
        "that looks like a Piper id.",
    )
    parser.add_argument(
        "--piper-model-dir",
        type=Path,
        default=None,
        help="Directory containing <voice>.onnx and .json (default: %%LOCALAPPDATA%%\\narrator\\piper).",
    )
    parser.add_argument(
        "--piper-model",
        default=None,
        metavar="PATH",
        help="Explicit path to a Piper .onnx file (overrides --piper-voice directory lookup).",
    )
    parser.add_argument(
        "--piper-cuda",
        action="store_true",
        help="Run Piper ONNX on CUDA (requires onnxruntime-gpu and a capable GPU).",
    )
    parser.add_argument(
        "--list-piper-voices",
        action="store_true",
        help="List Piper voice ids from Hugging Face (network; install: narrator[speak-piper]).",
    )
    args = parser.parse_args()

    if args.list_xtts_speakers:
        settings = build_runtime_settings(
            config_explicit=args.config,
            voice=None,
            rate=None,
            volume=None,
            speak_hotkey=None,
            listen_hotkey=None,
            legacy_hotkey=None,
            silent=False,
            verbose=args.verbose,
            speak_engine="xtts",
            xtts_model=args.xtts_model,
            xtts_speaker=args.xtts_speaker,
            xtts_language=args.xtts_language,
            xtts_device=args.xtts_device,
            xtts_speaker_wav=args.xtts_speaker_wav,
            listen_engine=None,
            whisper_model=None,
            whisper_device=None,
            listen_whisper_refine_punctuation=None,
            whisper_beam_size=None,
            whisper_initial_prompt=None,
            whisper_greedy=None,
            whisper_chunk_interval_seconds=None,
            piper_voice=None,
            piper_model_dir=None,
            piper_model_path=None,
            piper_cuda=None,
        )
        try:
            from narrator.tts_xtts import list_speakers as xtts_list_speakers

            names = xtts_list_speakers(settings)
        except ImportError as e:
            print("Install: pip install narrator[speak-xtts]", file=sys.stderr)
            print(e, file=sys.stderr)
            sys.exit(4)
        print("XTTS built-in speakers (pass as --voice when using --speak-engine xtts):")
        for n in names:
            print(f"  {n}")
        sys.exit(0)

    if args.list_piper_voices:
        try:
            from piper.download_voices import list_voices as piper_list_voices
        except ImportError as e:
            print("Install: pip install narrator[speak-piper]", file=sys.stderr)
            print(e, file=sys.stderr)
            sys.exit(4)
        piper_list_voices()
        sys.exit(0)

    if args.list_voices:
        winrt: list[dict[str, str]] | None
        try:
            winrt = list_winrt_voices()
        except Exception as e:
            print(f"Warning: could not enumerate WinRT voices: {e}", file=sys.stderr)
            winrt = None
        rows = list_installed_voices()
        print(format_voice_table(rows, winrt_rows=winrt))
        sys.exit(0)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.hide_console:
        hide_console_window()

    dpi.try_set_per_monitor_v2()

    settings = build_runtime_settings(
        config_explicit=args.config,
        voice=args.voice,
        rate=None,
        volume=args.volume,
        speak_hotkey=args.speak_hotkey,
        listen_hotkey=args.listen_hotkey,
        legacy_hotkey=args.hotkey,
        silent=args.silent,
        verbose=args.verbose,
        speak_engine=args.speak_engine,
        xtts_model=args.xtts_model,
        xtts_speaker=args.xtts_speaker,
        xtts_language=args.xtts_language,
        xtts_device=args.xtts_device,
        xtts_speaker_wav=args.xtts_speaker_wav,
        piper_voice=args.piper_voice,
        piper_model_dir=str(args.piper_model_dir) if args.piper_model_dir else None,
        piper_model_path=args.piper_model,
        piper_cuda=True if args.piper_cuda else None,
        listen_engine=args.listen_engine,
        whisper_model=args.whisper_model,
        whisper_device=args.whisper_device,
        listen_whisper_refine_punctuation=False if args.no_whisper_punct_refine else None,
        whisper_beam_size=args.whisper_beam_size,
        whisper_initial_prompt=args.whisper_prompt,
        whisper_greedy=True if args.whisper_greedy else None,
        whisper_chunk_interval_seconds=args.whisper_chunk_interval,
        speak_exclude_hyperlinks=False if args.no_speak_exclude_hyperlinks else None,
        speak_exclude_math=False if args.no_speak_exclude_math else None,
        speak_exclude_markup=False if args.no_speak_exclude_markup else None,
        speak_exclude_citations=False if args.no_speak_exclude_citations else None,
        speak_exclude_technical=False if args.no_speak_exclude_technical else None,
        speak_exclude_chrome=False if args.no_speak_exclude_chrome else None,
        speak_exclude_emoji=False if args.no_speak_exclude_emoji else None,
        speak_insert_line_pauses=False if args.no_speak_insert_line_pauses else None,
        speak_pause_between_lines=True if args.speak_pause_between_lines else None,
        speak_winrt_use_ssml_breaks=False if args.no_speak_winrt_ssml_breaks else None,
        speak_pause_line_ms=args.speak_pause_line_ms,
        speak_pause_paragraph_ms=args.speak_pause_paragraph_ms,
        speak_chunk_max_chars=args.speak_chunk_max_chars,
    )

    try:
        from narrator.tts_piper import (
            default_piper_data_dir,
            is_piper_available,
            piper_unavailable_reason,
            resolve_piper_onnx_path_from_settings,
        )

        _piper_ok = is_piper_available()
        _onnx = resolve_piper_onnx_path_from_settings(settings)
        logging.info(
            "TTS: cli speak_engine=%r -> resolved=%r | piper_import_ok=%s piper_onnx=%s (default dir %s)",
            args.speak_engine,
            settings.speak_engine,
            _piper_ok,
            _onnx,
            default_piper_data_dir(),
        )
        if not _piper_ok and piper_unavailable_reason():
            logging.warning(
                "Piper did not import (onnxruntime / DLL issues are common on Windows): %s",
                piper_unavailable_reason(),
            )
    except Exception as e:
        logging.debug("TTS diagnostics skipped: %s", e)

    try:
        speak_hk = parse_hotkey_spec(settings.speak_hotkey)
        listen_hk = parse_hotkey_spec(settings.listen_hotkey)
    except ValueError as e:
        logging.error("Invalid hotkey in CLI or config: %s", e)
        sys.exit(2)
    if speak_hk == listen_hk:
        logging.error("Speak and listen hotkeys must differ (got %s for both).", speak_hk)
        sys.exit(2)

    from narrator import speech, worker

    speak_queue: queue.Queue = queue.Queue()
    listen_queue: queue.Queue = queue.Queue()
    speak_thread = threading.Thread(
        target=worker.speak_worker_loop,
        args=(speak_queue, settings),
        daemon=False,
        name="narrator-speak",
    )
    listen_thread = threading.Thread(
        target=listen_worker_loop,
        args=(listen_queue, settings),
        daemon=False,
        name="narrator-listen",
    )
    speak_thread.start()
    listen_thread.start()

    if args.tray:
        try:
            from narrator.tray_mode import run_with_tray
        except ImportError as e:
            logging.error(
                "Tray mode requires optional dependencies. Install with: pip install narrator[tray] (%s)",
                e,
            )
            speak_queue.put(SHUTDOWN)
            listen_queue.put(SHUTDOWN)
            speech.stop_playback()
            speak_thread.join(timeout=5.0)
            listen_thread.join(timeout=5.0)
            sys.exit(3)
        run_with_tray(speak_queue, listen_queue, speak_thread, listen_thread, settings, speak_hk, listen_hk)
        return

    if settings.listen_engine == "whisper":
        if settings.whisper_chunk_interval_seconds > 0:
            listen_mode = (
                f"Whisper chunked (auto transcribe every ~{settings.whisper_chunk_interval_seconds:.0f}s; "
                f"{settings.listen_hotkey} again = stop, flush last audio, end; pip install narrator[listen-whisper])"
            )
        else:
            listen_mode = "Whisper (record, then transcribe; pip install narrator[listen-whisper])"
    else:
        listen_mode = "WinRT dictation (live)"
    if settings.speak_engine == "xtts":
        speak_mode = f"XTTS ({settings.xtts_model})"
    elif settings.speak_engine == "piper":
        from narrator.tts_piper import resolve_piper_onnx_path_from_settings

        pm = resolve_piper_onnx_path_from_settings(settings)
        speak_mode = f"Piper ({pm.name if pm else settings.piper_voice})"
    else:
        speak_mode = "WinRT TTS"
    logging.info(
        "Speak: %s (hover, then toggle) — Listen: %s — %s. Ctrl+C to exit.",
        speak_hk,
        listen_hk,
        listen_mode,
    )
    logging.info("Speak engine: %s", speak_mode)
    try:
        from narrator.tts_xtts import is_xtts_available

        if settings.speak_engine == "winrt":
            if not is_xtts_available():
                logging.info(
                    "Install narrator[speak-xtts] for Coqui XTTS, or narrator[speak-piper] + prefetch_piper_voice "
                    "for Piper (speak_engine=auto uses XTTS when Coqui is installed, else Piper when a voice is on disk)."
                )
    except Exception:
        pass
    logging.info(
        "Listen uses the full chord together (e.g. Ctrl AND Alt AND the letter). Plain Ctrl+L does nothing — use %s.",
        settings.listen_hotkey,
    )
    if settings.listen_engine == "whisper":
        if settings.whisper_chunk_interval_seconds > 0:
            logging.info(
                "Whisper chunked mode: press %s once (start beep), then speak. Text is typed automatically every "
                "~%.1fs; do not press the hotkey again for each chunk. Press %s again only to stop: remaining audio is "
                "transcribed and typed, then the session ends (end beep).",
                settings.listen_hotkey,
                settings.whisper_chunk_interval_seconds,
                settings.listen_hotkey,
            )
        else:
            logging.info(
                "Whisper listen is two steps: (1) press %s once to start recording — you should hear a short beep; "
                "(2) speak; (3) press %s again to stop and transcribe (second beep). Nothing is typed until step 3.",
                settings.listen_hotkey,
                settings.listen_hotkey,
            )
        logging.info(
            "Whisper speed/quality: defaults use model=%s, beam=%d. Fastest CPU: --whisper-model tiny; more accurate: "
            "small or medium; GPU: --whisper-device cuda. --whisper-greedy can help odd phrasing. "
            "STT is weak on read-aloud UI text (Ctrl, Alt, shortcuts).",
            settings.whisper_model,
            settings.whisper_beam_size,
        )

    try:
        with build_listener(
            speak_queue,
            listen_queue,
            speak_hotkey=settings.speak_hotkey,
            listen_hotkey=settings.listen_hotkey,
        ) as hotkeys:
            try:
                hotkeys.join()
            except KeyboardInterrupt:
                pass
    finally:
        speak_queue.put(SHUTDOWN)
        listen_queue.put(SHUTDOWN)
        speech.stop_playback()
        speak_thread.join(timeout=30.0)
        listen_thread.join(timeout=30.0)


if __name__ == "__main__":
    main()
