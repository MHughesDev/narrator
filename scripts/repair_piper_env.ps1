# Repair Piper / onnxruntime imports on Windows (DLL or numpy binding failures).
# Run from repo root:  powershell -ExecutionPolicy Bypass -File scripts\repair_piper_env.ps1
$ErrorActionPreference = "Stop"
$venvPy = Join-Path $PSScriptRoot "..\.venv311\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "ERROR: .venv311 not found next to scripts/. Set venv path manually." -ForegroundColor Red
    exit 1
}
$pip = Join-Path (Split-Path $venvPy) "pip.exe"
Write-Host "Using: $venvPy"
& $pip install --force-reinstall "numpy>=1.26,<2.1" "onnxruntime>=1.16.0,<2"
& $venvPy -c "import onnxruntime as o; import numpy as n; print('onnxruntime', o.__version__, 'numpy', n.__version__); from piper.voice import PiperVoice; print('Piper import: OK')"
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "If import still fails with DLL errors, install Microsoft VC++ Redistributable x64:" -ForegroundColor Yellow
    Write-Host "  https://aka.ms/vs/17/release/vc_redist.x64.exe" -ForegroundColor Cyan
    exit 2
}
Write-Host "OK. Run: python -m narrator --speak-engine auto" -ForegroundColor Green
