"""Optional system tray: Quit stops worker and exits (requires ``pip install narrator[tray]``)."""

from __future__ import annotations

import logging
import queue
import threading
from typing import TYPE_CHECKING

from narrator import speech
from narrator.hotkey import build_listener
from narrator.protocol import SHUTDOWN

if TYPE_CHECKING:
    from narrator.settings import RuntimeSettings

logger = logging.getLogger(__name__)


def _tray_icon_image():
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (64, 64), color=(28, 28, 52))
    draw = ImageDraw.Draw(img)
    draw.rectangle((8, 8, 56, 56), outline=(180, 180, 220), width=2)
    try:
        font = ImageFont.load_default()
    except OSError:
        font = None
    draw.text((24, 20), "N", fill=(220, 220, 255), font=font)
    return img


def run_with_tray(
    speak_queue: queue.Queue,
    listen_queue: queue.Queue,
    speak_thread: threading.Thread,
    listen_thread: threading.Thread,
    settings: "RuntimeSettings",
    speak_display: str,
    listen_display: str,
) -> None:
    import pystray

    def on_quit(_icon: pystray.Icon, _item: object = None) -> None:
        logger.info("Tray: quit")
        speak_queue.put(SHUTDOWN)
        listen_queue.put(SHUTDOWN)
        speech.stop_playback()
        speak_thread.join(timeout=30.0)
        listen_thread.join(timeout=30.0)
        _icon.stop()

    menu = pystray.Menu(pystray.MenuItem("Quit", on_quit))
    tip = f"narrator — speak {speak_display} (hover); listen {listen_display} (dictation)"
    icon = pystray.Icon(
        "narrator",
        _tray_icon_image(),
        tip,
        menu,
    )

    def hotkey_runner() -> None:
        try:
            with build_listener(
                speak_queue,
                listen_queue,
                speak_hotkey=settings.speak_hotkey,
                listen_hotkey=settings.listen_hotkey,
            ) as hotkeys:
                hotkeys.join()
        except Exception:
            logger.exception("Hotkey listener failed")

    hk_thread = threading.Thread(target=hotkey_runner, daemon=True, name="narrator-hotkey")
    hk_thread.start()

    logger.info(
        "Tray active — speak %s (hover); listen %s (dictation). Right-click icon → Quit.",
        speak_display,
        listen_display,
    )
    icon.run()
