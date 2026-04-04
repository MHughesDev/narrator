"""Phrase-level punctuation and casing helpers when WinRT dictation omits punctuation.

There is no access to audio prosody in our pipeline, so question vs statement is inferred
from common spoken question shapes (auxiliary / WH words at the start of a phrase).
"""

from __future__ import annotations

import re

# Spoken questions often start with these (phrase = one WinRT final result).
_QUESTION_START = re.compile(
    r"^(?:(?:can|could|would|should|must|shall|may|might|do|does|did|is|are|was|were|have|has|had|will|"
    r"am|who|what|when|where|why|how|which|whose|whom)\b|"
    r"(?:are you|can you|could you|would you|do you|does it|is it|is this|is that|was it|were you|"
    r"have you|has it|will you|shall we|should i|should we|do we|did we|did you|could it|would it|"
    r"can it|can we|can i|may i|got any|any idea))\b",
    re.I,
)

# Words often wrongly title-cased mid-sentence by the recognizer (streaming fixes).
_MID_SENTENCE_LOWER = frozenset(
    """
    the a an and or but nor so if as at to of in on for with from by
    can could would should must shall may might do does did is are was were am
    have has had will would
    when what why how who which where whom whose
    are you can you could you would you do you does it is it
    """.split()
)


def _continuing_sentence(partial: str) -> bool:
    """True if the visible partial is mid-sentence (no strong boundary yet)."""
    p = partial.rstrip()
    if not p:
        return False
    return p[-1] not in ".?!\n"


def soften_misleading_title_case(partial: str, suffix: str) -> str:
    """
    If the recognizer starts a new word with Title Case mid-sentence, lower-case it when the
    word is usually a function word (not perfect: skips all-caps and odd casing).
    """
    if not suffix or not _continuing_sentence(partial):
        return suffix
    leading_ws_len = len(suffix) - len(suffix.lstrip())
    head = suffix[:leading_ws_len]
    rest = suffix[leading_ws_len:]
    if not rest:
        return suffix
    m = re.match(r"([A-Za-z']+)(.*)", rest, re.DOTALL)
    if not m:
        return suffix
    word, tail = m.group(1), m.group(2)
    if (
        len(word) > 1
        and word[0].isupper()
        and word[1:].islower()
        and word.lower() in _MID_SENTENCE_LOWER
    ):
        return head + word.lower() + tail
    return suffix


_INFORMAL_QUESTION_TAIL = re.compile(
    r"(?:you hear me(?:\s+at\s+all)?|do you hear me|can you hear me|are you there|you with me|you know what i mean)\s*$",
    re.I,
)


def trailing_punctuation_to_add(phrase: str) -> str:
    """
    Return ``?``, ``.``, or ``''`` to append after a dictation phrase when the engine
    emitted no terminal punctuation.
    """
    stripped = phrase.rstrip()
    if not stripped:
        return ""
    if stripped[-1] in ".?!":
        return ""
    core = stripped.strip()
    if _QUESTION_START.match(core) or _INFORMAL_QUESTION_TAIL.search(core):
        return "?"
    return "."

