"""Line and paragraph pauses for speak: SSML breaks (WinRT) or punctuation joins (neural TTS)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Optional
from xml.sax.saxutils import escape

if TYPE_CHECKING:
    from narrator.settings import RuntimeSettings

_ESC = {'"': "&quot;", "'": "&apos;", "<": "&lt;", ">": "&gt;", "&": "&amp;"}


def apply_paragraph_pauses_plain(text: str) -> str:
    """
    Default **standard** prosody: pause only **between** paragraph blocks (blank-line separated).
    Lines within a block are joined with a space (no comma pause).
    """
    paragraphs = re.split(r"\n\s*\n+", text.strip())
    blocks: list[str] = []
    for para in paragraphs:
        lines = [ln.strip() for ln in para.split("\n") if ln.strip()]
        if not lines:
            continue
        blocks.append(" ".join(lines))
    return " . ".join(blocks)


def apply_line_pauses_plain(text: str) -> str:
    """
    Stronger prosody: lighter pauses between **lines** (``, ``) and between paragraphs (``. ``).
    Enable with ``speak_pause_between_lines = true``.
    """
    paragraphs = re.split(r"\n\s*\n+", text.strip())
    blocks: list[str] = []
    for para in paragraphs:
        lines = [ln.strip() for ln in para.split("\n") if ln.strip()]
        if not lines:
            continue
        blocks.append(", ".join(lines))
    return " . ".join(blocks)


def build_winrt_ssml_with_breaks(
    text: str,
    *,
    voice_name: Optional[str],
    lang: str,
    line_ms: int,
    paragraph_ms: int,
    between_lines: bool = False,
) -> str:
    """SSML ``<break/>`` between paragraphs; optionally between lines within a block."""
    paragraphs = re.split(r"\n\s*\n+", text.strip())
    inner_parts: list[str] = []
    first_para = True
    for para in paragraphs:
        lines = [ln.strip() for ln in para.split("\n") if ln.strip()]
        if not lines:
            continue
        if not first_para:
            inner_parts.append(f'<break time="{paragraph_ms}ms"/>')
        first_para = False
        if between_lines:
            for i, line in enumerate(lines):
                if i > 0:
                    inner_parts.append(f'<break time="{line_ms}ms"/>')
                inner_parts.append(escape(line, _ESC))
        else:
            merged = " ".join(lines)
            inner_parts.append(escape(merged, _ESC))
    body = "".join(inner_parts)
    if voice_name:
        vn = escape(voice_name, {'"': "&quot;", "&": "&amp;"})
        return (
            f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' "
            f"xml:lang='{lang}'><voice name=\"{vn}\">{body}</voice></speak>"
        )
    return f"<speak version='1.0' xml:lang='{lang}'>{body}</speak>"


def apply_speak_prosody(text: str, settings: "RuntimeSettings") -> str:
    """
    Neural engines: **standard** = paragraph pauses only; optional line pauses if
    ``speak_pause_between_lines``.

    WinRT: if ``speak_winrt_use_ssml_breaks``, newlines preserved for SSML in :mod:`narrator.speech`;
    otherwise same plain transform as neural.
    """
    if not getattr(settings, "speak_insert_line_pauses", True):
        return text
    if settings.speak_engine == "winrt" and getattr(settings, "speak_winrt_use_ssml_breaks", True):
        return text
    if getattr(settings, "speak_pause_between_lines", False):
        return apply_line_pauses_plain(text)
    return apply_paragraph_pauses_plain(text)


if __name__ == "__main__":
    sample = "Title line\n\nFirst section\nSecond line\n\nNew paragraph."
    std = apply_paragraph_pauses_plain(sample)
    assert "First section Second line" in std and "New paragraph" in std
    assert std.count(" . ") >= 1
    full = apply_line_pauses_plain(sample)
    assert "First section, Second line" in full
    ssml_std = build_winrt_ssml_with_breaks(
        sample, voice_name=None, lang="en-US", line_ms=300, paragraph_ms=500, between_lines=False
    )
    assert "<break time=\"500ms\"/>" in ssml_std
    assert "<break time=\"300ms\"/>" not in ssml_std
    ssml_full = build_winrt_ssml_with_breaks(
        sample, voice_name=None, lang="en-US", line_ms=300, paragraph_ms=500, between_lines=True
    )
    assert "<break time=\"300ms\"/>" in ssml_full
    print("OK")
