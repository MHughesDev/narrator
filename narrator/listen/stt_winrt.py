"""WinRT continuous speech recognition (dictation)."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from narrator.settings import RuntimeSettings

logger = logging.getLogger(__name__)

# Speech privacy is separate from “microphone works in another app” (see _privacy_error_message).
_PRIVACY_SETTINGS_OPENED = False


def _try_open_speech_privacy_settings() -> None:
    """Open the Speech / inking / typing privacy page once (where 'Get to know me' lives)."""
    global _PRIVACY_SETTINGS_OPENED
    if _PRIVACY_SETTINGS_OPENED:
        return
    _PRIVACY_SETTINGS_OPENED = True
    # Not the same as ms-settings:privacy-speech (online recognition). This URI matches the
    # "Speech, inking & typing privacy" / Get to know me flow from Microsoft's UWP speech docs.
    uri = "ms-settings:privacy-speechtyping"
    try:
        os.startfile(uri)
        logger.info(
            "Opened Windows Settings (%s). Turn ON 'Get to know me' on that page if shown, then try Ctrl+Alt+L again.",
            uri,
        )
    except Exception as e:
        logger.debug("Could not open %s: %s", uri, e)
        logger.info("Open settings manually: Win+R, paste %s, Enter.", uri)


def _privacy_error_message() -> str:
    return (
        "Windows reports: the speech privacy policy was not accepted (this is not fixed by mic working in other apps).\n"
        "You must accept it once on this PC:\n"
        "  1) Settings -> Time & language -> Speech\n"
        "  2) Open 'Speech, inking and typing privacy settings' (same target as Win+R: ms-settings:privacy-speechtyping)\n"
        "  3) Turn ON 'Get to know me' and confirm any dialog (this is what WinRT speech recognition requires).\n"
        "  4) Settings -> Privacy & security -> Speech -> turn ON Online speech recognition.\n"
        "  5) Settings -> Privacy & security -> Microphone -> turn ON Let desktop apps access your microphone.\n"
        "Underlying error details:"
    )


async def run_continuous_dictation(
    stop_event: threading.Event,
    _settings: "RuntimeSettings",
    *,
    on_hypothesis_text: Callable[[str | None], None],
    on_result_text: Callable[[str | None], None],
) -> None:
    from winrt.windows.media.speechrecognition import (
        SpeechRecognitionResultStatus,
        SpeechRecognitionScenario,
        SpeechRecognitionTopicConstraint,
        SpeechRecognizer,
    )

    # Explicit dictation topic (not generic “no constraint”): optimizes for continuous dictation and
    # routes recognition through the dictation web grammar, which supplies punctuation and
    # phrase boundaries much closer to Windows voice typing — provided “Online speech recognition”
    # is ON under Settings → Privacy & security → Speech (offline-only recognition is plain text).
    r = SpeechRecognizer()
    r.constraints.append(
        SpeechRecognitionTopicConstraint(SpeechRecognitionScenario.DICTATION, ""),
    )
    await r.compile_constraints_async()
    logger.info(
        "Listen: Dictation scenario (richer punctuation when Online speech recognition is ON under "
        "Privacy -> Speech). You can also say words like period, comma, or question mark to insert them."
    )
    if stop_event.is_set():
        try:
            r.close()
        except Exception as e:
            logger.debug("SpeechRecognizer.close: %s", e)
        return

    session = r.continuous_recognition_session
    hypothesis_token = None
    result_token = None

    def on_hypothesis(_sender, args) -> None:
        try:
            h = args.hypothesis
            on_hypothesis_text(h.text if h else None)
        except Exception as e:
            logger.exception("Hypothesis handler failed: %s", e)

    def on_result(_sender, args) -> None:
        try:
            res = args.result
            if res.status != SpeechRecognitionResultStatus.SUCCESS:
                return
            on_result_text(res.text)
        except Exception as e:
            logger.exception("Result handler failed: %s", e)

    try:
        hypothesis_token = r.add_hypothesis_generated(on_hypothesis)
        result_token = session.add_result_generated(on_result)
        await session.start_async()

        while not stop_event.is_set():
            await asyncio.sleep(0.05)

        await session.stop_async()
    except OSError as e:
        winerr = getattr(e, "winerror", None)
        es = str(e).lower()
        # Speech privacy policy / Get to know me — not the same as general microphone access.
        if (
            winerr == -2147199735
            or "privacy" in es
            or "speech privacy policy" in es
        ):
            _try_open_speech_privacy_settings()
            logger.error("%s winerror=%s %r", _privacy_error_message(), winerr, e)
        else:
            logger.error("Speech recognition failed (winerror=%s): %s", winerr, e)
    except Exception as e:
        logger.exception("Listen session error: %s", e)
    finally:
        if result_token is not None:
            try:
                session.remove_result_generated(result_token)
            except Exception as e:
                logger.debug("remove_result_generated: %s", e)
        if hypothesis_token is not None:
            try:
                r.remove_hypothesis_generated(hypothesis_token)
            except Exception as e:
                logger.debug("remove_hypothesis_generated: %s", e)
        try:
            r.close()
        except Exception as e:
            logger.debug("SpeechRecognizer.close: %s", e)
