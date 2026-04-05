@echo off
REM Tray mode — needs: setup.bat once, then pip install -e ".[tray]"
cd /d "%~dp0"
call "%~dp0scripts\ensure_ollama_running.bat"
if exist ".venv\Scripts\pythonw.exe" (
  if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" scripts\ensure_cuda_torch.py
  )
  ".venv\Scripts\pythonw.exe" -m narrator --tray %*
) else (
  python scripts\ensure_cuda_torch.py 2>nul
  pythonw -m narrator --tray %*
)
