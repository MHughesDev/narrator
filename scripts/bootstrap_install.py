"""
One entry point for narrator setup: choose profile from hardware (Windows) and run pip steps.

Usage:
  python scripts/bootstrap_install.py --auto
  python scripts/bootstrap_install.py --profile minimal
  python scripts/bootstrap_install.py --profile neural-cpu
  python scripts/bootstrap_install.py --profile neural-gpu
  python scripts/bootstrap_install.py --dry-run --auto
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

# Repo root = parent of scripts/
ROOT = Path(__file__).resolve().parent.parent


def _pip(args: list[str], *, dry_run: bool) -> int:
    cmd = [sys.executable, "-m", "pip"] + args
    print("+", " ".join(cmd))
    if dry_run:
        return 0
    # noqa: S603 - intentional controlled pip invocation
    return subprocess.call(cmd, cwd=str(ROOT))


def _run_script(rel: str, *, dry_run: bool, extra_args: list[str] | None = None) -> int:
    path = ROOT / rel
    cmd = [sys.executable, str(path)] + (extra_args or [])
    print("+", " ".join(cmd))
    if dry_run:
        return 0
    return subprocess.call(cmd, cwd=str(ROOT))


def resolve_auto_profile(rep) -> str:
    """Pick install profile from :func:`hw_detect.hardware_report`."""
    if not rep.is_windows:
        return "minimal"
    if rep.nvidia_present:
        return "neural-gpu"
    return "neural-cpu"


def install_minimal(dry_run: bool) -> int:
    return _pip(["install", "-e", "."], dry_run=dry_run)


def install_neural_cpu(dry_run: bool) -> int:
    return _pip(["install", "-e", ".[speak-xtts,speak-piper]"], dry_run=dry_run)


def install_torch_cuda(dry_run: bool) -> int:
    from hw_detect import torch_cuda_index_url

    index = torch_cuda_index_url()
    # Reinstall PyTorch stack from NVIDIA CUDA wheels (after CPU coqui pull).
    return _pip(
        [
            "install",
            "--upgrade",
            "torch",
            "torchaudio",
            "--index-url",
            index,
        ],
        dry_run=dry_run,
    )


def install_neural_gpu(dry_run: bool) -> int:
    r = install_neural_cpu(dry_run)
    if r != 0:
        return r
    print()
    print("Upgrading PyTorch to CUDA build (NVIDIA GPU detected)...")
    print("(Override wheel index: set NARRATOR_TORCH_CUDA_INDEX)")
    r = install_torch_cuda(dry_run)
    if r != 0:
        print(
            "[WARN] CUDA PyTorch install failed — you can stay on CPU PyTorch or install manually:",
            "https://pytorch.org/get-started/locally/",
            file=sys.stderr,
        )
    return 0


def post_install(dry_run: bool) -> int:
    r = _run_script("scripts/verify_setup.py", dry_run=dry_run)
    if r != 0 and not dry_run:
        print("[WARN] verify_setup reported issues.", file=sys.stderr)

    prefetch_extra: list[str] = []
    if os.environ.get("NARRATOR_COQUI_PREFETCH_YES", "").strip().lower() in ("1", "true", "yes", "on"):
        prefetch_extra.append("--yes")
    r2 = _run_script("scripts/prefetch_xtts_model.py", dry_run=dry_run, extra_args=prefetch_extra or None)
    if r2 != 0 and not dry_run:
        print("[WARN] XTTS prefetch failed — model may download on first use.", file=sys.stderr)

    r3 = _run_script("scripts/prefetch_piper_voice.py", dry_run=dry_run)
    if r3 != 0 and not dry_run:
        print("[WARN] Piper voice prefetch failed.", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Narrator bootstrap install (Windows-first).")
    ap.add_argument(
        "--profile",
        choices=("auto", "minimal", "neural-cpu", "neural-gpu"),
        default="auto",
        help="Install tier (default: auto — uses hardware detection on Windows).",
    )
    ap.add_argument(
        "--auto",
        action="store_true",
        help="Same as --profile auto (explicit for scripts).",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print pip commands without running them.",
    )
    ap.add_argument(
        "--skip-prefetch",
        action="store_true",
        help="Skip verify_setup and model prefetch (faster CI / debugging).",
    )
    ap.add_argument(
        "--force-cuda",
        action="store_true",
        help="With --profile neural-gpu: install CUDA PyTorch even if nvidia-smi was not found.",
    )
    args = ap.parse_args(argv)

    profile = args.profile
    if args.auto:
        profile = "auto"

    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT / "scripts"))
    from hw_detect import hardware_report, print_report

    rep = hardware_report()
    if not rep.is_windows and not args.dry_run:
        print(
            "Narrator is built for Windows (WinRT / UI Automation). "
            "Run setup.bat or this script on Windows 10/11.",
            file=sys.stderr,
        )
        return 1
    print_report(rep)

    if profile == "auto":
        profile = resolve_auto_profile(rep)
        print(f"Resolved profile: {profile!r} (from hardware / platform)")
        print()

    dry = args.dry_run

    if profile == "minimal":
        code = install_minimal(dry)
    elif profile == "neural-cpu":
        code = install_neural_cpu(dry)
    elif profile == "neural-gpu":
        if not rep.nvidia_present and not args.force_cuda and not dry:
            print(
                "[WARN] neural-gpu requested but nvidia-smi did not report a GPU — "
                "installing neural-cpu instead (CPU PyTorch). Use --force-cuda to try CUDA wheels anyway.",
                file=sys.stderr,
            )
            code = install_neural_cpu(dry)
        else:
            code = install_neural_gpu(dry)
    else:
        print("Unknown profile", file=sys.stderr)
        return 2

    if code != 0:
        return code

    if not args.skip_prefetch:
        post_install(dry)

    print()
    print("Done. Run: python -m narrator   or   run_narrator.bat")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
