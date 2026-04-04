"""Persisted speaking rate (Ctrl+Alt+/-)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


@pytest.fixture
def isolated_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("NARRATOR_STATE_DIR", str(tmp_path))
    return tmp_path


def test_load_missing_returns_none(isolated_state_dir: Path) -> None:
    from narrator.user_state import load_persisted_speaking_rate, speaking_rate_state_path

    assert not speaking_rate_state_path().is_file()
    assert load_persisted_speaking_rate() is None


def test_save_roundtrip(isolated_state_dir: Path) -> None:
    from narrator.user_state import (
        load_persisted_speaking_rate,
        save_persisted_speaking_rate,
        speaking_rate_state_path,
    )

    save_persisted_speaking_rate(1.3)
    path = speaking_rate_state_path()
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["speaking_rate"] == pytest.approx(1.3)
    assert load_persisted_speaking_rate() == pytest.approx(1.3)


def test_build_runtime_settings_uses_persisted(isolated_state_dir: Path) -> None:
    from narrator.settings import build_runtime_settings
    from narrator.user_state import save_persisted_speaking_rate

    save_persisted_speaking_rate(1.7)
    r = build_runtime_settings(
        config_explicit=None,
        voice=None,
        rate=None,
        volume=None,
        speak_hotkey=None,
        listen_hotkey=None,
        legacy_hotkey=None,
        silent=False,
        verbose=False,
    )
    assert r.speaking_rate == pytest.approx(1.7)


def test_cli_rate_overrides_persisted(isolated_state_dir: Path) -> None:
    from narrator.settings import build_runtime_settings
    from narrator.user_state import save_persisted_speaking_rate

    save_persisted_speaking_rate(2.0)
    r = build_runtime_settings(
        config_explicit=None,
        voice=None,
        rate=1.1,
        volume=None,
        speak_hotkey=None,
        listen_hotkey=None,
        legacy_hotkey=None,
        silent=False,
        verbose=False,
    )
    assert r.speaking_rate == pytest.approx(1.1)
