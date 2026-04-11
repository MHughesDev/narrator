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

## Beyond VoxCPM — Coqui XTTS (implemented knobs)

| Setting | What it does |
|---------|----------------|
| **`xtts_split_sentences`** | Coqui `tts_to_file` only; default **false** (fewer forward passes). |
| **`xtts_torch_inference_mode`** | Wraps synthesis in `torch.inference_mode()`. |
| **`xtts_torch_autocast`** | For **clone** path using `Xtts.inference` / `inference_stream`, enables `torch.autocast` on CUDA (`xtts_autocast_dtype`: float16 or bfloat16). |
| **`xtts_use_deepspeed`** | After initial load, re-invokes `load_checkpoint(..., use_deepspeed=True)` on the underlying model (requires `pip install deepspeed`). Model cache key includes this flag. |
| **`xtts_cache_conditioning_latents`** | Caches `get_conditioning_latents()` tensors (CPU) keyed by `speaker_wav` path, mtime, and model id. |
| **Clone path: `inference()` / `inference_stream()`** | When `speaker_wav` is set (or Piper-built ref), we call `Xtts.inference` or `inference_stream` with **one** `get_conditioning_latents` per session (cached), instead of `tts_to_file` re-encoding the reference every time. Falls back to `tts_to_file` on error. Named speakers (v2) still use `tts_to_file`. |
| **`xtts_inference_stream`** | Uses `inference_stream` instead of full-buffer `inference` (lower time to first samples inside the WAV write). |

References: [Coqui XTTS docs](https://github.com/coqui-ai/TTS/blob/dev/docs/source/models/xtts.md), [HF DeepSpeed note](https://huggingface.co/coqui/XTTS-v2/discussions/10).

## Piper / ONNX (implemented)

- **`piper_cuda`** — CUDA execution provider when `onnxruntime-gpu` is installed.
- **`piper_onnx_cudnn_conv_algo_search`** — `heuristic` (matches stock Piper), `exhaustive`, or `default` for the CUDA EP (see [ONNX Runtime CUDA EP](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html)).
- **`piper_onnx_intra_op_num_threads`** / **`piper_onnx_inter_op_num_threads`** — optional ORT `SessionOptions` tuning.
- Implementation builds `onnxruntime.InferenceSession` manually (same pattern as upstream `PiperVoice.load`) and falls back to `PiperVoice.load` if construction fails.

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
