@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo Narrator setup  (verbose: set NARRATOR_SETUP_VERBOSE=1^)
echo.

set "USE_PY=0"
where python >nul 2>&1 && goto have_python
where py >nul 2>&1 || goto no_python
set "USE_PY=1"
echo Using py launcher ^(python not on PATH^)
goto make_venv

:have_python
set "USE_PY=0"

:make_venv
if "%USE_PY%"=="1" (
  py -3 -c "import sys; v=sys.version_info; raise SystemExit(0 if (3,11)<=(v.major,v.minor)<(3,15) else 1)" 2>nul
) else (
  python -c "import sys; v=sys.version_info; raise SystemExit(0 if (3,11)<=(v.major,v.minor)<(3,15) else 1)" 2>nul
)
if errorlevel 1 (
  echo [ERROR] Need Python 3.11-3.14.  winget install Python.Python.3.12  then new terminal.
  goto fail
)

if exist ".venv\Scripts\python.exe" goto install_deps

echo Creating .venv ...
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
set "VENVPY=%~dp0.venv\Scripts\python.exe"
if not exist "%VENVPY%" (
  echo [ERROR] Missing "%VENVPY%"
  goto fail
)
"%VENVPY%" -m ensurepip --upgrade 2>nul
"%VENVPY%" -m pip install --upgrade pip "setuptools>=61,<82" wheel -q

if not "%NARRATOR_SETUP_PROFILE%"=="" (
  "%VENVPY%" scripts\bootstrap_install.py --profile %NARRATOR_SETUP_PROFILE%
) else (
  "%VENVPY%" scripts\bootstrap_install.py --auto
)

if errorlevel 1 (
  echo [ERROR] bootstrap_install failed.
  goto fail
)

"%VENVPY%" scripts\ensure_cuda_torch.py
if errorlevel 1 (
  echo [WARN] ensure_cuda_torch issue — see docs\SETUP.md
)

echo.
echo Done.  run.bat
echo.
pause
exit /b 0

:no_python
echo [ERROR] Python not found.  winget install Python.Python.3.12
goto fail

:fail
pause
exit /b 1
