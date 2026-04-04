"""Split preprocessed speak text into TTS-sized segments for long documents."""

from __future__ import annotations

import re
from typing import Iterator

# Sentence boundaries (space after punctuation); ``…`` for ellipsis-heavy prose.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")

_MIN_CHUNK = 1024
_MAX_CHUNK = 100_000


def clamp_chunk_max_chars(n: int) -> int:
    """``<= 0`` = disabled (entire document per synthesis). Else clamp to sane bounds."""
    if n <= 0:
        return 0
    return max(_MIN_CHUNK, min(_MAX_CHUNK, n))


def iter_tts_chunks(text: str, max_chars: int) -> Iterator[str]:
    """
    Yield segments of at most ``max_chars`` characters, preferring paragraph and sentence boundaries.

    Expects **preprocessed** text (``prepare_speak_text_*``) but **before** ``apply_speak_prosody`` so
    newlines still reflect document structure where possible.

    If ``max_chars`` is 0 (chunking disabled), yields the whole string once.
    """
    mc = clamp_chunk_max_chars(max_chars) if max_chars > 0 else 0
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
    """Last resort: break at spaces; if no space, cut at ``max_chars``."""
    rest = s
    while len(rest) > max_chars:
        window = rest[:max_chars]
        cut = window.rfind(" ")
        if cut < max_chars // 2:
            cut = max_chars
        piece = rest[:cut].strip()
        rest = rest[cut:].strip()
        if piece:
            yield piece
    if rest:
        yield rest
