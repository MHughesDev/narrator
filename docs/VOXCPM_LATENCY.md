# VoxCPM-style latency ideas in Narrator

[OpenBMB/VoxCPM](https://github.com/OpenBMB/VoxCPM) optimizes **time to first audible output** in ways that map only partly to Narrator (WinRT / Piper / XTTS). This document records what upstream does and how Narrator mirrors the relevant parts.

## What VoxCPM does (upstream)

| Technique | Role |
|-----------|------|
| **`torch.compile`** on hot paths (CUDA) | Reduces per-step inference overhead after the first compiled runs. Not applicable to our engines. |
| **Warmup `generate()` after load** | `VoxCPM.__init__` calls `tts_model.generate(...)` once so compile + kernels settle before user input. |
| **Streaming inference** | `generate_streaming` yields decoded audio chunks so playback can start before the full utterance is generated. |
| **KV / attention cache** | `setup_cache` on LMs reduces repeated work across steps. Model-internal. |
| **Optional reference denoiser** | ZipEnhancer on prompt/reference WAV — quality/latency tradeoff for cloning, not our stack. |

## What Narrator does

| Setting / behavior | Effect |
|--------------------|--------|
| **`speak_warmup_on_start`** (default **on**) | Background thread: for **XTTS** loads the model and optionally runs a **short synthesis** (“Hi.”); for **Piper** loads ONNX and optionally synthesizes the same. Mirrors VoxCPM’s post-load warmup without blocking the UI thread. Disable with `speak_warmup_on_start = false` or `NARRATOR_SPEAK_WARMUP_ON_START=0`. |
| **`speak_warmup_synthesize`** (default **on**) | If **off**, only **load** models (no tiny WAV). Slightly less startup CPU/GPU work; first hotkey may still pay full first-inference cost. Env: `NARRATOR_SPEAK_WARMUP_SYNTHESIZE`. |
| **`speak_audio_stream_compile`** (default **off**) | **On**: merge all segment WAVs into **one** PCM file, then play once (smooth single-file processing; **higher time-to-first-audio** for long documents because later segments must be synthesized sequentially during compile). **Off**: **prefetch** upcoming segments while the first plays — closer to VoxCPM **streaming** (start speaking after segment 0, pipeline the rest). Env: `NARRATOR_SPEAK_AUDIO_STREAM_COMPILE`. |
| **`speak_prefetch_depth`** / **`speak_synth_worker_threads`** | Deeper queue and optional parallel synth workers improve **steady-state** throughput; first segment is still dominated by capture + preprocess + first synth. |
| **`speak_preprocess_streaming`** | Prepares an initial text bundle first so the first TTS chunk can start while the rest of the document is still being cleaned. |

## Practical tuning

- **Fastest first speech** on neural engines: keep **`speak_audio_stream_compile = false`**, enable warmup (defaults), avoid LLM text pass if not needed (`speak_text_llm_force_for_neural = false`), use **`scripts/prefetch_xtts_model.py`** so weights are already on disk.
- **Smoothest single-file playback** for long multi-segment speaks: set **`speak_audio_stream_compile = true`** (accept longer wait before audio starts).

See also [`settings_schema.md`](../narrator/settings_schema.md) for all keys and env overrides.
