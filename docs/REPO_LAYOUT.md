# Repository layout

| Path | Purpose |
|------|---------|
| **`narrator/`** | Python package: CLI (`python -m narrator`), speak/listen workers, WinRT TTS, optional Piper/XTTS, settings. |
| **`scripts/`** | Install & maintenance: **`bootstrap_install.py`**, **`pytorch_cuda_wheels.py`** (gentle CUDA PyTorch into venv), **`ensure_cuda_torch.py`**, **`hw_detect.py`**, **`verify_setup.py`**, **`prefetch_utils.py`**, prefetch scripts. |
| **`docs/`** | Setup (`SETUP.md`), TTS/playback pipeline ([`TTS_PLAYBACK_ROADMAP.md`](TTS_PLAYBACK_ROADMAP.md)), VoxCPM-inspired latency notes ([`VOXCPM_LATENCY.md`](VOXCPM_LATENCY.md)), glitch/debug notes. |
| Root **`setup.bat`** | Windows: create `.venv`, run **`scripts/bootstrap_install.py --auto`**. |
| Root **`run.bat`** / **`run_narrator.bat`** | After **`ensure_ollama_running.bat`** and **`ensure_cuda_torch.py`**, run **`python -m narrator`** with local `.venv` if present. |
| **`pyproject.toml`** | Package metadata and optional extras: `speak-xtts`, `speak-piper`, `listen-whisper`, `tray`, `dev`. |

**Platforms:** Runtime is **Windows-only** (required WinRT wheels). **`setup.sh`** only prints a message; use **`setup.bat`** on Windows.

**Optional GPU:** Not a separate code path — install **CUDA PyTorch** / **`onnxruntime-gpu`** into the same venv when your hardware supports it (`setup.bat` does this automatically when `nvidia-smi` reports a GPU).
