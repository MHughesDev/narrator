"""Best-effort text into the focused control: UIA Value / Text, then clipboard + paste."""

from __future__ import annotations

import logging
from typing import Optional

import pyperclip
import uiautomation as auto
from pynput.keyboard import Controller, Key

logger = logging.getLogger(__name__)


def _try_value_pattern(control: auto.Control, text: str) -> bool:
    try:
        vp = control.GetValuePattern()
        if not vp:
            return False
        if getattr(vp, "IsReadOnly", False):
            return False
        vp.SetValue(text)
        return True
    except Exception as e:
        logger.debug("ValuePattern.SetValue: %s", e)
    return False


def _try_text_pattern_set(control: auto.Control, text: str) -> bool:
    """``TextPattern2`` / document range set when exposed."""
    try:
        tp = control.GetTextPattern()
        if not tp:
            return False
        doc = getattr(tp, "DocumentRange", None)
        if doc is None:
            return False
        if hasattr(doc, "SetText"):
            doc.SetText(text)
            return True
    except Exception as e:
        logger.debug("TextPattern set: %s", e)
    return False


def try_uia_set_focused_text(text: str) -> bool:
    """Replace the focused control's text via UIA when possible."""
    if not text:
        return True
    try:
        c = auto.GetFocusedControl()
    except Exception as e:
        logger.debug("GetFocusedControl: %s", e)
        return False
    if not c:
        return False
    if _try_value_pattern(c, text):
        return True
    if _try_text_pattern_set(c, text):
        return True
    return False


def paste_via_clipboard(text: str, *, kb: Optional[Controller] = None) -> None:
    """Copy ``text`` to the clipboard and send Ctrl+V."""
    if not text:
        return
    k = kb or Controller()
    prev = None
    try:
        prev = pyperclip.paste()
    except Exception as e:
        logger.debug("clipboard read: %s", e)
    try:
        pyperclip.copy(text)
    except Exception as e:
        logger.error("Clipboard copy failed: %s", e)
        return
    try:
        with k.pressed(Key.ctrl):
            k.tap("v")
    finally:
        if prev is not None:
            try:
                pyperclip.copy(prev)
            except Exception as e:
                logger.debug("clipboard restore: %s", e)


def insert_text_best_effort(text: str, *, kb: Optional[Controller] = None) -> bool:
    """
    Try UIA set on the focused element; if that fails, paste via clipboard.

    Returns True if UIA path succeeded; False if fallback paste was used (or nothing was done).
    """
    if not text:
        return True
    if try_uia_set_focused_text(text):
        return True
    paste_via_clipboard(text, kb=kb)
    return False
