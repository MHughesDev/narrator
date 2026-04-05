"""Windows WH_KEYBOARD_LL hook: consume speak/listen chord key events so they do not reach other apps.

``pynput.GlobalHotKeys`` cannot suppress only our chords; ``suppress=True`` swallows every key.
We install a low-level hook in a thread with a message loop and return non-zero from the hook
procedure to block propagation (see ``LowLevelKeyboardProc``).

This does **not** override secure attention sequences (e.g. Ctrl+Alt+Del), exclusive-mode games,
or every elevation/UAC scenario — those are OS limits, not something user code can disable.
"""

from __future__ import annotations

import ctypes
import logging
import queue
import re
import threading
from ctypes import wintypes

logger = logging.getLogger(__name__)

from narrator.protocol import LISTEN_TOGGLE, SPEAK_TOGGLE

WH_KEYBOARD_LL = 13
HC_ACTION = 0
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012

VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_MENU = 0x12  # Alt
VK_LWIN = 0x5B
VK_RWIN = 0x5C

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


_LP_KBDLL = ctypes.POINTER(_KBDLLHOOKSTRUCT)

# LRESULT / intptr-sized return for LowLevelKeyboardProc
_LLPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM,
)


def _parse_mods_and_trigger(spec: str) -> tuple[frozenset[str], str]:
    """Split ``ctrl+alt+s``-style spec into modifiers and single key token (same rules as ``parse_hotkey_spec``)."""
    s = spec.strip().lower().replace(" ", "")
    parts = [p for p in s.split("+") if p]
    if not parts:
        raise ValueError("empty hotkey")

    mod_aliases = {
        "ctrl": "ctrl",
        "control": "ctrl",
        "alt": "alt",
        "shift": "shift",
        "win": "win",
        "meta": "win",
        "super": "win",
    }
    mods: list[str] = []
    keys: list[str] = []
    for p in parts:
        if p in mod_aliases:
            mods.append(mod_aliases[p])
        else:
            keys.append(p)
    if len(keys) != 1:
        raise ValueError(f"hotkey must have exactly one non-modifier key, got {keys!r} in {spec!r}")
    return frozenset(mods), keys[0]


def _token_to_vk(token: str) -> int:
    t = token.lower()
    if len(t) == 1:
        if "a" <= t <= "z":
            return ord(t.upper())
        if t.isdigit():
            return ord(t)
    m = re.fullmatch(r"f(\d{1,2})", t)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 24:
            return 0x70 + (n - 1)  # VK_F1 = 0x70
    specials = {
        "space": 0x20,
        "tab": 0x09,
        "enter": 0x0D,
        "return": 0x0D,
        "escape": 0x1B,
        "esc": 0x1B,
        "backspace": 0x08,
    }
    if t in specials:
        return specials[t]
    raise ValueError(f"unsupported key token {token!r} for Win32 hook")


def _mods_down(need: frozenset[str]) -> bool:
    def down(vk: int) -> bool:
        return (user32.GetAsyncKeyState(vk) & 0x8000) != 0

    if "ctrl" in need and not down(VK_CONTROL):
        return False
    if "alt" in need and not down(VK_MENU):
        return False
    if "shift" in need and not down(VK_SHIFT):
        return False
    if "win" in need and not (down(VK_LWIN) or down(VK_RWIN)):
        return False
    return True


def _is_injected(kb: _KBDLLHOOKSTRUCT) -> bool:
    LLKHF_INJECTED = 0x10
    LLKHF_LOWER_IL_INJECTED = 0x02
    return (kb.flags & (LLKHF_INJECTED | LLKHF_LOWER_IL_INJECTED)) != 0


class SuppressingHotKeyHook:
    """Install WH_KEYBOARD_LL; enqueue toggles and swallow matching chord events system-wide."""

    def __init__(
        self,
        speak_queue: queue.Queue,
        listen_queue: queue.Queue,
        *,
        speak_hotkey: str,
        listen_hotkey: str,
    ) -> None:
        smods, stok = _parse_mods_and_trigger(speak_hotkey)
        lmods, ltok = _parse_mods_and_trigger(listen_hotkey)
        self._svk = _token_to_vk(stok)
        self._lvk = _token_to_vk(ltok)
        self._smods = smods
        self._lmods = lmods
        if self._svk == self._lvk and smods == lmods:
            raise ValueError("speak and listen hotkeys must differ")

        self._speak_queue = speak_queue
        self._listen_queue = listen_queue

        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._hook_handle: ctypes.c_void_p | None = None
        self._proc_ref: _LLPROC | None = None
        self._start_error: BaseException | None = None

        # Suppress key-up once after we swallowed the matching key-down (avoids orphan keyups)
        self._swallow_s_up = False
        self._swallow_l_up = False
        self._swallow_rate_plus_up = False
        self._swallow_rate_minus_up = False

        # Edge-detect the trigger key: do not rely on LLKHF repeat bit alone. After we swallow
        # chord key-ups, the next physical press can be misclassified as autorepeat and skipped,
        # so the second toggle (stop) never enqueues.
        self._speak_trigger_held = False
        self._listen_trigger_held = False
        self._rate_plus_held = False
        self._rate_minus_held = False

    def __enter__(self) -> SuppressingHotKeyHook:
        self._thread = threading.Thread(target=self._run, name="narrator-hotkey-hook", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=10.0)
        if not self._ready.is_set():
            raise RuntimeError("keyboard hook thread failed to start")
        if self._start_error is not None:
            self._thread.join(timeout=5.0)
            raise self._start_error
        return self

    def __exit__(self, *args: object) -> None:
        if self._thread is None:
            return
        tid = self._thread.ident
        if tid is not None:
            user32.PostThreadMessageW(tid, WM_QUIT, 0, 0)
        self._thread.join(timeout=10.0)
        self._thread = None

    def join(self, timeout: float | None = None) -> None:
        """Block until the hook thread ends (same role as ``pynput.keyboard.GlobalHotKeys.join``)."""
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        self_ref = self

        def low_level_proc(n_code: int, w_param: wintypes.WPARAM, l_param: wintypes.LPARAM) -> int:
            """Must not raise: an unhandled exception here can terminate the process."""
            hhk = self_ref._hook_handle
            try:
                if n_code != HC_ACTION:
                    return int(user32.CallNextHookEx(hhk, n_code, w_param, l_param) or 0)

                kb = ctypes.cast(l_param, _LP_KBDLL).contents
                if _is_injected(kb):
                    return int(user32.CallNextHookEx(hhk, n_code, w_param, l_param) or 0)

                vk = int(kb.vkCode)
                msg = int(w_param)

                if msg in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    if vk == self_ref._svk and _mods_down(self_ref._smods):
                        if not self_ref._speak_trigger_held:
                            self_ref._speak_trigger_held = True
                            self_ref._speak_queue.put(SPEAK_TOGGLE)
                            self_ref._swallow_s_up = True
                        return 1
                    if vk == self_ref._lvk and _mods_down(self_ref._lmods):
                        if not self_ref._listen_trigger_held:
                            self_ref._listen_trigger_held = True
                            self_ref._listen_queue.put(LISTEN_TOGGLE)
                            self_ref._swallow_l_up = True
                        return 1

                if msg in (WM_KEYUP, WM_SYSKEYUP):
                    if vk == self_ref._svk:
                        self_ref._speak_trigger_held = False
                        if self_ref._swallow_s_up:
                            self_ref._swallow_s_up = False
                            return 1
                    if vk == self_ref._lvk:
                        self_ref._listen_trigger_held = False
                        if self_ref._swallow_l_up:
                            self_ref._swallow_l_up = False
                            return 1

                return int(user32.CallNextHookEx(hhk, n_code, w_param, l_param) or 0)
            except Exception:
                logger.exception("Keyboard hook callback failed; passing event through")
                try:
                    return int(user32.CallNextHookEx(hhk, n_code, w_param, l_param) or 0)
                except Exception:
                    return 0

        try:
            self._proc_ref = _LLPROC(low_level_proc)
            self._hook_handle = user32.SetWindowsHookExW(
                WH_KEYBOARD_LL,
                self._proc_ref,
                None,
                0,
            )
            if not self._hook_handle:
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException as e:
            self._start_error = e
        finally:
            self._ready.set()

        if self._start_error is not None:
            return

        try:
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            if self._hook_handle:
                user32.UnhookWindowsHookEx(self._hook_handle)
                self._hook_handle = None
