"""Windows extended-length path helper, shared by any module that reads or
writes deep into the DataForge cache tree.
"""
import os
import sys

_LONG_PREFIX = "\\\\?\\"
_LONG_UNC_PREFIX = "\\\\?\\UNC\\"


def win_long_path(path) -> str:
    """Return *path* as a Windows extended-length path string when needed.

    DataForge's ~28k-file entity tree uses long CIG-authored filenames
    (e.g. ``softlock_terminal_standard_lowtech_commoditykiosk_console_
    transfers_1_straight_a.xml``); once nested under a user's install
    directory plus the per-channel cache layout, the destination path can
    exceed the legacy 260-char ``MAX_PATH``, and ``shutil``/``os``/lxml raise
    ``WinError 3`` ("The system cannot find the path specified") even
    though the path is otherwise valid (#221). The ``\\\\?\\`` prefix tells
    the Win32 API to skip that check (paths up to ~32,767 chars). No-op on
    non-Windows platforms and on paths that are already prefixed (checked
    before any transformation, so this really is a no-op for those).

    Uses ``os.path.abspath`` (absolute + normalized: no ``.``/``..``, no
    symlink/junction resolution) rather than ``Path.resolve()`` — the
    ``\\\\?\\`` prefix only needs a fully qualified path, and resolving
    symlinks would quietly rewrite a cache root behind a junction or subst
    drive to its real path everywhere downstream (logs, error messages),
    which is more than this fix is asking for.
    """
    if sys.platform != "win32":
        return str(path)
    p = str(path)
    if p.startswith(_LONG_PREFIX):
        return p
    p = os.path.abspath(p)
    if p.startswith("\\\\"):
        # UNC path: \\server\share\... -> \\?\UNC\server\share\...
        return _LONG_UNC_PREFIX + p[2:]
    return _LONG_PREFIX + p


def win_plain_path(path) -> str:
    """The inverse of :func:`win_long_path`: *path* made absolute, without the
    extended-length prefix, and with the UNC form turned back into a plain
    share path (#471).

    For a path that leaves the process or gets compared as text: unp4k and
    unforge are only ever handed plain paths (whether they accept the prefix
    was never tested), and ``onedrive.is_onedrive_path`` cannot match its
    environment roots against a prefixed path. No-op on non-Windows, like
    :func:`win_long_path`.
    """
    if sys.platform != "win32":
        return str(path)
    p = str(path)
    if p.startswith(_LONG_UNC_PREFIX):
        p = "\\\\" + p[len(_LONG_UNC_PREFIX):]
    elif p.startswith(_LONG_PREFIX):
        p = p[len(_LONG_PREFIX):]
    return os.path.abspath(p)
