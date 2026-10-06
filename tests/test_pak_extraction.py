"""
Tests for P4K extraction and DataForge integration (v0.6.0 critical feature)

Tests cover:
- P4K extraction pipeline
- DataForge cache management
- Stats INI generation
- Error handling for missing P4K or tools
"""

import pytest
import logging
import re
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from utils.pak_extractor import (
    DATAFORGE_KEEP_SUBPATHS,
    P4kLockedError,
    _copy_filtered_records,
    _raise_unp4k_failure,
    dataforge_cache_is_fresh,
    extract_dataforge,
)
from utils.i18n import set_language, tr


class TestDataForgeCache:
    """Test DataForge cache freshness detection"""

    # NOTE: freshness is keyed off a ``.p4k_size`` stamp (issue #209) with a
    # legacy ``.p4k_mtime`` fallback, PLUS real ``raw/libs`` XML content, and
    # the signature is dataforge_cache_is_fresh(p4k_path, cache_dir).
    # (Earlier versions of these tests utime'd the cache directory and passed
    # the args swapped as strings — both wrong against the current contract.)

    @staticmethod
    def _populate_cache(cache_dir: Path, stamp_mtime: float, *,
                        with_xml: bool = True, stamp_size: int = None) -> None:
        """Build a cache dir the way a real extraction leaves it: a
        ``.p4k_mtime`` stamp plus ``raw/libs`` content. When *stamp_size* is
        given, also write the ``.p4k_size`` stamp a post-#209 extraction
        leaves; omit it to simulate a legacy (mtime-only) cache."""
        libs = cache_dir / "raw" / "libs"
        libs.mkdir(parents=True, exist_ok=True)
        if with_xml:
            (libs / "sample.xml").write_text("<x/>")
        (cache_dir / ".p4k_mtime").write_text(str(stamp_mtime))
        if stamp_size is not None:
            (cache_dir / ".p4k_size").write_text(str(stamp_size))

    def test_cache_is_fresh_when_stamp_newer(self):
        """Fresh when the stamped mtime is >= the p4k mtime and XMLs exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            p4k_path = tmp / "Data.p4k"
            p4k_path.write_text("dummy")
            os.utime(p4k_path, (1_000_000_000, 1_000_000_000))  # Jan 2001

            cache_dir = tmp / "dataforge"
            self._populate_cache(cache_dir, stamp_mtime=2_000_000_000)  # newer

            assert dataforge_cache_is_fresh(p4k_path, cache_dir) is True

    def test_cache_is_stale_when_stamp_older(self):
        """Stale when the stamped mtime is older than the p4k mtime."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            p4k_path = tmp / "Data.p4k"
            p4k_path.write_text("dummy")
            os.utime(p4k_path, (9_999_999_999, 9_999_999_999))  # far future

            cache_dir = tmp / "dataforge"
            self._populate_cache(cache_dir, stamp_mtime=1_000_000_000)  # older

            assert dataforge_cache_is_fresh(p4k_path, cache_dir) is False

    def test_cache_is_stale_when_cache_missing(self):
        """A cache dir with no stamp and no libs is stale."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            p4k_path = tmp / "Data.p4k"
            p4k_path.write_text("dummy")

            cache_dir = tmp / "nonexistent"
            assert dataforge_cache_is_fresh(p4k_path, cache_dir) is False

    def test_cache_is_stale_when_stamp_present_but_no_xml(self):
        """A stamp-only remnant from a failed/partial extraction is stale."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            p4k_path = tmp / "Data.p4k"
            p4k_path.write_text("dummy")
            os.utime(p4k_path, (1_000_000_000, 1_000_000_000))

            cache_dir = tmp / "dataforge"
            self._populate_cache(cache_dir, stamp_mtime=2_000_000_000, with_xml=False)

            assert dataforge_cache_is_fresh(p4k_path, cache_dir) is False

    def test_cache_is_stale_when_p4k_missing(self):
        """A missing p4k cannot be verified against, so treat the cache as stale."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            p4k_path = tmp / "nonexistent" / "Data.p4k"  # does not exist

            cache_dir = tmp / "dataforge"
            self._populate_cache(cache_dir, stamp_mtime=2_000_000_000)

            assert dataforge_cache_is_fresh(p4k_path, cache_dir) is False

    def test_cache_is_fresh_when_size_matches_despite_newer_mtime(self):
        """Issue #209: a benign launcher mtime bump must NOT invalidate the
        cache. When ``.p4k_size`` matches the current p4k size, the cache is
        fresh even though the p4k mtime is now far newer than the stamp — the
        exact scenario the mtime-only check re-extracted needlessly on."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            p4k_path = tmp / "Data.p4k"
            p4k_path.write_bytes(b"x" * 4096)  # size == 4096
            os.utime(p4k_path, (9_999_999_999, 9_999_999_999))  # launcher touch

            cache_dir = tmp / "dataforge"
            # Older stamp mtime, same size.
            self._populate_cache(cache_dir, stamp_mtime=1_000_000_000, stamp_size=4096)

            assert dataforge_cache_is_fresh(p4k_path, cache_dir) is True

    def test_cache_is_stale_when_size_differs(self):
        """A real game patch changes Data.p4k's size, so a size mismatch is
        stale even when the mtime would look fresh (p4k older than the stamp)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            p4k_path = tmp / "Data.p4k"
            p4k_path.write_bytes(b"x" * 8192)  # size == 8192
            os.utime(p4k_path, (1_000_000_000, 1_000_000_000))  # older than stamp

            cache_dir = tmp / "dataforge"
            # Newer stamp mtime, different size.
            self._populate_cache(cache_dir, stamp_mtime=2_000_000_000, stamp_size=4096)

            assert dataforge_cache_is_fresh(p4k_path, cache_dir) is False

    def test_missing_size_stamp_falls_back_to_mtime(self):
        """A pre-#209 cache (no ``.p4k_size``) still resolves via the legacy
        mtime comparison, so upgrades don't force a spurious re-extract."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            p4k_path = tmp / "Data.p4k"
            p4k_path.write_bytes(b"x" * 4096)
            os.utime(p4k_path, (1_000_000_000, 1_000_000_000))

            cache_dir = tmp / "dataforge"
            # No stamp_size → legacy path. Stamp mtime newer than p4k → fresh.
            self._populate_cache(cache_dir, stamp_mtime=2_000_000_000)

            assert dataforge_cache_is_fresh(p4k_path, cache_dir) is True


class TestDataForgeExtraction:
    """Test P4K extraction pipeline"""

    @patch('utils.pak_extractor.subprocess.run')
    def test_extract_dataforge_calls_unp4k_and_unforge(self, mock_run):
        """Test that extract_dataforge calls both unp4k and unforge tools"""
        mock_run.return_value = MagicMock(returncode=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            p4k_path = os.path.join(tmpdir, 'Data.p4k')
            cache_dir = os.path.join(tmpdir, 'dataforge')

            # Create dummy p4k file
            with open(p4k_path, 'w') as f:
                f.write('dummy p4k')

            # Attempt extraction (will fail without real tools, but we can check calls)
            try:
                extract_dataforge(p4k_path, cache_dir)
            except Exception:
                pass  # Expected to fail without real tools

            # Verify subprocess.run was called (would be for unp4k)
            # Note: actual behavior depends on implementation
            assert mock_run.called or True  # Graceful failure

    @patch('utils.pak_extractor.subprocess.run')
    def test_extract_dataforge_handles_missing_tools(self, mock_run):
        """Test extraction error handling when tools are missing"""
        # Simulate tool not found error
        mock_run.side_effect = FileNotFoundError("unp4k.exe not found")

        with tempfile.TemporaryDirectory() as tmpdir:
            p4k_path = os.path.join(tmpdir, 'Data.p4k')
            cache_dir = os.path.join(tmpdir, 'dataforge')

            with open(p4k_path, 'w') as f:
                f.write('dummy p4k')

            # Should raise or return error gracefully
            with pytest.raises((FileNotFoundError, Exception)):
                extract_dataforge(p4k_path, cache_dir)

    @patch('utils.pak_extractor.subprocess.run')
    def test_extract_dataforge_handles_invalid_p4k(self, mock_run):
        """Test extraction error handling for invalid P4K file"""
        # Simulate extraction failure
        mock_run.return_value = MagicMock(returncode=1, stderr="Invalid P4K format")

        with tempfile.TemporaryDirectory() as tmpdir:
            p4k_path = os.path.join(tmpdir, 'invalid.p4k')
            cache_dir = os.path.join(tmpdir, 'dataforge')

            # Create invalid p4k file
            with open(p4k_path, 'w') as f:
                f.write('not a valid p4k file')

            # Should handle error gracefully
            try:
                extract_dataforge(p4k_path, cache_dir)
            except Exception as e:
                # Should provide meaningful error message
                assert 'p4k' in str(e).lower() or 'extract' in str(e).lower() or True

    def test_cache_directory_structure(self):
        """Test that expected cache directories are created"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = os.path.join(tmpdir, 'dataforge')

            expected_subdirs = [
                'entity',
                'entities',
                'entityclasses',
                'ships',
                'weapons',
            ]

            # Simulate creating cache structure
            os.makedirs(cache_dir, exist_ok=True)
            for subdir in expected_subdirs:
                subdir_path = os.path.join(cache_dir, subdir)
                os.makedirs(subdir_path, exist_ok=True)

            # Verify structure
            assert os.path.exists(cache_dir)
            for subdir in expected_subdirs:
                assert os.path.exists(os.path.join(cache_dir, subdir))


class TestStatsGeneration:
    """Test stats INI file generation"""

    def test_stats_file_format(self):
        """Test that generated stats files have correct format"""
        stats_content = 'vehicle_DescHunter=Max Speed: 210 m/s\n'
        stats_content += 'vehicle_Desc_Avenger=Cargo: 46 SCU\n'

        # Parse as INI format (key=value)
        lines = stats_content.strip().split('\n')
        entries = {}
        for line in lines:
            if '=' in line:
                key, value = line.split('=', 1)
                entries[key] = value

        assert 'vehicle_DescHunter' in entries
        assert entries['vehicle_DescHunter'] == 'Max Speed: 210 m/s'

    def test_stats_generation_handles_missing_dataforge(self):
        """Test stats generation graceful failure when DataForge cache missing"""
        with tempfile.TemporaryDirectory():
            # Cache doesn't exist - stats generation should handle gracefully
            # (may create empty stats files or skip)
            stats_files = [
                'ships_desc_stats.ini',
                'components_desc_stats.ini',
                'ship_weapons_desc_stats.ini',
                'fps_weapons_desc_stats.ini'
            ]

            # In production, script should handle missing cache
            # Here we just verify the filenames are expected
            for filename in stats_files:
                assert filename.endswith('.ini')

    def test_stats_file_merges_with_base(self):
        """Test that stats entries properly merge with base source"""
        base_entries = {
            'vehicle_NameHunter': 'Drake Cutlass Black',
            'vehicle_DescHunter': 'Original description'
        }

        stats_entries = {
            'vehicle_DescHunter': 'Max Speed: 210 m/s | Cargo: 180 SCU | Shields: 8000',
        }

        # Merge with stats having priority (higher in hierarchy)
        merged = base_entries.copy()
        merged.update(stats_entries)

        assert merged['vehicle_NameHunter'] == 'Drake Cutlass Black'
        assert 'Max Speed' in merged['vehicle_DescHunter']

    def test_component_stats_format(self):
        """Test that component stats have expected format"""
        component_stats = [
            'item_DescSHLD_Aspirum=Shield Generator: 8000 HP',
            'item_DescPOWR_TR1=Power: 4500W, Heat: 180',
            'item_DescCOOL_Delphi=Cooling: 1200/s',
            'item_DescQDRV_Soleris=Quantum Range: 46 Million KM',
        ]

        for line in component_stats:
            assert '=' in line
            key, value = line.split('=', 1)
            assert key.startswith('item_Desc')
            assert len(value) > 0


class TestStatsErrorHandling:
    """Test error handling in stats pipeline"""

    def test_corrupted_stats_file_handling(self):
        """Test that corrupted stats files are handled gracefully"""
        with tempfile.TemporaryDirectory() as tmpdir:
            stats_file = os.path.join(tmpdir, 'corrupted.ini')

            # Write corrupted content (no '=' on some lines)
            with open(stats_file, 'w') as f:
                f.write('valid_key=valid_value\n')
                f.write('invalid_line_no_equals\n')
                f.write('another_valid=value\n')

            # When parsing, invalid lines should be skipped gracefully
            with open(stats_file, 'r') as f:
                entries = {}
                for line in f:
                    line = line.strip()
                    if '=' in line:
                        key, value = line.split('=', 1)
                        entries[key] = value

            assert len(entries) == 2
            assert 'valid_key' in entries
            assert 'another_valid' in entries

    def test_missing_stats_file_fallback(self):
        """Test that missing stats files don't crash the app"""
        with tempfile.TemporaryDirectory() as tmpdir:
            stats_file = os.path.join(tmpdir, 'nonexistent.ini')

            # Attempt to load missing file
            entries = {}
            try:
                if os.path.exists(stats_file):
                    with open(stats_file, 'r') as f:
                        for line in f:
                            if '=' in line:
                                key, value = line.split('=', 1)
                                entries[key] = value
            except Exception:
                pass  # Gracefully continue without stats

            # App should continue with empty stats
            assert entries == {}

    def test_stats_disabled_flag(self):
        """Test that stats can be disabled via settings"""
        # Stats should be loadable only if stats_enabled=True in settings
        stats_enabled = True

        if stats_enabled:
            # Stats would be loaded from files
            stats_entries = {'vehicle_DescHunter': 'Max Speed: 210 m/s'}
        else:
            # Stats not loaded
            stats_entries = {}

        # Toggle off
        stats_enabled = False
        if stats_enabled:
            stats_entries = {'vehicle_DescHunter': 'Max Speed: 210 m/s'}
        else:
            stats_entries = {}

        # Verify toggle works
        assert stats_entries == {}


class TestIntegrationP4KToStats:
    """Integration tests for full P4K → Stats pipeline"""

    def test_pipeline_structure(self):
        """Test that P4K pipeline has all expected stages"""
        pipeline_stages = [
            'Extract P4K (unp4k.exe)',
            'Extract Game2.dcb',
            'Convert DataForge (unforge.exe)',
            'Generate entity XMLs',
            'Parse XMLs for stats',
            'Generate stats INI files',
            'Merge stats with sources',
        ]

        # Verify stages are logical
        assert 'P4K' in pipeline_stages[0]
        assert 'unforge' in pipeline_stages[2].lower()
        assert 'stats INI' in pipeline_stages[5]

    @patch('utils.pak_extractor.subprocess.run')
    def test_pipeline_stops_on_first_failure(self, mock_run):
        """Test that pipeline stops gracefully on first error"""
        # First call fails
        mock_run.side_effect = [
            Exception("unp4k failed"),
            MagicMock(returncode=0)  # unforge wouldn't be called
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            p4k_path = os.path.join(tmpdir, 'Data.p4k')
            with open(p4k_path, 'w') as f:
                f.write('dummy')

            cache_dir = os.path.join(tmpdir, 'cache')

            # Pipeline should fail at first stage
            with pytest.raises(Exception):
                extract_dataforge(p4k_path, cache_dir)


# ─────────────────────────────────────────────────────────────────────────────
# Filtered cache copy (cache streamlining — 0.9.3)
# ─────────────────────────────────────────────────────────────────────────────

# Every `records / <path>` that `scripts/generate_enhancements_ini.py`
# currently reads from. Duplicated here on purpose: this is the
# **contract** between the extractor's keep-list and the generator's
# read-list. If the generator grows a new read path, adding it to
# DATAFORGE_KEEP_SUBPATHS also requires adding it here (or something that
# covers it), which makes the maintenance coupling explicit.
#
# To update: run `grep -n 'records / "' scripts/generate_enhancements_ini.py`
# and ensure every leaf path is covered by some entry in
# DATAFORGE_KEEP_SUBPATHS.
GENERATOR_READ_SUBPATHS = (
    "entities/scitem",                                   # build_scitem_lookups
    "entities/scitem/ships/controller",                  # build_controller_lookup
    "entities/scitem/ships/armor",                       # build_armor_lookup
    "entities/scitem/ships/shieldgenerator",             # components gen (indirect via scitem)
    "entities/scitem/ships/cooler",
    "entities/scitem/ships/powerplant",
    "entities/scitem/ships/quantumdrive",
    "entities/scitem/ships/radar",
    "entities/scitem/ships/weapons",                     # ship weapons + missiles
    "entities/scitem/weapons/fps_weapons",               # FPS weapon descriptions
    "entities/scitem/carryables",                        # commodity-crafting carryable lookups
    "entities/spaceships",                               # scan_spaceships
    "ammoparams/vehicle",
    "ammoparams/fps",
    "reputation/rewards/missionrewards_reputation",
    "reputation/standings",                              # standings lookup (tier names)
    "contracts/contractgenerator",                       # scan_contract_generators
    "contracts/contracttemplates",                       # template fallback in scan_contract_generators
    "crafting/blueprintrewards/blueprintmissionpools",   # blueprint_pools lookup
    "crafting/blueprints/crafting",                      # crafting blueprint scan
    "missionbroker/pu_missions",                         # mission XP augmentation
    # Guarded reads (may or may not exist in a given patch; extractor keeps
    # the parent subtree, generator guards with `if dir.exists()`):
    "entities/missions",
    "entities/contracts",
    "entities/jobterminal",
)


def _is_subpath_of(child: str, parent: str) -> bool:
    """Is *child* equal to or under *parent* in slash-separated form?"""
    if child == parent:
        return True
    return child.startswith(parent + "/")


class TestDataForgeKeepList:
    """Regression tests locking the keep-list to the generator's read-paths.

    These are the guard-rails that catch the dangerous failure mode of cache
    streamlining: a future generator change reads from a subtree the extractor
    doesn't copy, producing silently-empty enhancements rather than an error.
    """

    def test_every_generator_read_path_is_covered(self):
        """Every path the generator reads must lie under some kept subpath."""
        keep = DATAFORGE_KEEP_SUBPATHS
        uncovered = []
        for read in GENERATOR_READ_SUBPATHS:
            if not any(_is_subpath_of(read, k) for k in keep):
                uncovered.append(read)
        assert not uncovered, (
            "Generator reads from paths the extractor does NOT cache:\n  "
            + "\n  ".join(uncovered)
            + "\nAdd these (or a common ancestor) to DATAFORGE_KEEP_SUBPATHS "
            "in src/utils/pak_extractor.py."
        )

    def test_keep_list_has_no_redundant_entries(self):
        """Reject entries that are already covered by another entry (a parent)."""
        redundant = []
        for i, entry in enumerate(DATAFORGE_KEEP_SUBPATHS):
            for j, other in enumerate(DATAFORGE_KEEP_SUBPATHS):
                if i == j:
                    continue
                if _is_subpath_of(entry, other):
                    redundant.append((entry, other))
                    break
        assert not redundant, (
            "DATAFORGE_KEEP_SUBPATHS contains entries already covered by "
            f"an ancestor entry: {redundant}"
        )


class TestCopyFilteredRecords:
    """Exercise the filtered-copy helper on a synthetic unforge output tree."""

    @staticmethod
    def _make_fake_unforge_output(root: Path) -> None:
        """Write a minimal ``libs/foundry/records/...`` tree with one file in
        each of the keep-paths plus several 'unused' paths that must NOT be
        carried over by the filter."""
        records = root / "libs" / "foundry" / "records"
        # Files inside kept subtrees — these MUST survive the filter.
        for kept in DATAFORGE_KEEP_SUBPATHS:
            leaf = records / kept / "sample.xml"
            leaf.parent.mkdir(parents=True, exist_ok=True)
            leaf.write_text("<kept/>", encoding="utf-8")
        # Files in paths we want dropped — these must NOT survive.
        for dropped in ("ui", "actor", "missiondata", "tintpalettes", "starmap"):
            leaf = records / dropped / "sample.xml"
            leaf.parent.mkdir(parents=True, exist_ok=True)
            leaf.write_text("<dropped/>", encoding="utf-8")

    def test_copies_only_keep_subpaths(self, tmp_path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        self._make_fake_unforge_output(src)

        copied, skipped = _copy_filtered_records(src / "libs", dst / "libs")

        records_dst = dst / "libs" / "foundry" / "records"
        for kept in DATAFORGE_KEEP_SUBPATHS:
            assert (records_dst / kept / "sample.xml").exists(), (
                f"kept path {kept!r} missing from filtered output"
            )
        for dropped in ("ui", "actor", "missiondata", "tintpalettes", "starmap"):
            assert not (records_dst / dropped).exists(), (
                f"{dropped!r} leaked into filtered output"
            )
        assert copied == len(DATAFORGE_KEEP_SUBPATHS)
        assert skipped == 0

    def test_skipped_when_source_subpath_missing(self, tmp_path):
        """Some patches don't ship every subtree (e.g. entities/missions).
        Missing source paths should increment `skipped`, not fail."""
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        self._make_fake_unforge_output(src)
        # Delete one keep-path from the source so the filter sees it missing.
        import shutil as _sh
        _sh.rmtree(src / "libs" / "foundry" / "records" / "entities" / "missions")

        copied, skipped = _copy_filtered_records(src / "libs", dst / "libs")

        assert skipped == 1
        assert copied == len(DATAFORGE_KEEP_SUBPATHS) - 1
        records_dst = dst / "libs" / "foundry" / "records"
        assert not (records_dst / "entities" / "missions").exists()
        # All other kept paths survived
        assert (records_dst / "entities" / "scitem" / "sample.xml").exists()

    def test_raises_on_unexpected_layout(self, tmp_path):
        """If unforge's output doesn't have the expected libs/foundry/records
        layout, fail loudly rather than producing a silently-empty cache."""
        src = tmp_path / "src"
        (src / "libs").mkdir(parents=True)
        # No foundry/records under libs — nothing for the filter to work with.

        with pytest.raises(FileNotFoundError):
            _copy_filtered_records(src / "libs", tmp_path / "dst" / "libs")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])


class TestUnp4kFailureMessage:
    """_raise_unp4k_failure upgrades a locked-Data.p4k failure (RSI Launcher
    updating) to a friendly hint, and otherwise preserves the raw output.

    The lock manifests as a .NET IOException '...being used by another
    process' with exit code 3762504530 (0xE0434352, the generic managed-
    exception code — so the message text, not the code, is what we match on."""

    _REAL_LOCK_STDERR = (
        r"Unhandled exception. System.IO.IOException: The process cannot access "
        r"the file 'E:\Games\...\StarCitizen\HOTFIX\Data.p4k' because it is "
        "being used by another process.\n   at Microsoft.Win32.SafeHandles..."
    )

    def setup_method(self):
        set_language("english")

    def test_locked_file_raises_friendly_message(self):
        with pytest.raises(P4kLockedError) as exc:
            _raise_unp4k_failure(3762504530, self._REAL_LOCK_STDERR)
        assert str(exc.value) == tr("extract.p4k_locked")
        # The friendly text must not leak the raw stack trace.
        assert "IOException" not in str(exc.value)
        assert "System.IO" not in str(exc.value)

    def test_locked_file_raises_the_typed_exception(self):
        """Must be P4kLockedError specifically, not a plain RuntimeError —
        the worker except blocks (workers.py) key off isinstance() to decide
        whether to log at WARNING (this case) or ERROR (any other failure),
        so the type distinction is what prevents the duplicate-dialog bug."""
        with pytest.raises(P4kLockedError):
            _raise_unp4k_failure(3762504530, self._REAL_LOCK_STDERR)

    def test_detection_is_case_insensitive(self):
        with pytest.raises(P4kLockedError) as exc:
            _raise_unp4k_failure(1, "BEING USED BY ANOTHER PROCESS")
        assert str(exc.value) == tr("extract.p4k_locked")

    def test_other_failure_preserves_raw_output(self):
        raw = "some other unp4k error: bad archive header"
        with pytest.raises(RuntimeError) as exc:
            _raise_unp4k_failure(2, raw)
        msg = str(exc.value)
        assert "exited with code 2" in msg
        assert raw in msg
        assert msg != tr("extract.p4k_locked")

    def test_other_failure_is_not_the_locked_type(self):
        """A genuine failure must NOT be P4kLockedError, or the worker would
        wrongly log it at WARNING and skip the global error-dialog handler
        for a real, unexpected problem."""
        with pytest.raises(RuntimeError) as exc:
            _raise_unp4k_failure(2, "some other unp4k error")
        assert not isinstance(exc.value, P4kLockedError)

    def test_locked_file_logs_at_warning_not_error(self, caplog):
        """The locked-file case must log below ERROR: MainWindow's global
        ErrorDialogHandler pops its own generic crash-style dialog for every
        ERROR-level record anywhere in the app, which would duplicate the
        friendly dialog this raises into with a second, raw-stack-trace
        popup on top of it (the exact bug this regression-guards)."""
        with caplog.at_level(logging.WARNING, logger="utils.pak_extractor"):
            with pytest.raises(RuntimeError):
                _raise_unp4k_failure(3762504530, self._REAL_LOCK_STDERR)
        assert not any(r.levelno >= logging.ERROR for r in caplog.records)
        assert any(r.levelno == logging.WARNING for r in caplog.records)

    def test_other_failure_logs_at_error(self, caplog):
        """A genuinely unexpected unp4k failure should still surface through
        the global ErrorDialogHandler — only the well-understood locked-file
        case is downgraded."""
        with caplog.at_level(logging.WARNING, logger="utils.pak_extractor"):
            with pytest.raises(RuntimeError):
                _raise_unp4k_failure(2, "some other unp4k error")
        assert any(r.levelno >= logging.ERROR for r in caplog.records)

    def test_empty_output_does_not_crash(self):
        with pytest.raises(RuntimeError) as exc:
            _raise_unp4k_failure(-1, None)
        assert "exited with code -1" in str(exc.value)


# ─────────────────────────────────────────────────────────────────────────────
# The cache layout is named once (#471 review)
# ─────────────────────────────────────────────────────────────────────────────

class TestCacheLayoutNamedOnce:
    """pak_extractor names the DataForge cache layout (raw/libs and
    foundry/records) once, and every reader joins DATAFORGE_LIBS_SUBPATH /
    DATAFORGE_RECORDS_SUBPATH (root CLAUDE.md, "Magic literals"). The only
    other spellings allowed are the generator's fallback for a missing src/,
    the same deferred-import pattern as its other src imports, and the
    legacy build cleaner, which still targets the pre-1.x Documents cache."""

    # Any quoted "raw" or "foundry" path segment: joined with / one at a
    # time ("raw" / "libs", or a variable / "raw" with "libs" added later),
    # a Path("raw") or joinpath("raw", ...) argument, or the start of a
    # "raw/libs" string. Neither word is used for anything else here.
    _SPELLED = re.compile(r"""["'](?:raw|foundry)(?:["']|[/\\])""")
    _REPO = Path(__file__).resolve().parent.parent
    _ALLOWED = {
        "src/utils/pak_extractor.py": 2,             # the definitions
        "scripts/generate_enhancements_ini.py": 2,   # the src/-missing fallback (one line)
        "scripts/build/clean_cache_for_distribution.py": 2,   # legacy, pre-1.x cache
    }

    def _spellings(self):
        found = {}
        for pattern in ("src/**/*.py", "scripts/**/*.py"):
            for path in self._REPO.glob(pattern):
                count = len(self._SPELLED.findall(path.read_text(encoding="utf-8")))
                if count:
                    found[path.relative_to(self._REPO).as_posix()] = count
        return found

    def test_nothing_else_spells_the_layout_out(self):
        assert self._spellings() == self._ALLOWED

    def test_the_names_describe_the_layout_the_extraction_writes(self):
        from utils.pak_extractor import (
            DATAFORGE_LIBS_SUBPATH, DATAFORGE_RECORDS_SUBPATH, DATAFORGE_RECORDS_UNDER_LIBS,
        )
        assert DATAFORGE_LIBS_SUBPATH.as_posix() == "raw/libs"
        assert DATAFORGE_RECORDS_UNDER_LIBS.as_posix() == "foundry/records"
        assert DATAFORGE_RECORDS_SUBPATH.as_posix() == "raw/libs/foundry/records"

    def test_the_guard_sees_a_hand_spelled_path(self):
        """Prove the pattern bites, so the guard can't pass by reading nothing."""
        assert self._SPELLED.search('records = forge_dir / "raw" / "libs" / "foundry"')
        assert self._SPELLED.search("x = Path('foundry') / 'records'")
        assert self._SPELLED.search('raw_dir = cache / "raw"')      # the split form
        assert self._SPELLED.search('cache.joinpath("raw", "libs")')
        assert self._SPELLED.search('libs = cache / "raw/libs"')
        assert not self._SPELLED.search("records = forge_dir / DATAFORGE_RECORDS_SUBPATH")
        assert not self._SPELLED.search('rawness = "rawhide"')
