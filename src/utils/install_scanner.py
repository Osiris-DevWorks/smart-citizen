r"""Find *every* Star Citizen install on this machine, not just the first one.

Smart Citizen writes into one install: apply drops ``global.ini`` under
``{sc_install_root}\{channel}\data\Localization\{lang}\`` and
``ensure_user_cfg_language`` sets ``g_language`` in that same channel's
``user.cfg``. When a machine carries more than one install (a moved library
folder, a second drive, a leftover from a reinstall) and Smart Citizen is
pointed at the one the player *doesn't* launch, apply reports success,
``validate_applied_file`` passes, and nothing changes in game. Nothing in the
app could previously surface that, because the only existing lookup
(``settings._scan_common_sc_install_locations``) returns a single install.

This module is the "find them all" half. It is deliberately Qt-free and
settings-free -- it takes explicit inputs and returns plain dataclasses, so it
unit-tests against a temp directory tree with no QSettings registry and no
widgets. The GUI half (``src/gui/duplicate_install_dialog.py``, driven from
the Config tab) resolves the configured root out of ``AppSettings``, passes it
in, and is the only place that writes anything back.

Evidence is gathered in three tiers, cheapest first:

1. **Free** -- the caller's configured root, the legacy installer registry key,
   and the RSI Launcher's own log at
   ``%APPDATA%\rsilauncher\logs\log.log``. The log is the only source that
   knows which install the *launcher* actually installs, patches, and starts,
   which is exactly the fact the filesystem cannot tell you. (Its sibling
   ``launcher store.json`` is encrypted in current launcher builds; don't
   bother with it.)
2. **Cheap** -- the common RSI install paths on every drive letter, shared with
   settings.py via ``iter_common_sc_install_locations``. First-run detection
   in settings.py also ranks hits from ``iter_shallow_sc_install_locations``,
   one folder below the top of each fixed drive.
3. **Opt-in** -- :func:`deep_scan_roots`, a depth-bounded walk of the fixed
   drives for installs at custom paths. Slow enough to need a worker thread,
   a progress callback, and a cancel hook, so it is never run implicitly.

Validation is deliberately stricter than ``settings._is_valid_sc_root``, which
only checks that a channel folder *exists*. A channel folder with no
``Data.p4k`` is a leftover shell, and pointing Smart Citizen at one is a
silent no-op -- so those are still reported, flagged as having no game data,
rather than quietly passing as a real install.
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import re
import string
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from functools import cached_property
from pathlib import Path
from typing import Callable, Iterable, Iterator, Optional

logger = logging.getLogger(__name__)

# Canonical channel-folder names Star Citizen ships under an install root.
# This is the Qt-free source of truth; ``AppSettings.AVAILABLE_CHANNELS`` is
# built from it so the two can't drift (settings.py can't own it -- importing
# settings here would drag PyQt6 into a module that must test without it).
SC_CHANNELS: tuple[str, ...] = ("LIVE", "PTU", "EPTU", "HOTFIX", "TECH-PREVIEW")

GAME_DATA_FILE = "Data.p4k"
BUILD_MANIFEST_FILE = "build_manifest.id"
USER_CFG_FILE = "user.cfg"
LOCALIZATION_DIRNAME = "Localization"

# Proof that a channel-named folder really is a Star Citizen channel.
#
# Channel names alone are not enough, and the thing that proves it is Smart
# Citizen itself: its own per-channel data root (0.9.3+) is
# ``{user_data_root}\{LIVE|PTU|...}\`` holding user.ini / cache / backups /
# dataforge. That is structurally identical to an install root as far as
# "does it contain a LIVE folder" is concerned, so a drive scan happily
# reported the user's own Smart Citizen data folders (and every portable
# build's ``data\`` directory) as Star Citizen installs.
#
# Any ONE of these is enough. Data.p4k alone would be too strict -- it would
# hide exactly the stale-install case this feature exists to catch -- so the
# list covers the files a real install keeps even when its game data has been
# deleted. None of them appear in Smart Citizen's own data tree.
SC_CHANNEL_MARKERS: tuple[str, ...] = (
    GAME_DATA_FILE,
    BUILD_MANIFEST_FILE,
    "Bin64",
    "StarCitizen_Launcher.exe",
    "EasyAntiCheat",
    "client.crt",
)

# The watermark ``main_window._stamp_frontend_version`` appends to the
# Frontend_PU_Version loc key on every apply. Finding it inside an install's
# applied global.ini is proof Smart Citizen wrote *there*, which is the single
# most useful fact when the user is asking "why didn't my edits show up".
APPLY_STAMP_MARKER = "Localizations Enhanced with Smart Citizen v"
_APPLY_STAMP_RE = re.compile(re.escape(APPLY_STAMP_MARKER) + r"([0-9][0-9A-Za-z.+-]*)")

# Reader half of user_cfg.py's ``_LANGUAGE_KV_RE``. Duplicated (rather than
# imported) on purpose: user_cfg.py imports AppSettings at module scope, and
# pulling Qt in here would cost this module its no-Qt testability for the sake
# of one 40-character pattern. The writer there stays the canonical one.
_USER_CFG_LANGUAGE_RE = re.compile(
    r'^\s*g_language\s*=\s*"?([^";\r\n]+?)"?\s*(?:[;#].*)?$',
    re.IGNORECASE | re.MULTILINE,
)

# Where an install root came from. An install can carry several at once (the
# configured root is normally also a common path, for instance).
SOURCE_CONFIGURED = "configured"
SOURCE_LAUNCHER = "launcher"
SOURCE_REGISTRY = "registry"
SOURCE_COMMON = "common"
SOURCE_DEEP = "deep"

# Scan outcomes. The dialog turns exactly one of these into its headline; the
# whole point of the feature is the verdict, not the list underneath it.
VERDICT_NONE = "none"                          # nothing found anywhere
VERDICT_SINGLE = "single"                      # one install, and it's the configured one
VERDICT_SINGLE_ELSEWHERE = "single_elsewhere"  # one install, configured points elsewhere
VERDICT_SINGLE_LEFTOVER = "single_leftover"    # one install, no game data in any channel
VERDICT_MATCH = "match"                        # several, configured == launcher's
VERDICT_MATCH_LEFTOVER = "match_leftover"      # several, configured == launcher's, no game data
VERDICT_MISMATCH = "mismatch"                  # several, configured != launcher's <- the bug
VERDICT_UNCONFIGURED = "unconfigured"          # several, nothing configured yet, launcher known
VERDICT_UNKNOWN_ACTIVE = "unknown_active"      # several, no launcher evidence to judge by

# Depth-bounded deep scan. 5 covers realistic nesting (``D:\Games\RSI\Star
# Citizen\StarCitizen``) without walking a whole source tree, and pruning at a
# matched root means a found install is never descended into.
DEEP_SCAN_MAX_DEPTH = 5

# Directories a Star Citizen install is never inside, pruned by lowercase name
# at every level. Skipping AppData and node_modules alone removes the large
# majority of the directory count on a typical Windows drive.
_DEEP_SCAN_SKIP_DIRS = frozenset({
    "$recycle.bin", "$windows.~bt", "$windows.~ws", "appdata", "boot",
    "config.msi", "msocache", "node_modules", "perflogs", "recovery",
    "system volume information", "windows", "winsxs", ".git", ".svn",
    "__pycache__", "temp", "tmp",
})

_DRIVE_FIXED = 3  # DRIVE_FIXED from winbase.h

# A deep-scan progress reporter: (directories_visited, current_path_or_drive).
ProgressCallback = Callable[[int, str], None]
# Returns True to abort a deep scan at the next directory boundary.
CancelCallback = Callable[[], bool]


def channel_dirs(root: Path) -> list[Path]:
    """Return the channel folders directly under *root*, in :data:`SC_CHANNELS`
    order (not filesystem order, so scan output is stable run to run)."""
    try:
        if not root.is_dir():
            return []
    except OSError:
        return []
    found = []
    for channel in SC_CHANNELS:
        candidate = root / channel
        try:
            if candidate.is_dir():
                found.append(candidate)
        except OSError:
            continue
    return found


def looks_like_sc_root(root: Path) -> bool:
    """Return True if *root* holds at least one channel folder.

    Deliberately loose, and kept that way because ``settings._is_valid_sc_root``
    delegates here: tightening it would change which path an existing profile
    resolves to. Use :func:`is_sc_install_root` for discovery, where a folder
    that merely has the right subfolder names is not good enough.
    """
    return bool(channel_dirs(root))


def channel_markers(channel_dir: Path) -> tuple[str, ...]:
    """Return the :data:`SC_CHANNEL_MARKERS` present in *channel_dir*."""
    found = []
    for marker in SC_CHANNEL_MARKERS:
        try:
            if (channel_dir / marker).exists():
                found.append(marker)
        except OSError:
            continue
    return tuple(found)


def is_sc_install_root(root: Path) -> bool:
    """Return True if *root* is really a Star Citizen install.

    The strict test: at least one channel folder carrying real Star Citizen
    evidence (see :data:`SC_CHANNEL_MARKERS`). This is what discovery filters
    on, so a folder that merely *looks* the part -- Smart Citizen's own
    per-channel data root being the one that actually bit -- never gets
    reported as somebody's game install.
    """
    return any(channel_markers(d) for d in channel_dirs(root))


def _normcase(path: Path | str) -> str:
    """Case- and separator-normalized string form, for comparing two paths."""
    return os.path.normcase(os.path.normpath(str(path)))


def same_path(a: Path | str | None, b: Path | str | None) -> bool:
    """Return True if *a* and *b* name the same location (textually)."""
    if a is None or b is None:
        return False
    if str(a) == "" or str(b) == "":
        return False
    return _normcase(a) == _normcase(b)


def version_sort_key(version: str) -> tuple:
    """Sort key for a ``4.9.188.23497``-style build version.

    Non-numeric or missing components sort lowest rather than raising, so an
    unreadable manifest just loses the tie-break instead of aborting a scan.
    """
    if not version:
        return ()
    parts = []
    for chunk in str(version).split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(-1)
    return tuple(parts)


def _mtime(path: Path) -> Optional[datetime]:
    """Naive local-time mtime of *path*, or None if it can't be stat'd.

    Naive on purpose: the RSI Launcher log stamps naive local times too, and
    the two get compared against each other when ranking installs.
    """
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except (OSError, ValueError, OverflowError):
        return None


# -- Per-install evidence ----------------------------------------------------

@dataclass(frozen=True)
class ScChannel:
    """One channel folder (``LIVE``, ``PTU``, ...) inside an install root."""

    name: str
    path: Path
    has_game_data: bool                 # Data.p4k present -- a real, playable channel
    game_data_size: int                 # bytes, 0 when absent
    game_data_mtime: Optional[datetime]
    markers: tuple[str, ...]            # SC_CHANNEL_MARKERS found here
    version: str                        # build_manifest.id -> Data.Version
    branch: str                         # e.g. "sc-alpha-4.9.0"
    build_date: str                     # e.g. "Wed Jul 29 2026"
    applied_languages: tuple[str, ...]  # Localization subdirs holding a global.ini
    applied_mtime: Optional[datetime]   # newest applied global.ini
    applied_stamp_version: str          # Smart Citizen version in the watermark, "" if none
    user_cfg_language: str              # g_language from user.cfg, "" if unset/absent

    @property
    def is_star_citizen(self) -> bool:
        """True if this folder carries real Star Citizen evidence, rather than
        just being named after a channel."""
        return bool(self.markers)

    @property
    def is_applied(self) -> bool:
        """True if any applied ``global.ini`` exists in this channel."""
        return bool(self.applied_languages)

    @property
    def is_smart_citizen_applied(self) -> bool:
        """True if an applied global.ini here carries our own watermark."""
        return bool(self.applied_stamp_version)


@dataclass
class ScInstall:
    """One Star Citizen install root, with everything known about it."""

    root: Path
    channels: list[ScChannel] = field(default_factory=list)
    sources: set[str] = field(default_factory=set)
    launcher_seen: Optional[datetime] = None  # newest RSI Launcher log mention

    @property
    def has_game_data(self) -> bool:
        """True if any channel here holds a real ``Data.p4k``."""
        return any(c.has_game_data for c in self.channels)

    @property
    def is_leftover(self) -> bool:
        """True for an install-shaped folder with no game data in any channel.

        This is the quiet failure mode: it passes the looser
        ``settings._is_valid_sc_root`` check, so it can be auto-picked and then
        silently swallow every apply.
        """
        return bool(self.channels) and not self.has_game_data

    @property
    def channel_names(self) -> list[str]:
        return [c.name for c in self.channels]

    @property
    def newest_game_data_mtime(self) -> Optional[datetime]:
        stamps = [c.game_data_mtime for c in self.channels if c.game_data_mtime]
        return max(stamps) if stamps else None

    @property
    def newest_version(self) -> str:
        versions = [c.version for c in self.channels if c.version]
        return max(versions, key=version_sort_key) if versions else ""

    @property
    def total_game_data_size(self) -> int:
        """Summed ``Data.p4k`` bytes across channels -- what deleting frees."""
        return sum(c.game_data_size for c in self.channels)

    @property
    def is_smart_citizen_applied(self) -> bool:
        return any(c.is_smart_citizen_applied for c in self.channels)

    @property
    def applied_stamp_versions(self) -> list[str]:
        """Distinct Smart Citizen versions watermarked into this install."""
        seen = {c.applied_stamp_version for c in self.channels if c.applied_stamp_version}
        return sorted(seen, key=version_sort_key)


@dataclass
class ScanReport:
    """Everything one scan learned, ranked and judged.

    ``installs`` is ordered most-likely-live first (see :func:`_liveness_key`),
    so the dialog renders it top-down without re-sorting.
    """

    installs: list[ScInstall] = field(default_factory=list)
    configured_root: Optional[Path] = None
    launcher_root: Optional[Path] = None
    launcher_log_read: bool = False
    deep_scanned: bool = False
    drives_scanned: tuple[str, ...] = ()
    cancelled: bool = False

    @property
    def count(self) -> int:
        return len(self.installs)

    @property
    def playable(self) -> list[ScInstall]:
        """Installs with real game data -- the ones that can actually run."""
        return [i for i in self.installs if i.has_game_data]

    @property
    def leftovers(self) -> list[ScInstall]:
        """Install-shaped folders with no game data in any channel."""
        return [i for i in self.installs if i.is_leftover]

    @cached_property
    def active(self) -> Optional[ScInstall]:
        """The install the player most likely actually launches.

        The launcher's own log wins when we have it; otherwise this is the
        top-ranked install by build recency, which the verdict reports as a
        guess (:data:`VERDICT_UNKNOWN_ACTIVE`) rather than a fact.

        Cached (#385 review): the dialog's per-card render loop calls this
        indirectly once per install via ``_badges()``, and a fresh
        ``ScanReport`` is never mutated in place after a scan builds it, so
        recomputing the O(n) search on every card was pure waste.
        """
        for install in self.installs:
            if same_path(install.root, self.launcher_root):
                return install
        return self.installs[0] if self.installs else None

    @cached_property
    def configured(self) -> Optional[ScInstall]:
        """The install Smart Citizen is currently pointed at, if it was found.

        Cached for the same reason as :attr:`active` (#385 review): ``verdict``
        reads this on every per-card ``_badges()`` call via the dialog's
        render loop.
        """
        for install in self.installs:
            if same_path(install.root, self.configured_root):
                return install
        return None

    @property
    def unused(self) -> list[ScInstall]:
        """Every install that is neither the launcher's nor the configured one.

        These are the ones the user asked to be told about: real installs
        sitting on disk that nothing is currently driving. Usually an old
        drive or a pre-move copy, and usually what is eating the disk space.
        """
        active = self.active
        return [
            i for i in self.installs
            if not (active and same_path(i.root, active.root))
            and not same_path(i.root, self.configured_root)
        ]

    @property
    def verdict(self) -> str:
        """One of the ``VERDICT_*`` constants. The dialog's headline.

        Several states get checked ahead of the count/agreement logic below,
        because none of them is a "some install disagrees with another"
        question:

        * A single leftover (channel folders, no ``Data.p4k``) is never a
          good outcome regardless of whether it happens to be configured --
          reported as-is here rather than falling into VERDICT_SINGLE's
          "nothing to fix" (#385 review).
        * "Nothing configured yet" is not the same claim as "configured
          wrong". ``same_path`` returns False whenever either side is None,
          so without this check an unset ``configured_root`` with 2+
          installs and a known launcher fell through to VERDICT_MISMATCH --
          a false "applying to the wrong install" alarm for a user who has
          simply never set a path (#385 review).
        * The same leftover blind spot as the single-install case, but for
          2+ installs: the configured root and the launcher's pick can
          agree with each other while still being a leftover neither
          side's agreement makes playable. Checked only in the ``MATCH``
          branch (not ``UNCONFIGURED``/``MISMATCH``) because those already
          point the user at fixing the mismatch itself, which is the more
          urgent problem regardless of what shape the target install turns
          out to be (#385 review).
        """
        if not self.installs:
            return VERDICT_NONE
        configured_found = self.configured is not None
        if len(self.installs) == 1:
            if self.installs[0].is_leftover:
                return VERDICT_SINGLE_LEFTOVER
            return VERDICT_SINGLE if configured_found else VERDICT_SINGLE_ELSEWHERE
        if self.launcher_root is None:
            return VERDICT_UNKNOWN_ACTIVE
        if not configured_found:
            return VERDICT_UNCONFIGURED
        if same_path(self.configured_root, self.launcher_root):
            # Same leftover blind spot as the single-install branch above,
            # just reachable with 2+ installs instead of exactly one: the
            # configured root and the launcher's pick agree, but the install
            # they agree on has no game data (#385 review -- this used to
            # fall straight through to VERDICT_MATCH's "nothing to fix").
            if self.configured.is_leftover:
                return VERDICT_MATCH_LEFTOVER
            return VERDICT_MATCH
        return VERDICT_MISMATCH


# -- Reading one install off disk --------------------------------------------

def _read_build_manifest(channel_dir: Path) -> tuple[str, str, str]:
    """Return ``(version, branch, build_date)`` from ``build_manifest.id``.

    Same JSON shape ``AppSettings.get_game_version`` reads. Returns empty
    strings for anything missing or unparseable -- a channel mid-download has
    no manifest yet, and that is not an error worth failing a scan over.
    """
    manifest = channel_dir / BUILD_MANIFEST_FILE
    try:
        data = json.loads(manifest.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return "", "", ""
    block = data.get("Data") if isinstance(data, dict) else None
    if not isinstance(block, dict):
        return "", "", ""
    return (
        str(block.get("Version", "") or ""),
        str(block.get("Branch", "") or ""),
        str(block.get("BuildDateStamp", "") or ""),
    )


def _read_user_cfg_language(channel_dir: Path) -> str:
    """Return ``g_language`` from the channel's ``user.cfg``, or ""."""
    try:
        text = (channel_dir / USER_CFG_FILE).read_text(
            encoding="utf-8", errors="replace"
        )
    except OSError:
        return ""
    matches = _USER_CFG_LANGUAGE_RE.findall(text)
    # Last assignment wins, matching how the game's own lenient parser reads it.
    return matches[-1].strip() if matches else ""


# Streamed in 1 MB chunks with a marker-sized overlap so a watermark straddling
# a chunk boundary is still matched. Sized to stop early on a hit: the stamp
# rides on the ``Frontend_PU_Version`` key, which lands wherever the merge
# happens to sort it (measured at ~1.4 MB into an 11 MB file, so a head-only
# read misses it), and a file with no stamp at all is read through once.
_STAMP_CHUNK_BYTES = 1024 * 1024
_STAMP_MAX_BYTES = 64 * 1024 * 1024


def _read_apply_stamp(global_ini: Path) -> str:
    """Return the Smart Citizen version watermarked into *global_ini*, or ""."""
    overlap = len(APPLY_STAMP_MARKER) + 32
    carry = ""
    consumed = 0
    try:
        with open(global_ini, "rb") as handle:
            while consumed < _STAMP_MAX_BYTES:
                chunk = handle.read(_STAMP_CHUNK_BYTES)
                if not chunk:
                    break
                consumed += len(chunk)
                text = carry + chunk.decode("utf-8", errors="replace")
                match = _APPLY_STAMP_RE.search(text)
                if match:
                    return match.group(1)
                carry = text[-overlap:]
    except OSError:
        return ""
    return ""


def _scan_applied_localization(
    channel_dir: Path,
) -> tuple[tuple[str, ...], Optional[datetime], str]:
    r"""Inspect ``data\Localization\*\global.ini`` inside *channel_dir*.

    Returns ``(language_dirs_with_a_global_ini, newest_mtime, stamp_version)``.
    """
    loc_dir = channel_dir / "data" / LOCALIZATION_DIRNAME
    languages: list[str] = []
    newest: Optional[datetime] = None
    stamp = ""
    try:
        entries = sorted(loc_dir.iterdir())
    except OSError:
        return (), None, ""
    for lang_dir in entries:
        global_ini = lang_dir / "global.ini"
        try:
            if not global_ini.is_file():
                continue
        except OSError:
            continue
        languages.append(lang_dir.name)
        stamped = _mtime(global_ini)
        if stamped and (newest is None or stamped > newest):
            newest = stamped
        if not stamp:
            stamp = _read_apply_stamp(global_ini)
    return tuple(languages), newest, stamp


def read_channel(channel_dir: Path) -> ScChannel:
    """Gather everything worth knowing about one channel folder."""
    game_data = channel_dir / GAME_DATA_FILE
    try:
        stat = game_data.stat()
        has_data, size, data_mtime = True, stat.st_size, _mtime(game_data)
    except OSError:
        has_data, size, data_mtime = False, 0, None

    version, branch, build_date = _read_build_manifest(channel_dir)
    languages, applied_mtime, stamp = _scan_applied_localization(channel_dir)
    return ScChannel(
        name=channel_dir.name.upper(),
        path=channel_dir,
        has_game_data=has_data,
        game_data_size=size,
        game_data_mtime=data_mtime,
        markers=channel_markers(channel_dir),
        version=version,
        branch=branch,
        build_date=build_date,
        applied_languages=languages,
        applied_mtime=applied_mtime,
        applied_stamp_version=stamp,
        user_cfg_language=_read_user_cfg_language(channel_dir),
    )


def read_install(root: Path) -> Optional[ScInstall]:
    """Build an :class:`ScInstall` for *root*, or None if it isn't one.

    The single gate every discovery path funnels through, so the marker check
    lives here: a folder whose only qualification is channel-shaped subfolder
    names (Smart Citizen's own data root, any portable build's ``data\\``)
    never reaches the report. Channels with no markers are still listed on a
    genuine install -- an empty ``PTU\\`` beside a real ``LIVE\\`` is worth
    showing -- they just cannot vouch for the install on their own.
    """
    dirs = channel_dirs(root)
    if not dirs:
        return None
    channels = [read_channel(d) for d in dirs]
    if not any(c.is_star_citizen for c in channels):
        return None
    return ScInstall(root=root, channels=channels)


# -- Tier 1: the RSI Launcher's own log --------------------------------------

# Each log line is a standalone JSON-ish object stamped with a naive local
# time: ``{ "t":"2026-07-11 14:47:35.478", "[main][info] ": "..." }``.
_LOG_TIMESTAMP_RE = re.compile(
    r'"t"\s*:\s*"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?)"'
)

# Any drive-rooted Windows path in a log line, up to a character no folder name
# can hold. Parentheses, apostrophes and commas are deliberately NOT excluded:
# ``C:\Program Files (x86)\...``, ``D:\Dad's Games\...`` and ``E:\Games, Apps\...``
# are real install locations. The launcher's own noise comes along too
# (`` (type: install``, a closing quote, every later path in the same string)
# and is cut back by :data:`_LOG_PATH_LIST_SPLIT_RE` and
# :func:`_logged_path_candidates`.
_LOG_PATH_RE = re.compile(r"[A-Za-z]:\\[^\"*?<>|\r\n]*")

# One logged string can name several paths: a list
# (``[validateNonExistantDirectories] C:\a,C:\a\StarCitizen,...``) or a
# sentence such as
# ``copy 'F:\Old\StarCitizen\LIVE' to 'G:\New\StarCitizen\LIVE'``
# (Node's file errors read ``rename 'A' -> 'B'``). A folder name cannot hold a
# colon, so a drive path in the middle of a match always starts a new entry,
# whatever sits between the two paths, and a match is split before each one.
# A list separator, a comma or a semicolon with any spaces after it, goes with
# the split, so list entries come out clean: one left on would cost every
# entry a failed probe before the cut at it. The last entry can still end in
# one (``A;B;``), and the cuts take that off. A comma or a semicolon in a
# folder name (``Games, Apps``, ``Games; Apps``) has no drive path after it, so
# it stays. Any other text between two paths (``' to '``) stays on the end of
# the earlier entry, where :func:`_logged_path_candidates` trims it. Inside a
# match the lookbehind keeps the drive letter standing alone, so the ``c:\`` in
# ``...\abc:\x`` does not start an entry. :data:`_LOG_PATH_RE` has no such
# check, so text that starts with ``abc:\x`` is still matched from its ``c:\``.
# The log is JSON, so a line break between two paths is the two characters
# ``\n`` (``\r`` and ``\t`` likewise), and the letter of that escape would hide
# the drive letter behind it from the lookbehind: a drive path right after one
# of them starts an entry as well. That cannot split a real path, since a
# folder name cannot hold the colon that makes it a drive path. The split
# leaves empty pieces, one at the front (every match starts at a drive path)
# and one after each separator it consumed, which the :data:`_LOG_PATH_HINT`
# check in :func:`parse_launcher_log` drops.
_LOG_PATH_LIST_SPLIT_RE = re.compile(
    r"(?:[,;]\s*)?(?:(?<![A-Za-z])|(?<=\\[nrt]))(?=[A-Za-z]:\\)"
)

# The launcher always creates its ``StarCitizen\<channel>`` tree inside the
# user's chosen library folder, so this substring is a safe, cheap filter that
# keeps the launcher's own program directory and its cache paths out.
_LOG_PATH_HINT = "starcitizen"

# A folder whose name starts with the hint: group 1 is the hint itself, group 2
# the rest of that folder's name (or of the text stuck to it).
_LOG_HINT_FOLDER_RE = re.compile(
    r"(?<=[\\/])(" + re.escape(_LOG_PATH_HINT) + r")([^\\/]*)", re.IGNORECASE
)

# Bound on how many trimmed variants of one logged path get probed. Real paths
# resolve within a handful; the cap just stops a pathological log line from
# turning into thousands of stat calls. The path as logged, the same path with
# each line break left on its end taken off, and the cuts (at a folder named
# for the hint, then at a quote, comma or semicolon) share one budget of this
# size. The word and folder trimming that follows has another, so a path with
# a great many quotes or commas still reaches the folder walk. The cut passes
# take their matches last first and spend one budget at most, so they keep
# only this many.
_MAX_PATH_CANDIDATES = 24

# Windows takes no path longer than this many characters, so a candidate cut
# from a logged path cannot be an install once it is longer.
_LONGEST_WINDOWS_PATH = 32_767

# How much of the log gets read and parsed, counted back from its end. First-run
# detection reads it on the GUI thread, and the per-folder memo bounds the work
# per folder but not per distinct path, so a runaway log (hundreds of thousands
# of distinct per-file paths under a folder that no longer exists) could stall
# the window for tens of seconds. The launcher's own log is about 40 KB, so
# this is a hundred times what a real one needs.
_LOG_READ_BUDGET_BYTES = 4 * 1024 * 1024

# How many folders one read of the log may probe in all. The per-folder memo
# bounds the work per folder but not per distinct path, and first-run
# detection reads the log on the GUI thread. Measured on a 4 MiB log of
# distinct per-file paths under a library folder that no longer exists (about
# 22 microseconds a probe on the PC it was measured on): plain paths take
# 16,000 probes, ENOENT errors 28,000 and rename errors 42,000, so this cap
# leaves them alone. Contrived lines are what it stops. A quoted path followed
# by thirty ``, x`` and thirty `` w`` took 474,000 probes and 11.6 s, and stops
# here at 2.2 s. Once it is reached, a path the log has not named before is
# not checked any more (a debug line says so once), while one already checked
# still updates its newest mention.
_MAX_LOG_PROBES = 100_000


def default_launcher_log_path() -> Optional[Path]:
    r"""Return ``%APPDATA%\rsilauncher\logs\log.log``, or None if APPDATA is unset."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / "rsilauncher" / "logs" / "log.log"


def _trailing_break_ends(raw: str) -> Iterator[int]:
    r"""Yield where *raw* ends as each JSON line break at its end comes off.

    The log is JSON, so a message that ends in a line break ends in the two
    characters ``\n`` (``\r`` and ``\t`` likewise), and a path at the end of
    such a message carries them. They come off one at a time, last first, each
    with the spaces and separators next to it, and every new end is yielded:
    ``...\Hub\t\n`` gives ``...\Hub\t``, which may be a folder really called
    ``t``, and then ``...\Hub``. It works back from the end one character at a
    time, so it stays linear on any line.
    """
    end = len(raw)
    while end >= 2 and raw[end - 2] == "\\" and raw[end - 1] in "nrt":
        end -= 2
        while end and (raw[end - 1].isspace() or raw[end - 1] in "\\/"):
            end -= 1
        yield end


def _hint_folder_cuts(raw: str) -> Iterator[str]:
    r"""Yield the prefixes of *raw* that end at a folder named for the hint.

    Last folder first, so ``D:\StarCitizen\StarCitizen\LIVE`` offers the inner
    folder before the outer one. A folder qualifies when its name starts with
    the hint, in any case, so ``MyStarCitizen`` does not. The whole name is
    offered and never a shorter one: ``StarCitizen_old`` and
    ``StarCitizen Old`` give those folders, not the ``StarCitizen`` beside
    them, which may be a different install. The one exception mirrors the cut
    at a quote, comma or semicolon in :func:`_logged_path_candidates`: where
    one of those follows the hint (``...\StarCitizen, Error: x``,
    ``...\StarCitizen' is missing``, ``...\StarCitizen;``) the bare name comes
    first, as that cut would have reached it before any walk up.

    These come before the walk up, so an install nested inside a folder named
    for the hint gives way to that folder: with installs at ``...\StarCitizen``
    and ``...\StarCitizen\Backup``, the path ``...\StarCitizen\Backup\LIVE``
    resolves to ``...\StarCitizen``. That is a decision. The launcher always
    names its own folder ``StarCitizen``, and a second install inside it is not
    a layout the launcher makes.

    Only the last :data:`_MAX_PATH_CANDIDATES` folders are kept, so the matches
    take no more memory on a line of hundreds of thousands of folders than on
    a short one. The caller spends at most one budget of that size here, every
    folder yields at least one prefix, and only one prefix can be skipped (the
    last folder's whole name, when that is the whole path), so no earlier
    folder is ever reached. Each prefix yielded is still a full copy of the
    text up to its folder, and :func:`parse_launcher_log` keeps every one it
    probes as a key of its memo. That is why :func:`_logged_path_candidates`
    first cuts the text to the longest path Windows takes.
    """
    matches = deque(
        _LOG_HINT_FOLDER_RE.finditer(raw), maxlen=_MAX_PATH_CANDIDATES
    )
    for match in reversed(matches):
        if match.group(2)[:1] in ("'", ",", ";"):
            yield raw[: match.end(1)]
        yield raw[: match.end()]


def _logged_path_candidates(raw: str) -> Iterator[str]:
    r"""Yield plausible truncations of *raw*, the whole path first.

    A logged path arrives with the launcher's own prose stuck to the end
    (``...\StarCitizen (type: install``, ``...\LIVE - required: 110085069``,
    ``...\StarCitizen' is missing``, the ``' to '`` between two quoted paths,
    which :data:`_LOG_PATH_LIST_SPLIT_RE` leaves on the earlier one, or a whole
    stack trace). A message that ends in a line break also leaves its JSON
    escape (``\n``) on the end, so after the path as logged come the same path
    with one escape taken off, then two, and so on
    (:func:`_trailing_break_ends`), and the rest works from the last of them.
    Four passes then clean it up.
    First the prefixes that end at a folder named for the hint
    (:func:`_hint_folder_cuts`): the launcher always creates ``StarCitizen``,
    so the root is nearly always one of them, however much text follows. Then
    a cut at each apostrophe, comma or semicolon, last one first (one that ends
    the path, while a folder name such as ``Dad's Games`` is kept whole by the
    full path being tried before any cut). Then whitespace-separated words
    trimmed off the final segment, from as many as the budget has room for
    down to the first word alone. Last a walk up whole segments. The path, the
    paths without their line breaks and the first two passes share one budget
    of :data:`_MAX_PATH_CANDIDATES` candidates, and the last two share another.
    Between them they recover the real root from every line shape the
    launcher currently emits, without this module having to know any of
    those shapes.
    """
    # Every candidate is a prefix of the path (the walk up also tidies its
    # separators, which only shortens it), and no path longer than Windows
    # takes can be an install, so the text past that length can go. It also
    # keeps every copy below, and every key of a caller's memo, that short.
    raw = raw[:_LONGEST_WINDOWS_PATH].strip().rstrip("\\/")
    if not raw:
        return
    yield raw

    emitted = 1
    # The path as logged went first, since a ``\n``, ``\r`` or ``\t`` on its
    # end may be a folder really called n, r or t. Each escape taken off gives
    # one more path to try, and the passes below work from the shortest.
    end = len(raw)
    for end in _trailing_break_ends(raw):
        if end <= 3:  # only a drive is left, never an install
            return
        if emitted < _MAX_PATH_CANDIDATES:
            yield raw[:end]
            emitted += 1
    raw = raw[:end]
    for cut in _hint_folder_cuts(raw):
        if emitted >= _MAX_PATH_CANDIDATES:
            break
        if cut != raw:
            yield cut
            emitted += 1
    quotes = deque(re.finditer(r"[',;]", raw), maxlen=_MAX_PATH_CANDIDATES)
    for match in reversed(quotes):
        if emitted >= _MAX_PATH_CANDIDATES:
            break
        cut = raw[: match.start()].rstrip("\\/ ")
        if cut:
            yield cut
            emitted += 1

    emitted = 1  # the cuts above must not eat the budget of the passes below
    head, sep, tail = raw.rpartition("\\")
    words = tail.split(" ")
    # With more words than the budget has room for, the trim starts at as many
    # as fit, so it still gets down to the first word alone (the name the prose
    # follows), and a longer name such as ``StarCitizen Old`` comes before it.
    longest = min(len(words) - 1, _MAX_PATH_CANDIDATES - emitted)
    for count in range(longest, 0, -1):
        yield head + sep + " ".join(words[:count])
        emitted += 1

    # A root not named for the hint has only this walk, so with a quote and a
    # long trace after it (five ``node:internal`` frames or more) the budget
    # runs out before the walk gets there. The launcher always names its root
    # ``StarCitizen``, so that takes a folder it did not make, and is left so.
    current = Path(raw)
    for parent in current.parents:
        if emitted >= _MAX_PATH_CANDIDATES:
            return
        # Stop at the drive root -- ``C:\`` is never a Star Citizen install.
        if parent == parent.parent:
            return
        yield str(parent)
        emitted += 1


def _drive_exists(drive: str) -> bool:
    r"""Return True if the drive *drive* (``"C:"``) is there.

    ``os.path.isdir`` never raises, so a drive that cannot be read counts as
    missing.
    """
    return os.path.isdir(drive + "\\")


def resolve_logged_root(
    raw: str, checked: Optional[dict[str, bool]] = None
) -> Optional[Path]:
    """Turn one raw path out of the launcher log into an install root on disk.

    Returns None when nothing along the path resolves, which covers both junk
    matches and installs the user has since deleted. *checked* memoizes the
    install test per candidate folder, so a caller resolving many paths under
    one install tests each of its folders once.
    """
    for candidate in _logged_path_candidates(raw):
        if checked is not None and candidate in checked:
            is_root = checked[candidate]
        else:
            is_root = is_sc_install_root(Path(candidate))
            if checked is not None:
                checked[candidate] = is_root
        if is_root:
            return Path(candidate)
    return None


def parse_launcher_log(text: str) -> dict[str, tuple[Path, datetime]]:
    """Map every install root the launcher log mentions to its newest mention.

    Keys are :func:`_normcase`-normalized strings so callers can match them
    against other candidates without worrying about case or separators; the
    value keeps the path as the launcher wrote it, not lowercased, because
    these end up in front of the user and ``c:\\program files\\...`` reads
    like a bug. The launcher writes the folder picked in its own dialog, so
    that normally matches the casing on disk, but nothing here checks. Lines
    with no timestamp inherit the last one seen, so a wrapped or continuation
    line still dates correctly.
    """
    seen: dict[str, tuple[Path, datetime]] = {}
    resolved: dict[str, Optional[Path]] = {}  # raw -> root, memo across lines
    # Folder -> install test, so per-file paths under one install (each a
    # distinct raw string) share the walk up through its folders.
    checked: dict[str, bool] = {}
    # Drive -> whether it is there. The log can name a mapped drive that is no
    # longer connected, where every probe waits for a network timeout, and
    # first-run detection runs this on the GUI thread. So each drive is
    # checked once, and nothing on a missing one is probed.
    drives: dict[str, bool] = {}
    out_of_probes = False
    last_stamp: Optional[datetime] = None

    for line in text.splitlines():
        stamp_match = _LOG_TIMESTAMP_RE.search(line)
        if stamp_match:
            try:
                last_stamp = datetime.fromisoformat(stamp_match.group(1))
            except ValueError:
                pass
        if _LOG_PATH_HINT not in line.lower():
            continue
        # The log is JSON-escaped, so on-disk ``C:\a\b`` appears as ``C:\\a\\b``.
        unescaped = line.replace("\\\\", "\\")
        # A match can hold several paths, so it is split into one entry each.
        # The empty pieces the split leaves fail the hint check below.
        raws = [
            entry
            for match in _LOG_PATH_RE.findall(unescaped)
            for entry in _LOG_PATH_LIST_SPLIT_RE.split(match)
        ]
        for raw in raws:
            if _LOG_PATH_HINT not in raw.lower():
                continue
            if raw not in resolved and len(checked) >= _MAX_LOG_PROBES:
                if not out_of_probes:
                    out_of_probes = True
                    logger.debug(
                        "RSI Launcher log: %d folders probed, later new paths "
                        "in it are not checked",
                        len(checked),
                    )
                continue
            if raw not in resolved:
                # Every logged path starts with its drive (``C:``).
                drive = raw[:2].upper()
                if drive not in drives:
                    drives[drive] = _drive_exists(drive)
                resolved[raw] = (
                    resolve_logged_root(raw, checked) if drives[drive] else None
                )
            root = resolved[raw]
            if root is None:
                continue
            key = _normcase(root)
            stamp = last_stamp if last_stamp is not None else datetime.min
            if key not in seen or stamp > seen[key][1]:
                seen[key] = (root, stamp)
    return seen


def _read_log_tail(path: Path) -> str:
    """Read *path*, or only its last :data:`_LOG_READ_BUDGET_BYTES` when it is bigger.

    The launcher only ever appends, so the newest mentions are at the end and
    those are what the ranking wants. The cut usually lands inside a line, so
    the first line of a trimmed read is dropped rather than parsed half.
    """
    with path.open("rb") as handle:
        size = handle.seek(0, os.SEEK_END)
        trimmed = size > _LOG_READ_BUDGET_BYTES
        handle.seek(size - _LOG_READ_BUDGET_BYTES if trimmed else 0)
        text = handle.read().decode("utf-8", errors="replace")
    if trimmed:
        text = text.partition("\n")[2]
    return text


def read_launcher_installs(
    log_path: Optional[Path] = None,
) -> tuple[dict[str, tuple[Path, datetime]], bool]:
    """Read and parse the RSI Launcher log.

    Returns ``(roots_to_newest_mention, log_was_read)``. The flag matters:
    "no launcher log" and "launcher log mentions nothing that still exists"
    lead to different verdicts, and the dialog says so rather than guessing.
    """
    path = log_path or default_launcher_log_path()
    if path is None:
        return {}, False
    try:
        text = _read_log_tail(path)
    except OSError as exc:
        logger.debug("RSI Launcher log unreadable at %s: %s", path, exc)
        return {}, False
    try:
        return parse_launcher_log(text), True
    except Exception as exc:  # pragma: no cover - defensive, log format is CIG's
        logger.warning("Could not parse RSI Launcher log at %s: %s", path, exc)
        return {}, False


# -- Tier 2: the common RSI install paths ------------------------------------

# Relative install paths under a drive's root, in the order real installs are
# most likely to use them. RSI Launcher's own default is the first two; the
# rest cover users who point the launcher at a secondary drive and either keep
# RSI's own folder shape or nest it under a personal "Games" folder -- both
# are common in the wild (a real tester install turned up at
# ``E:\Games\Roberts Space Industries\StarCitizen``, which none of the
# previous hardcoded C:\ candidates could ever have matched).
COMMON_SC_SUBPATHS: tuple[str, ...] = (
    r"Program Files\Roberts Space Industries\StarCitizen",
    r"Program Files (x86)\Roberts Space Industries\StarCitizen",
    r"Roberts Space Industries\StarCitizen",
    r"Games\Roberts Space Industries\StarCitizen",
)


def iter_common_sc_install_locations(
    drives: Optional[Iterable[str]] = None,
) -> Iterator[Path]:
    """Yield every existing install root sitting at a common RSI path.

    Shared by :func:`scan_installs` and first-run detection
    (``settings._scan_common_sc_install_locations``), which merges these hits
    with the roots the launcher log names and ranks them all. Hits only need a
    channel folder (:func:`looks_like_sc_root`), kept that loose so an existing
    profile keeps resolving to the same path. Drive presence is tested with
    ``exists()`` rather than :func:`fixed_drives` to keep the pre-existing
    behaviour exactly (an install on a removable or mapped drive still
    resolves).
    """
    letters = drives if drives is not None else (f"{c}:\\" for c in string.ascii_uppercase)
    for letter in letters:
        drive_root = Path(letter)
        try:
            if not drive_root.exists():
                continue
        except OSError:
            continue
        for subpath in COMMON_SC_SUBPATHS:
            candidate = drive_root / subpath
            if looks_like_sc_root(candidate):
                yield candidate


# The launcher puts ``StarCitizen`` straight inside whatever library folder the
# player picks, so a library at a drive's root or one folder below it (an
# ``E:\Other Games`` folder, with or without RSI's own folder inside) puts the
# install at one of these, relative to each top-level folder.
SHALLOW_SC_SUBPATHS: tuple[str, ...] = (
    r"Roberts Space Industries\StarCitizen",
    "StarCitizen",
)


def has_game_data(root: Path) -> bool:
    """Return True if any channel folder under *root* holds ``Data.p4k``."""
    for channel_dir in channel_dirs(root):
        try:
            if (channel_dir / GAME_DATA_FILE).is_file():
                return True
        except OSError:
            continue
    return False


def iter_shallow_sc_install_locations(
    drives: Optional[Iterable[str]] = None,
) -> Iterator[Path]:
    r"""Yield installs with game data one folder below the top of each fixed drive.

    First-run detection adds these hits to its ranking, so a custom library
    folder is found even when the launcher log does not name it and an old
    install or its shell sits at a common path. It costs one directory
    listing per fixed
    drive plus a few probes per top-level folder, so it can run on the GUI
    thread like the common-path walk. Checks ``<drive>\StarCitizen`` and each
    top-level folder joined with :data:`SHALLOW_SC_SUBPATHS`, skipping
    :data:`_DEEP_SCAN_SKIP_DIRS` and ``$``-prefixed system folders. Only a root
    with ``Data.p4k`` in some channel counts: nobody chose these folders, so a
    leftover shell must not be picked for them.
    """
    targets = list(drives) if drives is not None else fixed_drives()
    for drive in targets:
        drive_root = Path(drive)
        candidates = [drive_root / "StarCitizen"]
        try:
            with os.scandir(drive_root) as entries:
                tops = []
                for entry in entries:
                    name = entry.name.lower()
                    if name in _DEEP_SCAN_SKIP_DIRS or name.startswith("$"):
                        continue
                    try:
                        if not entry.is_dir(follow_symlinks=False):
                            continue
                    except OSError:
                        continue
                    tops.append(Path(entry.path))
        except OSError:
            continue
        for top in sorted(tops, key=lambda p: p.name.lower()):
            candidates.extend(top / subpath for subpath in SHALLOW_SC_SUBPATHS)
        for candidate in candidates:
            if has_game_data(candidate):
                yield candidate


# -- Tier 3: opt-in deep scan ------------------------------------------------

def fixed_drives() -> list[str]:
    r"""Return the local fixed drives as ``C:\``-style roots.

    Fixed only, on purpose: a deep scan across a disconnected network share or
    a sleeping USB disk can block for seconds per directory, and an install
    worth finding is on internal storage. Falls back to a plain existence test
    where the Win32 call isn't available (non-Windows, so tests still run).
    """
    kernel32 = getattr(ctypes, "windll", None)
    get_drive_type = getattr(kernel32.kernel32, "GetDriveTypeW", None) if kernel32 else None

    drives = []
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        if get_drive_type is not None:
            try:
                if get_drive_type(ctypes.c_wchar_p(root)) == _DRIVE_FIXED:
                    drives.append(root)
            except OSError:
                continue
        else:
            try:
                if Path(root).exists():
                    drives.append(root)
            except OSError:
                continue
    return drives


def deep_scan_roots(
    drives: Optional[Iterable[str]] = None,
    max_depth: int = DEEP_SCAN_MAX_DEPTH,
    progress: Optional[ProgressCallback] = None,
    should_cancel: Optional[CancelCallback] = None,
) -> tuple[list[Path], bool]:
    """Walk the fixed drives for install roots at non-standard paths.

    Returns ``(roots, cancelled)``. Depth-bounded and prune-heavy: a matched
    root is never descended into (nothing useful is nested inside an install),
    and :data:`_DEEP_SCAN_SKIP_DIRS` removes the directory trees an install is
    never inside. Progress is throttled to shallow directories plus every
    250th visit, so a fast walk doesn't flood the UI thread with signals.
    """
    targets = list(drives) if drives is not None else fixed_drives()
    found: list[Path] = []
    visited = 0

    for drive in targets:
        stack: list[tuple[Path, int]] = [(Path(drive), 0)]
        while stack:
            if should_cancel is not None and should_cancel():
                return found, True
            current, depth = stack.pop()
            visited += 1
            if progress is not None and (depth <= 2 or visited % 250 == 0):
                progress(visited, str(current))

            # Strict test, not looks_like_sc_root: a folder that merely has
            # channel-shaped subfolders must neither be reported nor stop the
            # walk, or Smart Citizen's own data root would both false-positive
            # and hide anything genuinely nested below it.
            if is_sc_install_root(current):
                found.append(current)
                continue  # an install holds no second install
            if depth >= max_depth:
                continue
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        if entry.name.lower() in _DEEP_SCAN_SKIP_DIRS:
                            continue
                        try:
                            if not entry.is_dir(follow_symlinks=False):
                                continue
                        except OSError:
                            continue
                        stack.append((Path(entry.path), depth + 1))
            except OSError:
                continue

    return found, False


# -- Top level ---------------------------------------------------------------

def _liveness_key(install: ScInstall) -> tuple:
    """Rank an install by how likely it is the one actually being played.

    Real game data first (a leftover shell never outranks a playable install),
    then the launcher's own most-recent mention, then build recency, then
    version. Sorting is stable, so installs that tie fall back to discovery
    order -- which puts the configured install first among equals.
    """
    return (
        install.has_game_data,
        install.launcher_seen or datetime.min,
        install.newest_game_data_mtime or datetime.min,
        version_sort_key(install.newest_version),
    )


def scan_installs(
    *,
    configured_root: Optional[Path | str] = None,
    registry_root: Optional[Path | str] = None,
    extra_roots: Iterable[Path | str] = (),
    launcher_log: Optional[Path] = None,
    deep: bool = False,
    drives: Optional[Iterable[str]] = None,
    max_depth: int = DEEP_SCAN_MAX_DEPTH,
    progress: Optional[ProgressCallback] = None,
    should_cancel: Optional[CancelCallback] = None,
) -> ScanReport:
    """Find every Star Citizen install this machine can see, and judge them.

    All settings-derived inputs (*configured_root*, *registry_root*) are
    passed in rather than read here, keeping this module free of Qt and of
    ``AppSettings``. *deep* opts into the drive walk and is the only expensive
    path; without it the whole scan is a handful of stat calls plus one log
    read, fast enough to run straight off a button click.
    """
    # normcase key -> (path, sources). Insertion order is discovery order,
    # which the stable sort below relies on as its final tie-break.
    candidates: dict[str, tuple[Path, set[str]]] = {}

    def _add(path: Path | str | None, source: str) -> None:
        if path is None or str(path).strip() == "":
            return
        resolved = Path(str(path))
        key = _normcase(resolved)
        if key in candidates:
            candidates[key][1].add(source)
        else:
            candidates[key] = (resolved, {source})

    _add(configured_root, SOURCE_CONFIGURED)
    _add(registry_root, SOURCE_REGISTRY)

    launcher_roots, log_read = read_launcher_installs(launcher_log)
    for logged_root, _stamp in launcher_roots.values():
        _add(logged_root, SOURCE_LAUNCHER)

    for common in iter_common_sc_install_locations(drives):
        _add(common, SOURCE_COMMON)

    for extra in extra_roots:
        _add(extra, SOURCE_DEEP)

    cancelled = False
    if deep:
        deep_found, cancelled = deep_scan_roots(
            drives=drives,
            max_depth=max_depth,
            progress=progress,
            should_cancel=should_cancel,
        )
        for root in deep_found:
            _add(root, SOURCE_DEEP)

    installs: list[ScInstall] = []
    for path, sources in candidates.values():
        install = read_install(path)
        if install is None:
            continue
        install.sources = sources
        logged = launcher_roots.get(_normcase(path))
        install.launcher_seen = logged[1] if logged else None
        installs.append(install)

    installs.sort(key=_liveness_key, reverse=True)

    # The launcher's target is the most recently mentioned root that still
    # exists. Resolving it here (rather than trusting the raw log) means a
    # deleted install never gets named as the thing you play.
    launcher_root: Optional[Path] = None
    dated = [i for i in installs if i.launcher_seen is not None]
    if dated:
        launcher_root = max(dated, key=lambda i: i.launcher_seen).root

    return ScanReport(
        installs=installs,
        configured_root=Path(str(configured_root)) if configured_root else None,
        launcher_root=launcher_root,
        launcher_log_read=log_read,
        deep_scanned=deep,
        drives_scanned=tuple(drives) if drives is not None else (),
        cancelled=cancelled,
    )
