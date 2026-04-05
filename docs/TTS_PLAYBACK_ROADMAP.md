# TTS and playback quality — roadmap

End-to-end view of how **captured text** becomes **audio**, where quality issues come from, and which **settings / modules** apply. For system shape and threading, see [`ARCHITECTURE.md`](../ARCHITECTURE.md). For hotkey semantics and capture rules, see [`SPEC.md`](../SPEC.md). For setup and profiles, see [`SETUP.md`](SETUP.md). For **post-processing / “voice cleaning”** (high-pass, loudness notes, future ideas), see [`TTS_VOICE_CLEANING.md`](TTS_VOICE_CLEANING.md). For **local LLM chunk readying** and synth prefetch settings, see [`SPEAK_TEXT_LLM.md`](SPEAK_TEXT_LLM.md).

---

## 1. Scope and mental model

Three layers affect perceived quality:

| Layer | What it controls | Typical issues |
|-------|------------------|----------------|
| **Text fidelity** | Invisible Unicode, PDF artifacts, soft hyphens | Odd pauses “inside” a word; tokenizer stress |
| **Neural prosody** | Chunk size, context, engine choice | Robotic short chunks; uneven emphasis across segment boundaries |
| **Audio glue** | `waveOut` buffers, crossfades, prefetch queue | Clicks, gaps between segments, echo / chorus from live-rate |

```mermaid
flowchart LR
  cap[Capture_UIA]
  prep[prepare_speak_text]
  chunk[iter_tts_chunks]
  pros[apply_speak_prosody]
  synth[Synthesize_engine]
  wav[Temp_WAV]
  play[play_wav_interruptible]

  cap --> prep --> chunk --> pros --> synth --> wav --> play
```

---

## 2. Text pipeline (before chunking)

**Streaming preprocess (large documents):** [`split_raw_for_streaming_preprocess`](../narrator/speak_chunking.py) + [`narrator/worker.py`](../narrator/worker.py) — first bundle is preprocessed and chunked immediately; the rest preprocesses in a background thread so the first WAV can start sooner (`speak_preprocess_streaming`, `speak_preprocess_initial_chunks`).

**Module:** [`narrator/speak_preprocess.py`](../narrator/speak_preprocess.py)

- **`prepare_speak_text` / `prepare_speak_text_from_settings`:** Optional stripping of links, math, markup, citations, technical tokens, chrome, emoji — controlled by `speak_exclude_*` in [`narrator/settings.py`](../narrator/settings.py) and [`settings_schema.md`](../narrator/settings_schema.md).
- **`_strip_invisible_chars`:** BOM, zero-width, bidi controls, **U+FFFC** (object replacement from some PDFs), etc.
- **`_normalize_hyphens_and_dashes_for_tts`:** Removes **soft hyphen (U+00AD)**; normalizes Unicode hyphen/minus variants; replaces en/em dash spans with comma pauses. This fixes **source text** that can sound like a mid-word stutter when the on-screen word looks normal.

**Limits:** Preprocessing does **not** fix all “stutters.” Listeners often describe glitches **phonetically** (e.g. “it said *re-ads*”) even when no visible hyphen exists — invisible characters are one cause; **playback gaps** (below) are another.

---

## 3. Chunking

**Module:** [`narrator/speak_chunking.py`](../narrator/speak_chunking.py)

- **`iter_tts_chunks`:** Splits long text at paragraph boundaries, then sentence boundaries, then **`_hard_wrap`** (whitespace) as a last resort.
- **`effective_speak_chunk_max_chars`:** For **`xtts`**, caps at **`XTTS_MAX_CHARS_PER_SEGMENT`** (Coqui’s English tokenizer warns ~250 characters; longer input risks truncation and GPU errors — see [`tts_xtts.py`](../narrator/tts_xtts.py)).
- **`clamp_chunk_max_chars`:** Default minimum segment size when `min_chunk_floor` is not set (XTTS passes a lower floor via the worker).
- **`merge_trailing_short_chunks`:** If the **last** segment is shorter than a threshold (~72 chars) and joining it to the previous segment stays under `max_chars`, merge them. Reduces “robotic” prosody on tiny isolated tails (especially XTTS).
- **`extract_chunk_context_tail`:** Last sentence(s) or word-aligned suffix of the previous chunk (for `speak_chunk_context_*` in [`worker.py`](../narrator/worker.py)).
- **Chunk context (default on):** `speak_chunk_context_enabled` — first piece of chunk *k+1* is synthesized as `context + utterance` on **WinRT, Piper, and XTTS**, then [`apply_chunk_context_trim`](../narrator/speech.py) removes the audio corresponding to `context` (`duration_probe` synthesizes context-only WAV to measure frames, or `fixed_ms`).

---

## 4. Per-engine synthesis

| Engine | Primary modules | Chunking / notes |
|--------|-----------------|------------------|
| **WinRT** | [`narrator/speech.py`](../narrator/speech.py), WinRT async synthesis | Large segments OK; optional SSML breaks via [`speak_prosody.py`](../narrator/speak_prosody.py) |
| **Piper** | [`narrator/tts_piper.py`](../narrator/tts_piper.py) | ONNX; `length_scale` for speaking rate at synthesis time |
| **XTTS** | [`narrator/tts_xtts.py`](../narrator/tts_xtts.py) | Worker respects `XTTS_MAX_CHARS_PER_SEGMENT`; **`synthesize_xtts_to_path`** micro-splits again with `iter_tts_chunks` and concatenates WAVs with a short crossfade |

**XTTS and short strings:** Very short, isolated utterances (e.g. a single instructional sentence) can sound more “prompt-like” or robotic because the model’s prior over long-form prose does not apply equally. Chunk merging and optional **chunk context** (§3) mitigate it.

---

## 5. Prefetch and segment gaps

**Module:** [`narrator/worker.py`](../narrator/worker.py)

**Order of operations (multi-segment):**

1. Build `work_items` from chunked, prosody-applied text.
2. Synthesize **segment 0** synchronously (cancellable queue).
3. If more segments exist, start a **prefetch thread** that synthesizes segments `1 … n-1` and enqueues `(wav_path, label, utterance_text)` tuples (synthesis used the paired `synth_text` / context already).
4. **Playback loop:** `play_wav_interruptible` for each segment; between segments, **`_blocking_get_ready_segment`** waits on a bounded queue for the next WAV.

**Why audible gaps happen:** If playback of segment *k* finishes before the WAV for segment *k+1* is ready, the worker blocks on the queue — the user hears **silence** (often reported as a skip or stutter). This is most visible when the **playing** segment is **short** (few seconds) but **synthesis** of the next segment is **slower than real-time** (heavy CPU/GPU load, large XTTS chunk, cold cache).

**Knobs:** `speak_prefetch_depth` (queue size), `speak_chunk_max_chars` (fewer/larger segments), engine choice; **`NARRATOR_DEBUG_AUDIO=1`** for segment boundaries and PCM stats.

**Risk note (future work):** Starting synthesis of segment 1 **before** segment 0 completes could overlap work on a **single** XTTS GPU model. Without a dedicated **inference lock** and careful measurement, concurrent calls may race or contend on VRAM. Any “early prefetch” design must account for this.

---

## 6. Playback glue

**Modules:** [`narrator/wav_play_win32.py`](../narrator/wav_play_win32.py), [`narrator/segment_transitions.py`](../narrator/segment_transitions.py)

- **Decode → optional peak normalize → edge fades → optional crossfade tail from previous segment →** feed PCM to winmm **`waveOut`** in slices (`WAVEOUT_PCM_MAX_CHUNK_BYTES` caps buffer size).
- **`resolve_playback_transition`:** `segment_transition_preset` (`engine` / `custom` / `minimal`) selects `pcm_edge_fade_ms`, `segment_crossfade_ms`, `pcm_peak_normalize` (per-engine defaults for WinRT / Piper / XTTS).
- **Live speaking rate:** Ctrl+Alt+Plus/Minus; WSOLA / phase vocoder / resample; remainder re-synthesis; see [`ARCHITECTURE.md`](../ARCHITECTURE.md) §4.4 and [`docs/DEBUG_MULTIPLE_VOICES.md`](DEBUG_MULTIPLE_VOICES.md).

---

## 7. Symptom → cause → mitigations

The canonical taxonomy lives in [`docs/GLITCH_REGRESSION.md`](GLITCH_REGRESSION.md). Extended here:

| Symptom | Likely causes | What to try |
|---------|----------------|-------------|
| Click / pop | Discontinuous samples at join or after `waveOutReset` | `segment_transition_preset`, `pcm_edge_fade_ms`, `segment_crossfade_ms` |
| Skip / stutter | Buffer underrun; **segment boundary silence** (prefetch not ready) | Shorter chunks vs faster synth; `speak_prefetch_depth`; reduce load; debug audio |
| Overlap / echo | Old PCM still playing; position lag | `live_rate_safe_chunk_discard`, `DEBUG_MULTIPLE_VOICES.md` |
| Chorus / doubled | WSOLA / phase vocoder on short tail | `live_rate_resynth_remainder`, `live_rate_defer_during_playback` |
| Mid-word “pause” (clean visible text) | Invisible soft hyphen / dash unicode | Preprocess normalization (§2) |
| Robotic tail | Tiny last segment | `merge_trailing_short_chunks` (§3) |
| New chunk starts “fresh” at a boundary | Model sees no prior text | `speak_chunk_context_enabled` (§3) |

---

## 8. Future / optional work (backlog)

- **Safe prefetch:** Serial XTTS inference lock + measured overlap of synthesis time vs playback duration; optional “prime” strategies without unsafe parallel GPU inference.
- **CUDA synthesis failure:** Retry on CPU or skip segment with log — partially guided by existing error hints in [`narrator/speech.py`](../narrator/speech.py).

---

## 9. Verification

- **Manual:** Checklist in [`docs/GLITCH_REGRESSION.md`](GLITCH_REGRESSION.md); long PDF / multi-segment; compare engines (`--speak-engine winrt|piper|xtts`).
- **Automated:** [`tests/test_speak_chunking.py`](../tests/test_speak_chunking.py) (chunking, merge, context tail, hyphen normalization); [`tests/test_audio_pcm.py`](../tests/test_audio_pcm.py) (WAV head trim); [`tests/test_wav_play_win32.py`](../tests/test_wav_play_win32.py) (playback helpers).

---

## 10. Which document to read

| Question | Doc |
|----------|-----|
| Setup, CUDA, profiles | [`docs/SETUP.md`](SETUP.md) |
| Process, threads, hotkeys, §4.4 TTS overview | [`ARCHITECTURE.md`](../ARCHITECTURE.md) |
| **This pipeline** — preprocess → chunk → synth → play | **This file** |
| Glitch vocabulary + regression checklist | [`docs/GLITCH_REGRESSION.md`](GLITCH_REGRESSION.md) |
| Echo / multiple voices / live rate | [`docs/DEBUG_MULTIPLE_VOICES.md`](DEBUG_MULTIPLE_VOICES.md) |
| Config keys | [`narrator/settings_schema.md`](../narrator/settings_schema.md) |
| Repo layout | [`docs/REPO_LAYOUT.md`](REPO_LAYOUT.md) |
