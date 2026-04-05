"""
Install Ollama (Windows) and pull the default text model used with Piper / XTTS.

Neural speak engines require local LLM text-readying; setup.bat / bootstrap call this
after pip installs (neural profiles only). Skip with NARRATOR_SKIP_OLLAMA_SETUP=1.

Usage:
  python scripts/setup_ollama_speak_llm.py
  python scripts/setup_ollama_speak_llm.py --dry-run
  python scripts/setup_ollama_speak_llm.py --model llama3.2:1b
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(_SCRIPTS))
from setup_terminal import setup_verbose

try:
    from narrator.speak_text_llm import DEFAULT_SPEAK_TEXT_LLM_MODEL as DEFAULT_MODEL
except Exception:  # pragma: no cover - venv not on path during dry tooling
    DEFAULT_MODEL = "llama3.2:1b"


def resolve_ollama_exe() -> str | None:
    w = shutil.which("ollama")
    if w:
        return w
    la = os.environ.get("LOCALAPPDATA", "")
    if la:
        cand = Path(la) / "Programs" / "Ollama" / "ollama.exe"
        if cand.is_file():
            return str(cand)
    pf = os.environ.get("ProgramFiles", "")
    if pf:
        cand = Path(pf) / "Ollama" / "ollama.exe"
        if cand.is_file():
            return str(cand)
    return None


def install_ollama_winget(*, dry_run: bool) -> int:
    cmd = [
        "winget",
        "install",
        "-e",
        "--id",
        "Ollama.Ollama",
        "--accept-package-agreements",
        "--accept-source-agreements",
    ]
    print("+", " ".join(cmd))
    if dry_run:
        return 0
    return subprocess.call(cmd, cwd=str(ROOT))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Ollama install + pull for Narrator speak LLM.")
    ap.add_argument("--dry-run", action="store_true", help="Print actions only.")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"Model tag for ollama pull (default: {DEFAULT_MODEL}).")
    args = ap.parse_args(argv)
    verbose = setup_verbose()

    skip = os.environ.get("NARRATOR_SKIP_OLLAMA_SETUP", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if skip:
        if verbose:
            print("Skipping Ollama setup (NARRATOR_SKIP_OLLAMA_SETUP).")
        return 0

    if os.name != "nt":
        if verbose:
            print(
                "Skipping Ollama setup (non-Windows). Install Ollama manually if you use Piper/XTTS elsewhere."
            )
        return 0

    exe = resolve_ollama_exe()
    if not exe:
        if verbose:
            print("Ollama not found on PATH; trying winget install Ollama.Ollama ...")
        elif not args.dry_run:
            print("Ollama: installing…", flush=True)
        wh = shutil.which("winget")
        if not wh:
            print(
                "[WARN] winget not found. Install Ollama from https://ollama.com/download",
                "then run:  ollama pull",
                args.model,
                file=sys.stderr,
            )
            return 0
        code = install_ollama_winget(dry_run=args.dry_run)
        if code != 0 and not args.dry_run:
            print(
                "[WARN] winget install failed (try running setup as Administrator or install Ollama manually).",
                file=sys.stderr,
            )
            return 0
        exe = resolve_ollama_exe()
        if not exe:
            print(
                "[WARN] Ollama still not found after install — open a NEW terminal so PATH updates,",
                f"then run:  ollama pull {args.model}",
                file=sys.stderr,
            )
            return 0

    pull_cmd = [exe, "pull", args.model.strip() or DEFAULT_MODEL]
    if verbose or args.dry_run:
        print("+", " ".join(pull_cmd))
    elif not args.dry_run:
        print(f"Ollama pull {args.model!r}…", flush=True)
    if args.dry_run:
        return 0
    code = subprocess.call(pull_cmd, cwd=str(ROOT))
    if code != 0:
        print(
            f"[WARN] ollama pull {args.model!r} failed — ensure the Ollama app is running, then:",
            f"  ollama pull {args.model}",
            file=sys.stderr,
        )
        return 0

    if verbose:
        print(f"Ollama ready with model {args.model!r} (speak_text_llm default for Piper/XTTS).")
    else:
        print("Ollama OK.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
