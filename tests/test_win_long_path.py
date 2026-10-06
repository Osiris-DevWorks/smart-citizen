"""Windows long-path support (issue #221 follow-up). A deeply nested
portable/tester install directory (or a zip extracted into an already
same-named folder, doubling a path segment) pushes individual DataForge XML
paths past the legacy 260-char Windows MAX_PATH — even though the file is
right there, Windows file APIs refuse it with a raw ``WinError 3`` ("cannot
find the path specified"). ``win_paths.win_long_path`` sidesteps this with
the ``\\\\?\\`` extended-length prefix, which Windows honors on every
supported version with no machine-wide configuration needed (unlike the
inbox "Enable Win32 long paths" policy, which requires admin rights and
isn't guaranteed to be on for any given user).

The ``win_paths.win_long_path`` helper (#221) already covered
``pak_extractor.py``'s copy/cleanup step and ``dataforge_patcher.py``'s
patch target reads. This file locks the follow-up fix: ``dataforge_diff.py``
(where a real crash was reported —
the post-extraction snapshot/hash pass had no long-path protection at all),
``pak_extractor.py``'s ``extract_dataforge``/``dataforge_cache_is_fresh``
entry points, and ``generate_enhancements_ini.py``'s ``main()`` (20+
``ET.parse`` call sites and 18+ ``rglob`` walks, all fixed for free by
wrapping the single ``forge_dir`` root they all derive from).
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from utils.win_paths import win_long_path, win_plain_path  # noqa: E402
from utils import dataforge_diff  # noqa: E402
from utils.pak_extractor import dataforge_cache_is_fresh  # noqa: E402

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def gen_module():
    """Load scripts/generate_enhancements_ini.py (lives outside src/)."""
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "generate_enhancements_ini.py"
    spec = importlib.util.spec_from_file_location("gen_long_path_test", script_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestWinLongPath:
    """The core ``\\\\?\\`` prefixing primitive."""

    def test_adds_prefix_on_windows(self):
        with patch("sys.platform", "win32"):
            result = win_long_path("C:\\Users\\test\\file.xml")
            assert result.startswith("\\\\?\\")
            assert result.endswith("file.xml")

    def test_idempotent_already_prefixed(self):
        with patch("sys.platform", "win32"):
            once = win_long_path("C:\\Users\\test\\file.xml")
            twice = win_long_path(once)
            assert once == twice
            assert twice.count("\\\\?\\") == 1

    def test_unc_path_gets_unc_prefix(self):
        with patch("sys.platform", "win32"):
            result = win_long_path("\\\\server\\share\\file.xml")
            assert result.startswith("\\\\?\\UNC\\")
            assert "server\\share\\file.xml" in result

    def test_noop_on_non_windows(self):
        with patch("sys.platform", "linux"):
            result = win_long_path("/home/test/file.xml")
            assert not result.startswith("\\\\?\\")

    def test_accepts_path_object(self):
        with patch("sys.platform", "win32"):
            result = win_long_path(Path("C:\\Users\\test\\file.xml"))
            assert result.startswith("\\\\?\\")


class TestWinPlainPath:
    """The inverse, for paths handed to the P4K tools or compared as text (#471)."""

    def test_round_trips_a_drive_path(self):
        with patch("sys.platform", "win32"):
            plain = "C:\\Users\\test\\cache\\dataforge"
            assert win_plain_path(win_long_path(plain)) == plain

    def test_round_trips_a_share(self):
        with patch("sys.platform", "win32"):
            share = "\\\\server\\share\\SC\\cache"
            long = win_long_path(share)
            assert long.startswith("\\\\?\\UNC\\")
            assert win_plain_path(long) == share

    def test_a_plain_path_comes_back_absolute(self):
        with patch("sys.platform", "win32"):
            assert win_plain_path("C:\\a\\b\\..\\c") == "C:\\a\\c"

    def test_accepts_path_object(self):
        with patch("sys.platform", "win32"):
            assert win_plain_path(Path("\\\\?\\C:\\x")) == "C:\\x"

    def test_noop_on_non_windows(self):
        with patch("sys.platform", "linux"):
            assert win_plain_path("/home/test") == "/home/test"


class TestDataforgeDiffLongPath:
    """#221 follow-up: the post-extraction snapshot/hash pass — where the
    real crash was reported — must wrap its cache_dir like every other
    DataForge-cache consumer."""

    def test_update_manifest_wraps_cache_dir(self, tmp_path):
        cache_dir = tmp_path / "dataforge"
        (cache_dir / "libs").mkdir(parents=True)
        (cache_dir / "libs" / "a.xml").write_text("<x/>")

        with patch(
            "utils.dataforge_diff.win_long_path", wraps=win_long_path
        ) as spy:
            dataforge_diff.update_manifest(cache_dir)
            spy.assert_called_once_with(cache_dir)

    def test_dirty_categories_wraps_cache_dir(self, tmp_path):
        cache_dir = tmp_path / "dataforge"
        (cache_dir / "libs").mkdir(parents=True)
        (cache_dir / "libs" / "a.xml").write_text("<x/>")
        dataforge_diff.update_manifest(cache_dir)

        with patch(
            "utils.dataforge_diff.win_long_path", wraps=win_long_path
        ) as spy:
            result = dataforge_diff.dirty_categories(cache_dir)
            spy.assert_called_once_with(cache_dir)
            assert result == set()  # nothing changed since the manifest snapshot

    def test_update_manifest_and_dirty_categories_still_work_normally(self, tmp_path):
        """Functional sanity check: wrapping doesn't change real behavior on
        an ordinary (short) path."""
        cache_dir = tmp_path / "dataforge"
        (cache_dir / "libs").mkdir(parents=True)
        (cache_dir / "libs" / "a.xml").write_text("<x/>")

        assert dataforge_diff.dirty_categories(cache_dir) is None  # no manifest yet
        dataforge_diff.update_manifest(cache_dir)
        assert dataforge_diff.dirty_categories(cache_dir) == set()

        (cache_dir / "libs" / "a.xml").write_text("<x changed='1'/>")
        changed = dataforge_diff.dirty_categories(cache_dir)
        assert changed is not None


class TestPakExtractorLongPath:
    """extract_dataforge / dataforge_cache_is_fresh must wrap
    dataforge_cache_dir at their own entry point (not rely solely on
    _copy_filtered_records' internal wrapping further down the call)."""

    def test_dataforge_cache_is_fresh_wraps_cache_dir(self, tmp_path):
        p4k_path = tmp_path / "Data.p4k"
        p4k_path.write_text("dummy")
        os.utime(p4k_path, (1_000_000_000, 1_000_000_000))

        cache_dir = tmp_path / "dataforge"
        libs = cache_dir / "raw" / "libs"
        libs.mkdir(parents=True)
        (libs / "a.xml").write_text("<x/>")
        (cache_dir / ".p4k_mtime").write_text("2000000000")

        with patch(
            "utils.pak_extractor._win_long_path", wraps=win_long_path
        ) as spy:
            result = dataforge_cache_is_fresh(p4k_path, cache_dir)
            assert result is True
            spy.assert_any_call(cache_dir)


class TestGenerateEnhancementsIniLongPath:
    """generate_enhancements_ini.py has 20+ ET.parse and 18+ rglob call
    sites reading the DataForge cache — all fixed at once by wrapping the
    single forge_dir root every one of them derives from."""

    def test_win_long_path_importable(self, gen_module):
        assert callable(gen_module.win_long_path)

    def test_win_long_path_has_safe_fallback_shape(self, gen_module):
        """Even in the (untriggered) ImportError fallback shape, calling the
        name must not raise — it degrades to a str() passthrough."""
        result = gen_module.win_long_path("some/path.xml")
        assert "path.xml" in str(result)

    def test_main_wraps_forge_dir(self, gen_module, tmp_path):
        """main() must call win_long_path on forge_dir before deriving
        records/ so every downstream ET.parse/rglob inherits long-path
        safety. Exercised via the real (short) fixture cache so we assert
        on the call, not on the OS-dependent long-path behavior itself."""
        base_ini = tmp_path / "base.ini"
        base_ini.write_text("some_key=Some Value\n", encoding="utf-8")
        forge_dir = tmp_path / "dataforge"
        (forge_dir / "raw" / "libs" / "foundry" / "records").mkdir(parents=True)

        with patch.object(
            gen_module, "win_long_path", wraps=gen_module.win_long_path
        ) as spy:
            gen_module.main(base_ini, forge_dir, categories=set())
            spy.assert_any_call(forge_dir)
