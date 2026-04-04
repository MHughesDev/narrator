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
| `rate` | float | `1.0` | Speaking rate (~0.5–3.0). |
| `volume` | float | `1.0` | Audio volume 0.0–1.0. |
| `beep_on_failure` | bool | `true` | Beep when capture finds no text (speak path). |
| `speak_exclude_hyperlinks` | bool | `true` | Remove markdown links / bare URLs before TTS. |
| `speak_exclude_math` | bool | `true` | Remove LaTeX-style and `$...$` math segments and Unicode math-alphanumeric letters before TTS. |
| `speak_exclude_markup` | bool | `true` | Remove fenced code, HTML tags / entities, markdown heading markers / `**`bold`**` / list bullets / `---` rules; strip `![alt](url)` and `[Image: …]`-style alt lines. |
| `speak_exclude_citations` | bool | `true` | Remove numeric bracket refs, markdown `[^n]`, and parenthetical author–year style citations. |
| `speak_exclude_technical` | bool | `true` | Remove UUIDs, `0x` hex words, long hex hashes, file paths (Windows/UNC/common Unix), and email addresses. |
| `speak_exclude_chrome` | bool | `true` | Remove “page *n* of *m*” snippets, line-leading Figure/Table labels, and dot-heavy TOC-style lines. |
| `speak_exclude_emoji` | bool | `true` | Remove emoji and most pictographic symbols (heuristic ranges). |
| `speak_insert_line_pauses` | bool | `true` | Enable structural pauses before TTS (paragraph breaks; optional line breaks — see `speak_pause_between_lines`). |
| `speak_pause_between_lines` | bool | `false` | **Standard:** `false` = pause only between **paragraphs** (blank-line blocks). `true` = also pause between **lines** within a block (comma / short SSML break). |
| `speak_winrt_use_ssml_breaks` | bool | `true` | WinRT only: use SSML millisecond breaks; if `false`, use the same plain insertion as neural engines. |
| `speak_pause_line_ms` | int | `320` | WinRT SSML pause between lines within a block (50–2000). |
| `speak_pause_paragraph_ms` | int | `520` | WinRT SSML pause between paragraph blocks (80–3000). |
| `speak_engine` | string | `auto` | `auto` prefers **Coqui XTTS** if `narrator[speak-xtts]` loads, else **Piper** when `narrator[speak-piper]` is installed and the ONNX voice exists, else **WinRT**. `piper`, `xtts`, or `winrt` force that engine (with fallbacks / warnings if deps or models are missing). |
| `piper_voice` | string | `en_US-ryan-high` | Piper voice id when using Piper (see `scripts/prefetch_piper_voice.py`, `python -m narrator --list-piper-voices`). |
| `piper_model_dir` | string | — | Directory containing `<voice>.onnx` and `.json`. |
| `piper_model_path` | string | — | Explicit path to a Piper `.onnx` file. |
| `piper_cuda` | bool | `false` | Use CUDA for Piper (requires GPU onnxruntime). |
| `xtts_model` | string | `tts_models/multilingual/multi-dataset/xtts_v2` | Used when `speak_engine` is `xtts`. |
| `xtts_speaker` | string | `Ana Florence` | Default Coqui speaker if `voice` is unset. |
| `xtts_language` | string | `en` | XTTS language code. |
| `xtts_device` | string | `auto` | `auto`, `cpu`, or `cuda`. |
| `xtts_speaker_wav` | string | — | Optional reference WAV for voice cloning (overrides speaker / voice). |
| `live_rate_resume_slack_ms` | float | `280` | Extra milliseconds of PCM skipped ahead after `waveOutGetPosition` when using **sample-accurate** seek (chunk discard off). Ignored when chunk discard is on. |
| `post_waveout_close_drain_s` | float | `0.35` | Seconds to sleep after `waveOutClose` before reopening the device on live rate change. |
| `live_rate_safe_chunk_discard` | bool | `true` | **Recommended default:** resume at the **next** chunk boundary (do not use `waveOutGetPosition` for the cut) — avoids echo when the driver lags the DAC. Set `false` for sample-accurate seek (smaller gaps; may echo). Env: `NARRATOR_LIVE_RATE_ACCURATE_SEEK=1` forces accurate seek; `NARRATOR_LIVE_RATE_SAFE=1` forces chunk discard. |
| `live_rate_defer_during_playback` | bool | `false` | If `true`, **Ctrl+Alt+Plus/Minus** only changes rate for the **next** speak (no in-play handoff). Env: `NARRATOR_LIVE_RATE_DEFER=1` / `=0`. |
| `live_rate_in_play_engine` | string | `wsola` | When defer is `false`: **`wsola`** = pitch-preserving WSOLA (audiotsm, default); **`phase_vocoder`** = librosa (may chorus); **`resample`** = tape-speed (pitch shifts). Env: `NARRATOR_LIVE_RATE_ENGINE`, legacy `NARRATOR_LIVE_RATE_PHASE_VOCODER=1` → `phase_vocoder`. |

CLI overrides: `--speak-hotkey`, `--listen-hotkey`, `--hotkey` (deprecated alias for `--speak-hotkey`), `--speak-engine`, `--no-speak-exclude-hyperlinks`, `--no-speak-exclude-math`, `--no-speak-exclude-markup`, `--no-speak-exclude-citations`, `--no-speak-exclude-technical`, `--no-speak-exclude-chrome`, `--no-speak-exclude-emoji`, `--no-speak-insert-line-pauses`, `--speak-pause-between-lines`, `--no-speak-winrt-ssml-breaks`, `--speak-pause-line-ms`, `--speak-pause-paragraph-ms`, `--piper-voice`, `--piper-model-dir`, `--piper-model`, `--piper-cuda`, `--xtts-model`, `--xtts-speaker`, `--xtts-language`, `--xtts-device`, `--xtts-speaker-wav`.
