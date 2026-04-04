"""
Record from the default microphone to WAV files — for loopback testing (mic near speaker).

Usage:
  pip install -e ".[audio-test]"
  python scripts/audio_loopback_record.py --duration 45 --out-dir audio_selftest_logs

While recording: run Narrator in another terminal, hover text, press Ctrl+Alt+S so TTS plays
into the mic. This script does not press keys for you.
"""

from __future__ import annotations

import argparse
import sys
import wave
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Record microphone to WAV (place mic near speaker to capture TTS output)."
    )
    ap.add_argument("--duration", type=float, default=30.0, help="Seconds to record (default: 30)")
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path("audio_selftest_logs"),
        help="Directory for WAV + session log (created if missing)",
    )
    ap.add_argument("--sample-rate", type=int, default=48000, help="Sample rate Hz (default: 48000)")
    ap.add_argument("--channels", type=int, default=1, choices=(1, 2), help="1=mono (default), 2=stereo")
    args = ap.parse_args()

    try:
        import numpy as np
        import sounddevice as sd
    except ImportError as e:
        print("Install: pip install -e \".[audio-test]\"  (needs sounddevice)", file=sys.stderr)
        print(e, file=sys.stderr)
        return 1

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    wav_path = args.out_dir / f"loopback_{stamp}.wav"
    log_path = args.out_dir / f"session_{stamp}.txt"

    try:
        dev = sd.query_devices(kind="input")
        dev_name = dev["name"]
    except Exception as e:
        dev_name = f"(query failed: {e})"

    frames = int(args.duration * args.sample_rate)
    print(f"Default input device: {dev_name}")
    print(f"Recording {args.duration:.1f}s @ {args.sample_rate} Hz -> {wav_path}")
    print("Place mic near speaker; start Narrator and use Ctrl+Alt+S on text NOW.")

    data = sd.rec(
        frames,
        samplerate=args.sample_rate,
        channels=args.channels,
        dtype="float32",
    )
    sd.wait()

    # mono/stereo int16 WAV
    x = np.asarray(data, dtype=np.float32)
    if x.ndim == 1:
        x = x[:, np.newaxis]
    peak = float(np.max(np.abs(x)))
    x16 = (np.clip(x, -1.0, 1.0) * 32767.0).astype(np.int16)

    with wave.open(str(wav_path), "wb") as w:
        w.setnchannels(args.channels)
        w.setsampwidth(2)
        w.setframerate(args.sample_rate)
        if args.channels == 1:
            w.writeframes(x16[:, 0].tobytes())
        else:
            # interleaved L,R
            inter = np.empty(x16.shape[0] * 2, dtype=np.int16)
            inter[0::2] = x16[:, 0]
            inter[1::2] = x16[:, 1]
            w.writeframes(inter.tobytes())

    lines = [
        f"utc_start={stamp}",
        f"duration_s={args.duration}",
        f"sample_rate={args.sample_rate}",
        f"channels={args.channels}",
        f"input_device={dev_name}",
        f"peak_abs_sample={peak:.6f}",
        f"wav_path={wav_path.resolve()}",
        "",
        "Next: python scripts/analyze_audio_recordings.py \"" + str(wav_path) + "\"",
    ]
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Peak sample magnitude: {peak:.4f} (use >0.01 if mic gained)")
    print(f"Saved: {wav_path}")
    print(f"Log:   {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
