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

## Beyond VoxCPM — Coqui XTTS (research / community)

Narrator is not VoxCPM, but **Coqui XTTS** has well-known levers ([XTTS docs](https://github.com/coqui-ai/TTS/blob/dev/docs/source/models/xtts.md), [HF discussion](https://huggingface.co/coqui/XTTS-v2/discussions/10)):

| Technique | Notes |
|-----------|--------|
| **Keep the model loaded** | We cache one `TTS` instance in-process (`get_tts`). Avoid restarting the app between speaks. |
| **`split_sentences`** | Coqui’s `tts_to_file(..., split_sentences=True)` runs **one forward pass per sentence**. Narrator already splits long text in `synthesize_xtts_to_path`; we default **`xtts_split_sentences = false`** so each Narrator chunk is **one** Coqui call when possible. Set `true` only if you hit length limits on huge single chunks. Env: `NARRATOR_XTTS_SPLIT_SENTENCES`. |
| **`torch.inference_mode()`** | Optional wrapper around synthesis (default **on** via `xtts_torch_inference_mode`) — small autograd overhead reduction. Env: `NARRATOR_XTTS_TORCH_INFERENCE_MODE`. |
| **`.to("cuda")`** | After load, we move the Coqui `TTS` module to GPU when `gpu=True` so parameters follow the documented pattern. |
| **DeepSpeed** | Upstream reports lower latency with `use_deepspeed=True` on **manual** `Xtts` checkpoint loading — not exposed by our high-level `TTS` API path; advanced users would need a custom integration. |
| **Cache `gpt_cond_latent` / `speaker_embedding`** | For a **fixed** `speaker_wav`, Coqui docs recommend caching conditioning latents between calls. We do not cache these yet (speaker or reference can change per settings); a future optimization could cache keyed by resolved WAV path + model id. |
| **Streaming `inference_stream`** | Coqui supports chunk streaming for faster **first** audio; our pipeline is file-based (`tts_to_file`). Adopting it would mean a larger worker/playback refactor. |

## Piper / ONNX (GPU)

- **`piper_cuda = true`** uses the Piper ONNX path on GPU when `onnxruntime-gpu` matches your CUDA stack.
- ONNX Runtime tuning (TensorRT EP, CUDA EP `cudnn_conv_algo_search`, I/O binding) is **outside** the `piper-tts` Python API we call — worth profiling only if Piper is your primary engine.

## System-level ideas (brainstorm)

| Idea | Tradeoff |
|------|----------|
| **Prefer WinRT** for instant first audio on Windows when quality is acceptable — no multi‑GB GPU model load. |
| **Smaller / faster models** — Piper is lighter than XTTS; `xtts_v2` vs `v1.1` has different speaker and speed profiles (try benchmarks on your GPU). |
| **Disable LLM text pass** for neural engines when you do not need cleanup (`speak_text_llm_force_for_neural = false`, `speak_text_llm_enabled = false`). |
| **Raise `speak_prefetch_depth`** when using parallel synth workers so the queue stays full during long documents. |
| **Avoid `speak_chunk_context_enabled`** or shorten context if XTTS work per segment dominates. |
| **Single GPU process** — running Ollama + Narrator + XTTS on one card competes for VRAM; closing other GPU apps helps. |

See also [`settings_schema.md`](../narrator/settings_schema.md) for all keys and env overrides.
