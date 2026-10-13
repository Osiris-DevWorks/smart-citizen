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
* The free-space check (#482): every drive a run writes to, before any tool
  runs and again just before the old cache is wiped, and a drive that fills
  during the copy. conftest's ``no_real_free_space`` keeps every other test
  here off the real drive's free space.

Qt-free. Child processes run on the base interpreter (``sys._base_executable``)
because a venv's ``python.exe`` is a launcher that starts a second process,
and killing the launcher would leave that one running, which is the very thing
under test. Every child exits on its own within 30 s even if a kill fails.
"""
from __future__ import annotations

import errno
import logging
import os
import shutil
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
# Free bytes on a drive the free-space tests never make short (1 TiB).
_PLENTY = 1 << 40
# The cluster size of a 128 KiB-cluster exFAT stick, the large-cluster drive.
_EXFAT_CLUSTER = 128 << 10


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

    def test_a_stop_before_the_start_runs_nothing(self, root, monkeypatch):
        started = []
        monkeypatch.setattr(pe.subprocess, "Popen", lambda *a, **k: started.append(a))
        with pytest.raises(pe.ExtractionCancelled):
            pe._run_tool([PY, "-c", "pass"], cwd=str(root), timeout=60,
                         should_cancel=lambda: True)
        assert started == []

    def test_a_pending_stop_wins_over_a_clean_exit(self, root, monkeypatch):
        """A tool that finishes while a stop is pending must not hand its exit
        code on: the stop is what the caller acts on. A 30 s poll makes the
        first communicate() return only when the tool exits, so this reaches
        the after-exit check and not the kill."""
        monkeypatch.setattr(pe, "_TOOL_POLL_SECONDS", 30)
        child = _script(root / "quick.py", "print('done')\n")
        answers = iter([False])   # not stopped at the start, stopped after

        with pytest.raises(pe.ExtractionCancelled, match="finished"):
            pe._run_tool([PY, str(child)], cwd=str(root), timeout=60,
                         should_cancel=lambda: next(answers, True))

    def test_a_killed_tool_whose_child_holds_the_pipes_is_not_waited_on_forever(
        self, root, monkeypatch, caplog
    ):
        """A tool that started a child of its own, which inherited the output
        pipes, keeps them open after the kill. The reap gives up after
        _TOOL_REAP_SECONDS instead of hanging the stop (or the close)."""
        monkeypatch.setattr(pe, "_TOOL_REAP_SECONDS", 1)
        pid_file, grand_pid_file = root / "pid", root / "grand.pid"
        grand_code = (
            "import os, time\n"
            f"open({str(grand_pid_file)!r}, 'w').write(str(os.getpid()))\n"
            "time.sleep(20)\n"
        )
        child = _script(root / "parent.py", (
            "import os, subprocess, sys, time\n"
            + _write_pid_code(pid_file)
            + f"subprocess.Popen([sys.executable, '-c', {grand_code!r}], "
            "stdout=sys.stdout, stderr=sys.stderr, creationflags=0x08000000)\n"
            "time.sleep(30)\n"
        ))
        started = time.monotonic()
        try:
            with caplog.at_level(logging.WARNING, logger=pe.logger.name):
                with pytest.raises(pe.ExtractionCancelled):
                    pe._run_tool([PY, str(child)], cwd=str(root), timeout=60,
                                 should_cancel=lambda: grand_pid_file.exists())
            assert time.monotonic() - started < 15
            assert "held its output pipes" in caplog.text
            assert _wait_for(lambda: not _pid_alive(int(pid_file.read_text())), 5)
        finally:
            if grand_pid_file.exists() and grand_pid_file.read_text():
                subprocess.run(["taskkill", "/F", "/PID", grand_pid_file.read_text()],
                               capture_output=True)

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
        assert pe._scratch_location(over_cap / "dataforge") == (systemp, pe._DATAFORGE_TEMP_PREFIX)

    def test_a_network_share_uses_temp(self, systemp):
        leaf = Path(r"\\server\share\SC\LIVE\cache\dataforge")
        assert pe._scratch_location(leaf) == (systemp, pe._DATAFORGE_TEMP_PREFIX)

    def test_onedrive_uses_temp(self, root, systemp, monkeypatch):
        onedrive = root / "OneDrive"
        monkeypatch.setenv("OneDrive", str(onedrive))
        leaf = onedrive / "Smart Citizen" / "LIVE" / "cache" / "dataforge"
        assert pe._scratch_location(leaf) == (systemp, pe._DATAFORGE_TEMP_PREFIX)

    def test_a_removable_or_network_drive_uses_temp(self, root, systemp, monkeypatch):
        monkeypatch.setattr(pe, "_drive_is_removable_or_network", lambda path: True)
        leaf = root / "SC" / "LIVE" / "cache" / "dataforge"
        assert pe._scratch_location(leaf) == (systemp, pe._DATAFORGE_TEMP_PREFIX)

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
        pe._sweep_stale_scratch(root, pe._DATAFORGE_TEMP_PREFIX)
        pe._sweep_stale_scratch(root, pe.GLOBAL_INI_SCRATCH_PREFIX)
        pe._sweep_stale_scratch(root, pe._GLOBAL_INI_TEMP_PREFIX)
        assert all(folder.exists() for folder in others)

    def test_a_marker_that_cannot_be_opened_leaves_no_folder(self, root, monkeypatch):
        def refuse(*args, **kwargs):
            raise PermissionError("held by antivirus")

        # A module-level open shadows the builtin inside pak_extractor only.
        monkeypatch.setattr(pe, "open", refuse, raising=False)
        with pytest.raises(PermissionError):
            pe._open_scratch(root, pe.DATAFORGE_SCRATCH_PREFIX)
        assert _scratch_folders(root, pe.DATAFORGE_SCRATCH_PREFIX) == []

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
        assert run_dir.name.startswith(pe._DATAFORGE_TEMP_PREFIX)
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

    def test_a_temp_leftover_is_swept_too(self, setup, systemp):
        """The %TEMP% fallback (OneDrive, network, removable or deep caches)
        leaves its own leftovers, swept whichever place this run uses."""
        _leaf, run = setup
        dead = systemp / (pe._DATAFORGE_TEMP_PREFIX + "crashed1")
        (dead / "Data").mkdir(parents=True)
        (dead / pe._SCRATCH_MARKER).write_text("")
        run(_FakeTools())
        assert not dead.exists()

    def test_a_folder_beside_the_cache_that_cannot_be_made_fails_the_run(
        self, setup, monkeypatch, systemp
    ):
        """Unlike the global.ini extraction, DataForge does not fall back to
        %TEMP%: its cache writes go to that same drive and would fail anyway,
        after a minute of unforge."""
        leaf, run = setup
        real_open = pe._open_scratch

        def refuse_beside(parent, prefix):
            if Path(parent) != systemp:
                raise PermissionError("Controlled Folder Access")
            return real_open(parent, prefix)

        monkeypatch.setattr(pe, "_open_scratch", refuse_beside)
        fake = _FakeTools()
        with pytest.raises(PermissionError):
            run(fake)
        assert fake.calls == []
        assert (leaf / "old-cache-sentinel").exists()

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

    def test_a_refused_folder_beside_the_cache_falls_back_to_temp(
        self, env, systemp, monkeypatch
    ):
        """It only ever needed %TEMP% before #471, so a folder beside the
        cache that cannot be made (permissions, Controlled Folder Access, a
        read-only drive) must not stop the base.ini refresh."""
        _leaf, out, fake, run = env
        real_open = pe._open_scratch

        def refuse_beside(parent, prefix):
            if Path(parent) != systemp:
                raise PermissionError("Controlled Folder Access")
            return real_open(parent, prefix)

        monkeypatch.setattr(pe, "_open_scratch", refuse_beside)
        assert run() is True
        run_dir = Path(fake.cwds[0])
        assert run_dir.parent == systemp
        assert run_dir.name.startswith(pe._GLOBAL_INI_TEMP_PREFIX)
        assert not run_dir.exists()
        assert out.read_text(encoding="utf-8") == "lang=english\n"

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

    # ── free space (#482) ──

    def test_a_short_cache_drive_moves_it_to_temp(self, env, systemp, monkeypatch, caplog):
        """Decision 1: a cache drive too full for the ~31 MB of work sends the
        run to %TEMP% quietly, as a refused folder does: D:'s shortage and the
        move are INFO lines, and nothing is logged at WARNING. The user only
        hears about it when %TEMP%'s drive or the data folder's is short
        too."""
        leaf, out, fake, run = env
        out.parent.mkdir(parents=True)
        drive = _drive_letters(systemp, data=out.parents[2])
        _volumes(monkeypatch, drive)
        _disk_space(monkeypatch, lambda folder: pe._MIB if drive(folder) == "D:" else _PLENTY)
        with caplog.at_level(logging.INFO, logger=pe.logger.name):
            assert run() is True
        run_dir = Path(fake.cwds[0])
        assert run_dir.parent == systemp
        assert run_dir.name.startswith(pe._GLOBAL_INI_TEMP_PREFIX)
        assert out.read_text(encoding="utf-8") == "lang=english\n"
        moved = [r for r in caplog.records
                 if r.levelno == logging.INFO and "not enough free space" in r.getMessage()]
        assert moved and str(systemp) in moved[0].getMessage()
        assert any(r.levelno == logging.INFO
                   and r.getMessage().startswith(f"Not enough free space: D: has {pe._MIB:,}")
                   for r in caplog.records)
        assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == []

    def test_a_short_temp_drive_stops_it_and_keeps_base_ini(
        self, env, systemp, monkeypatch, english_ui
    ):
        """No cache folder (its drive offline): %TEMP% is the only place, so a
        short one refuses with the plain advice, before unp4k runs and
        without making a folder. Never the temp advice, which ends in the
        same sentence but blames a cache folder on OneDrive or a network
        drive, which this run does not have."""
        _leaf, out, fake, run = env
        out.parent.mkdir(parents=True)
        out.write_text("old=1\n", encoding="utf-8")
        drive = _drive_letters(systemp)
        _volumes(monkeypatch, drive)
        _disk_space(monkeypatch, lambda folder: pe._MIB if drive(folder) == "C:" else _PLENTY)
        with pytest.raises(pe.NotEnoughSpaceError) as raised:
            run(near=None)
        assert fake.cwds == []
        assert out.read_text(encoding="utf-8") == "old=1\n"
        assert list(systemp.iterdir()) == []
        assert [s[0] for s in raised.value.shortages] == ["C:"]
        assert _intro_and_advice(raised) == (
            pe.tr("extract.no_space_global_ini"), [pe.tr("extract.no_space_fix", drive="C:")])

    def test_base_ini_is_counted_on_the_data_folder_drive(
        self, env, systemp, monkeypatch, english_ui
    ):
        """base.ini goes to the data folder, often another drive than the
        cache. Short there, %TEMP% cannot help, so the run is refused naming
        that drive, with the plain advice (choosing another cache folder
        would not help either), and unp4k never runs."""
        leaf, out, fake, run = env
        out.parent.mkdir(parents=True)
        drive = _drive_letters(systemp, data=out.parents[2])
        _volumes(monkeypatch, drive)
        _disk_space(monkeypatch, lambda folder: pe._MIB if drive(folder) == "E:" else _PLENTY)
        with pytest.raises(pe.NotEnoughSpaceError) as raised:
            run()
        assert [s[0] for s in raised.value.shortages] == ["E:"]
        assert _intro_and_advice(raised) == (
            pe.tr("extract.no_space_global_ini"), [pe.tr("extract.no_space_fix", drive="E:")])
        assert fake.cwds == []
        assert not out.exists()
        assert _scratch_folders(leaf.parent, pe.GLOBAL_INI_SCRATCH_PREFIX) == []
        assert list(systemp.iterdir()) == []

    def test_the_temp_retry_is_checked_too(self, env, systemp, monkeypatch, english_ui):
        """A folder beside the cache that cannot be made sends the run to
        %TEMP%, which gets the same check before anything is made there, and
        the plain advice when it is short."""
        leaf, out, fake, run = env
        out.parent.mkdir(parents=True)
        real_open = pe._open_scratch

        def refuse_beside(parent, prefix):
            if Path(parent) != systemp:
                raise PermissionError("Controlled Folder Access")
            return real_open(parent, prefix)

        monkeypatch.setattr(pe, "_open_scratch", refuse_beside)
        drive = _drive_letters(systemp)
        _volumes(monkeypatch, drive)
        _disk_space(monkeypatch, lambda folder: pe._MIB if drive(folder) == "C:" else _PLENTY)
        with pytest.raises(pe.NotEnoughSpaceError) as raised:
            run()
        assert fake.cwds == []
        assert list(systemp.iterdir()) == []
        assert _scratch_folders(leaf.parent, pe.GLOBAL_INI_SCRATCH_PREFIX) == []
        assert _intro_and_advice(raised) == (
            pe.tr("extract.no_space_global_ini"), [pe.tr("extract.no_space_fix", drive="C:")])

    @pytest.mark.parametrize("temp_free", [10 << 20, _PLENTY], ids=["temp short too", "temp fine"])
    def test_a_short_data_drive_alone_does_not_move_it_to_temp(
        self, env, systemp, monkeypatch, caplog, english_ui, temp_free
    ):
        """base.ini goes to the data folder wherever the work runs, so moving
        the work to %TEMP% cannot help a shortage there. With room beside the
        cache (D:), a short data folder drive (E:) refuses the run at once,
        at WARNING, naming E: alone with the plain advice. %TEMP%'s drive (C:)
        is never named, short or not, and there is no move to log."""
        leaf, out, fake, run = env
        out.parent.mkdir(parents=True)
        drive = _drive_letters(systemp, data=out.parents[2])
        _volumes(monkeypatch, drive)
        free = {"C:": temp_free, "D:": _PLENTY, "E:": 5 << 20}
        _disk_space(monkeypatch, lambda folder: free[drive(folder)])
        with caplog.at_level(logging.INFO, logger=pe.logger.name):
            with pytest.raises(pe.NotEnoughSpaceError) as raised:
                run()
        assert [s[0] for s in raised.value.shortages] == ["E:"]
        assert _intro_and_advice(raised) == (
            pe.tr("extract.no_space_global_ini"), [pe.tr("extract.no_space_fix", drive="E:")])
        assert "C:" not in str(raised.value)
        assert fake.cwds == []
        assert [r.getMessage() for r in caplog.records if "; working in " in r.getMessage()] == []
        base_ini = pe._space_for(pe._BASE_INI_BYTES, 1, 4096)
        assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == [
            f"Not enough free space: E: has {5 << 20:,} bytes free and needs about {base_ini:,}"]
        assert list(systemp.iterdir()) == []
        assert _scratch_folders(leaf.parent, pe.GLOBAL_INI_SCRATCH_PREFIX) == []

    def test_a_short_data_folder_on_the_temp_drive_is_asked_for_base_ini_only(
        self, env, systemp, monkeypatch, english_ui
    ):
        """The data folder on %TEMP%'s drive (C:) and the cache on D:, which
        has room. C: is short for base.ini, so the run is refused for base.ini
        alone, not for the work as well, which never needed C:, and with the
        plain advice."""
        _leaf, out, fake, run = env
        out.parent.mkdir(parents=True)
        on_c = (pe.win_plain_path(systemp), pe.win_plain_path(out.parents[2]))

        def drive(folder):
            return "C:" if any(folder == c or folder.startswith(c + os.sep) for c in on_c) else "D:"

        _volumes(monkeypatch, drive)
        _disk_space(monkeypatch, lambda folder: (10 << 20) if drive(folder) == "C:" else _PLENTY)
        with pytest.raises(pe.NotEnoughSpaceError) as raised:
            run()
        base_ini = pe._space_for(pe._BASE_INI_BYTES, 1, 4096)
        assert [s[0::3] for s in raised.value.shortages] == [("C:", base_ini)]
        assert _intro_and_advice(raised) == (
            pe.tr("extract.no_space_global_ini"), [pe.tr("extract.no_space_fix", drive="C:")])
        assert fake.cwds == []

    def test_a_short_cache_drive_and_a_short_temp_drive_give_one_warning(
        self, env, systemp, monkeypatch, caplog, english_ui
    ):
        """D: beside the cache is short, so the work moves to %TEMP%, and C:
        there is short too: refused for C: alone, with the plain advice. D:'s
        shortage was only the reason for the move and stays at INFO, so the
        refusal's is the one WARNING."""
        _leaf, out, fake, run = env
        out.parent.mkdir(parents=True)
        drive = _drive_letters(systemp, data=out.parents[2])
        _volumes(monkeypatch, drive)
        _disk_space(monkeypatch,
                    lambda folder: pe._MIB if drive(folder) in ("C:", "D:") else _PLENTY)
        with caplog.at_level(logging.INFO, logger=pe.logger.name):
            with pytest.raises(pe.NotEnoughSpaceError) as raised:
                run()
        assert [s[0] for s in raised.value.shortages] == ["C:"]
        assert _intro_and_advice(raised) == (
            pe.tr("extract.no_space_global_ini"), [pe.tr("extract.no_space_fix", drive="C:")])
        warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warnings) == 1 and warnings[0].startswith("Not enough free space: C: has")
        assert any(r.levelno == logging.INFO
                   and r.getMessage().startswith("Not enough free space: D: has")
                   for r in caplog.records)
        assert fake.cwds == []

    def test_a_cache_drive_that_is_gone_is_skipped_and_the_run_moves_to_temp(
        self, env, systemp, monkeypatch, caplog
    ):
        """The cache folder's drive is gone, so no folder above the work's
        place beside it exists. The check skips that part with a WARNING
        rather than call the drive short, and the run moves to %TEMP%
        because the folder there cannot be made, as it did before the check,
        and succeeds."""
        leaf, out, fake, run = env
        _cache_drive_gone(monkeypatch, leaf.parents[2])
        _disk_space(monkeypatch)
        with caplog.at_level(logging.INFO, logger=pe.logger.name):
            assert run() is True
        assert Path(fake.cwds[0]).parent == systemp
        assert out.read_text(encoding="utf-8") == "lang=english\n"
        messages = [(r.levelno, r.getMessage()) for r in caplog.records]
        assert any(level == logging.WARNING and "no folder above it exists" in message
                   for level, message in messages)
        moves = [message for _level, message in messages if "; working in " in message]
        assert len(moves) == 1 and "cannot find the path" in moves[0]
        assert not any("not enough free space" in message.lower() for _level, message in messages)


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


# ── the free-space check (#482) ─────────────────────────────────────────────

def _disk_space(monkeypatch, free=None, default=_PLENTY, raises=None):
    """Patch shutil.disk_usage, over conftest's session stub. *free* gives the
    free bytes for the folder asked (a dict keyed by folder, or a callable
    taking the plain folder path), *default* for any other folder, and
    *raises* makes every call raise it. The stub's real call still runs, so
    a folder that does not exist still raises. Returns the plain folders
    asked, in order."""
    asked = []
    stub = shutil.disk_usage
    table = ({pe.win_plain_path(k): v for k, v in free.items()}
             if isinstance(free, dict) else {})

    def usage(path):
        plain = pe.win_plain_path(path)
        asked.append(plain)
        if raises is not None:
            raise raises
        figure = free(plain) if callable(free) else table.get(plain, default)
        return stub(path)._replace(free=figure)

    monkeypatch.setattr(shutil, "disk_usage", usage)
    return asked


def _volumes(monkeypatch, drive_of, *, cluster=4096, caller_free=None):
    """Replace the volume probe: *drive_of(plain folder)* names the drive a
    folder is on, and each name is its own volume."""
    keys = {}

    def measure(folder):
        label = drive_of(pe.win_plain_path(folder))
        return pe._Volume(keys.setdefault(label, len(keys) + 1), label, cluster, caller_free)

    monkeypatch.setattr(pe, "_measure_volume", measure)


def _drive_letters(systemp, data=None):
    """A *drive_of* for _volumes: %TEMP% is on C:, the data folder (when
    given) on E:, everything else (the cache) on D:."""
    temp = pe.win_plain_path(systemp)
    data = pe.win_plain_path(data) if data is not None else None

    def drive_of(folder):
        if folder == temp or folder.startswith(temp + os.sep):
            return "C:"
        if data is not None and (folder == data or folder.startswith(data + os.sep)):
            return "E:"
        return "D:"

    return drive_of


def _intro_and_advice(raised) -> tuple[str, list[str]]:
    """A refusal's first paragraph, which names the extraction, and its
    advice paragraphs. The message is the intro, one line per short drive,
    then the advice for each drive in the same order."""
    paragraphs = str(raised.value).split("\n\n")
    short = len(raised.value.shortages)
    assert len(paragraphs) == 1 + 2 * short, paragraphs
    return paragraphs[0], paragraphs[1 + short:]


def _cache_drive_gone(monkeypatch, cache_root: Path) -> None:
    """The drive that holds *cache_root* is gone (a USB stick pulled after
    the cache folder was resolved): the free-space check finds no folder
    above anything under it, and making a folder there fails as Windows
    fails it. The folders under tmp_path are really there, hence the fakes."""
    gone = pe.win_plain_path(cache_root)
    real_nearest, real_open = pe._nearest_existing_folder, pe._open_scratch

    def under(path):
        plain = pe.win_plain_path(path)
        return plain == gone or plain.startswith(gone + os.sep)

    def nearest(path):
        return None if under(path) else real_nearest(path)

    def open_scratch(parent, prefix):
        if under(parent):
            raise FileNotFoundError(errno.ENOENT, "The system cannot find the path specified",
                                    str(parent))
        return real_open(parent, prefix)

    monkeypatch.setattr(pe, "_nearest_existing_folder", nearest)
    monkeypatch.setattr(pe, "_open_scratch", open_scratch)


class _ListedWithAttributes:
    """A DirEntry whose stat() adds *attributes* to the real ones. A DirEntry
    cannot be made or changed, so this stands in for one."""

    def __init__(self, entry, attributes: int):
        self._entry, self._attributes = entry, attributes

    def __getattr__(self, name):
        return getattr(self._entry, name)

    def stat(self, *, follow_symlinks=True):
        return _StatWithAttributes(self._entry.stat(follow_symlinks=follow_symlinks),
                                   self._attributes)


class _StatWithAttributes:
    """A stat result with *attributes* added to st_file_attributes and every
    other field the real one, so code that reads st_mode still works (Python
    3.11's shutil.rmtree does, when the run deletes the old cache)."""

    def __init__(self, real, attributes: int):
        self._real = real
        self.st_file_attributes = real.st_file_attributes | attributes

    def __getattr__(self, name):
        return getattr(self._real, name)


def _listed_with(monkeypatch, file: Path, attributes: int) -> None:
    """Make the directory listing report *file* with *attributes* as well,
    the way Windows lists a OneDrive online-only file: its full size, with a
    recall or offline attribute because its data is not on this PC. Those
    are set by the cloud files driver, not by a program, hence the fake.
    Every other entry is the real one."""
    real_scandir = os.scandir
    target = pe.win_plain_path(file)

    class Listing:
        def __init__(self, path="."):
            self._entries = real_scandir(path)

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            self._entries.close()

        def __iter__(self):
            return self

        def __next__(self):
            entry = next(self._entries)
            if pe.win_plain_path(entry.path) == target:
                return _ListedWithAttributes(entry, attributes)
            return entry

        def close(self):
            self._entries.close()

    monkeypatch.setattr(os, "scandir", Listing)


# What a DataForge run asks for at 4096-byte clusters: its working folder, the
# new cache, and what the check before the wipe asks for _FakeTools' output
# (one 4-byte file per keep subtree, a cluster each, plus the reserve).
_WORK_4K = pe._space_for(pe._DATAFORGE_WORK_BYTES, pe._DATAFORGE_WORK_FILES, 4096)
_CACHE_4K = pe._space_for(pe._DATAFORGE_CACHE_BYTES, pe._DATAFORGE_CACHE_FILES, 4096)
_GATE_4K = len(pe.DATAFORGE_KEEP_SUBPATHS) * 4096 + pe._NEW_CACHE_RESERVE_BYTES


class TestFreeSpaceCheck:
    """extract_dataforge refuses a run that would not fit (#482): before any
    tool runs, per volume, with the old cache counted as room only when it is
    complete; again just before the old cache is wiped; and a drive that
    fills during the copy gets the same error instead of a raw OSError."""

    def test_the_real_free_space_is_never_read(self, root):
        """conftest's no_real_free_space keeps every real extraction in the
        suite off the free space of the drive it happens to run on."""
        loaded = [sys.modules[name] for name in ("src.utils.pak_extractor", "utils.pak_extractor")
                  if name in sys.modules]
        assert pe in loaded
        for module in loaded:
            assert module._measure_volume(root)[2:] == (4096, None)
            with pytest.raises(OSError):
                module._measure_volume(root / "missing")   # the real probe still runs
        assert shutil.disk_usage(str(root)).free == 1 << 40
        with pytest.raises(FileNotFoundError):
            shutil.disk_usage(str(root / "missing"))

    def test_the_real_volume_probe_reads_this_volume(self, root, monkeypatch):
        """The Windows calls themselves, on this machine's drive (CI's 3.11
        included). A wrong ctypes call would only show as its fallback, so
        each fallback is made one that no drive has: a 1-byte cluster, and
        "?:" for the label, whose usual fallback (the drive in the path's
        text) is exactly what GetVolumePathNameW answers for tmp_path."""
        monkeypatch.setattr(pe, "_DEFAULT_CLUSTER_BYTES", 1)
        monkeypatch.setattr(pe, "_drive_label", lambda plain: "?:")
        volume = pe._measure_volume.__wrapped__(root)
        assert volume.key == os.stat(root).st_dev != 0
        assert volume.cluster >= 512 and volume.cluster & (volume.cluster - 1) == 0
        assert isinstance(volume.caller_free, int) and volume.caller_free > 0
        assert volume.label == os.path.splitdrive(str(root))[0]

    def test_a_short_drive_beside_the_cache_stops_before_any_tool_runs(
        self, setup, systemp, monkeypatch, english_ui
    ):
        """Refused in a second instead of failing in unforge minutes later,
        with nothing made and the old cache as it was. The cache's drive (D:)
        has room for the new cache but not for the work beside it too, and
        %TEMP%'s (C:) has plenty: DataForge still does not move its work to
        %TEMP%, unlike the global.ini extraction (decision 1). The message
        is DataForge's, with the advice to pick a cache folder elsewhere."""
        leaf, run = setup
        drive = _drive_letters(systemp)
        _volumes(monkeypatch, drive)
        assert _CACHE_4K < 2 * pe._GIB < _WORK_4K + _CACHE_4K
        _disk_space(monkeypatch, lambda folder: 2 * pe._GIB if drive(folder) == "D:" else _PLENTY)
        fake = _FakeTools()
        with pytest.raises(pe.NotEnoughSpaceError) as raised:
            run(fake)
        assert [s[0] for s in raised.value.shortages] == ["D:"]
        assert _intro_and_advice(raised) == (
            pe.tr("extract.no_space_dataforge"), [pe.tr("extract.no_space_fix_cache", drive="D:")])
        assert fake.calls == []
        assert (leaf / "old-cache-sentinel").exists() and (leaf / "raw" / "libs").is_dir()
        assert not (leaf / pe.P4K_MTIME_STAMP).exists()
        assert _scratch_folders(leaf.parent, pe.DATAFORGE_SCRATCH_PREFIX) == []
        assert list(systemp.iterdir()) == []

    def test_a_first_run_needs_the_working_folder_and_the_new_cache(self, setup, monkeypatch):
        """setup's leaf has raw/libs but no stamp: a first run, or a run cut
        off between the wipe and the stamps. Neither makes room, so the
        working folder and the new cache must both fit. Exactly enough
        passes."""
        leaf, run = setup
        both = _WORK_4K + _CACHE_4K
        _disk_space(monkeypatch, default=both - 1)
        with pytest.raises(pe.NotEnoughSpaceError) as raised:
            run(_FakeTools())
        assert raised.value.shortages[0][2:] == (both - 1, both)
        _disk_space(monkeypatch, default=both)
        assert run(_FakeTools()) is True
        assert (leaf / pe.P4K_SIZE_STAMP).exists()

    def test_a_stamped_old_cache_makes_room(self, setup, monkeypatch):
        """A complete cache is wiped before the new one is written, so it
        counts as room."""
        leaf, run = setup
        (leaf / pe.P4K_MTIME_STAMP).write_text("1")
        need = _WORK_4K + _CACHE_4K - pe._DATAFORGE_CACHE_BYTES
        _disk_space(monkeypatch, default=need - 1)
        with pytest.raises(pe.NotEnoughSpaceError):
            run(_FakeTools())
        _disk_space(monkeypatch, default=need)
        assert run(_FakeTools()) is True

    def test_a_stamped_old_cache_frees_a_cluster_per_file(self, setup, monkeypatch):
        """On a 128 KiB-cluster exFAT stick each of the old cache's ~31k
        files takes a whole cluster, so the wipe frees that, not just its
        1.2 GB of bytes. The new cache is charged a cluster per file, and a
        credit of bytes alone asked a re-extract there for about 2.5 GB more
        than it needs. Exactly enough passes."""
        leaf, run = setup
        (leaf / pe.P4K_MTIME_STAMP).write_text("1")
        cluster = _EXFAT_CLUSTER
        _volumes(monkeypatch, lambda folder: "D:", cluster=cluster)
        frees = pe._DATAFORGE_CACHE_FILES * cluster
        assert frees > pe._DATAFORGE_CACHE_BYTES
        need = (pe._space_for(pe._DATAFORGE_WORK_BYTES, pe._DATAFORGE_WORK_FILES, cluster)
                + pe._space_for(pe._DATAFORGE_CACHE_BYTES, pe._DATAFORGE_CACHE_FILES, cluster)
                - frees)
        _disk_space(monkeypatch, default=need - 1)
        with pytest.raises(pe.NotEnoughSpaceError) as raised:
            run(_FakeTools())
        assert raised.value.shortages[0][2:] == (need - 1, need)
        _disk_space(monkeypatch, default=need)
        assert run(_FakeTools()) is True

    def test_a_stamp_without_raw_libs_makes_no_room(self, setup, monkeypatch):
        """A stray .p4k_mtime with no raw/libs beside it (removed by hand, or
        a clean that got part-way) is no cache for the wipe to free, so the
        free space test_a_stamped_old_cache_makes_room passes with is short."""
        leaf, run = setup
        (leaf / pe.P4K_MTIME_STAMP).write_text("1")
        (leaf / "raw" / "libs").rmdir()
        _disk_space(monkeypatch, default=_WORK_4K + _CACHE_4K - pe._DATAFORGE_CACHE_BYTES)
        fake = _FakeTools()
        with pytest.raises(pe.NotEnoughSpaceError):
            run(fake)
        assert fake.calls == []
        assert (leaf / "old-cache-sentinel").exists()

    def test_the_figures_cover_the_measured_run(self):
        """The LIVE 4.10 run the constants come from (#482), with GB read as
        GiB, the larger reading."""
        gib, mib = 1 << 30, 1 << 20
        assert pe._DATAFORGE_WORK_BYTES >= 317 * mib + 1.84 * gib   # Game2.dcb + unforge's tree
        assert pe._DATAFORGE_WORK_FILES >= 61_950
        assert pe._DATAFORGE_CACHE_BYTES >= 1.2 * gib
        assert pe._DATAFORGE_CACHE_FILES >= 30_700
        assert pe._GLOBAL_INI_WORK_BYTES >= 31 * mib
        assert pe._BASE_INI_BYTES >= 11_128_009   # the English global.ini
        assert _WORK_4K + _CACHE_4K >= 4.2 * gib

    @pytest.mark.parametrize("short", [("C:",), ("D:",), ("C:", "D:")],
                             ids=["temp", "cache", "both"])
    def test_with_the_work_in_temp_each_drive_is_checked_for_its_own_part(
        self, setup, systemp, monkeypatch, english_ui, short
    ):
        """A OneDrive cache works in %TEMP% on C: and keeps its cache on D:.
        Each drive needs only its own part, and the message names each short
        one with the advice that fits it: the temp advice for the work in
        %TEMP% (why it is there and where), the cache advice for the cache."""
        _leaf, run = setup
        monkeypatch.setattr(pe, "is_onedrive_path", lambda path: True)
        drive = _drive_letters(systemp)
        _volumes(monkeypatch, drive)
        own_part = {"C:": _WORK_4K, "D:": _CACHE_4K}
        _disk_space(monkeypatch,
                    lambda folder: own_part[drive(folder)] - (drive(folder) in short))
        with pytest.raises(pe.NotEnoughSpaceError) as raised:
            run(_FakeTools())
        assert [s[0] for s in raised.value.shortages] == list(short)
        advice = {
            "C:": pe.tr("extract.no_space_fix_temp", drive="C:", folder=str(systemp)),
            "D:": pe.tr("extract.no_space_fix_cache", drive="D:"),
        }
        assert _intro_and_advice(raised) == (
            pe.tr("extract.no_space_dataforge"), [advice[label] for label in short])

    def test_with_the_work_in_temp_exactly_enough_on_each_drive_passes(
        self, setup, systemp, monkeypatch
    ):
        """The control for the test above: neither drive a byte short."""
        _leaf, run = setup
        monkeypatch.setattr(pe, "is_onedrive_path", lambda path: True)
        drive = _drive_letters(systemp)
        _volumes(monkeypatch, drive)
        own_part = {"C:": _WORK_4K, "D:": _CACHE_4K}
        _disk_space(monkeypatch, lambda folder: own_part[drive(folder)])
        assert run(_FakeTools()) is True

    def test_one_drive_for_both_parts_adds_them(self, setup, systemp, monkeypatch):
        """%TEMP% and the cache on one volume: both parts land there."""
        _leaf, run = setup
        monkeypatch.setattr(pe, "is_onedrive_path", lambda path: True)
        _volumes(monkeypatch, lambda folder: "C:")
        both = _WORK_4K + _CACHE_4K
        _disk_space(monkeypatch, {systemp: both - 1})
        with pytest.raises(pe.NotEnoughSpaceError):
            run(_FakeTools())
        _disk_space(monkeypatch, {systemp: both})
        assert run(_FakeTools()) is True

    def test_each_drive_gets_one_clean_info_line(self, setup, systemp, monkeypatch, caplog):
        """The Log tab line per drive gives what it has and what the run needs
        there. A drive letter label already ends in its colon ("D:"), so the
        line must not add a second one."""
        _leaf, run = setup
        monkeypatch.setattr(pe, "is_onedrive_path", lambda path: True)
        _volumes(monkeypatch, _drive_letters(systemp))
        free = 5 * pe._GIB
        _disk_space(monkeypatch, default=free)
        with caplog.at_level(logging.INFO, logger=pe.logger.name):
            assert run(_FakeTools()) is True
        lines = sorted(r.getMessage() for r in caplog.records
                       if r.getMessage().startswith("Free space on "))
        assert lines == [
            f"Free space on C: is {free:,} bytes, about {_WORK_4K:,} needed (4096-byte clusters)",
            f"Free space on D: is {free:,} bytes, about {_CACHE_4K:,} needed (4096-byte clusters)",
        ]
        assert [r.getMessage() for r in caplog.records if "::" in r.getMessage()] == []

    def test_leftovers_are_swept_before_the_space_is_measured(self, setup, monkeypatch):
        """A crashed run's leftover can be a whole working folder. It goes
        first, then the space is counted."""
        leaf, run = setup
        dead = leaf.parent / (pe.DATAFORGE_SCRATCH_PREFIX + "crashed1")
        (dead / "Data").mkdir(parents=True)
        (dead / pe._SCRATCH_MARKER).write_text("")
        enough = _WORK_4K + _CACHE_4K
        _disk_space(monkeypatch, lambda folder: 1 if dead.exists() else enough)
        assert run(_FakeTools()) is True
        assert not dead.exists()

    def test_a_cache_folder_that_does_not_exist_yet_is_measured_at_its_nearest_parent(
        self, root, monkeypatch
    ):
        """The free-space calls fail on a folder that does not exist, so the
        check walks up to one that does, and makes nothing on the way."""
        tools = root / "tools"
        tools.mkdir()
        for name in ("unp4k.exe", "unforge.exe", "Data.p4k"):
            (tools / name).write_bytes(b"x")
        leaf = root / "new" / "SC" / "LIVE" / "cache" / "dataforge"
        asked = _disk_space(monkeypatch, {root: 1})
        fake = _FakeTools()
        monkeypatch.setattr(pe, "_run_tool", fake)
        with pytest.raises(pe.NotEnoughSpaceError):
            pe.extract_dataforge(tools / "Data.p4k", tools / "unp4k.exe", tools / "unforge.exe",
                                 leaf)
        assert pe.win_plain_path(root) in asked
        assert not (root / "new").exists()
        assert fake.calls == []

    def test_a_cache_drive_that_is_gone_is_skipped_not_called_short(
        self, setup, systemp, monkeypatch, caplog
    ):
        """No folder above the cache exists (its drive is gone), so neither
        part can be measured. Each is skipped with a WARNING, like a probe
        that fails, and the run fails as it did before the check: the
        working folder beside the cache cannot be made. Not a free-space
        refusal, and no move to %TEMP% (DataForge never falls back)."""
        leaf, run = setup
        _cache_drive_gone(monkeypatch, leaf.parents[2])
        asked = _disk_space(monkeypatch, default=1)
        fake = _FakeTools()
        with caplog.at_level(logging.WARNING, logger=pe.logger.name):
            with pytest.raises(FileNotFoundError):
                run(fake)
        skipped = [r for r in caplog.records if r.getMessage().startswith(
            "Free-space check skipped for ") and "no folder above it exists" in r.getMessage()]
        assert len(skipped) == 2 and all(r.levelno == logging.WARNING for r in skipped)
        assert asked == []
        assert fake.calls == []
        assert list(systemp.iterdir()) == []

    def test_a_missing_tool_is_reported_before_the_free_space(self, setup, monkeypatch):
        leaf, run = setup
        (leaf.parents[3] / "tools" / "unforge.exe").unlink()
        _disk_space(monkeypatch, default=1)
        with pytest.raises(FileNotFoundError, match="unforge.exe"):
            run(_FakeTools())

    def test_a_drive_that_cannot_be_measured_does_not_stop_the_run(
        self, setup, monkeypatch, caplog
    ):
        """Best effort: a probe that fails is logged and the run goes on."""
        leaf, run = setup
        _disk_space(monkeypatch, raises=PermissionError("access denied"))
        with caplog.at_level(logging.WARNING, logger=pe.logger.name):
            assert run(_FakeTools()) is True
        assert "Free-space check skipped" in caplog.text
        assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []
        assert (leaf / pe.P4K_SIZE_STAMP).exists()

    def test_the_quota_figure_wins_when_it_is_smaller(self, setup, monkeypatch):
        """disk_usage reads the volume's free space, which ignores an NTFS
        per-user quota; the caller's own figure is the one that counts."""
        _leaf, run = setup
        _volumes(monkeypatch, lambda folder: "D:", caller_free=pe._GIB)
        _disk_space(monkeypatch)
        with pytest.raises(pe.NotEnoughSpaceError) as raised:
            run(_FakeTools())
        assert raised.value.shortages[0][2] == pe._GIB

    def test_large_clusters_ask_for_more(self, setup, monkeypatch):
        """~62k small files on a 128 KiB-cluster exFAT stick take far more
        than their size."""
        _leaf, run = setup
        _disk_space(monkeypatch, default=_WORK_4K + _CACHE_4K)
        _volumes(monkeypatch, lambda folder: "D:", cluster=_EXFAT_CLUSTER)
        with pytest.raises(pe.NotEnoughSpaceError):
            run(_FakeTools())
        _volumes(monkeypatch, lambda folder: "D:", cluster=4096)
        assert run(_FakeTools()) is True

    def test_a_short_drive_is_a_runtimeerror_logged_at_warning(self, setup, monkeypatch, caplog):
        """Not an OSError (no ``except OSError`` may read it as a folder that
        cannot be made), not a stop, and one the workers report quietly. The
        byte counts reach the log, the user gets the rounded figures."""
        assert issubclass(pe.NotEnoughSpaceError, RuntimeError)
        assert not issubclass(pe.NotEnoughSpaceError, (OSError, pe.ExtractionCancelled))
        assert pe.NotEnoughSpaceError in pe.ANTICIPATED_EXTRACTION_ERRORS
        _leaf, run = setup
        free, need = pe._GIB, _WORK_4K + _CACHE_4K
        _disk_space(monkeypatch, default=free)
        with caplog.at_level(logging.INFO, logger=pe.logger.name):
            with pytest.raises(pe.NotEnoughSpaceError):
                run(_FakeTools())
        assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []
        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any(f"{free:,}" in m and f"{need:,}" in m for m in warnings)

    def test_a_drive_that_fills_during_unforge_stops_before_the_wipe(
        self, setup, monkeypatch, caplog, english_ui
    ):
        """Another program (or a second Smart Citizen) can fill the drive
        while unforge runs. The check just before the wipe refuses, so the
        old cache is kept rather than lost to a copy that cannot finish,
        with DataForge's message and the cache advice.

        The user reads the box once the working folder beside the cache is
        gone, and a retry makes it again, so its allocation is in both
        figures: what the drive has then, and what a retry needs there."""
        leaf, run = setup
        filled = []
        _disk_space(monkeypatch, lambda folder: pe._MIB if filled else _PLENTY)
        fake = _FakeTools(during_unforge=lambda run_dir: filled.append(True))
        with caplog.at_level(logging.WARNING, logger=pe.logger.name):
            with pytest.raises(pe.NotEnoughSpaceError) as raised:
                run(fake)
        assert [tool for tool, _args, _cwd in fake.calls] == ["unp4k", "unforge"]
        assert (leaf / "old-cache-sentinel").exists() and (leaf / "raw" / "libs").is_dir()
        assert not (leaf / pe.P4K_MTIME_STAMP).exists()
        assert not Path(fake.calls[0][2]).exists()
        label, folder, free, need = raised.value.shortages[0]
        assert folder == pe.win_plain_path(leaf)
        assert _intro_and_advice(raised) == (
            pe.tr("extract.no_space_dataforge"), [pe.tr("extract.no_space_fix_cache", drive=label)])
        # _FakeTools' working folder: the dcb, one file per keep subtree and
        # one more, a 4096-byte cluster each. The old cache's 3-byte sentinel
        # frees one cluster.
        work = (len(pe.DATAFORGE_KEEP_SUBPATHS) + 2) * 4096
        assert free == pe._MIB + work
        # The need is never less than what a retry's up-front check asks this
        # drive for (the old cache here has no stamp, so it frees nothing).
        retry = (pe._space_for(pe._DATAFORGE_WORK_BYTES, pe._DATAFORGE_WORK_FILES, 4096)
                 + pe._space_for(pe._DATAFORGE_CACHE_BYTES, pe._DATAFORGE_CACHE_FILES, 4096))
        assert retry > _GATE_4K - 4096 + work
        assert need == retry
        assert f"{label} has {pe._MIB:,} bytes free" in caplog.text
        assert f"{label}::" not in caplog.text

    @pytest.mark.parametrize("cluster", [4096, _EXFAT_CLUSTER], ids=["4 KiB", "128 KiB"])
    def test_a_stamped_old_cache_counts_in_what_the_box_asks_for(self, setup, monkeypatch, cluster):
        """A re-extract over a complete cache, with the drive filling while
        unforge runs. The box asks for what a retry's up-front check will:
        the working folder and the new cache, less what the stamped old cache
        frees, which is at least a cluster per file. On a 128 KiB-cluster
        stick a credit of bytes alone named about 2.5 GB too much."""
        leaf, run = setup
        (leaf / pe.P4K_MTIME_STAMP).write_text("1")
        _volumes(monkeypatch, lambda folder: "D:", cluster=cluster)
        filled = []
        _disk_space(monkeypatch, lambda folder: pe._MIB if filled else _PLENTY)
        fake = _FakeTools(during_unforge=lambda run_dir: filled.append(True))
        with pytest.raises(pe.NotEnoughSpaceError) as raised:
            run(fake)
        assert (leaf / pe.P4K_MTIME_STAMP).exists() and (leaf / "old-cache-sentinel").exists()
        _label, _folder, free, need = raised.value.shortages[0]
        # The working folder is on the cache's drive, so it counts in both.
        assert free == pe._MIB + (len(pe.DATAFORGE_KEEP_SUBPATHS) + 2) * cluster
        frees = max(pe._DATAFORGE_CACHE_BYTES, pe._DATAFORGE_CACHE_FILES * cluster)
        assert need == (pe._space_for(pe._DATAFORGE_WORK_BYTES, pe._DATAFORGE_WORK_FILES, cluster)
                        + pe._space_for(pe._DATAFORGE_CACHE_BYTES, pe._DATAFORGE_CACHE_FILES,
                                        cluster)
                        - frees)

    @pytest.mark.parametrize("where", ["another drive", "a drive that cannot be measured"])
    def test_the_gate_leaves_out_a_working_folder_it_cannot_place_on_the_cache_drive(
        self, setup, systemp, monkeypatch, caplog, where
    ):
        """A OneDrive cache works in %TEMP% on C:, so deleting the working
        folder gives the cache's drive (D:) nothing back, and a working
        folder whose drive cannot be measured is left out too (best effort).
        The figures are then the cache drive's own, and the need is what a
        retry's up-front check asks that drive for: the new cache, not the
        64 MiB this run measured."""
        leaf, run = setup
        filled = []
        if where == "another drive":
            monkeypatch.setattr(pe, "is_onedrive_path", lambda path: True)
            drive = _drive_letters(systemp)
            _volumes(monkeypatch, drive)
            _disk_space(monkeypatch,
                        lambda folder: pe._MIB if filled and drive(folder) == "D:" else _PLENTY)
        else:
            _disk_space(monkeypatch, lambda folder: pe._MIB if filled else _PLENTY)
            stub = pe._measure_volume

            def measure(folder):
                if filled and pe.DATAFORGE_SCRATCH_PREFIX in pe.win_plain_path(folder):
                    raise OSError("the device is not ready")
                return stub(folder)

            monkeypatch.setattr(pe, "_measure_volume", measure)
        fake = _FakeTools(during_unforge=lambda run_dir: filled.append(True))
        with caplog.at_level(logging.WARNING, logger=pe.logger.name):
            with pytest.raises(pe.NotEnoughSpaceError) as raised:
                run(fake)
        # The old cache here has no stamp, so a retry is asked for the whole cache.
        assert _CACHE_4K > _GATE_4K - 4096
        assert raised.value.shortages[0][1:] == (pe.win_plain_path(leaf), pe._MIB, _CACHE_4K)
        assert (leaf / "old-cache-sentinel").exists()
        if where == "another drive":
            assert Path(fake.calls[0][2]).parent == systemp
            assert raised.value.shortages[0][0] == "D:"
        else:
            assert "Could not measure the drive of the working folder" in caplog.text

    @pytest.mark.parametrize("attribute, refused", [
        (0x00400000, True),    # FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
        (0x00040000, True),    # FILE_ATTRIBUTE_RECALL_ON_OPEN
        (0x00001000, True),    # FILE_ATTRIBUTE_OFFLINE
        (0x00080000, False),   # FILE_ATTRIBUTE_PINNED: always kept on this PC
    ], ids=["recall on data access", "recall on open", "offline", "pinned"])
    def test_the_gate_counts_no_room_for_online_only_files(
        self, setup, monkeypatch, attribute, refused
    ):
        """A OneDrive online-only file is listed with its full size but takes
        nothing on this PC, so wiping it frees nothing here. The 1 MiB file
        that makes room in test_the_gate_counts_the_old_cache_as_room is
        online-only now: the gate refuses and the old cache is kept, rather
        than wiped before a copy that runs out of space. A pinned file is on
        this PC and still counts."""
        leaf, run = setup
        big = leaf / "raw" / "libs" / "big.bin"
        big.write_bytes(b"\0" * (1 << 20))
        filled = []
        _disk_space(monkeypatch, lambda folder: _GATE_4K - (1 << 19) if filled else _PLENTY)

        def fill_and_list(run_dir):
            filled.append(True)
            _listed_with(monkeypatch, big, attribute)

        fake = _FakeTools(during_unforge=fill_and_list)
        if refused:
            with pytest.raises(pe.NotEnoughSpaceError):
                run(fake)
            assert big.exists() and (leaf / "old-cache-sentinel").exists()
        else:
            assert run(fake) is True
            assert not big.exists()

    @pytest.mark.parametrize("old_cache_bytes, passes", [(1 << 20, True), (0, False)],
                             ids=["old cache makes room", "too small to"])
    def test_the_gate_counts_the_old_cache_as_room(
        self, setup, monkeypatch, old_cache_bytes, passes
    ):
        """The wipe frees the whole old cache (unstamped too), so the check
        before it counts that as room. 512 KiB short: the 1 MiB file covers
        it, the 3-byte sentinel alone does not."""
        leaf, run = setup
        if old_cache_bytes:
            (leaf / "raw" / "libs" / "big.bin").write_bytes(b"\0" * old_cache_bytes)
        filled = []
        _disk_space(monkeypatch, lambda folder: _GATE_4K - (1 << 19) if filled else _PLENTY)
        fake = _FakeTools(during_unforge=lambda run_dir: filled.append(True))
        if passes:
            assert run(fake) is True
            assert not (leaf / "raw" / "libs" / "big.bin").exists()
        else:
            with pytest.raises(pe.NotEnoughSpaceError):
                run(fake)
            assert (leaf / "old-cache-sentinel").exists()

    def test_the_gate_logs_what_unforge_really_wrote(self, setup, caplog):
        """The line that checks the constants against a real run: _FakeTools
        writes one 4-byte file per keep subtree, one the cache does not take
        and a 3-byte dcb."""
        _leaf, run = setup
        with caplog.at_level(logging.INFO, logger=pe.logger.name):
            run(_FakeTools())
        kept = len(pe.DATAFORGE_KEEP_SUBPATHS)
        line = next(r.getMessage() for r in caplog.records
                    if r.getMessage().startswith("DataForge run wrote"))
        assert f"wrote {kept + 2} files, {(kept + 1) * 4 + 3} bytes." in line
        assert f"The new cache is {kept} files, {kept * 4} bytes, about {_GATE_4K:,} on" in line

    @pytest.mark.parametrize("broken", ["walk", "free space", "volume", "drive gone"])
    def test_a_gate_that_cannot_measure_lets_the_run_go_on(
        self, setup, monkeypatch, caplog, broken
    ):
        """Best effort before the wipe too: a walk or a probe that fails, or
        a cache drive with no folder above the cache left to measure, is
        logged and the run goes on."""
        leaf, run = setup
        failing = []
        if broken == "walk":
            def walk(*args, **kwargs):
                raise PermissionError("access denied")
                yield   # a generator, as the real one is

            fake = _FakeTools(during_unforge=lambda run_dir: monkeypatch.setattr(
                pe, "_walk_files", walk))
        elif broken == "drive gone":
            fake = _FakeTools(during_unforge=lambda run_dir: monkeypatch.setattr(
                pe, "_nearest_existing_folder", lambda path: None))
        else:
            stub_usage, stub_measure = shutil.disk_usage, pe._measure_volume

            def usage(path):
                if failing and broken == "free space":
                    raise PermissionError("access denied")
                return stub_usage(path)

            def measure(folder):
                if failing and broken == "volume":
                    raise OSError("the device is not ready")
                return stub_measure(folder)

            monkeypatch.setattr(shutil, "disk_usage", usage)
            monkeypatch.setattr(pe, "_measure_volume", measure)
            fake = _FakeTools(during_unforge=lambda run_dir: failing.append(True))
        with caplog.at_level(logging.WARNING, logger=pe.logger.name):
            assert run(fake) is True
        assert "Could not check the space for the new DataForge cache" in caplog.text
        if broken == "drive gone":
            assert "no folder above it exists" in caplog.text
        assert (leaf / pe.P4K_SIZE_STAMP).exists()

    @pytest.mark.parametrize("winerror", [39, 112, 1295])
    def test_a_full_drive_during_the_copy_says_the_cache_is_incomplete(
        self, setup, monkeypatch, english_ui, winerror
    ):
        """ERROR_HANDLE_DISK_FULL, ERROR_DISK_FULL, ERROR_DISK_QUOTA_EXCEEDED.
        copytree folds a per-file OSError into shutil.Error (errno None) and
        copies on, and Python maps 39 and 1295 to EINVAL, so the copy has to
        catch these itself, and stop at the first."""
        leaf, run = setup
        real_copy2 = shutil.copy2
        copies = []

        def copy2(src, dst, *args, **kwargs):
            copies.append(src)
            if len(copies) == 2:
                raise OSError(0, "There is not enough space on the disk", str(dst), winerror)
            return real_copy2(src, dst, *args, **kwargs)

        monkeypatch.setattr(shutil, "copy2", copy2)
        fake = _FakeTools()
        with pytest.raises(pe.NotEnoughSpaceError) as raised:
            run(fake)
        assert len(copies) == 2
        assert pe.win_plain_path(leaf) in str(raised.value)
        assert "incomplete" in str(raised.value)
        assert not (leaf / pe.P4K_MTIME_STAMP).exists() and not (leaf / pe.P4K_SIZE_STAMP).exists()
        assert not Path(fake.calls[0][2]).exists()

    def test_a_full_drive_while_stamping_says_the_cache_is_incomplete(self, setup, monkeypatch):
        leaf, run = setup
        real_write = Path.write_text

        def write_text(self, *args, **kwargs):
            if self.name == pe.P4K_SIZE_STAMP:
                raise OSError(errno.ENOSPC, "No space left on device", str(self))
            return real_write(self, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", write_text)
        with pytest.raises(pe.NotEnoughSpaceError):
            run(_FakeTools())
        # The mtime stamp alone reads as fresh, so it goes too, and startup
        # offers the re-extract the message promises.
        assert not (leaf / pe.P4K_SIZE_STAMP).exists()
        assert not (leaf / pe.P4K_MTIME_STAMP).exists()
        assert not pe._holds_complete_cache(leaf)

    def test_a_stamp_that_cannot_be_removed_still_says_incomplete(
        self, setup, monkeypatch, caplog
    ):
        """Removing the stamps is best effort: one that cannot go is logged,
        and the user still gets the "cache incomplete" message."""
        _leaf, run = setup
        real_write, real_unlink = Path.write_text, Path.unlink

        def write_text(self, *args, **kwargs):
            if self.name == pe.P4K_SIZE_STAMP:
                raise OSError(errno.ENOSPC, "No space left on device", str(self))
            return real_write(self, *args, **kwargs)

        def unlink(self, *args, **kwargs):
            if self.name == pe.P4K_MTIME_STAMP:
                raise PermissionError(errno.EACCES, "Access is denied", str(self))
            return real_unlink(self, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", write_text)
        monkeypatch.setattr(Path, "unlink", unlink)
        with caplog.at_level(logging.WARNING, logger=pe.logger.name):
            with pytest.raises(pe.NotEnoughSpaceError):
                run(_FakeTools())
        assert f"Could not remove {pe.P4K_MTIME_STAMP}" in caplog.text
        assert "that cache is incomplete" in caplog.text

    def test_another_copy_failure_is_not_called_a_full_drive(self, setup, monkeypatch):
        _leaf, run = setup

        def copy2(src, dst, *args, **kwargs):
            raise PermissionError(errno.EACCES, "Access is denied", str(dst))

        monkeypatch.setattr(shutil, "copy2", copy2)
        with pytest.raises(OSError) as raised:
            run(_FakeTools())
        assert raised.value.errno is None or raised.value.errno == errno.EACCES
