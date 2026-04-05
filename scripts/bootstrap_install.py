"""
One entry point for narrator setup: choose profile from hardware (Windows) and run pip steps.

This module only runs ``pip install`` / ``pip install --upgrade`` into the active environment
(typically the project ``.venv``). It never uninstalls packages or deletes user caches.

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


def _pip(args: list[str], *, dry_run: bool, quiet: bool) -> int:
    pargs = list(args)
    if quiet and not dry_run and len(pargs) > 0 and pargs[0] == "install" and "-q" not in pargs:
        pargs = [pargs[0], "-q"] + pargs[1:]
    cmd = [sys.executable, "-m", "pip"] + pargs
    if not quiet or dry_run:
        print("+", " ".join(cmd))
    if dry_run:
        return 0
    # noqa: S603 - intentional controlled pip invocation
    return subprocess.call(cmd, cwd=str(ROOT))


def _run_script(rel: str, *, dry_run: bool, quiet: bool, extra_args: list[str] | None = None) -> int:
    path = ROOT / rel
    cmd = [sys.executable, str(path)] + (extra_args or [])
    if not quiet or dry_run:
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


def install_minimal(dry_run: bool, *, quiet: bool) -> int:
    return _pip(["install", "-e", "."], dry_run=dry_run, quiet=quiet)


def install_neural_cpu(dry_run: bool, *, quiet: bool) -> int:
    return _pip(["install", "-e", ".[speak-xtts,speak-piper]"], dry_run=dry_run, quiet=quiet)


def install_torch_cuda(dry_run: bool, *, quiet: bool) -> int:
    from hw_detect import torch_cuda_index_url
    from pytorch_cuda_wheels import ensure_cuda_pytorch_for_venv

    index = torch_cuda_index_url()
    return ensure_cuda_pytorch_for_venv(
        sys.executable,
        index,
        cwd=ROOT,
        dry_run=dry_run,
        quiet=quiet,
    )


def install_neural_gpu(dry_run: bool, *, quiet: bool) -> int:
    r = install_neural_cpu(dry_run, quiet=quiet)
    if r != 0:
        return r
    if not quiet:
        print()
        print("Upgrading PyTorch to CUDA build (NVIDIA GPU detected)...")
        print("(Override wheel index: set NARRATOR_TORCH_CUDA_INDEX)")
    elif not dry_run:
        print("CUDA PyTorch…", flush=True)
    r = install_torch_cuda(dry_run, quiet=quiet)
    if r != 0:
        print(
            "[WARN] CUDA PyTorch install failed — you can stay on CPU PyTorch or install manually:",
            "https://pytorch.org/get-started/locally/",
            file=sys.stderr,
        )
    return 0


def post_install(dry_run: bool, *, profile: str, prefetch_always: bool, quiet: bool) -> int:
    r = _run_script("scripts/verify_setup.py", dry_run=dry_run, quiet=quiet)
    if r != 0 and not dry_run:
        print("[WARN] verify_setup reported issues.", file=sys.stderr)

    if profile == "minimal":
        if not quiet:
            print("Skipping neural model prefetch (minimal profile - no Coqui/Piper extras).")
        return 0

    prefetch_extra: list[str] = []
    if os.environ.get("NARRATOR_COQUI_PREFETCH_YES", "").strip().lower() in ("1", "true", "yes", "on"):
        prefetch_extra.append("--yes")
    if prefetch_always:
        prefetch_extra.append("--prefetch-always")
    r2 = _run_script(
        "scripts/prefetch_xtts_model.py",
        dry_run=dry_run,
        quiet=quiet,
        extra_args=prefetch_extra or None,
    )
    if r2 != 0 and not dry_run:
        print("[WARN] XTTS prefetch failed — model may download on first use.", file=sys.stderr)

    piper_extra = ["--prefetch-always"] if prefetch_always else None
    r3 = _run_script(
        "scripts/prefetch_piper_voice.py", dry_run=dry_run, quiet=quiet, extra_args=piper_extra
    )
    if r3 != 0 and not dry_run:
        print("[WARN] Piper voice prefetch failed.", file=sys.stderr)

    r4 = _run_script("scripts/setup_ollama_speak_llm.py", dry_run=dry_run, quiet=quiet)
    if r4 != 0 and not dry_run:
        print(
            "[WARN] Ollama / speak LLM setup had issues — Piper & XTTS need a running Ollama with the text model. "
            "See docs/SETUP.md (skip: NARRATOR_SKIP_OLLAMA_SETUP=1).",
            file=sys.stderr,
        )
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
    ap.add_argument(
        "--prefetch-always",
        action="store_true",
        help="Run XTTS/Piper prefetch even if cache looks ready (also env NARRATOR_FORCE_PREFETCH=1).",
    )
    args = ap.parse_args(argv)

    profile = args.profile
    if args.auto:
        profile = "auto"

    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT / "scripts"))
    from hw_detect import hardware_report, print_report
    from prefetch_utils import env_force_prefetch
    from setup_terminal import setup_verbose

    quiet = not setup_verbose()
    rep = hardware_report()
    if not rep.is_windows and not args.dry_run:
        print(
            "Narrator is built for Windows (WinRT / UI Automation). "
            "Run setup.bat or this script on Windows 10/11.",
            file=sys.stderr,
        )
        return 1
    print_report(rep, verbose=not quiet)

    if profile == "auto":
        profile = resolve_auto_profile(rep)
        if quiet:
            print(f"Profile: {profile}")
        else:
            print(f"Resolved profile: {profile!r} (from hardware / platform)")
            print()

    dry = args.dry_run

    if profile == "minimal":
        code = install_minimal(dry, quiet=quiet)
    elif profile == "neural-cpu":
        code = install_neural_cpu(dry, quiet=quiet)
    elif profile == "neural-gpu":
        if not rep.nvidia_present and not args.force_cuda and not dry:
            print(
                "[WARN] neural-gpu requested but nvidia-smi did not report a GPU — "
                "installing neural-cpu instead (CPU PyTorch). Use --force-cuda to try CUDA wheels anyway.",
                file=sys.stderr,
            )
            code = install_neural_cpu(dry, quiet=quiet)
        else:
            code = install_neural_gpu(dry, quiet=quiet)
    else:
        print("Unknown profile", file=sys.stderr)
        return 2

    if code != 0:
        return code

    if not args.skip_prefetch:
        prefetch_always = bool(args.prefetch_always) or env_force_prefetch()
        post_install(dry, profile=profile, prefetch_always=prefetch_always, quiet=quiet)

    if quiet:
        print("Done. run.bat")
    else:
        print()
        print("Done. Run: run.bat   or   python -m narrator")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
