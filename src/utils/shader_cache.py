"""Find, clean and remove Star Citizen's shader cache folders.

The game keeps one cache folder per build under
``%LOCALAPPDATA%\\Star Citizen\\``, named like
``starcitizen_(sc-alpha-4.10.2)_hg78hb_0``. Each holds ``shaders``,
``vulkanshadercache`` and ``GraphicsSettings``. Only the first two are cache
(the game rebuilds them on the next launch); ``GraphicsSettings`` is kept.
Other entries there (``crashes``) are not build folders and are never listed.

Qt-free so it can be tested without a QApplication.
"""
from __future__ import annotations

import logging
import os
import re
import stat
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from src.utils.pak_extractor import is_link_stat

logger = logging.getLogger(__name__)

SC_LOCAL_DIR_NAME = "Star Citizen"
GAME_EXE_NAME = "StarCitizen.exe"
_DELETE_THREADS = 16

_CACHE_DIR_RE = re.compile(
    r"^starcitizen_\((?P<branch>[^)]+)\)_(?P<id>[^_]+)_\d+$", re.IGNORECASE
)
_ALPHA_BRANCH_RE = re.compile(r"^sc-alpha-(?P<version>[\d.]+)$", re.IGNORECASE)

# Subfolders of a build folder that hold the shader cache. Everything else
# in the build folder (GraphicsSettings) is left alone.
SHADER_CACHE_SUBDIRS = ("shaders", "vulkanshadercache")


@dataclass(frozen=True)
class ShaderCacheDir:
    path: Path
    label: str
    is_clean: bool  # no shader cache subfolder has anything in it


def _is_link(path: Path) -> bool:
    """Symlink or NTFS junction (``Path.is_symlink()`` misses junctions).

    Same rule as the DataForge cache cleanup: other reparse points, such as
    OneDrive placeholders or deduplicated files, are ordinary entries.
    """
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return is_link_stat(st)


def _has_content(path: Path) -> bool:
    if _is_link(path):
        return False  # never followed or deleted, so nothing to clean
    try:
        return path.is_dir() and any(path.iterdir())
    except OSError:
        return True  # unreadable: let the delete try and report it


def get_shader_cache_root() -> Path:
    """``%LOCALAPPDATA%\\Star Citizen``.

    Falls back to ``~\\AppData\\Local`` when LOCALAPPDATA is unset, the same
    default ``AppSettings`` uses.
    """
    local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    return Path(local) / SC_LOCAL_DIR_NAME


def humanize_cache_name(name: str) -> str:
    """``starcitizen_(sc-alpha-4.10.2)_hg78hb_0`` -> ``Star Citizen Alpha 4.10.2 (hg78hb)``.

    Any other branch (``sc-patch-inc``) is a Tech Preview build and becomes
    ``Star Citizen Tech Preview (<id>)``. A name that does not match the cache
    pattern comes back unchanged.
    """
    match = _CACHE_DIR_RE.match(name)
    if not match:
        return name
    alpha = _ALPHA_BRANCH_RE.match(match.group("branch"))
    if alpha:
        branch_label = f"Star Citizen Alpha {alpha.group('version')}"
    else:
        branch_label = "Star Citizen Tech Preview"
    return f"{branch_label} ({match.group('id')})"


def find_shader_cache_dirs(root: Path | None = None) -> list[ShaderCacheDir]:
    """List the build folders under *root*, sorted by folder name."""
    if root is None:
        root = get_shader_cache_root()
    if not root.is_dir():
        return []
    found = [
        ShaderCacheDir(
            path=entry,
            label=humanize_cache_name(entry.name),
            is_clean=not any(_has_content(entry / sub) for sub in SHADER_CACHE_SUBDIRS),
        )
        for entry in root.iterdir()
        if entry.is_dir() and not _is_link(entry) and _CACHE_DIR_RE.match(entry.name)
    ]
    return sorted(found, key=lambda d: d.path.name.lower())


def is_star_citizen_running() -> bool:
    """True when a StarCitizen.exe process is running.

    A running game holds its shader files open, so a delete would stop part
    way and leave the cache half removed. False when tasklist is unavailable.
    """
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {GAME_EXE_NAME}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning(f"Could not check whether Star Citizen is running: {e}")
        return False
    return GAME_EXE_NAME.lower() in result.stdout.lower()


def _delete_with_retry(func, path) -> None:
    """Run os.unlink / os.rmdir; on a read-only entry clear the bit and retry once."""
    try:
        func(path)
    except PermissionError:
        os.chmod(path, stat.S_IWRITE)
        func(path)


def _unlink_link(path: str) -> None:
    # A directory symlink or junction is removed as a directory entry, never
    # followed into; a file symlink needs unlink.
    try:
        os.rmdir(path)
    except OSError:
        os.unlink(path)


def _rmtree(path: Path) -> None:
    """Delete *path* and everything in it, files in parallel.

    A cache folder is ~10-14k files in a handful of folders. Unlinking them
    on _DELETE_THREADS threads measured ~40% faster than shutil.rmtree (and
    than ``rmdir /s /q``; robocopy /MIR was ~20x slower). Links inside the
    tree are removed, never followed. Raises the first OSError after trying
    every entry, so one locked file doesn't stop the rest from going.
    """
    if _is_link(path):
        raise OSError(f"Refusing to delete through a link: {path}")
    errors: list[OSError] = []
    files: list[str] = []
    dirs: list[str] = []
    links: list[str] = []
    for dirpath, dirnames, filenames in os.walk(path, onerror=errors.append):
        dirs.append(dirpath)
        for name in list(dirnames):
            full = os.path.join(dirpath, name)
            if _is_link(Path(full)):
                dirnames.remove(name)
                links.append(full)
        files.extend(os.path.join(dirpath, name) for name in filenames)

    def unlink(file_path: str) -> None:
        try:
            _delete_with_retry(os.unlink, file_path)
        except OSError as e:
            errors.append(e)

    with ThreadPoolExecutor(max_workers=_DELETE_THREADS) as pool:
        list(pool.map(unlink, files, chunksize=64))
    for link in links:
        try:
            _unlink_link(link)
        except OSError as e:
            errors.append(e)
    if errors:
        raise errors[0]
    for dir_path in reversed(dirs):  # os.walk is top-down: deepest last
        _delete_with_retry(os.rmdir, dir_path)


def _is_build_folder(path: Path, root: Path | None) -> bool:
    # Guard against a wrong path handed in by mistake: only a real build
    # folder directly under the cache root is ever touched.
    if root is None:
        root = get_shader_cache_root()
    in_root = (
        os.path.normcase(os.path.abspath(path.parent))
        == os.path.normcase(os.path.abspath(root))
    )
    if in_root and _CACHE_DIR_RE.match(path.name) and path.is_dir() and not _is_link(path):
        return True
    logger.warning(f"Refused to touch non-cache folder: {path}")
    return False


def _delete_entry(target: Path) -> None:
    """Delete a cache subfolder, or a stray file of the same name."""
    if target.is_dir() and not _is_link(target):
        _rmtree(target)
    else:
        os.chmod(target, stat.S_IWRITE)
        target.unlink()


def clean_shader_cache(path: Path, root: Path | None = None) -> bool:
    """Delete the ``shaders`` and ``vulkanshadercache`` subfolders of a build.

    Keeps ``GraphicsSettings`` and the build folder itself. *root* is the
    cache root *path* must sit in (default: the real one). Returns False when
    *path* is not a build folder or a subfolder could not be fully removed.
    """
    if not _is_build_folder(path, root):
        return False
    ok = True
    for sub in SHADER_CACHE_SUBDIRS:
        target = path / sub
        if not os.path.lexists(target) or _is_link(target):
            continue
        try:
            _delete_entry(target)
            logger.info(f"Cleaned shader cache: {target}")
        except OSError as e:
            logger.warning(f"Could not clean shader cache {target}: {e}")
            ok = False
    return ok


def remove_build_folder(path: Path, root: Path | None = None) -> bool:
    """Hard-delete a whole build folder, ``GraphicsSettings`` included.

    *root* is the cache root *path* must sit in (default: the real one).
    Returns False when *path* is not a build folder or could not be removed.
    """
    if not _is_build_folder(path, root):
        return False
    try:
        _rmtree(path)
        logger.info(f"Removed shader cache folder: {path}")
        return True
    except OSError as e:
        logger.warning(f"Could not remove shader cache folder {path}: {e}")
        return False
