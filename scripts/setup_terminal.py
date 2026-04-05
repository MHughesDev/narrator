"""Quiet-by-default console output for setup.bat / bootstrap (verbose with NARRATOR_SETUP_VERBOSE=1)."""

from __future__ import annotations

import os


def setup_verbose() -> bool:
    """Detailed hardware report, pip command echoes, CUDA/Ollama chatter (setup.bat and run helpers)."""
    return (os.environ.get("NARRATOR_SETUP_VERBOSE") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
