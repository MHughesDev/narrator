# Narrator

**Windows only.** Hover over text, press a global hotkey to **hear it read aloud** (TTS), or press another hotkey to **dictate into the focused field** (STT). The mouse pointer chooses what gets read; the keyboard focus is where dictation goes.

| Action | Default | What it does |
|--------|---------|----------------|
| **Speak** | **Ctrl+Alt+S** | Hover, press → read under pointer. Press again to stop. |
| **Listen** | **Ctrl+Alt+L** | Focus a text box, press → start/stop dictation. |

Chords are configurable (`speak_hotkey` / `listen_hotkey` in TOML or `--speak-hotkey` / `--listen-hotkey`). Defaults use **Alt** so **Ctrl+S** (Save) and **Ctrl+L** (e.g. browser address bar) stay free in many apps — remap if a chord still conflicts.

**New machine — full stack:** **[`setup.bat`](setup.bat)** once, then **[`run.bat`](run.bat)** every time. Setup checks **Python 3.11–3.14**, creates **`.venv`**, scans hardware (**`scripts/hw_detect.py`** — CPU, RAM, disk, NVIDIA via `nvidia-smi` when present, ARM64 / VC++ hints), runs **`scripts/bootstrap_install.py --auto`** to install **WinRT / UIA / hotkey** deps plus **neural TTS** (CPU or **CUDA PyTorch** when a GPU is detected), then **`verify_setup.py`**, **`prefetch_xtts_model.py`**, **`prefetch_piper_voice.py`**, and **Ollama + text model** for Piper/XTTS (prefetch steps **skip** when caches are warm — see **[`docs/SETUP.md`](docs/SETUP.md)**). **`run.bat`** runs **`ensure_cuda_torch.py`**, ensures **Ollama** is listening if the CLI is installed, then starts the app. Profiles: **[`docs/SETUP.md`](docs/SETUP.md)** · repo map: **[`docs/REPO_LAYOUT.md`](docs/REPO_LAYOUT.md)** · **TTS pipeline**: **[`docs/TTS_PLAYBACK_ROADMAP.md`](docs/TTS_PLAYBACK_ROADMAP.md)**.

**Speak and listen are independent:** they use separate workers and queues. Starting or stopping one **does not** start, stop, or cancel the other. You can use **both at the same time** (for example, dictation active while something is read aloud). Details: [`SPEC.md`](SPEC.md) §5, [`ARCHITECTURE.md`](ARCHITECTURE.md) §5.

---

## Quick start (minimal path)

**1. Install Python** — **Windows**, **3.11–3.14** (Coqui TTS currently expects Python **below 3.15**).

- **Installer:** [python.org/downloads](https://www.python.org/downloads/) — enable **“Add python.exe to PATH”** and **pip**.
- **One-liner** (PowerShell as Administrator, if you use winget):  
  `winget install Python.Python.3.12`  
  Then open a **new** terminal so `PATH` updates.

[`setup.bat`](setup.bat) also works if only the **`py`** launcher is on PATH (no `python` yet) — it will run `py -3 -m venv`.

**2. Get this folder** — `git clone` the repo, or download and unzip it.

**3. Run setup** — double‑click **[`setup.bat`](setup.bat)** in the project folder, *or* in **Command Prompt** / **PowerShell**:

```bat
cd path\to\narrator
setup.bat
```

That **one step**:

1. Creates **`.venv`** (if needed), ensures **pip** (`ensurepip`), upgrades **pip / setuptools / wheel**.
2. Runs **`python scripts\bootstrap_install.py --auto`** — picks **neural-gpu** (CUDA **PyTorch** upgrade after neural extras) if **NVIDIA** is detected, else **neural-cpu**. Override with **`set NARRATOR_SETUP_PROFILE=minimal`** (WinRT-only) or **`neural-cpu`** / **`neural-gpu`** — see **[`docs/SETUP.md`](docs/SETUP.md)**.
3. Runs **[`scripts/verify_setup.py`](scripts/verify_setup.py)** to confirm imports (prints **torch.cuda** and **onnxruntime** providers).
4. Runs **[`scripts/prefetch_xtts_model.py`](scripts/prefetch_xtts_model.py)** and **`scripts/prefetch_piper_voice.py`** to cache default **XTTS** and **Piper** voices, then **[`scripts/setup_ollama_speak_llm.py`](scripts/setup_ollama_speak_llm.py)** for **Ollama** + the default text model (neural profiles). Prefetch can take **several minutes**; if it fails, the app still runs and may fetch on first use.

Default **`speak_engine`** is **`auto`**: **XTTS** when Coqui is installed (as after `setup.bat`), else **Piper** when an ONNX voice is present, else **Windows WinRT** TTS. Copy **[`config.example.toml`](config.example.toml)** to `%USERPROFILE%\.config\narrator\config.toml` if you want the same defaults in writing.

You only need full setup **once** per machine (or again after pulling major dependency changes).

**4. Run Narrator**

```bat
run.bat
```

Same as **`run_narrator.bat`**. Or, with the venv active:

```powershell
python -m narrator
```

Stop with **Ctrl+C** in the terminal. For a system tray icon and **Quit**, install tray extras once (`pip install -e ".[tray]"`) and use **`run_narrator_tray.bat`** — see [Tray mode](#tray-mode) below.

---

### Same setup without `setup.bat`

```powershell
cd path\to\narrator
python -m venv .venv
.\.venv\Scripts\python.exe -m ensurepip --upgrade
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python scripts\bootstrap_install.py --auto
python -m narrator
```

If you see **`No module named pip`** in a new venv, run **`.\.venv\Scripts\python.exe -m ensurepip --upgrade`** before any **`pip`** command.

(Or `pip install -e ".[speak-xtts,speak-piper]"` manually, then verify + prefetch — **`bootstrap_install.py`** does that and optional CUDA PyTorch.)

Use **`pip install -e .`** instead if you only want **WinRT** TTS (smaller install; no neural voice by default unless you change deps).

(On **cmd.exe** use `.\.venv\Scripts\activate.bat` instead of `Activate.ps1`.)

---

## Helper scripts (project root)

| File | Purpose |
|------|---------|
| **[`setup.bat`](setup.bat)** | **Full install:** `.venv`, **`scripts/bootstrap_install.py --auto`** (hardware-aware), **`verify_setup.py`**, prefetch, **Ollama + text model**, then **`scripts/ensure_cuda_torch.py`** if needed. |
| **[`run.bat`](run.bat)** | **`scripts/ensure_ollama_running.bat`** (if `ollama` on PATH), **`scripts/ensure_cuda_torch.py`**, then **`python -m narrator`** (`.venv` if present). Primary launcher after setup. |
| **[`scripts/bootstrap_install.py`](scripts/bootstrap_install.py)** | **`--auto`** or **`--profile`** `minimal` / `neural-cpu` / `neural-gpu`; optional **`--dry-run`**, **`--skip-prefetch`**, **`--prefetch-always`** (or env **`NARRATOR_FORCE_PREFETCH`**). Only **`pip install`** — never uninstalls deps. |
| **[`scripts/hw_detect.py`](scripts/hw_detect.py)** | Platform, CPU, RAM, disk, NVIDIA (`nvidia-smi`), ARM64 / VC++ hints (used by bootstrap). |
| **[`scripts/prefetch_utils.py`](scripts/prefetch_utils.py)** | Cache checks for idempotent XTTS / Piper prefetch (used by prefetch scripts). |
| **[`run_narrator.bat`](run_narrator.bat)** | Same as **`run.bat`** (ensure Ollama / CUDA, then **`python -m narrator`**). |
| **[`run_narrator_tray.bat`](run_narrator_tray.bat)** | **`ensure_ollama_running.bat`**, **`ensure_cuda_torch.py`**, then **`pythonw -m narrator --tray`** (install `[tray]` first). |
| **[`scripts/verify_setup.py`](scripts/verify_setup.py)** | Check **WinRT / UIA / PyTorch / Coqui** imports after install. |
| **[`scripts/prefetch_xtts_model.py`](scripts/prefetch_xtts_model.py)** | Load/cache XTTS weights (re-run after GPU/CUDA PyTorch changes if needed). |
| **[`scripts/prefetch_piper_voice.py`](scripts/prefetch_piper_voice.py)** | Download default Piper ONNX voice (`en_US-ryan-high`) into `%LOCALAPPDATA%\narrator\piper`. |
| **[`run_audio_selftest.bat`](run_audio_selftest.bat)** | **Loopback diagnostic:** mic near speaker → records WAV, then runs **[`scripts/analyze_audio_recordings.py`](scripts/analyze_audio_recordings.py)** (echo / overlap heuristics). Install: **`pip install -e ".[audio-test]"`**. Optional **`--openai`** needs **`OPENAI_API_KEY`** and **`pip install openai`**. |
| **[`scripts/audio_loopback_record.py`](scripts/audio_loopback_record.py)** | Record default microphone only (used by the batch file). |
| **[`scripts/audio_inference_selftest.py`](scripts/audio_inference_selftest.py)** | **Fixture-based ASR self-test:** optional audio download, Whisper inference, transcript assertions (WER/recall/precision), machine-readable JSON for agent automation. |

---

## Requirements

- **Windows 10/11** (64-bit)
- **Python 3.11–3.14** on `PATH` (recommended **3.12**; neural TTS needs Python **below 3.15** for Coqui today)
- **Disk / network:** several GB for PyTorch + XTTS prefetch on first full setup — see **[`docs/SETUP.md`](docs/SETUP.md)**

---

## Install options (reference)

| Method | When to use |
|--------|-------------|
| **`pip install -e ".[speak-xtts,speak-piper]"`** (what **`setup.bat`** runs) | **Recommended:** core app + **Coqui XTTS** + **Piper** (`speak_engine=auto` → XTTS when Coqui loads, else Piper when ONNX exists, else WinRT). |
| **`pip install -e ".[speak-xtts]"`** | Coqui XTTS only; add **`[speak-piper]`** for the same stack as **`setup.bat`**. |
| **`pip install -e .`** | Smaller install: **WinRT** TTS only; add extras for neural TTS. |
| **`pip install -r requirements.txt`** | Base deps only (no Coqui); pair with **`pip install coqui-tts`** or **`[speak-xtts]`** if you want XTTS. |
| **`pip install -r requirements-lock.txt` then `pip install -e ".[speak-xtts]" --no-deps`** | Reproducible base from [`requirements-lock.txt`](requirements-lock.txt) + extras by hand. |
| **`pip install -e ".[tray]"`** | Adds tray icon + **Quit** (pystray, Pillow). |

---

## Run (after install)

```powershell
python -m narrator
```

With the venv activated, the **`narrator`** command is also available:

```powershell
narrator
```

### Speak (TTS) — default **Ctrl+Alt+S**

- **Start:** hover the content, press the speak chord.
- **Stop:** press the same chord again.
- Speaking tempo is fixed at normal speed (no in-play rate hotkeys for now). Playback uses a single `waveOut` stream; see [Troubleshooting](#troubleshooting) if you hear overlapping voices.

### Listen (STT) — default **Ctrl+Alt+L**

- Focus a text field, press listen to **start** dictation; press again to **stop**.
- Allow the **microphone** and **speech** / online recognition in **Windows Settings** if prompted.
- This does **not** interfere with speak: you can have dictation on while TTS is playing, and vice versa.

### Tray mode

After:

```powershell
pip install -e ".[tray]"
```

```powershell
python -m narrator --tray
```

Or **`run_narrator_tray.bat`**. Right‑click the tray icon → **Quit**.

### Useful flags

| Flag | Meaning |
|------|---------|
| `--speak-engine auto\|winrt\|xtts\|piper` | **auto** (default): XTTS if Coqui loads, else Piper if ONNX voice installed, else WinRT; **piper** / **xtts** / **winrt** force one backend |
| `--list-voices` | WinRT + registry voices (offline Windows list) |
| `--list-xtts-speakers` | Coqui built-in speaker names (loads XTTS; slow) |
| `--voice NAME` | WinRT: voice from `--list-voices`. XTTS: speaker from `--list-xtts-speakers`. Piper: voice id (e.g. `en_US-ryan-high`) |
| `--piper-voice ID` | Default Piper voice when using **`--speak-engine piper`** (see **`prefetch_piper_voice.py`**) |
| `--xtts-model`, `--xtts-speaker`, `--xtts-language`, `--xtts-device`, `--xtts-speaker-wav` | Neural TTS options when using XTTS |
| `--volume 0.9` | Volume **0.0–1.0** |
| `--speak-hotkey CHORD` | Speak toggle (default **ctrl+alt+s** or config) |
| `--listen-hotkey CHORD` | Listen toggle (default **ctrl+alt+l** or config) |
| `--hotkey CHORD` | Deprecated: same as `--speak-hotkey` |
| `--silent` | No beep when capture finds no text |
| `--no-speak-exclude-hyperlinks` | Keep URLs / markdown links in captured text (default: strip) |
| `--no-speak-exclude-math` | Keep `$…$`, `\[…\]`, etc. (default: strip math markup) |
| `--no-speak-exclude-markup` | Keep code fences, HTML, markdown markers, image-alt patterns |
| `--no-speak-exclude-citations` | Keep bracket refs and parenthetical citations |
| `--no-speak-exclude-technical` | Keep UUIDs, hex, hashes, paths, emails |
| `--no-speak-exclude-chrome` | Keep page n of m, figure/table labels, TOC dot lines |
| `--no-speak-exclude-emoji` | Keep emoji |
| `--no-speak-insert-line-pauses` | Disable structural (paragraph) pauses |
| `--speak-pause-between-lines` | Also pause between lines within a block (not just paragraphs) |
| `--no-speak-winrt-ssml-breaks` | WinRT: use plain pauses like neural TTS instead of SSML breaks |
| `--speak-pause-line-ms`, `--speak-pause-paragraph-ms` | WinRT SSML break lengths when line pauses are on / always for paragraph gap |
| `--config PATH` | Extra TOML config |
| `--hide-console` | Hide console (with `python.exe`) |
| `--tray` | Tray + Quit (needs **`[tray]`** install) |

```powershell
python -m narrator --speak-hotkey ctrl+shift+s --list-voices
python -m narrator --list-xtts-speakers
python -m narrator --speak-engine xtts --voice "Ana Florence"
```

### No console (`pythonw`)

```powershell
pythonw -m narrator --tray
```

Logs go nowhere unless you add file logging later.

---

## Building a standalone `.exe` (optional)

```powershell
pip install -e ".[dev]"
powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1
```

Output: `dist\narrator.exe`. If bundling fails, use `python -m narrator`.

---

## CI

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs `scripts/smoke_test.py`, `scripts/verify_integration.py`, and **`pytest tests/`** (full suite under [`tests/`](tests/)), on **windows-latest** with Python **3.11–3.13**. Local installs may use **3.14** where supported; neural extras (**Coqui XTTS**) still expect **Python below 3.15** (see [`pyproject.toml`](pyproject.toml) `requires-python` and [`setup.bat`](setup.bat)).

---

## Open source

Licensed under the **MIT License** — see [`LICENSE`](LICENSE). Contributions: [`CONTRIBUTING.md`](CONTRIBUTING.md). **Security:** [`SECURITY.md`](SECURITY.md).

---

## Config file (optional)

Later files override earlier keys. Order: `%USERPROFILE%\.config\narrator\config.toml`, then `%LOCALAPPDATA%\narrator\config.toml`, then `--config`.

Start from **[`config.example.toml`](config.example.toml)** or use:

```toml
speak_engine = "auto"
piper_voice = "en_US-ryan-high"
voice = "Ana Florence"
xtts_model = "tts_models/multilingual/multi-dataset/xtts_v1.1"
rate = 1.0
volume = 1.0
speak_hotkey = "ctrl+alt+s"
listen_hotkey = "ctrl+alt+l"
beep_on_failure = true
```

With **`speak_engine = "auto"`**, **`voice`** / **`piper_voice`** depend on which engine runs: **XTTS** uses **`voice`** as the Coqui speaker (see `--list-xtts-speakers`); **Piper** uses the Piper voice id (default **`en_US-ryan-high`**). For **WinRT-only** installs, use names from **`--list-voices`** and set **`speak_engine = "winrt"`**. Use **`speak_engine = "piper"`** to force Piper when Coqui is also installed.

Legacy `hotkey` maps to `speak_hotkey` — see [`narrator/settings_schema.md`](narrator/settings_schema.md).

---

## Troubleshooting

- **Overlapping / stacked voices during speak** — See **[`docs/DEBUG_MULTIPLE_VOICES.md`](docs/DEBUG_MULTIPLE_VOICES.md)** for hypotheses and run with **`NARRATOR_DEBUG_AUDIO=1`** to log gate / `waveOut` / worker boundaries. Only one **`python -m narrator`** should run. If it sounds **roomy**, try disabling **spatial audio / enhancements** on the output device. A second copy plays on top of the first; the app normally exits if another instance exists (override with **`NARRATOR_ALLOW_MULTI=1`** only if you intend multiple processes). Listen (dictation) and speak use **separate** audio paths by design. (**Speaking speed hotkeys are disabled for now** — tempo stays at 1.0.)
- **Nothing on speak** — Another app may use the same chord. Try `--speak-hotkey ctrl+shift+alt+s` or another combo.
- **Nothing on listen** — Another app may use the same chord. Try `--listen-hotkey ctrl+shift+alt+l` or remap in TOML.
- **No text (speak)** — Some UIs hide text from UI Automation. Try Notepad or VS Code.
- **XTTS slow or first speak hangs** — Run **`python scripts\prefetch_xtts_model.py`** after install; use **`--xtts-device cuda`** if you have an NVIDIA GPU and CUDA PyTorch.
- **Neural TTS missing** — Run **`python scripts\verify_setup.py`**. Confirm **`pip install -e ".[speak-xtts,speak-piper]"`** completed; **`python -c "import TTS"`** and Piper import should work. Run **`prefetch_xtts_model.py`** / **`prefetch_piper_voice.py`** if models were not cached.
- **Elevation** — Match elevation with the target app (normal vs Run as administrator).
- **DPI** — Per‑monitor DPI is enabled; report odd hit‑testing with your display layout.
- **Corporate AV** — `pynput` uses hooks; see [`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## Docs

| Doc | Contents |
|-----|----------|
| **[`docs/SETUP.md`](docs/SETUP.md)** | **Full install:** PyTorch, Coqui, Piper, WinRT, prefetch, GPU, verify |
| [`IDEA.md`](IDEA.md) | Product intent |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Stack and modules |
| [`SPEC.md`](SPEC.md) | Behavior |
| [`TESTING.md`](TESTING.md) | Manual test matrix |
| [`SECURITY.md`](SECURITY.md) | How to report security issues |
| [`.gitignore`](.gitignore) | Ignores `.venv/`, `*.egg-info/`, `dist/`, etc. |
| [`narrator/settings_schema.md`](narrator/settings_schema.md) | TOML keys and defaults (**Ctrl+Alt+S** / **Ctrl+Alt+L**) |

---

## License

See [`LICENSE`](LICENSE).
