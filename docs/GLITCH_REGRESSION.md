# Glitch taxonomy and regression checklist

Use this when changing playback, live-rate, or TTS post-processing.

## Vocabulary

| Term | Typical cause |
|------|----------------|
| **Click** | Discontinuous sample at segment boundary or after `waveOutReset` |
| **Skip / stutter** | Buffer truncated mid-word, or underrun |
| **Overlap / echo** | Old PCM still in mixer; `waveOutGetPosition` lag; double playback |
| **Chorus / doubled** | Phase-vocoder or WSOLA on short tail; stereo L/R stretch mismatch |
| **Level jump** | No normalize; different engine gain per segment |
| **Lag** | Large `waveOut` buffers; sleep after close; settle timer |

## “Stutter” with no hyphen in the visible text

Listeners sometimes describe a glitch **phonetically** (“it said *re-ads*”) even when the on-screen word is plain `reads`. That can still be a **soft hyphen** or other invisible Unicode from the provider—handled by `speak_preprocess` normalization.

If the text is clean, a brief skip / silence is more often:

1. **Segment boundary** — the next WAV is not ready yet; the worker blocks on the prefetch queue → a short **gap** between segments (more likely when the **first chunk is short** and neural synthesis of the **next** chunk is slower than real-time).
2. **Buffering** — `waveOut` PCM is fed in slices; heavy CPU/GPU load can jitter delivery (rare).
3. **Engine behavior** — neural TTS (especially XTTS) can sound uneven on **very short** isolated chunks; `merge_trailing_short_chunks` reduces “robotic” tails.

Tuning: raise `speak_prefetch_depth`, avoid huge first-chunk / tiny-second imbalance, use `NARRATOR_DEBUG_AUDIO=1` to see segment boundaries.

**Chunk-context trim** (`speak_chunk_context_*`) removes overlapped audio with a frame cut; after trim the pipeline applies a short **head fade-in** so the splice does not click.

## Instrumentation

- `NARRATOR_DEBUG_AUDIO=1` — gate, `waveOut`, worker boundaries  
- `NARRATOR_DEBUG_LIVE_RATE=1` — handoff offset, ratio, engine  
- `NARRATOR_AUDIO_STATS=1` — counters for handoffs / resynth remainder  
- With debug audio, look for **`pcm ready`** lines: `effective_edge_fade_ms`, `effective_crossfade_ms`, `effective_peak_normalize`, `segment_transition_preset`, `speak_engine`.

## Manual regression (headphones + speakers)

1. **Single paragraph** at default rate — no boundary artifacts.  
2. **Ctrl+Alt+±** during playback — one clean transition; no double voice.  
3. **Long document** (multi-segment) — no clicks between segments; optional crossfade if enabled.  
4. **Cancel** mid-speech — immediate stop, no tail.  
5. With **`live_rate_resynth_remainder = true`** — speed change may re-synth remainder; expect short pause, clean prosody.  
6. With **`audio_output_backend = sounddevice`** — rate hotkeys apply to **next** utterance only (no in-play WSOLA).  

## Telemetry snapshot

From Python: `from narrator.playback_telemetry import snapshot; print(snapshot())` (after `NARRATOR_AUDIO_STATS=1` or debug audio).
