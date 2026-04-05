# Narrator — behavior specification (MVP)

This document defines **observable behavior** for the MVP. Implementation lives in the `narrator` package; stack choices are in [`ARCHITECTURE.md`](ARCHITECTURE.md); intent is in [`IDEA.md`](IDEA.md).

**Canonical defaults (always configurable, never hard-coded in logic):**

| Role | Default chord | Config keys / CLI |
|------|----------------|-------------------|
| **Speak** (TTS, hover) | **Ctrl+Alt+S** | `speak_hotkey`, `--speak-hotkey` |
| **Listen** (STT, focused field) | **Ctrl+Alt+L** | `listen_hotkey`, `--listen-hotkey` |

---

## 1. Entry and lifecycle

1. User runs `python -m narrator` from a terminal (see §7 for flags).
2. Process stays alive until **Ctrl+C** (SIGINT) or fatal error.
3. While alive, **two** global chords are registered (defaults **`ctrl+alt+s`** = speak, **`ctrl+alt+l`** = listen). Chords are configurable and must differ.

---

## 2. Hotkeys: speak vs listen

### 2.1 Speak (`speak_hotkey`, default `ctrl+alt+s`)

| State | User presses the **speak** chord | Result |
|-------|----------------------------------|--------|
| **Idle** (not synthesizing, not playing audio) | Once | **Start** a read: capture text at pointer (§3), then synthesize and play (§4). |
| **Busy** (synthesizing **or** playing) | Once | **Stop**: cancel playback as soon as possible; skip or truncate remaining work. |
| **Idle** immediately after a completed read | Once | **Start** a new read (same as first row). |

There is **no separate** “stop-only” key for speak: one chord toggles between **start** and **stop**.

### 2.2 Listen (`listen_hotkey`, default `ctrl+alt+l`)

| State | User presses the **listen** chord | Result |
|-------|-----------------------------------|--------|
| **Off** | Once | Start **continuous dictation** (WinRT speech recognition). Partial hypotheses and final phrase results are typed into the **focused** control (see `narrator.listen.session`). |
| **On** | Once | Stop dictation and end the recognition session. |

Queue messages use `listen_toggle` / `shutdown` per [`narrator/protocol.py`](narrator/protocol.py). Microphone and Windows speech privacy settings must allow recognition or the session logs an error and exits.

### 2.3 Conflict with other applications

Defaults use **Ctrl+Alt** to reduce clashes with **Ctrl+S** (save) and **Ctrl+L** (e.g. browser address bar). This tool registers **global** hooks: the OS may deliver a chord to **either** the foreground app **or** the hook. If nothing happens, remap via `--speak-hotkey` / `--listen-hotkey` or TOML (`speak_hotkey`, `listen_hotkey`). See also [`narrator/settings_schema.md`](narrator/settings_schema.md).

---

## 3. Pointer-based capture (not caret)

### 3.1 When capture runs

Capture runs **once** at the **start** of a read, **immediately after** the user’s **speak** chord while idle. The implementation uses the **mouse position at that moment** (same as “hover at hotkey time”).

### 3.2 Hit-test

1. Resolve the UI Automation element under the cursor (e.g. `ElementFromPoint` / `ControlFromPoint`).
2. If no element: **no text** → log warning, do not play audio.

### 3.3 Container choice and “top to bottom”

1. Walk **up** the UIA tree from the hit element to the root, up to **30** ancestors (implementation constant).
2. **Primary rule:** Prefer the **deepest** `Document` or `Edit` control (walking from hit toward root) that yields non-empty text from **Text pattern** (else **Value**). This targets real editor buffers in IDEs (e.g. VS Code / Cursor) instead of a parent range that concatenates menu bars and workspace chrome.
3. **Secondary:** Some hosts use `CustomControl` for the editor (e.g. Electron); take the deepest non-chrome `CustomControl` with text (class-name heuristics skip obvious toolbars).
4. **Fallback:** Among remaining ancestors, **exclude** menu bar, toolbar, title bar, status bar, and tab strip control types from aggregation; then choose the **longest** non-empty string (legacy behavior for simple apps). Pre-order child snippets run only as a last resort when the hit is already `Document`, `Edit`, or `Custom`.
5. For each visited control, text is obtained in this **order**: **Text pattern** — `DocumentRange` / `GetText(-1)` when supported; else **Value pattern**.

**Caret / insertion point** is **not** used for targeting or start offset (per IDEA).

### 3.4 Fallback

If no pattern yields non-empty text:

- Use the hit control’s **Name** (and optionally **HelpText**) if non-empty, as a last resort **short** snippet.

### 3.5 Failure

If the resolved string is empty: log a short message; **no** speech.

### 3.6 Preprocessing (optional)

Before TTS, the speak path may **strip** many non-prose patterns from the captured string (defaults on): links/URLs, math, markup (code fences, HTML, markdown artifacts, image alt patterns), citations, technical tokens (UUID, hex, paths, email), document chrome (page *n* of *m*, figure/table labels, TOC-like lines), emoji, and invisible control characters — see `narrator/speak_preprocess.py` and TOML keys `speak_exclude_*`. If nothing remains after stripping, treat as **failure** (§3.5).

### 3.7 Line / paragraph pauses (optional)

After preprocessing, the speak path may **insert pauses** at paragraph breaks (defaults on; **standard** profile: blank-line / section boundaries only). Optional **line-level** pauses (single newlines within a block) are off by default — see `narrator/speak_prosody.py` and keys `speak_insert_line_pauses`, `speak_pause_between_lines`, `speak_pause_*_ms`, `speak_winrt_use_ssml_breaks`.

---

## 4. Speech

1. Use **offline** Windows speech (WinRT `SpeechSynthesizer` per architecture).
2. Synthesize to a **temporary WAV** (in-memory or on disk), then play via a **stoppable** path — primary implementation uses **Win32 `waveOut`** with explicit open/write/reset/close (see [`narrator/wav_play_win32.py`](narrator/wav_play_win32.py)); optional **PortAudio** / `sounddevice` when `audio_output_backend` is set accordingly in settings.
3. Default voice: **system default** for the synthesizer unless overridden by CLI (future: explicit voice id).

---

## 5. Concurrency rules

1. Hotkey callbacks **must not** call UIA, TTS, or STT directly; they only **enqueue** messages on the appropriate queue ([`narrator/protocol.py`](narrator/protocol.py)).
2. The **speak worker** runs capture, synthesis, and playback/stop. The **listen worker** runs dictation start/stop and typing into focus. They are **separate threads** with **separate queues**.
3. A **second** press of the **speak** chord while the speak path is busy must **stop** speak audio/synthesis without requiring the user to focus the terminal.
4. **Speak and listen do not interact.** Toggling one feature **must not** start, stop, or cancel the other. Both may be **active at the same time** (e.g. dictation running while TTS plays, or any order of toggles). Implementations **must not** add cross-cancellation between speak and listen except when the **whole process** shuts down.

---

## 6. Logging and errors

- **INFO:** successful capture length, start/stop of playback (concise).
- **WARNING:** no element, no text, empty capture.
- **ERROR:** synthesis/play failures with exception type/message.

All logs go to **stderr** by default.

---

## 7. CLI (MVP)

```
python -m narrator [options]
```

| Flag | Meaning |
|------|---------|
| `--verbose` / `-v` | Set logging to DEBUG. |
| `--version` | Print version and exit. |
| `--config PATH` | TOML config; merged with `%USERPROFILE%\.config\...` and `%LOCALAPPDATA%\narrator\config.toml` (later overrides). |
| `--voice NAME` | SSML voice display name (see `--list-voices`). |
| `--rate FLOAT` | Speaking rate (approx 0.5–3.0). |
| `--volume FLOAT` | Audio volume 0.0–1.0. |
| `--speak-hotkey CHORD` | Toggle hover-and-speak (default `ctrl+alt+s` or from config). |
| `--listen-hotkey CHORD` | Toggle listen / STT when enabled (default `ctrl+alt+l` or from config). |
| `--hotkey CHORD` | **Deprecated:** same as `--speak-hotkey`. |
| `--silent` | No beep when capture finds no text. |
| `--list-voices` | List offline voices (registry) and exit. |
| `--hide-console` | Hide the console window (Windows). |
| `--tray` | System tray with Quit; requires optional dependency group `tray` (see [`README.md`](README.md)). |

TOML keys for hotkeys and deprecation of `hotkey` → `speak_hotkey` are summarized in [`narrator/settings_schema.md`](narrator/settings_schema.md).

See also: `pythonw`, batch launchers, and PyInstaller notes in [`README.md`](README.md).

---

## 8. Testing expectations (manual)

Not automated in v1; manual smoke tests:

1. **Notepad** — hover over text, default **speak** chord (`ctrl+alt+s`); expect speech; same chord again stops.
2. **Browser** — hover page content; expect content or partial content per UIA exposure.
3. **Desktop / no UIA text** — expect warning, no crash.

---

## 9. Traceability

| IDEA | Spec section |
|------|----------------|
| CLI + background | §1 |
| Speak / listen chords | §2 |
| Independent speak + listen concurrency | §5 |
| Hover-based, not caret | §3 |
| Top-down content | §3.3 (longest document-like range as proxy) |
| Offline voices | §4 |
