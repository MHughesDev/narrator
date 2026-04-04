@echo off
REM Tray mode — needs: setup.bat once, then pip install -e ".[tray]"
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
  ".venv\Scripts\pythonw.exe" -m narrator --tray %*
) else (
  pythonw -m narrator --tray %*
)
