"""
Install CUDA PyTorch + torchaudio into **one** Python environment (the project venv).

- Never touches system Python or other venvs: always pass that env's ``python.exe`` as ``executable``.
- Default: ``pip install --upgrade`` from the CUDA wheel index (minimal churn).
- If CUDA still does not load, ``--force-reinstall`` only then (replaces stubborn ``+cpu`` wheels).

Env:
  NARRATOR_CUDA_FORCE_REINSTALL=1 — skip the gentle step; run force-reinstall immediately.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def torch_cuda_available(executable: str) -> bool:
    """True if ``import torch`` works and ``torch.cuda.is_available()`` (fresh subprocess)."""
    r = subprocess.run(
        [executable, "-c", "import torch; raise SystemExit(0 if torch.cuda.is_available() else 1)"],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True,
        text=True,
        timeout=120,
    )
    return r.returncode == 0


def _pip(
    executable: str,
    args: list[str],
    *,
    cwd: Path,
    dry_run: bool,
    quiet: bool,
) -> int:
    pargs = list(args)
    if quiet and not dry_run and pargs and pargs[0] == "install" and "-q" not in pargs:
        pargs = ["install", "-q"] + pargs[1:]
    cmd = [executable, "-m", "pip"] + pargs
    if not quiet or dry_run:
        print("+", " ".join(cmd))
    if dry_run:
        return 0
    return subprocess.call(cmd, cwd=str(cwd))


def ensure_cuda_pytorch_for_venv(
    executable: str,
    index_url: str,
    *,
    cwd: Path,
    dry_run: bool,
    quiet: bool = False,
) -> int:
    """
    Ensure the interpreter at ``executable`` can use CUDA PyTorch.

    Returns 0 if pip commands ran (or dry-run); non-zero only if a pip invocation failed hard.
    """
    force_only = (os.environ.get("NARRATOR_CUDA_FORCE_REINSTALL") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    base = [
        "install",
        "--upgrade",
        "torch",
        "torchaudio",
        "--index-url",
        index_url,
    ]
    force = [
        "install",
        "--upgrade",
        "--force-reinstall",
        "torch",
        "torchaudio",
        "--index-url",
        index_url,
    ]

    if dry_run:
        print("Trying CUDA PyTorch: pip upgrade from CUDA index (gentle; preserves deps when possible)...")
        _pip(executable, base, cwd=cwd, dry_run=True, quiet=quiet)
        print(
            "If CUDA still missing: pip --force-reinstall torch torchaudio (only this venv's site-packages).",
        )
        _pip(executable, force, cwd=cwd, dry_run=True, quiet=quiet)
        return 0

    if not force_only:
        if not quiet:
            print(
                "Trying CUDA PyTorch: pip upgrade from CUDA index (gentle; preserves deps when possible)..."
            )
        r = _pip(executable, base, cwd=cwd, dry_run=False, quiet=quiet)
        if r != 0:
            return r
        if torch_cuda_available(executable):
            if not quiet:
                print("PyTorch CUDA is available after upgrade.")
            return 0

    if not quiet:
        print(
            "Installing CUDA PyTorch with --force-reinstall (needed when pip kept CPU wheels; "
            "only affects this venv's site-packages).",
        )
    return _pip(executable, force, cwd=cwd, dry_run=False, quiet=quiet)
