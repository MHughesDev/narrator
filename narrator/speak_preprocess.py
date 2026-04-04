"""Post-process captured text before TTS: strip links, math, markup, citations, technical tokens, chrome, emoji."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from narrator.settings import RuntimeSettings

# Unicode Mathematical Alphanumeric Symbols
_U_MATH_ALNUM = re.compile(r"[\U0001d400-\U0001d7ff]")

# Paths: Windows drive, UNC, common Unix prefixes
_PATH_RE = re.compile(
    r"(?:"
    r"\b[A-Za-z]:\\[^\s<>\|\"]+"  # C:\...
    r"|\\\\[^\s<>\|\"]+"  # \\server\...
    r"|(?:/Users|/home|/usr|/var|/tmp|/opt)(?:/[^\s/]+)+"
    r")",
    re.I,
)

# UUID v4-style (and generic hex-dash form)
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)

_HEX_WORD_RE = re.compile(r"\b0x[0-9a-fA-F]+\b", re.I)

# Long hex / base16 blobs (hashes)
_HASH_LIKE_RE = re.compile(r"\b[a-fA-F0-9]{32,}\b")

_EMAIL_RE = re.compile(
    r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b"
)

# Academic-style (Name, 2020) / (Name et al., 2020)
_CITE_PAREN_RE = re.compile(
    r"\(\s*[A-Z][a-zA-Z'\-]+(?:\s+et\s+al\.)?(?:\s*,\s*[A-Z][a-zA-Z'\-]+)*(?:\s*,\s*\d{4})\s*\)"
)

# "Page 3 of 47" / "page 12 of 100"
_PAGE_OF_RE = re.compile(r"(?i)\bpage\s+\d+\s+of\s+\d+\b")

# Line-start Figure / Table labels
_FIGURE_LINE_RE = re.compile(
    r"(?im)^\s*(?:figure|fig\.|table)\s+\d+(?:\.\d+)?\s*[:.)]?\s*"
)


# BOM / ZW / bidi embedding / word-joiner (explicit list — avoid stripping all Cf)
_SKIP_INVISIBLE = frozenset(
    {
        0xFEFF,
        0x200B,
        0x200C,
        0x200D,
        0x200E,
        0x200F,
        0x202A,
        0x202B,
        0x202C,
        0x202D,
        0x202E,
        0x2060,
        0x2061,
        0x2062,
        0x2063,
        0x2064,
        0x2066,
        0x2067,
        0x2068,
        0x2069,
    }
)


def _strip_invisible_chars(s: str) -> str:
    """BOM, zero-width, bidi embedding (always applied)."""
    return "".join(c for c in s if ord(c) not in _SKIP_INVISIBLE)


def _is_emoji_scalar(o: int) -> bool:
    if o in (0x200D, 0xFE0F, 0x20E3):
        return True
    if 0x1F300 <= o <= 0x1FAFF:
        return True
    if 0x2600 <= o <= 0x27BF:
        return True
    if 0x1F600 <= o <= 0x1F64F:
        return True
    if 0x1F680 <= o <= 0x1F6FF:
        return True
    if 0x1F1E0 <= o <= 0x1F1FF:
        return True
    if 0x2300 <= o <= 0x23FF:
        return True
    if 0x2B50 <= o <= 0x2B55:
        return True
    if 0x2700 <= o <= 0x27BF:
        return True
    return False


def _exclude_emoji(s: str) -> str:
    return "".join(c for c in s if not _is_emoji_scalar(ord(c)))


def _exclude_math(s: str) -> str:
    s = re.sub(r"\$\$[\s\S]*?\$\$", "", s)
    s = re.sub(r"\\\[[\s\S]*?\\\]", "", s)
    for env in ("equation", "equation*", "align", "align*", "gather", "gather*", "multline", "multline*"):
        s = re.sub(rf"\\begin\{{{re.escape(env)}\}}[\s\S]*?\\end\{{{re.escape(env)}\}}", "", s)
    s = re.sub(r"\\\((?:[^\\]|\\.)*?\\\)", "", s)

    def _inline_dollar(m: re.Match[str]) -> str:
        inner = m.group(1).strip()
        if re.fullmatch(r"[\d,.\s\$]+", inner):
            return m.group(0)
        return ""

    s = re.sub(r"(?<!\$)\$(?!\$)([^$\n]+?)\$(?!\$)", _inline_dollar, s)
    s = _U_MATH_ALNUM.sub("", s)
    return s


def _exclude_hyperlinks(s: str) -> str:
    s = re.sub(r"!\[([^\]]*)\]\([^)]*\)", "", s)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"\[([^\]]+)\]\[[^\]]*\]", r"\1", s)
    s = re.sub(r"<https?://[^>\s]+>", "", s, flags=re.I)
    s = re.sub(r"<mailto:[^>\s]+>", "", s, flags=re.I)
    s = re.sub(r"https?://[^\s\)\]<>\"\'\,]+", "", s, flags=re.I)
    s = re.sub(r"\bwww\.[^\s\)\]<>\"\'\,]+", "", s, flags=re.I)
    s = re.sub(r"mailto:[^\s\)\]<>\"\']+", "", s, flags=re.I)
    s = re.sub(r"\bftp://[^\s\)\]<>\"\'\,]+", "", s, flags=re.I)
    s = re.sub(r"file://[^\s\)\]<>\"\'\,]+", "", s, flags=re.I)
    return s


def _exclude_markup(s: str) -> str:
    s = re.sub(r"^```[^\n]*\n[\s\S]*?^```\s*$", "", s, flags=re.MULTILINE)
    s = re.sub(r"`[^`]+`", "", s)
    s = re.sub(r"</?[a-zA-Z][a-zA-Z0-9:-]*(?:\s[^>]*)?>", "", s)
    s = re.sub(r"&[a-zA-Z][a-zA-Z0-9]*;", " ", s)
    s = re.sub(r"&#\d+;", " ", s)
    s = re.sub(r"&#x[0-9a-fA-F]+;", " ", s, flags=re.I)
    s = re.sub(r"(?m)^#{1,6}\s*", "", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"__([^_]+)__", r"\1", s)
    s = re.sub(r"(?m)^(?:[-*_]\s*){3,}\s*$", "", s)

    def _list_line(line: str) -> str:
        line = re.sub(r"^(\s*)[-*+]\s+", r"\1", line)
        line = re.sub(r"^(\s*)\d+\.\s+", r"\1", line)
        return line

    s = "\n".join(_list_line(ln) for ln in s.split("\n"))
    return s


def _exclude_citations(s: str) -> str:
    s = re.sub(r"\[\^[^\]]+\]", "", s)
    s = re.sub(r"\^\[[^\]]+\]", "", s)
    s = re.sub(r"\[\d+(?:\s*,\s*\d+)*\]", "", s)
    s = _CITE_PAREN_RE.sub("", s)
    return s


def _exclude_technical(s: str) -> str:
    s = _UUID_RE.sub("", s)
    s = _HEX_WORD_RE.sub("", s)
    s = _HASH_LIKE_RE.sub("", s)
    s = _PATH_RE.sub("", s)
    s = _EMAIL_RE.sub("", s)
    return s


def _exclude_chrome(s: str) -> str:
    s = _PAGE_OF_RE.sub("", s)
    s = _FIGURE_LINE_RE.sub("", s)
    lines_out: list[str] = []
    for line in s.split("\n"):
        stripped = line.strip()
        if len(stripped) >= 12 and stripped.count(".") >= max(8, len(stripped) // 3):
            if re.match(r"^[\d.\s]+$", stripped):
                continue
        lines_out.append(line)
    return "\n".join(lines_out)


def _exclude_image_alt_patterns(s: str) -> str:
    s = re.sub(r"(?i)\[image:\s*[^\]]*\]", "", s)
    s = re.sub(r"(?i)\(image:\s*[^)]*\)", "", s)
    return s


def _collapse_ws(s: str) -> str:
    s = re.sub(r"[ \t\f\v]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def prepare_speak_text(
    text: str,
    *,
    exclude_hyperlinks: bool = True,
    exclude_math: bool = True,
    exclude_markup: bool = True,
    exclude_citations: bool = True,
    exclude_technical: bool = True,
    exclude_chrome: bool = True,
    exclude_emoji: bool = True,
) -> str:
    """Return text safer for TTS; may be empty if everything was stripped."""
    s = _strip_invisible_chars(text)
    if exclude_math:
        s = _exclude_math(s)
    if exclude_hyperlinks:
        s = _exclude_hyperlinks(s)
    if exclude_markup:
        s = _exclude_markup(s)
        s = _exclude_image_alt_patterns(s)
    if exclude_citations:
        s = _exclude_citations(s)
    if exclude_technical:
        s = _exclude_technical(s)
    if exclude_chrome:
        s = _exclude_chrome(s)
    if exclude_emoji:
        s = _exclude_emoji(s)
    s = _collapse_ws(s)
    return s


def prepare_speak_text_from_settings(text: str, settings: "RuntimeSettings") -> str:
    return prepare_speak_text(
        text,
        exclude_hyperlinks=settings.speak_exclude_hyperlinks,
        exclude_math=settings.speak_exclude_math,
        exclude_markup=settings.speak_exclude_markup,
        exclude_citations=settings.speak_exclude_citations,
        exclude_technical=settings.speak_exclude_technical,
        exclude_chrome=settings.speak_exclude_chrome,
        exclude_emoji=settings.speak_exclude_emoji,
    )


if __name__ == "__main__":
    assert "http" not in prepare_speak_text("x [a](https://b.com) y", exclude_emoji=False).lower()
    assert prepare_speak_text(r"$\frac{a}{b}$", exclude_hyperlinks=False, exclude_math=True) == ""
    assert "$3.50" in prepare_speak_text("cost $3.50", exclude_hyperlinks=False, exclude_math=True)
    assert "bold" == prepare_speak_text("**bold**", exclude_math=False, exclude_hyperlinks=False).strip()
    assert "f47ac10b" not in prepare_speak_text(
        "id f47ac10b-58cc-4372-a567-0e02b2c3d479 tail", exclude_technical=True, exclude_math=False
    ).lower()
    print("OK")
