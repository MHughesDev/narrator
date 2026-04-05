@echo off
REM Run narrator from a local venv if present, else python on PATH.
REM First time: setup.bat only — then this file or run.bat
REM With NVIDIA: ensure CUDA PyTorch is installed (scripts\ensure_cuda_torch.py)
cd /d "%~dp0"
REM Coqui XTTS CPML: required for non-interactive model download/load (see https://coqui.ai/cpml).
if not defined COQUI_TOS_AGREED set "COQUI_TOS_AGREED=1"
call "%~dp0scripts\ensure_ollama_running.bat"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" scripts\ensure_cuda_torch.py
  ".venv\Scripts\python.exe" -m narrator %*
) else if exist ".venv311\Scripts\python.exe" (
  ".venv311\Scripts\python.exe" scripts\ensure_cuda_torch.py
  ".venv311\Scripts\python.exe" -m narrator %*
) else if exist ".venv312\Scripts\python.exe" (
  ".venv312\Scripts\python.exe" scripts\ensure_cuda_torch.py
  ".venv312\Scripts\python.exe" -m narrator %*
) else (
  python scripts\ensure_cuda_torch.py 2>nul
  python -m narrator %*
)
