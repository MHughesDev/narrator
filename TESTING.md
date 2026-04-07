# Manual test matrix

**Default hotkeys:** **Ctrl+Alt+S** = speak (hover + read aloud), **Ctrl+Alt+L** = listen (dictation into focus). Remap in TOML or CLI if an app steals a chord.

**Simultaneous use:** Speak and listen **must** be testable together — start dictation (**Ctrl+Alt+L**), then trigger read-aloud (**Ctrl+Alt+S**) while dictation is still on (and the reverse order). Neither action should stop the other; only the **same** chord toggles its own feature.

Run `python -m narrator` (or `narrator` after install) and work through the table. Record **Pass / Fail / Notes** for your machine.

## Speak (TTS)

| App | Hover target | Read starts | Stop mid-play | Notes |
|-----|----------------|-------------|---------------|-------|
| Notepad | File content | | | Baseline |
| VS Code | Editor buffer | | | |
| Microsoft Edge | Article body | | | If a site or extension steals **Ctrl+Alt+S** / **Ctrl+Alt+L**, remap in TOML or CLI |
| Google Chrome | Article body | | | Same chord conflicts as Edge |
| Word | Document | | | |
| PDF (Edge or Acrobat) | Page text | | | Often UIA-limited |

## Listen (STT)

Focus a text field, press **`listen_hotkey`** (default **Ctrl+Alt+L**), speak a short phrase, press the chord again to stop. Confirm text appears as you speak (partial hypotheses) and that phrases finalize with a trailing space.

| App | Focus | Dictation starts | Text appears | Notes |
|-----|--------|------------------|--------------|-------|
| Notepad | Edit surface | | | Baseline |
| Edge / Chrome | Address bar or search field | | | If a chord conflicts, remap `listen_hotkey` (e.g. `ctrl+shift+alt+l`) |
| VS Code | Editor | | | |

## Speak + listen at the same time

| Step | Expected |
|------|----------|
| Focus Notepad, press **Ctrl+Alt+L** — dictation on | Listening |
| Without turning dictation off, hover text and press **Ctrl+Alt+S** | TTS plays; dictation **still** on |
| Press **Ctrl+Alt+S** again | TTS stops; dictation **still** on until **Ctrl+Alt+L** |
| Turn off dictation (**Ctrl+Alt+L**) while idle speak | Dictation stops; speak unchanged |

## Elevation (Phase D.3)

| Narrator | Target app | Expected |
|----------|------------|----------|
| Normal | Normal | Typical |
| Normal | Run as Administrator | UIA may see less — try Admin terminal |
| Administrator | Normal | Usually OK |

## Live speaking rate (during playback)

| Step | Expected |
|------|----------|
| Long paragraph (e.g. Piper, `speak_engine = piper`), start speak | Audio plays |
| While playing, press **Ctrl+Alt+Plus** several times | Rate increases; **no** stacked / echoing voices (single stream) |
| Press **Ctrl+Alt+Minus** | Rate decreases |

If overlap persists, confirm you are **not** using sample-accurate seek (`NARRATOR_LIVE_RATE_ACCURATE_SEEK=1` / `live_rate_safe_chunk_discard = false`); defaults should use chunk-boundary resume. Otherwise tune env vars (see [README](README.md) Troubleshooting).

## Smoke (automated)

From repo root with venv activated:

```powershell
pip install -e ".[dev]"
python scripts\smoke_test.py
python scripts\verify_integration.py
pytest tests/ -v
```

CI runs **`smoke_test.py`** (WinRT TTS), **`verify_integration.py`** (protocol, defaults, dual-queue `build_listener`), and **`pytest tests/`** (full suite under **`tests/`**) on **windows-latest** (Python 3.11–3.13); see [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

## Audio inference fixture test (automated)

Use this to validate the speech-to-text inference path with a deterministic fixture and explicit pass/fail thresholds.

```powershell
pip install -e ".[listen-whisper,dev]"
python scripts\audio_inference_selftest.py --use-default-fixture --print-json
```

This script can also run with custom fixture WAVs and expected transcripts (and emits a JSON report for agent assertions). See [`docs/AUDIO_SELFTEST.md`](docs/AUDIO_SELFTEST.md).

## Tray (optional)

After `pip install -e ".[tray]"`, run `python -m narrator --tray`, confirm **Ctrl+Alt+S** / **Ctrl+Alt+L** (or your configured chords), then **Quit** from the tray icon (no zombie `narrator` in Task Manager).
