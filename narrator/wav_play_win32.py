"""PCM WAV playback via winmm waveOut — reliable stop via waveOutReset (ctypes, no extra deps)."""

from __future__ import annotations

import array
import ctypes
import io
import logging
import os
import queue
import time
import wave
import winsound
from ctypes import wintypes
from pathlib import Path
from typing import TYPE_CHECKING

from narrator import audio_debug
from narrator.audio_pcm import (
    pcm_apply_crossfade_overlap_s16,
    pcm_extract_tail_s16,
    pcm_highpass_sosfilt_s16,
    pcm_peak_normalize_s16,
    pcm_prepend_silence_s16,
)
from narrator.playback_control import playback_gate_held
from narrator.playback_result import PlayWavResult
from narrator.playback_telemetry import record as playback_telemetry_record
from narrator.protocol import SHUTDOWN, SPEAK_RATE_DOWN, SPEAK_RATE_UP, SPEAK_TOGGLE
from narrator.segment_transitions import resolve_playback_transition
if TYPE_CHECKING:
    from narrator.settings import RuntimeSettings

logger = logging.getLogger(__name__)

# Cap waveOut buffer size so live-rate changes wait at most ~this much audio for a clean chunk boundary
# (smaller than 256 KiB legacy default — reduces mid-buffer cuts that sound like skips/stutter).
WAVEOUT_PCM_MAX_CHUNK_BYTES = 64 * 1024


def _purge_auxiliary_wave_playback() -> None:
    """Best-effort: clear legacy ``winsound`` output so nothing runs under waveOut."""
    try:
        winsound.PlaySound(None, winsound.SND_PURGE | winsound.SND_NODEFAULT)
    except Exception as e:
        logger.debug("SND_PURGE: %s", e)


winmm = ctypes.WinDLL("winmm", use_last_error=True)
user32 = ctypes.windll.user32

# Fallback if the keyboard hook does not enqueue ``speak_toggle`` (same chord as defaults).
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_S = 0x53


def _key_held(vk: int) -> bool:
    return (user32.GetAsyncKeyState(vk) & 0x8000) != 0


def _default_speak_chord_down() -> bool:
    return _key_held(VK_CONTROL) and _key_held(VK_MENU) and _key_held(VK_S)

WAVE_MAPPER = 0xFFFFFFFF
WAVE_FORMAT_PCM = 1
CALLBACK_NULL = 0
WHDR_DONE = 0x00000001
MMSYSERR_NOERROR = 0

def clamp_speaking_rate(v: float) -> float:
    return max(0.5, min(3.0, float(v)))


def apply_speak_rate_queue_message(settings: "RuntimeSettings", msg: object) -> bool:
    """Speaking rate is fixed at 1.0; rate hotkeys are disabled."""
    return False


def _drain_coalesce_speak_rates(event_queue: queue.Queue, settings: "RuntimeSettings") -> None:
    """
    Apply every pending Ctrl+Alt+/- already in the queue, then put back other messages in order.

    Without this, rapid +/+ produces multiple stretch passes; voices stack at different speeds.
    """
    pending: list[object] = []
    while True:
        try:
            pending.append(event_queue.get_nowait())
        except queue.Empty:
            break
    for m in pending:
        if m in (SPEAK_RATE_UP, SPEAK_RATE_DOWN):
            apply_speak_rate_queue_message(settings, m)
        else:
            event_queue.put(m)


def _settle_speak_rate_changes(
    event_queue: queue.Queue,
    settings: "RuntimeSettings",
    *,
    settle_ms: float,
) -> None:
    """
    After a rate nudge, wait briefly for more hotkeys (resetting the window on each) so one handoff
    sees the final target rate instead of chained WSOLA passes.
    """
    if settle_ms <= 0:
        return
    deadline = time.monotonic() + settle_ms / 1000.0
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            msg = event_queue.get(timeout=min(0.05, remaining))
        except queue.Empty:
            return
        if msg == SHUTDOWN or msg == SPEAK_TOGGLE:
            event_queue.put(msg)
            return
        if apply_speak_rate_queue_message(settings, msg):
            _drain_coalesce_speak_rates(event_queue, settings)
            deadline = time.monotonic() + settle_ms / 1000.0
        else:
            event_queue.put(msg)
            return


def handoff_tempo_engine_for_ratio(
    base: str,
    ratio: float,
    threshold: float,
) -> str:
    """
    Large in-play speed jumps make WSOLA/phase-vocoder tails sound smeary; use tape-speed resample
    for those handoffs when the configured engine is pitch-preserving.
    """
    b = (base or "wsola").strip().lower()
    if b not in ("wsola", "phase_vocoder", "resample"):
        b = "wsola"
    if threshold <= 1.0:
        return b
    r = max(float(ratio), 1.0 / max(float(ratio), 1e-9))
    if r > threshold and b in ("wsola", "phase_vocoder"):
        return "resample"
    return b


def adaptive_handoff_extra_sleep_s(tail_bytes: int, bpf: int, framerate: int) -> float:
    """Extra sleep after ``post_waveout_close_drain_s`` — shorter for tiny tails, capped for long ones."""
    if bpf <= 0 or framerate <= 0 or tail_bytes <= 0:
        return 0.06
    tail_s = (tail_bytes / float(bpf)) / float(framerate)
    return min(0.10, max(0.025, 0.02 + 0.06 * min(1.0, tail_s / 0.25)))


class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [
        ("wFormatTag", wintypes.WORD),
        ("nChannels", wintypes.WORD),
        ("nSamplesPerSec", wintypes.DWORD),
        ("nAvgBytesPerSec", wintypes.DWORD),
        ("nBlockAlign", wintypes.WORD),
        ("wBitsPerSample", wintypes.WORD),
        ("cbSize", wintypes.WORD),
    ]


class WAVEHDR(ctypes.Structure):
    _fields_ = [
        ("lpData", wintypes.LPVOID),
        ("dwBufferLength", wintypes.DWORD),
        ("dwBytesRecorded", wintypes.DWORD),
        ("dwUser", ctypes.c_size_t),
        ("dwFlags", wintypes.DWORD),
        ("dwLoops", wintypes.DWORD),
        ("lpNext", ctypes.c_void_p),
        ("reserved", ctypes.c_size_t),
    ]


waveOutOpen = winmm.waveOutOpen
waveOutOpen.argtypes = [
    ctypes.POINTER(wintypes.HANDLE),
    wintypes.UINT,
    ctypes.POINTER(WAVEFORMATEX),
    ctypes.c_size_t,
    ctypes.c_size_t,
    wintypes.DWORD,
]
waveOutOpen.restype = wintypes.UINT

waveOutPrepareHeader = winmm.waveOutPrepareHeader
waveOutPrepareHeader.argtypes = [wintypes.HANDLE, ctypes.POINTER(WAVEHDR), wintypes.UINT]
waveOutPrepareHeader.restype = wintypes.UINT

waveOutWrite = winmm.waveOutWrite
waveOutWrite.argtypes = [wintypes.HANDLE, ctypes.POINTER(WAVEHDR), wintypes.UINT]
waveOutWrite.restype = wintypes.UINT

waveOutReset = winmm.waveOutReset
waveOutReset.argtypes = [wintypes.HANDLE]
waveOutReset.restype = wintypes.UINT

waveOutUnprepareHeader = winmm.waveOutUnprepareHeader
waveOutUnprepareHeader.argtypes = [wintypes.HANDLE, ctypes.POINTER(WAVEHDR), wintypes.UINT]
waveOutUnprepareHeader.restype = wintypes.UINT

waveOutClose = winmm.waveOutClose
waveOutClose.argtypes = [wintypes.HANDLE]
waveOutClose.restype = wintypes.UINT

TIME_BYTES = 0x0004

# Defaults; overridden by RuntimeSettings and env (see ``build_runtime_settings`` / README).
# Used when sample-accurate seek is enabled (chunk discard off); position+slack path.
_DEFAULT_LIVE_RATE_RESUME_SLACK_MS = 280.0
_DEFAULT_POST_WAVEOUT_CLOSE_DRAIN_S = 0.35
# Floor slack/drain when accurate seek is on (env/settings may be lower).
_ACCURATE_SEEK_MIN_SLACK_MS = 280.0
_ACCURATE_SEEK_MIN_DRAIN_S = 0.35


class _MMTIME_U(ctypes.Union):
    _fields_ = [
        ("ms", wintypes.DWORD),
        ("sample", wintypes.DWORD),
        ("cb", wintypes.DWORD),
        ("ticks", wintypes.DWORD),
        ("smpte", wintypes.DWORD * 4),
        ("midi", wintypes.DWORD),
    ]


class MMTIME(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("wType", wintypes.UINT), ("u", _MMTIME_U)]


waveOutGetPosition = winmm.waveOutGetPosition
waveOutGetPosition.argtypes = [wintypes.HANDLE, ctypes.POINTER(MMTIME), wintypes.UINT]
waveOutGetPosition.restype = wintypes.UINT


def _env_float(name: str) -> float | None:
    v = os.environ.get(name, "").strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _live_rate_defer_to_next_utterance(settings: "RuntimeSettings") -> bool:
    """
    If True, rate hotkeys only update ``settings.speaking_rate`` for the *next* synthesis — we do **not**
    run librosa time-stretch on the current clip. Phase-vocoder stretch during playback often sounds like
    chorus / extra voices; deferring avoids that entirely.

    Default in :class:`narrator.settings.RuntimeSettings` is **False** (in-play rate changes allowed). Set
    ``live_rate_defer_during_playback = true`` or ``NARRATOR_LIVE_RATE_DEFER=1`` so hotkeys only affect the
    **next** utterance.
    """
    if _env_truthy("NARRATOR_LIVE_RATE_DEFER"):
        return True
    return bool(getattr(settings, "live_rate_defer_during_playback", False))


def live_rate_tuning_effective(settings: "RuntimeSettings") -> tuple[float, float, bool, bool]:
    """(slack_ms, post_close_drain_s, safe_chunk_discard, debug_log). Env overrides settings for live tuning.

    **Default:** chunk-boundary resume (``safe_chunk_discard=True``) — does not use ``waveOutGetPosition``
    for the cut point, so already-played audio is never repeated (fixes echo on many drivers).

    **Sample-accurate seek:** set ``NARRATOR_LIVE_RATE_ACCURATE_SEEK=1`` or ``live_rate_safe_chunk_discard=false``
    in TOML — uses position + slack (may echo if the driver lags the DAC).
    """
    slack = _env_float("NARRATOR_LIVE_RATE_SLACK_MS")
    if slack is None:
        slack = float(getattr(settings, "live_rate_resume_slack_ms", _DEFAULT_LIVE_RATE_RESUME_SLACK_MS))
    slack = max(0.0, min(2000.0, slack))

    drain = _env_float("NARRATOR_POST_WAVEOUT_CLOSE_DRAIN_S")
    if drain is None:
        drain = float(getattr(settings, "post_waveout_close_drain_s", _DEFAULT_POST_WAVEOUT_CLOSE_DRAIN_S))
    drain = max(0.0, min(2.0, drain))

    accurate_seek = _env_truthy("NARRATOR_LIVE_RATE_ACCURATE_SEEK")
    if _env_truthy("NARRATOR_LIVE_RATE_SAFE"):
        safe = True
    elif accurate_seek:
        safe = False
    else:
        safe = bool(getattr(settings, "live_rate_safe_chunk_discard", True))

    if not safe:
        slack = max(slack, _ACCURATE_SEEK_MIN_SLACK_MS)
        drain = max(drain, _ACCURATE_SEEK_MIN_DRAIN_S)

    debug = _env_truthy("NARRATOR_DEBUG_LIVE_RATE") or bool(getattr(settings, "verbose", False))
    return slack, drain, safe, debug


def compute_live_rate_resume_offset(
    *,
    pcm_len: int,
    bpf: int,
    chunk_boundary: int,
    chunk_end_exclusive: int,
    framerate: int,
    slack_ms: float,
    api_ok: bool,
    raw_cb_bytes: int,
) -> tuple[int, str]:
    """Pure resume offset for tests: byte index into ``pcm_play`` and a short reason tag."""
    if not api_ok:
        return min(chunk_end_exclusive, pcm_len), "api_error"
    if bpf <= 0:
        return min(chunk_end_exclusive, pcm_len), "bpf_nonpositive"
    pos = int(raw_cb_bytes)
    pos = (pos // bpf) * bpf
    if pos < 0:
        pos = 0
    if pos > pcm_len:
        pos = pcm_len
    # One buffer in flight: position should lie within the current chunk while it plays.
    if pos < chunk_boundary or pos > chunk_end_exclusive:
        return min(chunk_end_exclusive, pcm_len), "sanity_fallback"
    slack = max(0, int(framerate * bpf * slack_ms / 1000))
    pos = min(pcm_len, pos + slack)
    return pos, "ok"


def _playback_pcm_byte_offset(
    hwo: wintypes.HANDLE,
    pcm_len: int,
    *,
    bpf: int,
    chunk_boundary: int,
    chunk_end_exclusive: int,
    framerate: int,
    slack_ms: float,
    live_rate_safe_chunk_discard: bool,
) -> tuple[int, str, int | None]:
    """Byte offset into ``pcm_play``, reason tag, and raw ``waveOutGetPosition`` bytes (if sampled)."""
    if live_rate_safe_chunk_discard:
        return min(chunk_end_exclusive, pcm_len), "safe_chunk_discard", None
    if bpf <= 0:
        return min(chunk_end_exclusive, pcm_len), "bpf_nonpositive", None
    mm = MMTIME.from_buffer_copy(b"\x00" * ctypes.sizeof(MMTIME))
    mm.wType = TIME_BYTES
    r = waveOutGetPosition(hwo, ctypes.byref(mm), ctypes.sizeof(MMTIME))
    raw = int(mm.cb)
    api_ok = r == MMSYSERR_NOERROR
    off, reason = compute_live_rate_resume_offset(
        pcm_len=pcm_len,
        bpf=bpf,
        chunk_boundary=chunk_boundary,
        chunk_end_exclusive=chunk_end_exclusive,
        framerate=framerate,
        slack_ms=slack_ms,
        api_ok=api_ok,
        raw_cb_bytes=raw,
    )
    return off, reason, raw if api_ok else None


def _poll_until_buffer_done_or_cancel(
    dev: _WaveOutDevice,
    hdr: WAVEHDR,
    event_queue: queue.Queue,
    settings: "RuntimeSettings",
) -> bool:
    """
    Wait until the current ``waveOut`` buffer finishes (``WHDR_DONE``) or the user cancels.

    Used before a live-rate handoff so we do not call ``waveOutReset`` mid-buffer (which truncates
    speech and sounds like skipping/stutter).
    """
    chord_prev = _default_speak_chord_down()
    while not (hdr.dwFlags & WHDR_DONE):
        try:
            msg = event_queue.get(timeout=0.05)
        except queue.Empty:
            now = _default_speak_chord_down()
            if now and not chord_prev:
                dev.reset()
                return False
            chord_prev = now
            continue
        chord_prev = _default_speak_chord_down()
        if msg == SHUTDOWN or msg == SPEAK_TOGGLE:
            dev.reset()
            return False
        if not apply_speak_rate_queue_message(settings, msg):
            continue
        _drain_coalesce_speak_rates(event_queue, settings)
        if _live_rate_defer_to_next_utterance(settings):
            logger.debug(
                "live rate deferred during buffer drain (target=%.2f×)",
                settings.speaking_rate,
            )
            continue
    return True


def _wait_min_handoff_interval(
    event_queue: queue.Queue,
    settings: "RuntimeSettings",
    dev: _WaveOutDevice,
    *,
    last_handoff_t: float,
    min_iv_s: float,
) -> bool:
    """Wait until ``min_iv_s`` has passed since ``last_handoff_t`` (polls queue for cancel)."""
    if min_iv_s <= 0 or last_handoff_t <= 0:
        return True
    target = last_handoff_t + min_iv_s
    while time.monotonic() < target:
        rem = target - time.monotonic()
        if rem <= 0:
            break
        try:
            msg = event_queue.get(timeout=min(0.05, rem))
        except queue.Empty:
            continue
        if msg == SHUTDOWN or msg == SPEAK_TOGGLE:
            dev.reset()
            return False
        if not apply_speak_rate_queue_message(settings, msg):
            continue
        _drain_coalesce_speak_rates(event_queue, settings)
    return True


def _handoff_pcm_for_new_speaking_rate(
    dev: _WaveOutDevice,
    wfx: WAVEFORMATEX,
    hdr: WAVEHDR,
    *,
    pcm_play: bytes,
    chunks: list[bytes],
    chunk_idx: int,
    chunk: bytes,
    bpf: int,
    framerate: int,
    sampwidth: int,
    channels: int,
    rate_effective: float,
    settings: "RuntimeSettings",
    forced_byte_offset: int | None = None,
    utterance_text: str | None = None,
) -> tuple[bool, bytes, float, str | None]:
    """
    ``waveOutReset``, unprepare header, close device, optional drain, tempo-adjust tail, reopen.

    Used only when in-play rate changes are enabled (``live_rate_defer_during_playback`` is false). Tail tempo
    uses ``live_rate_in_play_engine`` (default **wsola**: pitch-preserving without tape-speed pitch shift).
    Returns ``(True, new_pcm_play, new_rate_effective, resynth_remainder_or_none)`` on success. Fourth element
    set triggers remainder re-synthesis in the worker instead of playing a stretched tail.
    Returns ``(False, …, None)`` only if ``waveOutOpen`` fails after many retries.
    """
    ratio = settings.speaking_rate / max(rate_effective, 1e-6)
    chunk_boundary = sum(len(chunks[j]) for j in range(chunk_idx))
    chunk_end_exclusive = chunk_boundary + len(chunk)
    _slack_ms, _drain_s, _safe_chunk, _debug_live = live_rate_tuning_effective(settings)
    if forced_byte_offset is not None:
        offset = min(max(0, int(forced_byte_offset)), len(pcm_play))
        _off_reason = "buffer_done_chunk_end"
        _raw_cb = None
    else:
        offset, _off_reason, _raw_cb = _playback_pcm_byte_offset(
            dev.hwo,
            len(pcm_play),
            bpf=bpf,
            chunk_boundary=chunk_boundary,
            chunk_end_exclusive=chunk_end_exclusive,
            framerate=framerate,
            slack_ms=_slack_ms,
            live_rate_safe_chunk_discard=_safe_chunk,
        )
        if offset < chunk_boundary:
            offset = chunk_boundary
    if _debug_live:
        logger.info(
            "live-rate handoff: reason=%s pcm_len=%s chunk_boundary=%s chunk_end=%s "
            "raw_waveout_cb=%s offset=%s tail_bytes=%s ratio=%.4f slack_ms=%.1f "
            "drain_s=%.2f accurate_seek=%s",
            _off_reason,
            len(pcm_play),
            chunk_boundary,
            chunk_end_exclusive,
            _raw_cb,
            offset,
            max(0, len(pcm_play) - offset),
            ratio,
            _slack_ms,
            _drain_s,
            not _safe_chunk,
        )

    raw_tail_preview = pcm_play[offset:]
    resynth_on = bool(getattr(settings, "live_rate_resynth_remainder", True))
    min_rem = int(getattr(settings, "live_rate_resynth_min_remainder_chars", 12))
    if resynth_on and utterance_text and forced_byte_offset is not None:
        start = min(
            len(utterance_text),
            int((offset / max(len(pcm_play), 1)) * len(utterance_text)),
        )
        remainder = utterance_text[start:].strip()
        if len(remainder) >= min_rem:
            dev.reset()
            u = waveOutUnprepareHeader(dev.hwo, ctypes.byref(hdr), ctypes.sizeof(WAVEHDR))
            if u != MMSYSERR_NOERROR:
                logger.debug("waveOutUnprepareHeader (rate change): %s", u)
            dev.close()
            _purge_auxiliary_wave_playback()
            extra_sleep = adaptive_handoff_extra_sleep_s(len(raw_tail_preview), bpf, framerate)
            time.sleep(_drain_s)
            time.sleep(extra_sleep)
            playback_telemetry_record("live_rate_resynth_remainder")
            logger.debug(
                "live rate: resynth remainder (%d chars) at %.2f× — skipping in-play stretch",
                len(remainder),
                float(settings.speaking_rate),
            )
            return True, b"", float(settings.speaking_rate), remainder

    dev.reset()
    u = waveOutUnprepareHeader(dev.hwo, ctypes.byref(hdr), ctypes.sizeof(WAVEHDR))
    if u != MMSYSERR_NOERROR:
        logger.debug("waveOutUnprepareHeader (rate change): %s", u)
    dev.close()
    _purge_auxiliary_wave_playback()
    raw_tail = pcm_play[offset:]
    extra_sleep = adaptive_handoff_extra_sleep_s(len(raw_tail), bpf, framerate)
    time.sleep(_drain_s)
    time.sleep(extra_sleep)
    if not raw_tail:
        # Nothing left to play at the new rate; finish this WAV without reopening the device.
        return True, b"", float(settings.speaking_rate), None

    base_eng = str(getattr(settings, "live_rate_in_play_engine", "wsola")).strip().lower()
    thr = float(getattr(settings, "live_rate_extreme_ratio_threshold", 1.15))
    eng = handoff_tempo_engine_for_ratio(base_eng, ratio, thr)
    if audio_debug.is_enabled():
        audio_debug.log_kv(
            "live tempo adjust (in-play)",
            tail_bytes=len(raw_tail),
            ratio=ratio,
            sampwidth=sampwidth,
            engine=eng,
            base_engine=base_eng,
            extreme_threshold=thr,
        )
    tail = raw_tail
    try:
        from narrator.wav_speaking_rate import apply_live_in_play_tempo

        tail = apply_live_in_play_tempo(
            raw_tail,
            channels=channels,
            sampwidth=sampwidth,
            rate_ratio=ratio,
            engine=eng,
        )
    except Exception as e:
        logger.error("live tempo change: %s", e)
        tail = raw_tail
    if not tail:
        logger.warning("live tempo adjust produced empty tail; using unstretched remainder")
        tail = raw_tail
    elif sampwidth == 2:
        tail = _fade_in_first_ms_pcm_s16(
            tail,
            channels=channels,
            sampwidth=sampwidth,
            framerate=framerate,
            ms=4.0,
        )

    prs = float(getattr(settings, "post_reset_silence_ms", 0.0))
    if prs > 0 and sampwidth == 2:
        tail = pcm_prepend_silence_s16(
            tail, channels=channels, sampwidth=sampwidth, framerate=framerate, ms=prs
        )

    new_rate = float(settings.speaking_rate)
    if _wave_out_open_retry(dev, wfx):
        _prev_eff = rate_effective
        logger.debug(
            "Speaking rate now %.2f× for remainder of clip (was %.2f×).",
            new_rate,
            _prev_eff,
        )
        playback_telemetry_record("live_rate_handoff")
        return True, tail, new_rate, None

    logger.error(
        "waveOutOpen failed after live-rate handoff (retried). "
        "Try increasing post_waveout_close_drain_s in config or NARRATOR_POST_WAVEOUT_CLOSE_DRAIN_S."
    )
    return False, pcm_play, rate_effective, None


def _interleaved_s16_to_mono(pcm: bytes, channels: int) -> bytes:
    """Average interleaved 16-bit samples to mono (no numpy). Avoids stereo playback quirks."""
    if channels <= 1 or not pcm:
        return pcm
    s = array.array("h")
    s.frombytes(pcm)
    n_frames = len(s) // channels
    if n_frames * channels != len(s):
        return pcm
    out = array.array("h")
    for i in range(n_frames):
        base = i * channels
        total = sum(int(s[base + c]) for c in range(channels))
        out.append(total // channels)
    return out.tobytes()


def _interleaved_u8_to_mono(pcm: bytes, channels: int) -> bytes:
    """Average interleaved 8-bit unsigned samples to mono."""
    if channels <= 1 or not pcm:
        return pcm
    n_frames = len(pcm) // channels
    if n_frames * channels != len(pcm):
        return pcm
    out = bytearray()
    for i in range(n_frames):
        base = i * channels
        s = sum(pcm[base + c] for c in range(channels)) // channels
        out.append(max(0, min(255, s)))
    return bytes(out)


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


def _fade_in_first_ms_pcm_s16(
    pcm: bytes,
    *,
    channels: int,
    sampwidth: int,
    framerate: int,
    ms: float = 3.5,
) -> bytes:
    """Gentle linear fade-in on the first few ms to reduce waveOut / segment-start clicks (16-bit PCM)."""
    import numpy as np

    if sampwidth != 2 or not pcm or channels < 1:
        return pcm
    bpf = channels * sampwidth
    if len(pcm) < bpf * 4:
        return pcm
    nframes = len(pcm) // bpf
    nfade = min(max(2, int(framerate * (ms / 1000.0))), nframes)
    if nfade < 2:
        return pcm
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32).copy()
    ramp = np.linspace(0.0, 1.0, nfade, dtype=np.float32)
    if channels == 1:
        x[:nfade] *= ramp
    else:
        xf = x.reshape(-1, channels)
        xf[:nfade, :] *= ramp[:, np.newaxis]
    return np.clip(np.round(x), -32768, 32767).astype(np.int16).tobytes()


def _fade_out_last_ms_pcm_s16(
    pcm: bytes,
    *,
    channels: int,
    sampwidth: int,
    framerate: int,
    ms: float = 3.5,
) -> bytes:
    """Linear fade-out on the last few ms to reduce clicks at clip end and before segment boundaries."""
    import numpy as np

    if sampwidth != 2 or not pcm or channels < 1 or ms <= 0:
        return pcm
    bpf = channels * sampwidth
    if len(pcm) < bpf * 4:
        return pcm
    nframes = len(pcm) // bpf
    nfade = min(max(2, int(framerate * (ms / 1000.0))), nframes)
    if nfade < 2:
        return pcm
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32).copy()
    ramp = np.linspace(1.0, 0.0, nfade, dtype=np.float32)
    if channels == 1:
        x[-nfade:] *= ramp
    else:
        xf = x.reshape(-1, channels)
        xf[-nfade:, :] *= ramp[:, np.newaxis]
    return np.clip(np.round(x), -32768, 32767).astype(np.int16).tobytes()


def _pcm_chunks(
    pcm: bytes,
    *,
    channels: int,
    sampwidth: int,
    framerate: int,
    max_chunk_bytes: int = 256 * 1024,
) -> tuple[int, list[bytes]]:
    """Split PCM into chunks the driver is happy with; return bytes per frame and chunks."""
    bpf = channels * sampwidth
    if bpf <= 0:
        return bpf, [pcm]
    # At least ~100ms per chunk so we poll the cancel queue often enough
    min_chunk = max(bpf * framerate // 10, bpf)
    chunk_size = max(min_chunk, min(max_chunk_bytes, len(pcm)))
    chunks = []
    offset = 0
    while offset < len(pcm):
        chunks.append(pcm[offset : offset + chunk_size])
        offset += chunk_size
    return bpf, chunks


class _WaveOutDevice:
    """Single winmm ``waveOut`` handle: open → play → close. Never two opens without a close in between."""

    __slots__ = ("_hwo", "_open")

    def __init__(self) -> None:
        self._hwo = wintypes.HANDLE()
        self._open = False

    @property
    def hwo(self) -> wintypes.HANDLE:
        return self._hwo

    @property
    def is_open(self) -> bool:
        return self._open

    def open(self, wfx: WAVEFORMATEX) -> bool:
        self.close()
        r = waveOutOpen(ctypes.byref(self._hwo), WAVE_MAPPER, ctypes.byref(wfx), 0, 0, CALLBACK_NULL)
        self._open = r == MMSYSERR_NOERROR
        if not self._open:
            logger.error("waveOutOpen failed: %s", r)
        if audio_debug.is_enabled():
            h = int(ctypes.cast(self._hwo, ctypes.c_void_p).value or 0)
            audio_debug.log_kv(
                "waveOutOpen",
                ok=self._open,
                mm_result=r,
                handle=h,
                dev_id=id(self),
                rate=wfx.nSamplesPerSec,
                channels=wfx.nChannels,
                bits=wfx.wBitsPerSample,
            )
        return self._open

    def close(self) -> None:
        if not self._open:
            return
        h = int(ctypes.cast(self._hwo, ctypes.c_void_p).value or 0)
        c = waveOutClose(self._hwo)
        self._open = False
        if c != MMSYSERR_NOERROR:
            logger.debug("waveOutClose: %s", c)
        if audio_debug.is_enabled():
            audio_debug.log_kv("waveOutClose", mm_result=c, handle=h, dev_id=id(self))

    def reset(self) -> None:
        if self._open:
            waveOutReset(self._hwo)
            if audio_debug.is_enabled():
                h = int(ctypes.cast(self._hwo, ctypes.c_void_p).value or 0)
                audio_debug.log_kv("waveOutReset", handle=h, dev_id=id(self))


def _wave_out_open_retry(dev: _WaveOutDevice, wfx: WAVEFORMATEX, *, attempts: int = 12) -> bool:
    """Re-open ``waveOut`` after device reset/close; drivers sometimes need several attempts."""
    for i in range(attempts):
        if dev.open(wfx):
            return True
        delay = min(0.05 * (2 ** min(i, 6)), 1.0)
        time.sleep(delay)
    return False


def play_wav_interruptible(
    path: Path | bytes,
    event_queue: queue.Queue,
    *,
    settings: "RuntimeSettings",
    rate_baked_in_wav: float,
    utterance_text: str | None = None,
    crossfade_prev_pcm: bytes | None = None,
) -> PlayWavResult:
    """
    Play a WAV file in small queued buffers; poll ``event_queue`` between buffers.
    On ``speak_toggle`` / ``shutdown``, call ``waveOutReset`` so audio stops immediately.

    Returns:
        :class:`PlayWavResult` — see ``played_full_clip``, ``resynth_remainder_text``, ``crossfade_tail_pcm``.

    ``rate_baked_in_wav`` is the speaking rate already applied to this file (post-synthesis stretch).

    ``speak_rate_up`` / ``speak_rate_down`` (Ctrl+Alt+Plus / Minus) update ``settings.speaking_rate``.
    In-play tail tempo uses ``live_rate_in_play_engine`` (default **wsola**, pitch-preserving). Set
    ``live_rate_defer_during_playback`` to apply rate only on the **next** utterance.

    Only one PCM playback session may run at a time process-wide (:func:`narrator.playback_control.playback_gate_held`).
    """
    with playback_gate_held():
        return _play_wav_pcm(
            path,
            event_queue,
            settings=settings,
            rate_baked_in_wav=rate_baked_in_wav,
            utterance_text=utterance_text,
            crossfade_prev_pcm=crossfade_prev_pcm,
        )


def _play_wav_pcm(
    path: Path | bytes,
    event_queue: queue.Queue,
    *,
    settings: "RuntimeSettings",
    rate_baked_in_wav: float,
    utterance_text: str | None = None,
    crossfade_prev_pcm: bytes | None = None,
) -> PlayWavResult:
    audio_debug.log_kv(
        "_play_wav_pcm enter",
        path="(bytes)" if isinstance(path, bytes) else str(path),
        rate_baked_in_wav=rate_baked_in_wav,
    )
    try:
        try:
            if isinstance(path, bytes):
                raw = path
            else:
                raw = path.read_bytes()
        except OSError as e:
            logger.error("read wav: %s", e)
            return PlayWavResult.cancelled()

        if not isinstance(path, bytes):
            try:
                path.unlink(missing_ok=True)
            except OSError as e:
                logger.debug("unlink wav: %s", e)

        try:
            with wave.open(io.BytesIO(raw), "rb") as w:
                if w.getcomptype() != "NONE":
                    logger.error("unsupported WAV compression %s", w.getcomptype())
                    return PlayWavResult.cancelled()
                channels = w.getnchannels()
                sampwidth = w.getsampwidth()
                framerate = w.getframerate()
                pcm = w.readframes(w.getnframes())
        except Exception as e:
            logger.error("wav parse: %s", e)
            return PlayWavResult.cancelled()

        if not pcm:
            return PlayWavResult.cancelled()

        if sampwidth not in (1, 2):
            logger.error("unsupported sample width %s bytes", sampwidth)
            return PlayWavResult.cancelled()

        # Always play mono: stereo TTS WAVs through waveOut can sound like doubled voices on some setups.
        if channels > 1 and sampwidth == 2:
            pcm = _interleaved_s16_to_mono(pcm, channels)
            channels = 1
        if channels > 1 and sampwidth == 1:
            pcm = _interleaved_u8_to_mono(pcm, channels)
            channels = 1

        transition = resolve_playback_transition(settings)
        xf_ms = transition.segment_crossfade_ms
        if (
            xf_ms > 0
            and crossfade_prev_pcm
            and sampwidth == 2
            and len(crossfade_prev_pcm) > 0
        ):
            pcm = pcm_apply_crossfade_overlap_s16(
                pcm,
                crossfade_prev_pcm,
                channels=channels,
                sampwidth=sampwidth,
                framerate=framerate,
                ms=xf_ms,
            )

        if bool(getattr(settings, "speak_voice_clean_enabled", False)) and sampwidth == 2:
            pcm = pcm_highpass_sosfilt_s16(
                pcm,
                channels=channels,
                sampwidth=sampwidth,
                framerate=framerate,
                cutoff_hz=float(getattr(settings, "speak_voice_clean_highpass_hz", 72.0)),
            )

        if transition.pcm_peak_normalize and sampwidth == 2:
            pcm = pcm_peak_normalize_s16(
                pcm,
                channels=channels,
                sampwidth=sampwidth,
                peak=transition.pcm_peak_normalize_level,
            )

        edge_ms = transition.pcm_edge_fade_ms
        pcm = _fade_in_first_ms_pcm_s16(
            pcm,
            channels=channels,
            sampwidth=sampwidth,
            framerate=framerate,
            ms=edge_ms,
        )
        pcm = _fade_out_last_ms_pcm_s16(
            pcm,
            channels=channels,
            sampwidth=sampwidth,
            framerate=framerate,
            ms=edge_ms,
        )

        if audio_debug.is_enabled():
            audio_debug.log_kv(
                "pcm ready",
                pcm_bytes=len(pcm),
                channels=channels,
                sampwidth=sampwidth,
                framerate=framerate,
                segment_transition_preset=str(
                    getattr(settings, "segment_transition_preset", "engine")
                ),
                speak_engine=str(getattr(settings, "speak_engine", "winrt")),
                effective_edge_fade_ms=edge_ms,
                effective_crossfade_ms=xf_ms,
                effective_peak_normalize=transition.pcm_peak_normalize,
                speak_voice_clean_enabled=bool(
                    getattr(settings, "speak_voice_clean_enabled", False)
                ),
            )

        backend = str(getattr(settings, "audio_output_backend", "waveout")).strip().lower()
        if backend == "sounddevice":
            try:
                from narrator.audio_sounddevice_play import play_prepared_pcm_sounddevice

                return play_prepared_pcm_sounddevice(
                    pcm,
                    channels,
                    sampwidth,
                    framerate,
                    event_queue,
                    settings,
                    rate_baked_in_wav,
                    utterance_text=utterance_text,
                )
            except ImportError:
                logger.warning(
                    "audio_output_backend=sounddevice requires the sounddevice package; "
                    "pip install sounddevice — falling back to waveOut"
                )

        wfx = WAVEFORMATEX()
        wfx.wFormatTag = WAVE_FORMAT_PCM
        wfx.nChannels = channels
        wfx.nSamplesPerSec = framerate
        wfx.wBitsPerSample = sampwidth * 8
        wfx.nBlockAlign = channels * sampwidth
        wfx.nAvgBytesPerSec = framerate * wfx.nBlockAlign
        wfx.cbSize = 0

        dev = _WaveOutDevice()
        if not dev.open(wfx):
            return PlayWavResult.cancelled()

        bpf = channels * sampwidth
        rate_effective = float(rate_baked_in_wav)
        pcm_play: bytes = pcm
        last_handoff_t = 0.0

        try:
            while pcm_play:
                seg_pcm_snapshot = pcm_play
                _, chunks = _pcm_chunks(
                    pcm_play,
                    channels=channels,
                    sampwidth=sampwidth,
                    framerate=framerate,
                    max_chunk_bytes=WAVEOUT_PCM_MAX_CHUNK_BYTES,
                )
                if audio_debug.is_enabled() and chunks:
                    bpf_i = max(bpf, 1)
                    nframes = len(pcm_play) // bpf_i
                    dur_s = (nframes / float(framerate)) if framerate else 0.0
                    sizes = [len(c) for c in chunks]
                    audio_debug.log_kv(
                        "speaker / waveOut: PCM going to default output device",
                        n_audio_buffers=len(chunks),
                        chunk_pcm_bytes_min=min(sizes),
                        chunk_pcm_bytes_max=max(sizes),
                        pcm_segment_bytes=len(pcm_play),
                        approx_duration_sec=round(dur_s, 4),
                        sample_rate_hz=framerate,
                        channels=channels,
                        rate_baked_into_wav=rate_baked_in_wav,
                    )
                chunk_idx = 0
                need_restart = False
                while chunk_idx < len(chunks) and not need_restart:
                    chunk = chunks[chunk_idx]
                    buf = ctypes.create_string_buffer(chunk, len(chunk))
                    hdr = WAVEHDR()
                    hdr.lpData = ctypes.cast(buf, wintypes.LPVOID)
                    hdr.dwBufferLength = len(chunk)

                    r = waveOutPrepareHeader(dev.hwo, ctypes.byref(hdr), ctypes.sizeof(WAVEHDR))
                    if r != MMSYSERR_NOERROR:
                        logger.error("waveOutPrepareHeader failed: %s", r)
                        return PlayWavResult.cancelled()

                    hdr_unprepared = False
                    try:
                        r = waveOutWrite(dev.hwo, ctypes.byref(hdr), ctypes.sizeof(WAVEHDR))
                        if r != MMSYSERR_NOERROR:
                            logger.error("waveOutWrite failed: %s", r)
                            return PlayWavResult.cancelled()
                        if audio_debug.is_enabled():
                            audio_debug.log_kv(
                                "waveOutWrite",
                                bytes=len(chunk),
                                chunk_idx=chunk_idx,
                                n_chunks=len(chunks),
                                pcm_play_len=len(pcm_play),
                            )

                        chord_prev = _default_speak_chord_down()
                        while not (hdr.dwFlags & WHDR_DONE):
                            try:
                                msg = event_queue.get(timeout=0.05)
                            except queue.Empty:
                                now = _default_speak_chord_down()
                                if now and not chord_prev:
                                    dev.reset()
                                    return PlayWavResult.cancelled()
                                chord_prev = now
                                continue
                            chord_prev = _default_speak_chord_down()
                            if msg == SHUTDOWN or msg == SPEAK_TOGGLE:
                                dev.reset()
                                return PlayWavResult.cancelled()
                            if not apply_speak_rate_queue_message(settings, msg):
                                continue
                            _drain_coalesce_speak_rates(event_queue, settings)

                            if _live_rate_defer_to_next_utterance(settings):
                                logger.debug(
                                    "live rate deferred to next utterance (no in-play stretch): target=%.2f×",
                                    settings.speaking_rate,
                                )
                                continue

                            if abs(settings.speaking_rate - rate_effective) < 1e-5:
                                continue

                            _settle_speak_rate_changes(
                                event_queue,
                                settings,
                                settle_ms=float(getattr(settings, "live_rate_settle_ms", 30.0)),
                            )
                            if _live_rate_defer_to_next_utterance(settings):
                                logger.debug(
                                    "live rate deferred after settle: target=%.2f×",
                                    settings.speaking_rate,
                                )
                                continue
                            if abs(settings.speaking_rate - rate_effective) < 1e-5:
                                continue

                            min_iv = float(getattr(settings, "live_rate_min_handoff_interval_s", 0.0))
                            if not _wait_min_handoff_interval(
                                event_queue,
                                settings,
                                dev,
                                last_handoff_t=last_handoff_t,
                                min_iv_s=min_iv,
                            ):
                                return PlayWavResult.cancelled()
                            if not _poll_until_buffer_done_or_cancel(
                                dev, hdr, event_queue, settings
                            ):
                                return PlayWavResult.cancelled()
                            chunk_end_exclusive = sum(len(chunks[j]) for j in range(chunk_idx)) + len(
                                chunk
                            )
                            ok_handoff, pcm_play, rate_effective, resynth_rem = (
                                _handoff_pcm_for_new_speaking_rate(
                                    dev,
                                    wfx,
                                    hdr,
                                    pcm_play=pcm_play,
                                    chunks=chunks,
                                    chunk_idx=chunk_idx,
                                    chunk=chunk,
                                    bpf=bpf,
                                    framerate=framerate,
                                    sampwidth=sampwidth,
                                    channels=channels,
                                    rate_effective=rate_effective,
                                    settings=settings,
                                    forced_byte_offset=chunk_end_exclusive,
                                    utterance_text=utterance_text,
                                )
                            )
                            hdr_unprepared = True
                            if not ok_handoff:
                                return PlayWavResult.cancelled()
                            if resynth_rem:
                                return PlayWavResult.resynth(resynth_rem)
                            last_handoff_t = time.monotonic()
                            need_restart = True
                            break
                    finally:
                        if not hdr_unprepared:
                            u = waveOutUnprepareHeader(dev.hwo, ctypes.byref(hdr), ctypes.sizeof(WAVEHDR))
                            if u != MMSYSERR_NOERROR:
                                logger.debug("waveOutUnprepareHeader: %s", u)

                    if need_restart:
                        break
                    chunk_idx += 1

                if not need_restart:
                    xf_tail: bytes | None = None
                    if transition.segment_crossfade_ms > 0 and sampwidth == 2:
                        xf_tail = pcm_extract_tail_s16(
                            seg_pcm_snapshot,
                            channels=channels,
                            sampwidth=sampwidth,
                            framerate=framerate,
                            ms=transition.segment_crossfade_ms,
                        )
                    return PlayWavResult.complete(crossfade_tail_pcm=xf_tail)
            # ``pcm_play`` became empty without hitting complete inside the loop (edge case).
            return PlayWavResult.complete()
        finally:
            dev.close()
    finally:
        audio_debug.log_kv("_play_wav_pcm leave")
