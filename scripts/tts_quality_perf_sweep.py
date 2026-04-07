"""
Recommended TTS performance + quality sweep.

Runs a matrix of synthesis profiles, then reports:
- speed (synth wall time, RTF),
- generated-audio quality heuristics (echo/overlap/dropout/clipping/instability),
- ranked candidates by speed among quality-passing runs.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import analyze_audio_recordings as aar
from tts_speed_diagnostics import DEFAULT_BENCH_TEXT


@dataclass
class SweepProfile:
    name: str
    engine: str
    xtts_device: str | None = None
    piper_cuda: bool = False


def _audio_duration_seconds(wav_path: Path) -> float:
    with wave.open(str(wav_path), "rb") as wf:
        n = wf.getnframes()
        sr = wf.getframerate()
    if sr <= 0:
        return 0.0
    return float(n / sr)


def _synthesize_once(settings: Any, profile: SweepProfile, wav_path: Path, text: str) -> None:
    engine = profile.engine
    if engine == "winrt":
        if sys.platform != "win32":
            raise RuntimeError("winrt benchmark requires Windows runtime")
        from narrator import speech

        ok = speech.synthesize_to_path_prefetch(text, wav_path, settings, context_prefix=None)
        if not ok:
            raise RuntimeError("winrt synthesis failed")
        return
    if engine == "piper":
        from narrator.tts_piper import is_piper_available, synthesize_piper_to_path

        if not is_piper_available():
            raise RuntimeError("piper-tts not installed/importable")
        synthesize_piper_to_path(wav_path, text, settings)
        return
    if engine == "xtts":
        from narrator.tts_xtts import is_xtts_available, synthesize_xtts_to_path

        if not is_xtts_available():
            raise RuntimeError("coqui-tts not installed/importable")
        synthesize_xtts_to_path(wav_path, text, settings)
        return
    raise RuntimeError(f"unsupported engine: {engine}")


def _build_settings(profile: SweepProfile) -> Any:
    from narrator.settings import build_runtime_settings

    return build_runtime_settings(
        config_explicit=None,
        voice=None,
        rate=None,
        volume=1.0,
        speak_hotkey=None,
        listen_hotkey=None,
        legacy_hotkey=None,
        silent=False,
        verbose=False,
        speak_engine=profile.engine,
        xtts_model=None,
        xtts_speaker=None,
        xtts_language=None,
        xtts_device=profile.xtts_device if profile.engine == "xtts" else None,
        xtts_speaker_wav=None,
        piper_voice=None,
        piper_model_dir=None,
        piper_model_path=None,
        piper_cuda=(True if profile.piper_cuda else None) if profile.engine == "piper" else None,
        listen_engine=None,
        whisper_model=None,
        whisper_device=None,
        listen_whisper_refine_punctuation=None,
        whisper_beam_size=None,
        whisper_initial_prompt=None,
        whisper_greedy=None,
        whisper_chunk_interval_seconds=None,
        # Speed sweep: isolate TTS generation cost from neural LLM text cleanup.
        speak_text_llm_force_for_neural=False,
    )


def _profile_matrix(
    engines: list[str],
    xtts_devices: list[str],
    piper_modes: list[str],
) -> list[SweepProfile]:
    out: list[SweepProfile] = []
    if "winrt" in engines:
        out.append(SweepProfile(name="winrt-default", engine="winrt"))
    if "piper" in engines:
        for mode in piper_modes:
            use_cuda = mode == "cuda"
            out.append(SweepProfile(name=f"piper-{mode}", engine="piper", piper_cuda=use_cuda))
    if "xtts" in engines:
        for dev in xtts_devices:
            out.append(SweepProfile(name=f"xtts-{dev}", engine="xtts", xtts_device=dev))
    return out


def _run_profile(
    profile: SweepProfile,
    text: str,
    out_dir: Path,
    *,
    warmup_runs: int,
    measured_runs: int,
    quality_thresholds: dict[str, float],
) -> dict[str, Any]:
    settings = _build_settings(profile)
    pdir = out_dir / profile.name
    pdir.mkdir(parents=True, exist_ok=True)

    synth_times: list[float] = []
    audio_durations: list[float] = []
    wav_for_analysis: Path | None = None

    total_runs = max(0, warmup_runs) + max(1, measured_runs)
    for i in range(total_runs):
        is_warmup = i < warmup_runs
        if is_warmup:
            tmp = NamedTemporaryFile(suffix=".wav", delete=False)
            tmp.close()
            wav_path = Path(tmp.name)
        else:
            wav_path = pdir / f"run_{i - warmup_runs + 1}.wav"

        t0 = time.perf_counter()
        _synthesize_once(settings, profile, wav_path, text)
        dt = time.perf_counter() - t0
        dur = _audio_duration_seconds(wav_path)

        if is_warmup:
            wav_path.unlink(missing_ok=True)
        else:
            wav_for_analysis = wav_path
            synth_times.append(dt)
            audio_durations.append(dur)

    if not synth_times or not audio_durations or wav_for_analysis is None:
        raise RuntimeError("no measured runs completed")

    mean_synth = float(statistics.mean(synth_times))
    p50_synth = float(statistics.median(synth_times))
    mean_audio = float(statistics.mean(audio_durations))
    rtf_mean = (mean_synth / mean_audio) if mean_audio > 0 else float("inf")

    quality = aar.analyze_wav(wav_for_analysis)
    quality_passed, quality_checks = aar._quality_gate_checks(
        quality,
        max_echo=quality_thresholds["max_echo"],
        max_overlap=quality_thresholds["max_overlap"],
        max_clip=quality_thresholds["max_clip"],
        max_dropout=quality_thresholds["max_dropout"],
        max_instability=quality_thresholds["max_instability"],
        max_quality_risk=quality_thresholds["max_quality_risk"],
    )

    words = max(1, len(text.split()))
    chars = max(1, len(text))
    return {
        "profile": profile.name,
        "engine": profile.engine,
        "xtts_device": profile.xtts_device,
        "piper_cuda": bool(profile.piper_cuda),
        "runs": len(synth_times),
        "synth_time_mean_s": round(mean_synth, 4),
        "synth_time_p50_s": round(p50_synth, 4),
        "audio_duration_mean_s": round(mean_audio, 4),
        "rtf_mean": round(rtf_mean, 4),
        "chars_per_synth_sec": round(chars / max(mean_synth, 1e-9), 2),
        "words_per_synth_sec": round(words / max(mean_synth, 1e-9), 2),
        "quality": quality,
        "quality_gate_passed": bool(quality_passed),
        "quality_gate_checks": quality_checks,
        "last_wav": str(wav_for_analysis.resolve()),
        "quality_speed_score": round((1.0 / max(rtf_mean, 1e-9)) * (1.0 - float(quality["quality_risk_0_1"])), 6),
    }


def _normalize_quality_thresholds(args: argparse.Namespace) -> dict[str, float]:
    q = {
        "max_echo": float(args.max_echo),
        "max_overlap": float(args.max_overlap),
        "max_clip": float(args.max_clip),
        "max_dropout": float(args.max_dropout),
        "max_instability": float(args.max_instability),
        "max_quality_risk": float(args.max_quality_risk),
    }
    if args.strict:
        q["max_echo"] = min(q["max_echo"], 0.55)
        q["max_overlap"] = min(q["max_overlap"], 0.55)
        q["max_clip"] = min(q["max_clip"], 0.20)
        q["max_dropout"] = min(q["max_dropout"], 0.45)
        q["max_instability"] = min(q["max_instability"], 0.60)
        q["max_quality_risk"] = min(q["max_quality_risk"], 0.55)
    return q


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Run a recommended TTS performance/quality sweep and rank profiles."
    )
    ap.add_argument(
        "--engines",
        type=str,
        default="winrt,piper,xtts",
        help="Comma-separated engines to include (subset of winrt,piper,xtts).",
    )
    ap.add_argument(
        "--xtts-devices",
        type=str,
        default="auto,cpu,cuda",
        help="Comma-separated XTTS devices to sweep when xtts is enabled.",
    )
    ap.add_argument(
        "--piper-modes",
        type=str,
        default="cpu,cuda",
        help="Comma-separated Piper modes (cpu,cuda) to sweep when piper is enabled.",
    )
    ap.add_argument("--warmup-runs", type=int, default=1, help="Warmup runs per profile (default: 1).")
    ap.add_argument("--runs", type=int, default=2, help="Measured runs per profile (default: 2).")
    ap.add_argument("--text", type=str, default=None, help="Benchmark text.")
    ap.add_argument("--text-file", type=Path, default=None, help="Benchmark text file (overrides --text).")
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path("audio_selftest_logs") / "tts_perf_sweep",
        help="Output directory for generated WAVs and report.",
    )
    ap.add_argument("--json-out", type=Path, default=None, help="Optional JSON report path.")
    ap.add_argument("--print-json", action="store_true", help="Print JSON report.")
    ap.add_argument("--strict", action="store_true", help="Apply stricter quality thresholds.")
    ap.add_argument("--max-echo", type=float, default=0.70)
    ap.add_argument("--max-overlap", type=float, default=0.70)
    ap.add_argument("--max-clip", type=float, default=0.30)
    ap.add_argument("--max-dropout", type=float, default=0.60)
    ap.add_argument("--max-instability", type=float, default=0.75)
    ap.add_argument("--max-quality-risk", type=float, default=0.70)
    return ap


def main() -> int:
    args = build_parser().parse_args()

    text = DEFAULT_BENCH_TEXT
    if args.text_file is not None:
        text = args.text_file.read_text(encoding="utf-8")
    elif args.text is not None:
        text = args.text
    text = text.strip()
    if not text:
        raise SystemExit("Benchmark text is empty.")

    engines = [s.strip().lower() for s in str(args.engines).split(",") if s.strip()]
    xtts_devices = [s.strip().lower() for s in str(args.xtts_devices).split(",") if s.strip()]
    piper_modes = [s.strip().lower() for s in str(args.piper_modes).split(",") if s.strip()]
    allowed_engines = {"winrt", "piper", "xtts"}
    allowed_xtts = {"auto", "cpu", "cuda"}
    allowed_piper = {"cpu", "cuda"}
    engines = [e for e in engines if e in allowed_engines]
    xtts_devices = [d for d in xtts_devices if d in allowed_xtts]
    piper_modes = [m for m in piper_modes if m in allowed_piper]
    if not engines:
        raise SystemExit("No valid engines requested.")
    if "xtts" in engines and not xtts_devices:
        raise SystemExit("xtts selected but no valid --xtts-devices provided.")
    if "piper" in engines and not piper_modes:
        raise SystemExit("piper selected but no valid --piper-modes provided.")

    profiles = _profile_matrix(engines, xtts_devices, piper_modes)
    quality_thresholds = _normalize_quality_thresholds(args)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for p in profiles:
        try:
            r = _run_profile(
                p,
                text,
                out_dir,
                warmup_runs=max(0, int(args.warmup_runs)),
                measured_runs=max(1, int(args.runs)),
                quality_thresholds=quality_thresholds,
            )
            results.append(r)
            print(
                f"[{p.name}] rtf={r['rtf_mean']:.3f} "
                f"quality_pass={r['quality_gate_passed']} risk={r['quality']['quality_risk_0_1']:.3f}"
            )
        except Exception as e:
            failed.append({"profile": p.name, "error": str(e)})
            print(f"[{p.name}] ERROR: {e}")

    passing = [r for r in results if bool(r.get("quality_gate_passed"))]
    ranked = sorted(passing, key=lambda r: float(r.get("rtf_mean", 1e9)))

    report: dict[str, Any] = {
        "text_chars": len(text),
        "text_words": len(text.split()),
        "quality_thresholds": quality_thresholds,
        "profiles_total": len(profiles),
        "results": results,
        "failed": failed,
        "quality_passing_ranked_by_rtf": [
            {
                "profile": r["profile"],
                "engine": r["engine"],
                "rtf_mean": r["rtf_mean"],
                "quality_risk_0_1": r["quality"]["quality_risk_0_1"],
                "quality_speed_score": r["quality_speed_score"],
            }
            for r in ranked
        ],
        "best_profile": ranked[0]["profile"] if ranked else None,
    }

    json_out = args.json_out if args.json_out is not None else (out_dir / "sweep_report.json")
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {json_out}")

    if args.print_json:
        print(json.dumps(report, indent=2))

    if not results:
        return 3
    if not passing:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

