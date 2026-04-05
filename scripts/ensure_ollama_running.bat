@echo off
REM If Ollama CLI exists but the API is not up, start "ollama serve" in the background.
REM Piper/XTTS use the local LLM at http://127.0.0.1:11434 — no-op when ollama is missing or already running.
setlocal
where ollama >nul 2>&1 || exit /b 0
ollama list >nul 2>&1 && exit /b 0
echo [Narrator] Starting Ollama…
start "Ollama" /MIN cmd /c "ollama serve"
ping 127.0.0.1 -n 6 >nul
exit /b 0
