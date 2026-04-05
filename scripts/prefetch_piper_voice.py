"""Download a Piper ONNX voice into the default narrator Piper directory (first speak with Piper is faster)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


def main() -> int:
    from prefetch_utils import env_force_prefetch, piper_voice_files_ready
    from setup_terminal import setup_verbose

    from narrator.tts_piper import DEFAULT_PIPER_VOICE_ID

    vq = setup_verbose()

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
    parser.add_argument(
        "--prefetch-always",
        action="store_true",
        help="Download even if voice files already exist (also: env NARRATOR_FORCE_PREFETCH=1).",
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

    force = args.prefetch_always or env_force_prefetch()
    if not force and piper_voice_files_ready(voice_arg, target):
        if vq:
            print(
                f"SKIP: Piper voice {voice_arg!r} already present under {target}",
                flush=True,
            )
        return 0

    if vq:
        print(f"Downloading Piper voice {voice_arg!r} to {target} ...", flush=True)
    else:
        print("Prefetch Piper…", flush=True)
    download_voice(voice_arg, target, force_redownload=False)
    if vq:
        print("OK: Piper model ready. Use --speak-engine piper or auto (with this voice installed).", flush=True)
    else:
        print("Piper ready.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
