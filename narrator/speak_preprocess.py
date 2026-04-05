"""Post-process captured text before TTS: strip links, math, markup, citations, technical tokens, chrome, emoji."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from narrator.settings import RuntimeSettings

# Unicode Mathematical Alphanumeric Symbols (bold italic math letters, etc.)
_U_MATH_ALNUM = re.compile(r"[\U0001d400-\U0001d7ff]")
# Mathematical Operators, block elements, and supplemental symbols (formulas / equations in PDFs).
_U_MATH_SYMBOLS_BLOCKS = re.compile(
    r"[\u2200-\u22ff\u27c0-\u27ef\u2980-\u29ff\u2b30-\u2bff]"
)

# amsmath / mathtools / AMS — strip entire display blocks (see _exclude_math).
_MATH_TEX_ENVS: tuple[str, ...] = tuple(
    sorted(
        {
            "equation",
            "equation*",
            "align",
            "align*",
            "alignat",
            "alignat*",
            "flalign",
            "flalign*",
            "gather",
            "gather*",
            "multline",
            "multline*",
            "split",
            "cases",
            "matrix",
            "pmatrix",
            "bmatrix",
            "Bmatrix",
            "vmatrix",
            "Vmatrix",
            "smallmatrix",
            "subequations",
            "eqnarray",
            "eqnarray*",
            "array",
            "cd",
        },
        key=len,
        reverse=True,
    )
)

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
    r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b",
)
# arXiv / CS papers: "{user1, user2}@institution.edu"
_BRACE_GROUP_EMAIL_RE = re.compile(
    r"\{[^}\n]{0,200}\}\s*@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b",
)

# Academic-style (Name, 2020) / (Name et al., 2020) — single-ish block (no semicolon groups).
_CITE_PAREN_RE = re.compile(
    r"\(\s*[A-Z][a-zA-Z'\-]+(?:\s+et\s+al\.)?(?:\s*,\s*[A-Z][a-zA-Z'\-]+)*(?:\s*,\s*\d{4}[a-z]?)\s*\)"
)
# (Org et al., 2024; Other et al., 2025a; …) — repeated in a single pair of parentheses.
_CITE_UNIT_IN_PARENS = (
    r"(?:"
    r"[A-Z][A-Za-z0-9'.\-]*(?:\s+[A-Z][A-Za-z0-9'.\-]*)*\s+et\s+al\.\s*,\s*\d{4}[a-z]?"
    r"|[A-Z][A-Za-z0-9'.\-]*(?:\s+[A-Z][A-Za-z0-9'.\-]*)+\s*,\s*\d{4}[a-z]?"
    r")"
)
_MULTI_CITE_PAREN_RE = re.compile(
    rf"\(\s*{_CITE_UNIT_IN_PARENS}(?:\s*;\s*{_CITE_UNIT_IN_PARENS})+\s*\)"
)

# "Page 3 of 47" / "page 12 of 100"
_PAGE_OF_RE = re.compile(r"(?i)\bpage\s+\d+\s+of\s+\d+\b")

# arXiv first-page / header boilerplate (PDF/HTML extraction varies).
_ARXIV_NUM_ID = re.compile(r"\b\d{4}\.\d{4,5}(?:v\d+)?\b", re.I)
_ARXIV_ABS_URL = re.compile(r"(?i)arxiv\.org/(?:abs|pdf)/\s*\d{4}\.\d{4,5}")


def _line_looks_like_arxiv_metadata(t: str) -> bool:
    """True if line looks like an arXiv header (id + arxiv mention, or /abs/ URL)."""
    if _ARXIV_ABS_URL.search(t):
        return True
    if re.search(r"(?i)arxiv", t) and _ARXIV_NUM_ID.search(t):
        return True
    return False
# Table-of-contents style: title ………… 12
_TOC_LEADER_LINE_RE = re.compile(
    r"^\s*\S.{0,400}?\.{3,}\s*\d{1,4}\s*$"
)

# Spoken letter-by-letter for TTS (longest keys first — applied in that order).
_TECH_ABBREV_EXPANSIONS: tuple[tuple[str, str], ...] = tuple(
    sorted(
        {
            "HTTPS": "H T T P S",
            "HTTP": "H T T P",
            "JSON": "J S O N",
            "YAML": "Y A M L",
            "LLMs": "L L M's",
            "LLM": "L L M",
            "GPUs": "G P U's",
            "GPU": "G P U",
            "CPUs": "C P U's",
            "CPU": "C P U",
            "APIs": "A P I's",
            "CLI": "C L I",
            "API": "A P I",
            "RAM": "R A M",
            "SSD": "S S D",
            "IDE": "I D E",
            "SQL": "S Q L",
            "URL": "U R L",
            "URI": "U R I",
            "REST": "R E S T",
            "NLP": "N L P",
            "CRT": "C R T",
            "GUI": "G U I",
            "TTS": "T T S",
            "UI": "U I",
            "UX": "U X",
            "OS": "O S",
            "AI": "A I",
        }.items(),
        key=lambda kv: len(kv[0]),
        reverse=True,
    )
)

# Full line: figure caption, table title row (PDF often dumps this as plain text).
_FIGURE_TABLE_FULL_LINE = re.compile(
    r"(?im)^\s*(?:figure|fig\.|table)\s+\d+(?:\.\d+)?\b.*\s*$"
)
# Standalone colour/style legend like "LLMs (Blue)" or "Agent Protocols (Orange)".
_FIGURE_LEGEND_LINE = re.compile(
    r"^\s*[A-Za-z][A-Za-z0-9'.\s/&\-]{0,72}\s*\([^)]{1,48}\)\s*$"
)
# A lone year or a row of years separated by pipes (timeline graphics).
_YEAR_ONLY_LINE = re.compile(r"^\s*(?:19|20)\d{2}[a-z]?\s*$")
_TIMELINE_YEAR_ROW = re.compile(
    r"^\s*(?:19|20)\d{2}[a-z]?(?:\s*\|\s*(?:19|20)\d{2}[a-z]?){2,}\s*$"
)


# BOM / ZW / bidi embedding / word-joiner (explicit list — avoid stripping all Cf)
# 0xFFFC: object replacement (common in PDF extraction; breaks some neural TTS tokenizers).
_SKIP_INVISIBLE = frozenset(
    {
        0xFEFF,
        0xFFFC,
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


def _normalize_hyphens_and_dashes_for_tts(s: str) -> str:
    """
    PDF/UI extraction often inserts **invisible** soft hyphens (U+00AD) and odd Unicode dash code points.
    Many TTS front-ends treat those as syllable boundaries and insert a micro-pause (easy to mistake for
    a random “stutter” mid-word). This pass fixes **source text** issues only—not playback glitches that
    occur when the visible text has no hyphen at all.
    """
    # Soft hyphen: optional line break inside words; remove so the word reads as one unit.
    s = s.replace("\u00ad", "")
    # Hyphen / minus / non-breaking hyphen → ASCII hyphen (keep compounds like forty-two).
    for u in ("\u2010", "\u2011", "\u2212"):
        s = s.replace(u, "-")
    # En/em dash between tokens → short pause (comma) instead of a long prosody break.
    s = re.sub(r"\s*[\u2013\u2014]\s*", ", ", s)
    return s


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
    """Remove LaTeX/HTML math and Unicode math symbols so TTS does not read formulas aloud."""

    # MathML / HTML5 equation markup from viewers or EPUB.
    s = re.sub(r"(?is)<math\b[^>]*>[\s\S]*?</math>", "", s)
    s = re.sub(r"(?is)<semantics\b[^>]*>[\s\S]*?</semantics>", "", s)
    # Commutative-diagram / figure blocks that are pure notation.
    s = re.sub(r"\\begin\{tikzpicture\}[\s\S]*?\\end\{tikzpicture\}", "", s)

    for env in _MATH_TEX_ENVS:
        s = re.sub(
            rf"\\begin\{{{re.escape(env)}\}}[\s\S]*?\\end\{{{re.escape(env)}\}}",
            "",
            s,
        )

    # Repeat: nested or back-to-back display blocks.
    for _ in range(24):
        prev = s
        s = re.sub(r"\$\$[\s\S]*?\$\$", "", s)
        s = re.sub(r"\\\[[\s\S]*?\\\]", "", s)
        if s == prev:
            break

    # Inline \(...\) — repeat for light nesting.
    for _ in range(16):
        prev = s
        s = re.sub(r"\\\((?:[^\\]|\\.)*?\\\)", "", s)
        if s == prev:
            break

    def _inline_dollar(m: re.Match[str]) -> str:
        inner = m.group(1).strip()
        if re.fullmatch(r"[\d,.\s\$]+", inner):
            return m.group(0)
        return ""

    s = re.sub(r"(?<!\$)\$(?!\$)([^$\n]+?)\$(?!\$)", _inline_dollar, s)
    s = _U_MATH_ALNUM.sub("", s)
    s = _U_MATH_SYMBOLS_BLOCKS.sub("", s)
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
    for _ in range(48):
        prev = s
        s = _MULTI_CITE_PAREN_RE.sub("", s)
        if s == prev:
            break
    s = _CITE_PAREN_RE.sub("", s)
    return s


def _exclude_technical(s: str) -> str:
    s = _UUID_RE.sub("", s)
    s = _HEX_WORD_RE.sub("", s)
    s = _HASH_LIKE_RE.sub("", s)
    s = _PATH_RE.sub("", s)
    s = _BRACE_GROUP_EMAIL_RE.sub("", s)
    s = _EMAIL_RE.sub("", s)
    return s


def _exclude_chrome(s: str) -> str:
    s = _PAGE_OF_RE.sub("", s)
    s = _FIGURE_TABLE_FULL_LINE.sub("", s)
    lines_out: list[str] = []
    for line in s.split("\n"):
        stripped = line.strip()
        if len(stripped) >= 12 and stripped.count(".") >= max(8, len(stripped) // 3):
            if re.match(r"^[\d.\s]+$", stripped):
                continue
        lines_out.append(line)
    return "\n".join(lines_out)


def _paragraph_looks_like_affiliation_footer(p: str) -> bool:
    """Keep lines such as ``University … {a,b}@domain`` — not a bare author list."""
    if re.search(r"\{[^}\n]{1,120}\}@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", p):
        return True
    if "@" in p and re.search(
        r"(?i)\b(university|institute|college|school|laboratory|labs?|research\s+cent(er|re)|community)\b",
        p,
    ):
        return True
    return False


def _segment_looks_like_person_name(seg: str) -> bool:
    seg = seg.strip()
    if not seg or len(seg) > 160:
        return False
    seg_core = re.sub(r"[\s∗†‡]+$", "", seg)
    seg_core = re.sub(r"^(?:[∗†‡]\s*)+", "", seg_core)
    words = re.split(r"\s+", seg_core)
    if len(words) < 2 or len(words) > 8:
        return False
    noise = frozenset(
        (
            "large",
            "natural",
            "artificial",
            "deep",
            "neural",
            "machine",
            "reinforcement",
            "language",
            "vision",
            "processing",
            "foundation",
            "agent",
            "model",
            "models",
            "training",
            "survey",
            "introduction",
            "conclusion",
            "abstract",
            "references",
            "appendix",
            "acknowledgments",
            "acknowledgement",
            "shanghai",
            "table",
            "contents",
        )
    )
    if words[0].lower() in noise:
        return False
    for w in words:
        if not w:
            return False
        ch0 = w[0]
        if ch0.isalpha() and ch0.isupper():
            continue
        if ch0 in "∗†‡" and len(w) > 1 and w[1].isalpha() and w[1].isupper():
            continue
        return False
    return True


def _collapse_long_name_lists(s: str, *, max_names: int = 4) -> str:
    """
    Replace comma-heavy **author / TOC name** blocks with ``see names`` when more than
    ``max_names`` segments look like ``Given Surname`` pairs.
    Affiliation / contact paragraphs (university lines, institute + e-mail patterns) also
    collapse to ``see names`` so author signatures are not read aloud.
    """
    max_names = max(1, min(32, max_names))
    blocks = re.split(r"\n\s*\n+", s)
    out: list[str] = []
    for block in blocks:
        t = block.strip()
        if not t:
            out.append(block)
            continue
        if _paragraph_looks_like_affiliation_footer(t):
            out.append("see names")
            continue
        t1 = re.sub(r"[\n\r]+", " ", t)
        segs = [x.strip() for x in t1.split(",") if x.strip()]
        if len(segs) <= max_names:
            out.append(block)
            continue
        name_like = sum(1 for seg in segs if _segment_looks_like_person_name(seg))
        if name_like > max_names:
            out.append("see names")
        else:
            out.append(block)
    return "\n\n".join(out)


def _strip_figure_legend_lines(s: str) -> str:
    """Remove lines that look like figure/image legends or extracted timeline rows."""
    lines_out: list[str] = []
    for line in s.split("\n"):
        t = line.strip()
        if _FIGURE_LEGEND_LINE.match(t):
            continue
        if _YEAR_ONLY_LINE.match(t):
            continue
        if _TIMELINE_YEAR_ROW.match(t):
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


def _strip_arxiv_metadata_lines(s: str) -> str:
    """Remove lines containing arXiv id / arxiv.org header noise."""
    lines_out: list[str] = []
    for line in s.split("\n"):
        t = line.strip()
        if not t:
            lines_out.append(line)
            continue
        if _line_looks_like_arxiv_metadata(t):
            continue
        lines_out.append(line)
    return "\n".join(lines_out)


def _strip_toc_leader_lines(s: str) -> str:
    """Remove dot-leader table-of-contents lines (e.g. Introduction .... 3)."""
    lines_out: list[str] = []
    for line in s.split("\n"):
        if _TOC_LEADER_LINE_RE.match(line.strip()):
            continue
        lines_out.append(line)
    return "\n".join(lines_out)


def _strip_contents_page_paragraphs(s: str) -> str:
    """Drop paragraphs that look like a contents page (heading + mostly dot-leader lines)."""
    blocks = re.split(r"\n\s*\n+", s)
    out: list[str] = []
    for block in blocks:
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        head = lines[0].lower().rstrip(".")
        if head in ("contents", "table of contents"):
            rest = lines[1:]
            if not rest:
                continue
            leaders = sum(1 for ln in rest if _TOC_LEADER_LINE_RE.match(ln))
            if leaders >= max(1, len(rest) // 2):
                continue
        out.append(block)
    return "\n\n".join(out)


def _truncate_from_abstract_start(s: str) -> str:
    """Start at abstract body: skip title, authors, affiliation, and mails above ``Abstract``."""
    if not s.strip():
        return s
    # "Abstract" as its own line (possibly with spaces), then body on following line(s)
    m = re.search(r"(?i)(?:^|\n)\s*abstract\s*\n\s*\n+", s)
    if m:
        return s[m.end() :].strip()
    m = re.search(r"(?i)(?:^|\n)\s*abstract\s*\n", s)
    if m:
        return s[m.end() :].strip()
    # "Abstract:" / "Abstract —" followed by text (same line or rest of document)
    m = re.search(r"(?i)(?:^|\n)\s*abstract\s*[—\-:]+", s)
    if m:
        rest = s[m.end() :].strip()
        if rest:
            return rest
    # "Abstract The rapid..." (heading and first sentence on one line, common in PDF text runs)
    m = re.search(r"(?i)(?:^|\n)\s*abstract\s+(?=[A-Z0-9\(\"'])", s)
    if m:
        return s[m.end() :].strip()
    return s


def _expand_tech_abbreviations(s: str) -> str:
    """Spell common tech acronyms with spaces so engines say letters (LLM, CLI, …)."""
    for word, spoken in _TECH_ABBREV_EXPANSIONS:
        s = re.sub(r"\b" + re.escape(word) + r"\b", spoken, s, flags=re.I)
    return s


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
    expand_tech_abbreviations: bool = True,
    strip_arxiv_metadata: bool = True,
    strip_toc_leader_lines: bool = True,
    strip_contents_pages: bool = True,
    start_at_abstract: bool = True,
    strip_figure_legend_lines: bool = True,
    collapse_long_name_lists: bool = True,
    long_name_list_max: int = 4,
) -> str:
    """Return text safer for TTS; may be empty if everything was stripped."""
    s = _strip_invisible_chars(text)
    s = _normalize_hyphens_and_dashes_for_tts(s)
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
    if strip_arxiv_metadata:
        s = _strip_arxiv_metadata_lines(s)
    if strip_toc_leader_lines:
        s = _strip_toc_leader_lines(s)
    if strip_contents_pages:
        s = _strip_contents_page_paragraphs(s)
    if start_at_abstract:
        s = _truncate_from_abstract_start(s)
    if strip_figure_legend_lines:
        s = _strip_figure_legend_lines(s)
    if collapse_long_name_lists:
        s = _collapse_long_name_lists(s, max_names=long_name_list_max)
    if expand_tech_abbreviations:
        s = _expand_tech_abbreviations(s)
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
        expand_tech_abbreviations=settings.speak_expand_tech_abbreviations,
        strip_arxiv_metadata=settings.speak_strip_arxiv_metadata,
        strip_toc_leader_lines=settings.speak_strip_toc_leader_lines,
        strip_contents_pages=settings.speak_strip_contents_pages,
        start_at_abstract=settings.speak_start_at_abstract,
        strip_figure_legend_lines=settings.speak_strip_figure_legend_lines,
        collapse_long_name_lists=settings.speak_collapse_long_name_lists,
        long_name_list_max=settings.speak_long_name_list_max,
    )


def prepare_speak_text_minimal(raw: str) -> str:
    """Invisible/strip + hyphen normalize only — for ``llm_primary`` before the LLM applies rules."""
    s = _strip_invisible_chars(raw)
    s = _normalize_hyphens_and_dashes_for_tts(s)
    s = _collapse_ws(s)
    return s


if __name__ == "__main__":
    assert "http" not in prepare_speak_text("x [a](https://b.com) y", exclude_emoji=False).lower()
    assert prepare_speak_text(r"$\frac{a}{b}$", exclude_hyperlinks=False, exclude_math=True) == ""
    assert "$3.50" in prepare_speak_text("cost $3.50", exclude_hyperlinks=False, exclude_math=True)
    assert "bold" == prepare_speak_text("**bold**", exclude_math=False, exclude_hyperlinks=False).strip()
    assert "f47ac10b" not in prepare_speak_text(
        "id f47ac10b-58cc-4372-a567-0e02b2c3d479 tail", exclude_technical=True, exclude_math=False
    ).lower()
    print("OK")
