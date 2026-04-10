"""
TTS speed diagnostics benchmark.

Measures synthesis throughput by engine and reports:
- synthesis wall time,
- generated audio duration,
- real-time factor (RTF = synth_time / audio_duration; lower is faster),
- chars/sec and words/sec.

This script does not run hotkeys/UIA; it only benchmarks synthesis functions.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import wave
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


DEFAULT_BENCH_TEXT = (
    "Narrator speed diagnostics benchmark. "
    "This text is intentionally long enough to measure synthesis throughput reliably. "
    "We evaluate runtime, generated duration, and real time factor. "
    "Consistent pronunciation and low latency are both important for perceived quality. "
    "The quick brown fox jumps over the lazy dog. "
    "One two three four five six seven eight nine ten. "
    "Repeat this segment to ensure the benchmark has enough audio length. "
    "Narrator speed diagnostics benchmark. "
    "This text is intentionally long enough to measure synthesis throughput reliably. "
    "We evaluate runtime, generated duration, and real time factor. "
    "Consistent pronunciation and low latency are both important for perceived quality. "
)


def _audio_duration_seconds(wav_path: Path) -> float:
    with wave.open(str(wav_path), "rb") as wf:
        n = wf.getnframes()
        sr = wf.getframerate()
    if sr <= 0:
        return 0.0
    return float(n / sr)


def _bench_once(engine: str, text: str, settings: Any) -> dict[str, Any]:
    tmp = NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    wav_path = Path(tmp.name)
    try:
        if engine == "winrt":
            if sys.platform != "win32":
                raise RuntimeError("winrt benchmark requires Windows runtime")
            from narrator import speech

            synth_fn = lambda: speech.synthesize_to_path_prefetch(text, wav_path, settings, context_prefix=None)
        elif engine == "piper":
            from narrator.tts_piper import is_piper_available, synthesize_piper_to_path

            if not is_piper_available():
                raise RuntimeError("piper-tts not installed/importable")
            synth_fn = lambda: (synthesize_piper_to_path(wav_path, text, settings) or True)
        elif engine == "xtts":
            from narrator.tts_xtts import is_xtts_available, synthesize_xtts_to_path

            if not is_xtts_available():
                raise RuntimeError("coqui-tts not installed/importable")
            synth_fn = lambda: (synthesize_xtts_to_path(wav_path, text, settings) or True)
        else:
            raise RuntimeError(f"unsupported engine: {engine}")

        t0 = time.perf_counter()
        ok = bool(synth_fn())
        dt = time.perf_counter() - t0
        if not ok or not wav_path.is_file():
            raise RuntimeError(f"{engine} synthesis failed")
        dur = _audio_duration_seconds(wav_path)
        words = max(1, len(text.split()))
        chars = max(1, len(text))
        rtf = (dt / dur) if dur > 0 else float("inf")
        return {
            "engine": engine,
            "synth_time_s": round(dt, 4),
            "audio_duration_s": round(dur, 4),
            "rtf": round(rtf, 4),
            "chars_per_synth_sec": round(chars / max(dt, 1e-9), 2),
            "words_per_synth_sec": round(words / max(dt, 1e-9), 2),
            "text_chars": chars,
            "text_words": words,
        }
    finally:
        wav_path.unlink(missing_ok=True)


def _build_settings_for_engine(engine: str, args: argparse.Namespace) -> Any:
    from narrator.settings import build_runtime_settings

    # Keep benchmark focused on TTS engine cost; do not force neural LLM clean-up.
    return build_runtime_settings(
        config_explicit=None,
        voice=None,
        rate=None,
        volume=1.0,
        speak_hotkey=None,
        listen_hotkey=None,
        legacy_hotkey=None,
        silent=False,
        verbose=bool(args.verbose),
        speak_engine=engine,
        xtts_model=None,
        xtts_speaker=None,
        xtts_language=None,
        xtts_device=args.xtts_device if engine == "xtts" else None,
        xtts_speaker_wav=None,
        piper_voice=None,
        piper_model_dir=None,
        piper_model_path=None,
        piper_cuda=(True if args.piper_cuda else None) if engine == "piper" else None,
        listen_engine=None,
        whisper_model=None,
        whisper_device=None,
        listen_whisper_refine_punctuation=None,
        whisper_beam_size=None,
        whisper_initial_prompt=None,
        whisper_greedy=None,
        whisper_chunk_interval_seconds=None,
        speak_text_llm_force_for_neural=False,
    )


def _run_engine(engine: str, text: str, args: argparse.Namespace) -> dict[str, Any]:
    settings = _build_settings_for_engine(engine, args)
    return _bench_once(engine, text, settings)


def main() -> int:
    ap = argparse.ArgumentParser(description="Benchmark Narrator TTS synthesis speed by engine.")
    ap.add_argument(
        "--engines",
        type=str,
        default="winrt,piper,xtts",
        help="Comma-separated engine list (subset of winrt,piper,xtts).",
    )
    ap.add_argument(
        "--text",
        type=str,
        default=None,
        help="Benchmark text. If omitted, uses a built-in benchmark paragraph.",
    )
    ap.add_argument(
        "--text-file",
        type=Path,
        default=None,
        help="Optional text file for benchmark input (overrides --text).",
    )
    ap.add_argument(
        "--xtts-device",
        type=str,
        choices=("auto", "cpu", "cuda"),
        default="auto",
        help="XTTS torch device when benchmarking xtts.",
    )
    ap.add_argument(
        "--piper-cuda",
        action="store_true",
        help="Use Piper CUDA path when benchmarking piper (requires onnxruntime-gpu).",
    )
    ap.add_argument("--json-out", type=Path, default=None, help="Optional JSON report output path.")
    ap.add_argument("--print-json", action="store_true", help="Print full report JSON.")
    ap.add_argument("--verbose", action="store_true", help="Enable verbose runtime settings logging.")
    args = ap.parse_args()

    text = DEFAULT_BENCH_TEXT
    if args.text_file is not None:
        text = args.text_file.read_text(encoding="utf-8")
    elif args.text is not None:
        text = args.text
    text = text.strip()
    if not text:
        raise SystemExit("Benchmark text is empty.")

    req = [s.strip().lower() for s in str(args.engines).split(",") if s.strip()]
    allowed = {"winrt", "piper", "xtts"}
    engines = [e for e in req if e in allowed]
    if not engines:
        raise SystemExit("No valid engines requested.")

    results: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for engine in engines:
        try:
            out = _run_engine(engine, text, args)
            results.append(out)
            print(
                f"[{engine}] synth={out['synth_time_s']:.3f}s "
                f"audio={out['audio_duration_s']:.3f}s rtf={out['rtf']:.3f} "
                f"chars/s={out['chars_per_synth_sec']:.1f}"
            )
        except Exception as e:
            failed.append({"engine": engine, "error": str(e)})
            print(f"[{engine}] ERROR: {e}")

    report: dict[str, Any] = {
        "text_chars": len(text),
        "text_words": len(text.split()),
        "results": results,
        "failed": failed,
    }
    if results:
        fastest = min(results, key=lambda r: float(r.get("rtf", 1e9)))
        report["fastest_engine_by_rtf"] = fastest["engine"]
        report["fastest_rtf"] = fastest["rtf"]
    else:
        report["fastest_engine_by_rtf"] = None
        report["fastest_rtf"] = None

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Wrote {args.json_out}")

    if args.print_json:
        print(json.dumps(report, indent=2))

    return 0 if results else 3


if __name__ == "__main__":
    raise SystemExit(main())
