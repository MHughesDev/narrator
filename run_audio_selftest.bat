@echo off
REM Mic loopback selftest — run run_narrator.bat in another window first.
cd /d "%~dp0"
if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"
python -m pip install -e ".[audio-test]" -q 2>nul
echo Selftest: other window ^> run_narrator.bat  |  mic near speaker  |  here: key to record 45s
pause
python scripts\audio_loopback_record.py --duration 45 --out-dir audio_selftest_logs
if errorlevel 1 goto :eof
python scripts\analyze_audio_recordings.py audio_selftest_logs
echo Optional: OPENAI_API_KEY + pip openai  —  python scripts\analyze_audio_recordings.py audio_selftest_logs --openai
pause
