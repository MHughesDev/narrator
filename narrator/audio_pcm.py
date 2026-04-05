"""Shared PCM helpers: peak normalize, segment crossfade, silence pad (16-bit mono preferred)."""

from __future__ import annotations

import io
import wave
from pathlib import Path


def wav_read_pcm(path: Path) -> tuple[int, int, int, bytes]:
    """Return ``(nchannels, sampwidth, framerate, pcm_bytes)`` from a PCM WAV file."""
    raw = path.read_bytes()
    with wave.open(io.BytesIO(raw), "rb") as w:
        return w.getnchannels(), w.getsampwidth(), w.getframerate(), w.readframes(w.getnframes())


def wav_write_pcm(path: Path, channels: int, sampwidth: int, framerate: int, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sampwidth)
        w.setframerate(framerate)
        w.writeframes(pcm)


def wav_frame_count(path: Path) -> int:
    ch, sw, fr, pcm = wav_read_pcm(path)
    bpf = ch * sw
    if bpf <= 0:
        return 0
    return len(pcm) // bpf


def wav_trim_head_frames(path: Path, n_frames: int) -> bool:
    """Remove the first ``n_frames`` frames from a PCM WAV in place. Returns False if nothing trimmed."""
    if n_frames <= 0:
        return True
    ch, sw, fr, pcm = wav_read_pcm(path)
    bpf = ch * sw
    need = n_frames * bpf
    if len(pcm) <= need:
        return False
    wav_write_pcm(path, ch, sw, fr, pcm[need:])
    return True


def wav_trim_head_ms(path: Path, ms: float) -> bool:
    """Remove approximately the first ``ms`` milliseconds (by frame count)."""
    if ms <= 0:
        return True
    ch, sw, fr, pcm = wav_read_pcm(path)
    bpf = ch * sw
    n = int(fr * (ms / 1000.0))
    return wav_trim_head_frames(path, n)


def wav_fade_in_head_ms(path: Path, ms: float) -> None:
    """
    Linear fade-in on the first ``ms`` of a 16-bit PCM WAV (in place).

    Softens discontinuities after arbitrary sample cuts (e.g. chunk-context trim).
    """
    import numpy as np

    if ms <= 0:
        return
    ch, sw, fr, pcm = wav_read_pcm(path)
    if sw != 2 or not pcm or ch < 1:
        return
    bpf = ch * sw
    nframes = len(pcm) // bpf
    n = min(nframes, max(2, int(fr * (ms / 1000.0))))
    if n < 2 or nframes < 3:
        return
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32).copy()
    xf = x.reshape(-1, ch)
    ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)[:, np.newaxis]
    xf[:n, :] *= ramp
    wav_write_pcm(
        path,
        ch,
        sw,
        fr,
        np.clip(np.round(xf.ravel()), -32768, 32767).astype(np.int16).tobytes(),
    )


def pcm_highpass_sosfilt_s16(
    pcm: bytes,
    *,
    channels: int,
    sampwidth: int,
    framerate: int,
    cutoff_hz: float = 72.0,
) -> bytes:
    """
    Zero-phase high-pass (Butterworth SOS + ``sosfiltfilt``) for interleaved int16 PCM.

    Reduces sub-bass rumble and DC-like offset common in neural TTS exports. Requires **SciPy**
    (installed with ``librosa``). Returns ``pcm`` unchanged if SciPy is missing, width is not 16-bit,
    or the buffer is too short to filter safely.
    """
    import numpy as np

    if sampwidth != 2 or not pcm or channels < 1:
        return pcm
    try:
        from scipy.signal import butter, sosfiltfilt
    except ImportError:
        return pcm

    bpf = channels * sampwidth
    nframes = len(pcm) // bpf
    # sosfiltfilt needs enough samples; keep conservative for short UI bleeps.
    if nframes < 64:
        return pcm
    nyq = 0.5 * float(framerate)
    if cutoff_hz <= 0 or cutoff_hz >= nyq * 0.85:
        return pcm
    fc = min(cutoff_hz, nyq * 0.2)

    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float64).reshape(-1, channels) / 32768.0
    sos = butter(4, fc, btype="high", fs=float(framerate), output="sos")
    try:
        for c in range(channels):
            x[:, c] = sosfiltfilt(sos, x[:, c])
    except ValueError:
        return pcm
    y = np.clip(np.round(x * 32767.0), -32768, 32767).astype(np.int16)
    return y.tobytes()


def pcm_peak_normalize_s16(
    pcm: bytes,
    *,
    channels: int,
    sampwidth: int,
    peak: float = 0.95,
) -> bytes:
    """Scale interleaved int16 PCM so max absolute sample is ``peak * 32767`` (no-op if silent)."""
    import numpy as np

    if sampwidth != 2 or not pcm or channels < 1 or peak <= 0:
        return pcm
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    if x.size == 0:
        return pcm
    m = float(np.max(np.abs(x)))
    if m < 1e-6:
        return pcm
    scale = (32767.0 * peak) / m
    y = np.clip(np.round(x * scale), -32768, 32767).astype(np.int16)
    return y.tobytes()


def pcm_extract_tail_s16(
    pcm: bytes,
    *,
    channels: int,
    sampwidth: int,
    framerate: int,
    ms: float,
) -> bytes:
    """Last ``ms`` milliseconds of PCM (16-bit), or empty if too short."""
    if sampwidth != 2 or ms <= 0 or not pcm or channels < 1:
        return b""
    bpf = channels * sampwidth
    nframes = len(pcm) // bpf
    ntail = min(nframes, max(1, int(framerate * (ms / 1000.0))))
    return pcm[-ntail * bpf :]


def pcm_prepend_silence_s16(
    pcm: bytes,
    *,
    channels: int,
    sampwidth: int,
    framerate: int,
    ms: float,
) -> bytes:
    """Prepend zeros (16-bit interleaved)."""
    if sampwidth != 2 or ms <= 0 or channels < 1:
        return pcm
    bpf = channels * sampwidth
    n = max(0, int(framerate * (ms / 1000.0)))
    return b"\x00" * (n * bpf) + pcm


def pcm_apply_crossfade_overlap_s16(
    pcm: bytes,
    prev_tail: bytes,
    *,
    channels: int,
    sampwidth: int,
    framerate: int,
    ms: float,
) -> bytes:
    """
    Overlap-add crossfade: ``prev_tail`` is the last ``ms`` of the previous segment; fade it with
    the first ``ms`` of ``pcm``. Lengths must match for the overlap region (caller trims ``prev_tail``).
    """
    import numpy as np

    if sampwidth != 2 or ms <= 0 or not pcm or channels < 1:
        return pcm
    bpf = channels * sampwidth
    n = max(2, int(framerate * (ms / 1000.0)))
    need = n * bpf
    if len(prev_tail) < need or len(pcm) < need:
        return pcm
    a = np.frombuffer(prev_tail[-need:], dtype=np.int16).astype(np.float32).reshape(n, channels)
    b = np.frombuffer(pcm[:need], dtype=np.int16).astype(np.float32).reshape(n, channels)
    t = np.linspace(0.0, 1.0, n, dtype=np.float32)[:, np.newaxis]
    mix = (1.0 - t) * a + t * b
    out = np.frombuffer(pcm, dtype=np.int16).astype(np.float32).copy()
    om = out.reshape(-1, channels)
    om[:n, :] = mix
    return np.clip(np.round(out), -32768, 32767).astype(np.int16).tobytes()


def pcm_ensure_standard_sample_rate(
    framerate: int,
    *,
    preferred: tuple[int, ...] = (22050, 24000, 44100, 48000),
) -> int:
    """Return ``framerate`` if already common; otherwise return nearest preferred (hint for TTS export)."""
    if framerate in preferred:
        return framerate
    return min(preferred, key=lambda f: abs(f - framerate))
