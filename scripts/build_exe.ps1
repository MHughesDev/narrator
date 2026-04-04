# Build a single-file narrator.exe (requires PyInstaller: pip install pyinstaller).
# WinRT + COM can be finicky; if the exe fails at runtime, run from source with: pip install -e .

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    Write-Error "Install PyInstaller first: pip install pyinstaller"
}

$py = (Get-Command python).Source
Write-Host "Using $py"

& pyinstaller --noconfirm --clean --onefile --name narrator `
    --collect-submodules narrator `
    --collect-all winrt `
    --collect-all pynput `
    --collect-all comtypes `
    --hidden-import winrt.windows.media.speechsynthesis `
    --hidden-import winrt.windows.storage.streams `
    --hidden-import PIL `
    --hidden-import PIL.Image `
    scripts\pyinstaller_entry.py

Write-Host "Done: dist\narrator.exe"
