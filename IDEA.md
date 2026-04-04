# Narrator — product idea (MVP)

## Problem

You want a **minimal**, **Windows-native** assistant: run a small tool from the **command line**, keep it **running in the background**, then use **two global hotkeys**:

- **Speak (TTS):** read text aloud with **built-in offline Windows voices** — default **Ctrl+Alt+S** (configurable).
- **Listen (STT):** dictate into the **focused** text field with Windows speech recognition — default **Ctrl+Alt+L** (configurable).

**No cloud TTS** is required for the speak path in v1.

The **speak** interaction is **not** “read from the typing caret” and **not** “read whatever window has keyboard focus” as the primary rule. For TTS, content is anchored to **where the mouse pointer is** when you press the **speak** hotkey: resolve the UI under the pointer and speak the associated content **from the top downward** (reading order).

## MVP goals

- **Windows only**, **Python-first**, **minimum moving parts** and **minimal lines of code** where practical.
- **Offline TTS:** use **speech voices already installed** on the machine for read-aloud (no paid or cloud voices required for v1).
- **CLI entry:** start the narrator from a terminal; it **stays running** until stopped.
- **Global hotkeys (defaults):**
  - **Ctrl+Alt+S** — **toggle speak:** first press starts capture + synthesis + playback; second press stops in-progress speech.
  - **Ctrl+Alt+L** — **toggle listen:** start/stop dictation into the focused control.
- **No coupling:** Speak and listen are **independent**. Either can be on or off without affecting the other; **both may run at once** (separate queues and workers).
- **Pointer-based targeting for speak:** on speak-toggle-start, use **current mouse screen coordinates** and resolve the **accessibility element under the pointer** (e.g. UI Automation **ElementFromPoint**), then obtain text for the appropriate **document-like** container when possible.
- **Reading order (speak):** speak from the **top of that content** **downward** — not from the insertion caret.
- Prefer the **most modern local Windows speech path** available to Python for **synthesis** (avoid stacks that only surface older SAPI voice lists if they hide newer preinstalled voices).

## Non-goals (v1)

- Universal guarantees across **every** Windows application (games, fully custom-drawn UIs, bitmap-only surfaces may not expose text).
- Full document pipeline for every format (`.pdf`, browser internals) as separate parsers — v1 assumes **OS accessibility** exposes enough structure where possible.
- Rich UI (tray wizard, settings app) — optional later; v1 can stay CLI + hotkey.
- Cloud / API-based neural voices for TTS.

## User workflow

1. Start the tool from the command line.
2. **Speak:** Hover over the **page / pane / control** whose text you want heard. Press **Ctrl+Alt+S** (or your `speak_hotkey`) → narration **starts from the top** of the resolved content. Press **Ctrl+Alt+S** again to **stop** speech.
3. **Listen:** Click into a text field. Press **Ctrl+Alt+L** (or your `listen_hotkey`) → dictation **on**; press again → dictation **off**.

## Proposed technical direction (high level)

| Area | Direction |
|------|-----------|
| Runtime | Python |
| Long-running process | One process: **hotkey listener** + **workers** (queues) so hotkey callbacks stay non-blocking |
| Hotkeys | Global registration; **Ctrl+Alt+S** → speak queue, **Ctrl+Alt+L** → listen queue (both configurable) |
| Text capture (speak) | At **speak** hotkey: **`GetCursorPos`** → **ElementFromPoint** (UI Automation) → normalize to a **document** or readable parent → extract **ordered** text |
| Speech (TTS) | Windows **local** synthesis via WinRT `SpeechSynthesizer` |
| Speech (STT) | WinRT speech recognition + typing into focus (`narrator.listen`) |

## Voice baseline (this machine)

Registry inspection on the development PC showed **OneCore** and **classic** token names including:

- `MSTTS_V110_enUS_DavidM`
- `MSTTS_V110_enUS_MarkM`
- `MSTTS_V110_enUS_ZiraM`
- plus related `TTS_MS_EN-US_*` style entries

v1 should **enumerate at runtime** on the user’s PC; the list above is a **snapshot**, not a guarantee for all machines.

## Risks and assumptions

- **Hotkey conflict:** Defaults use **Ctrl+Alt** to avoid **Ctrl+S** (save) and **Ctrl+L** (browser address bar, etc.); users remap via CLI/TOML if a chord still conflicts.
- **Hover ≠ perfect “page”:** the leaf element under the pointer may be a small control; the implementation must **walk up** to a sensible **container** for “page-like” reading. Behavior will be **best-effort** per app framework.
- **Caret ignored for speak:** some users expect reading from the insertion point; **speak** intentionally uses pointer hit-testing for v1.
- **Security / elevation:** low-level hooks and automation can behave differently across **elevated** vs non-elevated apps.
- **Clipboard:** not the primary model for speak capture unless order and scope are preserved; prefer **UI Automation** first.

## Open questions (for architecture / spec docs)

- **Normalization rules:** when to stop walking up the UIA tree (document, web area, scrollable pane, etc.).
- **Stop semantics (speak):** if speech is idle, does the **speak** chord **no-op** or **re-read**? (Default: toggle only affects **in-progress** speech vs **start new read**.)
- **pythonw** vs console process: whether the background process should hide the console window after launch.

## Next documents

1. **Architecture** — modules, dependencies, threading model, Windows API boundaries.
2. **Spec** — hotkey lifecycle, capture algorithm, failure modes, per-target expectations.
