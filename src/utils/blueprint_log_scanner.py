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

The game logs the notification in the language it shows (#564): a player
who plays in Spanish logs ``"Plano recibido: <name>: "``. That text comes
from the loc key ``NOTIFICATION_LOC_KEY``, English ``Received Blueprint: %s``.
So the functions here take templates, that key's text in each language to
look for, with ``%s`` where the name goes, and look for English alone when
given none. :func:`notification_templates` reads them from the loc files the
caller names.

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
from typing import Callable, Iterator, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger(__name__)

# Blueprints did not exist in Star Citizen before March 2026 (#222). A hard
# floor so we never parse ancient logs even absent a watermark. Timezone-aware
# (UTC) to compare cleanly against the ``...Z`` timestamps the log carries.
BLUEPRINT_EPOCH = datetime(2026, 3, 1, tzinfo=timezone.utc)

#: The loc key whose text the game shows, and logs, when the player receives
#: a blueprint (#564).
NOTIFICATION_LOC_KEY = "crafting_hud_notification_received_blueprint"

#: That key's text in the game's own English global.ini, with ``%s`` where
#: the game puts the blueprint's name. Always looked for: a log written while
#: the game showed English holds it, whatever language is selected now.
ENGLISH_NOTIFICATION = "Received Blueprint: %s"

# Where a template takes the blueprint's name.
_NAME_SLOT = "%s"

# Every "Added notification" line, blueprint or not. The game logs the
# notification's text (the template with the name in place of %s), then
# ``: "`` and its id in brackets, so the text is captured non-greedily up to
# the first ``: " [``, and embedded quotes survive intact (e.g.
# ``Demeco "Purgatory Camo" LMG``). Anchored on the
# ``<SHUDEvent_OnNotification> Added notification`` prefix (not just the
# notification's text) so the ``<UpdateNotificationItem>`` echo lines and
# bare continuation lines that quote the same notification are never
# mistaken for a second, distinct event. Whether a notification is a
# blueprint is decided from its text, against the templates (_name_in).
_NOTIFICATION_RE = re.compile(
    r"<(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)>"
    r".*?<SHUDEvent_OnNotification> Added notification "
    r'"(?P<text>.*?): " \['
)

# Every line _NOTIFICATION_RE can match holds this, so a line without it is
# rejected before the regex runs: the vast majority of log lines are not
# notifications. It holds no text of the notification itself, so it is the
# same check whatever language the game shows.
_NOTIFICATION_MARK = "<SHUDEvent_OnNotification> Added notification"

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


def notification_templates(loc_files: Sequence = ()) -> Tuple[str, ...]:
    """The templates a scan looks for: English, then the text of
    ``NOTIFICATION_LOC_KEY`` in each of *loc_files* that has it, each text
    once, in that order (#564).

    The game logs the notification in the language it shows, so the caller
    names the files that say what it shows (the base.ini Smart Citizen shows
    and applies, the global.ini applied to the game). A file that is missing,
    cannot be read or has no such key adds nothing. Each can be about 11 MB,
    so this runs on a worker's thread.
    """
    templates = [ENGLISH_NOTIFICATION]
    for path in loc_files:
        text = (_loc_value(path, NOTIFICATION_LOC_KEY) or "").strip()
        if text and text not in templates:
            templates.append(text)
    return tuple(templates)


def _loc_value(path, key: str) -> Optional[str]:
    """*key*'s value in the INI file at *path*, or None when the file or the
    key is not there. Keys are matched as ``mining_catalog.read_compendium``
    matches them: a ``,P``-style suffix CIG puts after a key is dropped, and
    case doesn't matter. Reading stops at the first match."""
    wanted = key.lower()
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            for line in fh:
                k, sep, value = line.partition("=")
                if sep and k.split(",", 1)[0].strip().lower() == wanted:
                    return value.rstrip("\r\n")
    except OSError as exc:
        logger.debug("Blueprint log scan: no notification text read from %s: %s", path, exc)
    return None


def _template_pattern(template: str) -> Optional[re.Pattern]:
    """The pattern a notification's text must match in full to be
    *template*'s, with the name captured where ``%s`` is.

    None for a template a scan cannot use: one without exactly one ``%s``
    has no one name to read, and one with no letter or digit around its
    ``%s`` would take every notification for a blueprint. Both ends are
    stripped, as they are from the text it is matched against.
    """
    text = template.strip()
    if text.count(_NAME_SLOT) != 1:
        return None
    before, after = text.split(_NAME_SLOT)
    if not any(ch.isalnum() for ch in before + after):
        return None
    return re.compile(re.escape(before) + "(?P<name>.*)" + re.escape(after))


def _template_patterns(templates: Sequence[str]) -> List[re.Pattern]:
    """The patterns of *templates*, each once, the one with the most fixed
    text first: a template that holds another's text and more (an override
    such as ``Received Blueprint: %s (new)``) must be tried before the
    shorter one, which would read the extra text as part of the name. A
    template that cannot be used is logged and left out."""
    found = {}
    for template in templates:
        pattern = _template_pattern(template)
        if pattern is None:
            logger.info("Blueprint log scan: not using the notification text %r, "
                        "which needs one %%s with text around it", template)
            continue
        fixed = len(template.strip()) - len(_NAME_SLOT)
        found.setdefault(pattern.pattern, (fixed, pattern))
    ordered = sorted(found.values(), key=lambda entry: entry[0], reverse=True)
    return [pattern for _, pattern in ordered]


def _name_in(text: str, patterns: Sequence[re.Pattern]) -> str:
    """The blueprint name in a notification's *text*: what the first template
    that matches all of it holds where ``%s`` is, stripped. "" when none
    does, as for every notification that is not a received blueprint."""
    text = text.strip()
    for pattern in patterns:
        m = pattern.fullmatch(text)
        if m:
            return m.group("name").strip()
    return ""


def parse_events(
    text: str, templates: Sequence[str] = (ENGLISH_NOTIFICATION,)
) -> Iterator[BlueprintEvent]:
    """Yield every ``BlueprintEvent`` in *text*, unfiltered and in file order.

    *templates* are the notification texts that mean a blueprint was
    received, ``%s`` where the name goes (#564); English alone by default.
    De-duplication and time filtering are the caller's job (``scan_files``);
    this stays a pure line matcher so it is trivially testable.
    """
    yield from _events(text, _template_patterns(templates))


def _events(text: str, patterns: Sequence[re.Pattern]) -> Iterator[BlueprintEvent]:
    """parse_events with the templates' patterns already built, so a scan
    builds them once rather than once a line."""
    for m in _NOTIFICATION_RE.finditer(text):
        name = _name_in(m.group("text"), patterns)
        if not name:
            continue
        ts = _parse_ts(m.group("ts"))
        if ts is not None:
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
    templates: Sequence[str] = (ENGLISH_NOTIFICATION,),
) -> ScanResult:
    """Scan *paths* for received-blueprint names, applying both time filters.

    A name is collected when its event is at/after ``BLUEPRINT_EPOCH`` and
    strictly after ``since`` (the watermark). ``latest_timestamp`` tracks the
    newest at/after-epoch event regardless of the watermark, so re-scans never
    lose ground on the mark. Files are read line by line — some live logs run
    to tens of MB — rather than loaded whole, and unreadable files (permission
    errors, a mid-write live ``Game.log``) are skipped, not fatal:
    ``logbackups/`` can hold hundreds of rotated session logs and one bad file
    shouldn't abort the whole scan. *templates* are as for
    :func:`parse_events`.
    """
    names: Set[str] = set()
    latest: Optional[datetime] = None
    matched = 0
    total = len(paths)
    patterns = _template_patterns(templates)

    for i, path in enumerate(paths):
        if progress is not None:
            progress(i, total, Path(path).name)
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    # Cheap reject before the regex — the vast majority of log
                    # lines are not notifications.
                    if _NOTIFICATION_MARK not in line:
                        continue
                    for ev in _events(line, patterns):
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
    templates: Sequence[str] = (ENGLISH_NOTIFICATION,),
) -> ScanResult:
    """Discover and scan a channel's logs in one call (the worker entry point)."""
    paths = find_log_files(channel_dir, since=since)
    return scan_files(paths, since=since, progress=progress, templates=templates)


class GameLogTail:
    """Incrementally read new "Received Blueprint" events from one live log.

    The Smart Citizen Overlay polls this while the game runs, so a blueprint
    earned mid-session shows up without a manual Scan. Each :meth:`poll`
    reads only the bytes appended since the last call and keeps a trailing
    partial line for the next poll, so an event the game is mid-way through
    writing is never half-parsed.

    Star Citizen rotates ``Game.log`` into ``logbackups/`` at launch and starts
    a fresh file. A different file (its ``st_ino`` changed), one smaller than
    the saved offset, or one gone and then back means rotation: reading
    restarts from the top. The identity check matters when the old log was
    short: a new one could pass its size between two polls. Events at or before
    *since* (the watermark) are dropped, so re-reading a rotated file never
    double-counts. Same epoch floor and *templates* as :func:`scan_files`.
    """

    #: Bytes read per step, so a first poll of a large log never holds it
    #: all in memory at once (the scan streams line by line for the same
    #: reason).
    READ_CHUNK = 1 << 20

    def __init__(
        self,
        path,
        *,
        since: Optional[datetime] = None,
        templates: Sequence[str] = (ENGLISH_NOTIFICATION,),
    ):
        self.path = Path(path)
        self.since = since
        self._patterns = _template_patterns(templates)
        self._offset = 0
        self._file_id: Optional[int] = None
        # Kept as bytes, not text: a poll can end inside a multi-byte UTF-8
        # character, and decoding the two halves apart would garble the name.
        self._partial = b""

    def poll(self) -> List[BlueprintEvent]:
        """Return new events since the last poll; [] when there are none."""
        try:
            st = self.path.stat()
        except OSError:
            # Between rotation and the new file appearing; try again later.
            self._offset, self._partial = 0, b""
            return []
        size = st.st_size
        # Where the platform has no file id st_ino is always 0, so this falls
        # back to the size check alone.
        replaced = self._file_id is not None and st.st_ino != self._file_id
        if replaced or size < self._offset:
            self._offset, self._partial = 0, b""
        self._file_id = st.st_ino
        if size == self._offset:
            return []
        events: List[BlueprintEvent] = []
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self._offset)
                while self._offset < size:
                    chunk = fh.read(min(self.READ_CHUNK, size - self._offset))
                    if not chunk:
                        break
                    self._offset += len(chunk)
                    complete, sep, rest = (self._partial + chunk).rpartition(b"\n")
                    if not sep:
                        self._partial = rest
                        continue
                    self._partial = rest
                    events.extend(self._events_in(complete))
        except OSError as exc:
            logger.debug("Live blueprint log read skipped %s: %s", self.path, exc)
        if events:
            self.since = max(ev.timestamp for ev in events)
        return events

    def _events_in(self, complete: bytes) -> List[BlueprintEvent]:
        found: List[BlueprintEvent] = []
        for line in complete.decode("utf-8", errors="replace").splitlines():
            if _NOTIFICATION_MARK not in line:
                continue
            for ev in _events(line, self._patterns):
                if ev.timestamp < BLUEPRINT_EPOCH:
                    continue
                if self.since is not None and ev.timestamp <= self.since:
                    continue
                found.append(ev)
        return found
