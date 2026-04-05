"""Tests for narrator.speak_preprocess."""

from __future__ import annotations

import pytest

from narrator.speak_preprocess import prepare_speak_text


def test_strip_arxiv_line_variants() -> None:
    raw = (
        "My Title\n"
        "ARXIV.org. 2504.16736v3 [cs.AI] 21 Jun 2025\n"
        "We study AI."
    )
    out = prepare_speak_text(raw, exclude_technical=False)
    assert "2504.16736" not in out
    assert "arxiv" not in out.lower()
    assert "study" in out.lower()


def test_strip_toc_leader_line() -> None:
    raw = "Introduction ................. 3\nWe begin."
    out = prepare_speak_text(raw, exclude_technical=False)
    assert "Introduction" not in out or "We begin" in out
    assert "We begin" in out


def test_exclude_math_mathml_and_unicode() -> None:
    raw = "Intro <math xmlns='http://www.w3.org/1998/Math/MathML'><mi>x</mi></math> done. Also ∑∫ and ∀x∈S."
    out = prepare_speak_text(raw, exclude_technical=False)
    assert "math" not in out.lower()
    assert "Intro" in out and "done" in out
    assert "∑" not in out and "∫" not in out
    assert "∀" not in out


def test_exclude_math_tikz() -> None:
    raw = r"See graph \begin{tikzpicture}\draw (0,0)--(1,1);\end{tikzpicture} end."
    out = prepare_speak_text(raw, exclude_technical=False)
    assert "tikzpicture" not in out.lower()
    assert "See graph" in out and "end" in out


def test_expand_llm_cli() -> None:
    out = prepare_speak_text("An LLM and CLI tool.", exclude_technical=False)
    assert "L L M" in out
    assert "C L I" in out


def test_expand_plural_abbrevs_apostrophe() -> None:
    out = prepare_speak_text("LLMs and APIs on GPUs.", exclude_technical=False)
    assert "L L M's" in out
    assert "A P I's" in out
    assert "G P U's" in out
    assert "LLMs" not in out


def test_start_at_abstract() -> None:
    raw = "Author One\nAuthor Two\nAbstract\nWe propose a method."
    out = prepare_speak_text(
        raw,
        exclude_technical=False,
        start_at_abstract=True,
    )
    assert "Author" not in out
    assert "propose" in out.lower()


def test_contents_page_paragraph_dropped() -> None:
    raw = (
        "Contents\n"
        "Introduction .... 1\n"
        "Methods ........ 5\n\n"
        "Real paragraph starts here."
    )
    out = prepare_speak_text(raw, exclude_technical=False)
    assert "Real paragraph" in out
    assert "Introduction" not in out


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
