"""
Analyze WAV recordings from scripts/audio_loopback_record.py for echo / overlap heuristics.

Uses numpy + librosa (already narrator deps). Optional: set OPENAI_API_KEY and pass --openai
for a short natural-language interpretation of the metrics (text-only; no audio uploaded to API).

Usage:
  python scripts/analyze_audio_recordings.py audio_selftest_logs/loopback_*.wav
  python scripts/analyze_audio_recordings.py one.wav --json-out report.json --openai
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

    # Heuristic scores 0..1 (not calibrated clinical tests)
    echo_score = min(1.0, max(0.0, (echo_ratio - 0.12) / 0.45))
    overlap_score = min(1.0, max(0.0, (burstiness - 1.5) / 6.0))

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


def main() -> int:
    ap = argparse.ArgumentParser(description="Analyze loopback WAVs for echo/overlap heuristics.")
    ap.add_argument("wavs", nargs="+", type=Path, help="WAV file(s) or directory (all *.wav)")
    ap.add_argument("--json-out", type=Path, default=None, help="Write combined JSON report")
    ap.add_argument(
        "--openai",
        action="store_true",
        help="If OPENAI_API_KEY is set, add a short GPT interpretation of metrics (text only)",
    )
    args = ap.parse_args()

    paths = _expand_paths(list(args.wavs))
    all_out: list[dict[str, Any]] = []
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
        for k, v in m.items():
            print(f"  {k}: {v}")
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

    return 0 if all_out else 1


if __name__ == "__main__":
    raise SystemExit(main())
