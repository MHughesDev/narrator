"""Windows DPI awareness so UIA hit-testing matches pointer (see ARCHITECTURE.md §7, SPEC.md §3)."""

from __future__ import annotations

import ctypes
import logging

logger = logging.getLogger(__name__)

# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4 as HANDLE
_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)


def try_set_per_monitor_v2() -> bool:
    """Call SetProcessDpiAwarenessContext when available (Windows 10 1703+)."""
    try:
        user32 = ctypes.windll.user32
        if not hasattr(user32, "SetProcessDpiAwarenessContext"):
            if hasattr(user32, "SetProcessDPIAware"):
                user32.SetProcessDPIAware()
                logger.debug("SetProcessDPIAware() applied")
            return True
        user32.SetProcessDpiAwarenessContext(_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
        logger.debug("SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2) applied")
        return True
    except Exception as e:
        logger.debug("DPI awareness not set: %s", e)
        return False
