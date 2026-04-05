"""Global hotkey -> worker queues.

On Windows, a low-level keyboard hook consumes matching chords so they are not
delivered to other applications (see :mod:`narrator.win32_hotkey_hook`).
Elsewhere, ``pynput.keyboard.GlobalHotKeys`` is used without suppression.
"""

from __future__ import annotations

import queue
import re
import sys

from narrator.protocol import LISTEN_TOGGLE, SPEAK_TOGGLE


def parse_hotkey_spec(spec: str) -> str:
    """
    Parse ``ctrl+alt+s``-style specs into a ``pynput`` GlobalHotKeys chord like ``<ctrl>+<alt>+s``.
    """
    s = spec.strip().lower().replace(" ", "")
    parts = [p for p in s.split("+") if p]
    if not parts:
        raise ValueError("empty hotkey")

    mod_map = {
        "ctrl": "<ctrl>",
        "control": "<ctrl>",
        "alt": "<alt>",
        "shift": "<shift>",
        "win": "<cmd>",
        "meta": "<cmd>",
        "super": "<cmd>",
    }
    mods: list[str] = []
    keys: list[str] = []
    for p in parts:
        if p in mod_map:
            mods.append(mod_map[p])
        else:
            keys.append(p)
    if len(keys) != 1:
        raise ValueError(f"hotkey must have exactly one non-modifier key, got {keys!r} in {spec!r}")
    key = keys[0]
    if re.fullmatch(r"f\d{1,2}", key):
        chord_key = f"<{key}>"
    elif len(key) == 1:
        chord_key = key
    else:
        chord_key = f"<{key}>"
    if mods:
        return "+".join(mods + [chord_key])
    return chord_key


def build_listener(
    speak_queue: queue.Queue,
    listen_queue: queue.Queue,
    *,
    speak_hotkey: str = "ctrl+alt+s",
    listen_hotkey: str = "ctrl+alt+l",
):
    """Register both chords; speak → ``speak_queue``, listen → ``listen_queue``.

    Returns a context manager with ``join()`` (Windows: :class:`narrator.win32_hotkey_hook.SuppressingHotKeyHook`).
    """
    speak_chord = parse_hotkey_spec(speak_hotkey)
    listen_chord = parse_hotkey_spec(listen_hotkey)
    if speak_chord == listen_chord:
        raise ValueError(f"speak and listen hotkeys must differ, both resolved to {speak_chord!r}")

    if sys.platform == "win32":
        from narrator.win32_hotkey_hook import SuppressingHotKeyHook

        return SuppressingHotKeyHook(
            speak_queue,
            listen_queue,
            speak_hotkey=speak_hotkey,
            listen_hotkey=listen_hotkey,
        )

    from pynput import keyboard

    def _on_speak() -> None:
        speak_queue.put(SPEAK_TOGGLE)

    def _on_listen() -> None:
        listen_queue.put(LISTEN_TOGGLE)

    return keyboard.GlobalHotKeys(
        {
            speak_chord: _on_speak,
            listen_chord: _on_listen,
        }
    )
