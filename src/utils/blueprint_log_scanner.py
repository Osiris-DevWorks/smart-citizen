"""Parse "Received Blueprint" events out of Star Citizen log files (#222).

Star Citizen records every blueprint the player receives as a client
notification line in its rolling ``Game.log``; rotated copies pile up under
``<channel>\\logbackups\\``. The authoritative event looks like::

    <2026-03-26T17:15:41.684Z> [Notice] <SHUDEvent_OnNotification> Added
    notification "Received Blueprint: Defiance Helmet Tactical: " [23] to
    queue. ... [Team_CoreGameplayFeatures][Missions][Comms]

The same blueprint also spawns ``<UpdateNotificationItem>`` lines and bare
continuation lines quoting the notification; those are UI echoes, so we key
only on the ``<SHUDEvent_OnNotification> Added notification`` line and de-dup
by display name.

This module is Qt-free and settings-free: it takes explicit paths and returns
plain data so it unit-tests with fixture strings. Name *normalization* and the
watermark *persistence* live elsewhere (``owned_items.normalize_item_name`` and
``AppSettings``) — the scanner deliberately returns raw display names so the
one canonical normalizer does the matching (mirrors ``owned_items.py``'s own
Qt-free/settings-free design). The caller (a QThread worker, ``workers.py``'s
``BlueprintLogScanWorker``) is handed a channel folder by ``MainWindow``, which
only ever passes LIVE or HOTFIX under the install root (#446), and reports
progress to the UI (#223 moved the button + result UI onto their own Blueprint
Tracker tab; the scanning internals here are unchanged by that move).

Two filters bound the work:

* **Epoch floor** — blueprints did not exist before March 2026 (#222), so any
  event (and any log file) older than ``BLUEPRINT_EPOCH`` is ignored outright.
* **Watermark** — an optional ``since`` timestamp (the newest event a prior
  scan already consumed); events at or before it are skipped so a re-scan only
  imports genuinely new blueprints, even from a still-growing ``Game.log``.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, List, Optional, Sequence, Set

logger = logging.getLogger(__name__)

# Blueprints did not exist in Star Citizen before March 2026 (#222). A hard
# floor so we never parse ancient logs even absent a watermark. Timezone-aware
# (UTC) to compare cleanly against the ``...Z`` timestamps the log carries.
BLUEPRINT_EPOCH = datetime(2026, 3, 1, tzinfo=timezone.utc)

# The one authoritative "you received a blueprint" line. The name is captured
# non-greedily up to the trailing ``: "`` so embedded quotes survive intact
# (e.g. ``Demeco "Purgatory Camo" LMG``). Anchored on the
# ``<SHUDEvent_OnNotification> Added notification`` prefix (not just the
# ``Received Blueprint: ...`` text) so the ``<UpdateNotificationItem>`` echo
# lines and bare continuation lines that quote the same notification are
# never mistaken for a second, distinct event.
_EVENT_RE = re.compile(
    r"<(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)>"
    r".*?<SHUDEvent_OnNotification> Added notification "
    r'"Received Blueprint: (?P<name>.*?): " \['
)

# The live (current-session) log at the channel install root, plus the rotated
# copies beside it.
LIVE_LOG_NAME = "Game.log"
LOGBACKUPS_DIRNAME = "logbackups"
_LOG_GLOB = "*.log"

# A progress reporter: (files_completed, files_total, current_filename).
ProgressCallback = Callable[[int, int, str], None]


@dataclass(frozen=True)
class BlueprintEvent:
    """One parsed "Received Blueprint" notification."""

    timestamp: datetime
    name: str  # raw display name exactly as it appears in the log


@dataclass
class ScanResult:
    """Outcome of a scan.

    ``names`` are raw, de-duplicated display names that passed both filters —
    the caller normalizes them (via the shared normalizer) before unioning into
    the owned set, so normalization-based de-dup falls out for free.
    ``latest_timestamp`` is the newest event at/after the epoch across every
    scanned file (ignoring the watermark) so the caller can advance the
    watermark monotonically: ``new = max(old, result.latest_timestamp)``.
    """

    names: Set[str]
    latest_timestamp: Optional[datetime]
    events_matched: int  # events that passed epoch + watermark filters
    files_scanned: int


def _parse_ts(raw: str) -> Optional[datetime]:
    """Parse a ``2026-03-26T17:15:41.684Z`` stamp to an aware UTC datetime.

    Returns ``None`` on anything unparseable rather than raising, so one odd
    line never aborts a scan. ``fromisoformat`` (Python 3.9+) accepts the
    ``+00:00`` offset and optional fractional seconds once ``Z`` is rewritten.
    """
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_events(text: str) -> Iterator[BlueprintEvent]:
    """Yield every ``BlueprintEvent`` in *text*, unfiltered and in file order.

    De-duplication and time filtering are the caller's job (``scan_files``);
    this stays a pure line matcher so it is trivially testable.
    """
    for m in _EVENT_RE.finditer(text):
        ts = _parse_ts(m.group("ts"))
        name = m.group("name").strip()
        if ts is not None and name:
            yield BlueprintEvent(ts, name)


def find_log_files(
    channel_install_path, *, since: Optional[datetime] = None
) -> List[Path]:
    """Return the SC log files worth scanning under *channel_install_path*,
    oldest first.

    Covers ``logbackups\\*.log`` plus the live ``Game.log`` at the channel
    root. A file whose mtime predates the effective floor (``since`` or the
    epoch) is dropped: its last write — hence its newest line — is already
    older than anything we care about, so a re-scan skips reading it at all
    instead of just filtering its events out afterward. Oldest-first ordering
    makes progress read naturally and lets ``latest_timestamp`` grow as the
    scan proceeds. Returns an empty list if neither location exists
    (uninitialized or misconfigured install path).
    """
    channel_install_path = Path(channel_install_path)
    floor = since or BLUEPRINT_EPOCH
    floor_posix = floor.timestamp()

    candidates: List[Path] = []
    backups = channel_install_path / LOGBACKUPS_DIRNAME
    if backups.is_dir():
        candidates.extend(backups.glob(_LOG_GLOB))
    live = channel_install_path / LIVE_LOG_NAME
    if live.is_file():
        candidates.append(live)

    kept: List[tuple] = []
    for path in candidates:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime < floor_posix:
            continue
        kept.append((mtime, path))

    kept.sort(key=lambda t: (t[0], str(t[1])))
    return [path for _, path in kept]


def scan_files(
    paths: Sequence[Path],
    *,
    since: Optional[datetime] = None,
    progress: Optional[ProgressCallback] = None,
) -> ScanResult:
    """Scan *paths* for received-blueprint names, applying both time filters.

    A name is collected when its event is at/after ``BLUEPRINT_EPOCH`` and
    strictly after ``since`` (the watermark). ``latest_timestamp`` tracks the
    newest at/after-epoch event regardless of the watermark, so re-scans never
    lose ground on the mark. Files are read line by line — some live logs run
    to tens of MB — rather than loaded whole, and unreadable files (permission
    errors, a mid-write live ``Game.log``) are skipped, not fatal:
    ``logbackups/`` can hold hundreds of rotated session logs and one bad file
    shouldn't abort the whole scan.
    """
    names: Set[str] = set()
    latest: Optional[datetime] = None
    matched = 0
    total = len(paths)

    for i, path in enumerate(paths):
        if progress is not None:
            progress(i, total, Path(path).name)
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    # Cheap reject before the regex — the vast majority of log
                    # lines never mention a blueprint.
                    if "Received Blueprint:" not in line:
                        continue
                    for ev in parse_events(line):
                        if ev.timestamp < BLUEPRINT_EPOCH:
                            continue
                        if latest is None or ev.timestamp > latest:
                            latest = ev.timestamp
                        if since is not None and ev.timestamp <= since:
                            continue
                        names.add(ev.name)
                        matched += 1
        except OSError as exc:
            logger.warning("Blueprint log scan skipped %s: %s", path, exc)
            continue

    if progress is not None:
        progress(total, total, "")

    return ScanResult(
        names=names,
        latest_timestamp=latest,
        events_matched=matched,
        files_scanned=total,
    )


def scan_channel(
    channel_dir,
    *,
    since: Optional[datetime] = None,
    progress: Optional[ProgressCallback] = None,
) -> ScanResult:
    """Discover and scan a channel's logs in one call (the worker entry point)."""
    paths = find_log_files(channel_dir, since=since)
    return scan_files(paths, since=since, progress=progress)
