"""Hide the console window (Windows) when running with python.exe."""

from __future__ import annotations

import ctypes
import logging

logger = logging.getLogger(__name__)


def hide_console_window() -> None:
    """Call ``ShowWindow(GetConsoleWindow(), SW_HIDE)`` when a console exists."""
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
            logger.debug("Console window hidden")
    except Exception as e:
        logger.debug("hide_console_window: %s", e)
