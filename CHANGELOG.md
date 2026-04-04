# Changelog

## 0.3.9

- **Live rate (Ctrl+Alt+Plus/Minus):** Default **`live_rate_in_play_engine = "wsola"`** (audiotsm: pitch-preserving in-play tempo; no tape-speed pitch shift). Alternatives: **`phase_vocoder`** (librosa), **`resample`**. Dependency: **`audiotsm`**. Setting **`live_rate_in_play_use_phase_vocoder`** in old configs still maps to **`phase_vocoder`**. Next-utterance-only: **`live_rate_defer_during_playback`**. Helpers: **`apply_live_in_play_tempo`**, **`tempo_change_wsola_int16_interleaved`** in [`narrator/wav_speaking_rate.py`](narrator/wav_speaking_rate.py).
- **Live rate handoff:** ``waveOutOpen`` after a speed change is retried with backoff; an empty remainder no longer forces a bogus reopen. Failures log tuning hints for ``post_waveout_close_drain_s`` / ``NARRATOR_POST_WAVEOUT_CLOSE_DRAIN_S`` (avoids treating a failed reopen like ``SPEAK_TOGGLE`` and skipping the rest of a long document).
- **Live rate quality:** Speed changes wait for the current ``waveOut`` buffer to finish before reset/stretch (avoids mid-word cuts / stutter). PCM chunks capped at **64 KiB** per buffer; WSOLA uses **2048-sample** frames for smoother speech.

- **Setup (Windows):** [`setup.bat`](setup.bat) calls [`scripts/bootstrap_install.py`](scripts/bootstrap_install.py) with **`--auto`**, using [`scripts/hw_detect.py`](scripts/hw_detect.py) (`nvidia-smi` when available) to pick **`neural-gpu`** (install neural extras, then **CUDA** `torch`/`torchaudio` from the **`cu124`** wheel index) vs **`neural-cpu`**. Overrides: **`NARRATOR_SETUP_PROFILE`** (`minimal` / `neural-cpu` / `neural-gpu`), **`NARRATOR_TORCH_CUDA_INDEX`**, bootstrap flags **`--dry-run`**, **`--skip-prefetch`**, **`--force-cuda`**. Docs: [`docs/SETUP.md`](docs/SETUP.md), [`docs/REPO_LAYOUT.md`](docs/REPO_LAYOUT.md). [`CONTRIBUTING.md`](CONTRIBUTING.md) for contributors. [`setup.sh`](setup.sh) only prints that the runtime targets Windows.

- **Audio loopback self-test (optional):** [`pip install -e ".[audio-test]"`](pyproject.toml) adds **`sounddevice`**. [`run_audio_selftest.bat`](run_audio_selftest.bat) records the default mic to **`audio_selftest_logs/`**, then runs [`scripts/analyze_audio_recordings.py`](scripts/analyze_audio_recordings.py) (echo / overlap heuristics from WAV). Optional **`--openai`** + **`OPENAI_API_KEY`** + **`pip install openai`** sends **numeric metrics only** to the API for a short interpretation. See [`docs/AUDIO_SELFTEST.md`](docs/AUDIO_SELFTEST.md).

## 0.3.8

- **Standard speak profile** is the default: all **`speak_exclude_*`** remain **`true`**, and prosody is **paragraph-only** — pauses between blank-line-separated blocks, not after every single newline (`speak_pause_between_lines = false`). Opt into line-level pauses with `speak_pause_between_lines = true` or **`--speak-pause-between-lines`**. WinRT SSML uses paragraph breaks only unless line pauses are enabled.
- **Piper speaking rate:** Tempo is applied with Piper **`length_scale`** during synthesis instead of librosa **whole-file** time stretch, so changing rate no longer adds a persistent “chorus” on every following utterance. WinRT / XTTS still use ``wav_speaking_rate`` librosa when ``speaking_rate ≠ 1``.

- **Live rate:** Optional **`live_rate_defer_during_playback`** / **`NARRATOR_LIVE_RATE_DEFER=1`** — rate hotkeys update the **next** utterance only (no librosa stretch during playback), avoiding phase-vocoder chorus artifacts.

- **Debug:** `NARRATOR_DEBUG_AUDIO=1` logs `playback_gate`, `waveOut` open/close/reset/write, PCM stats, librosa live stretch, worker/speech play boundaries; see **`docs/DEBUG_MULTIPLE_VOICES.md`**.

- **Live speaking-rate playback (Ctrl+Alt+Plus/Minus):** Default **chunk-boundary resume** (skip the rest of the current buffer) so **`waveOutGetPosition` is not the sole cut point**—it often lags the DAC and caused stacked/echo speech. Optional **sample-accurate** seek via `live_rate_safe_chunk_discard = false` or **`NARRATOR_LIVE_RATE_ACCURATE_SEEK=1`** (uses position + higher default slack/drain). Safer fallbacks when position fails or is out of range; **8-bit** mono PCM tails converted for live stretch. Tunables TOML / env (`NARRATOR_LIVE_RATE_*`). **`NARRATOR_DEBUG_LIVE_RATE`** logs `raw_waveout_cb`, offset, `accurate_seek`. Unit tests: `tests/test_wav_play_win32.py`. Docs: README, ARCHITECTURE §4.4.

## 0.3.7

- **Speak prosody** ([`narrator/speak_prosody.py`](narrator/speak_prosody.py)): optional pauses between **lines** (single newline) and **paragraphs** (blank line). **Piper / XTTS** insert `, ` between lines and `. ` between paragraph blocks. **WinRT** uses SSML ``<break time="…ms"/>`` (defaults **320 ms** line / **520 ms** paragraph; configurable). Disable with `speak_insert_line_pauses = false` or `--no-speak-insert-line-pauses`; WinRT plain pauses with `--no-speak-winrt-ssml-breaks`.

## 0.3.6

- **Speak preprocessing** expanded ([`narrator/speak_preprocess.py`](narrator/speak_preprocess.py)): optional stripping of **markup** (fenced code, HTML tags/entities, markdown headings / bold markers / list bullets / horizontal rules; markdown images and `[Image: …]` patterns), **citations** (bracket numbers, `[^footnotes]`, parenthetical author–year), **technical tokens** (UUID, `0x` hex, long hashes, Windows/UNC/Unix paths, emails), **document chrome** (“page *n* of *m*”, figure/table line prefixes, dot-heavy TOC lines), and **emoji** (broad Unicode ranges). Invisible characters (BOM, zero-width, bidi controls) are always removed. Each group can be disabled via TOML or `--no-speak-exclude-*` flags.

## 0.3.5

- **Speak preprocessing** ([`narrator/speak_preprocess.py`](narrator/speak_preprocess.py)): optional removal of **hyperlinks** (markdown `[text](url)`, bare URLs, `www.`, `mailto:`) and **math** (`$$…$$`, `\[…\]`, `\(…\)`, common `\begin{equation}`-style blocks, inline `$…$` except simple currency-like `$3.50`, and Unicode mathematical alphanumeric symbols). Defaults **on**; disable with `speak_exclude_hyperlinks = false` / `speak_exclude_math = false` in TOML or `--no-speak-exclude-hyperlinks` / `--no-speak-exclude-math` on the CLI.

## 0.3.4

- **`speak_engine = auto`** now prefers **Coqui XTTS** first (when `narrator[speak-xtts]` loads), then **Piper** if an ONNX voice is on disk, then **WinRT**. Docs and CLI help updated.

## 0.3.3

- **Default Piper voice** is **`en_US-ryan-high`** (clearer than `en_US-lessac-medium`); constant **`DEFAULT_PIPER_VOICE_ID`** in [`narrator/tts_piper.py`](narrator/tts_piper.py).
- **`setup.bat`** installs **`[speak-xtts,speak-piper]`** and runs **`scripts/prefetch_piper_voice.py`** after XTTS prefetch.
- **Docs:** README, [`docs/SETUP.md`](docs/SETUP.md), [`ARCHITECTURE.md`](ARCHITECTURE.md), [`narrator/settings_schema.md`](narrator/settings_schema.md) — Piper defaults and config examples updated. *(Auto order changed to XTTS-first in **0.3.4**.)*
- **[`config.example.toml`](config.example.toml)** documents **`piper_voice`** alongside XTTS keys.

## 0.3.2

- **[`docs/SETUP.md`](docs/SETUP.md)** — full Windows setup: what **`setup.bat`** installs (PyTorch, Coqui, WinRT, prefetch), manual steps, **`verify_setup`**, GPU notes.
- **[`scripts/verify_setup.py`](scripts/verify_setup.py)** — checks WinRT / UIA / PyTorch / Coqui imports; **`setup.bat`** runs it after **`pip install`**.
- **[`setup.bat`](setup.bat)** — **`ensurepip`**, upgrade **pip/setuptools/wheel**, then install, **verify**, **prefetch**.
- **`speak-xtts`** extra now lists **`torch>=2.0.0`** explicitly alongside **`coqui-tts`**.
- **`is_xtts_available()`** catches any import error (including broken PyTorch DLLs) so **`speak_engine=auto`** still falls back to WinRT.
- **[`README.md`](README.md)** — top “full stack” blurb, requirements, helper table, docs index link to **SETUP**.

## 0.2.1

- **[`setup.bat`](setup.bat):** tries the Windows **`py`** launcher when **`python`** is not on `PATH`; clearer errors + **`winget install Python.Python.3.12`** hint. README quick start documents **winget** and `py` behavior.
- **Documented product rule:** speak and listen are **independent** — separate queues and workers; **no cross-cancellation**; **simultaneous** use is allowed ([`SPEC.md`](SPEC.md) §5, [`ARCHITECTURE.md`](ARCHITECTURE.md) §5, [`narrator/protocol.py`](narrator/protocol.py)).
- [`TESTING.md`](TESTING.md): matrix for **speak + listen at the same time**.
- **[`.gitignore`](.gitignore)** added for `*.egg-info/`, `.venv/`, `dist/`, `build/`, and common Python/IDE artifacts.
- **[`scripts/verify_integration.py`](scripts/verify_integration.py)** — CI: protocol constants, default hotkeys, dual-queue `build_listener`. See [`.github/workflows/ci.yml`](.github/workflows/ci.yml).
- **Removed** completed planning docs **`PARALLEL_WORK_PLAN.md`** and **`NEXT_STEPS.md`**. Use [`SPEC.md`](SPEC.md), [`ARCHITECTURE.md`](ARCHITECTURE.md), [`README.md`](README.md), and [`CHANGELOG.md`](CHANGELOG.md) for behavior, packaging, and history.

## 0.2.0

- **Documentation unified** around default hotkeys: **Ctrl+S** (speak / TTS), **Ctrl+L** (listen / STT). README, SPEC, ARCHITECTURE, IDEA, TESTING, and `narrator/settings_schema.md` updated; `pyproject.toml` description refreshed.
- **Listen worker** wired from `__main__.py` with dedicated queue (`narrator.listen.session`); dual-queue `hotkey.build_listener` again routes speak vs listen.
- Optional **system tray** (`--tray`, `pip install -e ".[tray]"`): Quit menu, hotkey in background thread.
- **`--hide-console`**: hide console window on Windows (`narrator/win_console.py`).
- **`requirements-lock.txt`**: pinned transitive set for reproducible installs.
- **`scripts/build_exe.ps1`** + **`scripts/pyinstaller_entry.py`**: optional PyInstaller single-file build.
- **`.github/workflows/ci.yml`**: Windows smoke test on Python 3.11–3.13.
- **`run_narrator.bat`** / **`run_narrator_tray.bat`**: quick launchers.
- README updates: `pythonw`, tray, exe build, CI, AV note.

## 0.1.0

- Initial packaged release: global hotkey (configurable), pointer-based UIA capture with physical cursor coordinates, WinRT speech with rate/volume/voice (SSML), cancellable synthesis, `winsound` playback with stop, TOML config, `--list-voices`, README and manual test notes.
