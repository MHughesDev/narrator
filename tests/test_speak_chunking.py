"""Long-document TTS chunking."""

from __future__ import annotations

import pytest

from narrator.speak_chunking import clamp_chunk_max_chars, iter_tts_chunks


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
