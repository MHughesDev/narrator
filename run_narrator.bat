@echo off
REM Run narrator from a local venv if present, else python on PATH.
REM First time: run setup.bat (creates .venv and installs deps)
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m narrator %*
) else if exist ".venv311\Scripts\python.exe" (
  ".venv311\Scripts\python.exe" -m narrator %*
) else if exist ".venv312\Scripts\python.exe" (
  ".venv312\Scripts\python.exe" -m narrator %*
) else (
  python -m narrator %*
)
