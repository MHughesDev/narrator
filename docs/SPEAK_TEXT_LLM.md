# Local LLM text readying (speak)

**OpenAI-compatible** HTTP endpoint (Ollama, LM Studio, vLLM, etc.) refines each **chunk** after heuristic preprocessing so TTS hears cleaner prose. Implemented in [`narrator/speak_text_llm.py`](../narrator/speak_text_llm.py) and wired in [`narrator/worker.py`](../narrator/worker.py).

**Piper** and **XTTS** default to this pass: [`build_runtime_settings`](../narrator/settings.py) enables `speak_text_llm_enabled` and defaults `speak_text_llm_model` to **`llama3.2:1b`** when unset.  
For latency-focused runs, set `speak_text_llm_force_for_neural = false` (or env `NARRATOR_SPEAK_TEXT_LLM_FORCE_NEURAL=0`) to allow disabling LLM cleanup for neural engines. **WinRT** remains opt-in via config. Neural **`setup.bat`** runs [`scripts/setup_ollama_speak_llm.py`](../scripts/setup_ollama_speak_llm.py) to install Ollama (winget) and pull that model.

Each request’s system prompt includes a **CONSTRAINTS** block (from [`speak_text_llm.py`](../narrator/speak_text_llm.py)) with `speak_engine`, `speak_text_llm_mode`, TTS segment caps, and bundle limits, **before** the **RULES** section (builtin file + inline + optional file). Small models see hard pipeline limits explicitly.

## Settings

| Key | Default | Notes |
|-----|---------|--------|
| `speak_text_llm_enabled` | `false` (default **on** for Piper/XTTS) | WinRT: opt-in via config/env. For Piper/XTTS this is auto-enabled unless `speak_text_llm_force_for_neural = false`. |
| `speak_text_llm_base_url` | `http://127.0.0.1:11434/v1` | Root or `/v1` base. Env: `NARRATOR_SPEAK_TEXT_LLM_BASE_URL`. |
| `speak_text_llm_model` | `""` (**`llama3.2:1b`** for Piper/XTTS if empty) | e.g. `llama3.2:1b` or `llama3.2`. Env: `NARRATOR_SPEAK_TEXT_LLM_MODEL`. |
| `speak_text_llm_api_key` | — | Optional; often empty for Ollama. Env: `NARRATOR_SPEAK_TEXT_LLM_API_KEY`. |
| `speak_text_llm_timeout_s` | `120` | Per-chunk HTTP timeout. Env: `NARRATOR_SPEAK_TEXT_LLM_TIMEOUT_S`. |
| `speak_text_llm_max_chunk_chars` | `6000` | Truncate each TTS-chunk body before wrapping in a bundle. |
| `speak_text_llm_bundle_chunks` | `1` | Chunks per LLM request. Default **`1`** — one request per segment, no bundle markers (works with **`llama3.2:1b`**). Set **`2`–`4`** if your model reliably returns matching `<<<CHUNK n>>>` / `<<<END>>>` blocks (more TOC context). |
| `speak_text_llm_bundle_max_chars` | `16000` | Stop adding chunks to a bundle when the total would exceed this (allows many small XTTS segments in one request). |
| `speak_text_llm_force_for_neural` | `true` | Keep neural engines (Piper/XTTS) on LLM cleanup by default. Set `false` for lower latency / throughput benchmarks. Env: `NARRATOR_SPEAK_TEXT_LLM_FORCE_NEURAL`. |
| `speak_text_llm_mode` | `heuristic_then_llm` | `llm_primary` = minimal strip only, then LLM (rules must cover exclusions). |
| `speak_text_llm_builtin_rules` | `true` | Prepend the packaged [`narrator/default_speak_text_llm_rules.txt`](../narrator/default_speak_text_llm_rules.txt) to the `RULES` block (editorial policy for TTS: boilerplate, tables, cites, symbols, abbrevs, `see names`, `llm_primary`, etc.). Set `false` if you supply a fully custom `speak_text_llm_rules_file`. Env: `NARRATOR_SPEAK_TEXT_LLM_BUILTIN_RULES`. |
| `speak_text_llm_rules` | `""` | Extra rules (inline), appended after the builtin file. |
| `speak_text_llm_rules_file` | — | UTF-8 file appended after builtin + inline. |

## Builtin rules (default)

The **builtin** rules file is always merged first when `speak_text_llm_builtin_rules` is true. It is dense and avoids overlapping the short **structural** system strings in code (`output shape`, `<<<CHUNK>>>` discipline). Editorial highlights:

- **Heuristic-safe:** do not undo `see names` or spaced acronyms (`L L M`).
- **Tables / numeric dumps:** output an **empty** wrapper — no summarization or invented numbers.
- **Citations / noise:** strip leftovers (e.g. ibid., “see p.”, footnote markers) without adding sources.
- **`llm_primary`:** same file tells the model to perform the heavy exclusions when heuristics are off.

To customize: copy `default_speak_text_llm_rules.txt`, edit, point `speak_text_llm_rules_file` at your copy, and set `speak_text_llm_builtin_rules = false` if you want **only** your file (plus optional inline `speak_text_llm_rules`).

## Modes

- **`heuristic_then_llm`** (default): Full [`prepare_speak_text`](../narrator/speak_preprocess.py) pipeline, chunk, then each chunk is sent to the LLM.
- **`llm_primary`**: Only invisible-character strip + hyphen normalization, then chunk + LLM. Use a detailed **rules** file so the model drops math, links, name lists, etc.

## Bundled chunks (TOC / structure)

By default **`speak_text_llm_bundle_chunks = 1`**: each TTS segment is sent in its **own** LLM request (no `<<<CHUNK>>>` wrappers in the reply). That matches small models like **`llama3.2:1b`**, which rarely format multi-chunk bundles correctly. If you use a **larger** local model, you can set **`2`–`4`** so several consecutive segments are sent in one request; the model must return the **same** `<<<CHUNK n>>>`…`<<<END>>>` structure. With **XTTS**, segments are ~240 characters each; adjust `speak_text_llm_bundle_max_chars` when bundling.

## Time to first audio

The **first bundle** is LLM-processed before the first synthesis (with `speak_text_llm_bundle_chunks` > 1, that is several TTS segments in one call). **Later** bundles run **in parallel** (background thread) while earlier audio may already be playing.

## Synthesis pipeline

- **`speak_prefetch_depth`** / **`speak_synth_max_ahead`**: If `speak_synth_max_ahead > 0`, the prefetch queue uses that cap (up to 512); otherwise `speak_prefetch_depth` is used.
- **`speak_synth_worker_threads`**: For non-streaming document builds, synthesize segment 1…n−1 in parallel (up to this many workers). **XTTS / GPU**: keep `1` to avoid VRAM issues; WinRT/Piper may use `2` on CPU.
- **`speak_keep_wav_in_memory`**: Keep each prefetched segment as WAV **bytes** in RAM instead of a temp file path (higher RAM use).

## Failure behavior

If the LLM request fails or returns empty text, the **heuristic chunk** is used. **WinRT:** a warning is logged. **Piper / XTTS:** an **error** is logged (Ollama should be running and the model pulled — rerun setup or `ollama pull llama3.2:1b`).
