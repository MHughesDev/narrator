# Repository layout

| Path | Purpose |
|------|---------|
| **`narrator/`** | Python package: CLI (`python -m narrator`), speak/listen workers, WinRT TTS, optional Piper/XTTS, settings. |
| **`scripts/`** | Install & maintenance: **`bootstrap_install.py`** (hardware-aware setup), **`hw_detect.py`**, **`verify_setup.py`**, prefetch scripts. |
| **`docs/`** | Setup guides (`SETUP.md`), architecture pointers. |
| Root **`setup.bat`** | Windows: create `.venv`, run **`scripts/bootstrap_install.py --auto`**. |
| Root **`run_narrator.bat`** | Run **`python -m narrator`** with local `.venv` if present. |
| **`pyproject.toml`** | Package metadata and optional extras: `speak-xtts`, `speak-piper`, `listen-whisper`, `tray`, `dev`. |

**Platforms:** Runtime is **Windows-only** (required WinRT wheels). **`setup.sh`** only prints a message; use **`setup.bat`** on Windows.

**Optional GPU:** Not a separate code path — install **CUDA PyTorch** / **`onnxruntime-gpu`** into the same venv when your hardware supports it (`setup.bat` does this automatically when `nvidia-smi` reports a GPU).
