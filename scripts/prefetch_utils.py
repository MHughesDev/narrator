"""
Helpers for idempotent model prefetch (Piper voices, Hugging Face / Coqui XTTS cache).

Setup never uninstalls packages or deletes user caches; callers only skip redundant work.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    # Single source of truth (scripts may run before `pip install -e .`).
    from narrator.tts_xtts import DEFAULT_XTTS_MODEL_ID
except ImportError:  # pragma: no cover
    DEFAULT_XTTS_MODEL_ID = "tts_models/multilingual/multi-dataset/xtts_v1.1"

_FORCE_ENV = "NARRATOR_FORCE_PREFETCH"


def env_force_prefetch() -> bool:
    v = (os.environ.get(_FORCE_ENV) or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def hf_hub_cache_roots() -> list[Path]:
    """Directories where huggingface_hub stores model repos (`hub` layout)."""
    roots: list[Path] = []
    hub_override = (os.environ.get("HUGGINGFACE_HUB_CACHE") or "").strip()
    if hub_override:
        roots.append(Path(hub_override))
    hf_home = (os.environ.get("HF_HOME") or "").strip()
    if hf_home:
        roots.append(Path(hf_home) / "hub")
    roots.append(Path.home() / ".cache" / "huggingface" / "hub")
    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        try:
            resolved = str(r.resolve())
        except OSError:
            resolved = str(r)
        if resolved not in seen:
            seen.add(resolved)
            out.append(r)
    return out


def _snapshots_nonempty(model_cache_dir: Path) -> bool:
    snap = model_cache_dir / "snapshots"
    if not snap.is_dir():
        return False
    try:
        for child in snap.iterdir():
            if not child.is_dir():
                continue
            for f in child.iterdir():
                if f.is_file() and f.stat().st_size > 0:
                    return True
    except OSError:
        return False
    return False


def _hub_slug_for_model_id(model_id: str) -> str:
    return "models--" + model_id.replace("/", "--")


def xtts_cache_likely_ready(model_id: str | None = None) -> bool:
    """
    Best-effort True if default XTTS weights appear to be in a local HF-style cache.

    Does not import torch/TTS — safe to call before heavy installs. May return False
    when models live in a nonstandard path (setup will still run prefetch).
    """
    mid = (model_id or "").strip() or DEFAULT_XTTS_MODEL_ID
    for hub_root in hf_hub_cache_roots():
        if not hub_root.is_dir():
            continue
        slug = _hub_slug_for_model_id(mid)
        direct = hub_root / slug
        if direct.is_dir() and _snapshots_nonempty(direct):
            return True
        try:
            for p in hub_root.glob("models--*xtts*"):
                if p.is_dir() and _snapshots_nonempty(p):
                    return True
        except OSError:
            pass
    return _coqui_local_tts_has_large_xtts_artifact()


def _coqui_local_tts_has_large_xtts_artifact() -> bool:
    """Coqui may cache under ~/.local/share/tts (Linux) or similar."""
    candidates = [
        Path.home() / ".local" / "share" / "tts",
    ]
    la = os.environ.get("LOCALAPPDATA", "")
    if la:
        candidates.append(Path(la) / "tts")
    for base in candidates:
        if not base.is_dir():
            continue
        try:
            for f in base.rglob("*"):
                if not f.is_file():
                    continue
                if "xtts" not in f.name.lower():
                    continue
                try:
                    if f.stat().st_size >= 1_000_000:
                        return True
                except OSError:
                    continue
        except OSError:
            continue
    return False


def piper_voice_files_ready(voice_id: str, data_dir: Path) -> bool:
    """True if default Piper layout has both ONNX and JSON for this voice id."""
    vid = voice_id.strip()
    onnx = data_dir / f"{vid}.onnx"
    meta = data_dir / f"{vid}.onnx.json"
    try:
        if not onnx.is_file() or not meta.is_file():
            return False
        return onnx.stat().st_size > 0 and meta.stat().st_size > 0
    except OSError:
        return False
