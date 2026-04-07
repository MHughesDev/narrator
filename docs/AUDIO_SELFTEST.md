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

## Metrics (heuristic + quality gates)

| Field | Meaning |
|-------|--------|
| `autocorr_echo_ratio_40_500ms`, `echo_likelihood_0_1` | Delayed self-similarity heuristic (**echo/chorus** risk). |
| `rms_burst_edges_per_s`, `overlap_likelihood_0_1` | Onset burstiness heuristic (**overlap/double voice** risk). |
| `clip_ratio_near_fullscale`, `clip_likelihood_0_1` | Samples near full-scale (**clipping/distortion** risk). |
| `longest_silent_run_s`, `silent_runs_over_200ms`, `dropout_likelihood_0_1` | Long silence runs (**skip/dropout** risk). |
| `spectral_centroid_delta_mean_hz`, `zcr_mean`, `instability_likelihood_0_1` | Spectral jitter/roughness proxy (**robotic/unstable** risk). |
| `quality_risk_0_1` | Weighted aggregate risk score. |

The analyzer now includes pass/fail quality gates per file and exits non-zero on failures:

- Exit `0`: analyzed files passed configured thresholds
- Exit `4`: at least one analyzed file failed quality gates

Use `--strict` for tighter thresholds when doing regression hunting.

Interpret together with **`NARRATOR_DEBUG_AUDIO=1`** logs.

## Optional GPT interpretation (text only)

The analyzer **does not upload audio** to OpenAI. It sends **JSON metrics** only.

```powershell
set OPENAI_API_KEY=sk-...
pip install openai
python scripts\analyze_audio_recordings.py audio_selftest_logs --openai
```

---

## Automated fixture inference self-test (agent/CI friendly)

Use this when you want deterministic pass/fail checks from a known audio clip (instead of mic loopback):

1. Optionally download a public fixture WAV
2. Run Whisper inference on that file
3. Compare transcript to expected text using token WER/precision/recall thresholds

Install deps:

```powershell
pip install -e ".[listen-whisper,dev]"
```

Run with bundled default fixture (spoken digit "zero"):

```powershell
python scripts\audio_inference_selftest.py --use-default-fixture --print-json
```

The default fixture URL is:

`https://raw.githubusercontent.com/Jakobovski/free-spoken-digit-dataset/master/recordings/0_jackson_0.wav`

Custom fixture + expected transcript:

```powershell
python scripts\audio_inference_selftest.py `
  --audio-url https://example.com/sample.wav `
  --audio-path audio_selftest_logs\sample.wav `
  --expected-text "your expected transcript here" `
  --max-wer 0.40 --min-token-recall 0.60 --min-token-precision 0.60 `
  --json-out audio_selftest_logs\inference_report.json
```

Notes:

- Exit code `0` = pass, `4` = inference completed but failed thresholds.
- Use `--fixture-sha256` to pin fixture integrity.
- This validates the **ASR path** directly; pair it with loopback diagnostics above for playback-path issues.
