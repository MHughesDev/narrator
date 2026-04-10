"""
Analyze WAV recordings for playback quality regressions and voice irregularities.

Primary goals:
- detect echo/overlap (legacy metrics),
- detect likely skips/dropouts/clipping/robotic instability,
- produce deterministic pass/fail gates for agent automation.

Uses numpy + librosa. Optional: set OPENAI_API_KEY and pass --openai
for a short natural-language interpretation of the metrics (text-only; no audio uploaded).

Usage:
  python scripts/analyze_audio_recordings.py audio_selftest_logs/loopback_*.wav
  python scripts/analyze_audio_recordings.py one.wav --json-out report.json --openai --strict
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


def analyze_wav(path: Path) -> dict[str, Any]:
    import numpy as np

    try:
        import librosa
    except ImportError as e:
        raise RuntimeError("librosa required") from e

    y, sr = librosa.load(str(path), sr=None, mono=True)
    dur = float(len(y) / sr)
    rms = float(np.sqrt(np.mean(y**2)))
    peak = float(np.max(np.abs(y)))

    # Envelope for autocorrelation (echo = energy in delayed self-similarity)
    env = np.abs(y)
    mx = float(np.max(env)) + 1e-12
    env = env / mx
    hop = max(1, int(sr * 0.005))  # 5 ms steps for speed
    env_ds = env[::hop]
    env_ds = env_ds - float(np.mean(env_ds))
    ac = np.correlate(env_ds, env_ds, mode="full")
    ac = ac[len(ac) // 2 :]
    ac0 = float(ac[0]) + 1e-12
    ac = ac / ac0
    # Lags 40–500 ms in downsampled domain
    lag0 = int((0.040 * sr) / hop)
    lag1 = int((0.500 * sr) / hop)
    lag1 = min(lag1, len(ac) - 1)
    echo_ratio = 0.0
    if lag1 > lag0:
        echo_ratio = float(np.max(ac[lag0:lag1]))

    # RMS in short frames — many distinct speech-like bursts may indicate overlap
    frame = int(0.05 * sr)
    if frame < 256:
        frame = 256
    n_frames = len(y) // frame
    rms_blocks: list[float] = []
    for i in range(n_frames):
        seg = y[i * frame : (i + 1) * frame]
        rms_blocks.append(float(np.sqrt(np.mean(seg**2))))
    rb = np.array(rms_blocks, dtype=np.float64)
    thr = max(rms * 0.35, 1e-5)
    active = rb > thr
    # Count transitions to active (rough "onset" count)
    edges = int(np.sum(np.diff(active.astype(np.int32)) > 0))
    burstiness = float(edges / max(dur, 0.1))

    # Crest factor
    crest = (peak / (rms + 1e-12)) if rms > 1e-8 else 0.0

    # --- New "weirdness" metrics ---
    # Clipping: proportion of samples near int16 full-scale (float normalized around +/-1.0)
    clip_level = 0.985
    clip_ratio = float(np.mean(np.abs(y) >= clip_level))

    # Dropout/silence gaps:
    # treat a frame as effectively silent if RMS is tiny relative to global RMS.
    # then count long contiguous silent runs.
    if rb.size:
        silence_thr = max(rms * 0.10, 5e-5)
        silent = rb <= silence_thr
    else:
        silent = np.array([], dtype=np.bool_)

    longest_silent_frames = 0
    silent_runs_over_200ms = 0
    cur = 0
    min_silent_run_frames = max(1, int(0.20 / (frame / sr)))
    for s in silent:
        if bool(s):
            cur += 1
            if cur > longest_silent_frames:
                longest_silent_frames = cur
        else:
            if cur >= min_silent_run_frames:
                silent_runs_over_200ms += 1
            cur = 0
    if cur >= min_silent_run_frames:
        silent_runs_over_200ms += 1

    frame_s = frame / sr
    longest_silent_s = float(longest_silent_frames * frame_s)

    # "Jitter"/robotic instability proxy:
    # high frame-to-frame change in spectral centroid often appears in glitchy/metallic speech.
    try:
        cent = librosa.feature.spectral_centroid(y=y, sr=sr).ravel()
    except Exception:
        cent = np.array([], dtype=np.float64)
    centroid_delta_mean = float(np.mean(np.abs(np.diff(cent)))) if cent.size > 1 else 0.0

    # Zero crossing rate as a coarse roughness/harshness signal.
    try:
        zcr = librosa.feature.zero_crossing_rate(y, frame_length=2048, hop_length=512).ravel()
        zcr_mean = float(np.mean(zcr)) if zcr.size else 0.0
    except Exception:
        zcr_mean = 0.0

    # Heuristic scores 0..1 (not calibrated clinical tests)
    echo_score = min(1.0, max(0.0, (echo_ratio - 0.12) / 0.45))
    overlap_score = min(1.0, max(0.0, (burstiness - 1.5) / 6.0))
    clip_score = min(1.0, max(0.0, clip_ratio / 0.01))  # 1%+ near full-scale is usually bad
    dropout_score = min(
        1.0,
        max(
            0.0,
            max(
                (longest_silent_s - 0.25) / 1.0,
                silent_runs_over_200ms / 8.0,
            ),
        ),
    )
    instability_score = min(
        1.0,
        max(
            0.0,
            max(
                (centroid_delta_mean - 120.0) / 450.0,
                (zcr_mean - 0.09) / 0.18,
            ),
        ),
    )
    quality_risk = float(
        min(
            1.0,
            (
                echo_score * 0.28
                + overlap_score * 0.22
                + clip_score * 0.20
                + dropout_score * 0.18
                + instability_score * 0.12
            ),
        )
    )

    return {
        "file": str(path.resolve()),
        "duration_s": round(dur, 3),
        "sample_rate": int(sr),
        "rms": round(rms, 6),
        "peak": round(peak, 6),
        "crest_factor": round(crest, 3),
        "autocorr_echo_ratio_40_500ms": round(echo_ratio, 4),
        "echo_likelihood_0_1": round(echo_score, 3),
        "rms_burst_edges_per_s": round(burstiness, 3),
        "overlap_likelihood_0_1": round(overlap_score, 3),
        "clip_ratio_near_fullscale": round(clip_ratio, 6),
        "clip_likelihood_0_1": round(clip_score, 3),
        "longest_silent_run_s": round(longest_silent_s, 4),
        "silent_runs_over_200ms": int(silent_runs_over_200ms),
        "dropout_likelihood_0_1": round(dropout_score, 3),
        "spectral_centroid_delta_mean_hz": round(centroid_delta_mean, 3),
        "zcr_mean": round(zcr_mean, 5),
        "instability_likelihood_0_1": round(instability_score, 3),
        "quality_risk_0_1": round(quality_risk, 3),
    }


def maybe_openai(metrics: dict[str, Any]) -> str | None:
    if not (os.environ.get("OPENAI_API_KEY") or "").strip():
        return None
    try:
        from openai import OpenAI
    except ImportError:
        return "(install openai: pip install openai)"

    client = OpenAI()
    payload = json.dumps(metrics, indent=0)
    r = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "You help diagnose TTS playback from numeric audio metrics only. "
                "Echo or chorus may raise autocorr_echo_ratio and echo_likelihood. "
                "Overlapping voices may raise burstiness and overlap_likelihood. "
                "Dropouts/skips may raise longest_silent_run_s and dropout_likelihood. "
                "Clipping may raise clip_ratio_near_fullscale and clip_likelihood. "
                "Robotic instability may raise spectral_centroid_delta_mean_hz and instability_likelihood. "
                "Be concise; suggest next checks if uncertain.",
            },
            {"role": "user", "content": f"Metrics:\n{payload}"},
        ],
        max_tokens=400,
    )
    return (r.choices[0].message.content or "").strip()


def _expand_paths(items: list[Path]) -> list[Path]:
    out: list[Path] = []
    for p in items:
        if p.is_dir():
            out.extend(sorted(p.glob("*.wav")))
        else:
            out.append(p)
    return out


def _quality_gate_checks(
    metrics: dict[str, Any],
    *,
    max_echo: float,
    max_overlap: float,
    max_clip: float,
    max_dropout: float,
    max_instability: float,
    max_quality_risk: float,
) -> tuple[bool, list[dict[str, Any]]]:
    checks = [
        {
            "name": "echo_likelihood_0_1",
            "actual": float(metrics.get("echo_likelihood_0_1", 0.0)),
            "threshold": float(max_echo),
            "relation": "<=",
        },
        {
            "name": "overlap_likelihood_0_1",
            "actual": float(metrics.get("overlap_likelihood_0_1", 0.0)),
            "threshold": float(max_overlap),
            "relation": "<=",
        },
        {
            "name": "clip_likelihood_0_1",
            "actual": float(metrics.get("clip_likelihood_0_1", 0.0)),
            "threshold": float(max_clip),
            "relation": "<=",
        },
        {
            "name": "dropout_likelihood_0_1",
            "actual": float(metrics.get("dropout_likelihood_0_1", 0.0)),
            "threshold": float(max_dropout),
            "relation": "<=",
        },
        {
            "name": "instability_likelihood_0_1",
            "actual": float(metrics.get("instability_likelihood_0_1", 0.0)),
            "threshold": float(max_instability),
            "relation": "<=",
        },
        {
            "name": "quality_risk_0_1",
            "actual": float(metrics.get("quality_risk_0_1", 0.0)),
            "threshold": float(max_quality_risk),
            "relation": "<=",
        },
    ]
    for c in checks:
        c["passed"] = bool(c["actual"] <= c["threshold"])
    return all(bool(c["passed"]) for c in checks), checks


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Analyze WAVs for echo/overlap + glitches (dropout/clipping/instability)."
    )
    ap.add_argument("wavs", nargs="+", type=Path, help="WAV file(s) or directory (all *.wav)")
    ap.add_argument("--json-out", type=Path, default=None, help="Write combined JSON report")
    ap.add_argument(
        "--openai",
        action="store_true",
        help="If OPENAI_API_KEY is set, add a short GPT interpretation of metrics (text only)",
    )
    ap.add_argument(
        "--max-echo",
        type=float,
        default=0.70,
        help="Pass/fail threshold: max echo_likelihood_0_1 (default 0.70).",
    )
    ap.add_argument(
        "--max-overlap",
        type=float,
        default=0.70,
        help="Pass/fail threshold: max overlap_likelihood_0_1 (default 0.70).",
    )
    ap.add_argument(
        "--max-clip",
        type=float,
        default=0.30,
        help="Pass/fail threshold: max clip_likelihood_0_1 (default 0.30).",
    )
    ap.add_argument(
        "--max-dropout",
        type=float,
        default=0.60,
        help="Pass/fail threshold: max dropout_likelihood_0_1 (default 0.60).",
    )
    ap.add_argument(
        "--max-instability",
        type=float,
        default=0.75,
        help="Pass/fail threshold: max instability_likelihood_0_1 (default 0.75).",
    )
    ap.add_argument(
        "--max-quality-risk",
        type=float,
        default=0.70,
        help="Pass/fail threshold: max quality_risk_0_1 (default 0.70).",
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help="Use stricter default quality gates for regression hunting.",
    )
    args = ap.parse_args()

    if args.strict:
        args.max_echo = min(args.max_echo, 0.55)
        args.max_overlap = min(args.max_overlap, 0.55)
        args.max_clip = min(args.max_clip, 0.20)
        args.max_dropout = min(args.max_dropout, 0.45)
        args.max_instability = min(args.max_instability, 0.60)
        args.max_quality_risk = min(args.max_quality_risk, 0.55)

    paths = _expand_paths(list(args.wavs))
    all_out: list[dict[str, Any]] = []
    any_failed = False
    for p in paths:
        if not p.is_file():
            print(f"Missing: {p}", file=sys.stderr)
            continue
        print(f"=== {p} ===")
        try:
            m = analyze_wav(p)
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            continue
        passed, checks = _quality_gate_checks(
            m,
            max_echo=float(args.max_echo),
            max_overlap=float(args.max_overlap),
            max_clip=float(args.max_clip),
            max_dropout=float(args.max_dropout),
            max_instability=float(args.max_instability),
            max_quality_risk=float(args.max_quality_risk),
        )
        m["quality_gate_passed"] = bool(passed)
        m["quality_gate_checks"] = checks
        if not passed:
            any_failed = True

        for k, v in m.items():
            if k == "quality_gate_checks":
                continue
            print(f"  {k}: {v}")
        print("  quality_gate_checks:")
        for c in checks:
            print(
                "   - "
                f"{c['name']}: actual={c['actual']:.3f} {c['relation']} {c['threshold']:.3f} -> "
                f"{'PASS' if c['passed'] else 'FAIL'}"
            )
        if args.openai:
            txt = maybe_openai(m)
            if txt:
                print("  --- OpenAI interpretation ---")
                print(txt)
        all_out.append(m)
        print()

    if args.json_out and all_out:
        args.json_out.write_text(json.dumps(all_out, indent=2), encoding="utf-8")
        print(f"Wrote {args.json_out}")

    if not all_out:
        return 1
    return 4 if any_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
