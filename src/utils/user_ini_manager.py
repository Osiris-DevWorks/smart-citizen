"""User INI persistence and import utilities."""
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from src.models.string_model import StringEntry
from src.parser.ini_parser import parse_ini_file
from src.utils.install_scanner import SC_CHANNELS
from src.utils.perf import timed

logger = logging.getLogger(__name__)

# What Smart Citizen writes in its data folder's root since the 0.9.3 channel
# layout: a folder per channel, and logs (crash dumps and log exports). The
# installer's DeleteOwnedSubpaths knows the same folders.
OWNED_DATA_FOLDERS = (*SC_CHANNELS, "logs")


def migrate_user_data_dir(
    old_root: "str | Path", new_root: "str | Path", *, move: bool = False,
    exclude: "Optional[Callable[[Path], bool]]" = None,
) -> int:
    """Copy (or move) user data from ``old_root`` into ``new_root`` after the
    user changes the Smart Citizen data folder (issue #103).

    Copies/moves every file under ``old_root`` to the matching path under
    ``new_root``, **merging** rather than overwriting: any file that already
    exists at the destination is left untouched, so data already in the new
    location always wins.

    When ``move=True``, each successfully copied file is deleted from
    ``old_root``, and empty directories are pruned from the source tree
    afterwards (deepest first).  Files that were skipped because the
    destination already existed are left in place, so no data is lost.

    When ``move=False`` (default), the originals are left untouched — copy
    semantics, safe to re-run.

    ``exclude``, when given, is asked about each file's path relative to
    ``old_root``; a file it says yes to is left where it is, neither moved
    nor counted (#455 leaves the DataForge cache trees behind this way).

    Returns the number of files transferred. A no-op (returns 0) when the old
    root is missing or resolves to the same directory as the new root.

    Handles the case where the new folder is nested inside the old one: the
    file list is snapshotted before any copy (so freshly-written files can't
    be fed back into a lazy walk), and any source already under the
    destination is skipped (so the new folder's own contents aren't recursively
    re-copied into themselves).
    """
    old_root = Path(old_root)
    new_root = Path(new_root)
    try:
        old_resolved = old_root.resolve()
        new_resolved = new_root.resolve()
    except OSError:
        return 0
    if not old_root.exists() or old_resolved == new_resolved:
        return 0

    transferred = 0
    # Snapshot up front — if new_root is nested in old_root, copying into it
    # mid-walk would otherwise let a lazy rglob re-yield the new files.
    for src in list(old_root.rglob("*")):
        if src.is_dir():
            continue
        rel = src.relative_to(old_root)
        # Asked before the resolve below, so an excluded tree of thousands of
        # files costs only the walk.
        if exclude is not None and exclude(rel):
            continue
        # Skip anything already under the destination (the new-inside-old
        # case), so we don't recursively re-copy the new folder's contents.
        try:
            src.resolve().relative_to(new_resolved)
            continue  # src is inside new_root → leave it alone
        except (ValueError, OSError):
            pass  # not under new_root → migrate it
        dest = new_root / rel
        if dest.exists():
            continue  # never clobber data already present in the new location
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            if move:
                src.unlink()
            transferred += 1
        except OSError as e:
            logger.warning(f"Could not migrate {src} -> {dest}: {e}")

    if move:
        # Prune now-empty directories from old_root (deepest-path first so
        # parents are removed after their children).
        for d in sorted(old_root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if d.is_dir() and not any(d.iterdir()):
                try:
                    d.rmdir()
                except OSError:
                    pass
        # Remove old_root itself if it is now empty.
        try:
            if old_root.exists() and not any(old_root.iterdir()):
                old_root.rmdir()
        except OSError:
            pass

    verb = "Moved" if move else "Migrated"
    logger.info(f"{verb} {transferred} file(s) from {old_root} to {new_root}")
    return transferred


def _is_dataforge_cache(rel: Path) -> bool:
    """A DataForge cache tree, or an extraction's work folder, in a channel
    folder's ``cache`` (``rel`` is relative to the channel folder). An old
    data folder can still hold the pre-1.0 DataForge cache there, about
    28,000 files that ``migrate_dataforge_cache_to_local`` would only delete
    or queue again, and a queued ``pending_cache_cleanup`` may name it where
    it is. It is rebuilt by an extraction, so it is not moved (#455)."""
    parts = [part.lower() for part in rel.parts]
    return len(parts) > 2 and parts[0] == "cache" and (
        parts[1] == "dataforge" or parts[1].startswith(("dataforge.", "globalini.extracting-"))
    )


@dataclass(frozen=True)
class DataMoveResult:
    """What :func:`move_owned_user_data` did: the files it moved, and the
    Smart Citizen files still in the old folder afterwards."""
    old_root: Path
    new_root: Path
    moved: int
    left: tuple


def move_owned_user_data(old_root: "str | Path", new_root: "str | Path") -> DataMoveResult:
    """Move Smart Citizen's own folders (``OWNED_DATA_FOLDERS``) from
    ``old_root`` into ``new_root``, for the move Setup asks for when the user
    leaves a OneDrive data folder (#455).

    Nobody is asked first, so only what the app writes there moves. A data
    folder set to a general folder, such as OneDrive's Documents itself,
    keeps its other files. Each folder goes through
    :func:`migrate_user_data_dir` with ``move=True``: merged, never
    overwriting, so a file already in ``new_root`` wins and its old copy
    stays, as does a file that cannot be moved. ``left`` lists what stayed.
    The DataForge cache trees in each channel's ``cache`` are left out of
    both (``_is_dataforge_cache``): rebuilt by an extraction, not user data.
    ``old_root`` itself is removed when that leaves it empty. The same
    folder, or an old folder that is gone, moves nothing.
    """
    old_root = Path(old_root)
    new_root = Path(new_root)
    nothing = DataMoveResult(old_root, new_root, 0, ())
    try:
        if old_root.resolve() == new_root.resolve():
            return nothing
        owned = {name.upper() for name in OWNED_DATA_FOLDERS}
        folders = [p for p in old_root.iterdir() if p.is_dir() and p.name.upper() in owned]
    except OSError as e:
        logger.warning(f"Could not read the old data folder {old_root}: {e}")
        return nothing

    moved = 0
    for folder in folders:
        moved += migrate_user_data_dir(folder, new_root / folder.name, move=True,
                                       exclude=_is_dataforge_cache)
    left = []
    for folder in folders:
        try:
            left.extend(p for p in folder.rglob("*")
                        if p.is_file() and not _is_dataforge_cache(p.relative_to(folder)))
        except OSError:
            left.append(folder)
    try:
        if not any(old_root.iterdir()):
            old_root.rmdir()
    except OSError:
        pass
    if left:
        # The startup box points at the Log tab for these.
        logger.warning(f"{len(left)} Smart Citizen file(s) stayed in {old_root}:")
        for path in left:
            logger.warning(f"  {path}")
    return DataMoveResult(old_root, new_root, moved, tuple(left))


def reset_user_ini(user_ini_path: Path, backup: bool = True) -> Optional[Path]:
    """Remove ``user.ini`` for the active channel, optionally renaming it to a
    timestamped backup first.

    Used by the "Reset user.ini" tools-tab button. Returns the backup path
    when ``backup=True`` and a rename happened, otherwise ``None``.

    If the file doesn't exist, returns ``None`` — caller should treat that
    as a no-op (e.g. surface "already at stock values").

    Backup naming: ``user.ini.bak-YYYYMMDD-HHMMSS`` next to the original. If
    the timestamped target somehow already exists (double-click producing
    two resets inside one second), a numeric suffix ``-2`` / ``-3`` / … is
    appended until a free name is found, so the second click can never
    silently destroy the first backup.
    """
    if not user_ini_path.exists():
        return None

    if not backup:
        user_ini_path.unlink()
        logger.info(f"Deleted user.ini (no backup) at {user_ini_path}")
        return None

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = user_ini_path.with_name(f"{user_ini_path.name}.bak-{timestamp}")
    suffix = 2
    while candidate.exists():
        candidate = user_ini_path.with_name(
            f"{user_ini_path.name}.bak-{timestamp}-{suffix}"
        )
        suffix += 1

    user_ini_path.rename(candidate)
    logger.info(f"Reset user.ini: {user_ini_path} → backup {candidate}")
    return candidate


# Rotating snapshots of user.ini live alongside the game-file backups, in the
# active channel's backups/ dir, under a distinct prefix so they never collide
# with global.ini.bak_* or with reset_user_ini's sibling user.ini.bak-* files.
USER_INI_BACKUP_PREFIX = "user.ini.bak_"
MAX_USER_INI_BACKUPS = 5


def _user_ini_backups_dir(user_ini_path: Path) -> Path:
    """The channel's backups/ dir, derived from the user.ini path.

    user.ini lives at ``{root}/{channel}/user.ini`` and backups at
    ``{root}/{channel}/backups`` — i.e. ``AppSettings.get_backups_dir()`` — so
    deriving it here keeps this module Qt-free and registry-free (testable with
    plain tmp paths).
    """
    return user_ini_path.parent / "backups"


def backup_user_ini(
    user_ini_path: Path, *, keep: int = MAX_USER_INI_BACKUPS
) -> Optional[Path]:
    """Snapshot the current user.ini into the channel's backups/ dir.

    Rotates oldest-first to keep at most ``keep`` snapshots. Returns the backup
    path, or ``None`` when there's nothing worth saving (file missing or empty).

    This is the safety net for user.ini: the one file holding all of a user's
    hand-entered edits previously had no backups (only the applied game
    global.ini did), so a truncation or a OneDrive sync emptying the file was
    unrecoverable. Snapshotting before every content-changing write makes the
    last ``keep`` distinct states restorable.
    """
    try:
        if not user_ini_path.exists() or user_ini_path.stat().st_size == 0:
            return None
    except OSError:
        return None

    backups_dir = _user_ini_backups_dir(user_ini_path)
    try:
        backups_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning(f"Could not create backups dir {backups_dir}: {e}")
        return None

    # Rotate: drop oldest until making room for one more keeps us at <= keep.
    # Sort by name, not mtime: the timestamp in the name is fixed-width and
    # zero-padded, so lexicographic order is chronological order — deterministic
    # even when several saves land in the same clock tick (mtime ties are not).
    existing = sorted(
        backups_dir.glob(f"{USER_INI_BACKUP_PREFIX}*"),
        key=lambda p: p.name,
    )
    while len(existing) >= keep:
        oldest = existing.pop(0)
        try:
            oldest.unlink()
            logger.info(f"Deleted oldest user.ini backup: {oldest.name}")
        except OSError:
            break

    # Microsecond resolution so rapid successive saves get distinct, sortable
    # names instead of colliding on a one-second tick.
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    dest = backups_dir / f"{USER_INI_BACKUP_PREFIX}{timestamp}"
    # Same-second collision (two saves inside one second): suffix so the second
    # snapshot can't clobber the first.
    suffix = 2
    while dest.exists():
        dest = backups_dir / f"{USER_INI_BACKUP_PREFIX}{timestamp}-{suffix}"
        suffix += 1

    try:
        shutil.copy2(user_ini_path, dest)
    except OSError as e:
        logger.warning(f"Could not snapshot user.ini to {dest}: {e}")
        return None
    logger.info(f"Backed up user.ini -> {dest}")
    return dest


def list_user_ini_backups(user_ini_path: Path) -> List[Path]:
    """Return this channel's user.ini snapshots, newest first."""
    backups_dir = _user_ini_backups_dir(user_ini_path)
    if not backups_dir.exists():
        return []
    # Newest first by name (fixed-width timestamp → lexicographic == chronological).
    return sorted(
        backups_dir.glob(f"{USER_INI_BACKUP_PREFIX}*"),
        key=lambda p: p.name,
        reverse=True,
    )


def restore_user_ini_backup(backup_path: Path, user_ini_path: Path) -> Path:
    """Restore ``backup_path`` over user.ini, snapshotting the current file
    first so the restore itself is reversible. Returns ``user_ini_path``."""
    # Snapshot the pre-restore state so an unwanted restore can be undone.
    backup_user_ini(user_ini_path)
    user_ini_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup_path, user_ini_path)
    logger.info(f"Restored user.ini from {backup_path}")
    return user_ini_path


def _backup_if_changing(user_ini_path: Path, new_text: str) -> None:
    """Snapshot the existing user.ini before overwriting it with *different*
    content. No-op when the file is missing/empty or the content is unchanged,
    so identical saves don't rotate real history out of the backup set.
    """
    try:
        if user_ini_path.exists() and user_ini_path.stat().st_size > 0:
            # Compare bytes, not decoded text: read_text(encoding="utf-8")
            # raises UnicodeDecodeError (a ValueError, so it sailed past the
            # OSError guard below) if the on-disk file is corrupt — and this
            # runs on EVERY save, so one bad byte bricked all saves (#251
            # bug class). Byte inequality also correctly treats a corrupt
            # file as "changing", so it gets snapshotted before the clean
            # rewrite replaces it. Newlines are normalized first: the save
            # below uses text mode, which writes \n as \r\n on Windows,
            # while new_text carries bare \n — without this every identical
            # save would look "changed" and churn real history out of the
            # 5-slot backup rotation.
            on_disk = (
                user_ini_path.read_bytes()
                .replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            )
            if on_disk != new_text.encode("utf-8"):
                backup_user_ini(user_ini_path)
    except OSError as e:
        logger.warning(
            f"Could not snapshot user.ini before save ({user_ini_path}): {e}"
        )


def should_autosave_user_ini(entries: List[StringEntry], user_ini_path: Path) -> bool:
    """Decide whether the close-time autosave is safe to run.

    Returns False — and the caller skips the write — when the in-memory entry
    list has zero modified entries but ``user_ini_path`` already exists on
    disk with non-zero content. Under those conditions a write would
    truncate the file to 0 bytes, which is the data-loss path reported
    against 1.3.0: a load mismatch (channel/path drift after a migration,
    or a transient I/O hiccup) leaves every entry with an empty
    ``custom_value``, and the unconditional close-time write then clobbers
    a populated user.ini with an empty one.

    All other cases return True:
      * Modified entries exist → write captures the user's edits.
      * File doesn't exist → first save, nothing to protect.
      * File is already empty → write is a no-op rewrite.

    Trade-off: a user who manually reverts *every* edit and closes will
    not have their clear persisted via autosave. The explicit Apply-to-Game
    path remains the authoritative "persist current state" action.
    """
    if any(e.is_modified for e in entries):
        return True
    try:
        if user_ini_path.exists() and user_ini_path.stat().st_size > 0:
            logger.warning(
                f"Skipping autosave: in-memory state has no overrides but "
                f"on-disk user.ini has {user_ini_path.stat().st_size} bytes "
                f"({user_ini_path}). Preserving disk contents to guard against "
                f"a load mismatch."
            )
            return False
    except OSError as e:
        logger.warning(f"Could not stat user.ini for autosave guard ({user_ini_path}): {e}")
    return True


@timed
def save_user_ini(entries: List[StringEntry], user_ini_path: Path) -> int:
    """Write only user-modified entries to user.ini.

    Args:
        entries: List of StringEntry objects from self.entries
        user_ini_path: Destination path for user.ini

    Returns:
        Number of entries written

    Raises:
        IOError: If write fails
    """
    # Filter to entries the user actually modified (custom differs from original)
    user_edits = {
        entry.key: entry.custom_value
        for entry in entries
        if entry.is_modified
    }

    new_text = "".join(f"{key}={value}\n" for key, value in user_edits.items())
    user_ini_path.parent.mkdir(parents=True, exist_ok=True)
    # Snapshot the prior file before overwriting, so even a truncating write
    # (empty edits over a populated file) stays recoverable.
    _backup_if_changing(user_ini_path, new_text)

    try:
        with open(user_ini_path, 'w', encoding='utf-8') as f:
            f.write(new_text)

        count = len(user_edits)
        logger.info(f"Saved {count} user edits to {user_ini_path}")
        return count

    except Exception as e:
        logger.error(f"Failed to save user.ini: {e}")
        raise


@timed
def save_user_ini_dict(data: Dict[str, str], user_ini_path: Path) -> int:
    """Write a raw key-value dict to user.ini.

    Used by the import flow where we have a pre-merged dict rather than
    StringEntry objects.

    Args:
        data: Dict of key → value pairs to write
        user_ini_path: Destination path for user.ini

    Returns:
        Number of entries written
    """
    new_text = "".join(f"{key}={value}\n" for key, value in data.items())
    user_ini_path.parent.mkdir(parents=True, exist_ok=True)
    _backup_if_changing(user_ini_path, new_text)

    try:
        with open(user_ini_path, 'w', encoding='utf-8') as f:
            f.write(new_text)

        count = len(data)
        logger.info(f"Saved {count} entries to {user_ini_path}")
        return count

    except Exception as e:
        logger.error(f"Failed to save user.ini: {e}")
        raise


@timed
def generate_user_ini_from_diff(
    reference_path: Path,
    current_path: Path,
    user_ini_path: Path
) -> int:
    """Diff reference vs current file, write differing keys as user.ini.

    Used on first run to bootstrap user edits from existing game file.

    Args:
        reference_path: Path to reference base file (base.ini)
        current_path: Path to current game file (global.ini)
        user_ini_path: Destination path for user.ini

    Returns:
        Number of entries written, or 0 if skipped (missing files, etc.)
    """
    if not reference_path.exists():
        logger.debug(f"Reference file not found: {reference_path}")
        return 0

    if not current_path.exists():
        logger.debug(f"Current file not found: {current_path}")
        return 0

    if user_ini_path.exists():
        logger.debug(f"user.ini already exists: {user_ini_path}")
        return 0

    try:
        # strip_values=False so a favourite applied with a space prefix is
        # captured verbatim in the diff rather than collapsing to equal (#100).
        reference = parse_ini_file(reference_path, strip_values=False)
        current = parse_ini_file(current_path, strip_values=False)

        diffs = {}
        for key, current_value in current.items():
            reference_value = reference.get(key, "")
            if current_value != reference_value:
                diffs[key] = current_value

        if not diffs:
            logger.info("No differences found between reference and current file")
            return 0

        user_ini_path.parent.mkdir(parents=True, exist_ok=True)
        with open(user_ini_path, 'w', encoding='utf-8') as f:
            for key, value in diffs.items():
                f.write(f"{key}={value}\n")

        logger.info(f"Bootstrapped {len(diffs)} user edits from diff")
        return len(diffs)

    except Exception as e:
        logger.warning(f"Failed to generate user.ini from diff: {e}")
        return 0
