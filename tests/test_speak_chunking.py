"""Long-document TTS chunking."""

from __future__ import annotations

from pathlib import Path

import pytest

from narrator.speak_chunking import (
    XTTS_MAX_CHARS_PER_SEGMENT,
    clamp_chunk_max_chars,
    effective_speak_chunk_max_chars,
    extract_chunk_context_tail,
    iter_tts_chunks,
    merge_trailing_short_chunks,
    split_raw_for_streaming_preprocess,
    trim_context_to_synth_budget,
)
from narrator.speak_text_llm import DEFAULT_SPEAK_TEXT_LLM_MODEL


def test_disabled_chunking_yields_whole() -> None:
    text = "a" * 50_000
    out = list(iter_tts_chunks(text, 0))
    assert len(out) == 1
    assert out[0] == text


def test_short_text_single_chunk() -> None:
    assert list(iter_tts_chunks("Hello.\n\nWorld.", 8000)) == ["Hello.\n\nWorld."]


def test_two_paragraphs_split_when_over_max() -> None:
    # Minimum chunk clamp is 1024 — use paragraphs that exceed one chunk when packed.
    a = "x" * 600
    b = "y" * 600
    text = f"{a}\n\n{b}"
    chunks = list(iter_tts_chunks(text, 100))
    assert len(chunks) == 2
    assert a in chunks[0] and b in chunks[1]


def test_oversized_paragraph_hard_wraps() -> None:
    blob = "word " * 2000  # >> small max
    max_c = 1500
    chunks = list(iter_tts_chunks(blob, max_c))
    assert len(chunks) >= 3
    for c in chunks:
        assert len(c) <= max_c


def test_clamp_chunk_max_chars() -> None:
    assert clamp_chunk_max_chars(0) == 0
    assert clamp_chunk_max_chars(500) == 1024
    assert clamp_chunk_max_chars(50_000) == 50_000
    assert clamp_chunk_max_chars(500, min_floor=200) == 500


def test_effective_speak_chunk_max_chars() -> None:
    assert effective_speak_chunk_max_chars("piper", 8000) == 8000
    assert effective_speak_chunk_max_chars("xtts", 8000) == XTTS_MAX_CHARS_PER_SEGMENT
    assert effective_speak_chunk_max_chars("xtts", 0) == XTTS_MAX_CHARS_PER_SEGMENT
    assert effective_speak_chunk_max_chars("xtts", 400) == min(400, XTTS_MAX_CHARS_PER_SEGMENT)


def test_xtts_chunk_floor_allows_sub_1024_segments() -> None:
    blob = "word " * 400
    chunks = list(iter_tts_chunks(blob, XTTS_MAX_CHARS_PER_SEGMENT, min_chunk_floor=200))
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c) <= XTTS_MAX_CHARS_PER_SEGMENT


def test_xtts_second_pass_splits_long_string() -> None:
    """After prosody, text may still exceed the cap; a second iter_tts_chunks pass must split."""
    blob = "z" * 2000
    pieces = list(iter_tts_chunks(blob, XTTS_MAX_CHARS_PER_SEGMENT, min_chunk_floor=200))
    assert len(pieces) >= 2
    assert max(len(p) for p in pieces) <= XTTS_MAX_CHARS_PER_SEGMENT


def test_hard_wrap_finds_nbsp_break() -> None:
    nbsp = "\u00a0"
    blob = ("word" + nbsp) * 400
    chunks = list(iter_tts_chunks(blob, 200, min_chunk_floor=50))
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c) <= 200


def test_prepare_speak_text_hyphen_normalization() -> None:
    from narrator.speak_preprocess import prepare_speak_text

    assert prepare_speak_text("re\u00ADads") == "reads"
    assert prepare_speak_text("mouse\u2014headings") == "mouse, headings"


def test_extract_chunk_context_tail_last_sentence() -> None:
    prev = "First sentence here. Second sentence is longer. Third is last."
    tail = extract_chunk_context_tail(prev, 50)
    assert "Third is last" in tail
    assert "First sentence" not in tail


def test_extract_chunk_context_tail_short_returns_all() -> None:
    assert extract_chunk_context_tail("Hello.", 100) == "Hello."


def test_trim_context_to_synth_budget() -> None:
    long_c = "word " * 30
    u = "utterance"
    budget = 50
    short = trim_context_to_synth_budget(long_c, u, budget)
    assert len(short) + 1 + len(u) <= budget


def test_merge_trailing_short_chunks() -> None:
    long_a = "x" * 100
    short_b = "y" * 30
    merged = merge_trailing_short_chunks([long_a, short_b], max_chars=220, min_tail_chars=72)
    assert len(merged) == 1
    assert short_b in merged[0]
    # Tail not short — no merge
    assert len(merge_trailing_short_chunks(["a", "b" * 80], 220)) == 2


def test_split_raw_streaming_short_doc_no_suffix() -> None:
    raw = "One\n\nTwo\n\nThree"
    pre, suf = split_raw_for_streaming_preprocess(raw, 50_000)
    assert suf == ""
    assert "One" in pre and "Three" in pre


def test_split_raw_streaming_budget_splits_paragraphs() -> None:
    p1 = "a" * 100
    p2 = "b" * 100
    p3 = "c" * 100
    raw = f"{p1}\n\n{p2}\n\n{p3}"
    pre, suf = split_raw_for_streaming_preprocess(raw, 150)
    assert p1 in pre
    assert p3 in suf or p2 in suf


def test_build_runtime_settings_default_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NARRATOR_SPEAK_CHUNK_MAX_CHARS", raising=False)
    from narrator.settings import build_runtime_settings

    r = build_runtime_settings(
        config_explicit=None,
        voice=None,
        rate=None,
        volume=None,
        speak_hotkey=None,
        listen_hotkey=None,
        legacy_hotkey=None,
        silent=False,
        verbose=False,
    )
    assert r.speak_chunk_max_chars == 8000


def test_build_runtime_settings_piper_forces_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("narrator.settings._resolve_speak_engine", lambda _requested, **kw: "piper")
    from narrator.settings import build_runtime_settings

    r = build_runtime_settings(
        config_explicit=None,
        voice=None,
        rate=None,
        volume=None,
        speak_hotkey=None,
        listen_hotkey=None,
        legacy_hotkey=None,
        silent=False,
        verbose=False,
    )
    assert r.speak_engine == "piper"
    assert r.speak_text_llm_enabled is True
    assert r.speak_text_llm_model == DEFAULT_SPEAK_TEXT_LLM_MODEL
    assert r.speak_text_llm_builtin_rules is True


def test_build_runtime_settings_winrt_does_not_force_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("narrator.settings._resolve_speak_engine", lambda _requested, **kw: "winrt")
    from narrator.settings import build_runtime_settings

    r = build_runtime_settings(
        config_explicit=None,
        voice=None,
        rate=None,
        volume=None,
        speak_hotkey=None,
        listen_hotkey=None,
        legacy_hotkey=None,
        silent=False,
        verbose=False,
    )
    assert r.speak_engine == "winrt"
    assert r.speak_text_llm_enabled is False


def test_build_runtime_settings_piper_keeps_explicit_llm_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("narrator.settings._resolve_speak_engine", lambda _requested, **kw: "piper")
    p = tmp_path / "config.toml"
    p.write_text('speak_text_llm_model = "custom-llm-id"\n', encoding="utf-8")
    from narrator.settings import build_runtime_settings

    r = build_runtime_settings(
        config_explicit=p,
        voice=None,
        rate=None,
        volume=None,
        speak_hotkey=None,
        listen_hotkey=None,
        legacy_hotkey=None,
        silent=False,
        verbose=False,
    )
    assert r.speak_text_llm_model == "custom-llm-id"


def test_build_runtime_settings_llm_builtin_rules_false(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("narrator.settings._resolve_speak_engine", lambda _requested, **kw: "piper")
    p = tmp_path / "config.toml"
    p.write_text("speak_text_llm_builtin_rules = false\n", encoding="utf-8")
    from narrator.settings import build_runtime_settings

    r = build_runtime_settings(
        config_explicit=p,
        voice=None,
        rate=None,
        volume=None,
        speak_hotkey=None,
        listen_hotkey=None,
        legacy_hotkey=None,
        silent=False,
        verbose=False,
    )
    assert r.speak_text_llm_builtin_rules is False
