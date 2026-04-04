"""Pitch-preserving speaking rate via librosa phase-vocoder time stretch (PCM WAV in place)."""

from __future__ import annotations

import array
import io
import logging
import wave
from pathlib import Path

logger = logging.getLogger(__name__)


def _clamp_rate(v: float) -> float:
    return max(0.5, min(3.0, float(v)))


def apply_pitch_preserving_speaking_rate(path: Path, speaking_rate: float) -> None:
    """
    Rewrite ``path`` (16-bit PCM WAV) so playback tempo matches ``speaking_rate`` without
    changing perceived pitch. Engines' built-in rate controls often resample or alter prosody in
    ways that sound like pitch shifts; we synthesize at neutral speed and stretch here instead.
    """
    import librosa
    import numpy as np

    rate = _clamp_rate(speaking_rate)
    if abs(rate - 1.0) < 1e-4:
        return

    try:
        raw = path.read_bytes()
    except OSError as e:
        logger.error("speaking-rate stretch: read %s: %s", path, e)
        return

    try:
        with wave.open(io.BytesIO(raw), "rb") as wf:
            nch = wf.getnchannels()
            sw = wf.getsampwidth()
            fr = wf.getframerate()
            nframes = wf.getnframes()
            pcm = wf.readframes(nframes)
    except Exception as e:
        logger.error("speaking-rate stretch: parse wav: %s", e)
        return

    if sw != 2:
        logger.warning("speaking-rate stretch: expected 16-bit PCM, got %s bytes/sample — skipping", sw)
        return
    if not pcm or nch < 1:
        return

    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0

    try:
        if nch == 1:
            y = librosa.effects.time_stretch(x, rate=rate)
        else:
            # One phase-vocoder pass on a mono downmix — per-channel stretch makes L/R diverge and
            # sounds like multiple voices (chorus / talk-over) on stereo TTS output.
            mono = x.reshape(-1, nch).mean(axis=1)
            y_m = librosa.effects.time_stretch(mono, rate=rate)
            y = np.repeat(y_m[:, np.newaxis], nch, axis=1).reshape(-1)
    except Exception as e:
        logger.error("speaking-rate stretch: librosa failed: %s", e)
        return

    y = np.clip(y * 32768.0, -32768, 32767).astype(np.int16)
    try:
        # ``wave.open`` may not treat ``pathlib.Path`` as a writable path on all Python versions.
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(nch)
            wf.setsampwidth(2)
            wf.setframerate(fr)
            wf.writeframes(y.tobytes())
    except Exception as e:
        logger.error("speaking-rate stretch: write failed: %s — restoring original bytes", e)
        try:
            path.write_bytes(raw)
        except OSError:
            pass


def time_stretch_int16_interleaved(pcm: bytes, channels: int, rate_ratio: float) -> bytes:
    """
    Time-stretch 16-bit interleaved PCM (``rate_ratio`` as in ``librosa.effects.time_stretch``:
    values ``> 1`` speed up / shorten). Pitch-preserving phase vocoder.
    """
    import librosa
    import numpy as np

    if abs(rate_ratio - 1.0) < 1e-5 or not pcm or channels < 1:
        return pcm

    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    try:
        if channels == 1:
            y = librosa.effects.time_stretch(x, rate=rate_ratio)
        else:
            mono = x.reshape(-1, channels).mean(axis=1)
            y_m = librosa.effects.time_stretch(mono, rate=rate_ratio)
            y = np.repeat(y_m[:, np.newaxis], channels, axis=1).reshape(-1)
    except Exception as e:
        logger.error("time_stretch_int16_interleaved: %s", e)
        return pcm

    return np.clip(y * 32768.0, -32768, 32767).astype(np.int16).tobytes()


def tempo_change_resample_int16_interleaved(pcm: bytes, channels: int, rate_ratio: float) -> bytes:
    """
    Change tempo by **resampling** (same ``rate_ratio`` semantics as ``librosa.effects.time_stretch``:
    values ``> 1`` speed up / shorten output). **Pitch shifts** with speed (tape-style), which avoids the
    phase-vocoder **chorus/echo** artifacts that plague in-play ``time_stretch_int16_interleaved``.

    Uses ``scipy.signal.resample`` when SciPy is available; otherwise linear interpolation via NumPy.
    """
    import numpy as np

    if abs(rate_ratio - 1.0) < 1e-5 or not pcm or channels < 1 or rate_ratio <= 0:
        return pcm

    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    n_in = len(x) // channels
    if n_in < 1:
        return pcm
    n_out = max(1, int(round(n_in / rate_ratio)))

    try:
        from scipy import signal as scipy_signal

        if channels == 1:
            y = scipy_signal.resample(x, n_out)
        else:
            xr = x.reshape(n_in, channels)
            y = np.stack([scipy_signal.resample(xr[:, c], n_out) for c in range(channels)], axis=1).reshape(-1)
    except Exception:
        t_in = np.linspace(0.0, 1.0, n_in)
        t_out = np.linspace(0.0, 1.0, n_out)
        if channels == 1:
            y = np.interp(t_out, t_in, x)
        else:
            xr = x.reshape(n_in, channels)
            y = np.stack([np.interp(t_out, t_in, xr[:, c]) for c in range(channels)], axis=1).reshape(-1)

    return np.clip(np.round(y), -32768, 32767).astype(np.int16).tobytes()


# audiotsm WSOLA needs enough frames; shorter tails fall back to librosa (still pitch-preserving).
_MIN_FRAMES_WSOLA = 8000


def tempo_change_wsola_int16_interleaved(pcm: bytes, channels: int, rate_ratio: float) -> bytes:
    """
    Pitch-preserving time-scale via **WSOLA** (audiotsm). Same ``rate_ratio`` as librosa
    (``> 1`` = faster / shorter). For very short buffers, falls back to :func:`time_stretch_int16_interleaved`.
    """
    import numpy as np

    if abs(rate_ratio - 1.0) < 1e-5 or not pcm or channels < 1 or rate_ratio <= 0:
        return pcm

    x = np.frombuffer(pcm, dtype=np.int16)
    n = len(x) // channels
    if n < _MIN_FRAMES_WSOLA:
        return time_stretch_int16_interleaved(pcm, channels, rate_ratio)

    try:
        from audiotsm import wsola
        from audiotsm.io.array import ArrayReader, ArrayWriter

        xf = x.astype(np.float32).reshape(n, channels).T.copy() / 32768.0
        reader = ArrayReader(xf)
        writer = ArrayWriter(channels)
        # Larger frames reduce WSOLA warble on speech vs default 1024-sample frames.
        proc = wsola(channels, speed=rate_ratio, frame_length=2048)
        proc.run(reader, writer)
        out = writer.data
        if out.size == 0 or out.shape[1] < 1:
            return time_stretch_int16_interleaved(pcm, channels, rate_ratio)
        out_interleaved = out.T.reshape(-1)
        return np.clip(out_interleaved * 32768.0, -32768, 32767).astype(np.int16).tobytes()
    except Exception as e:
        logger.warning("WSOLA time stretch failed, using librosa: %s", e)
        return time_stretch_int16_interleaved(pcm, channels, rate_ratio)


def _pcm_u8_mono_to_s16(pcm: bytes) -> bytes:
    """8-bit unsigned WAV PCM (mono) to interleaved int16 little-endian."""
    out = array.array("h")
    for b in pcm:
        out.append((b - 128) << 8)
    return out.tobytes()


def _pcm_s16_mono_to_u8(pcm: bytes) -> bytes:
    """Mono int16 little-endian back to 8-bit unsigned."""
    out = bytearray()
    for i in range(0, len(pcm), 2):
        s = int.from_bytes(pcm[i : i + 2], "little", signed=True)
        out.append(max(0, min(255, (s // 256) + 128)))
    return bytes(out)


def apply_live_in_play_tempo(
    pcm: bytes,
    *,
    channels: int,
    sampwidth: int,
    rate_ratio: float,
    engine: str,
) -> bytes:
    """
    In-play tempo change for the waveOut handoff tail: **WSOLA** (default), librosa **phase_vocoder**,
    or **resample** (tape-speed).
    """
    eng = (engine or "wsola").strip().lower()
    if eng not in ("wsola", "phase_vocoder", "resample"):
        eng = "wsola"

    if eng == "resample":
        if sampwidth == 2:
            return tempo_change_resample_int16_interleaved(pcm, channels, rate_ratio)
        if sampwidth == 1:
            t16 = _pcm_u8_mono_to_s16(pcm)
            t16 = tempo_change_resample_int16_interleaved(t16, 1, rate_ratio)
            return _pcm_s16_mono_to_u8(t16)
        return pcm

    if eng == "phase_vocoder":
        if sampwidth == 2:
            return time_stretch_int16_interleaved(pcm, channels, rate_ratio)
        if sampwidth == 1:
            t16 = _pcm_u8_mono_to_s16(pcm)
            t16 = time_stretch_int16_interleaved(t16, 1, rate_ratio)
            return _pcm_s16_mono_to_u8(t16)
        return pcm

    # wsola (default)
    if sampwidth == 2:
        return tempo_change_wsola_int16_interleaved(pcm, channels, rate_ratio)
    if sampwidth == 1:
        t16 = _pcm_u8_mono_to_s16(pcm)
        t16 = tempo_change_wsola_int16_interleaved(t16, 1, rate_ratio)
        return _pcm_s16_mono_to_u8(t16)
    return pcm
