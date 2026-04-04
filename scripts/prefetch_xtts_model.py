"""Load the configured XTTS model once so checkpoints are downloaded (first run can take many minutes)."""

from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Prefetch Coqui XTTS weights into the local cache.")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Non-interactive: set COQUI_TOS_AGREED=1 (you must agree to CPML / license terms yourself).",
    )
    parser.add_argument(
        "--xtts-device",
        choices=["auto", "cpu", "cuda"],
        default="auto",
        help="Torch device for the load (default: auto).",
    )
    args = parser.parse_args()
    if args.yes:
        os.environ.setdefault("COQUI_TOS_AGREED", "1")

    try:
        from narrator.settings import build_runtime_settings
        from narrator.tts_xtts import get_tts, is_xtts_available
    except ImportError as e:
        print("ERROR: narrator is not installed in this environment.", e, file=sys.stderr)
        return 1

    if not is_xtts_available():
        print(
            "ERROR: coqui-tts is not installed. Run: pip install -e \".[speak-xtts]\"",
            file=sys.stderr,
        )
        return 2

    settings = build_runtime_settings(
        config_explicit=None,
        voice=None,
        rate=None,
        volume=None,
        speak_hotkey=None,
        listen_hotkey=None,
        legacy_hotkey=None,
        silent=False,
        verbose=True,
        speak_engine="xtts",
        xtts_model=None,
        xtts_speaker=None,
        xtts_language=None,
        xtts_device=args.xtts_device,
        xtts_speaker_wav=None,
        listen_engine=None,
        whisper_model=None,
        whisper_device=None,
        listen_whisper_refine_punctuation=None,
    )
    if settings.speak_engine != "xtts":
        print("ERROR: speak_engine did not resolve to xtts.", file=sys.stderr)
        return 3

    print("Loading XTTS model (downloads checkpoints on first run; GPU optional)...", flush=True)
    get_tts(settings)
    print("OK: XTTS model is cached. First speak with the app should skip this download.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
