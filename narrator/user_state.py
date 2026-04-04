"""Persist user-adjusted preferences (e.g. speaking rate from Ctrl+Alt+/-) across process restarts."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_MIN_RATE = 0.5
_MAX_RATE = 3.0


def user_state_dir() -> Path:
    override = (os.environ.get("NARRATOR_STATE_DIR") or "").strip()
    if override:
        return Path(override)
    la = os.environ.get("LOCALAPPDATA", "")
    if la:
        return Path(la) / "narrator"
    return Path.home() / ".config" / "narrator"


def speaking_rate_state_path() -> Path:
    return user_state_dir() / "speaking_rate.json"


def clamp_speaking_rate(r: float) -> float:
    """Same bounds as live-rate hotkeys (0.5×–3.0×)."""
    return max(_MIN_RATE, min(_MAX_RATE, float(r)))


def load_persisted_speaking_rate() -> Optional[float]:
    """Return last saved speaking rate from hotkeys, or ``None`` if missing/invalid."""
    path = speaking_rate_state_path()
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, dict):
            v = data.get("speaking_rate")
        else:
            v = data
        if v is None:
            return None
        return clamp_speaking_rate(float(v))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as e:
        logger.debug("Could not load persisted speaking rate: %s", e)
        return None


def save_persisted_speaking_rate(rate: float) -> None:
    """Write speaking rate (from Ctrl+Alt+/-) so the next app launch uses it."""
    r = clamp_speaking_rate(rate)
    path = speaking_rate_state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"speaking_rate": r}, indent=0) + "\n"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)
    except OSError as e:
        logger.debug("Could not persist speaking rate: %s", e)
