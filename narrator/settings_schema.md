# Config TOML keys (reference)

**Product defaults:** **Ctrl+Alt+S** = speak (TTS from hover), **Ctrl+Alt+L** = listen (STT into focused field). Override with the keys below or with `--speak-hotkey` / `--listen-hotkey`.

**Independence:** Changing or using `speak_hotkey` / `listen_hotkey` does not tie the features together — speak and listen remain **separate** pipelines; see [`SPEC.md`](../SPEC.md) §5.

Files are merged in order; later files override earlier keys. Standard paths: `%USERPROFILE%\.config\narrator\config.toml`, then `%LOCALAPPDATA%\narrator\config.toml`, then `--config`.

**Standard speak profile (product defaults):** all `speak_exclude_*` are **`true`**, and prosody is **paragraph-only** pauses (`speak_pause_between_lines = false`) with `speak_insert_line_pauses = true`.

| Key | Type | Default | Notes |
|-----|------|---------|--------|
| `speak_hotkey` | string | `ctrl+alt+s` | Toggle hover-and-speak (TTS). |
| `listen_hotkey` | string | `ctrl+alt+l` | Toggle speech-to-text into the focused field. |
| `hotkey` | string | — | **Deprecated.** Treated as `speak_hotkey` if `speak_hotkey` is unset; a deprecation warning is emitted. |
| `voice` | string | — | WinRT: SSML / display name. XTTS: built-in speaker name (see `--list-xtts-speakers`) or omit for `xtts_speaker`. |
| `rate` | float | `1.0` | **Ignored** — speaking tempo is fixed at **1.0** (no `rate` / `--rate` / hotkeys for now). |
| `volume` | float | `1.0` | Audio volume 0.0–1.0. |
| `beep_on_failure` | bool | `true` | Beep when capture finds no text (speak path). |
| `speak_exclude_hyperlinks` | bool | `true` | Remove markdown links / bare URLs before TTS. |
| `speak_exclude_math` | bool | `true` | Remove **entire** math: LaTeX display/AMS environments, `$$…$$`, `\[…\]`, `\(...\)`, inline `$…$` (except currency-like amounts), MathML/`<semantics>`, `tikzpicture`, Unicode math letters (U+1D400–1D7FF) and operator/symbol blocks (e.g. ∑, ∀, ∈). |
| `speak_exclude_markup` | bool | `true` | Remove fenced code, HTML tags / entities, markdown heading markers / `**`bold`**` / list bullets / `---` rules; strip `![alt](url)` and `[Image: …]`-style alt lines. |
| `speak_exclude_citations` | bool | `true` | Remove numeric bracket refs, markdown `[^n]`, and parenthetical author–year style citations. |
| `speak_exclude_technical` | bool | `true` | Remove UUIDs, `0x` hex words, long hex hashes, file paths (Windows/UNC/common Unix), and email addresses. |
| `speak_exclude_chrome` | bool | `true` | Remove “page *n* of *m*” snippets, line-leading Figure/Table labels, and dot-heavy TOC-style lines. |
| `speak_exclude_emoji` | bool | `true` | Remove emoji and most pictographic symbols (heuristic ranges). |
| `speak_expand_tech_abbreviations` | bool | `true` | Expand common tech acronyms to spaced letters (e.g. LLM, CLI) so TTS pronounces them clearly. Env: `NARRATOR_SPEAK_EXPAND_TECH_ABBREVIATIONS`. |
| `speak_strip_arxiv_metadata` | bool | `true` | Drop lines that look like arXiv headers (id + “arxiv”, or `arxiv.org/abs|pdf/…`). Env: `NARRATOR_SPEAK_STRIP_ARXIV_METADATA`. |
| `speak_strip_toc_leader_lines` | bool | `true` | Remove dot-leader table-of-contents lines. Env: `NARRATOR_SPEAK_STRIP_TOC_LEADER_LINES`. |
| `speak_strip_contents_pages` | bool | `true` | Drop paragraphs that look like a contents page (heading + mostly dot-leader lines). Env: `NARRATOR_SPEAK_STRIP_CONTENTS_PAGES`. |
| `speak_strip_figure_legend_lines` | bool | `true` | Remove lines that look like figure colour legends (`LLMs (Blue)`), lone years, or pipe-separated year rows from PDF figure dumps. Env: `NARRATOR_SPEAK_STRIP_FIGURE_LEGEND_LINES`. |
| `speak_collapse_long_name_lists` | bool | `true` | Replace comma-separated author-like lists longer than `speak_long_name_list_max` with **see names** (skips `{id}@` / university affiliation blocks). Env: `NARRATOR_SPEAK_COLLAPSE_LONG_NAME_LISTS`. |
| `speak_long_name_list_max` | int | `4` | Max comma-separated “Given Surname” segments before collapse. Env: `NARRATOR_SPEAK_LONG_NAME_LIST_MAX`. |
| `speak_start_at_abstract` | bool | `true` | Drop everything before the first **Abstract** section (title, author list, affiliation / contact lines typical in papers). Set `false` if you need the full capture spoken. Env: `NARRATOR_SPEAK_START_AT_ABSTRACT`. |
| `speak_insert_line_pauses` | bool | `true` | Enable structural pauses before TTS (paragraph breaks; optional line breaks — see `speak_pause_between_lines`). |
| `speak_pause_between_lines` | bool | `false` | **Standard:** `false` = pause only between **paragraphs** (blank-line blocks). `true` = also pause between **lines** within a block (comma / short SSML break). |
| `speak_winrt_use_ssml_breaks` | bool | `true` | WinRT only: use SSML millisecond breaks; if `false`, use the same plain insertion as neural engines. |
| `speak_pause_line_ms` | int | `320` | WinRT SSML pause between lines within a block (50–2000). |
| `speak_pause_paragraph_ms` | int | `520` | WinRT SSML pause between paragraph blocks (80–3000). |
| `speak_chunk_context_enabled` | bool | `true` | Prepend the tail of the **previous** chunk to the next synthesis for smoother prosody (WinRT, Piper, XTTS); trim duplicated audio via `speak_chunk_context_trim_mode`. Env: `NARRATOR_SPEAK_CHUNK_CONTEXT_ENABLED`. |
| `speak_chunk_context_max_chars` | int | `120` | Max characters of prior chunk to use as context (20–500). Env: `NARRATOR_SPEAK_CHUNK_CONTEXT_MAX_CHARS`. |
| `speak_chunk_context_trim_mode` | string | `fixed_ms` | **`fixed_ms`** (default) = trim `speak_chunk_context_trim_ms` from the start of the synthesized WAV (fast; avoids a second XTTS call per segment). **`duration_probe`** = synthesize context-only audio to measure trim (slower, sometimes more accurate). Env: `NARRATOR_SPEAK_CHUNK_CONTEXT_TRIM_MODE`. |
| `speak_chunk_context_trim_ms` | float | `400` | Used when `speak_chunk_context_trim_mode` = `fixed_ms`. Env: `NARRATOR_SPEAK_CHUNK_CONTEXT_TRIM_MS`. |
| `speak_preprocess_streaming` | bool | `true` | Large captures: preprocess only an initial **paragraph-bounded** bundle first; the rest runs in a background thread so the first TTS chunk can start sooner. Env: `NARRATOR_SPEAK_PREPROCESS_STREAMING`. |
| `speak_preprocess_initial_chunks` | int | `3` | Rough number of TTS-chunk lengths of raw text in the first bundle (with a minimum raw-char floor in code). Env: `NARRATOR_SPEAK_PREPROCESS_INITIAL_CHUNKS`. |
| `speak_audio_stream_compile` | bool | `false` | **Off** (default): prefetch segments while playing — lower **time to first speech** (VoxCPM-like streaming). **On**: merge all segment WAVs into one PCM clip before playback — smoother single-pass playback, higher latency before audio starts. Env: `NARRATOR_SPEAK_AUDIO_STREAM_COMPILE`. See [`docs/VOXCPM_LATENCY.md`](../docs/VOXCPM_LATENCY.md). |
| `speak_warmup_on_start` | bool | `true` | Background thread loads Piper/XTTS after startup (VoxCPM-style post-load warmup). WinRT skipped. Env: `NARRATOR_SPEAK_WARMUP_ON_START`. |
| `speak_warmup_synthesize` | bool | `true` | If `true`, warmup also runs a tiny synthesis (“Hi.”) so first hotkey avoids worst cold inference. If `false`, load only. Env: `NARRATOR_SPEAK_WARMUP_SYNTHESIZE`. |
| `speak_text_llm_enabled` | bool | `false` | LLM text-ready pass toggle. By default neural engines (Piper/XTTS) force this on; set `speak_text_llm_force_for_neural = false` to allow disabling for speed tests. See [`docs/SPEAK_TEXT_LLM.md`](../docs/SPEAK_TEXT_LLM.md). Env: `NARRATOR_SPEAK_TEXT_LLM_ENABLED`. |
| `speak_text_llm_force_for_neural` | bool | `true` | Keep default behavior that Piper/XTTS force LLM cleanup on. Set `false` to allow neural engines to run with LLM disabled (lower latency / throughput benchmarking). Env: `NARRATOR_SPEAK_TEXT_LLM_FORCE_NEURAL`. |
| `speak_text_llm_base_url` | string | `http://127.0.0.1:11434/v1` | API root (Ollama/LM Studio). Env: `NARRATOR_SPEAK_TEXT_LLM_BASE_URL`. |
| `speak_text_llm_model` | string | `""` | Model id; **Piper/XTTS** default **`llama3.2:1b`** when empty. Env: `NARRATOR_SPEAK_TEXT_LLM_MODEL`. |
| `speak_text_llm_api_key` | string | — | Optional `Authorization` bearer. Env: `NARRATOR_SPEAK_TEXT_LLM_API_KEY`. |
| `speak_text_llm_timeout_s` | float | `120` | Per-chunk HTTP timeout. Env: `NARRATOR_SPEAK_TEXT_LLM_TIMEOUT_S`. |
| `speak_text_llm_max_chunk_chars` | int | `6000` | Max chars per TTS chunk body embedded in a bundle (truncate before the LLM). |
| `speak_text_llm_bundle_chunks` | int | `1` | TTS chunks per LLM request. **`1`** (default) avoids `<<<CHUNK>>>` parsing issues with small models (`llama3.2:1b`). Use **`2`–`4`** with larger models that follow bundle delimiters (TOC context). |
| `speak_text_llm_bundle_max_chars` | int | `16000` | Soft cap on total characters per bundled request (sum of chunk bodies after `max_chunk_chars`). |
| `speak_text_llm_mode` | string | `heuristic_then_llm` | `heuristic_then_llm` or `llm_primary` (minimal strip, then LLM). Env: `NARRATOR_SPEAK_TEXT_LLM_MODE`. |
| `speak_text_llm_rules` | string | `""` | Extra rules text (inline), appended after the builtin file. |
| `speak_text_llm_rules_file` | string | — | UTF-8 file merged into the system prompt (after builtin + inline). |
| `speak_text_llm_builtin_rules` | bool | `true` | If `true`, prepend [`narrator/default_speak_text_llm_rules.txt`](../narrator/default_speak_text_llm_rules.txt) to RULES. Set `false` for a fully custom `speak_text_llm_rules_file` (e.g. with `llm_primary`). Env: `NARRATOR_SPEAK_TEXT_LLM_BUILTIN_RULES`. |
| `speak_synth_max_ahead` | int | `0` | If `>0`, prefetch queue depth uses this (capped 512); else `speak_prefetch_depth`. Env: `NARRATOR_SPEAK_SYNTH_MAX_AHEAD`. |
| `speak_synth_worker_threads` | int | `1` | Parallel synthesis workers for segments 1…n−1 (keep `1` for XTTS/GPU). Env: `NARRATOR_SPEAK_SYNTH_WORKER_THREADS`. |
| `speak_keep_wav_in_memory` | bool | `false` | Keep prefetched segments as WAV bytes in RAM instead of temp files. Env: `NARRATOR_SPEAK_KEEP_WAV_IN_MEMORY`. |
| `speak_engine` | string | `auto` | `auto` prefers **Coqui XTTS** if `narrator[speak-xtts]` loads, else **Piper** when `narrator[speak-piper]` is installed and the ONNX voice exists, else **WinRT**. `piper`, `xtts`, or `winrt` force that engine (with fallbacks / warnings if deps or models are missing). |
| `piper_voice` | string | `en_US-ryan-high` | Piper voice id when using Piper (see `scripts/prefetch_piper_voice.py`, `python -m narrator --list-piper-voices`). |
| `piper_model_dir` | string | — | Directory containing `<voice>.onnx` and `.json`. |
| `piper_model_path` | string | — | Explicit path to a Piper `.onnx` file. |
| `piper_cuda` | bool | `false` | Use CUDA for Piper (requires GPU onnxruntime). |
| `xtts_model` | string | `tts_models/multilingual/multi-dataset/xtts_v1.1` | Used when `speak_engine` is `xtts`. **`v1.1`** has no built-in names — Narrator uses **`xtts_speaker_wav`** or a **Piper-generated ref**; **`xtts_v2`** supports names like Ana Florence. |
| `xtts_speaker` | string | `Ana Florence` | Default Coqui **v2** speaker if `voice` is unset (ignored for **v1.1** without built-in list). |
| `xtts_language` | string | `en` | XTTS language code. |
| `xtts_device` | string | `auto` | `auto`, `cpu`, or `cuda`. |
| `xtts_speaker_wav` | string | — | Optional reference WAV for voice cloning (overrides speaker / voice). |
| `xtts_split_sentences` | bool | `false` | Coqui: when `true`, splits each chunk into sentences and synthesizes separately (more round-trips, often **slower**). Default **false** — Narrator already chunks long text; use `true` only if you hit model length limits. Env: `NARRATOR_XTTS_SPLIT_SENTENCES`. |
| `xtts_torch_inference_mode` | bool | `true` | Wrap XTTS `tts_to_file` in ``torch.inference_mode()`` when PyTorch is available. Env: `NARRATOR_XTTS_TORCH_INFERENCE_MODE`. |
| `live_rate_resume_slack_ms` | float | `280` | Extra milliseconds of PCM skipped ahead after `waveOutGetPosition` when using **sample-accurate** seek (chunk discard off). Ignored when chunk discard is on. |
| `post_waveout_close_drain_s` | float | `0.35` | Seconds to sleep after `waveOutClose` before reopening the device on live rate change. |
| `live_rate_safe_chunk_discard` | bool | `true` | **Recommended default:** resume at the **next** chunk boundary (do not use `waveOutGetPosition` for the cut) — avoids echo when the driver lags the DAC. Set `false` for sample-accurate seek (smaller gaps; may echo). Env: `NARRATOR_LIVE_RATE_ACCURATE_SEEK=1` forces accurate seek; `NARRATOR_LIVE_RATE_SAFE=1` forces chunk discard. |
| `live_rate_defer_during_playback` | bool | `false` | If `true`, **Ctrl+Alt+Plus/Minus** only changes rate for the **next** speak (no in-play handoff). Env: `NARRATOR_LIVE_RATE_DEFER=1` / `=0`. |
| `live_rate_in_play_engine` | string | `wsola` | When defer is `false`: **`wsola`** = pitch-preserving WSOLA (audiotsm, default); **`phase_vocoder`** = librosa (may chorus); **`resample`** = tape-speed (pitch shifts). Env: `NARRATOR_LIVE_RATE_ENGINE`, legacy `NARRATOR_LIVE_RATE_PHASE_VOCODER=1` → `phase_vocoder`. |
| `pcm_edge_fade_ms` | float | `8` | Linear fade-in at clip start and fade-out at clip end (16-bit PCM). Used when `segment_transition_preset = custom`; **engine** preset uses per-route values. `0` disables. Env: `NARRATOR_PCM_EDGE_FADE_MS`. |
| `live_rate_settle_ms` | float | `45` | After a rate hotkey, wait this long (reset on each extra hotkey) before handoff so bursts collapse to one stretch. `0` disables. Env: `NARRATOR_LIVE_RATE_SETTLE_MS`. |
| `live_rate_extreme_ratio_threshold` | float | `1.12` | If `max(ratio,1/ratio)` exceeds this during in-play handoff, **`resample`** is used for that tail instead of WSOLA/phase-vocoder. Set very high to always use `live_rate_in_play_engine`. Env: `NARRATOR_LIVE_RATE_EXTREME_RATIO`. |
| `live_rate_min_handoff_interval_s` | float | `0` | Minimum seconds between in-play handoff starts (spins the event queue while waiting). `0` = off. Env: `NARRATOR_LIVE_RATE_MIN_HANDOFF_S`. |
| `live_rate_resynth_remainder` | bool | `true` | If `true`, live rate change **re-synthesizes** unread text at the new rate (worker) instead of WSOLA on the tail. Env: `NARRATOR_LIVE_RATE_RESYNTH` (`0`/`1`). |
| `live_rate_resynth_min_remainder_chars` | int | `12` | Minimum remainder length to trigger re-synthesis. |
| `post_reset_silence_ms` | float | `12` | Lead silence prepended to the stretched tail after device reset (smoother live-rate handoff). |
| `pcm_peak_normalize` | bool | `true` | Peak-normalize 16-bit PCM before edge fades (used when `segment_transition_preset = custom`; **engine** preset also normalizes). |
| `pcm_peak_normalize_level` | float | `0.92` | Target peak (fraction of full scale). |
| `speak_voice_clean_enabled` | bool | `false` | Optional **high-pass** (rumble / DC) before peak normalize — see [`docs/TTS_VOICE_CLEANING.md`](../docs/TTS_VOICE_CLEANING.md). Env: `NARRATOR_SPEAK_VOICE_CLEAN_ENABLED`. |
| `speak_voice_clean_highpass_hz` | float | `72` | High-pass corner frequency (Hz); keep ~60–120 for speech. Env: `NARRATOR_SPEAK_VOICE_CLEAN_HIGHPASS_HZ`. |
| `segment_crossfade_ms` | float | `24` | Overlap-add crossfade (ms). Used when `segment_transition_preset = custom`; **engine** uses higher per-route values. |
| `segment_transition_preset` | string | `engine` | **`engine`**: smoothest per-route defaults (WinRT / Piper / XTTS). **`custom`**: use the `pcm_*` / `segment_crossfade_ms` columns. **`minimal`**: lighter than **engine** but still crossfaded + normalized. Env: `NARRATOR_SEGMENT_TRANSITION_PRESET`. |
| `audio_output_backend` | string | `waveout` | `waveout` (winmm) or `sounddevice` (PortAudio; in-play stretch deferred). Env: `NARRATOR_AUDIO_BACKEND`. |

CLI overrides: `--speak-hotkey`, `--listen-hotkey`, `--hotkey` (deprecated alias for `--speak-hotkey`), `--speak-engine`, `--no-speak-exclude-hyperlinks`, `--no-speak-exclude-math`, `--no-speak-exclude-markup`, `--no-speak-exclude-citations`, `--no-speak-exclude-technical`, `--no-speak-exclude-chrome`, `--no-speak-exclude-emoji`, `--no-speak-insert-line-pauses`, `--speak-pause-between-lines`, `--no-speak-winrt-ssml-breaks`, `--speak-pause-line-ms`, `--speak-pause-paragraph-ms`, `--piper-voice`, `--piper-model-dir`, `--piper-model`, `--piper-cuda`, `--xtts-model`, `--xtts-speaker`, `--xtts-language`, `--xtts-device`, `--xtts-speaker-wav`.
