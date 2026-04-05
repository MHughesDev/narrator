"""Tests for narrator.speak_text_llm (mocked HTTP)."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from narrator.speak_text_llm import (
    chat_completion,
    chunk_bundle_ranges,
    load_rules_text,
    ready_chunk_for_speech,
    ready_chunks_for_speech,
)
from narrator.speak_text_llm import _parse_marked_bundle

_ANCHOR = "narrator_speak_llm_builtin_v1"


class _RulesSettings:
    speak_text_llm_builtin_rules = True
    speak_text_llm_rules = ""
    speak_text_llm_rules_file = None


class _FakeResp:
    def __init__(self, payload: dict) -> None:
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._raw

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *a: object) -> None:
        return None


class TestSpeakTextLlm(unittest.TestCase):
    def test_parse_marked_bundle_lenient_without_end(self) -> None:
        raw = (
            "<<<CHUNK 1>>>\nfirst block\n"
            "<<<CHUNK 2>>>\nsecond here\n"
            "<<<CHUNK 3>>>\nthree\n"
            "<<<CHUNK 4>>>\nfour"
        )
        out = _parse_marked_bundle(raw, 4)
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(out[0], "first block")
        self.assertEqual(out[1], "second here")
        self.assertEqual(out[2], "three")
        self.assertEqual(out[3], "four")

    def test_parse_marked_bundle_strips_markdown_fence(self) -> None:
        raw = (
            "```text\n"
            "<<<CHUNK 1>>>\na\n<<<END>>>\n"
            "<<<CHUNK 2>>>\nb\n<<<END>>>\n"
            "```"
        )
        out = _parse_marked_bundle(raw, 2)
        self.assertEqual(out, ["a", "b"])

    def test_chat_completion_parses_message(self) -> None:
        payload = {"choices": [{"message": {"content": "  hello world  "}}]}
        with patch("narrator.speak_text_llm.urllib.request.urlopen") as m:
            m.return_value = _FakeResp(payload)
            out = chat_completion(
                base_url="http://127.0.0.1:11434/v1",
                model="m",
                api_key=None,
                system_prompt="s",
                user_message="u",
                timeout_s=30.0,
            )
            self.assertEqual(out, "hello world")

    def test_load_rules_text_includes_builtin_when_enabled(self) -> None:
        text = load_rules_text(_RulesSettings())
        self.assertIn(_ANCHOR, text)

    def test_load_rules_text_skips_builtin_when_disabled(self) -> None:
        class _Off:
            speak_text_llm_builtin_rules = False
            speak_text_llm_rules = ""
            speak_text_llm_rules_file = None

        self.assertEqual(load_rules_text(_Off()), "")

    def test_ready_chunk_system_includes_builtin_rules(self) -> None:
        captured: dict = {}

        def _opener(req: object, *a: object, **kw: object):
            data = getattr(req, "data", None)
            assert data is not None
            captured["body"] = json.loads(data.decode("utf-8"))
            return _FakeResp({"choices": [{"message": {"content": "y"}}]})

        class _S:
            speak_text_llm_model = "m"
            speak_text_llm_base_url = "http://127.0.0.1:11434/v1"
            speak_text_llm_api_key = None
            speak_text_llm_timeout_s = 30.0
            speak_text_llm_max_chunk_chars = 6000
            speak_text_llm_rules = ""
            speak_text_llm_rules_file = None
            speak_text_llm_builtin_rules = True
            verbose = False

        with patch("narrator.speak_text_llm.urllib.request.urlopen", side_effect=_opener):
            out = ready_chunk_for_speech("chunk body", _S())
        self.assertEqual(out, "y")
        sys_content = captured["body"]["messages"][0]["content"]
        self.assertIn("CONSTRAINTS", sys_content)
        self.assertIn("RULES:", sys_content)
        self.assertIn(_ANCHOR, sys_content)

    def test_ready_chunk_fallback_on_empty_model(self) -> None:
        class _S:
            speak_text_llm_model = ""
            speak_text_llm_base_url = "http://127.0.0.1:11434/v1"
            speak_text_llm_api_key = None
            speak_text_llm_timeout_s = 30.0
            speak_text_llm_max_chunk_chars = 6000
            speak_text_llm_rules = ""
            speak_text_llm_rules_file = None
            speak_text_llm_builtin_rules = True
            verbose = False

        t = "alpha beta"
        self.assertEqual(ready_chunk_for_speech(t, _S()), t)

    def test_ready_chunk_empty_llm_omits_non_speech_segment(self) -> None:
        def _opener(req: object, *a: object, **kw: object):
            return _FakeResp({"choices": [{"message": {"content": "   "}}]})

        class _S:
            speak_text_llm_model = "m"
            speak_text_llm_base_url = "http://127.0.0.1:11434/v1"
            speak_text_llm_api_key = None
            speak_text_llm_timeout_s = 30.0
            speak_text_llm_max_chunk_chars = 6000
            speak_text_llm_rules = ""
            speak_text_llm_rules_file = None
            speak_text_llm_builtin_rules = True
            verbose = False

        with patch("narrator.speak_text_llm.urllib.request.urlopen", side_effect=_opener):
            out = ready_chunk_for_speech("References\n[1] Foo et al.", _S())
        self.assertEqual(out, "")

    def test_chunk_bundle_ranges_respects_count(self) -> None:
        class _S:
            speak_text_llm_bundle_chunks = 3
            speak_text_llm_bundle_max_chars = 999_999
            speak_text_llm_max_chunk_chars = 6000

        r = chunk_bundle_ranges(["a", "b", "c", "d", "e"], _S())
        self.assertEqual(r, [(0, 3), (3, 5)])

    def test_ready_chunks_bundle_one_http_call(self) -> None:
        class _S:
            speak_text_llm_enabled = True
            speak_text_llm_model = "m"
            speak_text_llm_base_url = "http://127.0.0.1:11434/v1"
            speak_text_llm_api_key = None
            speak_text_llm_timeout_s = 30.0
            speak_text_llm_max_chunk_chars = 6000
            speak_text_llm_bundle_chunks = 2
            speak_text_llm_bundle_max_chars = 16000
            speak_text_llm_rules = ""
            speak_text_llm_rules_file = None
            speak_text_llm_builtin_rules = True
            speak_engine = "winrt"
            verbose = False

        content = (
            "<<<CHUNK 1>>>\nfirst\n<<<END>>>\n<<<CHUNK 2>>>\nsecond\n<<<END>>>"
        )
        payload = {"choices": [{"message": {"content": content}}]}
        with patch("narrator.speak_text_llm.urllib.request.urlopen") as m:
            m.return_value = _FakeResp(payload)
            out = ready_chunks_for_speech(["aaa", "bbb"], _S())
        self.assertEqual(out, ["first", "second"])

    def test_ready_chunks_bundle_allows_empty_middle_chunk(self) -> None:
        class _S:
            speak_text_llm_enabled = True
            speak_text_llm_model = "m"
            speak_text_llm_base_url = "http://127.0.0.1:11434/v1"
            speak_text_llm_api_key = None
            speak_text_llm_timeout_s = 30.0
            speak_text_llm_max_chunk_chars = 6000
            speak_text_llm_bundle_chunks = 3
            speak_text_llm_bundle_max_chars = 16000
            speak_text_llm_rules = ""
            speak_text_llm_rules_file = None
            speak_text_llm_builtin_rules = True
            speak_engine = "winrt"
            verbose = False

        content = (
            "<<<CHUNK 1>>>\nintro\n<<<END>>>\n<<<CHUNK 2>>>\n\n<<<END>>>\n<<<CHUNK 3>>>\noutro\n<<<END>>>"
        )
        payload = {"choices": [{"message": {"content": content}}]}
        with patch("narrator.speak_text_llm.urllib.request.urlopen") as m:
            m.return_value = _FakeResp(payload)
            out = ready_chunks_for_speech(["a", "b", "c"], _S())
        self.assertEqual(out, ["intro", "", "outro"])


if __name__ == "__main__":
    unittest.main()
