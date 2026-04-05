"""Tests for scripts/prefetch_utils (cache / Piper layout helpers)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Import from repo scripts/ (same pattern as bootstrap adding scripts to path).
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from prefetch_utils import (  # noqa: E402
    DEFAULT_XTTS_MODEL_ID,
    hf_hub_cache_roots,
    piper_voice_files_ready,
    xtts_cache_likely_ready,
)


class TestPiperVoiceFilesReady(unittest.TestCase):
    def test_missing_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            self.assertFalse(piper_voice_files_ready("en_US-ryan-high", d))

    def test_both_present_nonempty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            vid = "en_US-ryan-high"
            (d / f"{vid}.onnx").write_bytes(b"x")
            (d / f"{vid}.onnx.json").write_text("{}")
            self.assertTrue(piper_voice_files_ready(vid, d))


class TestHfHubCacheRoots(unittest.TestCase):
    def test_default_includes_user_cache(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_home = Path(td)
            with (
                mock.patch.dict(os.environ, {}, clear=True),
                mock.patch("prefetch_utils.Path.home", return_value=fake_home),
            ):
                roots = hf_hub_cache_roots()
            expected = fake_home / ".cache" / "huggingface" / "hub"
            self.assertIn(expected, roots)


class TestXttsCacheLikelyReady(unittest.TestCase):
    def test_false_when_empty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            hub_root = Path(td)
            with (
                mock.patch("prefetch_utils.hf_hub_cache_roots", return_value=[hub_root]),
                mock.patch(
                    "prefetch_utils._coqui_local_tts_has_large_xtts_artifact",
                    return_value=False,
                ),
            ):
                self.assertFalse(xtts_cache_likely_ready(DEFAULT_XTTS_MODEL_ID))

    def test_true_when_hub_slug_has_snapshot_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            hub_root = Path(td)
            slug = "models--tts_models--multilingual--multi-dataset--xtts_v1.1"
            snap_dir = hub_root / slug / "snapshots" / "abc123"
            snap_dir.mkdir(parents=True)
            (snap_dir / "config.json").write_text("{}")
            with (
                mock.patch("prefetch_utils.hf_hub_cache_roots", return_value=[hub_root]),
                mock.patch(
                    "prefetch_utils._coqui_local_tts_has_large_xtts_artifact",
                    return_value=False,
                ),
            ):
                self.assertTrue(xtts_cache_likely_ready(DEFAULT_XTTS_MODEL_ID))


if __name__ == "__main__":
    unittest.main()
