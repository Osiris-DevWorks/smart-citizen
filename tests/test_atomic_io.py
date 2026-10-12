"""src/utils/atomic_io.py: a file is replaced whole or not at all.

An enhancements generation, its stamps, the lookup pickles and the DataForge
patcher used to write their files in place, so a run cut off by a close or a
crash left the file it was writing truncated, and the next read took it as
whole. ``atomic_writer`` writes a temp file beside the target and swaps it in
with ``os.replace``. These tests pin:

* the bytes (text mode writes what ``Path.write_text`` wrote: UTF-8, no BOM,
  CRLF on Windows),
* where the temp goes and what it is called (beside the target, ``.sc-*.tmp``,
  never ``*.ini``), and that nothing else is left,
* how the temp is made: a folder that refuses new files fails the write on
  the first try, naming the target, and only a name already taken is
  retried, a small fixed number of times (``tempfile.mkstemp``, used
  before, retries a refusal up to 2**31 times on the Python 3.11 the
  release builds use),
* every way the write can fail (the swap, the sync, an interrupt in the body)
  keeping the old file and removing the temp,
* the swap's retry: a PermissionError only, which a reader holding the file
  causes on Windows, within its budget, with the real sleeps recorded,
* the reader's short retry, its sleeps recorded the same way, and the sweep
  of temps a hard kill left behind,
* a real child killed just before the swap leaving the old file whole.

Qt-free. The child runs on the base interpreter (``sys._base_executable``)
because a venv's ``python.exe`` is a launcher whose child a kill would orphan,
and it exits on its own within 30 s if the kill fails.
"""
from __future__ import annotations

import errno
import fnmatch
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from src.utils import atomic_io

pytestmark = [pytest.mark.unit, pytest.mark.regression]

PY = getattr(sys, "_base_executable", None) or sys.executable
REPO_ROOT = Path(__file__).resolve().parent.parent

OLD_BYTES = b"key_one=old value\r\nkey_two=old value\r\n"
NEW_TEXT = "key_one=new value \u2014 Sebasti\u00e1n\nkey_two=new value\nkey_three=x\n"

# The swap's real backoff on a PermissionError: 10 tries, so 9 sleeps,
# doubling from 10 ms and capped at 250 ms, about 1.3 s in all. Written out
# rather than worked out from the module's constants, so a change to the
# loop itself (a dropped cap, a sleep in the wrong place) fails the test.
SWAP_SLEEPS_S = [0.01, 0.02, 0.04, 0.08, 0.16, 0.25, 0.25, 0.25, 0.25]
# The reader's: 4 tries, so 3 sleeps of 50 ms, about 0.15 s. Stamps are read
# on the GUI thread, so this has to stay short.
READ_SLEEPS_S = [0.05, 0.05, 0.05]

# More os.open calls than any temp creation should make. A loop that
# retries a refusal (tempfile.mkstemp on Python 3.11 retries one up to 2**31
# times on Windows) is stopped at this count with an error the test reports,
# instead of hanging the run for days.
SPIN_GUARD_CALLS = 100

# The well-known SID of Everyone. The account name is translated on
# non-English Windows, the SID never is.
EVERYONE_SID = "*S-1-1-0"


def _temps(folder: Path) -> list[str]:
    return sorted(p.name for p in Path(folder).glob(".sc-*.tmp"))


def _wait_for(predicate, seconds: float = 20.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


@pytest.fixture
def target(tmp_path) -> Path:
    """An existing file holding OLD_BYTES, alone in its folder."""
    folder = tmp_path / "cache"
    folder.mkdir()
    path = folder / "ships_desc_enhancements.ini"
    path.write_bytes(OLD_BYTES)
    return path


@pytest.fixture
def no_backoff(monkeypatch):
    monkeypatch.setattr(atomic_io, "REPLACE_FIRST_DELAY_S", 0)
    monkeypatch.setattr(atomic_io, "REPLACE_MAX_DELAY_S", 0)
    monkeypatch.setattr(atomic_io, "READ_DELAY_S", 0)


@pytest.fixture
def recorded_sleeps(monkeypatch):
    """``time.sleep`` recorded and not slept, so a test sees the real delays
    atomic_io asks for without waiting them out. ``atomic_io.time`` is the
    ``time`` module itself, so this holds every sleep in the test."""
    sleeps = []
    monkeypatch.setattr(atomic_io.time, "sleep", sleeps.append)
    return sleeps


class StillRetrying(Exception):
    """A fake ``os.open`` called more than SPIN_GUARD_CALLS times. Not an
    OSError, so no temp creation loop can catch it and carry on."""


def _counting_open(monkeypatch, error=None) -> list[str]:
    """Patch ``os.open`` with one that records each path it is asked for.

    ``atomic_io.os`` is the ``os`` module itself, so this also counts the
    calls ``tempfile.mkstemp`` makes, should the temp ever be made with it
    again. With *error* (a function of the path), every call raises what it
    returns, otherwise the real ``os.open`` runs.
    """
    calls = []
    real_open = os.open

    def counting(path, flags, mode=0o777, *args, **kwargs):
        calls.append(path)
        if len(calls) > SPIN_GUARD_CALLS:
            raise StillRetrying(f"os.open asked {len(calls)} times")
        if error is not None:
            raise error(path)
        return real_open(path, flags, mode, *args, **kwargs)

    monkeypatch.setattr(atomic_io.os, "open", counting)
    return calls


def _icacls(*args: str) -> subprocess.CompletedProcess:
    """Run Windows' own icacls (from System32, never from PATH)."""
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    icacls = Path(system_root) / "System32" / "icacls.exe"
    return subprocess.run(
        [str(icacls), *args], capture_output=True, text=True, timeout=30,
    )


# ── Bytes and placement ─────────────────────────────────────────────────────

def test_text_writes_the_same_bytes_as_write_text(target):
    expected = target.with_name("expected.ini")
    expected.write_text(NEW_TEXT, encoding="utf-8")

    atomic_io.atomic_write_text(target, NEW_TEXT)

    written = target.read_bytes()
    assert written == expected.read_bytes()
    assert not written.startswith(b"\xef\xbb\xbf")
    if sys.platform == "win32":
        assert written.count(b"\r\n") == NEW_TEXT.count("\n")


def test_binary_writer_round_trips(target):
    payload = bytes(range(256)) * 64 + b"\r\n\n\r\x00"

    with atomic_io.atomic_writer(target, "wb") as f:
        f.write(payload)

    assert target.read_bytes() == payload


@pytest.mark.parametrize("mode", ["a", "ab", "r+", "w+", "x", "r"])
def test_only_w_and_wb_are_allowed(target, mode):
    with pytest.raises(ValueError):
        with atomic_io.atomic_writer(target, mode):
            pass
    assert target.read_bytes() == OLD_BYTES
    assert _temps(target.parent) == []


def test_the_temp_is_made_beside_the_target(target, monkeypatch):
    swaps = []
    real_replace = os.replace

    def spy(source, destination):
        swaps.append((Path(source), Path(destination)))
        real_replace(source, destination)

    monkeypatch.setattr(atomic_io.os, "replace", spy)
    atomic_io.atomic_write_text(target, NEW_TEXT)

    [(source, destination)] = swaps
    assert destination == target
    assert source.parent == target.parent
    assert fnmatch.fnmatch(source.name, ".sc-*.tmp")
    assert not source.name.endswith(".ini")
    # Shorter than every INI name, so a deep folder that holds the INIs
    # holds the temps too.
    assert len(source.name) == 16


def test_nothing_but_the_target_is_left(target):
    atomic_io.atomic_write_text(target, NEW_TEXT)
    with atomic_io.atomic_writer(target.with_name("standings.pkl"), "wb") as f:
        f.write(b"\x80\x05")

    assert sorted(p.name for p in target.parent.iterdir()) == [
        "ships_desc_enhancements.ini", "standings.pkl",
    ]


def test_a_missing_target_is_created(tmp_path):
    path = tmp_path / ".dataforge_stamp"
    atomic_io.atomic_write_text(path, "p4k-key")
    assert path.read_text(encoding="utf-8") == "p4k-key"


# ── Making the temp file ────────────────────────────────────────────────────

def test_a_refused_folder_fails_at_once_naming_the_target(target, monkeypatch):
    """A folder that refuses new files (Controlled Folder Access protecting
    Documents, a read-only share) fails the write on its first try. The
    error names the target, as the old in-place writes' did, so the error
    dialog and the log say which file could not be written."""
    calls = _counting_open(
        monkeypatch, lambda path: PermissionError(errno.EACCES, "Permission denied", path),
    )

    started = time.monotonic()
    with pytest.raises(PermissionError) as raised:
        atomic_io.atomic_write_text(target, NEW_TEXT)
    elapsed = time.monotonic() - started

    assert len(calls) == 1
    assert elapsed < 1.0
    assert raised.value.errno == errno.EACCES
    assert raised.value.filename == str(target)
    assert repr(str(target)) in str(raised.value)
    assert Path(calls[0]).name not in str(raised.value)
    assert target.read_bytes() == OLD_BYTES
    assert _temps(target.parent) == []


@pytest.mark.skipif(sys.platform != "win32", reason="a Windows access control list")
def test_a_real_folder_that_refuses_new_files_fails_at_once(target, monkeypatch):
    """The same against a real refusal: the target's folder denies Everyone
    the right to add a file (WD), which is what Windows answers a write
    into a protected or read-only folder with. The old file stays, and once
    the folder allows it again the write goes through."""
    folder = target.parent
    denied = _icacls(str(folder), "/deny", f"{EVERYONE_SID}:(WD)")
    if denied.returncode != 0:
        pytest.skip(f"icacls could not deny file creation here: {denied.stdout}{denied.stderr}")
    try:
        with monkeypatch.context() as patched:
            calls = _counting_open(patched)
            with pytest.raises(PermissionError) as raised:
                atomic_io.atomic_write_text(target, NEW_TEXT)
    finally:
        allowed = _icacls(str(folder), "/remove:d", EVERYONE_SID)
    assert allowed.returncode == 0, allowed.stdout + allowed.stderr

    assert len(calls) == 1
    assert raised.value.filename == str(target)
    assert target.read_bytes() == OLD_BYTES
    assert _temps(folder) == []

    atomic_io.atomic_write_text(target, NEW_TEXT)
    assert target.read_text(encoding="utf-8") == NEW_TEXT


def test_a_missing_folder_fails_at_once_naming_the_target(tmp_path, monkeypatch):
    calls = _counting_open(monkeypatch)
    path = tmp_path / "missing" / "ships_desc_enhancements.ini"

    with pytest.raises(FileNotFoundError) as raised:
        atomic_io.atomic_write_text(path, NEW_TEXT)

    assert len(calls) == 1
    assert raised.value.filename == str(path)
    assert repr(str(path)) in str(raised.value)


def test_a_name_already_taken_is_retried_with_a_new_one(target, monkeypatch):
    """The temp is opened only if it is new, so a clash with another write's
    temp moves on to a fresh name and leaves that temp alone."""
    taken = target.with_name(f"{atomic_io.TEMP_PREFIX}aaaaaaaa{atomic_io.TEMP_SUFFIX}")
    taken.write_bytes(b"another write's temp")
    tokens = iter(["aaaaaaaa", "aaaaaaaa", "bbbbbbbb"])
    sizes = []

    def scripted_token_hex(nbytes):
        sizes.append(nbytes)
        return next(tokens)

    monkeypatch.setattr(atomic_io.secrets, "token_hex", scripted_token_hex)
    calls = _counting_open(monkeypatch)

    atomic_io.atomic_write_text(target, NEW_TEXT)

    assert [Path(path).name for path in calls] == [
        taken.name, taken.name, f"{atomic_io.TEMP_PREFIX}bbbbbbbb{atomic_io.TEMP_SUFFIX}",
    ]
    assert sizes == [atomic_io.TEMP_RANDOM_BYTES] * 3
    assert target.read_text(encoding="utf-8") == NEW_TEXT
    assert taken.read_bytes() == b"another write's temp"
    assert _temps(target.parent) == [taken.name]


def test_endless_clashes_give_up_after_the_budget(target, monkeypatch):
    # A small fixed budget, well under the guard that stops a runaway loop.
    assert 1 < atomic_io.TEMP_CREATE_ATTEMPTS < SPIN_GUARD_CALLS
    calls = _counting_open(
        monkeypatch, lambda path: FileExistsError(errno.EEXIST, "File exists", path),
    )

    with pytest.raises(FileExistsError) as raised:
        atomic_io.atomic_write_text(target, NEW_TEXT)

    assert len(calls) == atomic_io.TEMP_CREATE_ATTEMPTS
    assert len(set(calls)) == len(calls), "a taken name was tried again"
    assert raised.value.filename == str(target)
    assert target.read_bytes() == OLD_BYTES
    assert _temps(target.parent) == []


# ── Failures keep the old file ──────────────────────────────────────────────

def test_a_failed_swap_keeps_the_old_file_and_removes_the_temp(target, monkeypatch):
    swaps = []

    def disk_full(source, destination):
        swaps.append(source)
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(atomic_io.os, "replace", disk_full)
    with pytest.raises(OSError) as raised:
        atomic_io.atomic_write_text(target, NEW_TEXT)

    assert raised.value.errno == errno.ENOSPC
    assert len(swaps) == 1
    assert target.read_bytes() == OLD_BYTES
    assert _temps(target.parent) == []


def test_a_failure_while_writing_keeps_the_old_file(target, monkeypatch):
    def failing_sync(fd):
        raise OSError(errno.EIO, "I/O error")

    monkeypatch.setattr(atomic_io.os, "fsync", failing_sync)
    with pytest.raises(OSError):
        atomic_io.atomic_write_text(target, NEW_TEXT)

    assert target.read_bytes() == OLD_BYTES
    assert _temps(target.parent) == []


def test_an_interrupt_before_the_swap_keeps_the_old_file_and_removes_the_temp(target):
    with pytest.raises(KeyboardInterrupt):
        with atomic_io.atomic_writer(target) as f:
            f.write(NEW_TEXT)
            raise KeyboardInterrupt

    assert target.read_bytes() == OLD_BYTES
    assert _temps(target.parent) == []


def test_only_a_permission_error_is_retried(target, monkeypatch, no_backoff):
    swaps = []

    def vanished(source, destination):
        swaps.append(source)
        raise FileNotFoundError(errno.ENOENT, "The system cannot find the path specified")

    monkeypatch.setattr(atomic_io.os, "replace", vanished)
    with pytest.raises(FileNotFoundError):
        atomic_io.atomic_write_text(target, NEW_TEXT)

    assert len(swaps) == 1
    assert target.read_bytes() == OLD_BYTES
    assert _temps(target.parent) == []


def test_a_permission_error_is_retried_up_to_its_budget(target, monkeypatch, recorded_sleeps):
    """The retry must outlast a reader's brief hold but give up on a holder
    that never lets go before the user notices a hang: about a second and a
    third. The sleeps the real loop makes are recorded, so a change to the
    loop (the cap dropped, which makes it about 5 s) fails here."""
    swaps = []

    def held(source, destination):
        swaps.append(source)
        raise PermissionError(errno.EACCES, "Access is denied")

    monkeypatch.setattr(atomic_io.os, "replace", held)
    with pytest.raises(PermissionError):
        atomic_io.atomic_write_text(target, NEW_TEXT)

    assert len(swaps) == atomic_io.REPLACE_ATTEMPTS
    assert recorded_sleeps == pytest.approx(SWAP_SLEEPS_S)
    assert 1.0 <= sum(recorded_sleeps) <= 1.6
    assert target.read_bytes() == OLD_BYTES
    assert _temps(target.parent) == []


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing rules")
def test_a_reader_holding_the_file_briefly_does_not_fail_the_write(target, monkeypatch):
    refused = []
    real_replace = os.replace

    def counting(source, destination):
        try:
            real_replace(source, destination)
        except PermissionError:
            refused.append(source)
            raise

    monkeypatch.setattr(atomic_io.os, "replace", counting)
    holder = open(target, "rb")
    timer = threading.Timer(0.3, holder.close)
    timer.start()
    try:
        atomic_io.atomic_write_text(target, NEW_TEXT)
    finally:
        timer.cancel()
        timer.join()
        holder.close()

    assert refused, "the open reader never blocked the swap, so nothing was retried"
    assert target.read_text(encoding="utf-8") == NEW_TEXT
    assert _temps(target.parent) == []


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing rules")
def test_a_holder_that_never_lets_go_fails_and_keeps_the_old_file(target, monkeypatch):
    monkeypatch.setattr(atomic_io, "REPLACE_ATTEMPTS", 2)
    monkeypatch.setattr(atomic_io, "REPLACE_FIRST_DELAY_S", 0)
    holder = open(target, "rb")
    try:
        with pytest.raises(PermissionError):
            atomic_io.atomic_write_text(target, NEW_TEXT)
    finally:
        holder.close()

    assert target.read_bytes() == OLD_BYTES
    assert _temps(target.parent) == []


# ── Reading ─────────────────────────────────────────────────────────────────

def _flaky_read_bytes(monkeypatch, failures: int, error=PermissionError):
    calls = []
    real_read_bytes = Path.read_bytes

    def flaky(self):
        calls.append(self)
        if len(calls) <= failures:
            raise error(errno.EACCES, "The process cannot access the file")
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", flaky)
    return calls


def test_read_retries_a_brief_permission_error(target, monkeypatch, no_backoff):
    calls = _flaky_read_bytes(monkeypatch, failures=2)
    assert atomic_io.read_bytes_retrying(target) == OLD_BYTES
    assert len(calls) == 3


def test_read_gives_up_after_its_budget(target, monkeypatch, recorded_sleeps):
    """The real sleeps between the reader's tries are recorded, as the
    swap's are: a reader on the GUI thread waits about 0.15 s at most."""
    calls = _flaky_read_bytes(monkeypatch, failures=99)
    with pytest.raises(PermissionError):
        atomic_io.read_bytes_retrying(target)
    assert len(calls) == atomic_io.READ_ATTEMPTS
    assert recorded_sleeps == pytest.approx(READ_SLEEPS_S)


def test_read_does_not_retry_a_missing_file(tmp_path, monkeypatch, no_backoff):
    calls = []
    real_read_bytes = Path.read_bytes

    def counting(self):
        calls.append(self)
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", counting)
    with pytest.raises(FileNotFoundError):
        atomic_io.read_bytes_retrying(tmp_path / "missing.ini")
    assert len(calls) == 1


# ── Sweep ───────────────────────────────────────────────────────────────────

def _age(path: Path, seconds: float) -> None:
    then = time.time() - seconds
    os.utime(path, (then, then))


def test_sweep_removes_only_old_temps(tmp_path):
    young = tmp_path / ".sc-young123.tmp"
    old = tmp_path / ".sc-old45678.tmp"
    unrelated = tmp_path / "x.tmp"
    an_ini = tmp_path / "ships_desc_enhancements.ini"
    nested = tmp_path / "records" / ".sc-nested12.tmp"
    nested.parent.mkdir()
    for path in (young, old, unrelated, an_ini, nested):
        path.write_bytes(b"x")
    for path in (old, unrelated, an_ini, nested):
        _age(path, 11 * 60)

    assert atomic_io.sweep_stale_temps(tmp_path) == 1

    assert not old.exists()
    assert young.exists()
    assert unrelated.exists()
    assert an_ini.exists()
    assert nested.exists()


def test_sweep_of_a_missing_folder_does_nothing(tmp_path):
    assert atomic_io.sweep_stale_temps(tmp_path / "missing") == 0


# ── A real hard kill ────────────────────────────────────────────────────────

def test_a_killed_writer_leaves_the_old_file_whole(target, tmp_path):
    """A child process writes the new contents and is killed just before
    the swap, the one point an atomic write can be cut off and still leave a
    temp behind. The target keeps its old bytes, the next write succeeds, and
    the sweep removes the leftover once it is old enough."""
    ready = tmp_path / "ready.json"
    ready_tmp = tmp_path / "ready.json.part"
    child = tmp_path / "child.py"
    child.write_text(
        "import json, os, sys, time\n"
        f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
        "from src.utils import atomic_io\n"
        "_real_replace = os.replace\n"
        "def _publish_ready_and_hang(source, destination):\n"
        f"    with open({str(ready_tmp)!r}, 'w') as f:\n"
        "        json.dump({'pid': os.getpid(), 'temp': str(source)}, f)\n"
        f"    _real_replace({str(ready_tmp)!r}, {str(ready)!r})\n"
        "    time.sleep(30)\n"
        "    sys.exit(3)\n"
        "os.replace = _publish_ready_and_hang\n"
        f"atomic_io.atomic_write_text({str(target)!r}, {NEW_TEXT!r})\n",
        encoding="utf-8",
    )
    expected_new = tmp_path / "expected.ini"
    expected_new.write_text(NEW_TEXT, encoding="utf-8")

    proc = subprocess.Popen([PY, "-I", str(child)], cwd=str(tmp_path))
    try:
        assert _wait_for(ready.exists), "the child never reached the swap"
        info = json.loads(ready.read_text(encoding="utf-8"))
        assert info["pid"] == proc.pid
        leftover = Path(info["temp"])
        # Everything but the swap was done: the temp holds the new contents.
        assert leftover.read_bytes() == expected_new.read_bytes()
        proc.kill()
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)

    assert target.read_bytes() == OLD_BYTES
    assert leftover.exists()

    atomic_io.atomic_write_text(target, NEW_TEXT)
    assert target.read_bytes() == expected_new.read_bytes()

    assert atomic_io.sweep_stale_temps(target.parent) == 0   # still young
    _age(leftover, 11 * 60)
    assert atomic_io.sweep_stale_temps(target.parent) == 1
    assert sorted(p.name for p in target.parent.iterdir()) == [target.name]
