"""Quick import + WinRT synthesis smoke test (no hotkey, no UIA)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def main() -> int:
    from narrator import speech
    from narrator.settings import RuntimeSettings

    fd, name = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    tmp = Path(name)
    try:
        settings = RuntimeSettings()
        import queue
        q: queue.Queue = queue.Queue()
        ok, _ = speech.synthesize_with_queue_cancel("Hello.", tmp, settings, q)
        if not ok or not tmp.is_file() or tmp.stat().st_size < 100:
            print("FAIL: synthesis did not produce WAV", file=sys.stderr)
            return 1
        print("OK: synthesis wrote", tmp.stat().st_size, "bytes")
        return 0
    finally:
        tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
