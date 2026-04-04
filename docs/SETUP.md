# Setup — Windows (automatic, hardware-aware)

Narrator is **Windows 10/11** and **Python 3.11–3.14** (Coqui TTS currently expects **Python below 3.15**).

## One-command install (recommended)

From the repo root:

```bat
setup.bat
```

### What runs

| Step | Action |
|------|--------|
| 1 | Creates **`.venv`** if missing (`python` or **`py`** launcher). |
| 2 | Upgrades **pip**, **setuptools**, **wheel**. |
| 3 | **`python scripts\bootstrap_install.py --auto`** — see [Profiles](#install-profiles) below. |
| 4 | **`verify_setup.py`**, then **XTTS** and **Piper** prefetch (unless `--skip-prefetch` was used manually). |

Hardware is scanned in **`scripts/hw_detect.py`** (NVIDIA via `nvidia-smi` when available).

### Install profiles

| Profile | When | What gets installed |
|---------|------|----------------------|
| **`auto`** (default) | `setup.bat` with no env override | **Windows + NVIDIA GPU** → **`neural-gpu`**. **Windows, no NVIDIA** → **`neural-cpu`**. |
| **`neural-gpu`** | Auto, or `set NARRATOR_SETUP_PROFILE=neural-gpu` | `pip install -e ".[speak-xtts,speak-piper]"` then **upgrade PyTorch + torchaudio** from the **CUDA 12.4** wheel index (`cu124`). |
| **`neural-cpu`** | No discrete NVIDIA, or forced | Full neural stack with **CPU PyTorch** (what `pip` resolves from extras). |
| **`minimal`** | `set NARRATOR_SETUP_PROFILE=minimal` | `pip install -e .` only — **WinRT** TTS; no Coqui/Piper unless added later. |

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
