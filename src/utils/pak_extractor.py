"""Extracts files from Star Citizen's Data.p4k using bundled unp4k.exe."""
import gc
import logging
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from src.utils.perf import timed

from src.utils.dataforge_diff import update_manifest
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

# Layout inside a DataForge cache folder: unforge's libs/ tree is kept under
# raw/, and the records everything reads sit in foundry/records inside it.
# Every module that reads or writes the cache joins these rather than
# spelling the segments out (root CLAUDE.md, "Magic literals").
DATAFORGE_LIBS_SUBPATH = Path("raw") / "libs"
DATAFORGE_RECORDS_UNDER_LIBS = Path("foundry") / "records"
DATAFORGE_RECORDS_SUBPATH = DATAFORGE_LIBS_SUBPATH / DATAFORGE_RECORDS_UNDER_LIBS

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


def _raise_if_cancelled(should_cancel, where: str) -> None:
    if should_cancel is not None and should_cancel():
        raise ExtractionCancelled(where)


def _raise_unp4k_failure(returncode: int, output: str) -> None:
    """Raise for a non-zero unp4k exit — P4kLockedError for a locked Data.p4k,
    plain RuntimeError otherwise.

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
    if _P4K_LOCKED_SIGNATURE in output.lower():
        logger.warning(
            f"unp4k.exe exited with code {returncode} — Data.p4k is locked "
            f"(game likely updating); output:\n{output[:2000]}"
        )
        raise P4kLockedError(tr("extract.p4k_locked"))
    logger.error(f"unp4k.exe exited with code {returncode}; output:\n{output[:2000]}")
    raise RuntimeError(f"unp4k.exe exited with code {returncode}.\n\n{output}")


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

    Silently succeeds if *path* doesn't exist. Raises the last error if
    every attempt fails so callers can surface it to the user.
    """
    if not path.exists():
        return

    def _on_error(func, target, *_):
        # Compatible with both 3.11 ``onerror(func, path, excinfo)`` and
        # 3.12+ ``onexc(func, path, exc)`` callback signatures — we only
        # care about the failing path so the trailing arg is ignored.
        # Clear the read-only bit and retry the single failing file/dir;
        # for other errors (e.g. lingering handle), propagate so the
        # outer retry loop picks it up.
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
            shutil.rmtree(_win_long_path(path), **{_RMTREE_CB_KWARG: _on_error})
            return
        except OSError as e:
            last_err = e
            # Exponential-ish backoff: 0.2, 0.4, 0.8, 1.5, 3.0 seconds. Total
            # ceiling ~6s before we bail, enough to outlast most AV/indexer
            # scans without hanging the UI forever.
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
#   * outside the leaf, which step 3 wipes and which the freshness check, the
#     diff manifest and the generator read;
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
# proven. The global.ini extraction (every language's global.ini, ~31 MB)
# follows the same rules with its own globalini.extracting-XXXXXXXX folder, so
# nothing Smart Citizen extracts lands in %TEMP% unless one of the fallbacks
# above applies.
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
_MKDTEMP_RANDOM_CHARS = 8            # length of tempfile.mkdtemp's random suffix
_MAX_SCRATCH_CHARS = 190
# A folder with no marker is either the instant between mkdtemp and opening
# the marker, or a removal that got part-way. Only an old one is a leftover.
_UNMARKED_SCRATCH_GRACE_SECONDS = 10 * 60
_DRIVE_REMOVABLE, _DRIVE_REMOTE = 2, 4   # GetDriveTypeW


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


def _sweep_stale_scratch(parent: Path, prefix: str) -> None:
    """Delete working folders an earlier extraction left in *parent*: a crash,
    a hard kill, or a close that stopped waiting (#471). Skips any folder a
    live run still holds. Never raises."""
    try:
        folders = [p for p in parent.glob(prefix + "*") if p.is_dir()]
    except OSError:
        return
    for folder in folders:
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


def _open_scratch(parent: Path, prefix: str):
    """Make a run's working folder under *parent* and open its marker.
    Returns ``(folder, marker)``; end the run with :func:`_close_scratch`."""
    parent.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix=prefix, dir=str(parent)))
    try:
        marker = open(run_dir / _SCRATCH_MARKER, "w", encoding="utf-8")
    except OSError:
        _close_scratch(run_dir, None)
        raise
    return run_dir, marker


def _close_scratch(run_dir: Path, marker) -> None:
    """Close the marker and delete the working folder. Never raises: a folder
    that will not go is logged and left for the next extraction's sweep, so a
    cleanup problem can never replace the run's real outcome (on 3.11,
    TemporaryDirectory's own cleanup could, even after the cache had been
    stamped)."""
    try:
        if marker is not None:
            marker.close()
        robust_rmtree(run_dir)
    except OSError as e:
        logger.warning(
            f"Could not remove the extraction working folder {run_dir} ({e}); "
            "the next extraction removes it"
        )


def _begin_scratch(near, prefix: str, temp_prefix: str, *, temp_if_refused: bool = False):
    """Sweep earlier leftovers and open this run's working folder (#471):
    beside the DataForge cache folder *near* by the _scratch_location rules,
    or in %TEMP% when *near* is None. Returns ``(folder, marker)``; end the
    run with :func:`_close_scratch`.

    *temp_if_refused* falls back to %TEMP% when the folder beside the cache
    cannot be made (permissions, Controlled Folder Access, a drive turned
    read-only). The global.ini extraction wants that: it only ever needed
    %TEMP% before #471, and its output goes to the data folder, not the
    cache. The DataForge run does not, because its cache writes go to that
    same drive and would fail anyway, after a minute of unforge.
    """
    temp_root = Path(tempfile.gettempdir())
    _sweep_stale_scratch(temp_root, temp_prefix)
    if near is None:
        return _open_scratch(temp_root, temp_prefix)
    plain_leaf = Path(win_plain_path(near))
    parent, run_prefix = _scratch_location(plain_leaf, prefix, temp_prefix)
    _sweep_stale_scratch(plain_leaf.parent, prefix)
    try:
        return _open_scratch(parent, run_prefix)
    except OSError as e:
        if not temp_if_refused or parent == temp_root:
            raise
        logger.info(f"Could not make a working folder in {parent} ({e}); working in {temp_root}")
        return _open_scratch(temp_root, temp_prefix)


# Path of global.ini inside the p4k archive (unp4k preserves directory structure)
_GLOBAL_INI_RELATIVE = Path("data/Localization/english/global.ini")


# Subtrees of unforge's ``libs/foundry/records/`` that the enhancement
# generator actually reads. Everything else unforge produces is copied nowhere
# — the working folder is deleted when extract_dataforge finishes.
#
# Keeping this list tight:
#   * halves the final cache's file count (~58k → ~28k) and disk footprint
#     (~2.4 GB → ~1.4 GB);
#   * cuts the working folder → cache copy step to ~50% of its old wall-clock (OneDrive
#     / Defender / Indexer fire hooks per-file-close, which dominates copy
#     time on typical Windows installs);
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


def _copy_filtered_records(src_libs: Path, dst_libs: Path) -> tuple[int, int]:
    """Copy only the generator's required subtrees from *src_libs* → *dst_libs*.

    Both paths point at the ``libs/`` directory unforge writes (which in turn
    contains ``foundry/records/<subtree>/...``). Only subpaths listed in
    :data:`DATAFORGE_KEEP_SUBPATHS` are copied; anything else in the source
    is left in the working folder, which extract_dataforge deletes when the
    run ends.

    Returns ``(copied, skipped)`` — the number of keep-subpaths actually
    present and copied, and the number that weren't in this game build
    (common for ``entities/missions`` etc. which appear and disappear between
    patches — the generator already guards each read with ``if dir.exists()``).
    """
    records_src = src_libs / DATAFORGE_RECORDS_UNDER_LIBS
    records_dst = dst_libs / DATAFORGE_RECORDS_UNDER_LIBS

    if not records_src.exists():
        raise FileNotFoundError(
            f"unforge output missing expected '{DATAFORGE_RECORDS_UNDER_LIBS.as_posix()}/' "
            f"layout at {records_src}"
        )

    Path(_win_long_path(records_dst)).mkdir(parents=True, exist_ok=True)

    copied = 0
    skipped = 0
    for rel in DATAFORGE_KEEP_SUBPATHS:
        src = records_src / rel
        dst = records_dst / rel
        if not src.exists():
            # Not every build ships every subtree — e.g. entities/missions,
            # entities/contracts, entities/jobterminal came and went across
            # 4.x patches. Log at debug so the cold-path message in the Log
            # Tab stays uncluttered.
            logger.debug(f"DataForge keep-path not in this build, skipping: {rel}")
            skipped += 1
            continue
        Path(_win_long_path(dst.parent)).mkdir(parents=True, exist_ok=True)
        # Long-path-prefixed on both sides: the deepest entries under
        # entities/scitem/mission_entities/ routinely push the destination
        # past 260 chars once nested under a user's install dir (#221).
        shutil.copytree(_win_long_path(src), _win_long_path(dst))
        copied += 1

    return copied, skipped


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

    Uses unp4k.exe with the filter "global.ini" to extract only the localization
    file, then copies it to output_path (overwriting any existing file).

    Args:
        p4k_path: Path to Star Citizen's Data.p4k file.
        output_path: Destination path (e.g. cache/base.ini).
        unp4k_exe: Path to the bundled unp4k.exe.
        progress_callback: Optional callable(str) for status messages.
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
        RuntimeError: If unp4k.exe exits with a non-zero return code.
        ExtractionCancelled: A stop was requested. Not a failure.
    """
    if not unp4k_exe.exists():
        raise FileNotFoundError(f"unp4k.exe not found at: {unp4k_exe}")
    if not p4k_path.exists():
        raise FileNotFoundError(f"Data.p4k not found at: {p4k_path}")

    TOTAL_PHASES = 2
    # unp4k writes every language's global.ini here (~31 MB). Like the
    # DataForge run it works beside the DataForge cache, gets an owned name,
    # a stoppable run and the leftover sweep (#471): it used to work in
    # %TEMP%, and a close left this folder and a running unp4k behind.
    run_dir, marker = _begin_scratch(
        scratch_near, GLOBAL_INI_SCRATCH_PREFIX, _GLOBAL_INI_TEMP_PREFIX,
        temp_if_refused=True,
    )
    tmp_dir = str(run_dir)
    try:
        if progress_callback:
            progress_callback(tr("progress.unp4k_launch"))
        if progress_pct_callback:
            progress_pct_callback(0, TOTAL_PHASES, tr("progress.unp4k_launch_short"))

        logger.info(f"Running unp4k: {unp4k_exe} {p4k_path} global.ini (cwd={tmp_dir})")
        result = _run_tool(
            [str(unp4k_exe), str(p4k_path), "global.ini"],
            cwd=tmp_dir,
            timeout=_UNP4K_GLOBAL_INI_TIMEOUT_SECONDS,
            should_cancel=should_cancel,
        )

        if result.returncode != 0:
            _raise_unp4k_failure(result.returncode, result.stderr or result.stdout)

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
) -> bool:
    """Extract DataForge entity XMLs from Data.p4k and cache them.

    Pipeline:
      1. unp4k.exe extracts Game2.dcb from the p4k into this run's working
         folder, beside the cache or in %TEMP% (see _scratch_location, #471).
      2. unforge.exe converts Game2.dcb → individual XML entity files, next to
         the dcb.
      3. The generator's subtrees are copied to dataforge_cache_dir and
         stamped, then the working folder is deleted.
      4. The diff manifest snapshots the new cache.

    This is slow the first time (~several minutes) but results are cached and
    only need to be re-run when the p4k file changes.

    Args:
        p4k_path: Path to Data.p4k.
        unp4k_exe: Path to bundled unp4k.exe.
        unforge_exe: Path to bundled unforge.exe.
        dataforge_cache_dir: Destination directory for the cached entity XMLs.
        progress_callback: Optional callable(str) for status messages.
        should_cancel: Optional callable() -> bool (#471). Polled while each
            tool runs, which kills the tool, and checked between steps. The
            check just before the old cache is wiped is the last point a stop
            leaves that cache untouched; past it the run finishes and stamps
            the new cache, then stops before the manifest.

    Returns:
        True on success.

    Raises:
        FileNotFoundError: If required executables or Data.p4k are missing.
        RuntimeError: If either subprocess fails.
        ExtractionCancelled: A stop was requested. Not a failure.
    """
    for exe, name in [(unp4k_exe, "unp4k.exe"), (unforge_exe, "unforge.exe")]:
        if not exe.exists():
            raise FileNotFoundError(f"{name} not found at: {exe}")
    if not p4k_path.exists():
        raise FileNotFoundError(f"Data.p4k not found at: {p4k_path}")

    # Wrap once here so every use below (mkdir, exists checks, and whatever
    # this function hands to _copy_filtered_records/update_manifest) inherits
    # long-path safety — see win_paths.win_long_path (#221).
    dataforge_cache_dir = Path(_win_long_path(dataforge_cache_dir))

    TOTAL_PHASES = 3
    # Where unp4k and unforge work (#471), with leftovers of earlier runs
    # swept first from both places, whichever this run uses.
    run_dir, marker = _begin_scratch(
        dataforge_cache_dir, DATAFORGE_SCRATCH_PREFIX, _DATAFORGE_TEMP_PREFIX
    )
    logger.info(f"DataForge working folder: {run_dir}")
    try:
        # ── Step 1: Extract Game2.dcb ─────────────────────────────────────────
        if progress_callback:
            progress_callback(tr("progress.extract_dcb"))
        if progress_pct_callback:
            progress_pct_callback(0, TOTAL_PHASES, tr("progress.extract_dcb"))
        logger.info(f"Running unp4k to extract .dcb: {unp4k_exe} {p4k_path} .dcb")
        result = _run_tool(
            [str(unp4k_exe), str(p4k_path), ".dcb"],
            cwd=str(run_dir),
            timeout=_UNP4K_DCB_TIMEOUT_SECONDS,
            should_cancel=should_cancel,
        )
        if result.returncode != 0:
            _raise_unp4k_failure(result.returncode, result.stderr or result.stdout)

        # Explicit cleanup: ensure subprocess is fully released
        del result
        gc.collect()
        time.sleep(0.1)  # Brief pause for file system to release locks

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
            progress_pct_callback(1, TOTAL_PHASES, tr("progress.unforge_short"))
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
            raise RuntimeError(f"unforge.exe failed (code {result.returncode}):\n{_stderr or _stdout or '(no output)'}")

        # Explicit cleanup: ensure subprocess is fully released
        del result
        gc.collect()
        time.sleep(0.1)  # Brief pause for file system to release locks

        # unforge writes entity XMLs into a libs/ subdirectory next to the
        # dcb file. When it's missing we surface whatever we captured from
        # unforge's stdout/stderr in the exception so the user (and the Log
        # Tab) can see what went wrong.
        #
        # Python-side reads under unforge's output get the long-path prefix
        # (#471). With the working folder near its depth cap the deepest keep
        # path is ~261 characters, where a plain exists() returns False and
        # _copy_filtered_records would skip that subtree without a word. The
        # tools themselves only ever see plain paths.
        libs_dir = Path(_win_long_path(dcb_path.parent))
        if not (libs_dir / "libs").exists():
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

        # ── Step 3: Cache the full extraction ─────────────────────────────────
        if progress_callback:
            progress_callback(tr("progress.caching_entities"))
        if progress_pct_callback:
            progress_pct_callback(2, TOTAL_PHASES, tr("progress.caching_entities"))

        # Ensure all file handles from extraction are released before copying
        gc.collect()
        time.sleep(0.1)

        # The last point a stop leaves the previous cache untouched (#471).
        # Past here the run always finishes and stamps the new cache, so a
        # stop never leaves it half-copied.
        _raise_if_cancelled(should_cancel, "stopped before the previous cache was replaced")

        # Blow away any prior cache. Uses a retry loop because on Windows
        # (particularly under OneDrive) a transient handle from the
        # just-exited unforge.exe or from the OneDrive/Defender/indexer
        # stack can reject the first few rmdir attempts with WinError 5.
        if dataforge_cache_dir.exists():
            robust_rmtree(dataforge_cache_dir)
        dataforge_cache_dir.mkdir(parents=True, exist_ok=True)

        # Cache only the subtrees the enhancement generator actually reads.
        # See DATAFORGE_KEEP_SUBPATHS for the list and rationale — dropping
        # the unused ~30k/~1 GB worth of entries halves cache file count and
        # makes every re-extract + clear-cache noticeably faster on the
        # OneDrive/Defender/Indexer-burdened Windows paths our users live in.
        cache_libs = dataforge_cache_dir / DATAFORGE_LIBS_SUBPATH
        logger.info(f"Saving DataForge extraction to {cache_libs}…")
        copied, skipped = _copy_filtered_records(libs_dir / "libs", cache_libs)
        logger.info(
            f"DataForge cache written: {copied}/{len(DATAFORGE_KEEP_SUBPATHS)} "
            f"keep-subpaths copied ({skipped} not present in this build)"
        )

        # Stamp the source Data.p4k's mtime AND size so a later launch can tell
        # whether this cache is still current. Size is the reliable signal —
        # see dataforge_cache_is_fresh — because the RSI launcher's file
        # verification bumps Data.p4k's mtime on game launches without changing
        # its content, and a multi-GB re-extract on every such benign touch is
        # exactly the needless work issue #209 reported.
        p4k_stat = p4k_path.stat()
        (dataforge_cache_dir / P4K_MTIME_STAMP).write_text(str(p4k_stat.st_mtime))
        (dataforge_cache_dir / P4K_SIZE_STAMP).write_text(str(p4k_stat.st_size))
        logger.info(f"DataForge cache written to {dataforge_cache_dir}")
    finally:
        # Success, failure or stop, the working folder goes now (#471), so
        # its ~2 GB never outlives the copy and a stopped run cleans up after
        # itself. _close_scratch never raises over the real outcome.
        _close_scratch(run_dir, marker)

    # A stop that arrived during the copy ends here. The cache is complete and
    # stamped; the next generation treats a missing manifest as "regenerate
    # everything", which is what it does anyway.
    _raise_if_cancelled(should_cancel, "stopped once the new cache was written")

    # Snapshot the new cache so the next run can diff against it.
    # SHA-256 over ~28k files is multi-minute serial; we surface it
    # to the progress bar (and parallelize it inside update_manifest)
    # so the UI doesn't appear frozen.
    logger.info("Snapshotting DataForge cache for diff manifest…")
    if progress_callback:
        progress_callback(tr("progress.snapshot_diff"))
    update_manifest(cache_libs, progress_callback=progress_pct_callback)
    logger.info("Diff manifest written")

    # Ensure all file handles are released before returning
    gc.collect()
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
