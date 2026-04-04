"""Neural punctuation restoration for raw dictation (optional ``deepmultilingualpunctuation``).

Designed for transcribed speech (Europarl-trained FullStop model): restores ``. , ? - :`` and
capitalization. Install: ``pip install "narrator[listen]"`` or ``pip install deepmultilingualpunctuation torch transformers``.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_model: Any = None  # PunctuationModel | False after failed import/load


def _get_model() -> Any:
    """Lazy singleton; ``False`` means unavailable (do not retry every phrase)."""
    global _model
    if _model is not None:
        return _model if _model is not False else None
    try:
        from deepmultilingualpunctuation import PunctuationModel
    except ImportError:
        logger.info(
            "Neural punctuation not installed. For automatic commas, periods, and questions without "
            "saying 'period' or 'question mark', run: pip install \"narrator[listen]\" "
            "(or: pip install deepmultilingualpunctuation torch transformers).",
        )
        _model = False
        return None
    try:
        logger.info("Loading FullStop punctuation model (first run may download ~500MB from Hugging Face)...")
        _model = PunctuationModel()
        logger.info("FullStop punctuation model ready.")
    except Exception as e:
        logger.warning("Could not load neural punctuation model: %s", e)
        _model = False
        return None
    return _model


def neural_punctuation_active() -> bool:
    return _get_model() is not None


def restore_phrase(text: str) -> str:
    """Return text with restored punctuation, or unchanged if the model is unavailable."""
    if not text.strip():
        return text
    m = _get_model()
    if m is None:
        return text
    try:
        return m.restore_punctuation(text)
    except Exception as e:
        logger.debug("restore_punctuation failed: %s", e)
        return text


def restore_document(text: str) -> str:
    """Full-session pass: same model, full context (best quality for long dictation)."""
    return restore_phrase(text)
