"""Return type for interruptible WAV playback (worker uses this for segment chaining and resynth)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlayWavResult:
    """Outcome of :func:`narrator.speech.play_wav_interruptible`."""

    played_full_clip: bool
    """True if the entire clip played without cancel/shutdown/error."""

    resynth_remainder_text: str | None = None
    """If set, stop in-play stretch and re-synthesize this text at the current rate (see worker)."""

    crossfade_tail_pcm: bytes | None = None
    """Last ``segment_crossfade_ms`` of PCM (16-bit mono) for blending into the next segment."""

    @staticmethod
    def complete(crossfade_tail_pcm: bytes | None = None) -> PlayWavResult:
        return PlayWavResult(True, None, crossfade_tail_pcm)

    @staticmethod
    def cancelled() -> PlayWavResult:
        return PlayWavResult(False, None, None)

    @staticmethod
    def resynth(remainder_text: str) -> PlayWavResult:
        return PlayWavResult(False, remainder_text, None)

    @property
    def user_cancelled(self) -> bool:
        """User aborted (toggle/shutdown/chord) — do not continue multi-segment speak."""
        return not self.played_full_clip and self.resynth_remainder_text is None
