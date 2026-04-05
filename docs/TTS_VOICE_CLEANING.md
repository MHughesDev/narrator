# AI / neural TTS voice cleaning

This document summarizes common **post-processing** techniques used to make synthesized speech sound cleaner, then maps them to **Narrator’s** pipeline (what we already do vs optional settings).

Sources: industry narration / podcast workflows, TTS mastering notes (e.g. loudness, de-essing, limiting), and practical warnings that **heavy** noise-reduction chains can *hurt* neural TTS more than help—**gentle** processing is preferred.

## Techniques (typical broadcast / TTS chain)

| Technique | Purpose | Notes |
|-----------|---------|--------|
| **High-pass filter** (~60–100 Hz) | Remove sub-bass rumble, DC-ish offset, room boom | Very common first step; low risk if cutoff is conservative (~70 Hz). |
| **Loudness normalization (LUFS)** | Consistent perceived level across clips | Often −16 LUFS stereo / −19 mono for delivery; we use **peak** normalize (simpler, real-time friendly). |
| **De-essing** (~5–8 kHz) | Tame harsh “s” / sibilance | Subtle ratio; too much dulls consonants. Not in core path yet (CPU + tuning). |
| **Gentle EQ / air** | Clarity | e.g. small high-shelf; optional; engine-dependent. |
| **Soft limiting / peak safety** | Avoid inter-sample overs after normalize | Transparent limiter at end of chain; we cap with **int16 clip** after scaling. |
| **Crossfade + edge fades** | Remove clicks between segments | **Implemented:** overlap-add + ms fades at boundaries. |
| **Noise reduction (spectral)** | Hiss / background | Risky on TTS: can add warble; Coqui discussion notes **afftdn**-style stacks sometimes **reduce** quality—use sparingly. |

## What Narrator already applies (playback path)

Order in [`narrator/wav_play_win32.py`](../narrator/wav_play_win32.py) (after decode → mono):

1. **Segment crossfade** — [`pcm_apply_crossfade_overlap_s16`](../narrator/audio_pcm.py) when a previous tail exists (`segment_crossfade_ms`, `segment_transition_preset`).
2. **Optional voice clean** — [`pcm_highpass_sosfilt_s16`](../narrator/audio_pcm.py) when `speak_voice_clean_enabled` (high-pass only in v1).
3. **Peak normalize** — [`pcm_peak_normalize_s16`](../narrator/audio_pcm.py) (`pcm_peak_normalize`, `pcm_peak_normalize_level`).
4. **Edge fades** — `_fade_in_first_ms_pcm_s16` / `_fade_out_last_ms_pcm_s16` (`pcm_edge_fade_ms` via transition preset).

Upstream (not “mastering” but affects quality): **text preprocess** ([`speak_preprocess.py`](../narrator/speak_preprocess.py)), **chunk context** for prosody, **engine-specific** segment presets in [`segment_transitions.py`](../narrator/segment_transitions.py).

## Configuration (voice cleaning)

| Key | Default | Role |
|-----|---------|------|
| `speak_voice_clean_enabled` | `false` | Enable high-pass cleaning before peak normalize. |
| `speak_voice_clean_highpass_hz` | `72` | −3 dB-ish corner (Butterworth SOS + zero-phase); keep in 60–120 for speech. |

Environment: `NARRATOR_SPEAK_VOICE_CLEAN_ENABLED`, `NARRATOR_SPEAK_VOICE_CLEAN_HIGHPASS_HZ`.

**Recommendation:** Try `speak_voice_clean_enabled = true` for **XTTS / Piper** if you hear low-frequency garbage or uneven rumble; leave off if the voice sounds too thin on your speakers.

## Future extensions (repo-level ideas)

- **LUFS** or RMS-target stage alongside peak normalize (optional, more CPU).
- **Mild de-esser** on a narrow band (would need careful defaults per engine).
- **Per-engine presets** under `segment_transition_preset` or `speak_engine` (already used for crossfade/fade strengths).

See also [`TTS_PLAYBACK_ROADMAP.md`](TTS_PLAYBACK_ROADMAP.md) for the full synth → WAV → playback graph.
