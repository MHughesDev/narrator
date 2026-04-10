"""
Fixture-based audio inference self-test (download -> transcribe -> assert thresholds).

This script is intended for repeatable agent automation:
1) optionally download a known audio fixture,
2) run Whisper transcription via narrator.listen.whisper_listen,
3) compare transcript against expected text with deterministic metrics.

Usage examples:
  python scripts/audio_inference_selftest.py \
    --audio-url https://raw.githubusercontent.com/Jakobovski/free-spoken-digit-dataset/master/recordings/0_jackson_0.wav \
    --audio-path audio_selftest_logs/fsdd_zero.wav \
    --expected-text "zero"

  python scripts/audio_inference_selftest.py \
    --audio-path tests/fixtures/my_clip.wav \
    --expected-text-file tests/fixtures/my_clip.txt \
    --max-wer 0.40 --min-token-recall 0.60 --min-token-precision 0.60 \
    --json-out audio_selftest_logs/inference_report.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_AUDIO_URL = (
    "https://raw.githubusercontent.com/Jakobovski/free-spoken-digit-dataset/master/recordings/0_jackson_0.wav"
)
DEFAULT_EXPECTED_TEXT = "zero"


def normalize_transcript_text(text: str) -> str:
    """Lowercase and keep only word-like tokens for robust comparison."""
    toks = re.findall(r"[a-z0-9']+", text.lower())
    return " ".join(toks)


def _tokenize_for_compare(text: str) -> list[str]:
    norm = normalize_transcript_text(text)
    return [t for t in norm.split(" ") if t]


def _word_error_rate(reference: list[str], hypothesis: list[str]) -> float:
    """Token-level Levenshtein WER in [0, +inf)."""
    if not reference:
        return 0.0 if not hypothesis else 1.0
    rows = len(reference) + 1
    cols = len(hypothesis) + 1
    dp = [[0] * cols for _ in range(rows)]
    for i in range(rows):
        dp[i][0] = i
    for j in range(cols):
        dp[0][j] = j
    for i in range(1, rows):
        for j in range(1, cols):
            cost = 0 if reference[i - 1] == hypothesis[j - 1] else 1
            dp[i][j] = min(
                dp[i - 1][j] + 1,  # deletion
                dp[i][j - 1] + 1,  # insertion
                dp[i - 1][j - 1] + cost,  # substitution
            )
    return float(dp[-1][-1] / len(reference))


def compute_text_metrics(expected_text: str, observed_text: str) -> dict[str, Any]:
    ref = _tokenize_for_compare(expected_text)
    hyp = _tokenize_for_compare(observed_text)

    ref_counts = Counter(ref)
    hyp_counts = Counter(hyp)
    true_pos = sum(min(ref_counts[w], hyp_counts[w]) for w in ref_counts)

    precision = float(true_pos / len(hyp)) if hyp else (1.0 if not ref else 0.0)
    recall = float(true_pos / len(ref)) if ref else 1.0
    wer = _word_error_rate(ref, hyp)

    return {
        "expected_normalized": " ".join(ref),
        "observed_normalized": " ".join(hyp),
        "expected_token_count": len(ref),
        "observed_token_count": len(hyp),
        "true_positive_tokens": int(true_pos),
        "token_precision": round(precision, 4),
        "token_recall": round(recall, 4),
        "word_error_rate": round(wer, 4),
    }


def evaluate_metrics(
    metrics: dict[str, Any],
    *,
    max_wer: float,
    min_token_recall: float,
    min_token_precision: float,
) -> tuple[bool, list[dict[str, Any]]]:
    checks = [
        {
            "name": "word_error_rate",
            "passed": float(metrics["word_error_rate"]) <= max_wer,
            "actual": float(metrics["word_error_rate"]),
            "threshold": max_wer,
            "relation": "<=",
        },
        {
            "name": "token_recall",
            "passed": float(metrics["token_recall"]) >= min_token_recall,
            "actual": float(metrics["token_recall"]),
            "threshold": min_token_recall,
            "relation": ">=",
        },
        {
            "name": "token_precision",
            "passed": float(metrics["token_precision"]) >= min_token_precision,
            "actual": float(metrics["token_precision"]),
            "threshold": min_token_precision,
            "relation": ">=",
        },
    ]
    passed = all(bool(c["passed"]) for c in checks)
    return passed, checks


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _download_fixture(url: str, out_path: Path, timeout_s: float) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=timeout_s) as resp:
        data = resp.read()
    out_path.write_bytes(data)


def transcribe_audio_fixture(
    audio_path: Path,
    *,
    whisper_model: str,
    whisper_device: str,
    whisper_beam_size: int,
) -> str:
    try:
        from narrator.listen.whisper_listen import _get_model, _transcribe_wav_path_with_model
        from narrator.settings import RuntimeSettings
    except ImportError as e:
        raise RuntimeError(
            "Whisper inference is unavailable. Install extras with: pip install -e \".[listen-whisper]\""
        ) from e

    settings = RuntimeSettings(
        listen_engine="whisper",
        whisper_model=whisper_model,
        whisper_device=whisper_device,
        whisper_beam_size=max(1, min(20, int(whisper_beam_size))),
        listen_whisper_refine_punctuation=False,
    )
    model = _get_model(settings)
    return _transcribe_wav_path_with_model(model, audio_path, settings)


def _read_expected_text(args: argparse.Namespace) -> str | None:
    if args.expected_text:
        return str(args.expected_text)
    if args.expected_text_file:
        p = Path(args.expected_text_file)
        return p.read_text(encoding="utf-8").strip()
    return None


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=(
            "Audio inference self-test: optional fixture download + Whisper transcription + metric assertions."
        )
    )
    ap.add_argument(
        "--audio-path",
        type=Path,
        default=Path("audio_selftest_logs") / "fixture.wav",
        help="Local fixture file path (default: audio_selftest_logs/fixture.wav)",
    )
    ap.add_argument(
        "--audio-url",
        type=str,
        default=None,
        help="Optional URL to download fixture audio before inference.",
    )
    ap.add_argument(
        "--force-download",
        action="store_true",
        help="Download fixture even when --audio-path already exists.",
    )
    ap.add_argument(
        "--download-timeout-s",
        type=float,
        default=45.0,
        help="Fixture download timeout seconds (default: 45).",
    )
    ap.add_argument(
        "--expected-text",
        type=str,
        default=None,
        help="Expected transcript text for assertions.",
    )
    ap.add_argument(
        "--expected-text-file",
        type=Path,
        default=None,
        help="Path to expected transcript text file.",
    )
    ap.add_argument(
        "--max-wer",
        type=float,
        default=0.45,
        help="Maximum allowed token WER when expected text is provided (default: 0.45).",
    )
    ap.add_argument(
        "--min-token-recall",
        type=float,
        default=0.55,
        help="Minimum token recall (default: 0.55).",
    )
    ap.add_argument(
        "--min-token-precision",
        type=float,
        default=0.55,
        help="Minimum token precision (default: 0.55).",
    )
    ap.add_argument(
        "--whisper-model",
        type=str,
        default="base",
        help="Whisper model id for faster-whisper (default: base).",
    )
    ap.add_argument(
        "--whisper-device",
        type=str,
        default="auto",
        choices=("auto", "cpu", "cuda"),
        help="Requested Whisper device (default: auto).",
    )
    ap.add_argument(
        "--whisper-beam-size",
        type=int,
        default=3,
        help="faster-whisper beam size (default: 3).",
    )
    ap.add_argument(
        "--fixture-sha256",
        type=str,
        default=None,
        help="Optional expected SHA256 for fixture integrity check.",
    )
    ap.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional output path for JSON report.",
    )
    ap.add_argument(
        "--print-json",
        action="store_true",
        help="Print JSON report to stdout.",
    )
    ap.add_argument(
        "--use-default-fixture",
        action="store_true",
        help=(
            "Convenience mode: set --audio-url to a tiny public sample and "
            "--expected-text to 'zero' if not already provided."
        ),
    )
    return ap


def main() -> int:
    ap = build_parser()
    args = ap.parse_args()

    if args.use_default_fixture and not args.audio_url:
        args.audio_url = DEFAULT_AUDIO_URL
    if args.use_default_fixture and not args.expected_text and not args.expected_text_file:
        args.expected_text = DEFAULT_EXPECTED_TEXT

    audio_path = Path(args.audio_path)
    downloaded = False

    if args.audio_url and (args.force_download or not audio_path.is_file()):
        try:
            _download_fixture(args.audio_url, audio_path, timeout_s=float(args.download_timeout_s))
            downloaded = True
        except Exception as e:
            print(f"ERROR: fixture download failed: {e}", file=sys.stderr)
            return 2

    if not audio_path.is_file():
        print(
            f"ERROR: audio fixture not found: {audio_path}. Provide --audio-path or --audio-url.",
            file=sys.stderr,
        )
        return 2

    audio_sha = _sha256_file(audio_path)
    if args.fixture_sha256:
        want = str(args.fixture_sha256).strip().lower()
        if audio_sha.lower() != want:
            print(
                f"ERROR: fixture SHA256 mismatch for {audio_path} (expected {want}, got {audio_sha})",
                file=sys.stderr,
            )
            return 2

    try:
        transcript = transcribe_audio_fixture(
            audio_path,
            whisper_model=args.whisper_model,
            whisper_device=args.whisper_device,
            whisper_beam_size=args.whisper_beam_size,
        ).strip()
    except Exception as e:
        print(f"ERROR: inference failed: {e}", file=sys.stderr)
        return 3

    expected_text = _read_expected_text(args)
    metrics: dict[str, Any] | None = None
    checks: list[dict[str, Any]] = []
    passed = True

    if expected_text is not None:
        metrics = compute_text_metrics(expected_text, transcript)
        passed, checks = evaluate_metrics(
            metrics,
            max_wer=float(args.max_wer),
            min_token_recall=float(args.min_token_recall),
            min_token_precision=float(args.min_token_precision),
        )

    report: dict[str, Any] = {
        "audio_path": str(audio_path.resolve()),
        "audio_downloaded_this_run": downloaded,
        "audio_source_url": args.audio_url,
        "audio_sha256": audio_sha,
        "whisper_model": args.whisper_model,
        "whisper_device_requested": args.whisper_device,
        "whisper_beam_size": int(args.whisper_beam_size),
        "transcript": transcript,
        "expected_text": expected_text,
        "thresholds": (
            {
                "max_wer": float(args.max_wer),
                "min_token_recall": float(args.min_token_recall),
                "min_token_precision": float(args.min_token_precision),
            }
            if expected_text is not None
            else None
        ),
        "metrics": metrics,
        "checks": checks,
        "passed": bool(passed),
    }

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Wrote {args.json_out}")

    if args.print_json:
        print(json.dumps(report, indent=2))
    else:
        print(f"transcript: {transcript!r}")
        if expected_text is None:
            print("status: pass (no expected transcript provided)")
        else:
            print(f"status: {'pass' if passed else 'fail'}")
            if metrics is not None:
                print(
                    "metrics:",
                    f"wer={metrics['word_error_rate']:.4f},",
                    f"recall={metrics['token_recall']:.4f},",
                    f"precision={metrics['token_precision']:.4f}",
                )

    return 0 if passed else 4


if __name__ == "__main__":
    raise SystemExit(main())
