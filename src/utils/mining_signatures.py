"""Mining scan signatures: the base resource signature (RS) per deposit type.

Qt-free and settings-free. One canonical table, two consumers:

- ``scripts/generate_enhancements_ini.py`` reads :data:`MINEABLE_RS_VALUES`
  for the Battaglia ``[RS ####]`` mission-title tag and the Mining
  Compendium journal's "Base Resource Signature" line.
- The Smart Citizen Overlay (SCO) decodes the number shown next to a scan
  ping with :func:`decode_signature`.

A cluster's signature is ``count * base``, so decoding is a divisibility
check against each base, capped at the deposit's largest cluster size.

CIG doesn't expose these numbers in DataForge (see scripts/CLAUDE.md, the
Battaglia entry), so the table is curated from community reference data:
MrKraken/StarStrings ``ptu/4.9`` ``mining.ini``, cross-checked against
starminersdepot.com's Alpha 4.8 scanner table. Max cluster sizes come from
the in-game scanner signature chart. "ice" has no confirmed reference for
this patch but is kept from the original 4.9 source.
"""
from __future__ import annotations

from dataclasses import dataclass

# Ship-mineable ores: key -> (base RS, largest cluster size).
# Keys match the ``mineabletype_primary_<ore>`` loc-key spelling.
ORE_SIGNATURES: dict[str, tuple[int, int]] = {
    "quantainium":   (3170, 2),
    "stileron":      (3185, 2),
    "savrillium":    (3200, 2),
    "ouratite":      (3370, 3),
    "riccite":       (3385, 3),
    "lindinium":     (3400, 3),
    "beryl":         (3540, 4),
    "taranite":      (3555, 4),
    "borase":        (3570, 4),
    "gold":          (3585, 4),
    "bexalite":      (3600, 4),
    "laranite":      (3825, 5),
    "aslarite":      (3840, 5),
    "titanium":      (3855, 5),
    "tungsten":      (3870, 5),
    "agricium":      (3885, 5),
    "torite":        (3900, 5),
    "hephaestanite": (4180, 6),
    "tin":           (4195, 6),
    "quartz":        (4210, 6),
    "corundum":      (4225, 6),
    "copper":        (4240, 6),
    "silicon":       (4255, 6),
    "iron":          (4270, 6),
    "aluminium":     (4285, 6),
    "ice":           (4300, 6),
}

# Non-ship deposits that share the scanner: key -> (base RS, largest count).
# Their round bases overlap each other (12000 = 3 ROC / 4 FPS / 6 Salvage),
# so a decode can return several of these at once.
OTHER_SIGNATURES: dict[str, tuple[int, int]] = {
    "roc":     (4000, 7),
    "fps":     (3000, 10),
    "salvage": (2000, 15),
}

# Base RS per ore, the shape the enhancement generator consumes.
MINEABLE_RS_VALUES: dict[str, int] = {
    ore: base for ore, (base, _max) in ORE_SIGNATURES.items()
}

_ALL_SIGNATURES: dict[str, tuple[int, int]] = {**ORE_SIGNATURES, **OTHER_SIGNATURES}


@dataclass(frozen=True)
class SignatureMatch:
    """One reading of a signature: *count* deposits of type *kind*."""
    kind: str
    count: int


def decode_signature(value: int) -> list[SignatureMatch]:
    """Return every (kind, count) whose ``count * base == value``.

    Empty when nothing matches (a misread, or a deposit type not in the
    table). Sorted by count, so a single-cluster reading comes first.
    """
    if value <= 0:
        return []
    matches = [
        SignatureMatch(kind, value // base)
        for kind, (base, max_count) in _ALL_SIGNATURES.items()
        if value % base == 0 and 1 <= value // base <= max_count
    ]
    return sorted(matches, key=lambda m: (m.count, m.kind))


def parse_signature_text(text: str) -> int | None:
    """Turn HUD text like ``"10,200"`` into ``10200``; None if not a number."""
    digits = text.replace(",", "").replace(".", "").strip()
    return int(digits) if digits.isdigit() else None
