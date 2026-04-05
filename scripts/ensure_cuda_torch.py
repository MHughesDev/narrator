"""
Ensure PyTorch CUDA wheels are installed when an NVIDIA GPU is present (Windows).

Used by setup.bat and run.bat / run_narrator.bat so XTTS uses the GPU instead of staying on +cpu wheels.
Install logic lives in :mod:`pytorch_cuda_wheels` (gentle upgrade first; force-reinstall only if needed).

Set NARRATOR_SKIP_CUDA_ENSURE=1 to skip (debugging). Override wheel index with NARRATOR_TORCH_CUDA_INDEX.
NARRATOR_CUDA_FORCE_REINSTALL=1 skips the gentle step (go straight to force-reinstall).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    if (os.environ.get("NARRATOR_SKIP_CUDA_ENSURE") or "").strip().lower() in ("1", "true", "yes", "on"):
        return 0

    if sys.platform != "win32":
        return 0

    sys.path.insert(0, str(ROOT / "scripts"))
    from setup_terminal import setup_verbose

    quiet = not setup_verbose()

    try:
        import platform

        if platform.machine().lower() in ("arm64", "aarch64"):
            if not quiet:
                print("ensure_cuda_torch: skipping ARM64 (CUDA PyTorch wheels are typically x64).")
            return 0
    except Exception:
        pass

    from hw_detect import detect_nvidia_via_smi, torch_cuda_index_url

    nvidia_ok, _gpu_name, _drv, _smi = detect_nvidia_via_smi()
    if not nvidia_ok:
        return 0

    try:
        import torch
    except ImportError:
        return 0

    if torch.cuda.is_available():
        try:
            name = torch.cuda.get_device_name(0)
        except Exception:
            name = "CUDA"
        if not quiet:
            print(f"PyTorch CUDA OK ({name}).")
        return 0

    if not quiet:
        print("NVIDIA GPU detected but PyTorch has no CUDA — installing CUDA wheels into this venv only...")
    else:
        print("CUDA PyTorch (pip)…", flush=True)
    from pytorch_cuda_wheels import ensure_cuda_pytorch_for_venv, torch_cuda_available

    index = torch_cuda_index_url()
    r = ensure_cuda_pytorch_for_venv(
        sys.executable,
        index,
        cwd=ROOT,
        dry_run=False,
        quiet=quiet,
    )
    if r != 0:
        print(
            "[WARN] pip could not install CUDA PyTorch — XTTS will use CPU. "
            "See https://pytorch.org/get-started/locally/ and docs/SETUP.md",
            file=sys.stderr,
        )
        return 0

    if not torch_cuda_available(sys.executable):
        print(
            "[WARN] CUDA PyTorch installed but torch.cuda.is_available() is still False "
            "(driver/toolkit mismatch?). See docs/SETUP.md.",
            file=sys.stderr,
        )
    elif not quiet:
        print("PyTorch CUDA is now available for XTTS.")
    else:
        print("CUDA OK.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
