# Setup — Windows (automatic, hardware-aware)

**Runtime is Windows-only** (WinRT, UI Automation). macOS and Linux are not supported for running the app; [`setup.sh`](setup.sh) only prints guidance.

Narrator targets **Windows 10/11** and **Python 3.11–3.14** (Coqui TTS currently expects **Python below 3.15**). [`setup.bat`](setup.bat) checks the interpreter version before creating **`.venv`** and rejects **3.15+** with an error.

### Isolated project environment (everything in `.venv`)

All **`pip install`** commands from **`setup.bat`**, **`bootstrap_install.py`**, and **`ensure_cuda_torch.py`** target **only** the **`.\.venv`** next to this repo (that interpreter’s `site-packages`). They do **not** modify:

- The **system** Python on `PATH`
- **pyenv**, **conda** base, or other global environments
- Packages you installed for **other projects** (unless you deliberately point `pip` at the same venv)

So “bundling” here means: **one self-contained venv folder** inside the project; Narrator’s dependencies live there alone. Optional neural assets (XTTS, Piper voices) still download to the **Hugging Face cache** and **`%LOCALAPPDATA%\narrator\piper`** — see [Skipping redundant model downloads](#skipping-redundant-model-downloads).

**CUDA PyTorch:** [`scripts/pytorch_cuda_wheels.py`](pytorch_cuda_wheels.py) tries a **gentle** `pip install --upgrade torch torchaudio` from the CUDA index first (less churn). **`--force-reinstall`** runs **only if** CUDA still does not load (stubborn `+cpu` wheels). Override: **`NARRATOR_CUDA_FORCE_REINSTALL=1`** to skip the gentle step.

**Offline / air-gapped:** pre-download wheels on a networked machine, then install from a folder:

```powershell
mkdir wheels
.\.venv\Scripts\python.exe -m pip download -e ".[speak-xtts,speak-piper]" -d wheels
# Add CUDA torch wheels for your platform from the same index bootstrap uses, then:
.\.venv\Scripts\python.exe -m pip install --no-index --find-links=wheels -e ".[speak-xtts,speak-piper]"
```

(Exact CUDA wheel names vary; mirror [`pytorch.org`](https://pytorch.org/get-started/locally/) for your Python version.)

## One-command install (recommended)

From the repo root:

```bat
setup.bat
```

### What runs

| Step | Action |
|------|--------|
| 1 | **Python 3.11–3.14** check (`python` or **`py -3`**). |
| 2 | Creates **`.venv`** if missing (`python` or **`py`** launcher). |
| 3 | Upgrades **pip**, **setuptools**, **wheel**. |
| 4 | **`python scripts\bootstrap_install.py --auto`** — see [Profiles](#install-profiles) below. |
| 5 | **`verify_setup.py`**, then **XTTS** and **Piper** prefetch when profile is **not** `minimal` (unless `--skip-prefetch` was used manually). |
| 5b | **`scripts\setup_ollama_speak_llm.py`** (same neural path): **winget** `Ollama.Ollama` if missing, then **`ollama pull`** the default text model (**`llama3.2:1b`**) — required for **Piper** / **XTTS** speak (local LLM readies each chunk). Set **`NARRATOR_SKIP_OLLAMA_SETUP=1`** to skip. |
| 6 | **`python scripts\ensure_cuda_torch.py`** — if **`nvidia-smi`** reports a GPU but PyTorch is still **CPU-only** (`+cpu`), installs **CUDA** `torch` / `torchaudio` from the configured wheel index (same as **`neural-gpu`**). No-op if no NVIDIA, non-Windows, or CUDA already works. |

**[`run.bat`](../run.bat)** (or **`run_narrator.bat`**) runs **`scripts/ensure_ollama_running.bat`** (starts **`ollama serve`** in the background if the CLI exists but the API is down), then **`ensure_cuda_torch.py`**, then the app — so day-to-day use is **setup.bat** once and **run.bat** after. **Quiet by default:** set **`NARRATOR_SETUP_VERBOSE=1`** for full hardware tables, pip command echoes, and longer prefetch/CUDA/Ollama messages. **`run_narrator_tray.bat`** does the same Ollama + CUDA checks before **`pythonw -m narrator --tray`**. Set **`NARRATOR_SKIP_CUDA_ENSURE=1`** to skip CUDA ensure. **ARM64** Windows skips automatic CUDA install (wheels are typically x64).

**Hardware / environment** is summarized in **`scripts/hw_detect.py`**: logical CPU name and core count, total RAM, free disk space on the repo drive (warning if under ~15 GiB), machine architecture (ARM64 note), NVIDIA GPU and driver via **`nvidia-smi`** when available, and a basic **Microsoft VC++** runtime check (**`vcruntime140.dll`** in System32 — informational only; setup does not install runtimes).

Setup only changes packages **inside the active venv** (usually **`.venv`**). Pip may refresh or reinstall dependencies there when resolving versions; it does **not** touch installs outside that venv.

### Skipping redundant model downloads

If **Piper** voice files for the chosen voice id already exist under the default Piper data directory, or **XTTS** / Hugging Face hub caches already contain the default model, prefetch scripts print **`SKIP`** and exit successfully. This only inspects **known cache locations** (`HF_HOME`, `HUGGINGFACE_HUB_CACHE`, `%USERPROFILE%\.cache\huggingface\hub`, and Coqui local dirs under **`%LOCALAPPDATA%\tts`** / **`~/.local/share/tts`**) — not arbitrary folders like **Downloads**.

To force a full load/download anyway: **`--prefetch-always`** on **`scripts/prefetch_xtts_model.py`** / **`scripts/prefetch_piper_voice.py`**, or set **`NARRATOR_FORCE_PREFETCH=1`** (also passed through **`python scripts\bootstrap_install.py --prefetch-always`**).

### Install profiles

| Profile | When | What gets installed |
|---------|------|----------------------|
| **`auto`** (default) | `setup.bat` with no env override | **Windows + NVIDIA GPU** → **`neural-gpu`**. **Windows, no NVIDIA** → **`neural-cpu`**. |
| **`neural-gpu`** | Auto, or `set NARRATOR_SETUP_PROFILE=neural-gpu` | `pip install -e ".[speak-xtts,speak-piper]"` then **upgrade PyTorch + torchaudio** from the **CUDA 12.4** wheel index (`cu124`). |
| **`neural-cpu`** | No discrete NVIDIA, or forced | Full neural stack with **CPU PyTorch** (what `pip` resolves from extras). |
| **`minimal`** | `set NARRATOR_SETUP_PROFILE=minimal` | `pip install -e .` only — **WinRT** TTS; **neural prefetch is skipped** (no Coqui/Piper in this profile). |

Override profile for one run:

```bat
set NARRATOR_SETUP_PROFILE=minimal
setup.bat
```

CUDA wheel index override (advanced):

```bat
set NARRATOR_TORCH_CUDA_INDEX=https://download.pytorch.org/whl/cu124
setup.bat
```

Dry-run (print `pip` commands only):

```bat
.venv\Scripts\activate.bat
python scripts\bootstrap_install.py --dry-run --auto
```

**Bootstrap flags** (see `python scripts\bootstrap_install.py --help`): **`--dry-run`**, **`--skip-prefetch`**, **`--force-cuda`**, **`--prefetch-always`** (or **`NARRATOR_FORCE_PREFETCH=1`**).

**CUDA PyTorch (`neural-gpu`):** after the CPU-oriented `pip install -e ".[speak-xtts,speak-piper]"`, bootstrap reinstalls **`torch`** / **`torchaudio`** from the CUDA wheel index with **`--force-reinstall`** so an existing **`+cpu`** build is replaced. If you still see **`torch ... +cpu`** and **`CUDA available: False`**, run manually:  
`pip install --upgrade --force-reinstall torch torchaudio --index-url https://download.pytorch.org/whl/cu124`  
(override URL with **`NARRATOR_TORCH_CUDA_INDEX`** if needed).

### Linux / macOS

Narrator’s **runtime dependencies include WinRT** — use **Windows** for installation. **`setup.sh`** in the repo root only prints guidance.

---

## Manual install (same as automatic)

```powershell
cd path\to\narrator
python -m venv .venv
.\.venv\Scripts\python.exe -m ensurepip --upgrade
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python scripts\bootstrap_install.py --profile neural-cpu
```

Use **`--profile neural-gpu`** on a machine with NVIDIA if you want CUDA PyTorch without `nvidia-smi` auto-detection.

---

## Verify your environment

```powershell
python scripts\verify_setup.py
```

Check PyTorch and ONNX providers:

```powershell
python -c "import torch; print('cuda=', torch.cuda.is_available())"
python -c "import onnxruntime as ort; print(ort.get_available_providers())"
```

**Piper on GPU** additionally needs **`CUDAExecutionProvider`** from `onnxruntime-gpu` if you want `--piper-cuda`; the bootstrap path installs **`onnxruntime`** (CPU). You can add `pip install onnxruntime-gpu` after setup if needed.

---

## WinRT-only (small install)

```powershell
pip install -e .
```

Set **`speak_engine = "winrt"`** in config.

---

## Troubleshooting

- **`No module named pip`** — Run **`.\.venv\Scripts\python.exe -m ensurepip --upgrade`** (or delete `.venv` and run `setup.bat` again, which runs `ensurepip`).
- **`import TTS` fails** — `pip install -e ".[speak-xtts]"` inside `.venv`.
- **PyTorch DLL / WinError 1114** — Install [VC++ redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist); try Python **3.12** from python.org; or stay on **CPU** PyTorch (`neural-cpu`).
- **CUDA PyTorch install fails** — Use `neural-cpu`, or follow [pytorch.org](https://pytorch.org/get-started/locally/) and set **`NARRATOR_TORCH_CUDA_INDEX`** to a matching index.
