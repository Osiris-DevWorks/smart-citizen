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

Not synced, by design: the per-channel log-scan watermark (a position in this
PC's own logs), paths, caches, user.ini and the generated global.ini (each PC
builds its own from its own Data.p4k).

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
FORMAT_VERSION = 1

# The time a first ledger gives what the PC already owned: older than any real
# change, so a real change on any PC wins over it.
BASELINE_AT = "1970-01-01T00:00:00.000000Z"

# Ledger entry fields.
OWNED = "owned"
AT = "at"


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


# -- the files ---------------------------------------------------------------

@dataclass
class MachineFile:
    """What one PC's file holds."""
    machine_id: str
    ledger: dict
    seeded: frozenset = frozenset()
    updated: str = ""


def encode(machine_id: str, ledger: dict, seeded, updated: str) -> str:
    """The text of a machine file, stable for diffs."""
    return json.dumps({
        "format": FORMAT_VERSION,
        "machine": machine_id,
        "updated": updated,
        "owned": {name: ledger[name] for name in sorted(ledger)},
        "starter_seeded": sorted(seeded),
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


def sync(folder, machine_id: str, ledger: dict, seeded, last_written: str = "",
         at: str | None = None) -> SyncResult:
    """Merge this PC's ledger with every file in the sync folder, and write ours.

    *ledger* is this PC's ledger, already brought in line with its owned set
    (:func:`record`). *last_written* is the ``updated`` time this PC wrote
    last. If this PC's file holds a later one, another install has the same
    id (a copied portable folder): that file is still merged, and this PC
    takes a new id so the two stop writing over each other.

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

    merged = merge([ledger] + [f.ledger for f in files.values()])
    merged_seeded = frozenset(seeded).union(*(f.seeded for f in files.values()))
    others = sum(1 for name in files if name != own_name)

    result = SyncResult(ledger=merged, seeded=merged_seeded, machine_id=machine_id,
                        other_machines=others, id_changed=id_changed)
    if own is not None and own.ledger == merged and own.seeded == merged_seeded:
        result.updated = own.updated
        return result
    updated = at or now_iso()
    # Never write a time older than the one already there, or the next sync
    # would take this PC's own file for another install's.
    if own is not None and own.updated > updated:
        updated = own.updated
    atomic_write_text(folder / own_name, encode(machine_id, merged, merged_seeded, updated))
    result.written = True
    result.updated = updated
    return result
