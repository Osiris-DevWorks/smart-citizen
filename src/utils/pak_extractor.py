"""Extracts files from Star Citizen's Data.p4k using bundled unp4k.exe."""
import atexit
import errno
import gc
import logging
import math
import os
import queue
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import NamedTuple, Optional

from src.utils.perf import timed

from src.utils.i18n import tr
from src.utils.onedrive import is_onedrive_path
from src.utils.win_paths import win_long_path as _win_long_path
from src.utils.win_paths import win_plain_path

logger = logging.getLogger(__name__)

# DataForge-cache freshness stamps, written after extraction and read by
# dataforge_cache_is_fresh. Size is the primary signal (#209); mtime is the
# legacy fallback for caches written before the size stamp existed.
P4K_MTIME_STAMP = ".p4k_mtime"
P4K_SIZE_STAMP = ".p4k_size"

# base.ini's freshness stamp, beside it in the channel's cache folder (perf
# proposal): the size of the Data.p4k it was extracted from, then base.ini's
# own size. Written by extract_global_ini and read by base_ini_is_fresh, by
# the same size rule as the DataForge stamps above.
BASE_INI_STAMP = ".base_ini_stamp"

# Layout inside a DataForge cache folder: unforge's libs/ tree is kept under
# raw/, and the records everything reads sit in foundry/records inside it.
# Every module that reads or writes the cache joins these rather than
# spelling the segments out (root CLAUDE.md, "Magic literals").
DATAFORGE_LIBS_SUBPATH = Path("raw") / "libs"
DATAFORGE_RECORDS_UNDER_LIBS = Path("foundry") / "records"
DATAFORGE_RECORDS_SUBPATH = DATAFORGE_LIBS_SUBPATH / DATAFORGE_RECORDS_UNDER_LIBS
# The enhancements generator's lookup pickles (_cached_lookup) sit beside
# raw/ in this folder, and EnhancementsGeneratorWorker sweeps the temp files
# a hard kill leaves there, so the two join this one name.
DATAFORGE_LOOKUPS_SUBPATH = Path(".lookups")

# The folder unforge writes beside Game2.dcb in the working folder. The cache
# keeps its contents under DATAFORGE_LIBS_SUBPATH; the two are separate names
# that happen to end alike.
_UNFORGE_LIBS_DIR = "libs"

# ``shutil.rmtree`` replaced ``onerror`` with ``onexc`` in Python 3.12. The
# frozen build runs on 3.11, so passing ``onexc=`` raises TypeError there.
# Detect once at import.
_RMTREE_CB_KWARG = "onexc" if sys.version_info >= (3, 12) else "onerror"

# The RSI Launcher holds an exclusive lock on Data.p4k while it downloads or
# verifies a game update, so unp4k (which opens Data.p4k directly) dies with a
# .NET IOException whose message contains "being used by another process"
# (exit code 0xE0434352 = 3762504530, the generic managed-exception code — so
# the message text, not the code, is the reliable signal). Detect it and give
# the user a plain "your install is updating, wait and retry" hint instead of
# a raw stack trace.
_P4K_LOCKED_SIGNATURE = "being used by another process"

# unp4k catches an archive entry it cannot extract, prints "Exception while
# extracting <entry>: <message>" and goes on to exit 0, so a run could pass
# with its file missing or cut short. unforge does the same with "Error
# converting <file>: <message>" when anything in its conversion fails, from
# reading the dcb to saving a file (one catch around it all), which can leave
# a partial tree that passes _unforge_records and would be stamped as a
# complete cache. Either one fails the run as a non-zero exit does (perf
# proposal), so a dcb unforge cannot read fails at this check, before the
# libs/ one. Nothing is required of their output on success. Both texts are
# copies of literals in odw-fast-unp4k's src/unp4k/Program.cs and
# src/unforge.cli/Program.cs, and tests/test_extraction_working_folder.py
# checks the bundled exes still hold them.
_UNP4K_ENTRY_FAILED = "Exception while extracting"
_UNFORGE_FILE_FAILED = "Error converting"


class P4kLockedError(RuntimeError):
    """Data.p4k is locked by another process (RSI Launcher updating/verifying).

    A RuntimeError subclass, not a plain RuntimeError, so P4kExtractWorker /
    DataForgeExtractWorker (workers.py) can tell this anticipated, already-
    friendly-messaged condition apart from a genuinely unexpected extraction
    failure — via isinstance(), not by re-sniffing the message text a second
    time. Both workers' blanket ``except Exception`` handlers otherwise call
    logger.exception() unconditionally, which independently satisfies
    MainWindow's global ErrorDialogHandler (error_dialog.py, triggers on any
    ERROR-level log record app-wide) — so downgrading only the log call
    inside _raise_unp4k_failure wasn't enough; the worker's own logging needed
    the same treatment, and needed a reliable way to recognize this case."""


class DataForgeTimeoutError(RuntimeError):
    """unforge.exe ran past its timeout converting the DataForge database.

    A RuntimeError subclass for the same reason as P4kLockedError above: an
    anticipated condition that carries its own friendly message, which
    DataForgeExtractWorker recognises via isinstance() so its blanket
    ``except Exception`` does not log at ERROR and fire the global
    ErrorDialogHandler on top of the dialog the ``error`` signal already
    shows.

    Overwhelmingly this means the game install is inconsistent rather than
    the machine being slow. Measured on a healthy 4.9.188.23497 install,
    unforge converts the 330 MB Game2.dcb in about 40 seconds against a
    1800 second budget. Issue #370 was a user whose Data.p4k carried a
    114 MB ``Game.dcb`` while their build_manifest.id was byte-for-byte
    identical to a working install's: a patch that never finished applying
    to the 160 GB archive. unforge sat on the mismatched database until the
    timeout while their memory climbed, and all the user saw was "DataForge
    extraction failed" with no mention of a timeout at all.
    """


class NotEnoughSpaceError(RuntimeError):
    """A drive an extraction writes to is short of free space (#482).

    Raised before anything is written when the free-space check finds a drive
    short, by the check just before the old DataForge cache is wiped, and when
    a write fails because a drive filled up. The message is user-ready (tr()
    at raise time, as for P4kLockedError) and the byte counts were logged in
    English at WARNING first. ``shortages`` keeps them for tests. A
    RuntimeError subclass for the same reason as P4kLockedError, and never an
    OSError, so no ``except OSError`` mistakes a full drive for a folder that
    cannot be made."""

    def __init__(self, message: str, shortages=()):
        super().__init__(message)
        self.shortages = tuple(shortages)


class _WorkDriveShort(NotEnoughSpaceError):
    """The drive the working folder would go on is short, and the caller
    moves the work to %TEMP% instead of refusing (#482, decision 1: the
    global.ini extraction beside the cache). _begin_scratch always catches
    it; a NotEnoughSpaceError still, should one ever get past."""


class WorkingFolderRefusedError(RuntimeError):
    """Windows would not make an extraction's working folder (#490): the
    folder's permissions deny Smart Citizen or Controlled Folder Access
    blocks it, or the drive cannot be written (write-protected, failing, or
    a file in the way held by another program), which the message gives in
    Windows' own words (see windows_refused).

    Raised before any tool runs, for DataForge at once and for the global.ini
    extraction only when %TEMP% refuses too, since it moves its work there
    first (#471). The message is user-ready (tr() at raise time, as for
    P4kLockedError) and names the folder, and the Windows error was logged
    in English at WARNING first. ``folder`` keeps the folder for tests. A
    RuntimeError for the same reason as NotEnoughSpaceError: never an
    OSError, so no ``except OSError`` reads it as a folder to try somewhere
    else."""

    def __init__(self, message: str, folder: str = ""):
        super().__init__(message)
        self.folder = folder


class CacheFolderIsLinkError(RuntimeError):
    """The DataForge cache folder is a link to another folder (#491): a
    junction or a symbolic link, made by hand, usually to keep the cache on
    another drive. Step 3 wipes the cache folder with shutil.rmtree, which
    deletes nothing through a link, so every re-extract met the old cache
    after unforge and failed with a raw FileExistsError. Nothing is ever
    deleted through a link, so the run is refused before anything runs, and
    the old cache and the link stay as they were.

    The message is user-ready (tr() at raise time, as for P4kLockedError),
    names the folder and the folder it leads to, and says to choose that
    one in the Config tab instead. ``folder`` and ``target`` keep both for
    tests. A RuntimeError for the same reason as NotEnoughSpaceError."""

    def __init__(self, message: str, folder: str = "", target: str = ""):
        super().__init__(message)
        self.folder = folder
        self.target = target


class LinkedFolderError(OSError):
    """robust_rmtree was asked to delete a link (#491): a junction or a
    symbolic link, which shutil.rmtree refuses, deleting nothing. An
    OSError, so a caller's ``except OSError`` reports it as a folder that
    could not be deleted, and robust_rmtree never tries it again."""


class ExtractionCancelled(Exception):
    """A stop request ended the extraction (#471): Smart Citizen is closing,
    or the user stopped it from the progress dialog.

    Deliberately not a RuntimeError, unlike P4kLockedError and
    DataForgeTimeoutError above. Those are failures with a friendly message;
    this is not a failure at all, so no ``except RuntimeError`` anywhere may
    swallow or misreport it. The extraction workers catch it ahead of their
    other handlers, log at INFO and emit no error, because an ERROR record
    would fire the global ErrorDialogHandler for something the user asked
    for."""


# Failures that carry their own user-ready message and were logged at WARNING
# where they were raised. The extraction workers report them without
# logger.exception, which would open the global error dialog on top of the
# box their error signal opens.
ANTICIPATED_EXTRACTION_ERRORS = (
    P4kLockedError, DataForgeTimeoutError, NotEnoughSpaceError, WorkingFolderRefusedError,
    CacheFolderIsLinkError,
)


def _raise_if_cancelled(should_cancel, where: str) -> None:
    if should_cancel is not None and should_cancel():
        raise ExtractionCancelled(where)


# A Data.p4k changed this recently is treated as still being patched (#516).
# The RSI Launcher writes the archive in place for the whole of a patch, so
# its modified time keeps moving until the patch ends.
_P4K_RECENT_WRITE_SECONDS = 120

_ERROR_SHARING_VIOLATION = 32


def _p4k_has_writer(p4k_path: Path) -> bool:
    """True when another program has Data.p4k open for writing (#516).

    Opens the file for reading while sharing it for reading only. Windows
    refuses that open with a sharing violation while any other handle on the
    file can write, which is the RSI Launcher patching it. The game and an
    idle launcher only read it, so they pass. Any other failure (the file is
    gone, access denied) is left to the extraction itself to report, and is
    False here. Always False off Windows."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileW.argtypes = (
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
        )
        k32.CreateFileW.restype = wintypes.HANDLE
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    except Exception:
        return False
    generic_read, file_share_read, open_existing = 0x80000000, 0x1, 3
    invalid_handle = wintypes.HANDLE(-1).value
    handle = k32.CreateFileW(_win_long_path(p4k_path), generic_read, file_share_read,
                             None, open_existing, 0, None)
    if handle == invalid_handle or handle is None:
        return ctypes.get_last_error() == _ERROR_SHARING_VIOLATION
    k32.CloseHandle(handle)
    return False


def _p4k_changed_recently(p4k_path: Path, now: Optional[float] = None) -> bool:
    """True when Data.p4k was modified in the last _P4K_RECENT_WRITE_SECONDS
    (#516). A modified time in the future (a clock that moved) is not
    counted, nor is a file whose time cannot be read."""
    try:
        age = (time.time() if now is None else now) - os.stat(_win_long_path(p4k_path)).st_mtime
    except OSError:
        return False
    return 0 <= age < _P4K_RECENT_WRITE_SECONDS


def _refuse_if_p4k_being_written(p4k_path: Path) -> None:
    """Raise P4kLockedError before any tool runs when Data.p4k is being
    written (#516): another program has it open for writing, or it changed
    in the last couple of minutes.

    The launcher does not always lock the archive against readers while it
    patches. When it doesn't, unp4k reads a half-written archive and crashes
    inside SharpZipLib's ReadEntries (#516), or hands unforge a database that
    does not match the build. Refusing up front gives the same "wait for the
    launcher, then try again" message as the locked case."""
    if _p4k_has_writer(p4k_path):
        reason = "another program has it open for writing"
    elif _p4k_changed_recently(p4k_path):
        reason = f"it changed in the last {_P4K_RECENT_WRITE_SECONDS} seconds"
    else:
        return
    logger.warning(f"Not extracting from {p4k_path}: {reason} (game likely updating)")
    raise P4kLockedError(tr("extract.p4k_locked"))


def _raise_unp4k_failure(returncode: int, output: str) -> None:
    """Raise for a failed unp4k run — P4kLockedError for a locked Data.p4k,
    plain RuntimeError otherwise. A run has failed when it exits non-zero,
    or exits 0 after an entry it says it could not extract (_check_unp4k).

    Upgrades the generic "exited with code N" message to a clear "Star Citizen
    is updating, wait and retry" hint when the failure is Data.p4k being locked
    by another process (the common case — the user launched an extract while
    the RSI Launcher was patching). Always logs the raw output first so the Log
    tab keeps the underlying technical detail even when the friendly message is
    shown. Never returns — always raises.

    Logged at WARNING, not ERROR, for the locked-file case specifically — see
    P4kLockedError's docstring for why. Any OTHER unp4k failure still logs at
    ERROR — those are genuinely unexpected and should still surface through
    the generic handler."""
    output = output or ""
    how = f"exited with code {returncode}"
    if not returncode:
        how += " but could not extract a file"
    if _P4K_LOCKED_SIGNATURE in output.lower():
        logger.warning(
            f"unp4k.exe {how} — Data.p4k is locked "
            f"(game likely updating); output:\n{output[:2000]}"
        )
        raise P4kLockedError(tr("extract.p4k_locked"))
    logger.error(f"unp4k.exe {how}; output:\n{output[:2000]}")
    raise RuntimeError(f"unp4k.exe {how}.\n\n{output}")


def _check_unp4k(result) -> None:
    """Log unp4k's stdout at INFO, truncated as unforge's is (its "Found N
    files to extract." says what the filter matched), then raise through
    _raise_unp4k_failure when the run failed: a non-zero exit, or an entry
    it says it could not extract (_UNP4K_ENTRY_FAILED, perf proposal)."""
    stdout = (result.stdout or "").strip()
    if stdout:
        logger.info(f"unp4k stdout ({len(stdout)} bytes, truncated): {stdout[:2000]}")
    if result.returncode != 0:
        _raise_unp4k_failure(result.returncode, result.stderr or result.stdout)
    if _UNP4K_ENTRY_FAILED in f"{result.stdout or ''}\n{result.stderr or ''}":
        _raise_unp4k_failure(result.returncode,
                             "\n".join(filter(None, (result.stderr, result.stdout))))


def _unforge_timeout_error(exc, dcb_path: Path, dcb_mb: float,
                           p4k_path: Path) -> DataForgeTimeoutError:
    """Log everything the timeout knows and build the error to raise.

    Two things the previous bare propagation threw away.

    First, the diagnostics. On Windows ``subprocess.run`` kills the child and
    re-collects its output onto the exception (``exc.stdout``/``exc.stderr``)
    precisely so a timeout is not silent, but nothing caught the exception, so
    that output went in the bin. The normal success path logs unforge's output
    a few lines below; the one failure that most needs it logged nothing.

    Second, which database it was chewing on. The name and size are the whole
    diagnosis: a healthy install yields Game2.dcb at ~330 MB, and #370's
    stalled one yielded Game.dcb at 114 MB. Without both in the log there is
    no way to tell a mismatched install from a slow machine, and the two need
    opposite advice.

    Returns the exception rather than raising it, so the caller's `raise`
    is visible at the call site. Raising from in here would leave `result`
    statically possibly-unbound after the try block, resting on an implicit
    "this never returns" contract that a later edit could quietly break into
    a confusing NameError."""
    def _decode(v) -> str:
        if not v:
            return ""
        return v if isinstance(v, str) else v.decode("utf-8", "replace")

    out = _decode(getattr(exc, "stdout", None)).strip()
    err = _decode(getattr(exc, "stderr", None)).strip()
    logger.warning(
        f"unforge.exe timed out after {exc.timeout:.0f}s on {dcb_path.name} "
        f"({dcb_mb:.0f} MB). A healthy install converts in well under a "
        f"minute, so this usually means Data.p4k does not match the "
        f"installed build (see issue #370)."
    )
    if out:
        logger.warning(f"unforge partial stdout ({len(out)} bytes, truncated): {out[:2000]}")
    if err:
        logger.warning(f"unforge partial stderr ({len(err)} bytes, truncated): {err[:2000]}")
    return DataForgeTimeoutError(
        tr("extract.dataforge_timeout", dcb=dcb_path.name,
           size=f"{dcb_mb:.0f}", path=str(p4k_path))
    )


def _is_link(st) -> bool:
    """True when the ``lstat`` result *st* is a link by shutil.rmtree's own
    rule (#491): a symbolic link, or a junction (which is also how a drive
    mounted in a folder looks). rmtree never goes through one."""
    return bool(stat.S_ISLNK(st.st_mode)
                or (getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                    and getattr(st, "st_reparse_tag", 0) == stat.IO_REPARSE_TAG_MOUNT_POINT))


def linked_folder_target(path) -> Optional[str]:
    """Where *path* leads when it is a link that shutil.rmtree will not
    delete through (#491): a symbolic link, or a junction (which is also how
    a drive mounted in a folder looks). The rule is rmtree's own. None when
    *path* is not a link or is not there. Read without following the link,
    so a link whose target is gone counts too. The target is the folder at
    the end of the link, any link on the way followed, with no long-path
    prefix. Where that cannot be read (realpath raises for an error it does
    not expect while it follows the link, such as a network that cannot be
    reached) it is the link's own text, and "" when even that cannot be
    read."""
    try:
        st = os.lstat(path)
    except OSError:
        return None
    if not _is_link(st):
        return None
    for read in (os.path.realpath, os.readlink):
        try:
            return win_plain_path(read(path))
        except OSError:
            continue
    return ""


def linked_cache_folder_error(leaf) -> Optional[CacheFolderIsLinkError]:
    """The refusal for a DataForge cache folder *leaf* that is a link
    (#491), or None when it is not one. Logs the link at WARNING. Asked by
    MainWindow._run_dataforge_extraction before any worker exists, and by
    extract_dataforge before anything runs."""
    target = linked_folder_target(leaf)
    if target is None:
        return None
    folder = win_plain_path(leaf)
    logger.warning(f"The DataForge cache folder {folder} is a link to {target}; "
                   "an extraction deletes nothing through a link, so it was refused")
    return CacheFolderIsLinkError(
        tr("extract.cache_folder_is_link", folder=folder, target=target),
        folder=folder, target=target)


# robust_rmtree deletes a tree's files with this many threads before
# shutil.rmtree removes the folders (perf proposal). A delete is mostly
# Windows' own work (the file system, antivirus), done outside Python's lock,
# so several overlap well. Measured on this PC on a 30,000-file tree shaped
# like the DataForge records: rmtree alone took 3.9 to 5.1 s, with 8 threads
# 1.3 to 1.4 s, and 16 threads were no faster than 8.
_DELETE_THREADS = min(8, os.cpu_count() or 1)
# Files handed to one thread at a time: one job per file would cost more to
# hand out than to delete, and one per folder would leave a folder with
# thousands of files to a single thread.
_DELETE_BATCH = 64
# Set once Python begins to exit (perf proposal). The threaded pass then
# hands out no more batches, and its threads drop the ones still queued.
_EXITING = threading.Event()
atexit.register(_EXITING.set)


def _unlink_files(paths) -> None:
    """Delete each file in *paths*, clearing the read-only bit and trying
    once more when the first try fails. A file that still will not go is
    left for shutil.rmtree, which meets it again and reports it, so this
    never raises an OSError."""
    for path in paths:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        except OSError:
            try:
                os.chmod(path, stat.S_IWRITE)
                os.unlink(path)
            except OSError:
                pass


def _delete_batches(batches: queue.Queue, failed: list) -> None:
    """One thread of _delete_files_first: deletes each batch of files it is
    handed until it gets None. Once Python has begun to exit, or another of
    these threads has failed, it drops each batch it gets instead, so the
    walking thread is never left waiting on a full queue. An exception
    (never an OSError, which _unlink_files keeps to itself) goes in *failed*
    for the walking thread to raise."""
    while True:
        batch = batches.get()
        if batch is None:
            return
        if failed or _EXITING.is_set():
            continue
        try:
            _unlink_files(batch)
        except BaseException as e:   # raised again on the walking thread
            failed.append(e)


def _delete_files_first(top: str) -> None:
    """Delete the plain files under the folder *top* with _DELETE_THREADS
    threads (perf proposal), leaving shutil.rmtree, which robust_rmtree runs
    next, the folders and whatever would not go.

    It walks by rmtree's own rule: it goes into a folder only when that is a
    real folder, never a junction or a symbolic link, and deletes only plain
    files. So every link, *top* itself or one inside it, is left to rmtree,
    which refuses the first (#491) and unlinks the others without following
    them, as before. A folder it cannot list is left to rmtree too, which
    reports it. Never raises an OSError.

    The threads are daemon threads, handed a few batches ahead through a
    bounded queue, so Python's exit never waits for them. A
    ThreadPoolExecutor's threads were joined at exit only after every batch
    queued had run, and the walk queues nearly the whole tree while the
    first deletes run: a close past its wait kept the hidden process alive
    until the tree was gone, or for ever behind one delete that blocked. Once
    Python has begun to exit (_EXITING) the walk stops and the queued
    batches are dropped. rmtree then goes on with the rest on the calling
    thread, which Python does not wait for either (a QThread in the app),
    and what the process does not finish is left with the working folder's
    marker file for the next extraction's sweep (_close_scratch deletes the
    marker last). Where Python starts no new thread (while it exits, from
    3.12) rmtree deletes it all, one file at a time."""
    try:
        st = os.lstat(top)
    except OSError:
        return
    if not stat.S_ISDIR(st.st_mode) or _is_link(st):
        return
    # Twice as many batches as threads: enough that no thread waits for the
    # walk, few enough that dropping them at exit costs nothing.
    batches = queue.Queue(maxsize=2 * _DELETE_THREADS)
    failed: list = []
    threads: list = []
    may_start = True
    try:
        folders = [top]
        while folders and not failed and not _EXITING.is_set():
            folder = folders.pop()
            files = []
            try:
                with os.scandir(folder) as listing:
                    for entry in listing:
                        try:
                            st = entry.stat(follow_symlinks=False)
                        except OSError:
                            continue
                        if stat.S_ISDIR(st.st_mode) and not _is_link(st):
                            folders.append(entry.path)
                        elif stat.S_ISREG(st.st_mode):
                            files.append(entry.path)
            except OSError:
                continue
            for start in range(0, len(files), _DELETE_BATCH):
                if failed or _EXITING.is_set():
                    break
                # One thread more for each batch, up to _DELETE_THREADS, as
                # a pool starts them, so a small tree starts only a few.
                if may_start and len(threads) < _DELETE_THREADS:
                    thread = threading.Thread(target=_delete_batches, args=(batches, failed),
                                              name="robust_rmtree", daemon=True)
                    try:
                        thread.start()
                        threads.append(thread)
                    except RuntimeError:
                        may_start = False
                if not threads:
                    return   # no thread to be had: rmtree deletes it all
                batches.put(files[start:start + _DELETE_BATCH])
    finally:
        for _ in threads:
            batches.put(None)
        for thread in threads:
            thread.join()
    if failed:
        # Emptied as it is raised: the exception's traceback holds the frames
        # whose `failed` holds the exception, a cycle that kept everything in
        # those frames (a working folder's marker, up the stack) alive until
        # the cyclic GC ran, so a sweep straight after skipped the folder.
        try:
            raise failed[0]
        finally:
            failed.clear()


def robust_rmtree(path: Path, attempts: int = 6) -> None:
    """Delete *path* recursively, surviving transient Windows locks.

    On Windows — especially when the target lives under OneDrive — rmtree
    often trips over three things:

    1. Read-only attribute on files unp4k/unforge just wrote. Clearing the
       bit via ``os.chmod(.., stat.S_IWRITE)`` lets the retry succeed.
    2. A ghost handle from the just-exited ``unforge.exe`` child process
       (or Windows Defender / Search Indexer / OneDrive client) that
       releases a beat later. A short sleep-and-retry loop clears these.
    3. A non-empty directory whose children are mid-delete. Re-walking the
       tree on each attempt catches files added or unlocked between tries.

    Each attempt deletes the files with several threads first
    (_delete_files_first, perf proposal: about 3x faster on ~30k files),
    then shutil.rmtree removes the folders bottom-up and anything that
    would not go, one at a time, with the hook below.

    Silently succeeds if *path* doesn't exist. Raises the last error if
    every attempt fails so callers can surface it to the user, without a
    wait after the last attempt (perf proposal).

    A *path* that is a link (a junction or a symbolic link, also one whose
    target is gone) raises LinkedFolderError at once, with nothing deleted
    (#491). rmtree refuses a link and deletes nothing through it, and this
    used to return as if the delete had worked.
    """
    if not os.path.lexists(_win_long_path(path)):
        return

    def _on_error(func, target, *_):
        # Compatible with both 3.11 ``onerror(func, path, excinfo)`` and
        # 3.12+ ``onexc(func, path, exc)`` callback signatures — we only
        # care about the failing path so the trailing arg is ignored.
        # Clear the read-only bit and retry the single failing file/dir;
        # for other errors (e.g. lingering handle), propagate so the
        # outer retry loop picks it up.
        if func is os.path.islink:
            # rmtree refused *target* because it is a link, and returns
            # once this hook does (#491). Calling islink again below only
            # returned a bool, so a delete that never happened read as done.
            raise LinkedFolderError(
                f"{win_plain_path(target)} is a link to "
                f"{linked_folder_target(target) or 'another folder'}, "
                "and nothing is deleted through a link")
        try:
            os.chmod(target, stat.S_IWRITE)
        except OSError:
            pass
        try:
            func(target)
        except OSError:
            raise

    last_err: Exception | None = None
    for i in range(attempts):
        try:
            gc.collect()  # drop any lingering XML file handles we own
            _delete_files_first(_win_long_path(path))
            shutil.rmtree(_win_long_path(path), **{_RMTREE_CB_KWARG: _on_error})
            return
        except LinkedFolderError:
            raise   # trying again changes nothing
        except OSError as e:
            last_err = e
            if i + 1 == attempts:
                # Nothing follows the last attempt, so waiting first only
                # held up the caller (perf proposal).
                logger.warning(f"rmtree {path} attempt {i + 1}/{attempts} failed ({e}); "
                               "giving up")
                break
            # Exponential-ish backoff: 0.2, 0.4, 0.8, 1.6 and 3.0 seconds
            # between the six attempts, 6 s in all, enough to outlast most
            # AV/indexer scans without hanging the UI forever.
            delay = min(0.2 * (2 ** i), 3.0)
            logger.warning(
                f"rmtree {path} attempt {i + 1}/{attempts} failed ({e}); "
                f"retrying in {delay:.1f}s"
            )
            time.sleep(delay)

    raise last_err if last_err else OSError(f"Failed to remove {path}")


# ── Extraction working folders (#471) ────────────────────────────────────────
# unp4k and unforge used to work in tempfile.TemporaryDirectory(), which is
# always under %TEMP% on the system drive. A full DataForge run writes
# Game2.dcb (~317 MB) plus unforge's ~62k XMLs (~1.8 GB) there, so a user who
# moved the DataForge cache off C: still had every extraction hammer C: — on
# an HDD system drive that stalls the whole PC. Each DataForge run now works
# in its own folder beside the cache leaf,
# {base}\{channel}\cache\dataforge.extracting-XXXXXXXX, which is:
#   * on the cache's drive by construction;
#   * outside the leaf, which step 3 wipes and which the freshness check and
#     the generator read;
#   * inside the channel folder the uninstaller's opt-in wipe deletes whole;
#   * never named "dataforge" (installer LooksLikeScCache) or
#     "dataforge.migrating" (the settings.py migrator).
# Unique per run, because two Smart Citizens can run at once: Import
# Settings' relaunch starts the new process before the old one closes, and
# installer.iss suggests sharing one cache between installs.
#
# %TEMP% stays the working place where beside the cache would do harm:
#   * a network share or drive (~1.8 GB of SMB writes);
#   * OneDrive (~62k files queued for sync);
#   * a removable drive (slow flash against unforge's 1800 s budget);
#   * a cache so deep that unp4k's working folder would pass what
#     CreateProcess accepts as a current directory.
# The depth cap is measured, not guessed: unforge wrote all 61,950 records
# with its dcb in a 197-character folder (58,290 of them past 260 characters,
# the longest 368), so it copes with long output paths itself. The dcb folder
# is the run folder plus "\Data", so a cap of 190 stays inside what was
# proven. The global.ini extraction (the English global.ini alone, ~10 MB)
# follows the same rules with its own globalini.extracting-XXXXXXXX folder, so
# nothing Smart Citizen extracts lands in %TEMP% unless one of the fallbacks
# above applies.
#
# Making the folder (#490): one os.mkdir per random name, not
# tempfile.mkdtemp. On Windows mkdtemp takes a PermissionError for a name
# that may be taken and tries the next one. On the Python 3.11 the release
# builds use that is up to os.TMP_MAX (2**31 - 1) times, so a folder Windows
# refuses (its permissions, Controlled Folder Access) kept an extraction
# looking stuck for about 39 hours, at 66 microseconds a try. (Python 3.14.6
# stops after 20.) Here only a name that is taken is tried again, a few
# times, and a refusal fails at once.
#
# Liveness: a run holds an empty .in_use file open until its folder is
# deleted. Python's open() never grants delete sharing on Windows, so no other
# process can delete that file while the run is alive, and Windows closes the
# handle when the process ends for any reason (a crash, a hard kill). The
# sweep at the start of every extraction removes only folders whose marker it
# can delete, which keeps it off a live run in another window.
DATAFORGE_SCRATCH_PREFIX = "dataforge.extracting-"
GLOBAL_INI_SCRATCH_PREFIX = "globalini.extracting-"
_DATAFORGE_TEMP_PREFIX = "SmartCitizen-DataForge-"    # like %TEMP%\SmartCitizen-Update
_GLOBAL_INI_TEMP_PREFIX = "SmartCitizen-GlobalIni-"
_SCRATCH_MARKER = ".in_use"
# The random part of a working folder's name, as long as tempfile.mkdtemp's
# was: hex, two characters per random byte.
_MKDTEMP_RANDOM_CHARS = 8
# How many random names making a working folder tries. Only a name that is
# already taken is tried again, which with 8 hex characters almost never
# happens; a refusal never is (see the comment above).
_SCRATCH_NAME_ATTEMPTS = 10
_MAX_SCRATCH_CHARS = 190
# A folder with no marker is either the instant between making the folder
# and opening the marker, or a removal that got part-way. Only an old one is
# a leftover.
_UNMARKED_SCRATCH_GRACE_SECONDS = 10 * 60
_DRIVE_REMOVABLE, _DRIVE_REMOTE = 2, 4   # GetDriveTypeW

# Free space (#482). Measured on LIVE 4.10 (October 2026): Game2.dcb 317 MiB,
# unforge's tree 61,950 files and 1.84 GB, the kept cache about 30,700 files
# and 1.2 GB, with GB read as GiB (the larger reading). _space_for adds 15%
# for growth between builds and one cluster per file for slack and file
# records. The working folder lives until the kept files are in the cache,
# and the old cache is wiped only just before that. Beside the cache the kept
# files are moved, which needs no new room, but a subtree whose move is
# refused is copied after the wipe (#484). So a run is still sized for a
# copy: both at once unless a stamped cache at the leaf makes room.
# _require_room_for_new_cache logs what each run really wrote, so these can
# be checked against real runs.
_MIB, _GIB = 1 << 20, 1 << 30
_SPACE_GROWTH_PERCENT = 115
_DATAFORGE_WORK_BYTES = 317 * _MIB + math.ceil(1.84 * _GIB)
_DATAFORGE_WORK_FILES = 61_950 + 1           # the tree and the dcb
_DATAFORGE_CACHE_BYTES = math.ceil(1.2 * _GIB)
_DATAFORGE_CACHE_FILES = 30_700
_BASE_INI_BYTES = 11 * _MIB                  # the English global.ini
# unp4k extracts the English global.ini alone (perf proposal): one file,
# measured at 10.1 MB, the same file base.ini is a copy of.
_GLOBAL_INI_WORK_BYTES = _BASE_INI_BYTES
_GLOBAL_INI_WORK_FILES = 1
_NEW_CACHE_RESERVE_BYTES = 64 * _MIB         # the gate: folders, stamps (sized with the manifest)
_DEFAULT_CLUSTER_BYTES = 4096
# ERROR_HANDLE_DISK_FULL, ERROR_DISK_FULL, ERROR_DISK_QUOTA_EXCEEDED. Python
# maps only 112 to ENOSPC (39 and 1295 become EINVAL), so errno alone misses two.
_DISK_FULL_WINERRORS = (39, 112, 1295)


def _drive_is_removable_or_network(path) -> bool:
    """True for a drive letter Windows reports as removable or remote. Best
    effort: any failure keeps the working folder beside the cache."""
    if sys.platform != "win32":
        return False
    drive = os.path.splitdrive(str(path))[0]
    if len(drive) != 2:   # a UNC path, which the caller already sent to %TEMP%
        return False
    try:
        import ctypes
        kind = ctypes.windll.kernel32.GetDriveTypeW(drive + "\\")
    except Exception:
        return False
    return kind in (_DRIVE_REMOVABLE, _DRIVE_REMOTE)


def _scratch_location(plain_leaf: Path, prefix: str = DATAFORGE_SCRATCH_PREFIX,
                      temp_prefix: str = _DATAFORGE_TEMP_PREFIX) -> tuple[Path, str]:
    """Parent folder and name prefix for a run's working folder: beside the
    DataForge cache leaf with *prefix*, or %TEMP% with *temp_prefix* (see the
    comment above). *plain_leaf* carries no long-path prefix."""
    beside = plain_leaf.parent
    run_chars = len(str(beside)) + 1 + len(prefix) + _MKDTEMP_RANDOM_CHARS
    if str(beside).startswith("\\\\"):
        reason = "it is on a network share"
    elif is_onedrive_path(beside):
        reason = "it is inside OneDrive"
    elif run_chars > _MAX_SCRATCH_CHARS:
        reason = f"the working folder would be {run_chars} characters long"
    elif _drive_is_removable_or_network(beside):
        reason = "it is on a removable or network drive"
    else:
        return beside, prefix
    temp = Path(tempfile.gettempdir())
    logger.info(
        f"Extraction working files go to {temp}, not beside the DataForge "
        f"cache in {beside}: {reason}"
    )
    return temp, temp_prefix


def _sweep_stale_scratch(parent: Path, prefix: str, should_cancel=None) -> None:
    """Delete working folders an earlier extraction left in *parent*: a crash,
    a hard kill, or a close that stopped waiting (#471). Skips any folder a
    live run still holds. Never raises an OSError.

    *should_cancel*, when given, is asked before each folder, and a stop
    leaves the rest for a later sweep: closing stops the window's own sweep
    (StaleWorkingFolderSweepWorker, perf proposal) this way."""
    try:
        folders = [p for p in parent.glob(prefix + "*") if p.is_dir()]
    except OSError:
        return
    for folder in folders:
        if should_cancel is not None and should_cancel():
            return
        try:
            os.unlink(_win_long_path(folder / _SCRATCH_MARKER))
        except FileNotFoundError:
            try:
                age = time.time() - folder.stat().st_mtime
            except OSError:
                continue
            if age < _UNMARKED_SCRATCH_GRACE_SECONDS:
                continue
        except OSError:
            continue   # a live run in another window holds its marker open
        try:
            robust_rmtree(folder, attempts=2)
            logger.info(f"Removed a leftover extraction working folder: {folder}")
        except OSError as e:
            logger.warning(f"Could not remove leftover extraction working folder {folder}: {e}")


def _make_run_folder(parent: Path, prefix: str) -> Path:
    """Make a new ``<prefix>XXXXXXXX`` folder in the existing *parent* (#490).

    One os.mkdir per random name. A name that is taken (FileExistsError, or
    a PermissionError for a name that is there, which a folder Windows is
    still deleting can give) is tried again with a new one, up to
    ``_SCRATCH_NAME_ATTEMPTS`` names in all. Any other OSError raises at
    once, so a PermissionError from a folder that refuses new folders fails
    on the first try. Plain os.mkdir, so the folder takes its parent's
    permissions, as mkdtemp's did on the Python 3.11 the release builds use.
    """
    for _ in range(_SCRATCH_NAME_ATTEMPTS):
        run_dir = parent / (prefix + secrets.token_hex(_MKDTEMP_RANDOM_CHARS // 2))
        try:
            os.mkdir(run_dir)
        except FileExistsError:
            continue
        except PermissionError:
            if os.path.lexists(run_dir):
                continue
            raise
        return run_dir
    raise FileExistsError(
        errno.EEXIST,
        f"No free working folder name in {_SCRATCH_NAME_ATTEMPTS} tries",
        str(parent),
    )


def _open_scratch(parent: Path, prefix: str):
    """Make a run's working folder under *parent* and open its marker.
    Returns ``(folder, marker)``; end the run with :func:`_close_scratch`."""
    parent.mkdir(parents=True, exist_ok=True)
    run_dir = _make_run_folder(parent, prefix)
    try:
        marker = open(run_dir / _SCRATCH_MARKER, "w", encoding="utf-8")
    except OSError:
        _close_scratch(run_dir, None)
        raise
    return run_dir, marker


def _close_scratch(run_dir: Path, marker) -> None:
    """Delete the working folder, its marker last. Never raises an OSError: a
    folder that will not go is logged and left for the next extraction's
    sweep, so a cleanup problem Windows reports can never replace the run's
    real outcome (on 3.11, TemporaryDirectory's own cleanup could, even after
    the cache had been stamped). Anything else, such as a MemoryError in a
    delete thread, still gets out.

    Everything but the marker goes while the marker is still held (perf
    proposal), so another window's sweep, which deletes only a folder whose
    marker it can delete, never works on a folder that is still being
    deleted, which can now take a while in the background (see
    WorkingFolder). A crash part-way, or a folder that will not go, leaves
    the marker file, closed, so the next sweep takes the folder at once
    rather than waiting out the grace for an unmarked one. An entry that
    will not go (a file another program holds under Data) does not stop the
    others (perf proposal): the set-aside old cache beside it still goes."""
    failed = None
    try:
        entries = list(os.scandir(_win_long_path(run_dir)))
    except FileNotFoundError:
        entries = []
    except OSError as e:
        entries, failed = [], e
    for entry in entries:
        if entry.name == _SCRATCH_MARKER:
            continue
        try:
            if entry.is_dir(follow_symlinks=False):
                robust_rmtree(Path(entry.path))
                continue
            try:
                os.chmod(entry.path, stat.S_IWRITE)
                os.unlink(entry.path)
            except FileNotFoundError:
                pass
        except OSError as e:
            if failed is None:
                failed = e
    if failed is not None:
        if marker is not None:
            marker.close()
        logger.warning(
            f"Could not remove the extraction working folder {run_dir} ({failed}); "
            "the next extraction removes it"
        )
        return
    try:
        if marker is not None:
            marker.close()
        robust_rmtree(run_dir)
    except OSError as e:
        logger.warning(
            f"Could not remove the extraction working folder {run_dir} ({e}); "
            "the next extraction removes it"
        )


class WorkingFolder:
    """A DataForge run's working folder, handed by extract_dataforge to its
    caller to delete later instead of deleted before it returned (perf
    proposal). It holds Game2.dcb, what unforge wrote that the cache does
    not keep, and the old cache when it was set aside there
    (_set_old_cache_aside). On a re-extract beside the cache that is about
    62,000 files: the ~31,000 unforge wrote that the cache does not keep,
    and the ~31,000 of the old cache. In %TEMP% the old cache is wiped in
    place and the kept files are copied, so the folder holds all of
    unforge's ~62,000, and on a first extraction beside the cache the
    ~31,000 it does not keep and the dcb. Enhancement generation used to
    wait for both halves (6.9 s for unforge's unkept files and about 7 s for
    the old cache on the PC this was measured on, far longer on a slow disk).

    The run's .in_use marker stays open until delete() has removed
    everything else, so another window's sweep leaves the folder alone the
    whole time, as it does a running extraction (#471). A crash before then
    closes the marker with the process, and the next extraction's sweep
    removes the folder, as it does a crashed run's. delete() touches nothing
    outside the folder: the new cache was moved or copied out of it, and the
    folder is beside the cache folder, or in %TEMP% when the work was there,
    never inside the cache folder."""

    def __init__(self, folder: Path, marker):
        self.folder = folder
        self._marker = marker
        self._done = False

    def delete(self) -> None:
        """Delete the folder, its marker last (_close_scratch). Never
        raises an OSError (anything else, such as a MemoryError in a delete
        thread, still gets out). Only the first call (of this or release)
        does anything."""
        if self._done:
            return
        self._done = True
        started = time.monotonic()
        _close_scratch(self.folder, self._marker)
        logger.info(f"Deleting the DataForge working folder after the run took "
                    f"{time.monotonic() - started:.1f} s")

    def release(self) -> None:
        """Close the marker and leave the folder for the next extraction's
        sweep, as a crash would: for a folder nobody will delete now (the
        app is closing). Only the first call (of this or delete) does
        anything."""
        if self._done:
            return
        self._done = True
        try:
            self._marker.close()
        except OSError as e:
            logger.warning(f"Could not close the marker of {self.folder}: {e}")
        logger.info(f"Left the DataForge working folder {self.folder} for the next extraction")


# Python raises a whole range of Windows errors as PermissionError, but only
# these two mean Smart Citizen was denied permission: ERROR_ACCESS_DENIED (a
# folder's permissions, Controlled Folder Access) and
# ERROR_NETWORK_ACCESS_DENIED (a share). The rest of that range (19 to 36: a
# write-protected or failing drive, a file another program holds) is not a
# question of permissions, and its own reason says what is wrong.
_WINDOWS_DENIED_WINERRORS = (5, 65)


def windows_refused(error: OSError) -> bool:
    """True when *error* means Windows denied Smart Citizen permission (#490):
    a PermissionError that is ERROR_ACCESS_DENIED or
    ERROR_NETWORK_ACCESS_DENIED, or has no Windows error code at all."""
    return (isinstance(error, PermissionError)
            and getattr(error, "winerror", None) in (None, *_WINDOWS_DENIED_WINERRORS))


def windows_reason(error: OSError) -> str:
    """Windows' own reason for *error* (its ``strerror``). It is already in
    the user's Windows language, so it is shown as it is, not translated.
    The whole error when it has no reason of its own."""
    return error.strerror or str(error)


def _folder_refused_error(parent: Path, in_temp: bool,
                          error: OSError) -> WorkingFolderRefusedError:
    """What the user is told when Windows will not make a working folder in
    *parent* (#490): the folder, that Windows denied permission there, and
    what to do. Choosing another DataForge cache folder is advised only for
    a folder beside the cache. In %TEMP% it may not help: a DataForge run is
    there because of where its cache folder is (OneDrive, a network or
    removable drive, a deep path), and a global.ini run after the folder
    beside the cache refused, or with no cache folder at all. A
    PermissionError that is not a refusal (see windows_refused) gets
    Windows' own reason instead, with no advice about permissions. Logs the
    Windows error at WARNING."""
    folder = win_plain_path(parent)
    logger.warning(f"Windows refused an extraction working folder in {folder}: {error}")
    if not windows_refused(error):
        return WorkingFolderRefusedError(
            tr("extract.folder_unusable", folder=folder, reason=windows_reason(error)),
            folder=folder)
    fix = tr("extract.folder_refused_fix") if in_temp else tr("extract.folder_refused_fix_cache")
    return WorkingFolderRefusedError(
        tr("extract.folder_refused", folder=folder) + "\n\n" + fix, folder=folder)


def _begin_scratch(near, prefix: str, temp_prefix: str, *,
                   temp_if_refused: bool = False, check_space=None):
    """Sweep earlier leftovers and open this run's working folder (#471):
    beside the DataForge cache folder *near* by the _scratch_location rules,
    or in %TEMP% when *near* is None. Returns ``(folder, marker)``; end the
    run with :func:`_close_scratch`.

    *temp_if_refused* falls back to %TEMP% when the folder beside the cache
    cannot be made (permissions, Controlled Folder Access, a drive turned
    read-only), or when that drive is short of free space (#482). The
    global.ini extraction wants that: it only ever needed %TEMP% before #471,
    and its output goes to the data folder, not the cache. The DataForge run
    does not, because its cache writes go to that same drive and would fail
    anyway, after a minute of unforge.

    A PermissionError making the folder or its marker raises
    WorkingFolderRefusedError (#490), which names the folder, unless
    *temp_if_refused* moves the work to %TEMP% first: the global.ini
    extraction reports a refusal only when %TEMP% refuses too. Any other
    OSError (a drive that is gone, a path too long) is raised as it is, or
    moves the work the same way.

    *check_space(parent, in_temp, movable)*, when given, raises
    NotEnoughSpaceError when the run would not fit with its working folder in
    *parent* (#482). *movable* is *parent* when a shortage on that drive
    moves the work to %TEMP%, and None otherwise. A shortage that includes
    *movable*'s drive then raises _WorkDriveShort, which makes the move; a
    shortage only on drives the move cannot help (the data folder's)
    refuses the run from here. The check runs after both sweeps, so a
    crashed run's leftover is gone before the space is counted, and before
    any folder is made, so a drive with nothing left still gets the clear
    message rather than a raw OSError.
    """
    temp_root = Path(tempfile.gettempdir())

    def attempt(parent, run_prefix, may_move=False):
        in_temp = parent == temp_root
        if check_space is not None:
            check_space(parent, in_temp, parent if may_move else None)
        try:
            return _open_scratch(parent, run_prefix)
        except PermissionError as e:
            if may_move:
                raise   # the work moves to %TEMP% below
            raise _folder_refused_error(parent, in_temp, e) from e

    _sweep_stale_scratch(temp_root, temp_prefix)
    if near is None:
        return attempt(temp_root, temp_prefix)
    plain_leaf = Path(win_plain_path(near))
    parent, run_prefix = _scratch_location(plain_leaf, prefix, temp_prefix)
    _sweep_stale_scratch(plain_leaf.parent, prefix)
    may_move = temp_if_refused and parent != temp_root
    try:
        return attempt(parent, run_prefix, may_move)
    except (OSError, _WorkDriveShort) as e:
        if not may_move:
            raise
        reason = "not enough free space" if isinstance(e, NotEnoughSpaceError) else e
        logger.info(f"Could not work in {parent} ({reason}); working in {temp_root}")
        return attempt(temp_root, temp_prefix)


def _require_cache_can_be_remade(run_dir: Path, leaf: Path) -> None:
    """Refuse a DataForge run that works in %TEMP% when the folder holding
    the cache folder *leaf* will not take a new folder (#494).

    Just before the new cache is saved the run deletes *leaf* and makes it
    again in that same folder. Beside the cache, making the run's working
    folder there has already shown that it can, so nothing more is checked.
    In %TEMP% nothing had: a folder that refuses new folders (its
    permissions, Controlled Folder Access) let the run delete the old cache
    and then fail to make the new one, with a raw error box. Here one empty
    folder is made there and removed again, before any tool runs, and a
    PermissionError is the #490 refusal with the cache advice, the old cache
    untouched. Any other OSError (a drive that is gone) is raised as it is,
    as _begin_scratch does. The folder takes the working folder's prefix,
    so one that cannot be removed is swept by a later DataForge run, as a
    crashed run's leftover is."""
    parent = leaf.parent
    if run_dir.parent == Path(win_plain_path(parent)):
        return
    try:
        parent.mkdir(parents=True, exist_ok=True)
        probe = _make_run_folder(parent, DATAFORGE_SCRATCH_PREFIX)
    except PermissionError as e:
        raise _folder_refused_error(parent, False, e) from e
    try:
        os.rmdir(probe)
    except OSError as e:
        logger.warning(f"Could not remove the test folder {win_plain_path(probe)} ({e}); "
                       "a later DataForge extraction removes it")


# ── Free space (#482) ────────────────────────────────────────────────────────
# Each extraction checks, before it makes its working folder, that every
# drive it writes to has room for what it writes there, and DataForge checks
# again just before it wipes the old cache. Every probe is best effort: one
# that fails is logged and skipped, so measuring never refuses a run.

class _Volume(NamedTuple):
    key: int                 # os.stat().st_dev, the volume serial on Windows
    label: str               # the mount path without its trailing backslash: "D:"
    cluster: int             # bytes per cluster
    caller_free: Optional[int]   # free to this user (NTFS quotas), or None


def _drive_label(plain: str) -> str:
    """The drive a plain path names in its text ("D:", or the share for a
    network path): the label when Windows cannot name the volume itself."""
    return os.path.splitdrive(plain)[0]


def _measure_volume(folder) -> _Volume:
    """The volume an existing *folder* is on. The one probe tests replace.

    ``shutil.disk_usage`` reads the volume's total free space, which ignores
    NTFS per-user quotas, so the caller's own figure comes from
    GetDiskFreeSpaceExW. The label is the mount path GetVolumePathNameW
    gives, which for a folder mounted as a volume is not its drive letter.
    Raises OSError when *folder* cannot be stat'ed; each Windows call falls
    back on its own, as _drive_is_removable_or_network does."""
    key = os.stat(_win_long_path(folder)).st_dev
    plain = win_plain_path(folder)
    label = _drive_label(plain)
    cluster = _DEFAULT_CLUSTER_BYTES
    caller_free = None
    if sys.platform != "win32":
        return _Volume(key, label, cluster, caller_free)
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except Exception:
        return _Volume(key, label, cluster, caller_free)
    try:
        k32.GetVolumePathNameW.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD)
        buffer = ctypes.create_unicode_buffer(1024)
        if k32.GetVolumePathNameW(plain, buffer, len(buffer)) and buffer.value:
            label = buffer.value.rstrip("\\")
    except Exception:
        pass
    try:
        dword_p = ctypes.POINTER(wintypes.DWORD)
        k32.GetDiskFreeSpaceW.argtypes = (wintypes.LPCWSTR, dword_p, dword_p, dword_p, dword_p)
        sectors, sector_bytes, free_clusters, clusters = (wintypes.DWORD() for _ in range(4))
        if k32.GetDiskFreeSpaceW(label + "\\", ctypes.byref(sectors), ctypes.byref(sector_bytes),
                                 ctypes.byref(free_clusters), ctypes.byref(clusters)):
            cluster = sectors.value * sector_bytes.value or _DEFAULT_CLUSTER_BYTES
    except Exception:
        pass
    try:
        ull_p = ctypes.POINTER(ctypes.c_ulonglong)
        k32.GetDiskFreeSpaceExW.argtypes = (wintypes.LPCWSTR, ull_p, ull_p, ull_p)
        to_caller, total, total_free = (ctypes.c_ulonglong() for _ in range(3))
        if k32.GetDiskFreeSpaceExW(_win_long_path(folder), ctypes.byref(to_caller),
                                   ctypes.byref(total), ctypes.byref(total_free)):
            caller_free = to_caller.value
    except Exception:
        pass
    return _Volume(key, label, cluster, caller_free)


def _nearest_existing_folder(path) -> Optional[Path]:
    """*path* or its nearest parent that exists, as a plain path, or None when
    nothing above it exists (a drive that is gone). The free-space calls all
    fail on a folder that does not exist yet."""
    plain = Path(win_plain_path(path))
    for candidate in (plain, *plain.parents):
        try:
            if Path(_win_long_path(candidate)).is_dir():
                return candidate
        except OSError:
            continue
    return None


def _space_for(logical: int, files: int, cluster: int) -> int:
    """Bytes *files* files of *logical* bytes in all take on a drive with
    *cluster*-byte clusters, with the growth margin (see the constants)."""
    return -(-logical * _SPACE_GROWTH_PERCENT // 100) + files * cluster


def _allocated(size: int, cluster: int) -> int:
    """Bytes a file of *size* takes on disk: whole clusters."""
    return -(-size // cluster) * cluster


# The advice a shortage gets: choose another cache folder, free %TEMP%'s
# drive, or free the drive.
_FIX_CACHE, _FIX_TEMP, _FIX_PLAIN = "cache", "temp", "plain"

# Strongest advice first: a drive shared by parts takes the strongest one.
_FIX_ORDER = (_FIX_CACHE, _FIX_TEMP, _FIX_PLAIN)


class _SpaceNeed(NamedTuple):
    folder: object        # where the bytes go; it may not exist yet
    logical: int
    files: int
    # What the run frees on that drive before it needs the room: an old
    # cache of credit bytes in credit_files files, which the run sets aside
    # or wipes, and frees before any copy (see _credit).
    credit: int = 0
    credit_files: int = 0
    fix: str = _FIX_PLAIN


def _credit(part: _SpaceNeed, cluster: int) -> int:
    """Bytes the old cache frees for *part* on a drive with *cluster*-byte
    clusters. Beside the cache the run now sets the old cache aside rather
    than wiping it, and frees it after the run (perf proposal), but the
    credit still holds: on a drive that has room only once the old cache is
    gone it is wiped in place first, as before (_require_room_for_new_cache
    returns True), a move takes no new room, and a copy deletes a set-aside
    cache first (_cache_filtered_records' before_copy). Each file takes at
    least one cluster, so the old cache takes at least its bytes and at
    least a cluster per file, whichever is more. The new cache is charged a
    cluster per file on top, so on a large-cluster drive a byte-only credit
    asked for far more than a re-extract needs."""
    return max(part.credit, part.credit_files * cluster)


def _part_need(part: _SpaceNeed, cluster: int) -> int:
    """Bytes *part* needs on a drive with *cluster*-byte clusters, less what
    the run frees there first."""
    return max(0, _space_for(part.logical, part.files, cluster) - _credit(part, cluster))


class _Shortage(NamedTuple):
    label: str
    folder: str
    free: int
    need: int
    fix: str


def _holds_complete_cache(leaf) -> bool:
    """True when *leaf* holds a stamped cache, which the run sets aside or
    wipes before it fills the new one (see _credit). The same stamp
    config_tab uses as its "populated cache" probe; a cache cut off between
    the wipe and the stamps has none."""
    leaf = Path(_win_long_path(leaf))
    try:
        return (leaf / P4K_MTIME_STAMP).is_file() and (leaf / DATAFORGE_LIBS_SUBPATH).is_dir()
    except OSError:
        return False


def _dataforge_needs(parent, leaf, in_temp: bool):
    """A DataForge run's parts: its working folder in *parent*, and the new
    cache at *leaf*, less the old one when that is complete, which the run
    sets aside or wipes, and frees before any copy (see _credit). Sized for
    a copy of the new cache, the most a run needs when every move is refused
    (#484)."""
    complete = _holds_complete_cache(leaf)
    return (
        _SpaceNeed(parent, _DATAFORGE_WORK_BYTES, _DATAFORGE_WORK_FILES,
                   fix=_FIX_TEMP if in_temp else _FIX_CACHE),
        _SpaceNeed(leaf, _DATAFORGE_CACHE_BYTES, _DATAFORGE_CACHE_FILES,
                   credit=_DATAFORGE_CACHE_BYTES if complete else 0,
                   credit_files=_DATAFORGE_CACHE_FILES if complete else 0,
                   fix=_FIX_CACHE),
    )


def _global_ini_needs(parent, output_path, in_temp: bool):
    """A global.ini run's parts: its working folder in *parent*, and base.ini
    in the data folder. In %TEMP% the advice is the plain one, because the
    run can be there for reasons the "temp" text does not list (no cache
    folder, or a refused or short folder beside the cache)."""
    return (
        _SpaceNeed(parent, _GLOBAL_INI_WORK_BYTES, _GLOBAL_INI_WORK_FILES,
                   fix=_FIX_PLAIN if in_temp else _FIX_CACHE),
        _SpaceNeed(Path(output_path).parent, _BASE_INI_BYTES, 1),
    )


def _free_bytes(folder, volume: _Volume) -> int:
    """Free bytes at an existing *folder*: the smaller of the volume's free
    space and the caller's own (quota-aware) figure. Raises OSError."""
    free = shutil.disk_usage(_win_long_path(folder)).free
    if volume.caller_free is not None:
        free = min(free, volume.caller_free)
    return free


def _require_free_space(needs, intro: str, *, movable=None) -> None:
    """Raise NotEnoughSpaceError when a drive is short for the *needs* that
    land on it. Parts on one volume (by st_dev, which handles subst drives
    and mounted folders) are added together. *intro* opens the message.

    *movable* is the folder of the part the caller moves to %TEMP% when its
    drive is short (decision 1). When that drive is among the short ones,
    this raises _WorkDriveShort and logs the shortage at INFO, because the
    move is not a refusal and the retry logs its own. A shortage only on
    drives the move cannot help is a refusal, logged at WARNING."""
    volumes = {}
    movable_key = None
    for part in needs:
        folder = _nearest_existing_folder(part.folder)
        if folder is None:
            logger.warning(f"Free-space check skipped for {part.folder}: no folder above it exists")
            continue
        try:
            volume = _measure_volume(folder)
            free = _free_bytes(folder, volume)
        except OSError as e:
            logger.warning(f"Free-space check skipped for {folder}: {e}")
            continue
        if movable is not None and part.folder == movable:
            movable_key = volume.key
        need = _part_need(part, volume.cluster)
        group = volumes.setdefault(volume.key, {
            "volume": volume, "free": free, "need": 0,
            "fix": part.fix, "folder": win_plain_path(part.folder),
        })
        group["free"] = min(group["free"], free)
        group["need"] += need
        if _FIX_ORDER.index(part.fix) < _FIX_ORDER.index(group["fix"]):
            group["fix"], group["folder"] = part.fix, win_plain_path(part.folder)
    short = []
    moves = False
    for key, group in volumes.items():
        volume, free, need = group["volume"], group["free"], group["need"]
        logger.info(
            f"Free space on {volume.label} is {free:,} bytes, about {need:,} needed "
            f"({volume.cluster}-byte clusters)"
        )
        if free < need:
            short.append(_Shortage(volume.label, group["folder"], free, need, group["fix"]))
            moves = moves or key == movable_key
    if short:
        summary = "Not enough free space: " + "; ".join(
            f"{s.label} has {s.free:,} bytes free and needs about {s.need:,}" for s in short)
        if moves:
            logger.info(summary)
            raise _no_space_error(intro, short, _WorkDriveShort)
        logger.warning(summary)
        raise _no_space_error(intro, short)


def _size_text(n: int, *, round_up: bool) -> str:
    """*n* bytes as the user reads it, GB with one decimal from 1 GiB up and
    whole MB below (powers of two, as Explorer shows them). Free rounds down
    and the need rounds up, so a short drive never reads as having enough."""
    if n >= _GIB:
        tenths = -(-n * 10 // _GIB) if round_up else n * 10 // _GIB
        return tr("extract.size_gb", whole=tenths // 10, tenth=tenths % 10)
    mb = -(-n // _MIB) if round_up else n // _MIB
    return tr("extract.size_mb", mb=mb)


def _fix_text(shortage: _Shortage) -> str:
    if shortage.fix == _FIX_CACHE:
        return tr("extract.no_space_fix_cache", drive=shortage.label)
    if shortage.fix == _FIX_TEMP:
        return tr("extract.no_space_fix_temp", drive=shortage.label, folder=shortage.folder)
    return tr("extract.no_space_fix", drive=shortage.label)


def _no_space_error(intro: str, shortages, kind=NotEnoughSpaceError) -> NotEnoughSpaceError:
    """The user's message: *intro*, then each short drive with what it has and
    needs, then the advice for each."""
    lines = [intro]
    lines += [tr("extract.no_space_drive", drive=s.label,
                 free=_size_text(s.free, round_up=False),
                 needed=_size_text(s.need, round_up=True)) for s in shortages]
    lines += [_fix_text(s) for s in shortages]
    return kind(
        "\n\n".join(lines),
        shortages=[(s.label, s.folder, s.free, s.need) for s in shortages],
    )


def _is_disk_full(e) -> bool:
    """True when *e* says a drive is full or the user's quota on it is."""
    if isinstance(e, _DiskFullDuringCopy):
        return True
    return isinstance(e, OSError) and (
        e.errno == errno.ENOSPC or getattr(e, "winerror", None) in _DISK_FULL_WINERRORS)


class _DiskFullDuringCopy(RuntimeError):
    """A full drive while the new cache is moved or copied (#484: a rename
    that finds the drive full raises it too). Not an OSError, so
    shutil.copytree stops at once instead of folding it into shutil.Error
    (errno None) and copying on through every remaining file."""


def _copy_file_checked(src, dst, *, follow_symlinks=True):
    """``shutil.copy2`` for copytree, with a full drive raised as
    _DiskFullDuringCopy."""
    try:
        return shutil.copy2(src, dst, follow_symlinks=follow_symlinks)
    except OSError as e:
        if _is_disk_full(e):
            raise _DiskFullDuringCopy(e) from e
        raise


# FILE_ATTRIBUTE_OFFLINE, FILE_ATTRIBUTE_RECALL_ON_OPEN and
# FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS: a file whose data is not on this PC,
# such as a OneDrive online-only file. The directory listing still gives its
# full size, but it takes no space here, so deleting it frees none.
_ONLINE_ONLY_ATTRIBUTES = 0x00001000 | 0x00040000 | 0x00400000


def _walk_files(folder: Path, should_cancel, keep_prefixes=frozenset(), *, local_only=False):
    """Yield ``(size, kept)`` for every file under *folder*, with one
    os.scandir per folder (on Windows its stat, attributes included, comes
    from the directory listing, so no file is opened). *kept* is True under
    a subfolder whose path parts, relative to *folder* and case-folded, are
    in *keep_prefixes*. *local_only* leaves out the files whose data is not
    on this PC. Checks for a stop once per folder."""
    stack = [(Path(folder), (), False)]
    while stack:
        current, rel, kept = stack.pop()
        _raise_if_cancelled(should_cancel, "stopped before the previous cache was replaced")
        with os.scandir(current) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    sub = rel + (entry.name.casefold(),)
                    stack.append((Path(entry.path), sub, kept or sub in keep_prefixes))
                elif entry.is_file(follow_symlinks=False):
                    info = entry.stat(follow_symlinks=False)
                    attributes = getattr(info, "st_file_attributes", 0)
                    if local_only and attributes & _ONLINE_ONLY_ATTRIBUTES:
                        continue
                    yield info.st_size, kept


def _require_room_for_new_cache(libs_dir: Path, leaf: Path, should_cancel) -> bool:
    """The check just before the old cache is wiped (#482): the drive may
    have filled while unforge ran (another program, a second Smart Citizen).
    Counts what copying this run's kept files would take, the most filling
    the cache can need when every move is refused (#484), and logs it, which
    is how the constants above can be checked against real runs. When the
    drive is short, the old cache's own allocation counts as room, since the
    wipe frees it, except for files whose data is not on this PC (OneDrive
    online-only files), which free nothing. Raises NotEnoughSpaceError with
    nothing wiped, its figures counting this run's working folder when it is
    on the cache's drive. Best effort: a walk or a probe that fails is
    logged and the run goes on.

    Returns True when the run goes on only because the old cache's room was
    counted (or the drive is short and that room could not be measured):
    the old cache must then be wiped before the new one is filled, and the
    working folder deleted before the run returns, as before the perf
    proposal. False when the drive has room for a full copy without it, or
    nothing could be measured."""
    keep_prefixes = frozenset(
        tuple(part.casefold() for part in
              (_UNFORGE_LIBS_DIR, *DATAFORGE_RECORDS_UNDER_LIBS.parts, *rel.split("/")))
        for rel in DATAFORGE_KEEP_SUBPATHS
    )
    try:
        work_sizes, kept_sizes = [], []
        for size, kept in _walk_files(libs_dir, should_cancel, keep_prefixes):
            work_sizes.append(size)
            if kept:
                kept_sizes.append(size)
        folder = _nearest_existing_folder(leaf)
        if folder is None:
            logger.warning(f"Could not check the space for the new DataForge cache in {leaf}: "
                           "no folder above it exists")
            return False
        volume = _measure_volume(folder)
        free = _free_bytes(folder, volume)
    except OSError as e:
        logger.warning(f"Could not check the space for the new DataForge cache ({e}); going on")
        return False
    cluster = volume.cluster
    need = sum(max(cluster, _allocated(size, cluster)) for size in kept_sizes)
    need += _NEW_CACHE_RESERVE_BYTES
    logger.info(
        f"DataForge run wrote {len(work_sizes):,} files, {sum(work_sizes):,} bytes. The new "
        f"cache is {len(kept_sizes):,} files, {sum(kept_sizes):,} bytes, about {need:,} on "
        f"{volume.label} ({cluster}-byte clusters), {free:,} free there."
    )
    if free >= need:
        return False
    # Short without the old cache's room from here on: the run goes on only
    # if the old cache is wiped before the new one is filled (perf proposal).
    credit = 0
    try:
        if Path(_win_long_path(leaf)).is_dir():
            credit = sum(_allocated(size, cluster) for size, _kept in
                         _walk_files(_win_long_path(leaf), should_cancel, local_only=True))
    except OSError as e:
        logger.warning(f"Could not measure the old DataForge cache in {leaf} ({e}); going on")
        return True
    if free + credit >= need:
        logger.info(f"The old DataForge cache frees {credit:,} bytes, which makes room")
        return True
    # The user reads the box after the finally has deleted this run's
    # working folder, and a retry makes it again. On the cache's volume its
    # allocation therefore counts in both figures: what the drive has once
    # it is gone, against what a run like this one needs there beyond the
    # old cache.
    work = 0
    try:
        if _measure_volume(libs_dir).key == volume.key:
            work = sum(_allocated(size, cluster) for size in work_sizes)
    except OSError as e:
        logger.warning(f"Could not measure the drive of the working folder "
                       f"{win_plain_path(libs_dir)} ({e})")
    # A retry starts with the up-front check, which asks this drive for the
    # constants rather than what this run measured: the new cache, and the
    # working folder too when it was here. The box must not name less than
    # that, or a retry with the room it says is refused.
    work_part, cache_part = _dataforge_needs(libs_dir, leaf, in_temp=False)
    retry_need = sum(_part_need(part, cluster)
                     for part in ((work_part, cache_part) if work else (cache_part,)))
    box_need = max(need - credit + work, retry_need)
    shortage = _Shortage(volume.label, win_plain_path(leaf), free + work, box_need, _FIX_CACHE)
    logger.warning(
        f"Not enough free space for the new DataForge cache: {volume.label} has {free:,} "
        f"bytes free and {credit:,} more once the old cache goes, and needs about {need:,}. "
        f"The old cache was kept."
        + (f" This run's working folder takes {work:,} bytes there until it is deleted."
           if work else "")
    )
    raise _no_space_error(tr("extract.no_space_dataforge"), [shortage])


def _cache_incomplete_error(leaf, error) -> NotEnoughSpaceError:
    """A drive filled while the new cache was moved, copied or stamped
    (#482). The old cache is gone by then; the new one has no stamp, so the
    startup check offers a re-extract."""
    plain = win_plain_path(leaf)
    label = _drive_label(plain)
    try:
        folder = _nearest_existing_folder(leaf)
        if folder is not None:
            label = _measure_volume(folder).label
    except OSError:
        pass   # best effort: the drive letter is enough
    logger.warning(
        f"Drive {label} ran out of space while the new DataForge cache was "
        f"saved in {plain} ({error}); that cache is incomplete"
    )
    return NotEnoughSpaceError(
        tr("extract.no_space_cache_incomplete", drive=label, folder=plain))


def _remove_stamps(leaf: Path) -> None:
    """Remove both freshness stamps, .p4k_mtime first: every reader needs it
    before it takes a cache for complete (dataforge_cache_is_fresh, the
    Config tab, _holds_complete_cache). Best effort: a stamp that will not go
    is logged."""
    for stamp in (P4K_MTIME_STAMP, P4K_SIZE_STAMP):
        try:
            (leaf / stamp).unlink(missing_ok=True)
        except OSError as e:
            logger.warning(f"Could not remove {stamp} from the DataForge cache in "
                           f"{win_plain_path(leaf)}: {e}")


# Path of global.ini inside the p4k archive (unp4k preserves directory structure)
_GLOBAL_INI_RELATIVE = Path("data/Localization/english/global.ini")

# The filter unp4k gets for it (perf proposal). unp4k extracts every entry
# whose name holds the filter, ignoring case, and names entries with "/"
# (Data/Localization/english/global.ini). "global.ini" alone matched every
# language's file, 11 of them: 20 to 26 s and 9 GB of memory on a 150 GB
# Data.p4k. This one file, byte for byte the same, took 5.4 s and 1.65 GB
# with the release's unp4k.exe, which reads the whole archive's directory
# again for each parallel worker, and takes 2.3 to 2.6 s and under 1 GB with
# the bundled one, built from odw-fast-unp4k eb060c3, which extracts up to 16
# matches through the archive it opened for the listing. A rebuilt unp4k.exe
# without that change keeps the filter's gain but not the rest. Only the
# English file is read from the run; the other languages come from
# community downloads (languages/sources.json).
_GLOBAL_INI_FILTER = _GLOBAL_INI_RELATIVE.relative_to("data").as_posix()


# Subtrees of unforge's ``libs/foundry/records/`` that the enhancement
# generator actually reads. Everything else unforge produces is kept nowhere
# — it goes with the working folder, which extract_dataforge deletes before
# it returns, or hands to *defer_cleanup* after a success.
#
# Keeping this list tight:
#   * halves the final cache's file count (~62k → ~31k) and cuts its disk
#     footprint by about a third (~1.8 GB → ~1.2 GB);
#   * cuts the working folder → cache copy step to ~50% of its old wall-clock (OneDrive
#     / Defender / Indexer fire hooks per-file-close, which dominates copy
#     time on typical Windows installs; since #484 the kept subtrees are
#     moved rather than copied when the work is beside the cache);
#   * makes ``robust_rmtree`` on the old cache roughly 2x faster and less
#     prone to transient WinError 5 retries, since there are half as many
#     files for the AV/indexer stack to hold open briefly.
#
# unp4k and unforge themselves are unaffected — unforge has no filter flag,
# so we still produce the full DCB-expansion into the working folder. The savings
# are on the persistent cache, not on the first-time CPU work.
#
# MAINTENANCE CONTRACT: paths here must cover everything ``scripts/
# generate_enhancements_ini.py`` reads via ``records / ...``. If a future
# generator feature reads a new subtree, add it here or the cache won't
# contain it and enhancements for that subtree will silently be empty.
# ``tests/test_pak_extraction.py`` has a regression test that diffs this
# list against a hardcoded copy of the generator's read-paths so drift is
# caught at test time.
DATAFORGE_KEEP_SUBPATHS: tuple[str, ...] = (
    "entities/scitem",
    "entities/spaceships",
    "entities/missions",
    "entities/contracts",
    "entities/jobterminal",
    "contracts/contractgenerator",
    "contracts/contracttemplates",
    "crafting/blueprintrewards",
    "crafting/blueprints/crafting",
    "missionbroker/pu_missions",
    "ammoparams/vehicle",
    "ammoparams/fps",
    "reputation/rewards/missionrewards_reputation",
    "reputation/standings",
)

# A folder rename is refused while another program holds any file or folder
# under it, even with delete sharing (#484): antivirus, the search indexer,
# a ghost handle of the just-exited unforge (see robust_rmtree). The waits
# before a refused move is tried again, then copied instead. Named so tests
# can shorten them.
_MOVE_RETRY_DELAYS = (0.1, 0.2, 0.4)
_FILE_IN_USE_WINERRORS = (5, 32)   # ERROR_ACCESS_DENIED, ERROR_SHARING_VIOLATION


def _rename_tree(src: Path, dst: Path) -> None:
    """Rename the folder *src* to *dst* (#484). The one call tests replace.
    os.rename, not os.replace: *dst* never exists here, and os.rename refuses
    one that does (WinError 183) where os.replace would put the folder in
    place of a stray file. Long-path prefixed on both sides (#221): a plain
    path past 260 characters fails the rename with WinError 3."""
    os.rename(_win_long_path(src), _win_long_path(dst))


def _move_tree(src: Path, dst: Path) -> Optional[OSError]:
    """Move *src* to *dst* with one rename. Returns None once it has moved,
    or the error that kept it where it was: a rename moves the whole folder
    or nothing. A refusal because another program holds something under it
    (WinError 5 or 32) is tried again after each of _MOVE_RETRY_DELAYS. A
    full drive raises _DiskFullDuringCopy, since a copy could not fit
    either."""
    for delay in (*_MOVE_RETRY_DELAYS, None):
        try:
            _rename_tree(src, dst)
            return None
        except OSError as e:
            if _is_disk_full(e):
                raise _DiskFullDuringCopy(e) from e
            if delay is None or getattr(e, "winerror", None) not in _FILE_IN_USE_WINERRORS:
                return e
            time.sleep(delay)


# The name the old cache takes inside the run's working folder when it is
# set aside rather than wiped (perf proposal). unforge writes only Data\.
_SET_ASIDE_CACHE_NAME = "previous-cache"


def _set_old_cache_aside(leaf: Path, run_dir: Path) -> Optional[Path]:
    """Move the old cache *leaf* into the working folder *run_dir* with one
    rename (perf proposal), so it is deleted with that folder after the run
    instead of before the new cache is filled. The working folder is beside
    the cache, in the same folder, so this is a rename on one drive, as the
    kept subtrees' moves are (#484), with their retries for a held file.

    Returns where the old cache went, or None when it stayed: the rename was
    refused (another program holds a file under it, past the retries), the
    drive is full, a stamp is still there (_remove_stamps could not remove
    it), because nothing may ever read a set-aside cache as fresh, or *leaf*
    is not a folder, which the wipe never deleted either. The caller then
    wipes it in place, as before."""
    if not leaf.is_dir() or any(
            (leaf / stamp).exists() for stamp in (P4K_MTIME_STAMP, P4K_SIZE_STAMP)):
        return None
    target = Path(_win_long_path(run_dir)) / _SET_ASIDE_CACHE_NAME
    try:
        refused = _move_tree(leaf, target)
    except _DiskFullDuringCopy as e:
        refused = e
    if refused is not None:
        logger.info(f"Could not set the old DataForge cache aside ({refused}), "
                    "so it is deleted where it is")
        return None
    logger.info(f"Set the old DataForge cache aside in {win_plain_path(target)}, "
                "to be deleted with the working folder")
    return target


def _unforge_records(src_libs: Path) -> Path:
    """unforge's records folder under *src_libs* (its ``libs/``), or
    FileNotFoundError when its output does not have the layout the cache
    keeps: no records folder, or none of the DATAFORGE_KEEP_SUBPATHS
    subtrees in it. A build can lack some of them, never all."""
    records = src_libs / DATAFORGE_RECORDS_UNDER_LIBS
    if not records.is_dir():
        raise FileNotFoundError(
            f"unforge output missing expected '{DATAFORGE_RECORDS_UNDER_LIBS.as_posix()}/' "
            f"layout at {win_plain_path(records)}"
        )
    if not any((records / rel).exists() for rel in DATAFORGE_KEEP_SUBPATHS):
        raise FileNotFoundError(
            f"unforge output has none of the {len(DATAFORGE_KEEP_SUBPATHS)} subtrees "
            f"the DataForge cache keeps under {win_plain_path(records)}"
        )
    return records


def _cache_filtered_records(src_libs: Path, dst_libs: Path, *, move: bool,
                            before_copy=None) -> tuple[int, int, int]:
    """Put the generator's subtrees from *src_libs* into *dst_libs* (#484).

    Both point at a ``libs/`` folder (unforge's in the working folder, and
    the cache's) holding ``foundry/records/<subtree>``. Only the
    DATAFORGE_KEEP_SUBPATHS subtrees go. Everything else stays in the working
    folder, which extract_dataforge deletes before it returns, or hands to
    *defer_cleanup* after a success.

    With *move*, each subtree is renamed into place: one rename instead of a
    copy of its files one by one, and the working folder then has half as
    much left to delete. A subtree whose rename is refused is still whole
    where unforge wrote it, and is copied instead: another program held a
    file under it past the retries, or the cache folder leads to another
    drive. Without *move* (the working folder is in %TEMP%) every subtree is
    copied, as before #484. The free-space checks are sized for a full copy,
    the most this can need (#482). *before_copy*, when given, is called once
    before the first copy (perf proposal: it deletes an old cache that was
    set aside rather than wiped, so a copy gets the room the checks counted).

    Returns ``(moved, copied, skipped)``. *skipped* counts the subtrees this
    game build does not have (entities/missions and others come and go
    between patches, and the generator checks that each one exists).
    """
    records_src = _unforge_records(src_libs)
    records_dst = dst_libs / DATAFORGE_RECORDS_UNDER_LIBS
    Path(_win_long_path(records_dst)).mkdir(parents=True, exist_ok=True)

    moved = copied = skipped = 0
    for rel in DATAFORGE_KEEP_SUBPATHS:
        src = records_src / rel
        dst = records_dst / rel
        if not src.exists():
            logger.debug(f"DataForge keep-path not in this build, skipping: {rel}")
            skipped += 1
            continue
        Path(_win_long_path(dst.parent)).mkdir(parents=True, exist_ok=True)
        if move:
            refused = _move_tree(src, dst)
            if refused is None:
                moved += 1
                continue
            logger.info(f"Could not move {rel} into the DataForge cache ({refused}), "
                        "so it is copied instead")
        if before_copy is not None:
            before_copy()
            before_copy = None
        # Long-path prefixed on both sides: the deepest entries under
        # entities/scitem/mission_entities/ pass 260 characters once nested
        # under a user's install folder (#221). _copy_file_checked stops the
        # copy at a full drive (#482).
        shutil.copytree(_win_long_path(src), _win_long_path(dst),
                        copy_function=_copy_file_checked)
        copied += 1
    return moved, copied, skipped


def _get_subprocess_kwargs() -> dict:
    """Return subprocess kwargs to suppress window on Windows."""
    kwargs = {"text": True}
    # On Windows, suppress the subprocess window completely
    if sys.platform == "win32":
        # CREATE_NO_WINDOW = 0x08000000
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0x08000000
    return kwargs


# How often a running tool is checked for a stop request, how long a killed
# tool gets to let go of its output pipes, and the budgets the old
# subprocess.run calls had (#471). Named so tests can shorten them.
_TOOL_POLL_SECONDS = 0.25
_TOOL_REAP_SECONDS = 30
_UNP4K_GLOBAL_INI_TIMEOUT_SECONDS = 300
_UNP4K_DCB_TIMEOUT_SECONDS = 600
_UNFORGE_TIMEOUT_SECONDS = 1800   # a healthy run takes ~40 s (#370)


def _run_tool(args, *, cwd, timeout, should_cancel=None) -> subprocess.CompletedProcess:
    """``subprocess.run(capture_output=True, text=True, timeout=...)`` that a
    stop request can end (#471).

    subprocess.run blocks until the tool exits, so closing the window used to
    leave unforge.exe running on its own (measured: ~23 s past the app's exit,
    writing into a folder Python's exit-time cleanup was already failing to
    delete). This polls instead. ``communicate(timeout=...)`` keeps both
    pipes drained the whole time (its Windows reader threads do), and calling
    it again after a timeout loses no output, so a chatty tool can never fill
    a pipe and stall.

    A stop kills and reaps the tool and raises ExtractionCancelled here,
    before any caller sees an exit code, so a killed unp4k never reaches
    _raise_unp4k_failure (which logs at ERROR) and a killed unforge never
    becomes the non-zero RuntimeError. A stop already pending when the tool
    exits by itself wins over its exit code for the same reason.

    A timeout kills the tool, collects what it wrote and raises the same
    ``subprocess.TimeoutExpired`` that run() raised — _unforge_timeout_error
    and #370's diagnostics rely on that shape. Unlike run(), the reap after a
    kill is bounded, and nothing unexpected can leave the tool running.
    """
    name = Path(args[0]).name
    _raise_if_cancelled(should_cancel, f"{name} was not started")
    kwargs = _get_subprocess_kwargs()
    proc = subprocess.Popen(
        args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs
    )
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                out, err = proc.communicate(timeout=_TOOL_POLL_SECONDS)
                break   # exited by itself
            except subprocess.TimeoutExpired:
                pass    # still running, and nothing it wrote is lost
            if should_cancel is not None and should_cancel():
                _kill_and_reap(proc)
                raise ExtractionCancelled(f"{name} was stopped")
            if time.monotonic() >= deadline:
                out, err = _kill_and_reap(proc)
                raise subprocess.TimeoutExpired(args, timeout, output=out, stderr=err)
    finally:
        if proc.poll() is None:
            _kill_and_reap(proc)   # anything unexpected above must not orphan it
    _raise_if_cancelled(should_cancel, f"{name} finished, but a stop was already requested")
    return subprocess.CompletedProcess(args, proc.returncode, out, err)


def _kill_and_reap(proc) -> tuple[str, str]:
    """Kill *proc* and collect its output, giving up after _TOOL_REAP_SECONDS."""
    try:
        proc.kill()
    except OSError:
        pass   # it exited between the last poll and the kill
    try:
        return proc.communicate(timeout=_TOOL_REAP_SECONDS)
    except subprocess.TimeoutExpired:
        logger.warning(
            f"{Path(proc.args[0]).name} was killed but held its output pipes "
            f"for {_TOOL_REAP_SECONDS}s; continuing without its output"
        )
        proc.poll()
        return "", ""


@timed
def extract_global_ini(
    p4k_path: Path,
    output_path: Path,
    unp4k_exe: Path,
    progress_callback=None,
    progress_pct_callback=None,
    should_cancel=None,
    scratch_near=None,
) -> bool:
    """Extract global.ini from Data.p4k and save it to output_path.

    Uses unp4k.exe with the filter _GLOBAL_INI_FILTER to extract only the
    English localization file, then copies it to output_path (overwriting any
    existing file), removes the old BASE_INI_STAMP once that copy is in place,
    and records Data.p4k's size and base.ini's own size beside it in
    BASE_INI_STAMP for base_ini_is_fresh.

    Args:
        p4k_path: Path to Star Citizen's Data.p4k file.
        output_path: Destination path (e.g. cache/base.ini).
        unp4k_exe: Path to the bundled unp4k.exe.
        progress_callback: Optional callable(str) for status messages.
        progress_pct_callback: Optional callable(completed, total, message)
            for the progress bar. unp4k reports nothing while it runs, so
            its phase is sent with a total of 0, the busy bar (#507).
        should_cancel: Optional callable() -> bool, polled while unp4k runs
            (#471). True kills unp4k, deletes the working folder and raises
            ExtractionCancelled; output_path is left untouched.
        scratch_near: The DataForge cache folder (#471). unp4k works beside
            it, on the drive the user picked for heavy data, by the same rules
            as extract_dataforge. None works in %TEMP% (the caller could not
            resolve the cache folder, e.g. its drive is offline).

    Returns:
        True on success.

    Raises:
        FileNotFoundError: If unp4k.exe or Data.p4k is missing, or the
            extracted file is not found after extraction.
        RuntimeError: If unp4k.exe exits with a non-zero return code, or
            says it could not extract the file (perf proposal).
        P4kLockedError: Data.p4k is locked, or is being written (another
            program has it open for writing, or it changed in the last two
            minutes, #516). The latter is found before anything runs.
        NotEnoughSpaceError: %TEMP%'s drive or the data folder's drive is
            short of free space (#482). A short drive beside the cache only
            moves the work to %TEMP%. Nothing was written.
        WorkingFolderRefusedError: Windows refused the working folder in
            %TEMP% (#490). A refusal beside the cache only moves the work
            to %TEMP%. Nothing was written.
        ExtractionCancelled: A stop was requested. Not a failure.
    """
    if not unp4k_exe.exists():
        raise FileNotFoundError(f"unp4k.exe not found at: {unp4k_exe}")
    if not p4k_path.exists():
        raise FileNotFoundError(f"Data.p4k not found at: {p4k_path}")
    _refuse_if_p4k_being_written(p4k_path)
    # Read before unp4k opens it (perf proposal): a Data.p4k that changes
    # during the run then reads as changed at the next check, rather than
    # its new size vouching for a global.ini taken from the old one.
    p4k_size = p4k_path.stat().st_size

    TOTAL_PHASES = 2
    # unp4k writes the English global.ini here (~10 MB). Like the
    # DataForge run it works beside the DataForge cache, gets an owned name,
    # a stoppable run and the leftover sweep (#471): it used to work in
    # %TEMP%, and a close left this folder and a running unp4k behind.
    run_dir, marker = _begin_scratch(
        scratch_near, GLOBAL_INI_SCRATCH_PREFIX, _GLOBAL_INI_TEMP_PREFIX,
        temp_if_refused=True,
        check_space=lambda parent, in_temp, movable: _require_free_space(
            _global_ini_needs(parent, output_path, in_temp),
            tr("extract.no_space_global_ini"), movable=movable),
    )
    tmp_dir = str(run_dir)
    try:
        if progress_callback:
            progress_callback(tr("progress.unp4k_launch"))
        if progress_pct_callback:
            # A total of 0 is the dialog's moving busy bar (#507). unp4k
            # reports nothing while it runs, and a bar held at 0% for the
            # whole run looked as if the app had hung.
            progress_pct_callback(0, 0, tr("progress.unp4k_launch_short"))

        logger.info(f"Running unp4k: {unp4k_exe} {p4k_path} {_GLOBAL_INI_FILTER} "
                    f"(cwd={tmp_dir})")
        result = _run_tool(
            [str(unp4k_exe), str(p4k_path), _GLOBAL_INI_FILTER],
            cwd=tmp_dir,
            timeout=_UNP4K_GLOBAL_INI_TIMEOUT_SECONDS,
            should_cancel=should_cancel,
        )
        _check_unp4k(result)

        extracted = Path(tmp_dir) / _GLOBAL_INI_RELATIVE
        if not extracted.exists():
            raise FileNotFoundError(
                f"unp4k ran successfully but global.ini was not found at the expected path:\n"
                f"{extracted}\n\n"
                f"stdout: {result.stdout[:500]}"
            )

        if progress_callback:
            progress_callback(tr("progress.copy_global"))
        if progress_pct_callback:
            progress_pct_callback(1, TOTAL_PHASES, tr("progress.copy_global_short"))

        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(extracted), str(output_path))
        logger.info(f"Extracted global.ini → {output_path}")
        # The old stamp goes once the new base.ini is in place, before the
        # new stamp is written (perf proposal). It speaks for the old
        # base.ini, and kept past a new stamp that could not be written it
        # spoke for a new base.ini of the same size too: after a patch that
        # left global.ini as it was, base.ini read stale straight after every
        # extraction. With no stamp the modified times decide, and they read
        # the new base.ini as fresh. Removed before the copy, a copy that
        # failed left the old base.ini with no stamp, and the modified times
        # could then read it fresh against a patched Data.p4k.
        try:
            (output_path.parent / BASE_INI_STAMP).unlink(missing_ok=True)
        except OSError as e:
            logger.warning(f"Could not remove the old {BASE_INI_STAMP} beside {output_path}: {e}")
        # What base_ini_is_fresh keys off (perf proposal): Data.p4k's size,
        # not its modified time, which the launcher moves on a game launch.
        _write_base_ini_stamp(output_path, p4k_size)
    finally:
        _close_scratch(run_dir, marker)

    if progress_pct_callback:
        progress_pct_callback(2, TOTAL_PHASES, "Done")
    return True


@timed
def extract_dataforge(
    p4k_path: Path,
    unp4k_exe: Path,
    unforge_exe: Path,
    dataforge_cache_dir: Path,
    progress_callback=None,
    progress_pct_callback=None,
    should_cancel=None,
    defer_cleanup=None,
) -> bool:
    """Extract DataForge entity XMLs from Data.p4k and cache them.

    Pipeline:
      1. unp4k.exe extracts Game2.dcb from the p4k into this run's working
         folder, beside the cache or in %TEMP% (see _scratch_location, #471).
      2. unforge.exe converts Game2.dcb → individual XML entity files, next to
         the dcb.
      3. The old cache is set aside in the working folder (wiped in place in
         %TEMP%, on a tight drive or when the rename is refused), the
         generator's subtrees are moved into dataforge_cache_dir (copied
         when the work is in %TEMP% or a move is refused) and stamped, then
         the working folder is deleted, or handed to *defer_cleanup*. No
         diff manifest follows (perf proposal, #495): nothing read it.

    This is slow the first time (~several minutes) but results are cached and
    only need to be re-run when the p4k file changes.

    Args:
        p4k_path: Path to Data.p4k.
        unp4k_exe: Path to bundled unp4k.exe.
        unforge_exe: Path to bundled unforge.exe.
        dataforge_cache_dir: Destination directory for the cached entity XMLs.
        progress_callback: Optional callable(str) for status messages.
        progress_pct_callback: Optional callable(completed, total, message)
            for the progress bar. unp4k and unforge report nothing while
            they run, so their phases are sent with a total of 0, the busy
            bar (#507). Caching the entity files is 2 of 3, and Done is 3
            of 3.
        should_cancel: Optional callable() -> bool (#471). Polled while each
            tool runs, which kills the tool, and checked between steps. The
            check just before the old cache is wiped is the last point a stop
            leaves that cache untouched; past it the run finishes and stamps
            the new cache, then reports the stop.
        defer_cleanup: Optional callable(WorkingFolder) (perf proposal). A
            run that saved and stamped the new cache with no stop requested
            hands it the working folder (what the cache does not keep, and
            the old cache when it was set aside there) instead of deleting
            it, so the caller can delete it later with WorkingFolder.delete,
            in the background. Not on a drive that had room only once the
            old cache was gone. Every other outcome deletes the folder
            before returning or raising, as without it. A stop that arrives
            right after the hand-over still raises ExtractionCancelled, with
            the folder already handed over: the caller owns it then and must
            delete it on that path too (DataForgeExtractWorker._finish does).

    Returns:
        True on success.

    Raises:
        FileNotFoundError: If required executables or Data.p4k are missing,
            or unforge's output lacks `libs/`, the records folder the cache
            keeps, or every one of the subtrees it keeps there, all found
            before the old cache is wiped (#484).
        RuntimeError: If either subprocess fails: a non-zero exit, or a file
            it says it could not extract or convert (perf proposal), found
            before the old cache is wiped.
        P4kLockedError: Data.p4k is locked, or is being written (another
            program has it open for writing, or it changed in the last two
            minutes, #516). The latter is found before anything runs.
        NotEnoughSpaceError: A drive the run writes to is short of free
            space, found before any tool runs or just before the old cache
            is wiped (which then stays), or a drive filled while the new
            cache was saved (#482).
        WorkingFolderRefusedError: Windows refused the working folder,
            found before any tool runs (#490), or, with the work in %TEMP%,
            a new folder where the cache folder is made again after the
            wipe (#494). The old cache stays.
        CacheFolderIsLinkError: dataforge_cache_dir is a junction or a
            symbolic link, found before anything runs (#491). The old cache
            and the link stay.
        ExtractionCancelled: A stop was requested. Not a failure.
    """
    for exe, name in [(unp4k_exe, "unp4k.exe"), (unforge_exe, "unforge.exe")]:
        if not exe.exists():
            raise FileNotFoundError(f"{name} not found at: {exe}")
    if not p4k_path.exists():
        raise FileNotFoundError(f"Data.p4k not found at: {p4k_path}")
    _refuse_if_p4k_being_written(p4k_path)

    # Wrap once here so every use below (mkdir, exists checks, and whatever
    # this function hands to _cache_filtered_records) inherits long-path
    # safety — see win_paths.win_long_path (#221).
    dataforge_cache_dir = Path(_win_long_path(dataforge_cache_dir))

    # Step 3's wipe deletes nothing through a link (see robust_rmtree), so a
    # cache folder that is one is refused before anything runs (#491).
    linked = linked_cache_folder_error(dataforge_cache_dir)
    if linked is not None:
        raise linked

    TOTAL_PHASES = 3
    # Where unp4k and unforge work (#471), with leftovers of earlier runs
    # swept first from both places, whichever this run uses.
    run_dir, marker = _begin_scratch(
        dataforge_cache_dir, DATAFORGE_SCRATCH_PREFIX, _DATAFORGE_TEMP_PREFIX,
        check_space=lambda parent, in_temp, movable: _require_free_space(
            _dataforge_needs(parent, dataforge_cache_dir, in_temp),
            tr("extract.no_space_dataforge"), movable=movable),
    )
    logger.info(f"DataForge working folder: {run_dir}")
    handed_off = False
    try:
        # Work in %TEMP% has not shown that the cache folder can be made again
        # after the wipe in step 3 (#494).
        _require_cache_can_be_remade(run_dir, dataforge_cache_dir)

        # Data.p4k as unp4k is about to read it, for the stamps in step 3
        # (perf proposal). Read after unforge, a game patch that landed
        # during the run made a cache of the old build read as current, as
        # extract_global_ini's base.ini stamp would have.
        p4k_stat = p4k_path.stat()

        # ── Step 1: Extract Game2.dcb ─────────────────────────────────────────
        if progress_callback:
            progress_callback(tr("progress.extract_dcb"))
        if progress_pct_callback:
            # The busy bar while each tool runs, as for global.ini (#507).
            # Neither reports progress, so a counted bar stood at 0% here
            # and at 33% for the minutes unforge takes.
            progress_pct_callback(0, 0, tr("progress.extract_dcb"))
        logger.info(f"Running unp4k to extract .dcb: {unp4k_exe} {p4k_path} .dcb")
        result = _run_tool(
            [str(unp4k_exe), str(p4k_path), ".dcb"],
            cwd=str(run_dir),
            timeout=_UNP4K_DCB_TIMEOUT_SECONDS,
            should_cancel=should_cancel,
        )
        _check_unp4k(result)
        # No pause and no gc.collect() after either tool (perf proposal):
        # each is a separate process _run_tool has already reaped, and Python
        # holds none of the files it wrote. A refused move has its own retries
        # (_MOVE_RETRY_DELAYS), and the wipe has robust_rmtree's backoff.

        # unp4k preserves archive structure: Data/Game2.dcb
        dcb_candidates = list(run_dir.glob("Data/Game*.dcb"))
        if not dcb_candidates:
            raise FileNotFoundError("Game*.dcb not found in p4k output — check game install path.")
        dcb_path = dcb_candidates[0]
        logger.info(f"Found DCB: {dcb_path} ({dcb_path.stat().st_size / 1_048_576:.0f} MB)")

        # ── Step 2: Run unforge to produce entity XMLs ────────────────────────
        if progress_callback:
            progress_callback(tr("progress.unforge"))
        if progress_pct_callback:
            progress_pct_callback(0, 0, tr("progress.unforge_short"))
        # Size is captured before the run so the timeout handler can name it:
        # "Game.dcb (114 MB)" versus a healthy "Game2.dcb (330 MB)" is the
        # entire diagnosis when this stalls (#370).
        dcb_mb = dcb_path.stat().st_size / 1_048_576
        logger.info(f"Running unforge: {unforge_exe} {dcb_path}")
        try:
            # cwd too: unforge writes next to the dcb, and anything else it
            # might drop in its working folder then stays inside the run's
            # folder as well.
            result = _run_tool(
                [str(unforge_exe), str(dcb_path)],
                cwd=str(run_dir),
                timeout=_UNFORGE_TIMEOUT_SECONDS,
                should_cancel=should_cancel,
            )
        except subprocess.TimeoutExpired as e:
            raise _unforge_timeout_error(e, dcb_path, dcb_mb, p4k_path) from e
        # Always log unforge's output at INFO (truncated). A zero-length
        # stdout + sub-second runtime is typically a silent failure — e.g.
        # antivirus blocking unforge.exe or quarantining a file it wrote, or
        # unforge choking on a new DCB schema. Without this log the
        # downstream "libs/ directory was not created" error gives no clue
        # what went wrong.
        _stdout = (result.stdout or "").strip()
        _stderr = (result.stderr or "").strip()
        if _stdout:
            logger.info(f"unforge stdout ({len(_stdout)} bytes, truncated): {_stdout[:2000]}")
        if _stderr:
            logger.info(f"unforge stderr ({len(_stderr)} bytes, truncated): {_stderr[:2000]}")
        if result.returncode != 0:
            raise RuntimeError(f"unforge.exe failed (code {result.returncode}):\n"
                               f"{_stderr or _stdout or '(no output)'}")
        # Exit code 0, but a file it could not save fails the run all the
        # same (_UNFORGE_FILE_FAILED), here, while the old cache is still
        # there (perf proposal).
        if _UNFORGE_FILE_FAILED in f"{_stdout}\n{_stderr}":
            raise RuntimeError(f"unforge.exe failed (code {result.returncode}):\n"
                               + "\n".join(filter(None, (_stderr, _stdout))))

        # unforge writes entity XMLs into a libs/ subdirectory next to the
        # dcb file. When it's missing we surface whatever we captured from
        # unforge's stdout/stderr in the exception so the user (and the Log
        # Tab) can see what went wrong.
        #
        # Python-side reads under unforge's output get the long-path prefix
        # (#471). With the working folder near its depth cap the deepest keep
        # path is ~261 characters, where a plain exists() returns False and
        # _cache_filtered_records would skip that subtree without a word. The
        # tools themselves only ever see plain paths.
        libs_dir = Path(_win_long_path(dcb_path.parent))
        if not (libs_dir / _UNFORGE_LIBS_DIR).exists():
            diagnostic = ""
            if _stdout or _stderr:
                diagnostic = (
                    f"\n\nunforge stdout:\n{_stdout[:1500] or '(empty)'}"
                    f"\n\nunforge stderr:\n{_stderr[:1500] or '(empty)'}"
                )
            else:
                # Nothing on either stream and no libs/. Both bundled tools
                # are self-contained single-file .NET builds (unforge .NET 8,
                # unp4k .NET 10), so this is not a missing runtime. It is
                # almost always antivirus blocking or quarantining
                # unforge.exe, or unforge being refused writes to its
                # working folder (e.g. Controlled Folder Access).
                diagnostic = (
                    "\n\nNo output from unforge and no libs/ directory produced. "
                    "This usually means antivirus blocked or quarantined unforge.exe, "
                    f"or it could not write to its working folder ({dcb_path.parent}). "
                    "Check your antivirus history, allow Smart Citizen's unforge.exe, "
                    "and try again."
                )
            raise FileNotFoundError(
                "unforge ran but libs/ directory was not created — unexpected output structure."
                + diagnostic
            )
        # The records folder the cache keeps, and at least one of its kept
        # subtrees, checked while the old cache is still there (#484). Found
        # missing only after the wipe, it cost the old cache and left an
        # empty one that reads as never extracted.
        _unforge_records(libs_dir / _UNFORGE_LIBS_DIR)

        # ── Step 3: Cache the full extraction ─────────────────────────────────
        if progress_callback:
            progress_callback(tr("progress.caching_entities"))
        if progress_pct_callback:
            progress_pct_callback(2, TOTAL_PHASES, tr("progress.caching_entities"))

        # The drive may have filled while unforge ran (#482). Refused here,
        # the old cache is kept. *tight*: it has room only once the old
        # cache is gone (perf proposal).
        tight = _require_room_for_new_cache(libs_dir, dataforge_cache_dir, should_cancel)

        # The last point a stop leaves the previous cache untouched (#471).
        # Past here the run always finishes and stamps the new cache, so a
        # stop never leaves it half filled.
        _raise_if_cancelled(should_cancel, "stopped before the previous cache was replaced")

        # Beside the cache the working folder is on the cache's drive, and
        # the kept subtrees are moved in (#484). In %TEMP% they are copied
        # as before: moved files would keep %TEMP%'s permissions, and a move
        # into a OneDrive folder is untested. Beside the cache they end up
        # with the cache's permissions: the working folder is a plain
        # os.mkdir (#490), so both inherit from the same parent.
        move = run_dir.parent == Path(win_plain_path(dataforge_cache_dir)).parent
        # Out with the prior cache. Its stamps go first (#484): from Python
        # 3.12.4 rmtree deletes the leaf's own files last, so a wipe that
        # gave up part-way, or a hard kill during it, would leave a stamped
        # partial cache. That reads as fresh when the stamps match this
        # Data.p4k, and the next free-space check counts it as a complete
        # old cache. Beside the cache it is then set aside in the working
        # folder with one rename, and deleted with that folder after the
        # run (perf proposal). It is wiped in place, as before, in %TEMP%
        # (another drive), on a drive that has room only once it is gone,
        # or when the rename is refused. The wipe uses a retry loop because
        # on Windows (particularly under OneDrive) a transient handle from
        # the just-exited unforge.exe or from the OneDrive/Defender/indexer
        # stack can reject the first few rmdir attempts with WinError 5.
        set_aside = None
        if dataforge_cache_dir.exists():
            _remove_stamps(dataforge_cache_dir)
            if move and not tight:
                set_aside = _set_old_cache_aside(dataforge_cache_dir, run_dir)
            if set_aside is None:
                robust_rmtree(dataforge_cache_dir)

        def free_the_old_cache():
            # A copy needs the room the wipe would have freed (#482), so a
            # set-aside old cache goes first (perf proposal). Best effort: a
            # copy that then finds the drive full is the "cache incomplete"
            # message, as it would have been.
            try:
                robust_rmtree(set_aside)
                logger.info("Deleted the old DataForge cache before a copy")
            except OSError as e:
                logger.warning(f"Could not delete the old DataForge cache in "
                               f"{win_plain_path(set_aside)} before a copy: {e}")

        # A full drive from here to the stamps leaves a cache with no stamp,
        # which the startup check offers to re-extract (#482).
        try:
            dataforge_cache_dir.mkdir(parents=True, exist_ok=True)

            # Cache only the subtrees the enhancement generator actually reads.
            # See DATAFORGE_KEEP_SUBPATHS for the list and rationale — dropping
            # the unused ~31k/~0.6 GB worth of entries halves cache file count and
            # makes every re-extract + clear-cache noticeably faster on the
            # OneDrive/Defender/Indexer-burdened Windows paths our users live in.
            cache_libs = dataforge_cache_dir / DATAFORGE_LIBS_SUBPATH
            logger.info(f"Saving DataForge extraction to {cache_libs}…")
            filling = time.monotonic()
            moved, copied, skipped = _cache_filtered_records(
                libs_dir / _UNFORGE_LIBS_DIR, cache_libs, move=move,
                before_copy=free_the_old_cache if set_aside is not None else None)
            logger.info(
                f"DataForge cache written: {moved + copied}/{len(DATAFORGE_KEEP_SUBPATHS)} "
                f"keep-subpaths in {time.monotonic() - filling:.1f} s, {moved} moved and "
                f"{copied} copied ({skipped} not present in this build)"
            )

            # Stamp the source Data.p4k's mtime AND size so a later launch can tell
            # whether this cache is still current. Size is the reliable signal —
            # see dataforge_cache_is_fresh — because the RSI launcher's file
            # verification bumps Data.p4k's mtime on game launches without changing
            # its content, and a multi-GB re-extract on every such benign touch is
            # exactly the needless work issue #209 reported. Both come from
            # Data.p4k as it was before unp4k ran (see above).
            (dataforge_cache_dir / P4K_MTIME_STAMP).write_text(str(p4k_stat.st_mtime))
            (dataforge_cache_dir / P4K_SIZE_STAMP).write_text(str(p4k_stat.st_size))
        except (_DiskFullDuringCopy, OSError) as e:
            # A stamp left after a failure here can make the unfinished
            # cache read as fresh (the mtime stamp alone does), so neither
            # stays, whatever the failure (#484, #482).
            _remove_stamps(dataforge_cache_dir)
            if not _is_disk_full(e):
                raise
            raise _cache_incomplete_error(dataforge_cache_dir, e) from e
        logger.info(f"DataForge cache written to {dataforge_cache_dir}")
        # The caller deletes the working folder after the run, in the
        # background (perf proposal), unless a stop is already pending or
        # the drive had room only once the old cache was gone.
        if defer_cleanup is not None and not tight and not (
                should_cancel is not None and should_cancel()):
            defer_cleanup(WorkingFolder(run_dir, marker))
            handed_off = True
    finally:
        # Failure or stop, the working folder goes now (#471), so its ~2.3 GB
        # never outlives the run and a stopped run cleans up after itself,
        # and so does a success nobody took it from. _close_scratch logs
        # every OSError, never raising it over the real outcome.
        if not handed_off:
            cleanup = time.monotonic()
            _close_scratch(run_dir, marker)
            logger.info(f"Deleting the DataForge working folder took "
                        f"{time.monotonic() - cleanup:.1f} s")

    # A stop that arrived while the cache was filled ends here, as a stop:
    # the cache is complete and stamped, but the user asked to stop, so
    # nothing may chain into generation.
    _raise_if_cancelled(should_cancel, "stopped once the new cache was written")

    # No diff manifest (perf proposal, #495). Hashing every cached file
    # took about 4.5 s after each extraction, longer on a hard drive, and
    # nothing reads the manifest any more: the generator runs every
    # category it is handed.

    if progress_pct_callback:
        progress_pct_callback(3, TOTAL_PHASES, "Done")
    return True


@timed
def dataforge_cache_is_fresh(p4k_path: Path, dataforge_cache_dir: Path) -> bool:
    """Return True if the cached DataForge XMLs are up-to-date with the p4k.

    Requires a stamp AND actual XML content in the cache so a stamp-only
    remnant from a failed/partial extraction returns False.

    Freshness is keyed off the source Data.p4k's **byte size**, not its mtime
    (issue #209). The RSI launcher's file verification bumps Data.p4k's mtime
    on ordinary game launches without changing its content, so an mtime-only
    check declared the cache stale after any game launch and forced a needless
    multi-minute re-extract on the next app start. A real game patch always
    changes the ~100 GB archive's size, so size is the reliable "did the
    content change" signal. Caches written before the ``.p4k_size`` stamp
    existed (upgrades) fall back to the legacy mtime comparison until the next
    extraction writes the size stamp.
    """
    dataforge_cache_dir = Path(_win_long_path(dataforge_cache_dir))
    stamp = dataforge_cache_dir / P4K_MTIME_STAMP
    size_stamp = dataforge_cache_dir / P4K_SIZE_STAMP
    libs_dir = dataforge_cache_dir / DATAFORGE_LIBS_SUBPATH
    if not stamp.exists() or not libs_dir.exists():
        return False
    # Verify there is at least one XML file — guards against empty extractions
    if not any(libs_dir.rglob("*.xml")):
        return False
    try:
        p4k_stat = p4k_path.stat()
    except OSError:
        return False
    # Primary signal: unchanged size means unchanged content → fresh,
    # regardless of any benign mtime drift.
    try:
        cached_size = int(size_stamp.read_text().strip())
        return cached_size == p4k_stat.st_size
    except (OSError, ValueError):
        pass
    # Legacy fallback (no size stamp yet): the pre-#209 mtime comparison.
    try:
        cached_mtime = float(stamp.read_text().strip())
        return cached_mtime >= p4k_stat.st_mtime
    except (OSError, ValueError):
        return False


def _write_base_ini_stamp(base_ini: Path, p4k_size: int) -> None:
    """Record that *base_ini* came from a Data.p4k of *p4k_size* bytes
    (perf proposal).

    base.ini's own size goes in too, so the stamp speaks only for the
    base.ini it was written for. The cache folder holds other files that
    come and go on their own: Clear Cache deletes base.ini and leaves the
    stamp, and a data folder change copies each file only where the new
    folder has none, so a stamp can end up beside another base.ini.
    A stamp that cannot be written is logged at WARNING and never fails
    the caller; base_ini_is_fresh then falls back to the modified times,
    since extract_global_ini removes the old stamp once the new base.ini is
    in place, before it writes the new one.
    """
    stamp = base_ini.parent / BASE_INI_STAMP
    try:
        stamp.write_text(f"{p4k_size} {base_ini.stat().st_size}", encoding="utf-8")
    except OSError as e:
        logger.warning(f"Could not record Data.p4k's size beside {base_ini}: {e}")


def base_ini_is_fresh(p4k_path: Path, base_ini: Path) -> bool:
    """Return True if *base_ini*, the global.ini extracted from Data.p4k, is
    still current with *p4k_path* (perf proposal).

    Keyed off Data.p4k's byte size, by #209's rule for the DataForge cache
    (see dataforge_cache_is_fresh): the RSI launcher's file verification
    moves Data.p4k's modified time on an ordinary game launch without
    changing its content. The old rule here (Data.p4k newer than base.ini)
    then asked to extract global.ini again at the next start, channel switch
    or data folder change, and lit the Config tab's Extract button, after
    nothing more than playing.

    A stamp written for another base.ini (its recorded size differs) counts
    as no stamp. With no usable stamp (a base.ini extracted before the
    stamp existed) the old rule decides, so an upgrade asks for nothing the
    old rule would not have asked for, and reads a game patch as the old
    rule reads it at that check. When it reads fresh, Data.p4k's modified
    time is no newer than base.ini's, which normally means it has not been
    touched since base.ini was written, so its size is recorded there and
    then: the next launcher touch is recognised without an extraction
    first. A patch the old rule misses (one that left Data.p4k's modified
    time no newer than base.ini's) is recorded the same way, so it stays
    missed until the next patch changes the size, where the old rule would
    have asked after the next game launch. Nothing else tells a launch from
    such a patch.
    """
    try:
        p4k_stat = p4k_path.stat()
        base_stat = base_ini.stat()
    except OSError:
        return False
    try:
        text = (base_ini.parent / BASE_INI_STAMP).read_text(encoding="utf-8")
        stamped_p4k_size, stamped_base_size = (int(value) for value in text.split())
    except (OSError, ValueError):
        # No stamp, or one that is not two numbers (a ValueError, also for
        # bytes that are not text): fall back to the modified times.
        pass
    else:
        if stamped_base_size == base_stat.st_size:
            return stamped_p4k_size == p4k_stat.st_size
    if p4k_stat.st_mtime > base_stat.st_mtime:
        return False
    logger.info(f"Recording Data.p4k's size ({p4k_stat.st_size:,} bytes) for {base_ini}, "
                f"which is not older than Data.p4k")
    _write_base_ini_stamp(base_ini, p4k_stat.st_size)
    return True
