# Audio loopback self-test (echo / overlap diagnostics)

This does **not** automate hotkeys. You run Narrator, put a **microphone near the speaker**, and capture what the mic hears while TTS plays.

## Why

To compare **metrics** across builds when you hear **echo**, **chorus**, or **multiple voices** — see also [`docs/DEBUG_MULTIPLE_VOICES.md`](DEBUG_MULTIPLE_VOICES.md).

## One-shot (Windows)

1. Install the extra: `pip install -e ".[audio-test]"`
2. In **terminal A:** `run_narrator.bat`
3. In **terminal B:** `run_audio_selftest.bat` — follow prompts; during the 45 s recording, hover text and press **Ctrl+Alt+S**.

Outputs under **`audio_selftest_logs/`**: `loopback_*.wav`, `session_*.txt`, plus console analysis.

## Manual

```bat
pip install -e ".[audio-test]"
python scripts\audio_loopback_record.py --duration 45 --out-dir audio_selftest_logs
python scripts\analyze_audio_recordings.py audio_selftest_logs
```

## Metrics (heuristic)

| Field | Meaning |
|-------|--------|
| `autocorr_echo_ratio_40_500ms` | Strength of delayed self-similarity in the envelope — **higher** may indicate **echo / delayed copy**. |
| `echo_likelihood_0_1` | Normalized score from the above (not a clinical test). |
| `rms_burst_edges_per_s` | Rough “activity edges” per second — **higher** *may* suggest **overlapping** phrases. |
| `overlap_likelihood_0_1` | Normalized from burstiness. |

Interpret together with **`NARRATOR_DEBUG_AUDIO=1`** logs.

## Optional GPT interpretation (text only)

The analyzer **does not upload audio** to OpenAI. It sends **JSON metrics** only.

```powershell
set OPENAI_API_KEY=sk-...
pip install openai
python scripts\analyze_audio_recordings.py audio_selftest_logs --openai
```
