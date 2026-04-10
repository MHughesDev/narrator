"""
Text stages aligned with OpenBMB/VoxCPM before neural (or non-SSML) TTS.

VoxCPM ``core.VoxCPM._generate`` (see upstream ``core.py``):
- Collapses whitespace: newlines and runs of spaces → single spaces (``re.sub(r"\\s+", " ", ...)``).
- Optionally runs ``TextNormalizer`` (wetext + inflect for English) when ``normalize=True``.

Upstream ``utils/text_normalize.py`` also applies ``clean_text``: markdown stripping, emoji removal,
then newline/tab normalization — we mirror that when the pipeline is enabled.

WinRT + SSML breaks: newlines carry paragraph/line structure into ``build_winrt_ssml_with_breaks``;
we skip the aggressive newline→space collapse in that mode but still apply markdown/emoji cleanup
line-oriented so structure is preserved.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from narrator.settings import RuntimeSettings

# --- Portions adapted from VoxCPM utils/text_normalize.py (Apache-2.0, OpenBMB) ---


def _clean_markdown(md_text: str) -> str:
    md_text = re.sub(r"```.*?```", "", md_text, flags=re.DOTALL)
    md_text = re.sub(r"`[^`]*`", "", md_text)
    md_text = re.sub(r"!\[[^\]]*\]\([^\)]+\)", "", md_text)
    md_text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", md_text)
    md_text = re.sub(r"^(\s*)-\s+", r"\1", md_text, flags=re.MULTILINE)
    md_text = re.sub(r"<[^>]+>", "", md_text)
    md_text = re.sub(r"^#{1,6}\s*", "", md_text, flags=re.MULTILINE)
    md_text = re.sub(r"\n\s*\n", "\n", md_text)
    return md_text.strip()


def _strip_emoji(text: str) -> str:
    try:
        import regex

        return regex.compile(r"\p{Emoji_Presentation}|\p{Emoji}\uFE0F", flags=regex.UNICODE).sub("", text)
    except ImportError:
        return text


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def _collapse_whitespace_like_voxcpm_core(text: str) -> str:
    """Match ``VoxCPM.core`` text = re.sub(r'\\s+', ' ', text) after newline→space."""
    text = text.replace("\n", " ")
    text = text.replace("\t", " ")
    return re.sub(r"\s+", " ", text).strip()


def _clean_text_full(text: str) -> str:
    """Equivalent to upstream ``clean_text`` (including newline → space)."""
    text = _clean_markdown(text)
    text = _strip_emoji(text)
    text = text.replace("\n", " ")
    text = text.replace("\t", " ")
    text = text.replace("“", '"').replace("”", '"')
    return text


def _clean_text_preserve_newlines(text: str) -> str:
    """Markdown/emoji cleanup without merging lines (for WinRT SSML path)."""
    lines = text.split("\n")
    out: list[str] = []
    for line in lines:
        t = _clean_markdown(line)
        t = _strip_emoji(t)
        t = t.replace("\t", " ")
        t = t.replace("“", '"').replace("”", '"')
        out.append(t)
    return "\n".join(out)


def _spell_out_ascii_digits_inflect(text: str) -> str:
    try:
        import inflect
    except ImportError:
        return text

    inflect_parser = inflect.engine()
    new_text: list[str] = []
    st: int | None = None
    for i, c in enumerate(text):
        if not c.isdigit():
            if st is not None:
                num_str = inflect_parser.number_to_words(text[st:i])
                new_text.append(num_str)
                st = None
            new_text.append(c)
        else:
            if st is None:
                st = i
    if st is not None and st < len(text):
        new_text.append(inflect_parser.number_to_words(text[st:]))
    return "".join(new_text)


def _wetext_normalize(text: str) -> str | None:
    """Return wetext-normalized text, or None if unavailable."""
    try:
        from wetext import Normalizer
    except ImportError:
        return None

    lang = "zh" if _contains_cjk(text) else "en"
    if lang == "zh":
        tn = Normalizer(lang="zh", operator="tn", remove_erhua=True)
        text = text.replace("=", "等于")
        if re.search(r"([\d$%^*_+≥≤≠×÷?=])", text):
            text = re.sub(r"(?<=[a-zA-Z0-9])-(?=\d)", " - ", text)
        text = tn.normalize(text)
        # replace_blank / corner marks / brackets — light port
        text = _replace_blank_cjk(text)
        text = text.replace("²", "平方").replace("³", "立方")
        text = text.replace("√", "根号").replace("≈", "约等于")
        text = text.replace("<", "小于")
        text = text.replace("（", " ").replace("）", " ")
        text = text.replace("【", " ").replace("】", " ")
        text = text.replace("`", "")
        text = text.replace("——", " ")
    else:
        tn = Normalizer(lang="en", operator="tn")
        text = tn.normalize(text)
        text = _spell_out_ascii_digits_inflect(text)
    return text


def _replace_blank_cjk(text: str) -> str:
    out: list[str] = []
    for i, c in enumerate(text):
        if c == " ":
            if (
                0 < i < len(text) - 1
                and text[i + 1].isascii()
                and text[i + 1] != " "
                and text[i - 1].isascii()
                and text[i - 1] != " "
            ):
                out.append(c)
        else:
            out.append(c)
    return "".join(out)


def apply_voxcpm_style_text_for_tts(text: str, settings: "RuntimeSettings") -> str:
    """
    Apply VoxCPM-like preprocessing before synthesis.

    Controlled by ``speak_voxcpm_text_pipeline`` and optional ``speak_voxcpm_text_normalize`` (wetext).
    """
    if not getattr(settings, "speak_voxcpm_text_pipeline", True):
        return text
    if not text or not str(text).strip():
        return text

    winrt_ssml = (
        str(getattr(settings, "speak_engine", "")).strip().lower() == "winrt"
        and bool(getattr(settings, "speak_winrt_use_ssml_breaks", True))
        and bool(getattr(settings, "speak_insert_line_pauses", True))
    )

    if winrt_ssml:
        cleaned = _clean_text_preserve_newlines(text)
    else:
        cleaned = _clean_text_full(text)

    if getattr(settings, "speak_voxcpm_text_normalize", False):
        tn_out = _wetext_normalize(cleaned)
        if tn_out is not None:
            cleaned = tn_out

    if winrt_ssml:
        return cleaned.strip()

    return _collapse_whitespace_like_voxcpm_core(cleaned)
