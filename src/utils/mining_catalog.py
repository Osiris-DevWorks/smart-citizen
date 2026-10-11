"""Where minerals are found and what they craft, for the SCO drawer searches.

Qt-free and settings-free. Two sources:

- The game's Mining Compendium journal (``Journal_General_Mining_Compendium_
  Content`` in the loaded strings): ``** Tier **`` headings over lines like
  ``Beryl - Aaron Halo, ARC-L3, Wala``. :func:`parse_mining_compendium`
  reads it into :class:`MineralInfo` records.
- ``crafting_index.json``, written next to the enhancement INIs by
  ``scripts/generate_enhancements_ini.py`` from the DataForge crafting
  blueprints (:data:`CRAFTING_INDEX_FILE`). :func:`load_crafting_index`
  reads it into a :class:`CraftingIndex`.

The compendium only names locations, so :func:`star_system` files each one
under Stanton, Pyro or Nyx from a short curated list
(:data:`STAR_SYSTEM_LOCATIONS`) plus the lagrange-point and suffix rules.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from src.utils.mining_signatures import ORE_SIGNATURES

COMPENDIUM_KEY = "Journal_General_Mining_Compendium_Content"
CRAFTING_INDEX_FILE = "crafting_index.json"

STANTON, PYRO, NYX = "Stanton", "Pyro", "Nyx"
# Locations the compendium lists that no rule below places. Lower-cased.
STAR_SYSTEM_LOCATIONS: dict[str, frozenset[str]] = {
    STANTON: frozenset({
        "aaron halo", "aberdeen", "arial", "calliope", "cellin", "clio",
        "daymar", "euterpe", "hurston", "ita", "lyria", "magda",
        "magda sand caves", "microtech", "wala", "yela", "yela ring",
    }),
    PYRO: frozenset({
        "adir", "akiro cluster", "bloom", "fairo", "fuego", "ignis", "monox",
        "terminus", "vatra", "vuur",
    }),
    NYX: frozenset({"glaciem ring", "keeger belt"}),
}
SYSTEM_ORDER = (STANTON, PYRO, NYX)
# The compendium's own prose spells some ores differently from their
# DataForge loc keys (a CIG typo): lower-cased compendium name -> table key.
COMPENDIUM_ORE_ALIASES = {"savrilium": "savrillium"}
# Stanton's lagrange points: HUR-L1, ARC-L5, ...
_STANTON_LAGRANGE = re.compile(r"^(?:ARC|CRU|HUR|MIC)-L\d$", re.IGNORECASE)
_TIER_LINE = re.compile(r"^\*+\s*(.+?)\s*\*+$")


@dataclass(frozen=True)
class MineralInfo:
    name: str
    tier: str
    locations: tuple[str, ...]


def star_system(location: str) -> str:
    """The star system a compendium location belongs to, or ``""``."""
    low = location.strip().lower()
    if "(nyx)" in low:
        return NYX
    if "pyro" in low:
        return PYRO
    if "stanton" in low or _STANTON_LAGRANGE.match(location.strip()):
        return STANTON
    for system, names in STAR_SYSTEM_LOCATIONS.items():
        if low in names:
            return system
    return ""


def locations_by_system(locations) -> dict[str, list[str]]:
    """Group locations by star system in :data:`SYSTEM_ORDER`; unplaced ones
    (e.g. "All Moons/Planets/Caves") go under ``""`` last."""
    grouped: dict[str, list[str]] = {}
    for loc in sorted(locations, key=str.lower):
        grouped.setdefault(star_system(loc), []).append(loc)
    order = [s for s in SYSTEM_ORDER if s in grouped] + ([""] if "" in grouped else [])
    return {s: grouped[s] for s in order}


def parse_mining_compendium(content: str) -> dict[str, MineralInfo]:
    """Minerals listed in the compendium text, keyed by name.

    Takes the loc value as stored (``\\n`` escapes) or with real newlines.
    A mineral line is one word, `` - ``, then comma-separated locations;
    anything else (intro prose, notes) is skipped.
    """
    minerals: dict[str, MineralInfo] = {}
    tier = ""
    for raw in re.split(r"\\n|\n", content or ""):
        line = raw.strip()
        heading = _TIER_LINE.match(line)
        if heading:
            tier = heading.group(1)
            continue
        name, sep, rest = line.partition(" - ")
        name = name.strip()
        if not sep or not name or " " in name:
            continue
        locations = tuple(
            re.sub(r"^Found in\s+", "", part.strip(), flags=re.IGNORECASE)
            for part in rest.split(",") if part.strip()
        )
        if locations:
            minerals[name] = MineralInfo(name, tier, locations)
    return minerals


def read_compendium(base_ini: Path) -> dict[str, MineralInfo]:
    """The compendium minerals from a ``base.ini``; empty when it is missing.

    Keys are matched the way ``parse_ini_file`` reads them: any ``,P``-style
    suffix CIG puts after a key is dropped, and case doesn't matter.
    """
    wanted = COMPENDIUM_KEY.lower()
    try:
        with open(base_ini, encoding="utf-8-sig", errors="replace") as fh:
            for line in fh:
                key, sep, value = line.partition("=")
                if sep and key.split(",", 1)[0].strip().lower() == wanted:
                    return parse_mining_compendium(value.rstrip("\r\n"))
    except OSError:
        pass
    return {}


def ore_signature(mineral: str) -> tuple[int, int] | None:
    """``(base RS, largest cluster)`` for a compendium mineral, if known."""
    low = mineral.lower()
    return ORE_SIGNATURES.get(COMPENDIUM_ORE_ALIASES.get(low, low))


def minerals_at(location: str, minerals: dict[str, MineralInfo]) -> list[str]:
    """Names of the minerals the compendium lists at *location*."""
    low = location.lower()
    return sorted(m.name for m in minerals.values()
                  if any(loc.lower() == low for loc in m.locations))


@dataclass
class CraftingIndex:
    """Material <-> crafted item links from the DataForge blueprints.

    ``materials`` maps a material's internal name to its display names and
    the ``(category, item)`` pairs it goes into.
    """
    materials: dict[str, dict] = field(default_factory=dict)

    def material_names(self) -> dict[str, list[str]]:
        return {key: entry.get("names") or [key] for key, entry in self.materials.items()}

    def items_using(self, material_key: str) -> list[tuple[str, str]]:
        entry = self.materials.get(material_key) or {}
        return [tuple(pair) for pair in entry.get("items", [])]

    def materials_for(self, item: str) -> list[str]:
        """Display names of every material that goes into *item*."""
        return sorted(
            (entry.get("names") or [key])[0]
            for key, entry in self.materials.items()
            if any(name == item for _cat, name in entry.get("items", []))
        )

    def items(self) -> dict[str, str]:
        """Every crafted item, with its category."""
        return {name: cat for entry in self.materials.values()
                for cat, name in entry.get("items", [])}

    def material_key_for(self, mineral: str) -> str | None:
        """The material whose display names include *mineral*'s word."""
        low = mineral.lower()
        for key, entry in self.materials.items():
            names = [n.lower() for n in entry.get("names") or []] + [key.lower()]
            if any(n == low or n.split(" ")[0] == low for n in names):
                return key
        return None


def load_crafting_index(path: Path) -> CraftingIndex:
    """Read ``crafting_index.json``; an empty index when missing or unreadable."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return CraftingIndex()
    materials = data.get("materials") if isinstance(data, dict) else None
    return CraftingIndex(materials if isinstance(materials, dict) else {})


def write_crafting_index(path: Path, materials: dict[str, dict]) -> None:
    """Write the index the generator builds (see :class:`CraftingIndex`)."""
    Path(path).write_text(
        json.dumps({"version": 1, "materials": materials}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
