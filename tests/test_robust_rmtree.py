"""robust_rmtree, faster (perf proposal).

Deleting the extraction's working folder took about 220 us a file one at a
time (6.9 s for ~31k files), and a re-extract deletes the old cache's ~31k
files as well. Each attempt now deletes the plain files with several threads
first (``_delete_files_first``), and ``shutil.rmtree`` then removes the
folders bottom-up and anything that would not go, one at a time with the
read-only hook, as before. Nothing waits after the last attempt any more:
the final failure used to sleep up to 3 s before raising.

These tests pin the speed-up itself (two threads deleting at once) and what
it must keep: every file and folder goes, read-only files and paths past 260
characters included, before rmtree runs; a held file fails the attempt with
Windows' own error and the whole tree is tried again after the backoff; and
the last failure raises that error at once. The threads are daemon threads
that stop once Python begins to exit, so a child process whose delete is
still running when main returns exits at once, which a ThreadPoolExecutor's
threads, joined at exit after every queued batch, did not. #491's links (a
link handed in raises ``LinkedFolderError`` with nothing deleted, a link
inside is unlinked and never followed) run through the same code in
``tests/test_linked_cache_folder.py``. Windows only.
"""
from __future__ import annotations

import gc
import logging
import os
import queue
import shutil
import stat
import subprocess
import sys
import threading
import time
import weakref
from pathlib import Path

import pytest

import src.utils.pak_extractor as pe
from src.utils.win_paths import win_long_path, win_plain_path

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(sys.platform != "win32", reason="Windows file deletes"),
]


def _fill_tree(root: Path, folders: int = 4, files: int = 40) -> list[Path]:
    """*folders* folders of *files* files under *root*, a file at its top
    and an empty folder. Returns every file."""
    made = [root / "top.xml"]
    for f in range(folders):
        folder = root / "records" / f"kind_{f}"
        made += [folder / f"record_{i:03d}.xml" for i in range(files)]
    for path in made:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<x/>", encoding="utf-8")
    (root / "records" / "empty").mkdir()
    return made


@pytest.fixture
def sleeps(monkeypatch):
    """The waits robust_rmtree asks for, recorded instead of slept."""
    asked = []
    monkeypatch.setattr(pe.time, "sleep", asked.append)
    return asked


def test_the_files_are_deleted_by_several_threads_at_once(tmp_path, monkeypatch, sleeps):
    """The first two threads that delete a file each wait until the other
    is deleting too, which one thread alone never gets past."""
    monkeypatch.setattr(pe, "_DELETE_THREADS", 4)
    tree = tmp_path / "tree"
    _fill_tree(tree)
    both_deleting = threading.Barrier(2, timeout=10)
    lock = threading.Lock()
    threads = set()
    real_unlink = os.unlink

    def unlink(path, *args, **kwargs):
        me = threading.get_ident()
        with lock:
            first = me not in threads and len(threads) < 2
            threads.add(me)
        if first:
            both_deleting.wait()
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", unlink)
    pe.robust_rmtree(tree)

    assert not os.path.lexists(tree)
    assert len(threads) >= 2 and threading.get_ident() not in threads
    assert sleeps == []


def test_rmtree_is_left_only_the_folders(tmp_path, monkeypatch, sleeps):
    """Read-only files and a file past 260 characters go with the rest
    before rmtree runs, so it only removes the folders, bottom-up. The
    threaded pass is handed the long-path form (#221), so the deep file
    goes on a PC where long paths are not turned on too (where they are,
    as on the PC this was written on, a plain path reaches it as well)."""
    tree = tmp_path / "tree"
    files = _fill_tree(tree)
    deep = Path(win_long_path(tree / ("d" * 100) / ("e" * 100) / ("f" * 100) / "deep.xml"))
    deep.parent.mkdir(parents=True)
    deep.write_text("<x/>", encoding="utf-8")
    assert len(str(deep)) > 300
    for path in (files[0], files[-1], deep):
        os.chmod(path, stat.S_IREAD)
    tops, left = [], []
    real_pass, real_rmtree = pe._delete_files_first, shutil.rmtree

    def delete_files_first(top):
        tops.append(top)
        return real_pass(top)

    def rmtree(path, *args, **kwargs):
        left.extend(p for p in Path(path).rglob("*") if not p.is_dir())
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(pe, "_delete_files_first", delete_files_first)
    monkeypatch.setattr(shutil, "rmtree", rmtree)
    pe.robust_rmtree(tree)

    assert not os.path.lexists(tree)
    assert tops == [win_long_path(tree)]
    assert left == []
    assert sleeps == []


def _rmtree_finds(monkeypatch) -> list[Path]:
    """Wrap shutil.rmtree to list the files it finds left, as plain paths.
    Returns that list."""
    left = []
    real_rmtree = shutil.rmtree

    def rmtree(path, *args, **kwargs):
        left.extend(Path(win_plain_path(p)) for p in Path(path).rglob("*") if not p.is_dir())
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", rmtree)
    return left


def test_no_new_threads_while_python_shuts_down_still_deletes_the_tree(
    tmp_path, monkeypatch, sleeps
):
    """A close that outlasted its wait can leave the working folder's delete
    running while Python shuts down, when Python starts no new thread (from
    3.12). rmtree then deletes every file itself, instead of a RuntimeError
    reaching _close_scratch, which keeps only OSErrors to itself and would
    not catch it. The tree has more batches than the bounded queue
    holds (2 x _DELETE_THREADS, at most 16 of 64 files), so a walker that
    queued batches no thread drains would block on a full queue: the delete
    runs on a thread of its own, started before Thread.start is refused, and
    a hang fails the test after 20 s instead of hanging the run."""
    tree = tmp_path / "tree"
    files = _fill_tree(tree, folders=4, files=400)
    assert len(files) > 2 * 8 * pe._DELETE_BATCH
    go, failures = threading.Event(), []

    def delete():
        go.wait(10)
        try:
            pe.robust_rmtree(tree)
        except BaseException as e:   # reported below, not lost on the thread
            failures.append(e)

    deleter = threading.Thread(target=delete, daemon=True)
    deleter.start()

    def start(_thread):
        raise RuntimeError("can't create new thread at interpreter shutdown")

    monkeypatch.setattr(pe.threading.Thread, "start", start)
    left = _rmtree_finds(monkeypatch)
    go.set()
    deleter.join(20)

    assert not deleter.is_alive(), "the delete was still running 20 s later"
    assert failures == []
    assert not os.path.lexists(tree)
    assert sorted(left) == sorted(files)
    assert sleeps == []


def test_the_threads_drop_the_queued_batches_once_python_begins_to_exit(
    tmp_path, monkeypatch, sleeps
):
    """Python's exit never waits for a daemon thread. With both threads
    holding a batch, the walk fills the queue and waits to hand out one
    more. Python then begins to exit (``_EXITING``, which atexit sets): each
    thread finishes the batch in hand and drops every queued one, the walk
    hands out nothing more, the threads are gone when the pass returns, and
    rmtree deletes the rest on the calling thread, as it did every file
    before the threaded pass."""
    monkeypatch.setattr(pe, "_EXITING", threading.Event())
    monkeypatch.setattr(pe, "_DELETE_THREADS", 2)
    tree = tmp_path / "tree"
    files = _fill_tree(tree, folders=4, files=400)
    queues = []

    class Recording(queue.Queue):
        def __init__(self, maxsize=0):
            super().__init__(maxsize)
            self.sizes = []
            queues.append(self)

        @property
        def batches(self):
            return len(self.sizes)

        def put(self, item, *args, **kwargs):
            if item is not None:
                self.sizes.append(len(item))
            super().put(item, *args, **kwargs)

    monkeypatch.setattr(pe.queue, "Queue", Recording)
    release, deleted, daemons = threading.Event(), [], []
    real_unlink_files = pe._unlink_files

    def unlink_files(paths):
        daemons.append(threading.current_thread().daemon)
        release.wait(10)
        deleted.extend(paths)
        real_unlink_files(paths)

    monkeypatch.setattr(pe, "_unlink_files", unlink_files)
    left = _rmtree_finds(monkeypatch)
    errors = []

    def delete():
        try:
            pe.robust_rmtree(tree)
        except BaseException as e:   # reported below, not lost on the thread
            errors.append(e)

    runner = threading.Thread(target=delete, daemon=True)
    runner.start()
    # A batch in each thread's hands, the queue full (twice the threads),
    # and the walk waiting to put one more.
    full = 2 + 2 * 2 + 1
    tick = threading.Event()   # time.sleep is the sleeps fixture's
    for _ in range(1000):
        if queues and queues[0].batches >= full:
            break
        tick.wait(0.01)
    assert queues and queues[0].batches == full
    pe._EXITING.set()
    release.set()
    runner.join(20)

    assert not runner.is_alive(), "the delete was still running 20 s later"
    assert errors == []
    assert not os.path.lexists(tree)
    assert daemons == [True, True]   # only the two batches in hand
    in_hand = sum(queues[0].sizes[:2])   # the top file alone, then a full batch
    assert len(deleted) == in_hand
    assert queues[0].batches == full   # the walk handed out nothing more
    assert len(left) == len(files) - in_hand > 1000
    assert [t for t in threading.enumerate() if t.name == "robust_rmtree"] == []
    assert sleeps == []


def test_python_sets_the_flag_as_it_begins_to_exit():
    """``_EXITING`` is set by an atexit hook, so a delete still running when
    main returns stops handing out batches. Run in a child, where the exit
    hooks can run without ending the test run."""
    root = str(Path(__file__).resolve().parent.parent)
    child = (f"import sys; sys.path.insert(0, {root!r})\n"
             "import atexit\n"
             "import src.utils.pak_extractor as pe\n"
             "print('before', pe._EXITING.is_set())\n"
             "atexit._run_exitfuncs()\n"
             "print('after', pe._EXITING.is_set())\n")
    python = getattr(sys, "_base_executable", None) or sys.executable
    done = subprocess.run([python, "-c", child], cwd=root, capture_output=True,
                          text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == ["before", "False", "after", "True"]


# The child for test_python_exits_while_a_delete_still_runs. It deletes a
# working folder as the app's delete worker does, on a thread Python does not
# wait for, with its first file delete blocked for a minute (a delete an
# antivirus or file system filter holds), and returns from main once that
# delete has begun.
_EXIT_CHILD = """\
import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, {root!r})
import src.utils.pak_extractor as pe

parent, signal = Path(sys.argv[1]), sys.argv[2]
run_dir, marker = pe._open_scratch(parent, pe.DATAFORGE_SCRATCH_PREFIX)
for kind in range(4):
    folder = run_dir / "Data" / f"kind_{{kind}}"
    folder.mkdir(parents=True)
    for i in range(200):
        (folder / f"record_{{i:03d}}.xml").write_bytes(b"<x/>")
blocked = threading.Event()
real_unlink = os.unlink


def unlink(path, *args, **kwargs):
    if not blocked.is_set():
        blocked.set()
        threading.Event().wait(60)
    return real_unlink(path, *args, **kwargs)


os.unlink = unlink
threading.Thread(target=pe.WorkingFolder(run_dir, marker).delete, daemon=True).start()
blocked.wait(60)
with open(signal + ".tmp", "w", encoding="utf-8") as published:
    published.write(str(run_dir))
os.replace(signal + ".tmp", signal)
"""
# How long the child may take to exit once main has returned. It takes well
# under a second; a ThreadPoolExecutor's threads held it for the whole minute.
_EXIT_SECONDS = 10


def test_python_exits_while_a_delete_still_runs(tmp_path):
    """A close past its deadline leaves the working folder's delete running
    on a thread Python does not wait for, and the process must still end
    then. Python joined a ThreadPoolExecutor's threads at exit after every
    batch queued, so the child lived until its blocked delete returned (and
    with one that never returns, for ever). The marker file is left, so the
    next sweep takes the folder at once. On the base interpreter, as the
    other child tests run, so a kill on failure leaves no launcher child."""
    root = Path(__file__).resolve().parents[1]
    script = tmp_path / "exit_child.py"
    script.write_text(_EXIT_CHILD.format(root=str(root)), encoding="utf-8")
    parent = tmp_path / "cache"
    parent.mkdir()
    signal = tmp_path / "main_returns"
    python = getattr(sys, "_base_executable", None) or sys.executable
    child = subprocess.Popen([python, str(script), str(parent), str(signal)], cwd=root,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 60
        while not signal.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        if not signal.exists():
            child.kill()
            pytest.fail(f"the child never began its delete: {child.communicate()[1]!r}")
        try:
            _out, err = child.communicate(timeout=_EXIT_SECONDS)
        except subprocess.TimeoutExpired:
            pytest.fail(f"the child was still running {_EXIT_SECONDS} s after main returned")
        assert child.returncode == 0, err
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate()
    run_dir = Path(signal.read_text(encoding="utf-8"))
    assert (run_dir / pe._SCRATCH_MARKER).is_file()
    pe._sweep_stale_scratch(parent, pe.DATAFORGE_SCRATCH_PREFIX)
    assert not os.path.lexists(run_dir)


def test_a_held_file_fails_the_attempt_and_the_whole_tree_is_tried_again(
    tmp_path, monkeypatch, caplog
):
    """A file another program holds (here, open without delete sharing, as
    antivirus holds one) fails the first attempt. Its holder lets go during
    the wait, and the second attempt deletes it with the folders."""
    tree = tmp_path / "tree"
    files = _fill_tree(tree)
    held = open(files[5], "rb")
    asked = []

    def sleep(seconds):
        asked.append(seconds)
        held.close()

    monkeypatch.setattr(pe.time, "sleep", sleep)
    try:
        with caplog.at_level(logging.WARNING, logger=pe.logger.name):
            pe.robust_rmtree(tree, attempts=3)
    finally:
        held.close()

    assert not os.path.lexists(tree)
    assert asked == [0.2]
    warnings = [r.getMessage() for r in caplog.records]
    assert len(warnings) == 1 and warnings[0].endswith("retrying in 0.2s")


@pytest.mark.parametrize("attempts, waits", [
    (1, []),
    (2, [0.2]),
    (6, [0.2, 0.4, 0.8, 1.6, 3.0]),
], ids=["one attempt", "the sweep's two", "the default six"])
def test_the_last_failure_is_raised_without_a_wait(tmp_path, sleeps, caplog, attempts, waits):
    """The error is Windows' own, for the held file, as rmtree's hook raised
    it before, and every other file is gone. There is a wait between two
    attempts and none after the last."""
    tree = tmp_path / "tree"
    files = _fill_tree(tree)
    with open(files[5], "rb"):
        with caplog.at_level(logging.WARNING, logger=pe.logger.name):
            with pytest.raises(PermissionError) as raised:
                pe.robust_rmtree(tree, attempts=attempts)
        left = [p for p in tree.rglob("*") if p.is_file()]

    assert raised.value.winerror == 32
    assert Path(raised.value.filename).name == files[5].name
    assert left == [files[5]]
    assert sleeps == waits
    warnings = [r.getMessage() for r in caplog.records]
    assert len(warnings) == attempts
    assert warnings[-1].endswith("giving up")


def test_a_delete_threads_failure_keeps_no_marker_open(tmp_path, monkeypatch):
    """A delete thread's exception that is not an OSError (a MemoryError,
    say) is raised again on the calling thread. Its traceback held the frames
    whose failure list held it, a reference cycle that kept a working
    folder's marker open until the cyclic GC ran, so a sweep straight after
    skipped the folder. With the cyclic GC off, the marker is closed as soon
    as the exception and the WorkingFolder holding the marker are dropped,
    and the next sweep takes the folder (perf proposal review). The
    background delete worker drops its WorkingFolder before it sets done
    (test_extraction_stop.py's TestTheDeletesFinishedSlot)."""
    real_unlink = pe._unlink_files

    def boom(_paths):
        raise MemoryError()

    run_dir, marker = pe._open_scratch(tmp_path, pe.DATAFORGE_SCRATCH_PREFIX)
    for i in range(5):
        path = run_dir / "Data" / f"f{i}.bin"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    folder = pe.WorkingFolder(run_dir, marker)
    marker_alive = weakref.ref(marker)
    del marker
    monkeypatch.setattr(pe, "_unlink_files", boom)
    gc_was_on = gc.isenabled()
    gc.disable()
    try:
        # Not pytest.raises, whose ExceptionInfo would keep the traceback.
        try:
            folder.delete()
        except MemoryError:
            pass
        else:
            pytest.fail("the delete thread's MemoryError was not raised")
        del folder
        assert marker_alive() is None
        monkeypatch.setattr(pe, "_unlink_files", real_unlink)
        pe._sweep_stale_scratch(tmp_path, pe.DATAFORGE_SCRATCH_PREFIX)
        assert not run_dir.exists()
    finally:
        if gc_was_on:
            gc.enable()
