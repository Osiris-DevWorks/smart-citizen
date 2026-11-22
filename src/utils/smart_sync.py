"""Smart Sync: keep the Owned blueprints the same on every PC a player uses (#567).

The Owned set is built from each PC's own game logs, so a blueprint earned on
one PC never shows as Owned on another. Smart Sync shares it through a folder
the player already syncs (Google Drive for Desktop, OneDrive, Dropbox, a NAS).
The app makes no network calls: the player's own sync client moves the files.

Layout. Each PC writes only its own file and reads everyone's::

    <chosen folder>/Smart Citizen Sync/machine-3f9a1b2c.json   <- PC A only
    <chosen folder>/Smart Citizen Sync/machine-b71c04de.json   <- PC B only

No two PCs write the same file, so the cloud client never has to resolve a
conflict. A conflicted copy it makes anyway (``machine-3f9a1b2c (1).json``)
is read like any other file, which is harmless under the merge rule below.
Every file is written in one step (``atomic_io``), so a reader never sees half
of one.

Merge rule: the newest change to each blueprint wins. The ledger holds, per
blueprint name, whether it is owned and when that last changed. Moving a
blueprint back to Available is a change too (``owned: false`` with a newer
time), so the next sync does not bring it back, which a plain union would.
Equal times favour owned. A PC's first ledger records what it already owned
at ``BASELINE_AT`` (the epoch): it says "owned", but any real change on any
PC wins over it.

The starter-blueprint seed marker (#416) travels too: the loc keys seeded on
any PC are seeded everywhere, so a starter moved back to Available on one PC
is not seeded again by the next scan on another.

Since format 2 a file also carries the player's settings (what Export
Settings saves, less the keys ``AppSettings.is_smart_sync_local_key`` keeps on
each PC) and their string edits (each channel's user.ini), in *value
ledgers*: ``{key: {"value": v, "at": iso}}``, ``value`` None for a key that
was removed, so a removal travels too. The newest change to each key wins,
as for blueprints. A value ledger is recorded against what this PC last saw
(:func:`record_values`), not against the ledger itself, because settings
from another PC wait for the next start: until then the PC's own values
differ from the ledger without being changes.

A PC that turns sync on gives what it already has :data:`BASELINE_AT`, or
:data:`JOIN_AT` when other PCs already share that section, so a PC that
joins takes the shared settings and edits instead of handing its own to
every other PC.

Not synced, by design: the per-channel log-scan watermark (a position in this
PC's own logs), paths, caches and the generated global.ini (each PC builds its
own from its own Data.p4k and the synced edits and settings).

Qt-free and settings-free: ``AppSettings`` stores the ledger, the machine id
and the folder, and ``SmartSyncWorker`` runs :func:`sync` off the GUI thread.
"""
from __future__ import annotations

import json
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src.utils.atomic_io import atomic_write_text, read_bytes_retrying

logger = logging.getLogger(__name__)

# The folder Smart Sync makes inside the folder the player picks, so its files
# never mix with whatever else is synced there.
SYNC_SUBFOLDER = "Smart Citizen Sync"
MACHINE_FILE_PREFIX = "machine-"
MACHINE_FILE_SUFFIX = ".json"
# 4 random bytes, 8 hex characters: no name, account or path goes in a file.
MACHINE_ID_BYTES = 4
FORMAT_VERSION = 2

# The time a first ledger gives what the PC already owned: older than any real
# change, so a real change on any PC wins over it.
BASELINE_AT = "1970-01-01T00:00:00.000000Z"

# The time a PC that joins gives what it already had: older still, so what
# the PCs already sharing chose wins over it.
JOIN_AT = "0000-01-01T00:00:00.000000Z"

# Ledger entry fields.
OWNED = "owned"
AT = "at"
VALUE = "value"

# Machine file sections.
SECTION_OWNED = "owned"
SECTION_SETTINGS = "settings"
SECTION_USER_INI = "user_ini"


def now_iso() -> str:
    """The current UTC time in the ledger's form: microseconds, ``Z``.

    Microseconds, not seconds: a blueprint owned and moved back within one
    second must still read as moved back, and equal times favour owned. One
    fixed width, so the times order correctly as strings.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def new_machine_id() -> str:
    """A random id for this PC's file. It names nothing about the PC."""
    return secrets.token_hex(MACHINE_ID_BYTES)


def machine_file_name(machine_id: str) -> str:
    return f"{MACHINE_FILE_PREFIX}{machine_id}{MACHINE_FILE_SUFFIX}"


def sync_dir(folder) -> Path:
    """The ``Smart Citizen Sync`` folder inside the folder the player picked."""
    return Path(folder) / SYNC_SUBFOLDER


# -- the ledger --------------------------------------------------------------
#
# A ledger is a plain dict ``{name: {"owned": bool, "at": iso}}``. Every
# function here returns a new dict and leaves its inputs alone.

def _valid_entry(entry) -> bool:
    return (isinstance(entry, dict)
            and isinstance(entry.get(OWNED), bool)
            and isinstance(entry.get(AT), str))


def clean_ledger(raw) -> dict:
    """The well-formed entries of *raw*; anything else is dropped."""
    if not isinstance(raw, dict):
        return {}
    return {
        name: {OWNED: entry[OWNED], AT: entry[AT]}
        for name, entry in raw.items()
        if isinstance(name, str) and name and _valid_entry(entry)
    }


def owned_from_ledger(ledger: dict) -> set:
    """The names the ledger calls owned."""
    return {name for name, entry in ledger.items() if entry[OWNED]}


def baseline(ledger: dict, owned) -> dict:
    """Add each owned name the ledger has no word on, at ``BASELINE_AT``.

    For a PC that has just turned Smart Sync on: what it already owns is
    shared, but loses to any real change made anywhere.
    """
    out = dict(ledger)
    for name in owned:
        if name not in out:
            out[name] = {OWNED: True, AT: BASELINE_AT}
    return out


def record(ledger: dict, owned, at: str | None = None) -> dict:
    """Bring the ledger in line with *owned*, stamping each difference *at*.

    A name *owned* holds that the ledger does not call owned becomes owned; a
    name the ledger calls owned that *owned* lacks becomes not owned. Names
    that already agree keep their time, so a sync that changed nothing
    writes nothing new.
    """
    at = at or now_iso()
    owned = set(owned)
    out = dict(ledger)
    for name in owned:
        entry = out.get(name)
        if entry is None or not entry[OWNED]:
            out[name] = {OWNED: True, AT: at}
    for name, entry in ledger.items():
        if entry[OWNED] and name not in owned:
            out[name] = {OWNED: False, AT: at}
    return out


def _newer(a: dict, b: dict) -> dict:
    """The entry that wins: the later time, and owned when the times match."""
    if a[AT] != b[AT]:
        return a if a[AT] > b[AT] else b
    return a if a[OWNED] else b


def merge(ledgers) -> dict:
    """One ledger from many: per name, the newest entry wins.

    Times are compared as strings, which orders ISO-8601 UTC times
    correctly. Every ledger here is written by :func:`now_iso`, so they share
    one form.
    """
    out: dict = {}
    for ledger in ledgers:
        for name, entry in ledger.items():
            have = out.get(name)
            out[name] = entry if have is None else _newer(have, entry)
    return out


# -- value ledgers (settings, user.ini) --------------------------------------
#
# ``{key: {"value": v, "at": iso}}``; ``value`` is None for a removed key.

def _valid_value_entry(entry) -> bool:
    return (isinstance(entry, dict) and VALUE in entry
            and isinstance(entry.get(AT), str))


def clean_value_ledger(raw) -> dict:
    """The well-formed entries of *raw*; anything else is dropped."""
    if not isinstance(raw, dict):
        return {}
    return {
        key: {VALUE: entry[VALUE], AT: entry[AT]}
        for key, entry in raw.items()
        if isinstance(key, str) and key and _valid_value_entry(entry)
    }


def clean_channel_ledgers(raw) -> dict:
    """``{channel: value ledger}`` from *raw*, empty channels dropped."""
    if not isinstance(raw, dict):
        return {}
    out = {}
    for channel, ledger in raw.items():
        if isinstance(channel, str) and channel:
            cleaned = clean_value_ledger(ledger)
            if cleaned:
                out[channel] = cleaned
    return out


def values_from_ledger(ledger: dict) -> dict:
    """The keys the ledger holds a value for, with that value."""
    return {key: entry[VALUE] for key, entry in ledger.items() if entry[VALUE] is not None}


def baseline_values(ledger: dict, values: dict, at: str = BASELINE_AT) -> dict:
    """Add each key of *values* the ledger has no word on, at *at*."""
    out = dict(ledger)
    for key, value in values.items():
        if key not in out:
            out[key] = {VALUE: value, AT: at}
    return out


def record_values(ledger: dict, values: dict, seen: dict, at: str | None = None,
                  *, new_keys_are_changes: bool = False) -> dict:
    """Stamp, at *at*, each change this PC made since it last saw *seen*.

    A key whose value differs from *seen* changed here; a key *seen* had
    that *values* lacks was removed here. A setting this PC never saw (one a
    newer version adds with its default) is no change: it joins at
    :data:`BASELINE_AT` when the ledger has no word on it, so it never wins
    over another PC's real change. A string edit is never a default, so
    user.ini passes *new_keys_are_changes* and a new key is a change.
    """
    at = at or now_iso()
    out = dict(ledger)
    for key, value in values.items():
        if key in seen:
            if seen[key] != value:
                out[key] = {VALUE: value, AT: at}
        elif new_keys_are_changes:
            entry = out.get(key)
            if entry is None or entry[VALUE] != value:
                out[key] = {VALUE: value, AT: at}
        elif key not in out:
            out[key] = {VALUE: value, AT: BASELINE_AT}
    for key in seen:
        if key not in values:
            out[key] = {VALUE: None, AT: at}
    return out


def _value_rank(entry: dict) -> str:
    return json.dumps(entry[VALUE], sort_keys=True, ensure_ascii=False)


def merge_values(ledgers) -> dict:
    """One value ledger from many: per key, the newest entry wins.

    Equal times (two PCs' baselines) are settled the same way on every PC,
    by the value's JSON text, so all PCs end on one answer.
    """
    out: dict = {}
    for ledger in ledgers:
        for key, entry in ledger.items():
            have = out.get(key)
            if have is None:
                out[key] = entry
            elif entry[AT] != have[AT]:
                out[key] = entry if entry[AT] > have[AT] else have
            elif _value_rank(entry) > _value_rank(have):
                out[key] = entry
    return out


def merge_channels(channel_ledgers) -> dict:
    """:func:`merge_values` per channel."""
    out: dict = {}
    for ledgers in channel_ledgers:
        for channel, ledger in ledgers.items():
            out[channel] = merge_values([out.get(channel, {}), ledger])
    return out


# -- the files ---------------------------------------------------------------

@dataclass
class MachineFile:
    """What one PC's file holds."""
    machine_id: str
    ledger: dict
    seeded: frozenset = frozenset()
    updated: str = ""
    settings: dict = field(default_factory=dict)
    user_ini: dict = field(default_factory=dict)


def _sorted(ledger: dict) -> dict:
    return {key: ledger[key] for key in sorted(ledger)}


def encode(machine_id: str, ledger: dict, seeded, updated: str,
           settings: dict | None = None, user_ini: dict | None = None) -> str:
    """The text of a machine file, stable for diffs."""
    return json.dumps({
        "format": FORMAT_VERSION,
        "machine": machine_id,
        "updated": updated,
        SECTION_OWNED: _sorted(ledger),
        "starter_seeded": sorted(seeded),
        SECTION_SETTINGS: _sorted(settings or {}),
        SECTION_USER_INI: {ch: _sorted(led) for ch, led in sorted((user_ini or {}).items())},
    }, indent=1, ensure_ascii=False) + "\n"


def decode(text: str) -> MachineFile | None:
    """A machine file's contents, or None for one that is not one."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("owned"), dict):
        return None
    seeded = data.get("starter_seeded")
    if not isinstance(seeded, list):
        seeded = []
    return MachineFile(
        machine_id=data.get("machine") if isinstance(data.get("machine"), str) else "",
        ledger=clean_ledger(data.get("owned")),
        seeded=frozenset(k for k in seeded if isinstance(k, str)),
        updated=data.get("updated") if isinstance(data.get("updated"), str) else "",
        settings=clean_value_ledger(data.get(SECTION_SETTINGS)),
        user_ini=clean_channel_ledgers(data.get(SECTION_USER_INI)),
    )


def read_machine_files(folder: Path) -> "dict[str, MachineFile]":
    """Every machine file in the sync folder, by file name.

    A file that cannot be read or is not a machine file is logged and
    skipped: one bad file must not stop the others syncing.
    """
    out = {}
    if not folder.is_dir():
        return out
    for path in sorted(folder.glob(f"{MACHINE_FILE_PREFIX}*{MACHINE_FILE_SUFFIX}")):
        try:
            text = read_bytes_retrying(path).decode("utf-8")
        except (OSError, UnicodeDecodeError) as e:
            logger.warning("Smart Sync: could not read %s: %s", path.name, e)
            continue
        parsed = decode(text)
        if parsed is None:
            logger.warning("Smart Sync: %s is not a Smart Sync file, skipped", path.name)
            continue
        out[path.name] = parsed
    return out


@dataclass
class SyncResult:
    """What a sync found and did."""
    ledger: dict                          # the merged ledger, now this PC's own
    seeded: frozenset                     # the merged starter seed marker
    machine_id: str                       # this PC's id (new if it was shared)
    written: bool = False                 # this PC's file was written
    updated: str = ""                     # the "updated" time written, or kept
    other_machines: int = 0               # files from other PCs that were read
    id_changed: bool = False              # another install had this PC's id
    notes: list = field(default_factory=list)
    settings: dict = field(default_factory=dict)   # merged settings ledger
    user_ini: dict = field(default_factory=dict)   # merged {channel: ledger}


def sync(folder, machine_id: str, ledger: dict, seeded, last_written: str = "",
         at: str | None = None, *, settings: dict | None = None,
         user_ini: dict | None = None, baseline_settings: dict | None = None,
         baseline_user_ini: dict | None = None) -> SyncResult:
    """Merge this PC's ledger with every file in the sync folder, and write ours.

    *ledger* is this PC's ledger, already brought in line with its owned set
    (:func:`record`). *last_written* is the ``updated`` time this PC wrote
    last. If this PC's file holds a later one, another install has the same
    id (a copied portable folder): that file is still merged, and this PC
    takes a new id so the two stop writing over each other.

    *settings* and *user_ini* are this PC's value ledgers. A PC that has
    none yet (it just turned sync on, or just upgraded from format 1) passes
    what it has as *baseline_settings* / *baseline_user_ini*
    (``{channel: {key: value}}``) instead: it joins at :data:`JOIN_AT` when
    another PC's file already shares that section (that channel, for
    user.ini), and at :data:`BASELINE_AT` otherwise.

    The file is written only when what it would hold changed. Raises OSError
    when the folder cannot be made or the file cannot be written; reading
    problems are logged and skipped.
    """
    folder = sync_dir(folder)
    folder.mkdir(parents=True, exist_ok=True)
    files = read_machine_files(folder)

    own_name = machine_file_name(machine_id)
    own = files.get(own_name)
    id_changed = False
    if own is not None and last_written and own.updated > last_written:
        logger.warning(
            "Smart Sync: %s was written by another install with this PC's id; "
            "this PC takes a new one", own_name)
        machine_id = new_machine_id()
        own_name = machine_file_name(machine_id)
        own = files.get(own_name)
        id_changed = True

    other_files = [f for name, f in files.items() if name != own_name]
    settings = dict(settings or {})
    user_ini = {ch: dict(led) for ch, led in (user_ini or {}).items()}
    if baseline_settings is not None and not settings:
        joined = any(f.settings for f in other_files)
        settings = baseline_values({}, baseline_settings, JOIN_AT if joined else BASELINE_AT)
    for channel, values in (baseline_user_ini or {}).items():
        if user_ini.get(channel):
            continue
        joined = any(f.user_ini.get(channel) for f in other_files)
        user_ini[channel] = baseline_values({}, values, JOIN_AT if joined else BASELINE_AT)

    merged = merge([ledger] + [f.ledger for f in files.values()])
    merged_seeded = frozenset(seeded).union(*(f.seeded for f in files.values()))
    merged_settings = merge_values([settings] + [f.settings for f in files.values()])
    merged_user_ini = merge_channels([user_ini] + [f.user_ini for f in files.values()])
    merged_user_ini = {ch: led for ch, led in merged_user_ini.items() if led}
    others = len(other_files)

    result = SyncResult(ledger=merged, seeded=merged_seeded, machine_id=machine_id,
                        other_machines=others, id_changed=id_changed,
                        settings=merged_settings, user_ini=merged_user_ini)
    if (own is not None and own.ledger == merged and own.seeded == merged_seeded
            and own.settings == merged_settings and own.user_ini == merged_user_ini):
        result.updated = own.updated
        return result
    updated = at or now_iso()
    # Never write a time older than the one already there, or the next sync
    # would take this PC's own file for another install's.
    if own is not None and own.updated > updated:
        updated = own.updated
    atomic_write_text(folder / own_name, encode(machine_id, merged, merged_seeded, updated,
                                                merged_settings, merged_user_ini))
    result.written = True
    result.updated = updated
    return result
