"""Write a file in one step, so a run that is cut off never leaves it half written.

An enhancements generation writes up to nine INIs, the two stamp files beside
them and the lookup pickles under the DataForge cache's ``.lookups`` folder,
and the DataForge patcher rewrites cache XMLs. All of them used to be written
in place, so a run cut off by a close or a crash left the file it was writing
truncated, and later reads took it as whole: an enhancement category with
half its entries, a patched XML that ``.p4k_mtime`` still called fresh.
:func:`atomic_writer` writes to a temp file beside the target and swaps it in
with ``os.replace``, so a reader only ever sees the old file or the new one.

Measured on Windows:

* ``os.replace`` fails with PermissionError (WinError 5) while any other
  handle has the target open, even one opened with delete sharing. The swap
  retries a PermissionError for about 1.3 s, then gives up and leaves the old
  file whole.
* A reader that opens the file during the swap gets PermissionError for a
  moment, so readers of these files go through :func:`read_bytes_retrying`.
* Text mode keeps the bytes ``Path.write_text`` wrote: CRLF line ends on
  Windows, UTF-8, no BOM.
* The temp file is made here, not with ``tempfile.mkstemp``. On Python 3.11,
  which the release builds use, mkstemp also retries a PermissionError, up
  to ``os.TMP_MAX`` (2,147,483,647) times on Windows, so a folder that
  refuses new files (Controlled Folder Access, a read-only share) hung the
  write for about two days instead of failing it. Here only a name that is
  already taken is retried, and a refusal fails at once, naming the target.

Never fall back to writing in place when the swap fails. That brings back the
partial reads this module exists to stop (3271 of 3391 reads were partial in
a race probe against an in-place write).

Stdlib only, with no Qt and no settings: the generator script imports it
through its ``src`` shim, and a test runs it in a child on the base
interpreter.
"""
from __future__ import annotations

import errno
import os
import secrets
import time
from contextlib import contextmanager
from pathlib import Path

# A temp name is the prefix, 8 random hex characters and the suffix, 16
# characters in all: shorter than every INI name, and only a few characters
# longer than the shortest pickle name (standings.pkl). It never ends in
# ".ini", so Clear Cache's *.ini glob and every exact-name reader skip it.
TEMP_PREFIX = ".sc-"
TEMP_SUFFIX = ".tmp"
# secrets.token_hex writes two hex characters per byte: 4 bytes, 8 characters.
TEMP_RANDOM_BYTES = 4

# How many random names the temp file's creation tries. Only a name that is
# already taken is retried, which with 8 hex characters almost never
# happens; 20 is what Python 3.14's tempfile allows. Any other error (a
# folder that refuses new files, a missing folder) is never retried.
TEMP_CREATE_ATTEMPTS = 20

# The flags tempfile.mkstemp opened the temp with, write-only rather than
# read-write since the file object only writes. O_EXCL never opens a file
# that is already there, another write's temp or a link (so mkstemp's
# O_NOFOLLOW adds nothing). O_BINARY matches mkstemp but changes nothing
# here: os.fdopen's FileIO switches the descriptor to binary mode on Windows
# anyway, so the text layer's newline translation is the only one and the
# file gets CRLF exactly as Path.write_text wrote it. O_NOINHERIT, which os.open sets on
# Windows anyway, keeps the handle out of any child process, where it could
# hold the file open and block the swap.
_TEMP_OPEN_FLAGS = (
    os.O_WRONLY | os.O_CREAT | os.O_EXCL
    | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0)
)
# The mode open() and Path.write_text create a file with, so a new file gets
# the same permissions as the old in-place writes gave it (mkstemp's 0o600
# made it owner-only on POSIX). On Windows the mode only decides whether the
# file is read-only, and this one leaves it writable.
_TEMP_FILE_MODE = 0o666

# The swap's retry on PermissionError. The delay doubles each try up to the
# cap: about 1.3 s in all before the write fails.
REPLACE_ATTEMPTS = 10
REPLACE_FIRST_DELAY_S = 0.01
REPLACE_MAX_DELAY_S = 0.25

# A reader's retry on PermissionError, about 0.15 s in all. A swap holds the
# file for a moment only.
READ_ATTEMPTS = 4
READ_DELAY_S = 0.05

# A temp file is left behind only by a hard kill between its creation and the
# swap. The same 10-minute grace as the extraction's unmarked working folders
# (pak_extractor), so a write still running in another window is never swept.
STALE_TEMP_AGE_S = 600


@contextmanager
def atomic_writer(path, mode: str = "w", *, encoding: str = "utf-8"):
    """Yield a file whose contents replace *path* in one step when the block ends.

    *mode* is ``"w"`` (text, *encoding*) or ``"wb"``. The temp file is made
    in *path*'s folder, which must exist. A folder that refuses a new file
    raises PermissionError at once, naming *path* (see
    :func:`_create_temp_beside`). After the block the file is flushed,
    synced to disk and closed (an open source cannot be swapped in, WinError
    32), then moved over *path* with ``os.replace``. Only a PermissionError
    from the swap is retried, with the backoff above. Any other error (a full
    disk, a path too long) raises at once.

    If the block raises, or the swap never completes, the temp file is
    removed and the error re-raised: *path* keeps its old contents, or stays
    missing if it was missing. That includes KeyboardInterrupt.
    """
    if mode not in ("w", "wb"):
        raise ValueError(f"atomic_writer mode must be 'w' or 'wb', not {mode!r}")
    path = Path(path)
    fd, tmp = _create_temp_beside(path)
    try:
        try:
            if mode == "wb":
                f = os.fdopen(fd, "wb")
            else:
                f = os.fdopen(fd, "w", encoding=encoding)
        except BaseException:
            os.close(fd)
            raise
        with f:
            yield f
            f.flush()
            os.fsync(f.fileno())
        _replace_retrying(tmp, path)
    except BaseException:
        _unlink_quietly(tmp)
        raise


def atomic_write_text(path, text: str, *, encoding: str = "utf-8") -> None:
    """Replace *path*'s contents with *text* in one step (see :func:`atomic_writer`)."""
    with atomic_writer(path, "w", encoding=encoding) as f:
        f.write(text)


def read_bytes_retrying(path) -> bytes:
    """``Path(path).read_bytes()``, retried on PermissionError only.

    A reader that opens a file while :func:`atomic_writer` swaps it gets a
    PermissionError for a moment. It is retried up to ``READ_ATTEMPTS`` times,
    then re-raised. Any other OSError (a missing file) raises at once.
    """
    attempt = 1
    while True:
        try:
            return Path(path).read_bytes()
        except PermissionError:
            if attempt >= READ_ATTEMPTS:
                raise
        attempt += 1
        time.sleep(READ_DELAY_S)


def sweep_stale_temps(folder, max_age_s: float = STALE_TEMP_AGE_S) -> int:
    """Remove this module's temp files older than *max_age_s* from *folder*.

    Looks only at ``.sc-*.tmp`` files directly in *folder*, never below it. A
    missing folder and any OSError are ignored. Returns how many it removed.
    """
    cutoff = time.time() - max_age_s
    removed = 0
    try:
        candidates = list(Path(folder).glob(f"{TEMP_PREFIX}*{TEMP_SUFFIX}"))
    except OSError:
        return 0
    for candidate in candidates:
        try:
            if candidate.is_file() and candidate.stat().st_mtime < cutoff:
                candidate.unlink()
                removed += 1
        except OSError:
            pass
    return removed


def _create_temp_beside(path: Path) -> tuple[int, str]:
    """Create and open a new ``.sc-XXXXXXXX.tmp`` file in *path*'s folder.

    Returns the open file descriptor and the temp's path. A name that is
    already taken (FileExistsError) is retried with a new random name, up to
    ``TEMP_CREATE_ATTEMPTS`` times. Any other OSError, such as a
    PermissionError from a folder that refuses new files or a
    FileNotFoundError from a missing one, raises at once.

    Every error raised here names *path*, not the temp: the error dialog and
    the log then say which file could not be written, as the old in-place
    writes did, rather than a temp name nobody has seen.
    """
    for _ in range(TEMP_CREATE_ATTEMPTS):
        name = f"{TEMP_PREFIX}{secrets.token_hex(TEMP_RANDOM_BYTES)}{TEMP_SUFFIX}"
        tmp = str(path.parent / name)
        try:
            return os.open(tmp, _TEMP_OPEN_FLAGS, _TEMP_FILE_MODE), tmp
        except FileExistsError:
            continue
        except OSError as e:
            # The same error, with its type, errno and (on Windows) winerror;
            # only the file it names changes. os.open sets no second file,
            # and setting filename2 (even to None) would print "-> None".
            e.filename = str(path)
            raise
    raise FileExistsError(
        errno.EEXIST,
        f"No free temp file name in {TEMP_CREATE_ATTEMPTS} tries",
        str(path),
    )


def _replace_retrying(source: str, target: Path) -> None:
    """``os.replace(source, target)``, retrying a PermissionError with backoff."""
    attempt = 1
    delay = REPLACE_FIRST_DELAY_S
    while True:
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt >= REPLACE_ATTEMPTS:
                raise
        attempt += 1
        time.sleep(delay)
        delay = min(delay * 2, REPLACE_MAX_DELAY_S)


def _unlink_quietly(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
