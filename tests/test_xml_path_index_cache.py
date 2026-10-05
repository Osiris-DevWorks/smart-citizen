r"""Regression test for the xml_path_index lookup-cache invalidation bug.

xml_path_index had no entry in _LOOKUP_VERSIONS before this fix, so it
silently defaulted to "v1" forever. #231 started wrapping forge_dir (and
everything derived from it, including records_dir) via win_paths.win_long_path
before building this index, changing the shape of the path strings it stores
(unprefixed -> \\?\-prefixed) without a version bump. A pickle built by a
pre-#231 run was then reused indefinitely against a post-#231 run's now-
prefixed comparison paths (e.g. bp_dir), crashing scan_crafting_blueprints's
xml_file.relative_to(bp_dir) with "not in the subpath of" against a real
DataForge cache that had been generated before.
"""
from __future__ import annotations

import importlib.util
import pickle
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.fixture(scope="module")
def gen_module():
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "generate_enhancements_ini.py"
    spec = importlib.util.spec_from_file_location(
        "generate_enhancements_ini_xml_path_index_test", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestXmlPathIndexCacheVersion:
    def test_xml_path_index_has_a_pinned_version(self, gen_module):
        assert "xml_path_index" in gen_module._LOOKUP_VERSIONS, (
            "xml_path_index must have its own _LOOKUP_VERSIONS entry (not "
            "silently default to 'v1') so a future shape/format change forces "
            "a rebuild instead of reusing a stale pickle indefinitely."
        )

    def test_stale_pre_bump_pickle_is_invalidated(self, gen_module, tmp_path):
        forge_dir = tmp_path / "forge"
        (forge_dir / ".lookups").mkdir(parents=True)
        (forge_dir / ".p4k_mtime").write_text("teststamp123", encoding="utf-8")

        # Simulate a pickle written by the pre-fix code: version "v1" (the
        # default before this _LOOKUP_VERSIONS entry existed) holding an
        # unprefixed path, matching the shape a pre-#231 run would have
        # stored.
        stale_key = "v1:teststamp123"
        stale_value = {"some_subdir": ["C:\\unwrapped\\path\\file.xml"]}
        with (forge_dir / ".lookups" / "xml_path_index.pkl").open("wb") as f:
            pickle.dump((stale_key, stale_value), f)

        fresh_value = {"some_subdir": ["\\\\?\\C:\\wrapped\\path\\file.xml"]}
        result = gen_module._cached_lookup(
            forge_dir, "xml_path_index", lambda: fresh_value
        )

        assert result == fresh_value, (
            "A pre-#231 xml_path_index pickle (implicit version v1) must be "
            "treated as stale now that xml_path_index has its own pinned "
            "version, not reused just because the DataForge fingerprint "
            "still matches."
        )

    def test_matching_version_pickle_is_still_reused(self, gen_module, tmp_path):
        """Sanity check the other half of the contract: a pickle already
        written under the current version must still be a cache hit (this
        fix isn't supposed to defeat caching entirely, just invalidate the
        stale pre-#231 shape)."""
        forge_dir = tmp_path / "forge"
        (forge_dir / ".lookups").mkdir(parents=True)
        (forge_dir / ".p4k_mtime").write_text("teststamp456", encoding="utf-8")

        current_version = gen_module._LOOKUP_VERSIONS["xml_path_index"]
        cached_value = {"some_subdir": ["\\\\?\\C:\\wrapped\\path\\file.xml"]}
        with (forge_dir / ".lookups" / "xml_path_index.pkl").open("wb") as f:
            pickle.dump((f"{current_version}:teststamp456", cached_value), f)

        builder_called = []

        def _builder():
            builder_called.append(True)
            return {"different": ["should not be used"]}

        result = gen_module._cached_lookup(forge_dir, "xml_path_index", _builder)

        assert result == cached_value
        assert not builder_called, "A matching-version pickle should be a cache hit"
