"""
Compile multiple TTS segment WAVs into one PCM stream (VoxCPM-style: decode chunks, then join).

VoxCPM streams decoded audio patches and concatenates overlap regions during streaming inference.
Here we synthesize per-segment WAVs with the existing engines, merge PCM with the same overlap-add
crossfade used between segments, then play the merged clip once — :func:`speech.play_wav_interruptible`
applies voice clean / peak normalize / edge fades to the full utterance (no double-processing).
"""

from __future__ import annotations

import io
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from narrator.audio_pcm import pcm_apply_crossfade_overlap_s16, pcm_extract_tail_s16
from narrator.segment_transitions import resolve_playback_transition

if TYPE_CHECKING:
    from narrator.settings import RuntimeSettings

WavPathOrBytes = Path | bytes


@dataclass
class CompiledUtteranceState:
    """Accumulated mono int16 PCM plus format; ``prev_tail`` holds the last ``crossfade_ms`` for blending."""

    pcm: bytes = b""
    framerate: int = 22050
    channels: int = 1
    sampwidth: int = 2
    prev_tail: bytes | None = None
    segments_merged: int = 0


def _wav_bytes_to_mono_s16_pcm(raw: bytes) -> tuple[int, int, int, bytes]:
    """Return ``(channels, sampwidth, framerate, pcm)`` as mono 16-bit PCM."""
    with wave.open(io.BytesIO(raw), "rb") as w:
        if w.getcomptype() != "NONE":
            raise ValueError(f"unsupported WAV compression {w.getcomptype()}")
        channels = w.getnchannels()
        sampwidth = w.getsampwidth()
        framerate = w.getframerate()
        pcm = w.readframes(w.getnframes())

    if not pcm:
        return 1, 2, framerate, b""

    if sampwidth == 2 and channels > 1:
        import numpy as np

        x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32).reshape(-1, channels)
        mono = np.mean(x, axis=1)
        pcm = np.clip(np.round(mono), -32768, 32767).astype(np.int16).tobytes()
        channels = 1
    elif sampwidth == 1 and channels >= 1:
        import numpy as np

        u = np.frombuffer(pcm, dtype=np.uint8).astype(np.float32)
        if channels > 1:
            u = u.reshape(-1, channels).mean(axis=1)
        pcm = np.clip(np.round((u - 128.0) * 256.0), -32768, 32767).astype(np.int16).tobytes()
        sampwidth = 2
        channels = 1
    elif sampwidth != 2 or channels != 1:
        raise ValueError("compiled stream expects mono int16 after conversion")

    return channels, sampwidth, framerate, pcm


def merge_segment_wav_into_state(
    state: CompiledUtteranceState,
    wav: WavPathOrBytes,
    settings: "RuntimeSettings",
) -> None:
    """Decode one segment WAV and append to ``state`` with boundary crossfade (see VoxCPM sequential decode)."""
    raw = wav.read_bytes() if isinstance(wav, Path) else wav
    ch, sw, fr, pcm = _wav_bytes_to_mono_s16_pcm(raw)
    if not pcm:
        return

    if state.segments_merged == 0:
        state.framerate = fr
        state.channels = ch
        state.sampwidth = sw
        state.pcm = pcm
        state.segments_merged = 1
        transition = resolve_playback_transition(settings)
        xf = transition.segment_crossfade_ms
        if xf > 0:
            state.prev_tail = pcm_extract_tail_s16(
                pcm,
                channels=ch,
                sampwidth=sw,
                framerate=fr,
                ms=xf,
            )
        else:
            state.prev_tail = None
        return

    if fr != state.framerate or ch != state.channels or sw != state.sampwidth:
        raise ValueError(
            f"WAV format mismatch in compiled stream: got {(ch, sw, fr)}, "
            f"expected {(state.channels, state.sampwidth, state.framerate)}"
        )

    transition = resolve_playback_transition(settings)
    xf_ms = transition.segment_crossfade_ms
    if xf_ms > 0 and state.prev_tail and len(state.prev_tail) > 0:
        pcm = pcm_apply_crossfade_overlap_s16(
            pcm,
            state.prev_tail,
            channels=ch,
            sampwidth=sw,
            framerate=fr,
            ms=xf_ms,
        )

    state.pcm += pcm
    state.segments_merged += 1
    if xf_ms > 0:
        state.prev_tail = pcm_extract_tail_s16(
            pcm,
            channels=ch,
            sampwidth=sw,
            framerate=fr,
            ms=xf_ms,
        )
    else:
        state.prev_tail = None


def combined_utterance_label(work_items: list[tuple[str, str, str | None, str]]) -> str:
    """Join segment texts for logging / live-rate resynth (paragraph breaks between chunks)."""
    parts: list[str] = []
    for _synth, utterance_t, _ctx, _lab in work_items:
        u = utterance_t.strip()
        if u:
            parts.append(u)
    return "\n\n".join(parts)
