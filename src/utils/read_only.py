"""Clearing the read-only flag on a file Smart Citizen is about to replace.

Windows refuses to open a read-only file for writing, or to delete it, with
"[Errno 13] Permission denied", the same error a missing permission gives.
Some guides and tools mark the game's global.ini read-only, and
``shutil.copy2`` carries the flag into every backup made from it, so Apply
to Game, the backup rotation, Restore Backup and Clear Localization clear
it first.
"""

import logging
import os
import stat
from pathlib import Path

logger = logging.getLogger(__name__)


def clear_read_only(path: str | Path) -> bool:
    """Clear ``path``'s read-only flag when it is set.

    True when the flag was set and is now cleared. A missing file, a file
    that is already writable, and a flag Windows will not let us change all
    return False: the write that follows then fails with its own error,
    which the caller reports.
    """
    try:
        mode = os.stat(path).st_mode
    except OSError:
        return False
    if mode & stat.S_IWRITE:
        return False
    try:
        os.chmod(path, mode | stat.S_IWRITE)
    except OSError as e:
        logger.warning(f"Could not clear the read-only flag on {path}: {e}")
        return False
    logger.info(f"Cleared the read-only flag on {path}")
    return True
