@echo off
REM Mic loopback capture + analysis. Run Narrator in another window first (run_narrator.bat).
cd /d "%~dp0"
if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"
echo Installing audio-test extra if needed...
python -m pip install -e ".[audio-test]" -q
echo.
echo === Instructions ===
echo 1. Open a SECOND Command Prompt and run:  run_narrator.bat
echo 2. Put your microphone close to the speaker.
echo 3. Return HERE and press a key — recording will start for 45 seconds.
echo 4. During recording: hover text and press Ctrl+Alt+S so Narrator speaks.
echo.
pause
python scripts\audio_loopback_record.py --duration 45 --out-dir audio_selftest_logs
if errorlevel 1 goto :eof
echo.
echo === Analysis (heuristic metrics) ===
python scripts\analyze_audio_recordings.py audio_selftest_logs
echo.
echo Optional OpenAI summary (needs OPENAI_API_KEY and: pip install openai^)
echo   python scripts\analyze_audio_recordings.py audio_selftest_logs --openai
echo.
pause
