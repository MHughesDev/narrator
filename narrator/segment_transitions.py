"""Resolve segment boundary smoothing (edge fades, crossfade, peak normalize) per speak engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from narrator.settings import RuntimeSettings


@dataclass(frozen=True)
class PlaybackTransitionParams:
    """Effective values for one WAV decode/play path."""

    pcm_edge_fade_ms: float
    segment_crossfade_ms: float
    pcm_peak_normalize: bool
    pcm_peak_normalize_level: float


# Defaults favor maximum smoothness (within ~40 ms crossfade cap in settings): stronger overlap reduces
# clicks; peak normalize evens level jumps between synthesized segments.
_ENGINE_DEFAULTS: dict[str, tuple[float, float, bool]] = {
    "winrt": (8.0, 30.0, True),
    "piper": (7.5, 32.0, True),
    # XTTS: longer overlap + edge fade reduces boundary clicks and level steps between neural chunks.
    "xtts": (10.0, 38.0, True),
}
_FALLBACK_ENGINE = (7.0, 24.0, True)


def resolve_playback_transition(settings: "RuntimeSettings") -> PlaybackTransitionParams:
    """
    ``segment_transition_preset``:

    - **engine** (default): tuned per ``speak_engine`` (winrt / piper / xtts).
    - **custom**: use ``pcm_edge_fade_ms``, ``segment_crossfade_ms``, ``pcm_peak_normalize`` from settings.
    - **minimal**: lighter overlap than **engine** but still crossfaded + normalized (less aggressive than per-engine defaults).
    """
    preset = str(getattr(settings, "segment_transition_preset", "engine")).strip().lower()
    lvl = float(getattr(settings, "pcm_peak_normalize_level", 0.95))
    lvl = max(0.1, min(1.0, lvl))

    if preset == "custom":
        return PlaybackTransitionParams(
            pcm_edge_fade_ms=float(getattr(settings, "pcm_edge_fade_ms", 8.0)),
            segment_crossfade_ms=float(getattr(settings, "segment_crossfade_ms", 24.0)),
            pcm_peak_normalize=bool(getattr(settings, "pcm_peak_normalize", True)),
            pcm_peak_normalize_level=lvl,
        )

    if preset == "minimal":
        # Lightest CPU path that still sounds acceptable: short overlap + gentle fades.
        return PlaybackTransitionParams(
            pcm_edge_fade_ms=5.0,
            segment_crossfade_ms=12.0,
            pcm_peak_normalize=True,
            pcm_peak_normalize_level=lvl,
        )

    # engine (default) or unknown → per-engine table
    eng = str(getattr(settings, "speak_engine", "winrt")).strip().lower()
    edge, xf, norm = _ENGINE_DEFAULTS.get(eng, _FALLBACK_ENGINE)
    return PlaybackTransitionParams(
        pcm_edge_fade_ms=edge,
        segment_crossfade_ms=xf,
        pcm_peak_normalize=norm,
        pcm_peak_normalize_level=lvl,
    )
