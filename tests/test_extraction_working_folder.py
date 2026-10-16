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
  during the move or a fallback copy. conftest's ``no_real_free_space`` keeps
  every other test here off the real drive's free space.
* Moving the kept files into the cache (#484): one rename per kept subtree
  beside the cache, a copy for a subtree whose rename is refused and for
  work in %TEMP%, told apart by file IDs (a rename keeps a file's ID).
* Making the working folder (#490): one ``os.mkdir`` per random name. A
  folder Windows refuses fails on the first try with
  ``WorkingFolderRefusedError`` (for global.ini only once %TEMP% refuses
  too), a name that is taken gets a new name a few times, and any other
  OSError behaves as before. ``tempfile.mkdtemp``, used before, retried a
  refusal up to 2**31 - 1 times on Windows on Python 3.11 (the release
  builds and CI), so every test that refuses a folder counts the calls
  through ``_counting_mkdir``, whose spin guard fails a retry loop instead
  of hanging the run.

Qt-free. Child processes run on the base interpreter (``sys._base_executable``)
because a venv's ``python.exe`` is a launcher that starts a second process,
and killing the launcher would leave that one running, which is the very thing
under test. Every child exits on its own within 30 s even if a kill fails.
"""
from __future__ import annotations

import contextlib
import errno
import json
import logging
import os
import re
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
# The four prefixes a run's working folder name starts with.
_RUN_PREFIXES = (pe.DATAFORGE_SCRATCH_PREFIX, pe.GLOBAL_INI_SCRATCH_PREFIX,
                 pe._DATAFORGE_TEMP_PREFIX, pe._GLOBAL_INI_TEMP_PREFIX)
# More os.mkdir calls than making one working folder may take. A loop that
# retries a refusal (tempfile.mkdtemp on Python 3.11 retries one up to
# 2**31 - 1 times on Windows, #490) is stopped here with an error the test
# reports, instead of hanging the run for a day and a half.
_SPIN_GUARD_CALLS = 100
# The well-known SID of Everyone. The account name is translated on
# non-English Windows, the SID never is.
_EVERYONE_SID = "*S-1-1-0"


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


class _StillRetrying(Exception):
    """A fake os.mkdir called more than _SPIN_GUARD_CALLS times. Not an
    OSError, so no folder creation loop can catch it and carry on."""


def _counting_mkdir(monkeypatch, refuse=None) -> list[Path]:
    """Patch os.mkdir with one that records each run folder it is asked for
    (a name with one of _RUN_PREFIXES), in order. *refuse(folder)* returns
    the OSError to raise for that folder, or None to make it for real.

    ``pe.os`` is the os module itself, so this also sees the calls
    tempfile.mkdtemp makes, should the folder ever be made with it again.
    Other folders (Path.mkdir making the parent) are made, not recorded."""
    calls = []
    real_mkdir = os.mkdir

    def mkdir(path, *args, **kwargs):
        folder = Path(path)
        if folder.name.startswith(_RUN_PREFIXES):
            calls.append(folder)
            if len(calls) > _SPIN_GUARD_CALLS:
                raise _StillRetrying(f"os.mkdir asked {len(calls)} times")
            error = refuse(folder) if refuse is not None else None
            if error is not None:
                raise error
        return real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(pe.os, "mkdir", mkdir)
    return calls


def _refused_in(*parents):
    """A *refuse* for _counting_mkdir: Access denied (WinError 5, which
    Python raises as PermissionError) for a folder in any of *parents*."""
    refused = {pe.win_plain_path(p) for p in parents}

    def refuse(folder):
        if pe.win_plain_path(folder.parent) in refused:
            return PermissionError(errno.EACCES, "Access is denied", str(folder))
        return None

    return refuse


# Windows' own reason for a write-protected drive, WinError 19.
_WRITE_PROTECTED = "The media is write protected"


def _write_protected_in(*parents):
    """A *refuse* for _counting_mkdir: a write-protected drive (WinError 19,
    which Python also raises as PermissionError, although nothing was
    refused) for a folder in any of *parents*."""
    plain = {pe.win_plain_path(p) for p in parents}

    def refuse(folder):
        if pe.win_plain_path(folder.parent) in plain:
            return OSError(None, _WRITE_PROTECTED, str(folder), 19)
        return None

    return refuse


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


def _refuse_moves(monkeypatch, winerror: int, only=(), times=None):
    """pe._rename_tree fails as Windows fails it (17 another drive, 5 or 32 a
    held file, 39, 112 or 1295 a full drive) for the keep subtrees in *only*,
    or for all of them. With *times*, each fails that many times and then
    goes through (a holder that lets go). Returns the subtrees refused, one
    entry per refusal."""
    real, refused = pe._rename_tree, []

    def rename(src, dst):
        rel = pe.win_plain_path(src).replace(os.sep, "/").partition("/foundry/records/")[2]
        if (not only or rel in only) and (times is None or refused.count(rel) < times):
            refused.append(rel)
            raise OSError(0, "refused by the test", str(src), winerror, str(dst))
        return real(src, dst)

    monkeypatch.setattr(pe, "_rename_tree", rename)
    return refused


def _record_renames(monkeypatch) -> list[str]:
    """Pass every pe._rename_tree call through, and return the plain sources
    it was called with."""
    real, calls = pe._rename_tree, []

    def rename(src, dst):
        calls.append(pe.win_plain_path(src))
        return real(src, dst)

    monkeypatch.setattr(pe, "_rename_tree", rename)
    return calls


def _never_copy(src, dst, *args, **kwargs):
    """shutil.copy2 for a test where nothing may be copied."""
    raise AssertionError(f"{src} was copied")


def _ids(records: Path) -> dict[str, int]:
    """{path under *records*: NTFS file ID}. A rename keeps a file's ID and a
    copy makes a new one, so this tells a moved cache from a copied one with
    no mocks."""
    root = Path(win_long_path(records))
    return {p.relative_to(root).as_posix(): p.stat().st_ino
            for p in root.rglob("*") if p.is_file()}


def _tree(records: Path) -> dict[str, tuple[bytes, int]]:
    """{path under *records*: (bytes, mtime_ns)} for comparing two caches."""
    root = Path(win_long_path(records))
    return {p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in root.rglob("*") if p.is_file()}


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

# Files _FakeTools(siblings=True) writes beside the kept subtrees, in parents
# the cache keeps only part of (#484): a folder beside a kept one, a file
# directly in a partly kept parent, and the same deeper down.
_SIBLINGS = ("entities/other/x.xml", "entities/loose.xml",
             "crafting/blueprints/other/x.xml", "reputation/rewards/other/x.xml")


def _working_records(run_dir: Path) -> Path:
    """Where _FakeTools' unforge writes the records in the working folder."""
    return run_dir / "Data" / "libs" / "foundry" / "records"


class _FakeTools:
    """Stands in for _run_tool: unp4k writes Data/Game2.dcb into its working
    folder, unforge writes libs/foundry/records next to the dcb (every keep
    subtree plus one the cache must not keep). Opt-in (#484): *siblings*
    adds _SIBLINGS, *fixed_ns* gives every file it writes that mtime (a
    multiple of 100, NTFS's resolution), and ``records=False`` writes a
    libs/ folder without foundry/records."""

    def __init__(self, *, unforge_rc: int = 0, deep_name: str | None = None, during_unforge=None,
                 siblings: bool = False, fixed_ns: int | None = None, records: bool = True):
        self.calls: list[tuple[str, list, str]] = []
        self.unforge_rc = unforge_rc
        self.deep_name = deep_name
        self.during_unforge = during_unforge
        self.siblings = siblings
        self.fixed_ns = fixed_ns
        self.records = records

    def _write(self, path: Path, data: bytes) -> None:
        path = Path(win_long_path(path))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if self.fixed_ns is not None:
            os.utime(path, ns=(self.fixed_ns, self.fixed_ns))

    def __call__(self, args, *, cwd, timeout, should_cancel=None):
        tool = Path(args[0]).stem
        self.calls.append((tool, list(args), cwd))
        if tool == "unp4k":
            (Path(cwd) / "Data").mkdir()
            self._write(Path(cwd) / "Data" / "Game2.dcb", b"dcb")
        else:
            libs = Path(args[1]).parent / "libs"
            records = libs / "foundry" / "records"
            if not self.records:
                self._write(libs / "other" / "x.xml", b"<x/>")
            else:
                for rel in pe.DATAFORGE_KEEP_SUBPATHS + ("unused/elsewhere",):
                    self._write(records / rel / "x.xml", b"<x/>")
            if self.records and self.siblings:
                for rel in _SIBLINGS:
                    self._write(records / rel, b"<sibling/>")
            if self.records and self.deep_name:
                deep = records / "entities" / "scitem" / self.deep_name
                self._write(deep / (self.deep_name + ".xml"), b"<deep/>")
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


def _stamp_old_cache(leaf: Path) -> Path:
    """Make setup's old cache complete and current: a kept file and both
    stamps matching the fake Data.p4k, so it reads as fresh. A test that
    keeps the old cache then shows its stamps stayed too, which an
    unstamped one cannot. Returns the Data.p4k."""
    p4k = leaf.parents[3] / "tools" / "Data.p4k"
    kept = leaf / "raw" / "libs" / "foundry" / "records" / "entities" / "scitem"
    kept.mkdir(parents=True)
    (kept / "x.xml").write_text("<x/>", encoding="utf-8")
    (leaf / pe.P4K_MTIME_STAMP).write_text(str(p4k.stat().st_mtime))
    (leaf / pe.P4K_SIZE_STAMP).write_text(str(p4k.stat().st_size))
    assert pe.dataforge_cache_is_fresh(p4k, leaf)
    return p4k


class _Killed(BaseException):
    """A hard stop (a crash, a kill) between two steps, which no
    ``except OSError`` catches."""


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
        """The old cache is kept stamped, so it still reads as fresh."""
        leaf, run = setup
        p4k = _stamp_old_cache(leaf)
        fake = _FakeTools(unforge_rc=1)
        with pytest.raises(RuntimeError, match="unforge.exe failed"):
            run(fake)
        assert (leaf / "old-cache-sentinel").exists()
        assert pe.dataforge_cache_is_fresh(p4k, leaf)
        assert not Path(fake.calls[0][2]).exists()

    def test_a_stop_before_the_wipe_keeps_the_old_cache(self, setup):
        """The old cache is kept stamped, so it still reads as fresh."""
        leaf, run = setup
        p4k = _stamp_old_cache(leaf)
        stopped = []
        fake = _FakeTools(during_unforge=lambda run_dir: stopped.append(True))
        with pytest.raises(pe.ExtractionCancelled):
            run(fake, should_cancel=lambda: bool(stopped))
        assert (leaf / "old-cache-sentinel").exists()
        assert pe.dataforge_cache_is_fresh(p4k, leaf)
        assert not Path(fake.calls[0][2]).exists()

    def test_a_stop_after_the_check_before_the_wipe_keeps_the_old_cache(
        self, setup, monkeypatch
    ):
        """The stop check just before the wipe on its own (#471): a stop that
        arrives once the free-space check has walked everything still keeps
        the old cache, stamps and all (they go only after this point), and
        nothing is moved."""
        leaf, run = setup
        p4k = _stamp_old_cache(leaf)
        stopped = []
        real_check = pe._require_room_for_new_cache

        def check_then_stop(*args, **kwargs):
            real_check(*args, **kwargs)
            stopped.append(True)

        monkeypatch.setattr(pe, "_require_room_for_new_cache", check_then_stop)
        renames = _record_renames(monkeypatch)
        fake = _FakeTools()
        with pytest.raises(pe.ExtractionCancelled,
                           match="stopped before the previous cache was replaced"):
            run(fake, should_cancel=lambda: bool(stopped))
        assert (leaf / "old-cache-sentinel").exists()
        assert pe.dataforge_cache_is_fresh(p4k, leaf)
        assert renames == []
        assert not Path(fake.calls[0][2]).exists()

    @pytest.mark.parametrize("how", ["moved", "copied"])
    def test_a_stop_while_the_cache_is_filled_finishes_it_and_skips_the_manifest(
        self, setup, monkeypatch, how
    ):
        """Past the wipe a stop never leaves the cache half filled: nothing
        checks for one during the renames (#484) or a fallback copy, so the
        cache is written and stamped, and only the manifest is skipped."""
        leaf, run = setup
        stopped = []
        if how == "moved":
            real_rename = pe._rename_tree

            def rename_and_stop(src, dst):
                stopped.append(True)
                return real_rename(src, dst)

            monkeypatch.setattr(pe, "_rename_tree", rename_and_stop)
        else:
            _refuse_moves(monkeypatch, 17)
            real_copy2 = shutil.copy2

            def copy2_and_stop(src, dst, *args, **kwargs):
                stopped.append(True)
                return real_copy2(src, dst, *args, **kwargs)

            monkeypatch.setattr(shutil, "copy2", copy2_and_stop)
        fake = _FakeTools()
        with pytest.raises(pe.ExtractionCancelled, match="stopped once the new cache was written"):
            run(fake, should_cancel=lambda: bool(stopped))
        assert stopped
        assert (leaf / pe.P4K_MTIME_STAMP).exists() and (leaf / pe.P4K_SIZE_STAMP).exists()
        records = leaf / "raw" / "libs" / "foundry" / "records"
        assert [rel for rel in pe.DATAFORGE_KEEP_SUBPATHS
                if not (records / rel / "x.xml").is_file()] == []
        assert not (leaf / "raw" / "libs" / MANIFEST_FILE).exists()
        assert not Path(fake.calls[0][2]).exists()

    def test_unforge_output_without_its_records_folder_keeps_the_old_cache(self, setup, caplog):
        """unforge wrote libs/ but no foundry/records (#484, gap A). That is
        found before the check before the wipe, so the old cache is kept
        instead of being wiped for an empty one that reads as never
        extracted."""
        leaf, run = setup
        p4k = _stamp_old_cache(leaf)
        fake = _FakeTools(records=False)
        with caplog.at_level(logging.INFO, logger=pe.logger.name):
            with pytest.raises(FileNotFoundError, match="foundry/records"):
                run(fake)
        assert (leaf / "old-cache-sentinel").exists() and (leaf / "raw" / "libs").is_dir()
        assert pe.dataforge_cache_is_fresh(p4k, leaf)
        assert "DataForge run wrote" not in caplog.text
        assert not Path(fake.calls[0][2]).exists()

    def test_unforge_output_with_none_of_the_kept_subtrees_keeps_the_old_cache(
        self, setup, caplog
    ):
        """unforge wrote foundry/records but none of the subtrees the cache
        keeps (a layout change). The run used to wipe the old cache and
        stamp an empty one, which never reads as fresh, so startup asked on
        every launch and each re-extract wiped again. It now fails before
        the check before the wipe, as a missing records folder does."""
        leaf, run = setup
        p4k = _stamp_old_cache(leaf)

        def drop_the_kept_subtrees(run_dir: Path):
            for rel in pe.DATAFORGE_KEEP_SUBPATHS:
                shutil.rmtree(win_long_path(_working_records(run_dir) / rel))

        fake = _FakeTools(during_unforge=drop_the_kept_subtrees)
        with caplog.at_level(logging.INFO, logger=pe.logger.name):
            with pytest.raises(FileNotFoundError, match="none of the"):
                run(fake)
        assert (leaf / "old-cache-sentinel").exists()
        assert pe.dataforge_cache_is_fresh(p4k, leaf)
        assert "DataForge run wrote" not in caplog.text
        assert not Path(fake.calls[0][2]).exists()

    def test_a_records_file_instead_of_a_folder_keeps_the_old_cache(self, setup):
        """unforge's records must be a folder: a file there is no layout the
        cache keeps."""
        leaf, run = setup
        p4k = _stamp_old_cache(leaf)

        def records_as_file(run_dir: Path):
            target = _working_records(run_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("not a folder", encoding="utf-8")

        with pytest.raises(FileNotFoundError, match="foundry/records"):
            run(_FakeTools(records=False, during_unforge=records_as_file))
        assert (leaf / "old-cache-sentinel").exists()
        assert pe.dataforge_cache_is_fresh(p4k, leaf)

    def test_a_wipe_cut_short_leaves_no_stamp(self, setup, monkeypatch):
        """From Python 3.12.4 rmtree deletes the leaf's own files last, so a
        wipe that gave up part-way could leave both stamps on a partial
        cache, which reads as fresh while they match this Data.p4k (#484,
        gap B). The stamps go before the wipe."""
        leaf, run = setup
        p4k = leaf.parents[3] / "tools" / "Data.p4k"
        records = leaf / "raw" / "libs" / "foundry" / "records"
        for rel in ("entities/scitem", "contracts/contractgenerator"):
            (records / rel).mkdir(parents=True)
            (records / rel / "x.xml").write_text("<x/>", encoding="utf-8")
        (leaf / pe.P4K_MTIME_STAMP).write_text(str(p4k.stat().st_mtime))
        (leaf / pe.P4K_SIZE_STAMP).write_text(str(p4k.stat().st_size))
        assert pe.dataforge_cache_is_fresh(p4k, leaf)
        real_rmtree = pe.robust_rmtree

        def rmtree(path, attempts=6):
            if pe.win_plain_path(path) == pe.win_plain_path(leaf):
                shutil.rmtree(win_long_path(records / "entities"))
                raise PermissionError(errno.EACCES, "Access is denied", str(records / "contracts"))
            return real_rmtree(path, attempts)

        monkeypatch.setattr(pe, "robust_rmtree", rmtree)
        fake = _FakeTools()
        with pytest.raises(PermissionError):
            run(fake)
        assert not (leaf / pe.P4K_MTIME_STAMP).exists() and not (leaf / pe.P4K_SIZE_STAMP).exists()
        assert (records / "contracts" / "contractgenerator" / "x.xml").exists()
        assert not pe.dataforge_cache_is_fresh(p4k, leaf)
        assert not Path(fake.calls[0][2]).exists()

    def test_any_failure_on_the_stamps_leaves_neither_stamp(self, setup, monkeypatch):
        """A failure on the size stamp that is not a full drive used to leave
        the mtime stamp, which alone reads as fresh, behind a raw error
        (#484, gap E). Neither stays, whatever the failure."""
        leaf, run = setup
        real_write = Path.write_text

        def write_text(self, *args, **kwargs):
            if self.name == pe.P4K_SIZE_STAMP:
                raise PermissionError(errno.EACCES, "Access is denied", str(self))
            return real_write(self, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", write_text)
        with pytest.raises(PermissionError):
            run(_FakeTools())
        assert not (leaf / pe.P4K_MTIME_STAMP).exists() and not (leaf / pe.P4K_SIZE_STAMP).exists()
        assert not pe._holds_complete_cache(leaf)

    def test_a_kill_between_the_two_stamp_removals_leaves_no_mtime_stamp(
        self, setup, monkeypatch
    ):
        """.p4k_mtime goes first: a kill after the first removal must never
        leave the stamp that alone reads as fresh."""
        leaf, run = setup
        _stamp_old_cache(leaf)
        real_unlink = Path.unlink
        stamps = []

        def unlink(self, *args, **kwargs):
            if self.name in (pe.P4K_MTIME_STAMP, pe.P4K_SIZE_STAMP):
                stamps.append(self.name)
                if len(stamps) == 2:
                    raise _Killed()
            return real_unlink(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", unlink)
        with pytest.raises(_Killed):
            run(_FakeTools())
        assert stamps == [pe.P4K_MTIME_STAMP, pe.P4K_SIZE_STAMP]
        assert not (leaf / pe.P4K_MTIME_STAMP).exists()

    @pytest.mark.parametrize("error, raised_as", [
        (PermissionError(errno.EACCES, "Access is denied"), pe.WorkingFolderRefusedError),
        (FileNotFoundError(errno.ENOENT, "The system cannot find the path specified"),
         FileNotFoundError),
    ], ids=["refused", "drive gone"])
    def test_no_working_folder_means_no_tool_runs_and_the_cache_stays(
        self, setup, monkeypatch, error, raised_as
    ):
        leaf, run = setup
        calls = _counting_mkdir(monkeypatch, lambda folder: error)
        fake = _FakeTools()
        with pytest.raises(raised_as):
            run(fake)
        assert len(calls) == 1
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
        after a minute of unforge. A refusal there is the user's box (#490),
        naming the folder."""
        leaf, run = setup
        calls = _counting_mkdir(monkeypatch, _refused_in(leaf.parent))
        fake = _FakeTools()
        with pytest.raises(pe.WorkingFolderRefusedError) as raised:
            run(fake)
        assert len(calls) == 1
        assert raised.value.folder == str(leaf.parent)
        assert fake.calls == []
        assert (leaf / "old-cache-sentinel").exists()
        assert list(systemp.iterdir()) == []

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

    @pytest.mark.parametrize("how", ["moved", "copied"])
    def test_a_deep_cache_still_fills_every_keep_path(self, root, monkeypatch, how):
        """At the depth cap the deepest keep file passes 260 characters in the
        working folder. The rename and the fallback copy both reach it
        through the long-path prefix, so it is not skipped without a word.
        Moved, the deep file keeps its ID; copied, it gets a new one."""
        extra = 1 + len(pe.DATAFORGE_SCRATCH_PREFIX) + pe._MKDTEMP_RANDOM_CHARS
        beside = _pad_to(root / "deep", pe._MAX_SCRATCH_CHARS - extra)
        leaf = beside / "dataforge"
        tools = root / "tools"
        tools.mkdir()
        for name in ("unp4k.exe", "unforge.exe", "Data.p4k"):
            (tools / name).write_bytes(b"x")
        deep_rel = Path("entities") / "scitem" / ("d" * 60) / ("d" * 60 + ".xml")
        written = []
        fake = _FakeTools(deep_name="d" * 60, during_unforge=lambda run_dir: written.append(
            os.stat(win_long_path(_working_records(run_dir) / deep_rel)).st_ino))
        monkeypatch.setattr(pe, "_run_tool", fake)
        if how == "copied":
            _refuse_moves(monkeypatch, 17)

        pe.extract_dataforge(tools / "Data.p4k", tools / "unp4k.exe", tools / "unforge.exe", leaf)

        run_dir = Path(fake.calls[0][2])
        assert run_dir.parent == beside and len(str(run_dir)) == pe._MAX_SCRATCH_CHARS
        assert len(str(_working_records(run_dir) / deep_rel)) > 260
        records = leaf / "raw" / "libs" / "foundry" / "records"
        deep_id = os.stat(win_long_path(records / deep_rel)).st_ino
        assert (deep_id == written[0]) == (how == "moved")
        # Every keep subtree, including the deepest one (~261 characters in
        # the working folder at this depth), reached the cache.
        missing = [rel for rel in pe.DATAFORGE_KEEP_SUBPATHS
                   if not Path(win_long_path(records / rel / "x.xml")).exists()]
        assert missing == []

    def test_the_caching_step_reads_unforge_output_through_the_long_path_prefix(
        self, setup, monkeypatch, root
    ):
        """A plain exists() on a keep path past 260 characters returns False
        on a PC without Windows long paths turned on (the default), and the
        caching step would skip that subtree without a word. Checked
        directly, since a developer machine with long paths enabled can't
        show the failure. The rename is checked on its own as well (#484):
        in a run every path it gets is prefixed already, so only a direct
        call on plain paths shows _rename_tree adding the prefix itself."""
        leaf, run = setup
        seen = []
        real_cache = pe._cache_filtered_records

        def spy(src, dst, *, move):
            seen.append((str(src), str(dst)))
            return real_cache(src, dst, move=move)

        monkeypatch.setattr(pe, "_cache_filtered_records", spy)
        run(_FakeTools())
        assert len(seen) == 1 and all(path.startswith("\\\\?\\") for path in seen[0])

        renames = []
        real_rename = os.rename

        def rename(src, dst, *args, **kwargs):
            renames.append((src, dst))
            return real_rename(src, dst, *args, **kwargs)

        monkeypatch.setattr(pe.os, "rename", rename)
        source, target = root / "rename-from", root / "rename-to"
        source.mkdir()
        pe._rename_tree(source, target)
        assert renames == [(win_long_path(source), win_long_path(target))]
        assert target.is_dir() and not source.exists()


# ── moving the kept files into the cache (#484) ─────────────────────────────

class TestMovingTheKeptFiles:
    """Beside the cache each kept subtree is renamed into place instead of
    copied file by file, and a subtree whose rename is refused is copied.
    File IDs tell the two apart (a rename keeps a file's ID, a copy makes a
    new one), read with os.stat on both sides: a DirEntry's st_ino is 0 on
    Windows, which would make a copy pass for a move."""

    _HELD = "contracts/contracttemplates"

    @staticmethod
    def _cache(leaf: Path) -> Path:
        return leaf / "raw" / "libs" / "foundry" / "records"

    @staticmethod
    def _kept_files() -> set[str]:
        return {rel + "/x.xml" for rel in pe.DATAFORGE_KEEP_SUBPATHS}

    @staticmethod
    def _fallbacks(caplog) -> list[str]:
        return [r.getMessage() for r in caplog.records
                if r.levelno == logging.INFO and r.getMessage().startswith("Could not move ")]

    def test_beside_the_cache_every_keep_subtree_is_moved_not_copied(
        self, setup, monkeypatch, caplog
    ):
        """Every cached file has the ID unforge's file had, copy2 never runs,
        and the summary line gives the counts and the fill time, with the
        cleanup's time on its own line. setup's old cache has no stamps, as
        on a first run, and their absence is not logged as a failure to
        remove them."""
        leaf, run = setup
        written = {}
        fake = _FakeTools(during_unforge=lambda run_dir: written.update(
            _ids(_working_records(run_dir))))
        monkeypatch.setattr(shutil, "copy2", _never_copy)
        with caplog.at_level(logging.INFO, logger=pe.logger.name):
            assert run(fake) is True
        assert _ids(self._cache(leaf)) == {path: written[path] for path in self._kept_files()}
        kept = len(pe.DATAFORGE_KEEP_SUBPATHS)
        assert f"DataForge cache written: {kept}/{kept} keep-subpaths in " in caplog.text
        assert f" s, {kept} moved and 0 copied (0 not present in this build)" in caplog.text
        assert "Deleting the DataForge working folder took " in caplog.text
        assert self._fallbacks(caplog) == []
        assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == []
        assert (leaf / pe.P4K_MTIME_STAMP).exists() and (leaf / pe.P4K_SIZE_STAMP).exists()
        assert (leaf / "raw" / "libs" / MANIFEST_FILE).exists()
        assert not Path(fake.calls[0][2]).exists()

    def test_each_retry_waits_its_delay_then_the_refusal_comes_back(self, tmp_path, monkeypatch):
        """A held subtree is tried again after each delay, not four times in
        a row: without the waits the retry never outlasts a scanner's
        handle."""
        sleeps, tries = [], []

        def rename(src, dst):
            tries.append(src)
            raise OSError(0, "held", str(src), 32, str(dst))

        monkeypatch.setattr(pe, "_rename_tree", rename)
        monkeypatch.setattr(pe, "_MOVE_RETRY_DELAYS", (0.001, 0.002, 0.003))
        monkeypatch.setattr(pe.time, "sleep", sleeps.append)
        refused = pe._move_tree(tmp_path / "a", tmp_path / "b")
        assert refused.winerror == 32
        assert sleeps == [0.001, 0.002, 0.003]
        assert len(tries) == 4

    def test_the_shipped_retry_schedule_is_short_but_real(self):
        """The app does retry a held subtree, and fourteen held subtrees
        still finish well inside the 180 s close wait."""
        delays = pe._MOVE_RETRY_DELAYS
        assert delays and all(delay > 0 for delay in delays)
        assert sum(delays) * len(pe.DATAFORGE_KEEP_SUBPATHS) <= 30

    def test_the_fill_and_cleanup_times_are_measured(self, setup, monkeypatch, caplog):
        """The two times in the log are real measurements, not a fixed 0.0."""
        _leaf, run = setup
        real_cache, real_close = pe._cache_filtered_records, pe._close_scratch

        def slow_cache(*args, **kwargs):
            time.sleep(0.25)
            return real_cache(*args, **kwargs)

        def slow_close(*args, **kwargs):
            time.sleep(0.25)
            return real_close(*args, **kwargs)

        monkeypatch.setattr(pe, "_cache_filtered_records", slow_cache)
        monkeypatch.setattr(pe, "_close_scratch", slow_close)
        with caplog.at_level(logging.INFO, logger=pe.logger.name):
            assert run(_FakeTools()) is True
        fill = float(re.search(r"keep-subpaths in (\d+\.\d) s,", caplog.text).group(1))
        cleanup = float(re.search(r"working folder took (\d+\.\d) s", caplog.text).group(1))
        assert fill >= 0.1 and cleanup >= 0.1

    def test_unkept_siblings_stay_behind_and_go_with_the_working_folder(
        self, setup, monkeypatch
    ):
        """Only the kept subtrees are renamed, never a parent such as
        entities: what sits beside them is still in the working folder just
        before it is deleted, and never reaches the cache."""
        leaf, run = setup
        left = []
        real_close = pe._close_scratch

        def close(run_dir, marker):
            records = _working_records(Path(run_dir))
            left.extend(rel for rel in _SIBLINGS
                        if Path(win_long_path(records / rel)).is_file())
            return real_close(run_dir, marker)

        monkeypatch.setattr(pe, "_close_scratch", close)
        fake = _FakeTools(siblings=True)
        assert run(fake) is True
        assert left == list(_SIBLINGS)
        assert set(_ids(self._cache(leaf))) == self._kept_files()
        assert not Path(fake.calls[0][2]).exists()

    @pytest.mark.parametrize("winerror, refusals", [(17, 1), (5, 4), (32, 4)],
                             ids=["17 another drive", "5 access denied", "32 sharing violation"])
    def test_a_subtree_that_will_not_move_is_copied_and_the_rest_moved(
        self, setup, monkeypatch, caplog, winerror, refusals
    ):
        """A refused rename leaves the subtree whole where unforge wrote it,
        so it is copied, and the rest are still moved. A held file (5 or 32)
        is tried again after each retry delay first; another drive (17) is
        not, since waiting cannot help it."""
        leaf, run = setup
        monkeypatch.setattr(pe, "_MOVE_RETRY_DELAYS", (0, 0, 0))
        refused = _refuse_moves(monkeypatch, winerror, only=(self._HELD,))
        written = {}
        fake = _FakeTools(during_unforge=lambda run_dir: written.update(
            _ids(_working_records(run_dir))))
        with caplog.at_level(logging.INFO, logger=pe.logger.name):
            assert run(fake) is True
        cached = _ids(self._cache(leaf))
        held = self._HELD + "/x.xml"
        assert set(cached) == self._kept_files()
        assert cached[held] != written[held]
        assert (self._cache(leaf) / held).read_bytes() == b"<x/>"
        assert {path: cached[path] for path in cached if path != held} == {
            path: written[path] for path in cached if path != held}
        assert refused == [self._HELD] * refusals
        fallbacks = self._fallbacks(caplog)
        assert len(fallbacks) == 1
        assert fallbacks[0].startswith(f"Could not move {self._HELD} into the DataForge cache (")
        kept = len(pe.DATAFORGE_KEEP_SUBPATHS)
        assert f" s, {kept - 1} moved and 1 copied" in caplog.text
        assert (leaf / pe.P4K_SIZE_STAMP).exists()
        assert (leaf / "raw" / "libs" / MANIFEST_FILE).exists()

    def test_a_subtree_held_by_another_program_is_retried_then_copied(
        self, setup, monkeypatch, caplog
    ):
        """No fake refusal: a file under one subtree is held open, as
        antivirus or the search indexer would hold it, so Windows refuses
        that folder's rename. After the retries it is copied (a copy reads a
        file held open for reading) and the rest are moved."""
        leaf, run = setup
        monkeypatch.setattr(pe, "_MOVE_RETRY_DELAYS", (0, 0, 0))
        written, handles = {}, []

        def write_and_hold(run_dir):
            records = _working_records(run_dir)
            written.update(_ids(records))
            handles.append(open(win_long_path(records / self._HELD / "x.xml"), "rb"))

        real_close = pe._close_scratch

        def let_go_then_close(run_dir, marker):
            for handle in handles:
                handle.close()
            return real_close(run_dir, marker)

        monkeypatch.setattr(pe, "_close_scratch", let_go_then_close)
        try:
            with caplog.at_level(logging.INFO, logger=pe.logger.name):
                assert run(_FakeTools(during_unforge=write_and_hold)) is True
        finally:
            for handle in handles:
                handle.close()
        cached = _ids(self._cache(leaf))
        held = self._HELD + "/x.xml"
        assert set(cached) == self._kept_files()
        assert cached[held] != written[held]
        assert (self._cache(leaf) / held).read_bytes() == b"<x/>"
        assert {path: cached[path] for path in cached if path != held} == {
            path: written[path] for path in cached if path != held}
        fallbacks = self._fallbacks(caplog)
        assert len(fallbacks) == 1 and fallbacks[0].startswith(f"Could not move {self._HELD} ")
        assert "[WinError 5]" in fallbacks[0]
        kept = len(pe.DATAFORGE_KEEP_SUBPATHS)
        assert f" s, {kept - 1} moved and 1 copied" in caplog.text
        assert (leaf / pe.P4K_SIZE_STAMP).exists()
        assert (leaf / "raw" / "libs" / MANIFEST_FILE).exists()

    def test_a_subtree_let_go_during_the_retries_is_moved(self, setup, monkeypatch, caplog):
        """A holder that lets go within the retries costs nothing: the
        subtree is still moved, and nothing says it was copied."""
        leaf, run = setup
        monkeypatch.setattr(pe, "_MOVE_RETRY_DELAYS", (0, 0, 0))
        refused = _refuse_moves(monkeypatch, 32, only=(self._HELD,), times=2)
        written = {}
        fake = _FakeTools(during_unforge=lambda run_dir: written.update(
            _ids(_working_records(run_dir))))
        with caplog.at_level(logging.INFO, logger=pe.logger.name):
            assert run(fake) is True
        held = self._HELD + "/x.xml"
        assert _ids(self._cache(leaf))[held] == written[held]
        assert refused == [self._HELD] * 2
        assert self._fallbacks(caplog) == []
        kept = len(pe.DATAFORGE_KEEP_SUBPATHS)
        assert f" s, {kept} moved and 0 copied" in caplog.text

    @pytest.mark.parametrize("winerror", [39, 112, 1295])
    def test_a_rename_that_finds_the_drive_full_says_the_cache_is_incomplete(
        self, setup, monkeypatch, english_ui, winerror
    ):
        """A copy needs more room than the rename did, so a full drive on a
        rename is neither retried nor copied: it is the "cache incomplete"
        message at once, with no stamp left."""
        leaf, run = setup
        monkeypatch.setattr(pe, "_MOVE_RETRY_DELAYS", (0, 0, 0))
        refused = _refuse_moves(monkeypatch, winerror, only=("entities/scitem",))
        monkeypatch.setattr(shutil, "copy2", _never_copy)
        fake = _FakeTools()
        with pytest.raises(pe.NotEnoughSpaceError) as raised:
            run(fake)
        assert "incomplete" in str(raised.value)
        assert pe.win_plain_path(leaf) in str(raised.value)
        assert refused == ["entities/scitem"]
        assert not (leaf / pe.P4K_MTIME_STAMP).exists() and not (leaf / pe.P4K_SIZE_STAMP).exists()
        assert not Path(fake.calls[0][2]).exists()

    def test_work_in_temp_is_copied_not_moved(self, setup, monkeypatch, systemp, caplog):
        """Moved files would keep %TEMP%'s permissions, and a move into
        OneDrive is untested, so work in %TEMP% is copied as before."""
        leaf, run = setup
        monkeypatch.setattr(pe, "is_onedrive_path", lambda path: True)
        renames = _record_renames(monkeypatch)
        written = {}
        fake = _FakeTools(during_unforge=lambda run_dir: written.update(
            _ids(_working_records(run_dir))))
        with caplog.at_level(logging.INFO, logger=pe.logger.name):
            assert run(fake) is True
        assert Path(fake.calls[0][2]).parent == systemp
        assert renames == []
        cached = _ids(self._cache(leaf))
        assert set(cached) == self._kept_files()
        assert [path for path in cached if cached[path] == written[path]] == []
        kept = len(pe.DATAFORGE_KEEP_SUBPATHS)
        assert f" s, 0 moved and {kept} copied" in caplog.text

    def test_a_moved_cache_and_a_copied_cache_are_the_same(self, setup, monkeypatch, caplog):
        """One run moves, a second copies every subtree: the two caches hold
        the same paths (in the same case), bytes and mtimes, and the same
        manifest. Compared as parsed JSON, since the manifest is filled in
        the order its hashes finish."""
        leaf, run = setup
        fixed_ns = 1_700_000_000 * 10**9
        manifest = leaf / "raw" / "libs" / MANIFEST_FILE
        kept = len(pe.DATAFORGE_KEEP_SUBPATHS)
        with caplog.at_level(logging.INFO, logger=pe.logger.name):
            assert run(_FakeTools(siblings=True, fixed_ns=fixed_ns)) is True
        assert f" s, {kept} moved and 0 copied" in caplog.text
        moved_tree = _tree(self._cache(leaf))
        moved_manifest = json.loads(manifest.read_text(encoding="utf-8"))
        assert set(moved_tree) == self._kept_files()
        caplog.clear()
        _refuse_moves(monkeypatch, 17)
        with caplog.at_level(logging.INFO, logger=pe.logger.name):
            assert run(_FakeTools(siblings=True, fixed_ns=fixed_ns)) is True
        assert f" s, 0 moved and {kept} copied" in caplog.text
        assert _tree(self._cache(leaf)) == moved_tree
        assert json.loads(manifest.read_text(encoding="utf-8")) == moved_manifest


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
{after}
print("unforge done")
"""

# _UNFORGE_SCRIPT's {after} for a run that checks the moved files' IDs
# (#484): each kept x.xml's ID, read with os.stat (a DirEntry's st_ino is 0
# on Windows), saved outside the working folder before the child exits.
_SAVE_IDS_SCRIPT = """\
import json
ids = {{}}
for rel in {keep!r}:
    path = "\\\\\\\\?\\\\" + os.path.join(records, *rel.split("/"), "x.xml")
    ids[rel] = os.stat(path).st_ino
with open({ids_file!r}, "w", encoding="utf-8") as f:
    json.dump(ids, f)
"""


def _real_tools(root: Path, *, slow_unforge: bool = False, slow_global_ini: bool = False,
                ids_file: Path | None = None):
    """A Data.p4k that is really an unp4k-like script, whose Game2.dcb is
    really an unforge-like script, both run by the base interpreter. With
    *ids_file*, unforge saves the kept files' IDs there."""
    pid_file = root / "tool.pid"
    before = (_write_pid_code(pid_file) + "time.sleep(30)\n") if slow_unforge else ""
    keep = list(pe.DATAFORGE_KEEP_SUBPATHS)
    after = _SAVE_IDS_SCRIPT.format(keep=keep, ids_file=str(ids_file)) if ids_file else ""
    dcb = _UNFORGE_SCRIPT.format(before=before, keep=keep, after=after)
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

    def test_a_full_run_moves_what_the_tool_wrote(self, root, caplog):
        """The unforge stand-in, a real child process, saves each kept file's
        ID before it exits. Each cached file keeps that ID, so it was moved
        after a real process wrote and closed it (#484). An antivirus that
        holds a just-closed file past the retries (a CI runner's) turns that
        subtree into a copy, which its INFO line then names."""
        ids_file = root / "ids.json"
        p4k, py, _pid = _real_tools(root, ids_file=ids_file)
        leaf = root / "cache" / "LIVE" / "cache" / "dataforge"
        with caplog.at_level(logging.INFO, logger=pe.logger.name):
            assert pe.extract_dataforge(p4k, py, py, leaf) is True
        written = json.loads(ids_file.read_text(encoding="utf-8"))
        assert sorted(written) == sorted(pe.DATAFORGE_KEEP_SUBPATHS)
        cached = _ids(leaf / "raw" / "libs" / "foundry" / "records")
        assert set(cached) == {rel + "/x.xml" for rel in written}
        copied = [rel for rel in written if cached[rel + "/x.xml"] != written[rel]]
        assert [rel for rel in copied
                if f"Could not move {rel} into the DataForge cache" not in caplog.text] == []
        summary = re.search(r" s, (\d+) moved and (\d+) copied", caplog.text)
        assert summary is not None
        moved = int(summary.group(1))
        assert moved >= 1 and (moved, int(summary.group(2))) == (len(written) - len(copied),
                                                                 len(copied))
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


@pytest.fixture
def env(root, monkeypatch):
    """A global.ini extraction with a fake unp4k: the DataForge cache leaf it
    works beside (not made), the base.ini it writes, the fake, and run()."""
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


class TestGlobalIniWorkingFolder:
    """The global.ini extraction works beside the DataForge cache too (#471),
    by the same rules, so nothing it extracts lands in %TEMP% unless a
    fallback applies."""

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
        leaf, out, fake, run = env
        leaf.parent.mkdir(parents=True, exist_ok=True)
        calls = _counting_mkdir(monkeypatch, _refused_in(leaf.parent))
        assert run() is True
        assert [call.parent for call in calls] == [leaf.parent, systemp]
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
        leaf.parent.mkdir(parents=True, exist_ok=True)
        _counting_mkdir(monkeypatch, _refused_in(leaf.parent))
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
    fills during the move or a fallback copy gets the same error instead of
    a raw OSError."""

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

    def test_a_stop_during_the_old_caches_walk_keeps_it(self, setup, monkeypatch, caplog):
        """The check walks the old cache only when the drive is short, and
        that walk checks for a stop too: the run ends there with the old
        cache kept, not after the whole walk at the stop check that follows
        (whose own test is
        test_a_stop_after_the_check_before_the_wipe_keeps_the_old_cache)."""
        leaf, run = setup
        p4k = _stamp_old_cache(leaf)
        big = leaf / "raw" / "libs" / "big.bin"
        big.write_bytes(b"\0" * (1 << 20))
        filled, stopped = [], []
        _disk_space(monkeypatch, lambda folder: _GATE_4K - (1 << 19) if filled else _PLENTY)
        real_walk = pe._walk_files

        def walk(folder, should_cancel, keep_prefixes=frozenset(), *, local_only=False):
            if local_only:   # the old cache's walk
                stopped.append(True)
            return real_walk(folder, should_cancel, keep_prefixes, local_only=local_only)

        monkeypatch.setattr(pe, "_walk_files", walk)
        renames = _record_renames(monkeypatch)
        fake = _FakeTools(during_unforge=lambda run_dir: filled.append(True))
        with caplog.at_level(logging.INFO, logger=pe.logger.name):
            with pytest.raises(pe.ExtractionCancelled,
                               match="stopped before the previous cache was replaced"):
                run(fake, should_cancel=lambda: bool(stopped))
        assert stopped
        assert big.exists() and (leaf / "old-cache-sentinel").exists()
        assert pe.dataforge_cache_is_fresh(p4k, leaf)
        assert "The old DataForge cache frees" not in caplog.text
        assert renames == []
        assert not Path(fake.calls[0][2]).exists()

    @pytest.mark.parametrize("short_by, passes", [(4096, True), (4097, False)],
                             ids=["short_by=4096", "short_by=4097"])
    def test_the_check_before_the_wipe_still_asks_for_a_full_copy(
        self, setup, monkeypatch, short_by, passes
    ):
        """A refused move is copied after the wipe (#484), so the check still
        asks for a copy of every kept file, to the byte, and not only the
        64 MiB a move needs. The old cache's 3-byte sentinel frees one
        4096-byte cluster: 4096 bytes short passes, 4097 does not. The
        512 KiB margins of the tests above are larger than all 14 clusters,
        so they would not notice."""
        leaf, run = setup
        filled = []
        _disk_space(monkeypatch, lambda folder: _GATE_4K - short_by if filled else _PLENTY)
        renames = _record_renames(monkeypatch)
        fake = _FakeTools(during_unforge=lambda run_dir: filled.append(True))
        if passes:
            assert run(fake) is True
            assert not (leaf / "old-cache-sentinel").exists()
            assert len(renames) == len(pe.DATAFORGE_KEEP_SUBPATHS)
        else:
            with pytest.raises(pe.NotEnoughSpaceError):
                run(fake)
            assert (leaf / "old-cache-sentinel").exists()
            assert renames == []

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

    @pytest.mark.parametrize("where", ["beside", "temp"])
    @pytest.mark.parametrize("winerror", [39, 112, 1295])
    def test_a_full_drive_during_a_fallback_copy_says_the_cache_is_incomplete(
        self, setup, monkeypatch, english_ui, winerror, where
    ):
        """ERROR_HANDLE_DISK_FULL, ERROR_DISK_FULL, ERROR_DISK_QUOTA_EXCEEDED.
        copytree folds a per-file OSError into shutil.Error (errno None) and
        copies on, and Python maps 39 and 1295 to EINVAL, so the copy has to
        catch these itself, and stop at the first. Beside the cache the copy
        is the fallback for refused renames (#484), and with the work in
        %TEMP% (OneDrive here) it is the only way."""
        leaf, run = setup
        if where == "beside":
            _refuse_moves(monkeypatch, 17)
        else:
            monkeypatch.setattr(pe, "is_onedrive_path", lambda path: True)
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
        and the user still gets the "cache incomplete" message. The stamps
        are removed before the wipe too (#484), so the warning comes twice,
        and each removal must log rather than raise."""
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
        assert caplog.text.count(f"Could not remove {pe.P4K_MTIME_STAMP}") == 2
        assert "that cache is incomplete" in caplog.text

    def test_another_copy_failure_is_not_called_a_full_drive(self, setup, monkeypatch):
        """A fallback copy that fails for another reason (#484: every rename
        refused here) is raised as it is, with no stamp left."""
        leaf, run = setup
        _refuse_moves(monkeypatch, 17)

        def copy2(src, dst, *args, **kwargs):
            raise PermissionError(errno.EACCES, "Access is denied", str(dst))

        monkeypatch.setattr(shutil, "copy2", copy2)
        with pytest.raises(OSError) as raised:
            run(_FakeTools())
        assert raised.value.errno is None or raised.value.errno == errno.EACCES
        assert not (leaf / pe.P4K_MTIME_STAMP).exists() and not (leaf / pe.P4K_SIZE_STAMP).exists()


# ── a working folder Windows refuses (#490) ─────────────────────────────────

def _refusal_text(folder, fix_key: str) -> str:
    """The message a refusal in *folder* gives: the intro naming it, then
    the advice *fix_key*."""
    return pe.tr("extract.folder_refused", folder=str(folder)) + "\n\n" + pe.tr(fix_key)


def _scripted_names(monkeypatch, *tokens: str) -> list[int]:
    """Make secrets.token_hex return *tokens* in turn, the last one for
    every call after them. Returns the byte counts it was asked for."""
    sizes = []
    queue = list(tokens)

    def token_hex(nbytes):
        sizes.append(nbytes)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(pe.secrets, "token_hex", token_hex)
    return sizes


# Other OSErrors making the folder, which keep the handling they had before
# #490: a drive that is gone, and a path Windows cannot use (WinError 123,
# which Python raises as a plain OSError with EINVAL). Each test makes its
# own instance.
_OTHER_FOLDER_ERRORS = [
    pytest.param(lambda: FileNotFoundError(errno.ENOENT,
                                           "The system cannot find the path specified"),
                 id="drive gone"),
    pytest.param(lambda: OSError(errno.EINVAL, "The filename, directory name, or volume label "
                                               "syntax is incorrect"),
                 id="bad path"),
]


def _failing_in(parent, error):
    """A *refuse* for _counting_mkdir: *error* for a folder in *parent*."""
    plain = pe.win_plain_path(parent)
    return lambda folder: error if pe.win_plain_path(folder.parent) == plain else None


class TestMakeRunFolder:
    """One os.mkdir per random name: only a name that is taken is tried
    again, and only a few times."""

    def test_the_name_is_the_prefix_and_eight_random_hex_characters(self, root, monkeypatch):
        sizes = _scripted_names(monkeypatch, "0123abcd")
        folder = pe._make_run_folder(root, pe.DATAFORGE_SCRATCH_PREFIX)
        assert folder == root / (pe.DATAFORGE_SCRATCH_PREFIX + "0123abcd")
        assert folder.is_dir()
        assert sizes == [pe._MKDTEMP_RANDOM_CHARS // 2]
        assert len(folder.name) == len(pe.DATAFORGE_SCRATCH_PREFIX) + pe._MKDTEMP_RANDOM_CHARS

    def test_a_refused_folder_fails_on_the_first_try(self, root, monkeypatch):
        calls = _counting_mkdir(monkeypatch, _refused_in(root))
        started = time.monotonic()
        with pytest.raises(PermissionError) as raised:
            pe._make_run_folder(root, pe.DATAFORGE_SCRATCH_PREFIX)
        assert time.monotonic() - started < 1.0
        assert len(calls) == 1 and calls[0].parent == root
        assert raised.value.errno == errno.EACCES
        assert _scratch_folders(root, pe.DATAFORGE_SCRATCH_PREFIX) == []

    def test_a_name_that_is_taken_gets_a_new_name(self, root, monkeypatch):
        """A clash with another run's folder moves on to a fresh name and
        leaves that folder alone."""
        taken = root / (pe.DATAFORGE_SCRATCH_PREFIX + "aaaaaaaa")
        taken.mkdir()
        (taken / "other-run").write_text("x")
        _scripted_names(monkeypatch, "aaaaaaaa", "aaaaaaaa", "bbbbbbbb")
        calls = _counting_mkdir(monkeypatch)
        folder = pe._make_run_folder(root, pe.DATAFORGE_SCRATCH_PREFIX)
        assert [c.name for c in calls] == [taken.name, taken.name,
                                           pe.DATAFORGE_SCRATCH_PREFIX + "bbbbbbbb"]
        assert folder == root / (pe.DATAFORGE_SCRATCH_PREFIX + "bbbbbbbb")
        assert (taken / "other-run").read_text() == "x"

    def test_a_refused_name_that_is_there_gets_a_new_name(self, root, monkeypatch):
        """Windows can answer Access denied for a name that is there, such as
        a folder it is still deleting. A refusal for a name that exists is a
        clash, not a folder that refuses."""
        pending = root / (pe.DATAFORGE_SCRATCH_PREFIX + "aaaaaaaa")
        pending.mkdir()
        _scripted_names(monkeypatch, "aaaaaaaa", "bbbbbbbb")
        calls = _counting_mkdir(monkeypatch, lambda folder: (
            PermissionError(errno.EACCES, "Access is denied", str(folder))
            if folder == pending else None))
        folder = pe._make_run_folder(root, pe.DATAFORGE_SCRATCH_PREFIX)
        assert calls == [pending, folder]
        assert folder.name == pe.DATAFORGE_SCRATCH_PREFIX + "bbbbbbbb"

    def test_a_name_that_stays_taken_gives_up_after_a_few_tries(self, root, monkeypatch):
        """The limit is a few names, never Python 3.11 tempfile's 2**31 - 1. Giving up
        is a FileExistsError, an OSError, so callers handle it as they
        handle any other folder that cannot be made."""
        (root / (pe.DATAFORGE_SCRATCH_PREFIX + "aaaaaaaa")).mkdir()
        _scripted_names(monkeypatch, "aaaaaaaa")
        calls = _counting_mkdir(monkeypatch)
        with pytest.raises(FileExistsError) as raised:
            pe._make_run_folder(root, pe.DATAFORGE_SCRATCH_PREFIX)
        assert len(calls) == pe._SCRATCH_NAME_ATTEMPTS
        assert 1 < pe._SCRATCH_NAME_ATTEMPTS <= 20
        assert raised.value.filename == str(root)


class TestRefusedWorkingFolder:
    """A refusal becomes one translated message that names the folder (#490):
    for DataForge at once, for global.ini only when %TEMP% refuses too. Any
    other OSError is handled as before."""

    def test_a_refused_parent_of_the_cache_folder_is_the_same_box(
        self, root, monkeypatch, systemp
    ):
        """_open_scratch makes the cache folder's own folder first when it is
        missing. The app normally makes the cache folder before an
        extraction, so this is rare, but Windows refusing it is the same box
        as a refused working folder, not a raw error."""
        tools = root / "tools"
        tools.mkdir()
        for name in ("unp4k.exe", "unforge.exe", "Data.p4k"):
            (tools / name).write_bytes(b"x")
        new = root / "new"
        leaf = new / "cache" / "dataforge"
        real_mkdir = os.mkdir

        def mkdir(path, *args, **kwargs):
            if pe.win_plain_path(str(path)) == pe.win_plain_path(str(new)):
                raise PermissionError(errno.EACCES, "Access is denied", str(path))
            return real_mkdir(path, *args, **kwargs)

        monkeypatch.setattr(pe.os, "mkdir", mkdir)
        calls = _counting_mkdir(monkeypatch)   # counts run folders, then calls the fake above
        fake = _FakeTools()
        monkeypatch.setattr(pe, "_run_tool", fake)
        with pytest.raises(pe.WorkingFolderRefusedError) as raised:
            pe.extract_dataforge(tools / "Data.p4k", tools / "unp4k.exe", tools / "unforge.exe",
                                 leaf)
        assert raised.value.folder == str(leaf.parent)
        assert isinstance(raised.value.__cause__, PermissionError)
        assert calls == []   # refused before any run folder was asked for
        assert fake.calls == []
        assert not new.exists()
        assert list(systemp.iterdir()) == []

    def test_dataforge_fails_on_the_first_try_and_names_the_folder(
        self, setup, monkeypatch, systemp, caplog, english_ui
    ):
        """Before #490, tempfile.mkdtemp took each refusal for a name that
        might be taken and tried the next, so on Python 3.11 this run
        looked stuck for about 39 hours (the spin guard stops it here)."""
        leaf, run = setup
        calls = _counting_mkdir(monkeypatch, _refused_in(leaf.parent))
        fake = _FakeTools()
        started = time.monotonic()
        with caplog.at_level(logging.INFO, logger=pe.logger.name):
            with pytest.raises(pe.WorkingFolderRefusedError) as raised:
                run(fake)
        assert time.monotonic() - started < 5
        assert len(calls) == 1 and calls[0].parent == leaf.parent
        message = str(raised.value)
        assert message == _refusal_text(leaf.parent, "extract.folder_refused_fix_cache")
        assert message.startswith("Windows denied Smart Citizen permission to create a working "
                                  f"folder in:\n{leaf.parent}\n\n")
        assert "Controlled folder access" in message
        assert "choose another DataForge cache folder in the Config tab" in message
        assert raised.value.folder == str(leaf.parent)
        assert isinstance(raised.value.__cause__, PermissionError)
        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings == [f"Windows refused an extraction working folder in {leaf.parent}: "
                            f"{raised.value.__cause__}"]
        assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []
        assert fake.calls == []
        assert (leaf / "old-cache-sentinel").exists()
        assert list(systemp.iterdir()) == []

    def test_dataforge_working_in_temp_gets_the_advice_for_temp(
        self, setup, monkeypatch, systemp, english_ui
    ):
        """A OneDrive cache sends the work to %TEMP%. Choosing another cache
        folder is not the advice there, since it would not always help."""
        _leaf, run = setup
        monkeypatch.setattr(pe, "is_onedrive_path", lambda path: True)
        calls = _counting_mkdir(monkeypatch, _refused_in(systemp))
        with pytest.raises(pe.WorkingFolderRefusedError) as raised:
            run(_FakeTools())
        assert len(calls) == 1
        assert raised.value.folder == str(systemp)
        assert str(raised.value) == _refusal_text(systemp, "extract.folder_refused_fix")
        assert "Config tab" not in str(raised.value)

    def test_a_marker_refused_in_the_new_folder_is_a_refusal_too(self, setup, monkeypatch):
        """A folder can allow new folders and refuse new files. The marker is
        the run's first file, and its folder is removed again."""
        leaf, run = setup

        def refuse(*args, **kwargs):
            raise PermissionError(errno.EACCES, "Access is denied")

        # A module-level open shadows the builtin inside pak_extractor only.
        monkeypatch.setattr(pe, "open", refuse, raising=False)
        fake = _FakeTools()
        with pytest.raises(pe.WorkingFolderRefusedError) as raised:
            run(fake)
        assert raised.value.folder == str(leaf.parent)
        assert fake.calls == []
        assert _scratch_folders(leaf.parent, pe.DATAFORGE_SCRATCH_PREFIX) == []

    def test_global_ini_moves_to_temp_when_the_folder_beside_the_cache_refuses(
        self, env, systemp, monkeypatch, caplog
    ):
        """#471's fallback still comes first, now on the first refusal: one
        try beside the cache, an INFO line, and the run in %TEMP%."""
        leaf, out, fake, run = env
        calls = _counting_mkdir(monkeypatch, _refused_in(leaf.parent))
        with caplog.at_level(logging.INFO, logger=pe.logger.name):
            assert run() is True
        assert [c.parent for c in calls] == [leaf.parent, systemp]
        assert Path(fake.cwds[0]).parent == systemp
        assert out.read_text(encoding="utf-8") == "lang=english\n"
        moves = [r.getMessage() for r in caplog.records if "; working in " in r.getMessage()]
        assert len(moves) == 1
        assert moves[0].startswith(f"Could not work in {leaf.parent} (")
        assert "Access is denied" in moves[0] and moves[0].endswith(f"working in {systemp}")
        assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == []

    def test_global_ini_shows_the_message_only_when_temp_refuses_too(
        self, env, systemp, monkeypatch, caplog, english_ui
    ):
        leaf, out, fake, run = env
        out.parent.mkdir(parents=True)
        out.write_text("old=1\n", encoding="utf-8")
        calls = _counting_mkdir(monkeypatch, _refused_in(leaf.parent, systemp))
        with caplog.at_level(logging.INFO, logger=pe.logger.name):
            with pytest.raises(pe.WorkingFolderRefusedError) as raised:
                run()
        assert [c.parent for c in calls] == [leaf.parent, systemp]
        assert raised.value.folder == str(systemp)
        assert str(raised.value) == _refusal_text(systemp, "extract.folder_refused_fix")
        assert any(f"Could not work in {leaf.parent}" in r.getMessage()
                   and r.levelno == logging.INFO for r in caplog.records)
        warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warnings) == 1 and warnings[0].startswith(
            f"Windows refused an extraction working folder in {systemp}: ")
        assert fake.cwds == []
        assert out.read_text(encoding="utf-8") == "old=1\n"

    def test_global_ini_without_a_cache_folder_shows_the_message_when_temp_refuses(
        self, env, systemp, monkeypatch, english_ui
    ):
        _leaf, _out, fake, run = env
        calls = _counting_mkdir(monkeypatch, _refused_in(systemp))
        with pytest.raises(pe.WorkingFolderRefusedError) as raised:
            run(near=None)
        assert len(calls) == 1
        assert str(raised.value) == _refusal_text(systemp, "extract.folder_refused_fix")
        assert fake.cwds == []

    @pytest.mark.parametrize("make_error", _OTHER_FOLDER_ERRORS)
    def test_another_error_fails_dataforge_as_before(self, setup, monkeypatch, make_error):
        leaf, run = setup
        error = make_error()
        calls = _counting_mkdir(monkeypatch, _failing_in(leaf.parent, error))
        fake = _FakeTools()
        with pytest.raises(OSError) as raised:
            run(fake)
        assert raised.value is error
        assert len(calls) == 1
        assert fake.calls == []
        assert (leaf / "old-cache-sentinel").exists()

    @pytest.mark.parametrize("make_error", _OTHER_FOLDER_ERRORS)
    def test_another_error_beside_the_cache_moves_global_ini_as_before(
        self, env, systemp, monkeypatch, make_error
    ):
        leaf, _out, fake, run = env
        _counting_mkdir(monkeypatch, _failing_in(leaf.parent, make_error()))
        assert run() is True
        assert Path(fake.cwds[0]).parent == systemp

    @pytest.mark.parametrize("make_error", _OTHER_FOLDER_ERRORS)
    def test_another_error_in_temp_fails_global_ini_as_before(
        self, env, systemp, monkeypatch, make_error
    ):
        _leaf, _out, fake, run = env
        error = make_error()
        _counting_mkdir(monkeypatch, _failing_in(systemp, error))
        with pytest.raises(OSError) as raised:
            run(near=None)
        assert raised.value is error
        assert fake.cwds == []

    def test_a_refusal_is_an_anticipated_runtimeerror(self):
        assert issubclass(pe.WorkingFolderRefusedError, RuntimeError)
        assert not issubclass(pe.WorkingFolderRefusedError, (OSError, pe.ExtractionCancelled))
        assert pe.WorkingFolderRefusedError in pe.ANTICIPATED_EXTRACTION_ERRORS

    def test_a_write_protected_drive_gives_windows_own_reason(
        self, setup, monkeypatch, systemp, caplog, english_ui
    ):
        """Python raises a write-protected drive (WinError 19) as a
        PermissionError too, but nothing was refused, so the message gives
        Windows' own reason and no advice about permissions, still on the
        first try and with the old cache kept."""
        leaf, run = setup
        calls = _counting_mkdir(monkeypatch, _write_protected_in(leaf.parent))
        fake = _FakeTools()
        with caplog.at_level(logging.INFO, logger=pe.logger.name):
            with pytest.raises(pe.WorkingFolderRefusedError) as raised:
                run(fake)
        assert len(calls) == 1 and calls[0].parent == leaf.parent
        cause = raised.value.__cause__
        assert isinstance(cause, PermissionError) and cause.winerror == 19
        assert str(raised.value) == ("Smart Citizen could not use a working folder in:\n"
                                     f"{leaf.parent}\n\n{_WRITE_PROTECTED}\n\n"
                                     "The extraction did not start, so nothing was changed.")
        assert raised.value.folder == str(leaf.parent)
        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings == [f"Windows refused an extraction working folder in {leaf.parent}: "
                            f"{cause}"]
        assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []
        assert fake.calls == []
        assert (leaf / "old-cache-sentinel").exists()
        assert list(systemp.iterdir()) == []

    def test_global_ini_moves_off_a_write_protected_drive_and_names_temp_if_it_fails_too(
        self, env, systemp, monkeypatch, english_ui
    ):
        """global.ini moves to %TEMP% first, as for a refusal, and gives
        Windows' reason naming %TEMP% only when %TEMP% fails too."""
        leaf, _out, fake, run = env
        calls = _counting_mkdir(monkeypatch, _write_protected_in(leaf.parent, systemp))
        with pytest.raises(pe.WorkingFolderRefusedError) as raised:
            run()
        assert [c.parent for c in calls] == [leaf.parent, systemp]
        assert raised.value.folder == str(systemp)
        assert str(raised.value) == pe.tr("extract.folder_unusable", folder=str(systemp),
                                          reason=_WRITE_PROTECTED)
        assert fake.cwds == []

    @pytest.mark.parametrize("winerror, refused", [
        (5, True),     # ERROR_ACCESS_DENIED: a folder's permissions, Controlled Folder Access
        (65, True),    # ERROR_NETWORK_ACCESS_DENIED: a share
        (19, False),   # ERROR_WRITE_PROTECT
        (21, False),   # ERROR_NOT_READY: a drive with no media in it
        (23, False),   # ERROR_CRC: a failing drive
        (29, False),   # ERROR_WRITE_FAULT
        (32, False),   # ERROR_SHARING_VIOLATION: a file another program holds
        (33, False),   # ERROR_LOCK_VIOLATION
    ])
    def test_only_a_denied_permission_is_a_refusal(self, winerror, refused):
        error = OSError(None, "x", None, winerror)
        assert isinstance(error, PermissionError)   # how Python raises all of these
        assert pe.windows_refused(error) is refused

    def test_a_permission_error_with_no_windows_code_is_a_refusal_and_no_other_error_is(self):
        assert pe.windows_refused(PermissionError(errno.EACCES, "Access is denied"))
        assert not pe.windows_refused(FileNotFoundError(errno.ENOENT, "gone"))
        assert not pe.windows_refused(OSError(None, "There is not enough space on the disk.",
                                              None, 112))

    def test_windows_reason_is_the_errors_own_text(self):
        assert pe.windows_reason(OSError(None, _WRITE_PROTECTED, "Z:\\x", 19)) == _WRITE_PROTECTED
        bare = PermissionError("no strerror")
        assert bare.strerror is None and pe.windows_reason(bare) == "no strerror"


def _icacls(*args: str) -> subprocess.CompletedProcess:
    """Run Windows' own icacls (from System32, never from PATH). It writes to
    a pipe in the OEM code page, not the ANSI one ``text=True`` would read,
    so a folder name or a translated message with a letter only the OEM page
    has would fail to decode."""
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    icacls = Path(system_root) / "System32" / "icacls.exe"
    return subprocess.run([str(icacls), *args], capture_output=True, encoding="oem",
                          errors="replace", timeout=30)


@contextlib.contextmanager
def _new_folders_denied(*folders: Path):
    """Deny Everyone the right to add a subfolder (AD) in each of *folders*
    for the block: what Windows answers when a folder's permissions refuse
    Smart Citizen. The deny is removed in a finally, so pytest can clean up,
    and skips the test when icacls cannot set it."""
    denied = []
    try:
        for folder in folders:
            result = _icacls(str(folder), "/deny", f"{_EVERYONE_SID}:(AD)")
            if result.returncode != 0:
                pytest.skip(f"icacls could not deny new folders here: "
                            f"{result.stdout}{result.stderr}")
            denied.append(folder)
        yield
    finally:
        failed = [(folder, result.stdout + result.stderr) for folder, result in
                  ((folder, _icacls(str(folder), "/remove:d", _EVERYONE_SID)) for folder in denied)
                  if result.returncode != 0]
    assert failed == [], failed


class TestRealRefusal:
    """The same against folders that really refuse new folders, through an
    access control list, as a folder whose permissions deny Smart Citizen
    does. Controlled Folder Access itself cannot be turned on from a test."""

    def test_dataforge_fails_at_once_and_runs_once_the_folder_allows_it(
        self, setup, monkeypatch, systemp
    ):
        leaf, run = setup
        with monkeypatch.context() as patched:
            calls = _counting_mkdir(patched)
            with _new_folders_denied(leaf.parent):
                with pytest.raises(pe.WorkingFolderRefusedError) as raised:
                    run(_FakeTools())
        assert len(calls) == 1 and calls[0].parent == leaf.parent
        assert raised.value.folder == str(leaf.parent)
        assert getattr(raised.value.__cause__, "winerror", None) == 5   # ERROR_ACCESS_DENIED
        assert (leaf / "old-cache-sentinel").exists()
        assert list(systemp.iterdir()) == []

        assert run(_FakeTools()) is True
        assert (leaf / pe.P4K_SIZE_STAMP).exists()

    def test_global_ini_moves_to_temp_and_stops_when_temp_refuses_too(
        self, env, systemp, monkeypatch
    ):
        leaf, out, fake, run = env
        leaf.parent.mkdir(parents=True)
        with monkeypatch.context() as patched:
            calls = _counting_mkdir(patched)
            with _new_folders_denied(leaf.parent):
                assert run() is True
                assert Path(fake.cwds[-1]).parent == systemp
                with _new_folders_denied(systemp):
                    with pytest.raises(pe.WorkingFolderRefusedError) as raised:
                        run()
        assert [c.parent for c in calls] == [leaf.parent, systemp] * 2
        assert raised.value.folder == str(systemp)
        assert len(fake.cwds) == 1
        assert out.read_text(encoding="utf-8") == "lang=english\n"
