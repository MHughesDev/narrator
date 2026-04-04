@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo  Narrator — automatic setup (hardware-aware)
echo  ----------------------------------------------
echo.

set "USE_PY=0"
where python >nul 2>&1 && goto have_python
where py >nul 2>&1 || goto no_python
set "USE_PY=1"
echo Note: "python" not on PATH — using Windows "py" launcher.
goto make_venv

:have_python
set "USE_PY=0"

:make_venv
if exist ".venv\Scripts\python.exe" goto install_deps

echo Creating virtual environment .venv ...
if "%USE_PY%"=="1" (
  py -3 -m venv .venv 2>nul
  if errorlevel 1 py -m venv .venv
) else (
  python -m venv .venv
)
if errorlevel 1 (
  echo [ERROR] Could not create .venv
  goto fail
)

:install_deps
REM Use venv python.exe directly — "call activate.bat" fails on some systems and leaves PATH python
REM (then pip installs to user site-packages and neural DLLs break under Python 3.14).
set "VENVPY=%~dp0.venv\Scripts\python.exe"
if not exist "%VENVPY%" (
  echo [ERROR] Missing "%VENVPY%"
  goto fail
)
echo Using venv Python:
echo   %VENVPY%
echo Ensuring pip in venv...
"%VENVPY%" -m ensurepip --upgrade 2>nul
"%VENVPY%" -m pip install --upgrade pip setuptools wheel -q

REM Optional override: set NARRATOR_SETUP_PROFILE=minimal ^| neural-cpu ^| neural-gpu
if not "%NARRATOR_SETUP_PROFILE%"=="" (
  echo Using profile from NARRATOR_SETUP_PROFILE=%NARRATOR_SETUP_PROFILE%
  "%VENVPY%" scripts\bootstrap_install.py --profile %NARRATOR_SETUP_PROFILE%
) else (
  echo Running hardware scan and installing ^(see scripts\hw_detect.py^)...
  "%VENVPY%" scripts\bootstrap_install.py --auto
)

if errorlevel 1 (
  echo [ERROR] bootstrap_install failed.
  goto fail
)

echo.
echo  Done.
echo    Run:  run_narrator.bat
echo      or:  python -m narrator
echo.
echo  Profiles:  set NARRATOR_SETUP_PROFILE=minimal   ^(WinRT only, smallest^)
echo              set NARRATOR_SETUP_PROFILE=neural-cpu ^(force CPU PyTorch^)
echo              set NARRATOR_SETUP_PROFILE=neural-gpu ^(force CUDA PyTorch if NVIDIA present^)
echo.
echo  Optional — tray icon + Quit:
echo    pip install -e ".[tray]"
echo    run_narrator_tray.bat
echo.
pause
exit /b 0

:no_python
echo [ERROR] Python was not found.
echo.
echo  Install Python 3.11+ from https://www.python.org/downloads/
echo  ^(enable "Add python.exe to PATH"^), or in PowerShell ^(Admin^) try:
echo    winget install Python.Python.3.12
echo.
echo Then open a NEW terminal and run setup.bat again.
goto fail

:fail
pause
exit /b 1
