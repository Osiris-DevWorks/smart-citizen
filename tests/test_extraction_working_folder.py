"""#471: where the P4K tools work, and stopping them.

``extract_dataforge`` used to run unp4k and unforge inside
``tempfile.TemporaryDirectory()``, so all ~2 GB of their output landed in
%TEMP% on the system drive whatever DataForge cache folder the user had
picked, and nothing could stop a running tool: closing the window left
unforge.exe writing on its own into a folder Python's exit-time cleanup was
already failing to delete. These tests pin the replacement:

* ``_run_tool``: a stoppable ``subprocess.run`` (real child processes).
* ``_scratch_location``: beside the cache, or %TEMP% for a network share,
  OneDrive, a removable drive or a path too deep for a working folder.
* ``_sweep_stale_scratch``: leftovers of a crash go, a live run in another
  window (its ``.in_use`` marker held open) never does.
* ``extract_dataforge`` / ``extract_global_ini``: placement, cleanup on every
  outcome, and the stop points (with fake tools for the branches, and Python
  scripts standing in for unp4k and unforge for the real process handling).

Qt-free. Child processes run on the base interpreter (``sys._base_executable``)
because a venv's ``python.exe`` is a launcher that starts a second process,
and killing the launcher would leave that one running, which is the very thing
under test. Every child exits on its own within 30 s even if a kill fails.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

import src.utils.pak_extractor as pe
from src.utils.dataforge_diff import MANIFEST_FILE
from src.utils.win_paths import win_long_path

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(sys.platform != "win32", reason="Windows process and path behaviour"),
]

PY = getattr(sys, "_base_executable", None) or sys.executable
# Captured before the autouse fixture swaps it out for every test.
_REAL_DRIVE_PROBE = pe._drive_is_removable_or_network


# ── helpers ─────────────────────────────────────────────────────────────────

def _pid_alive(pid: int) -> bool:
    """True while the process with *pid* is still running."""
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    handle = k32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == 259   # STILL_ACTIVE
    finally:
        k32.CloseHandle(handle)


def _wait_for(predicate, seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def _script(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def _write_pid_code(pid_file: Path, indent: str = "") -> str:
    """Child-script lines that publish the child's pid atomically (write a
    temp file, then rename it), so a test that waits for the file can never
    read it half-written. Tests key off this file rather than a fixed delay,
    so a slow CI runner's start-up time can't make them flaky."""
    tmp = str(pid_file) + ".tmp"
    return (f"{indent}with open({tmp!r}, 'w') as _f: _f.write(str(os.getpid()))\n"
            f"{indent}os.replace({tmp!r}, {str(pid_file)!r})\n")


def _scratch_folders(parent: Path, prefix: str) -> list[Path]:
    return sorted(p for p in Path(parent).glob(prefix + "*") if p.is_dir())


def _pad_to(base: Path, length: int) -> Path:
    """A folder under *base* whose path is exactly *length* characters."""
    path = base
    need = length - len(str(base))
    assert need >= 2, f"{base} is already too long to pad to {length}"
    while need > 0:
        size = min(40, need - 1)
        if need - (size + 1) == 1:   # never leave a one-character gap
            size -= 1
        path = path / ("p" * size)
        need -= size + 1
    assert len(str(path)) == length
    return path


@pytest.fixture(autouse=True)
def _isolated(tmp_path_factory, monkeypatch):
    """A short private root, a private %TEMP%, no OneDrive in the environment
    and no real drive-type probe, so nothing here depends on the machine."""
    root = tmp_path_factory.mktemp("wf")
    systemp = root / "systemp"
    systemp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(systemp))
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(pe, "_drive_is_removable_or_network", lambda path: False)
    return root


@pytest.fixture
def root(_isolated):
    return _isolated


@pytest.fixture
def systemp():
    return Path(tempfile.gettempdir())


# ── _run_tool ───────────────────────────────────────────────────────────────

class TestRunTool:
    def test_a_chatty_tool_never_stalls_and_loses_nothing(self, root):
        """2 MB on each pipe, far past a pipe buffer: the poll loop keeps both
        drained, and repeated communicate() calls lose no output."""
        child = _script(root / "chatty.py", (
            "import sys, time\n"
            "for i in range(4):\n"
            "    sys.stdout.write('o' * 512 * 1024); sys.stdout.flush()\n"
            "    sys.stderr.write('e' * 512 * 1024); sys.stderr.flush()\n"
            "    time.sleep(0.3)\n"
        ))
        result = pe._run_tool([PY, str(child)], cwd=str(root), timeout=60)
        assert result.returncode == 0
        assert len(result.stdout) == 2 * 1024 * 1024
        assert len(result.stderr) == 2 * 1024 * 1024

    def test_a_failing_tool_returns_its_exit_code_and_output(self, root):
        child = _script(root / "fail.py", "import sys\nprint('boom')\nsys.exit(3)\n")
        result = pe._run_tool([PY, str(child)], cwd=str(root), timeout=60)
        assert result.returncode == 3
        assert result.stdout.strip() == "boom"

    def test_a_timeout_kills_the_tool_and_raises_what_run_raised(self, root, monkeypatch):
        """_unforge_timeout_error reads the TimeoutExpired run() used to raise
        (#370), so the shape stays, and the tool is dead afterwards."""
        pid_file = root / "pid"
        child = _script(root / "slow.py", (
            "import os, sys, time\n"
            + _write_pid_code(pid_file)
            + "print('partial'); sys.stdout.flush()\n"
            "time.sleep(30)\n"
        ))
        # Long enough for even a slow runner to start the child and let it
        # print, short enough to keep the test quick.
        with pytest.raises(subprocess.TimeoutExpired) as raised:
            pe._run_tool([PY, str(child)], cwd=str(root), timeout=5)
        assert raised.value.timeout == 5
        assert "partial" in (raised.value.output or "")
        pid = int(pid_file.read_text())
        assert _wait_for(lambda: not _pid_alive(pid), 5)

    def test_a_stop_kills_the_running_tool(self, root):
        pid_file = root / "pid"
        child = _script(root / "slow.py", (
            "import os, time\n"
            + _write_pid_code(pid_file)
            + "time.sleep(30)\n"
        ))
        started = time.monotonic()
        with pytest.raises(pe.ExtractionCancelled):
            # Stop once the child is really running, whatever its start-up took.
            pe._run_tool([PY, str(child)], cwd=str(root), timeout=60,
                         should_cancel=pid_file.exists)
        assert time.monotonic() - started < 10
        pid = int(pid_file.read_text())
        assert _wait_for(lambda: not _pid_alive(pid), 5)

    def test_a_stop_before_the_start_runs_nothing(self, root):
        marker = root / "ran"
        child = _script(root / "touch.py", f"open({str(marker)!r}, 'w').close()\n")
        with pytest.raises(pe.ExtractionCancelled):
            pe._run_tool([PY, str(child)], cwd=str(root), timeout=60, should_cancel=lambda: True)
        time.sleep(0.5)
        assert not marker.exists()

    def test_a_pending_stop_wins_over_a_clean_exit(self, root):
        """A tool that finishes while a stop is pending must not hand its exit
        code on: the stop is what the caller acts on."""
        child = _script(root / "quick.py", "print('done')\n")
        answers = iter([False])   # not stopped at the start, stopped after

        with pytest.raises(pe.ExtractionCancelled):
            pe._run_tool([PY, str(child)], cwd=str(root), timeout=60,
                         should_cancel=lambda: next(answers, True))

    def test_the_tool_gets_the_working_folder_pipes_and_no_window(self, root, monkeypatch):
        seen = {}
        real_popen = subprocess.Popen

        def recording_popen(args, **kwargs):
            seen.update(kwargs)
            return real_popen(args, **kwargs)

        monkeypatch.setattr(pe.subprocess, "Popen", recording_popen)
        child = _script(root / "cwd.py", "import os\nprint(os.getcwd())\n")
        work = root / "work"
        work.mkdir()
        result = pe._run_tool([PY, str(child)], cwd=str(work), timeout=60)
        assert Path(result.stdout.strip()) == work
        assert seen["cwd"] == str(work)
        assert seen["text"] is True
        assert seen["stdout"] is subprocess.PIPE and seen["stderr"] is subprocess.PIPE
        assert seen["creationflags"] & subprocess.CREATE_NO_WINDOW
        assert "capture_output" not in seen


# ── _scratch_location ───────────────────────────────────────────────────────

class TestScratchLocation:
    def test_an_ordinary_cache_works_beside_its_leaf(self, root):
        leaf = root / "SC" / "LIVE" / "cache" / "dataforge"
        assert pe._scratch_location(leaf) == (leaf.parent, pe.DATAFORGE_SCRATCH_PREFIX)

    def test_the_cap_stays_inside_what_unforge_was_measured_to_handle(self):
        """unforge wrote all 61,950 records with its dcb in a 197-character
        folder (#471). The dcb folder is the run folder plus '\\Data', so the
        cap has to keep run folder + 5 at or under 197; 190 leaves margin."""
        assert pe._MAX_SCRATCH_CHARS == 190
        assert pe._MAX_SCRATCH_CHARS + len("\\Data") <= 197

    def test_the_depth_cap_is_exactly_190_characters(self, root, systemp):
        """Run folder = parent + '\\' + prefix + 8 random characters: a run
        folder of 190 characters stays beside the cache, 191 goes to %TEMP%."""
        extra = 1 + len(pe.DATAFORGE_SCRATCH_PREFIX) + pe._MKDTEMP_RANDOM_CHARS
        at_cap = _pad_to(root, 190 - extra)
        over_cap = _pad_to(root, 190 - extra + 1)
        assert pe._scratch_location(at_cap / "dataforge")[0] == at_cap
        assert pe._scratch_location(over_cap / "dataforge") == (systemp, pe._TEMP_SCRATCH_PREFIX)

    def test_a_network_share_uses_temp(self, systemp):
        leaf = Path(r"\\server\share\SC\LIVE\cache\dataforge")
        assert pe._scratch_location(leaf) == (systemp, pe._TEMP_SCRATCH_PREFIX)

    def test_onedrive_uses_temp(self, root, systemp, monkeypatch):
        onedrive = root / "OneDrive"
        monkeypatch.setenv("OneDrive", str(onedrive))
        leaf = onedrive / "Smart Citizen" / "LIVE" / "cache" / "dataforge"
        assert pe._scratch_location(leaf) == (systemp, pe._TEMP_SCRATCH_PREFIX)

    def test_a_removable_or_network_drive_uses_temp(self, root, systemp, monkeypatch):
        monkeypatch.setattr(pe, "_drive_is_removable_or_network", lambda path: True)
        leaf = root / "SC" / "LIVE" / "cache" / "dataforge"
        assert pe._scratch_location(leaf) == (systemp, pe._TEMP_SCRATCH_PREFIX)

    def test_long_path_prefixes_come_off_for_the_tools(self):
        assert pe._plain_path("\\\\?\\E:\\SC\\LIVE") == "E:\\SC\\LIVE"
        assert pe._plain_path("\\\\?\\UNC\\server\\share\\SC") == "\\\\server\\share\\SC"
        assert pe._plain_path("E:\\SC") == "E:\\SC"

    def test_the_drive_probe_is_best_effort(self, root):
        """It never raises, whatever the path: a failure keeps the folder
        beside the cache, where it would have been anyway. A UNC path is not
        its business (the caller already sent those to %TEMP%)."""
        assert _REAL_DRIVE_PROBE("\\\\server\\share\\x") is False
        assert _REAL_DRIVE_PROBE(str(root)) is False   # the fixed drive the tests run on
        assert _REAL_DRIVE_PROBE(r"Q:\nowhere") in (True, False)


# ── _sweep_stale_scratch ────────────────────────────────────────────────────

class TestScratchSweep:
    @staticmethod
    def _leftover(parent: Path, name: str, *, marker: bool = True) -> Path:
        folder = parent / name
        (folder / "Data" / "libs").mkdir(parents=True)
        (folder / "Data" / "Game2.dcb").write_bytes(b"x" * 1024)
        if marker:
            (folder / pe._SCRATCH_MARKER).write_text("")
        return folder

    def test_a_dead_run_is_removed(self, root):
        dead = self._leftover(root, pe.DATAFORGE_SCRATCH_PREFIX + "dead0001")
        pe._sweep_stale_scratch(root, pe.DATAFORGE_SCRATCH_PREFIX)
        assert not dead.exists()

    def test_a_live_run_in_another_window_is_left_alone(self, root):
        live = self._leftover(root, pe.DATAFORGE_SCRATCH_PREFIX + "live0001", marker=False)
        with open(live / pe._SCRATCH_MARKER, "w", encoding="utf-8"):
            pe._sweep_stale_scratch(root, pe.DATAFORGE_SCRATCH_PREFIX)
            assert (live / "Data" / "Game2.dcb").exists()

    def test_an_unmarked_folder_gets_a_grace_period(self, root):
        fresh = self._leftover(root, pe.DATAFORGE_SCRATCH_PREFIX + "fresh001", marker=False)
        old = self._leftover(root, pe.DATAFORGE_SCRATCH_PREFIX + "old00001", marker=False)
        stale = time.time() - pe._UNMARKED_SCRATCH_GRACE_SECONDS - 60
        os.utime(old, (stale, stale))
        pe._sweep_stale_scratch(root, pe.DATAFORGE_SCRATCH_PREFIX)
        assert fresh.exists()
        assert not old.exists()

    def test_only_its_own_names_are_touched(self, root):
        """The cache leaf, the settings migrator's staging folder and anything
        else beside them never match."""
        names = ("dataforge", "dataforge.migrating", "tmpabc123", "other")
        others = [root / name for name in names]
        for folder in others:
            (folder / "x").mkdir(parents=True)
            (folder / pe._SCRATCH_MARKER).write_text("")
        pe._sweep_stale_scratch(root, pe.DATAFORGE_SCRATCH_PREFIX)
        pe._sweep_stale_scratch(root, pe._TEMP_SCRATCH_PREFIX)
        pe._sweep_stale_scratch(root, pe.GLOBAL_INI_SCRATCH_PREFIX)
        pe._sweep_stale_scratch(root, pe._GLOBAL_INI_TEMP_PREFIX)
        assert all(folder.exists() for folder in others)

    def test_a_missing_parent_is_fine(self, root):
        pe._sweep_stale_scratch(root / "not-there", pe.DATAFORGE_SCRATCH_PREFIX)

    def test_a_folder_that_will_not_go_is_logged_not_raised(self, root, monkeypatch, caplog):
        self._leftover(root, pe.DATAFORGE_SCRATCH_PREFIX + "stuck001")

        def refuse(path, attempts=6):
            raise PermissionError("held by antivirus")

        monkeypatch.setattr(pe, "robust_rmtree", refuse)
        with caplog.at_level(logging.WARNING, logger=pe.logger.name):
            pe._sweep_stale_scratch(root, pe.DATAFORGE_SCRATCH_PREFIX)
        assert "Could not remove leftover extraction working folder" in caplog.text


# ── extract_dataforge with fake tools (fast branch coverage) ────────────────

class _FakeTools:
    """Stands in for _run_tool: unp4k writes Data/Game2.dcb into its working
    folder, unforge writes libs/foundry/records next to the dcb (every keep
    subtree plus one the cache must not copy)."""

    def __init__(self, *, unforge_rc: int = 0, deep_name: str | None = None, during_unforge=None):
        self.calls: list[tuple[str, list, str]] = []
        self.unforge_rc = unforge_rc
        self.deep_name = deep_name
        self.during_unforge = during_unforge

    def __call__(self, args, *, cwd, timeout, should_cancel=None):
        tool = Path(args[0]).stem
        self.calls.append((tool, list(args), cwd))
        if tool == "unp4k":
            (Path(cwd) / "Data").mkdir()
            (Path(cwd) / "Data" / "Game2.dcb").write_bytes(b"dcb")
        else:
            records = Path(args[1]).parent / "libs" / "foundry" / "records"
            for rel in pe.DATAFORGE_KEEP_SUBPATHS + ("unused/elsewhere",):
                folder = Path(win_long_path(records / rel))
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "x.xml").write_text("<x/>", encoding="utf-8")
            if self.deep_name:
                deep = Path(win_long_path(records / "entities" / "scitem" / self.deep_name))
                deep.mkdir(parents=True, exist_ok=True)
                (deep / (self.deep_name + ".xml")).write_text("<deep/>", encoding="utf-8")
            if self.during_unforge:
                self.during_unforge(Path(cwd))
        rc = self.unforge_rc if tool == "unforge" else 0
        return subprocess.CompletedProcess(args, rc, "", "")


@pytest.fixture
def setup(root, monkeypatch):
    """A fake Data.p4k and tools, a cache leaf with an old cache in it."""
    tools = root / "tools"
    tools.mkdir()
    for name in ("unp4k.exe", "unforge.exe", "Data.p4k"):
        (tools / name).write_bytes(b"x")
    leaf = root / "SC" / "LIVE" / "cache" / "dataforge"
    (leaf / "raw" / "libs").mkdir(parents=True)
    (leaf / "old-cache-sentinel").write_text("old")

    def run(fake, **kwargs):
        monkeypatch.setattr(pe, "_run_tool", fake)
        return pe.extract_dataforge(
            tools / "Data.p4k", tools / "unp4k.exe", tools / "unforge.exe", leaf, **kwargs
        )

    return leaf, run


class TestExtractDataforgeWorkingFolder:
    def test_the_tools_work_beside_the_cache_and_the_folder_goes(self, setup):
        leaf, run = setup
        held = []

        def check_marker(run_dir: Path):
            # The marker is held open while the run is alive, so another
            # window's sweep cannot delete it.
            try:
                os.unlink(run_dir / pe._SCRATCH_MARKER)
            except PermissionError:
                held.append(True)

        fake = _FakeTools(during_unforge=check_marker)
        assert run(fake) is True

        cwds = {cwd for _tool, _args, cwd in fake.calls}
        assert len(cwds) == 1
        run_dir = Path(cwds.pop())
        assert run_dir.parent == leaf.parent
        assert run_dir.name.startswith(pe.DATAFORGE_SCRATCH_PREFIX)
        assert held == [True]
        assert not run_dir.exists()
        assert _scratch_folders(leaf.parent, pe.DATAFORGE_SCRATCH_PREFIX) == []
        records = leaf / "raw" / "libs" / "foundry" / "records"
        assert (records / "entities" / "scitem" / "x.xml").exists()
        assert not (records / "unused").exists()
        assert (leaf / pe.P4K_MTIME_STAMP).exists() and (leaf / pe.P4K_SIZE_STAMP).exists()
        assert (leaf / "raw" / "libs" / MANIFEST_FILE).exists()
        assert not (leaf / "old-cache-sentinel").exists()

    def test_unforge_is_handed_the_dcb_inside_the_working_folder(self, setup):
        leaf, run = setup
        fake = _FakeTools()
        run(fake)
        (unp4k, unp4k_args, _), (unforge, unforge_args, unforge_cwd) = fake.calls
        assert (unp4k, unforge) == ("unp4k", "unforge")
        assert unp4k_args[1:] == [str(setup[0].parents[3] / "tools" / "Data.p4k"), ".dcb"]
        assert Path(unforge_args[1]) == Path(unforge_cwd) / "Data" / "Game2.dcb"
        # Plain paths only: whether the tools accept \\?\ was never tested.
        assert not unforge_args[1].startswith("\\\\?\\") and not unforge_cwd.startswith("\\\\?\\")

    def test_a_onedrive_cache_keeps_the_work_in_temp(self, setup, monkeypatch, systemp):
        leaf, run = setup
        monkeypatch.setattr(pe, "is_onedrive_path", lambda path: True)
        fake = _FakeTools()
        run(fake)
        run_dir = Path(fake.calls[0][2])
        assert run_dir.parent == systemp
        assert run_dir.name.startswith(pe._TEMP_SCRATCH_PREFIX)
        assert not run_dir.exists()
        assert (leaf / pe.P4K_SIZE_STAMP).exists()

    def test_a_failed_run_keeps_the_old_cache_and_cleans_up(self, setup):
        leaf, run = setup
        fake = _FakeTools(unforge_rc=1)
        with pytest.raises(RuntimeError, match="unforge.exe failed"):
            run(fake)
        assert (leaf / "old-cache-sentinel").exists()
        assert not Path(fake.calls[0][2]).exists()

    def test_a_stop_before_the_wipe_keeps_the_old_cache(self, setup):
        leaf, run = setup
        stopped = []
        fake = _FakeTools(during_unforge=lambda run_dir: stopped.append(True))
        with pytest.raises(pe.ExtractionCancelled):
            run(fake, should_cancel=lambda: bool(stopped))
        assert (leaf / "old-cache-sentinel").exists()
        assert not (leaf / pe.P4K_SIZE_STAMP).exists()
        assert not Path(fake.calls[0][2]).exists()

    def test_a_stop_during_the_copy_finishes_the_cache_and_skips_the_manifest(
        self, setup, monkeypatch
    ):
        """Past the wipe a stop never leaves the cache half-copied: it is
        written and stamped, and only the manifest is skipped."""
        leaf, run = setup
        stopped = []
        real_copy = pe._copy_filtered_records

        def copy_then_stop(src, dst):
            result = real_copy(src, dst)
            stopped.append(True)
            return result

        monkeypatch.setattr(pe, "_copy_filtered_records", copy_then_stop)
        fake = _FakeTools()
        with pytest.raises(pe.ExtractionCancelled):
            run(fake, should_cancel=lambda: bool(stopped))
        assert (leaf / pe.P4K_SIZE_STAMP).exists()
        records = leaf / "raw" / "libs" / "foundry" / "records"
        assert (records / "entities" / "scitem" / "x.xml").exists()
        assert not (leaf / "raw" / "libs" / MANIFEST_FILE).exists()
        assert not Path(fake.calls[0][2]).exists()

    def test_no_working_folder_means_no_tool_runs_and_the_cache_stays(self, setup, monkeypatch):
        leaf, run = setup

        def refuse(**kwargs):
            raise PermissionError("access denied")

        monkeypatch.setattr(pe.tempfile, "mkdtemp", refuse)
        fake = _FakeTools()
        with pytest.raises(PermissionError):
            run(fake)
        assert fake.calls == []
        assert (leaf / "old-cache-sentinel").exists()

    def test_a_cleanup_failure_never_replaces_the_outcome(self, setup, monkeypatch, caplog):
        leaf, run = setup
        real_rmtree = pe.robust_rmtree

        def rmtree(path, attempts=6):
            if Path(path).name.startswith(pe.DATAFORGE_SCRATCH_PREFIX):
                raise PermissionError("held by antivirus")
            return real_rmtree(path, attempts)

        monkeypatch.setattr(pe, "robust_rmtree", rmtree)
        with caplog.at_level(logging.WARNING, logger=pe.logger.name):
            assert run(_FakeTools()) is True
        assert "the next extraction removes it" in caplog.text
        assert (leaf / pe.P4K_SIZE_STAMP).exists()

    def test_a_leftover_is_swept_and_a_live_run_is_not(self, setup):
        leaf, run = setup
        dead = leaf.parent / (pe.DATAFORGE_SCRATCH_PREFIX + "crashed1")
        (dead / "Data").mkdir(parents=True)
        (dead / pe._SCRATCH_MARKER).write_text("")
        live = leaf.parent / (pe.DATAFORGE_SCRATCH_PREFIX + "otherwin")
        live.mkdir()
        with open(live / pe._SCRATCH_MARKER, "w", encoding="utf-8"):
            run(_FakeTools())
            assert live.exists()
        assert not dead.exists()

    def test_a_deep_cache_still_copies_every_keep_path(self, root, monkeypatch):
        """At the depth cap the deepest keep file passes 260 characters in the
        working folder. The copy reads through the long-path prefix, so it is
        not skipped without a word."""
        extra = 1 + len(pe.DATAFORGE_SCRATCH_PREFIX) + pe._MKDTEMP_RANDOM_CHARS
        beside = _pad_to(root / "deep", pe._MAX_SCRATCH_CHARS - extra)
        leaf = beside / "dataforge"
        tools = root / "tools"
        tools.mkdir()
        for name in ("unp4k.exe", "unforge.exe", "Data.p4k"):
            (tools / name).write_bytes(b"x")
        fake = _FakeTools(deep_name="d" * 60)
        monkeypatch.setattr(pe, "_run_tool", fake)

        pe.extract_dataforge(tools / "Data.p4k", tools / "unp4k.exe", tools / "unforge.exe", leaf)

        run_dir = Path(fake.calls[0][2])
        assert run_dir.parent == beside and len(str(run_dir)) == pe._MAX_SCRATCH_CHARS
        deep_rel = Path("entities") / "scitem" / ("d" * 60) / ("d" * 60 + ".xml")
        scratch_deep = run_dir / "Data" / "libs" / "foundry" / "records" / deep_rel
        assert len(str(scratch_deep)) > 260
        records = leaf / "raw" / "libs" / "foundry" / "records"
        assert Path(win_long_path(records / deep_rel)).exists()
        # Every keep subtree, including the deepest one (~261 characters in
        # the working folder at this depth), reached the cache.
        missing = [rel for rel in pe.DATAFORGE_KEEP_SUBPATHS
                   if not Path(win_long_path(records / rel / "x.xml")).exists()]
        assert missing == []

    def test_the_copy_reads_unforge_output_through_the_long_path_prefix(self, setup, monkeypatch):
        """A plain exists() on a keep path past 260 characters returns False
        on a PC without Windows long paths turned on (the default), and the
        copy would skip that subtree without a word. Checked directly, since a
        developer machine with long paths enabled can't show the failure."""
        leaf, run = setup
        sources = []
        real_copy = pe._copy_filtered_records

        def spy(src, dst):
            sources.append(str(src))
            return real_copy(src, dst)

        monkeypatch.setattr(pe, "_copy_filtered_records", spy)
        run(_FakeTools())
        assert len(sources) == 1 and sources[0].startswith("\\\\?\\")


# ── the real process handling, with Python scripts as the tools ─────────────

_UNP4K_SCRIPT = """\
import os, sys
mode = sys.argv[1]
if mode == ".dcb":
    os.makedirs("Data", exist_ok=True)
    with open(os.path.join("Data", "Game2.dcb"), "w", encoding="utf-8") as f:
        f.write({dcb!r})
else:
    folder = os.path.join("data", "Localization", "english")
    os.makedirs(folder, exist_ok=True)
    {global_ini_extra}
    with open(os.path.join(folder, "global.ini"), "w", encoding="utf-8") as f:
        f.write("key=value\\n")
"""

_UNFORGE_SCRIPT = """\
import os, time
here = os.path.dirname(os.path.abspath(__file__))
{before}
records = os.path.join(here, "libs", "foundry", "records")
for rel in {keep!r}:
    folder = "\\\\\\\\?\\\\" + os.path.join(records, *rel.split("/"))
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "x.xml"), "w", encoding="utf-8") as f:
        f.write("<x/>")
print("unforge done")
"""


def _real_tools(root: Path, *, slow_unforge: bool = False, slow_global_ini: bool = False):
    """A Data.p4k that is really an unp4k-like script, whose Game2.dcb is
    really an unforge-like script, both run by the base interpreter."""
    pid_file = root / "tool.pid"
    before = (_write_pid_code(pid_file) + "time.sleep(30)\n") if slow_unforge else ""
    dcb = _UNFORGE_SCRIPT.format(before=before, keep=list(pe.DATAFORGE_KEEP_SUBPATHS))
    extra = ("import time\n" + _write_pid_code(pid_file, "    ") + "    time.sleep(30)"
             if slow_global_ini else "pass")
    p4k = _script(root / "Data.p4k", _UNP4K_SCRIPT.format(dcb=dcb, global_ini_extra=extra))
    return p4k, Path(PY), pid_file


class TestExtractDataforgeRealTools:
    pytestmark = pytest.mark.integration

    def test_a_full_run_builds_the_cache_and_leaves_no_folder(self, root):
        p4k, py, _pid = _real_tools(root)
        leaf = root / "cache" / "LIVE" / "cache" / "dataforge"
        assert pe.extract_dataforge(p4k, py, py, leaf) is True
        records = leaf / "raw" / "libs" / "foundry" / "records"
        assert (records / "entities" / "scitem" / "x.xml").exists()
        assert (leaf / "raw" / "libs" / MANIFEST_FILE).exists()
        assert _scratch_folders(leaf.parent, pe.DATAFORGE_SCRATCH_PREFIX) == []

    def test_a_stop_mid_unforge_kills_it_and_cleans_up(self, root):
        p4k, py, pid_file = _real_tools(root, slow_unforge=True)
        leaf = root / "cache" / "LIVE" / "cache" / "dataforge"
        leaf.mkdir(parents=True)
        (leaf / "old-cache-sentinel").write_text("old")
        with pytest.raises(pe.ExtractionCancelled):
            pe.extract_dataforge(p4k, py, py, leaf, should_cancel=pid_file.exists)
        pid = int(pid_file.read_text())
        assert _wait_for(lambda: not _pid_alive(pid), 5)
        assert (leaf / "old-cache-sentinel").exists()
        assert _scratch_folders(leaf.parent, pe.DATAFORGE_SCRATCH_PREFIX) == []

    def test_a_timeout_kills_unforge_and_cleans_up(self, root, monkeypatch):
        monkeypatch.setattr(pe, "_UNFORGE_TIMEOUT_SECONDS", 5)
        p4k, py, pid_file = _real_tools(root, slow_unforge=True)
        leaf = root / "cache" / "LIVE" / "cache" / "dataforge"
        with pytest.raises(pe.DataForgeTimeoutError):
            pe.extract_dataforge(p4k, py, py, leaf)
        pid = int(pid_file.read_text())
        assert _wait_for(lambda: not _pid_alive(pid), 5)
        assert _scratch_folders(leaf.parent, pe.DATAFORGE_SCRATCH_PREFIX) == []


class _FakeGlobalIniTool:
    """Stands in for _run_tool on the global.ini extraction: writes every
    language's global.ini under data/Localization in its working folder."""

    def __init__(self):
        self.cwds = []

    def __call__(self, args, *, cwd, timeout, should_cancel=None):
        self.cwds.append(cwd)
        for lang in ("english", "german"):
            folder = Path(cwd) / "data" / "Localization" / lang
            folder.mkdir(parents=True)
            (folder / "global.ini").write_text(f"lang={lang}\n", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, "", "")


class TestGlobalIniWorkingFolder:
    """The global.ini extraction works beside the DataForge cache too (#471),
    by the same rules, so nothing it extracts lands in %TEMP% unless a
    fallback applies."""

    @pytest.fixture
    def env(self, root, monkeypatch):
        tools = root / "tools"
        tools.mkdir()
        for name in ("unp4k.exe", "Data.p4k"):
            (tools / name).write_bytes(b"x")
        leaf = root / "SC" / "LIVE" / "cache" / "dataforge"
        out = root / "data" / "LIVE" / "cache" / "base.ini"
        fake = _FakeGlobalIniTool()
        monkeypatch.setattr(pe, "_run_tool", fake)

        def run(near=leaf):
            return pe.extract_global_ini(tools / "Data.p4k", out, tools / "unp4k.exe",
                                         scratch_near=near)

        return leaf, out, fake, run

    def test_it_works_beside_the_dataforge_cache_and_cleans_up(self, env, systemp):
        leaf, out, fake, run = env
        assert run() is True
        run_dir = Path(fake.cwds[0])
        assert run_dir.parent == leaf.parent
        assert run_dir.name.startswith(pe.GLOBAL_INI_SCRATCH_PREFIX)
        assert not run_dir.exists()
        assert out.read_text(encoding="utf-8") == "lang=english\n"
        assert list(systemp.iterdir()) == []

    def test_onedrive_keeps_it_in_temp(self, env, systemp, monkeypatch):
        _leaf, out, fake, run = env
        monkeypatch.setattr(pe, "is_onedrive_path", lambda path: True)
        run()
        run_dir = Path(fake.cwds[0])
        assert run_dir.parent == systemp
        assert run_dir.name.startswith(pe._GLOBAL_INI_TEMP_PREFIX)
        assert not run_dir.exists()

    def test_without_a_cache_folder_it_works_in_temp(self, env, systemp):
        _leaf, out, fake, run = env
        run(near=None)
        assert Path(fake.cwds[0]).parent == systemp

    def test_a_leftover_beside_the_cache_is_swept(self, env):
        leaf, _out, _fake, run = env
        dead = leaf.parent / (pe.GLOBAL_INI_SCRATCH_PREFIX + "crashed1")
        (dead / "data").mkdir(parents=True)
        (dead / pe._SCRATCH_MARKER).write_text("")
        run()
        assert not dead.exists()

    def test_it_never_sweeps_a_dataforge_run(self, env):
        """Each extraction sweeps only its own names: a DataForge run in
        progress beside the same cache is not its business."""
        leaf, _out, _fake, run = env
        other = leaf.parent / (pe.DATAFORGE_SCRATCH_PREFIX + "deadrun1")
        other.mkdir(parents=True)
        (other / pe._SCRATCH_MARKER).write_text("")
        run()
        assert other.exists()


class TestExtractGlobalIni:
    def test_it_works_beside_the_cache_with_the_real_process(self, root, systemp):
        """unp4k's working folder beside the cache, with a real child."""
        p4k, py, _pid = _real_tools(root)
        leaf = root / "cache" / "LIVE" / "cache" / "dataforge"
        out = root / "data" / "LIVE" / "cache" / "base.ini"
        assert pe.extract_global_ini(p4k, out, py, scratch_near=leaf) is True
        assert out.read_text(encoding="utf-8") == "key=value\n"
        assert _scratch_folders(leaf.parent, pe.GLOBAL_INI_SCRATCH_PREFIX) == []
        assert list(systemp.iterdir()) == []

    def test_it_works_in_its_own_temp_folder_and_cleans_up(self, root, systemp):
        p4k, py, _pid = _real_tools(root)
        out = root / "data" / "LIVE" / "cache" / "base.ini"
        assert pe.extract_global_ini(p4k, out, py) is True
        assert out.read_text(encoding="utf-8") == "key=value\n"
        assert _scratch_folders(systemp, pe._GLOBAL_INI_TEMP_PREFIX) == []

    def test_a_stop_kills_unp4k_and_leaves_base_ini_alone(self, root, systemp):
        p4k, py, pid_file = _real_tools(root, slow_global_ini=True)
        out = root / "data" / "LIVE" / "cache" / "base.ini"
        out.parent.mkdir(parents=True)
        out.write_text("old=1\n", encoding="utf-8")
        with pytest.raises(pe.ExtractionCancelled):
            pe.extract_global_ini(p4k, out, py, should_cancel=pid_file.exists)
        pid = int(pid_file.read_text())
        assert _wait_for(lambda: not _pid_alive(pid), 5)
        assert out.read_text(encoding="utf-8") == "old=1\n"
        assert _scratch_folders(systemp, pe._GLOBAL_INI_TEMP_PREFIX) == []

    def test_a_leftover_from_a_crash_is_swept(self, root, systemp):
        dead = systemp / (pe._GLOBAL_INI_TEMP_PREFIX + "crashed1")
        dead.mkdir()
        (dead / pe._SCRATCH_MARKER).write_text("")
        p4k, py, _pid = _real_tools(root)
        pe.extract_global_ini(p4k, root / "base.ini", py)
        assert not dead.exists()
