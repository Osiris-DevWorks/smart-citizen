"""
Tests for P4K extraction and DataForge integration (v0.6.0 critical feature)

Tests cover:
- P4K extraction pipeline
- DataForge cache management
- Error handling for missing P4K or tools
"""

import pytest
import ast
import logging
import re
import subprocess
import tempfile
import os
from pathlib import Path
from types import SimpleNamespace

import src.utils.pak_extractor as pe
from src.utils.onedrive import _ONEDRIVE_ENV_VARS
from src.utils.pak_extractor import (
    DATAFORGE_KEEP_SUBPATHS,
    P4kLockedError,
    _copy_filtered_records,
    _raise_unp4k_failure,
    dataforge_cache_is_fresh,
)
# The extractor translates through src.utils.i18n, so the language is set there.
from src.utils.i18n import set_language, tr


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


class _UnpackFailed(Exception):
    """Stands in for whatever unp4k's _run_tool can raise: an OSError from
    Popen, its timeout, a stop."""


def _write_dcb(args, cwd: Path) -> subprocess.CompletedProcess:
    """What a working unp4k leaves in its working folder."""
    (cwd / "Data").mkdir()
    (cwd / "Data" / "Game2.dcb").write_bytes(b"dcb")
    return subprocess.CompletedProcess(args, 0, "", "")


class TestDataForgeExtraction:
    """extract_dataforge's early failures, with a fake _run_tool standing in
    for unp4k and unforge: a missing tool or Data.p4k, and an unp4k that
    fails by exit code or by exception. Each must end the run before unforge
    starts, keep the old cache and leave no working folder. Where the tools
    work, the copy and the stop points are in test_extraction_working_folder.py.

    The fake goes on src.utils.pak_extractor (``pe``), the module production
    imports and whose extract_dataforge these tests call. A fake set on a
    second copy of the module would never reach it, and tests/test_import_paths.py
    keeps the short import that loaded one out (#510)."""

    pytestmark = pytest.mark.unit

    @pytest.fixture
    def env(self, tmp_path, monkeypatch):
        """Dummy tools and Data.p4k, a cache leaf holding an old cache, and a
        fake _run_tool that records each tool it is asked to run. unp4k does
        what ``env.unp4k`` says (by default it writes Data/Game2.dcb) and
        unforge writes every keep subtree next to the dcb. Isolated as in
        test_extraction_working_folder.py: a private %TEMP%, no OneDrive in
        the environment and no real drive-type probe."""
        systemp = tmp_path / "systemp"
        systemp.mkdir()
        monkeypatch.setattr(tempfile, "tempdir", str(systemp))
        for var in _ONEDRIVE_ENV_VARS:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr(pe, "_drive_is_removable_or_network", lambda path: False)
        tools = tmp_path / "tools"
        tools.mkdir()
        for name in ("unp4k.exe", "unforge.exe", "Data.p4k"):
            (tools / name).write_bytes(b"x")
        leaf = tmp_path / "LIVE" / "cache" / "dataforge"
        leaf.mkdir(parents=True)
        (leaf / "old-cache-sentinel").write_text("old")
        env = SimpleNamespace(tools=tools, leaf=leaf, systemp=systemp, calls=[],
                              unp4k=_write_dcb)

        def fake_run_tool(args, *, cwd, timeout, should_cancel=None):
            tool = Path(args[0]).stem
            env.calls.append(tool)
            if tool == "unp4k":
                return env.unp4k(args, Path(cwd))
            records = Path(args[1]).parent / "libs" / pe.DATAFORGE_RECORDS_UNDER_LIBS
            for rel in pe.DATAFORGE_KEEP_SUBPATHS:
                (records / rel).mkdir(parents=True, exist_ok=True)
                (records / rel / "x.xml").write_text("<x/>", encoding="utf-8")
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(pe, "_run_tool", fake_run_tool)
        env.run = lambda: pe.extract_dataforge(
            tools / "Data.p4k", tools / "unp4k.exe", tools / "unforge.exe", leaf
        )
        return env

    @staticmethod
    def _assert_old_cache_kept_and_no_folder_left(env):
        assert (env.leaf / "old-cache-sentinel").exists()
        assert not (env.leaf / pe.P4K_SIZE_STAMP).exists()
        assert not (env.leaf / pe.P4K_MTIME_STAMP).exists()
        assert list(env.leaf.parent.glob(pe.DATAFORGE_SCRATCH_PREFIX + "*")) == []
        assert list(env.systemp.iterdir()) == []

    @pytest.mark.parametrize("missing", ["unp4k.exe", "unforge.exe", "Data.p4k"])
    def test_a_missing_tool_or_p4k_fails_before_any_tool_runs(self, env, missing):
        (env.tools / missing).unlink()
        with pytest.raises(FileNotFoundError, match=re.escape(missing) + " not found at"):
            env.run()
        assert env.calls == []
        self._assert_old_cache_kept_and_no_folder_left(env)

        # With the file back the same run goes through the fake tools, so the
        # fake reaches this extract_dataforge and only the missing file stopped it.
        (env.tools / missing).write_bytes(b"x")
        assert env.run() is True
        assert env.calls == ["unp4k", "unforge"]

    def test_a_failed_unp4k_stops_the_run_with_its_error_output(self, env):
        def failing_unp4k(args, cwd):
            _write_dcb(args, cwd)   # a partial dcb, which unforge must never get
            return subprocess.CompletedProcess(args, 1, "unp4k 3.0 banner", "Invalid P4K format")

        env.unp4k = failing_unp4k
        with pytest.raises(RuntimeError) as raised:
            env.run()
        assert not isinstance(raised.value, pe.P4kLockedError)
        assert "exited with code 1" in str(raised.value)
        assert "Invalid P4K format" in str(raised.value)
        assert env.calls == ["unp4k"]
        self._assert_old_cache_kept_and_no_folder_left(env)

    def test_a_locked_p4k_reaches_the_caller_as_the_locked_error(self, env):
        """The workers tell this case apart by its type (P4kLockedError), so it
        must come out of extract_dataforge as it is. The helper alone is
        tested in TestUnp4kFailureMessage."""
        def locked_unp4k(args, cwd):
            return subprocess.CompletedProcess(
                args, 3762504530, "unp4k 3.0 banner",
                "System.IO.IOException: The process cannot access the file 'Data.p4k' "
                "because it is being used by another process.",
            )

        env.unp4k = locked_unp4k
        with pytest.raises(pe.P4kLockedError):
            env.run()
        assert env.calls == ["unp4k"]
        self._assert_old_cache_kept_and_no_folder_left(env)

    def test_an_exception_from_unp4k_stops_the_run_unchanged(self, env):
        boom = _UnpackFailed("unp4k failed")

        def raising_unp4k(args, cwd):
            _write_dcb(args, cwd)   # a partial dcb, which unforge must never get
            raise boom

        env.unp4k = raising_unp4k
        with pytest.raises(_UnpackFailed) as raised:
            env.run()
        assert raised.value is boom
        assert env.calls == ["unp4k"]
        self._assert_old_cache_kept_and_no_folder_left(env)


class TestNoSubprocessRunPatches:
    """pak_extractor runs unp4k and unforge through _run_tool, which uses
    Popen (#471), so a patch of subprocess.run never reaches them. Four tests
    in this file patched it and passed without testing anything. This fails
    when a test file that mentions pak_extractor has a patch(), patch.object(),
    mocker.patch(), monkeypatch.setattr() or setattr() call whose target,
    given positionally or as the target=, attribute= or name= keyword, is
    spelled through the name subprocess: the string
    subprocess.run, utils.pak_extractor.subprocess.run or
    src.utils.pak_extractor.subprocess.run, or an object such as subprocess
    or pe.subprocess with the name "run". An aliased import is not seen
    (import subprocess as sp, then patch.object(sp, "run")). Patch
    ``pe._run_tool`` instead, as TestDataForgeExtraction does."""

    pytestmark = pytest.mark.unit

    _TESTS = Path(__file__).resolve().parent
    _TARGET = re.compile(r"(?:^|\.)subprocess\.run$")

    @classmethod
    def _subprocess_run_patches(cls, source: str) -> list:
        """Lines of patch(), patch.object(), monkeypatch.setattr() and
        setattr() calls (a decorator, a with block, mocker.patch too) whose
        target is subprocess.run: a dotted string ending in subprocess.run,
        or an object ending in subprocess with the name "run". Only the
        target is read, so a fake that calls subprocess.run is no match."""
        hits = []
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Call):
                continue
            func = ast.unparse(node.func).split(".")
            if not (func[-1] in ("patch", "setattr") or func[-2:] == ["patch", "object"]):
                continue
            # The target and the name may also come as keywords: patch(target=...),
            # patch.object(..., attribute=...), monkeypatch.setattr(target=..., name=...).
            keywords = {k.arg: k.value for k in node.keywords if k.arg}
            first = node.args[0] if node.args else keywords.get("target")
            second = (node.args[1] if len(node.args) >= 2
                      else keywords.get("attribute", keywords.get("name")))
            if first is None:
                continue
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                target = first.value
            elif second is not None:
                name = second.value if isinstance(second, ast.Constant) else ast.unparse(second)
                target = f"{ast.unparse(first)}.{name}"
            else:
                continue
            if cls._TARGET.search(target):
                hits.append(node.lineno)
        return hits

    def test_no_test_file_patches_subprocess_run_for_pak_extractor(self):
        scanned, offenders = [], {}
        for path in sorted(self._TESTS.glob("*.py")):
            source = path.read_text(encoding="utf-8-sig")
            if "pak_extractor" not in source:
                continue
            scanned.append(path.name)
            lines = self._subprocess_run_patches(source)
            if lines:
                offenders[path.name] = lines
        assert offenders == {}, (
            f"These lines patch subprocess.run, which pak_extractor never calls: "
            f"{offenders}. Patch pe._run_tool instead."
        )
        # It read the files it is there for, so it cannot pass by reading nothing.
        assert {"test_pak_extraction.py", "test_extraction_working_folder.py"} <= set(scanned)

    @pytest.mark.parametrize("snippet, line", [
        pytest.param("@patch('utils.pak_extractor.subprocess.run')\ndef f(m): pass\n", 1,
                     id="old-decorator"),
        pytest.param("@patch('src.utils.pak_extractor.subprocess.run')\ndef f(m): pass\n", 1,
                     id="src-decorator"),
        pytest.param("def f():\n    with mock.patch('subprocess.run'):\n        pass\n", 2,
                     id="with-block"),
        pytest.param("@patch.object(pe.subprocess, 'run')\ndef f(m): pass\n", 1,
                     id="patch-object"),
        pytest.param("def f(monkeypatch):\n"
                     "    monkeypatch.setattr(pe.subprocess, 'run', None)\n", 2,
                     id="monkeypatch-object"),
        pytest.param("def f(monkeypatch):\n"
                     "    monkeypatch.setattr('utils.pak_extractor.subprocess.run', None)\n", 2,
                     id="monkeypatch-string"),
        pytest.param("def f(mocker):\n"
                     "    mocker.patch('src.utils.pak_extractor.subprocess.run')\n", 2,
                     id="mocker"),
        pytest.param("setattr(subprocess, 'run', None)\n", 1, id="builtin-setattr"),
        pytest.param("@patch(target='utils.pak_extractor.subprocess.run')\ndef f(m): pass\n", 1,
                     id="patch-target-keyword"),
        pytest.param("@patch.object(pe.subprocess, attribute='run')\ndef f(m): pass\n", 1,
                     id="patch-object-attribute-keyword"),
        pytest.param("def f(monkeypatch):\n"
                     "    monkeypatch.setattr(target=pe.subprocess, name='run', value=None)\n", 2,
                     id="monkeypatch-keywords"),
    ])
    def test_the_guard_sees_each_spelling(self, snippet, line):
        assert self._subprocess_run_patches(snippet) == [line]

    @pytest.mark.parametrize("snippet", [
        pytest.param("def f(monkeypatch):\n    monkeypatch.setattr(pe, '_run_tool', None)\n",
                     id="the-run-tool-seam"),
        pytest.param("def f(monkeypatch):\n"
                     "    monkeypatch.setattr(pe.subprocess, 'Popen', None)\n",
                     id="popen"),
        pytest.param("def f(monkeypatch):\n"
                     "    monkeypatch.setattr(pe, '_run_tool',\n"
                     "                        lambda *a, **k: subprocess.run(*a))\n",
                     id="a-fake-that-calls-run"),
        pytest.param("x = \"@patch('utils.pak_extractor.subprocess.run')\"\n",
                     id="a-string-not-a-call"),
    ])
    def test_the_guard_ignores_what_is_not_a_subprocess_run_patch(self, snippet):
        assert self._subprocess_run_patches(snippet) == []


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

    def test_setup_reaches_the_language_the_extractor_reads(self):
        """setup_method must switch the language the extractor reads, on
        src.utils.i18n. Set on a second copy of the module, it once left these
        tests on whatever language an earlier test had set."""
        import src.utils.i18n as extractor_i18n
        try:
            extractor_i18n.set_language("german")
            german = extractor_i18n.tr("extract.p4k_locked")
            self.setup_method()
            english = tr("extract.p4k_locked")
            assert german != english     # control: the two languages differ here
            with pytest.raises(P4kLockedError) as exc:
                _raise_unp4k_failure(3762504530, self._REAL_LOCK_STDERR)
            assert str(exc.value) == english
        finally:
            extractor_i18n.set_language("english")

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
        with caplog.at_level(logging.WARNING, logger="src.utils.pak_extractor"):
            with pytest.raises(RuntimeError):
                _raise_unp4k_failure(3762504530, self._REAL_LOCK_STDERR)
        assert not any(r.levelno >= logging.ERROR for r in caplog.records)
        assert any(r.levelno == logging.WARNING for r in caplog.records)

    def test_other_failure_logs_at_error(self, caplog):
        """A genuinely unexpected unp4k failure should still surface through
        the global ErrorDialogHandler — only the well-understood locked-file
        case is downgraded."""
        with caplog.at_level(logging.WARNING, logger="src.utils.pak_extractor"):
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
        from src.utils.pak_extractor import (
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
