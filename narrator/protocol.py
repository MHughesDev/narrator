"""Queue messages between hotkey thread and workers.

Defaults (configurable): **Ctrl+Alt+S** → ``speak_toggle`` (TTS from hover); **Ctrl+Alt+L** → ``listen_toggle`` (STT into focus).

**Independence:** Speak and listen use **separate** ``queue.Queue`` instances and **separate** worker threads. They **must not** cancel, pause, or block each other. **Simultaneous** operation is allowed and expected (e.g. TTS playing while dictation is active, or both toggled in any order). Only process shutdown coordinates both via ``shutdown``.

``speak_toggle`` — request TTS from text under the pointer (hover + toggle).
``listen_toggle`` — start/stop microphone dictation into the focused field.
``shutdown`` — stop workers and release resources.
``listen_session_ended`` — internal: dictation thread exited (placed by the listen worker, not the hotkey).
``speak_rate_up`` / ``speak_rate_down`` — adjust speaking rate during WAV playback only (Ctrl+Alt+Plus / Minus).
"""

from __future__ import annotations

from typing import Literal

QueueMessage = Literal[
    "speak_toggle",
    "listen_toggle",
    "shutdown",
    "listen_session_ended",
    "speak_rate_up",
    "speak_rate_down",
]

SPEAK_TOGGLE: QueueMessage = "speak_toggle"
LISTEN_TOGGLE: QueueMessage = "listen_toggle"
SHUTDOWN: QueueMessage = "shutdown"
LISTEN_SESSION_ENDED: QueueMessage = "listen_session_ended"
SPEAK_RATE_UP: QueueMessage = "speak_rate_up"
SPEAK_RATE_DOWN: QueueMessage = "speak_rate_down"
