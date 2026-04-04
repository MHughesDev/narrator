"""Download a Piper ONNX voice into the default narrator Piper directory (first speak with Piper is faster)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    from narrator.tts_piper import DEFAULT_PIPER_VOICE_ID

    parser = argparse.ArgumentParser(
        description=f"Download a Piper voice (default: {DEFAULT_PIPER_VOICE_ID}) from rhasspy/piper-voices.",
    )
    parser.add_argument(
        "voice",
        nargs="?",
        default=None,
        help=f"Voice id (default: {DEFAULT_PIPER_VOICE_ID}). See: python -m narrator --list-piper-voices",
    )
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=None,
        help="Override target directory (default: %%LOCALAPPDATA%%\\narrator\\piper on Windows).",
    )
    args = parser.parse_args()
    voice_arg = (args.voice or "").strip() or DEFAULT_PIPER_VOICE_ID

    try:
        from piper.download_voices import download_voice
    except ImportError as e:
        print("ERROR: pip install narrator[speak-piper]", e, file=sys.stderr)
        return 1

    if args.download_dir is not None:
        target = args.download_dir
    else:
        from narrator.tts_piper import default_piper_data_dir

        target = default_piper_data_dir()
    target.mkdir(parents=True, exist_ok=True)
    print(f"Downloading Piper voice {voice_arg!r} to {target} ...", flush=True)
    download_voice(voice_arg, target, force_redownload=False)
    print("OK: Piper model ready. Use --speak-engine piper or auto (with this voice installed).", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
