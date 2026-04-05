"""Split preprocessed speak text into TTS-sized segments for long documents."""

from __future__ import annotations

import re
from typing import Iterator

# Sentence boundaries (space after punctuation); ``…`` for ellipsis-heavy prose.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")

_MIN_CHUNK = 1024
_MAX_CHUNK = 100_000

# Coqui XTTS ~400 token limit per ``tts_to_file``; the **en** tokenizer warns around **250 chars**.
# ~242 keeps margin for PDF extraction oddities while cutting segment count vs 220.
XTTS_MAX_CHARS_PER_SEGMENT = 242


def clamp_chunk_max_chars(n: int, *, min_floor: int | None = None) -> int:
    """``<= 0`` = disabled (entire document per synthesis). Else clamp to sane bounds."""
    if n <= 0:
        return 0
    floor = _MIN_CHUNK if min_floor is None else min_floor
    return max(floor, min(_MAX_CHUNK, n))


def effective_speak_chunk_max_chars(speak_engine: str, speak_chunk_max_chars: int) -> int:
    """
    XTTS has a hard ~400-token limit per ``tts_to_file`` call; large ``speak_chunk_max_chars`` must
    not be passed through unchanged or synthesis fails on long sentences.
    """
    if speak_engine != "xtts":
        return speak_chunk_max_chars
    cap = XTTS_MAX_CHARS_PER_SEGMENT
    if speak_chunk_max_chars <= 0:
        return cap
    return min(speak_chunk_max_chars, cap)


def iter_tts_chunks(
    text: str,
    max_chars: int,
    *,
    min_chunk_floor: int | None = None,
) -> Iterator[str]:
    """
    Yield segments of at most ``max_chars`` characters, preferring paragraph and sentence boundaries.

    Expects **preprocessed** text (``prepare_speak_text_*``) but **before** ``apply_speak_prosody`` so
    newlines still reflect document structure where possible.

    If ``max_chars`` is 0 (chunking disabled), yields the whole string once.

    ``min_chunk_floor`` overrides the default minimum segment size (1024) so engines like XTTS can
    use smaller segments without ``clamp_chunk_max_chars`` inflating user values.
    """
    if max_chars > 0:
        mc = (
            clamp_chunk_max_chars(max_chars, min_floor=min_chunk_floor)
            if min_chunk_floor is not None
            else clamp_chunk_max_chars(max_chars)
        )
    else:
        mc = 0
    if not text or not text.strip():
        return
    t = text.strip()
    if mc <= 0 or len(t) <= mc:
        yield t
        return

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", t) if p.strip()]
    if not paragraphs:
        yield t
        return

    buf: list[str] = []
    buf_len = 0

    def flush_buf() -> Iterator[str]:
        nonlocal buf, buf_len
        if not buf:
            return
        joined = "\n\n".join(buf)
        buf = []
        buf_len = 0
        yield joined

    for para in paragraphs:
        if len(para) > mc:
            yield from flush_buf()
            yield from _split_oversized_block(para, mc)
            continue

        sep = 2 if buf else 0  # "\n\n"
        if buf_len + sep + len(para) <= mc:
            buf.append(para)
            buf_len += sep + len(para)
        else:
            yield from flush_buf()
            buf = [para]
            buf_len = len(para)

    yield from flush_buf()


def _split_oversized_block(para: str, max_chars: int) -> Iterator[str]:
    """Split a single huge paragraph by sentences, then hard-wrap."""
    if len(para) <= max_chars:
        yield para
        return

    parts = _SENTENCE_SPLIT.split(para)
    buf: list[str] = []
    buf_len = 0

    def flush_sent() -> Iterator[str]:
        nonlocal buf, buf_len
        if not buf:
            return
        s = " ".join(buf).strip()
        buf = []
        buf_len = 0
        if s:
            yield s

    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(p) > max_chars:
            yield from flush_sent()
            yield from _hard_wrap(p, max_chars)
            continue

        sep = 1 if buf else 0
        if buf_len + sep + len(p) <= max_chars:
            buf.append(p)
            buf_len += sep + len(p)
        else:
            for s in flush_sent():
                if len(s) > max_chars:
                    yield from _hard_wrap(s, max_chars)
                else:
                    yield s
            buf = [p]
            buf_len = len(p)

    for s in flush_sent():
        if len(s) > max_chars:
            yield from _hard_wrap(s, max_chars)
        else:
            yield s


def _hard_wrap(s: str, max_chars: int) -> Iterator[str]:
    """Last resort: break at whitespace (any Unicode space); if none in 2nd half, cut at ``max_chars``."""
    rest = s
    half = max_chars // 2
    while len(rest) > max_chars:
        window = rest[:max_chars]
        cut = max_chars
        for i in range(max_chars - 1, half - 1, -1):
            if i < len(window) and window[i].isspace():
                cut = i + 1
                break
        piece = rest[:cut].strip()
        rest = rest[cut:].strip()
        if piece:
            yield piece
    if rest:
        yield rest


def extract_chunk_context_tail(prev_chunk_text: str, max_chars: int) -> str:
    """
    Return a suffix of ``prev_chunk_text`` to prepend to the next chunk for continuity (prefer last
    complete sentences, then a word-aligned suffix). Empty if ``max_chars`` <= 0 or no text.
    """
    t = prev_chunk_text.strip()
    if not t or max_chars <= 0:
        return ""
    if len(t) <= max_chars:
        return t
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(t) if p.strip()]
    if not parts:
        return _tail_word_aligned(t, max_chars)
    acc: list[str] = []
    n = 0
    for p in reversed(parts):
        sep = 1 if acc else 0
        if n + sep + len(p) <= max_chars:
            acc.insert(0, p)
            n += sep + len(p)
        else:
            break
    if acc:
        return " ".join(acc)
    return _tail_word_aligned(parts[-1], max_chars)


def _tail_word_aligned(s: str, max_chars: int) -> str:
    if len(s) <= max_chars:
        return s
    window = s[-max_chars:]
    sp = window.find(" ")
    if sp > 0 and sp + 1 < len(window):
        return window[sp + 1 :].strip()
    return window.strip()


def trim_context_to_synth_budget(context: str, utterance: str, max_synth_chars: int) -> str:
    """
    Shorten ``context`` from the left so ``len(context) + 1 + len(utterance) <= max_synth_chars``.
    Returns ``context`` unchanged if already within budget or ``utterance`` alone exceeds budget.
    """
    u = utterance.strip()
    c = context.strip()
    if not c:
        return ""
    sep = 1
    while c and sep + len(c) + len(u) > max_synth_chars:
        ws = c.find(" ")
        if ws < 0:
            c = ""
            break
        c = c[ws + 1 :].strip()
    return c


def split_raw_for_streaming_preprocess(raw: str, budget_chars: int) -> tuple[str, str]:
    """
    Split captured text at paragraph boundaries so the **first** bundle can be preprocessed without a
    full-document pass. ``budget_chars`` is a rough **raw** character target (typically
    ``effective_chunk_max * speak_preprocess_initial_chunks``, with a minimum floor in the worker).

    Returns ``(prefix, suffix)`` stripped paragraphs joined with ``\\n\\n``. If the whole string fits
    the budget, ``suffix`` is empty. If a single paragraph exceeds ``budget_chars``, hard-splits at
    ``budget_chars``.
    """
    if budget_chars <= 0 or not raw:
        return (raw.strip() if raw else ""), ""
    t = raw.strip()
    if len(t) <= budget_chars:
        return t, ""
    paras = [p.strip() for p in re.split(r"\n\s*\n+", t) if p.strip()]
    if not paras:
        return t[:budget_chars], t[budget_chars:].strip()
    acc: list[str] = []
    n = 0
    for p in paras:
        add = len(p) if not acc else 2 + len(p)
        if acc and n + add > budget_chars:
            break
        acc.append(p)
        n += add
        if n >= budget_chars:
            break
    if not acc:
        return t[:budget_chars], t[budget_chars:].strip()
    prefix = "\n\n".join(acc)
    rest = paras[len(acc) :]
    suffix = "\n\n".join(rest) if rest else ""
    return prefix, suffix


def merge_trailing_short_chunks(
    chunks: list[str],
    max_chars: int,
    *,
    min_tail_chars: int = 72,
) -> list[str]:
    """
    If the **last** segment is very short, merge it into the previous one so the TTS model gets more
    context (reduces “robotic” prosody on tiny tails). Only applied when the join fits in ``max_chars``.
    """
    if max_chars <= 0 or len(chunks) < 2:
        return chunks
    last = chunks[-1]
    if len(last) >= min_tail_chars:
        return chunks
    prev = chunks[-2]
    sep = "\n\n"
    if len(prev) + len(sep) + len(last) <= max_chars:
        return chunks[:-2] + [prev + sep + last]
    return chunks
