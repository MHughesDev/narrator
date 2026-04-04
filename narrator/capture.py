"""Pointer-based UI Automation text capture (see SPEC.md)."""

from __future__ import annotations

import logging
from typing import Optional

import uiautomation as auto

logger = logging.getLogger(__name__)

_MAX_ANCESTORS = 30
_MAX_CHILD_DEPTH = 5

# Skip these when gathering text — their DocumentRange/Value often spans menu bars, tabs, etc.
_CHROME_TYPES = frozenset(
    {
        auto.ControlType.MenuBarControl,
        auto.ControlType.MenuControl,
        auto.ControlType.ToolBarControl,
        auto.ControlType.TitleBarControl,
        auto.ControlType.StatusBarControl,
        auto.ControlType.TabControl,
    }
)

# Editor surfaces in many apps (Notepad, Word, browser content in some cases)
_CONTENT_TYPES = frozenset(
    {
        auto.ControlType.DocumentControl,
        auto.ControlType.EditControl,
    }
)


def _control_type(ctrl: auto.Control) -> int:
    return int(ctrl.ControlType)


def _is_chrome_control(ctrl: auto.Control) -> bool:
    try:
        return _control_type(ctrl) in _CHROME_TYPES
    except Exception:
        return False


def _bad_custom_class_name(ctrl: auto.Control) -> bool:
    """Electron / IDE toolbars often use CustomControl; avoid treating them as document body."""
    try:
        c = (ctrl.ClassName or "").lower()
    except Exception:
        return False
    if not c:
        return False
    for bad in (
        "toolbar",
        "menubar",
        "titlebar",
        "statusbar",
        "tab-bar",
        "tabbar",
        "actionbar",
        "navigation",
    ):
        if bad in c:
            return True
    return False


def _text_or_value(ctrl: auto.Control) -> Optional[str]:
    t = _safe_text_from_pattern(ctrl)
    if t and t.strip():
        return t.strip()
    v = _safe_value(ctrl)
    if v and str(v).strip():
        return str(v).strip()
    return None


def _safe_text_from_pattern(control: auto.Control) -> Optional[str]:
    try:
        tp = control.GetTextPattern()
        if not tp:
            return None
        doc = tp.DocumentRange
        if not doc:
            return None
        text = doc.GetText(-1)
        if text and text.strip():
            return text
    except Exception as e:
        logger.debug("TextPattern failed: %s", e)
    return None


def _safe_value(control: auto.Control) -> Optional[str]:
    try:
        vp = control.GetValuePattern()
        if not vp:
            return None
        v = vp.Value
        if v and str(v).strip():
            return str(v)
    except Exception as e:
        logger.debug("ValuePattern failed: %s", e)
    return None


def _ancestors_from(control: Optional[auto.Control]) -> list[auto.Control]:
    out: list[auto.Control] = []
    c = control
    for _ in range(_MAX_ANCESTORS):
        if not c:
            break
        out.append(c)
        try:
            c = c.GetParentControl()
        except Exception:
            break
    return out


def _walk_children_preorder(control: auto.Control, depth: int, max_depth: int) -> list[str]:
    if depth > max_depth:
        return []
    chunks: list[str] = []
    try:
        child = control.GetFirstChildControl()
        while child:
            t = _safe_text_from_pattern(child)
            if t and t.strip():
                chunks.append(t.strip())
            v = _safe_value(child)
            if v and v.strip():
                chunks.append(v.strip())
            chunks.extend(_walk_children_preorder(child, depth + 1, max_depth))
            child = child.GetNextSiblingControl()
    except Exception as e:
        logger.debug("child walk: %s", e)
    return chunks


def capture_at_cursor() -> Optional[str]:
    """
    Resolve text under the current mouse pointer using UIA.
    Uses physical cursor coordinates for ElementFromPoint (DPI).

    Multi-pane apps (e.g. VS Code / Cursor) often expose a **parent** whose TextPattern
    concatenates menu bars + editor — longer than the real buffer. We therefore **prefer**
    the deepest ``Document`` / ``Edit`` under the hit, and exclude menu/toolbar/title
    controls from the legacy "longest string" fallback.
    """
    try:
        x, y = auto.GetPhysicalCursorPos()
        hit = auto.ControlFromPoint(x, y)
    except Exception as e:
        logger.warning("ControlFromPoint failed: %s", e)
        return None

    if not hit:
        logger.warning("No UIA element under cursor")
        return None

    ancestors = _ancestors_from(hit)

    # 1) Deepest Document or Edit with text (typical for editors, Notepad, many web views)
    for ctrl in ancestors:
        if _is_chrome_control(ctrl):
            continue
        try:
            ct = _control_type(ctrl)
        except Exception:
            continue
        if ct in _CONTENT_TYPES:
            got = _text_or_value(ctrl)
            if got:
                logger.debug("capture: using %s", ctrl.ControlTypeName)
                return got

    # 2) Electron / Monaco: editor is sometimes CustomControl with a document-like range
    for ctrl in ancestors:
        if _is_chrome_control(ctrl):
            continue
        try:
            if _control_type(ctrl) != auto.ControlType.CustomControl:
                continue
        except Exception:
            continue
        if _bad_custom_class_name(ctrl):
            continue
        got = _text_or_value(ctrl)
        if got:
            logger.debug("capture: using CustomControl %s", getattr(ctrl, "ClassName", ""))
            return got

    # 3) Fallback: longest text among non-chrome ancestors (legacy SPEC behavior, narrowed)
    candidates: list[str] = []
    for ctrl in ancestors:
        if _is_chrome_control(ctrl):
            continue
        t = _safe_text_from_pattern(ctrl)
        if t:
            candidates.append(t)
        v = _safe_value(ctrl)
        if v:
            candidates.append(v)

    # 4) Pre-order child snippets only when the hit is likely a container for the buffer,
    # not the root window (avoids merging menu + editor siblings)
    if not candidates:
        try:
            ht_ct = _control_type(hit)
        except Exception:
            ht_ct = -1
        if ht_ct in _CONTENT_TYPES or ht_ct == auto.ControlType.CustomControl:
            child_bits = _walk_children_preorder(hit, 0, _MAX_CHILD_DEPTH)
            if child_bits:
                merged = "\n".join(child_bits)
                if merged.strip():
                    candidates.append(merged)

    if candidates:
        best = max(candidates, key=lambda s: len(s.strip()))
        return best.strip()

    try:
        name = (hit.Name or "").strip()
        if name:
            return name
    except Exception:
        pass
    try:
        ht = (hit.HelpText or "").strip()
        if ht:
            return ht
    except Exception:
        pass

    logger.warning("No readable text from UIA under pointer")
    return None
