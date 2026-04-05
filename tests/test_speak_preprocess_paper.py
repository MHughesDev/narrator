"""Paper / PDF-style speak_preprocess heuristics (citations, author lists, figure dump lines)."""

from __future__ import annotations

from narrator.speak_preprocess import prepare_speak_text


def test_multi_parenthetical_citations_removed() -> None:
    s = (
        "deployed (OpenAI et al., 2024; Gottweis et al., 2025; Yang et al., 2025a; "
        "Guo et al., 2024; Zhou et al., 2024), transforming"
    )
    out = prepare_speak_text(s, exclude_technical=False)
    assert "(" not in out
    assert "2024" not in out
    assert "deployed" in out and "transforming" in out


def test_long_author_list_collapsed() -> None:
    s = (
        "Yingxuan Yang, Huacan Chai, Yuanyi Song, Siyuan Qi, Muning Wen, Ning Li, "
        "Junwei Liao, Haoyi Hu, Jianghao Lin, Gaowei Chang, Ying Wen"
    )
    out = prepare_speak_text(s, exclude_technical=False)
    assert "see names" in out
    assert "Yingxuan" not in out


def test_affiliation_with_brace_email_collapsed() -> None:
    s = "Shanghai Jiao Tong University, †ANP Community {zoeyyx, chiangel, wnzhang}@sjtu.edu.cn"
    out = prepare_speak_text(s, exclude_technical=False, start_at_abstract=False)
    assert out.strip() == "see names"
    assert "University" not in out


def test_paper_front_matter_title_authors_then_abstract() -> None:
    raw = (
        "A Survey of AI Agent Protocols\n\n"
        "Yingxuan Yang, Huacan Chai, Yuanyi Song\n\n"
        "Shanghai Jiao Tong University, †ANP Community {zoeyyx, chiangel, wnzhang}@sjtu.edu.cn\n\n"
        "Abstract\n\n"
        "The rapid development of large language models has led to the widespread deployment."
    )
    out = prepare_speak_text(raw, exclude_technical=True)
    assert "Yingxuan" not in out
    assert "Shanghai" not in out
    assert "sjtu" not in out.lower()
    assert "Survey of AI Agent" not in out
    assert "rapid development" in out.lower()


def test_brace_group_email_removed() -> None:
    s = "Contact {a, b}@example.org today."
    out = prepare_speak_text(s, exclude_technical=True, start_at_abstract=False)
    assert "example.org" not in out
    assert "Contact" in out and "today" in out


def test_figure_caption_line_removed() -> None:
    s = "Body text.\nFigure 2: A glance at the development of agent protocols.\nMore body."
    out = prepare_speak_text(s, exclude_technical=False)
    assert "Figure 2" not in out
    assert "Body text" in out and "More body" in out


def test_figure_legend_line_removed() -> None:
    s = "Before\nLLMs (Blue)\nAfter"
    out = prepare_speak_text(s, exclude_technical=False)
    assert "LLMs (Blue)" not in out
    assert "Before" in out and "After" in out
