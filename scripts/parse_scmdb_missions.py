"""Parse SCMDB mission export (multi-line text) into the fixture CSV format.

Input: tests/fixtures/temp.txt (SCMDB copy-paste export)
Output: tests/fixtures/missions_latest.csv (same columns as missions_4.7.177.csv)
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Known 2-letter faction codes from SCMDB
FACTION_CODES = {
    "AH", "BH", "BZ", "CD", "CF", "CO", "DS", "ES", "FC", "FE",
    "HA", "HE", "ID", "KR", "LF", "MG", "NS", "RI", "RW", "SI",
    "UN", "UW", "VA", "WE",
}

SYSTEMS = {"Pyro", "Stanton", "Nyx"}

FLAGS = {"ILLEGAL", "CHAIN", "STARTER", "UNIQUE"}

MISSION_TYPES = {
    "Delivery", "Mercenary", "Bounty Hunter", "Maintenance",
    "Investigation", "Collection", "Smuggling", "Piracy",
    "Racing", "Salvage",
}


def parse_scmdb(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    records: list[dict] = []
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # Look for a faction code to start a new record
        if line in FACTION_CODES:
            rec = _parse_record(lines, i)
            if rec:
                records.append(rec)
                i = rec["_end_line"]
                continue
        i += 1

    return records


def _parse_record(lines: list[str], start: int) -> dict | None:
    """Parse one mission record starting at a faction code line."""
    i = start
    i += 1  # past the faction code line
    if i >= len(lines):
        return None

    # Title
    title = lines[i].strip()
    i += 1

    # Faction name
    if i >= len(lines):
        return None
    faction = lines[i].strip()
    i += 1

    # Optional "NEW" tag, skipped
    if i < len(lines) and lines[i].strip() == "NEW":
        i += 1

    # System
    if i >= len(lines):
        return None
    system = lines[i].strip()
    if system not in SYSTEMS:
        return None
    i += 1

    # Mission type
    if i >= len(lines):
        return None
    mission_type = lines[i].strip()
    i += 1

    # Collect flags and metadata until we hit "Reward"
    is_illegal = False
    is_chain = False
    is_starter = False
    is_unique = False
    awards_blueprint = False
    num_waves = ""
    num_enemies = ""
    materials = ""

    material_parts = []

    while i < len(lines):
        line = lines[i].strip()

        if line == "Reward":
            i += 1
            break
        elif line == "ILLEGAL":
            is_illegal = True
        elif line == "CHAIN":
            is_chain = True
        elif line == "STARTER":
            is_starter = True
        elif line == "UNIQUE":
            is_unique = True
        elif line.startswith("\U0001f527"):  # 🔧 Blueprint
            awards_blueprint = True
        elif line.startswith("〰"):  # 〰 waves
            m = re.search(r"(\d+(?:–\d+)?)", line)
            if m:
                num_waves = m.group(1)
        elif line.startswith("\U0001f680"):  # 🚀 enemies
            m = re.search(r"(\d+(?:–\d+)?)", line)
            if m:
                num_enemies = m.group(1)
        elif line == "\U0001f4e6":  # 📦 (items present marker)
            pass
        elif re.match(r"\d+×[A-Z]", line):  # 2×AGRI material lines
            material_parts.append(line)
        i += 1

    materials = ", ".join(material_parts) if material_parts else ""

    # Reward amount
    reward = ""
    if i < len(lines):
        reward = lines[i].strip()
        i += 1

    # "Base XP"
    if i < len(lines) and lines[i].strip() == "Base XP":
        i += 1

    # XP value
    base_xp = ""
    if i < len(lines):
        xp_raw = lines[i].strip()
        base_xp = xp_raw.replace(",", "")
        if base_xp == "—":  # em dash
            base_xp = "—"
        i += 1

    return {
        "system": system,
        "title": title,
        "faction": faction,
        "mission_type": mission_type,
        "is_illegal": is_illegal,
        "is_chain": is_chain,
        "is_starter": is_starter,
        "is_unique": is_unique,
        "materials": materials,
        "items": "",
        "routes": "",
        "awards_blueprint": awards_blueprint,
        "num_waves": num_waves,
        "num_enemies": num_enemies,
        "num_not_enemies": "",
        "base_xp": base_xp,
        "reward": reward,
        "_end_line": i,
    }


def write_csv(records: list[dict], output: Path) -> None:
    fields = [
        "system", "title", "faction", "mission_type",
        "is_illegal", "is_chain", "is_starter", "is_unique",
        "materials", "items", "routes", "awards_blueprint",
        "num_waves", "num_enemies", "num_not_enemies",
        "base_xp", "reward",
    ]
    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for rec in records:
            writer.writerow(rec)


def main():
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "tests" / "fixtures" / "temp.txt"
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else REPO / "tests" / "fixtures" / "missions_latest.csv"

    records = parse_scmdb(input_path)
    write_csv(records, output_path)
    print(f"Parsed {len(records)} records -> {output_path}")

    # Summary
    systems = {}
    types = {}
    for r in records:
        s = r["system"]
        t = r["mission_type"]
        systems[s] = systems.get(s, 0) + 1
        types[t] = types.get(t, 0) + 1
    print(f"\nBy system: {dict(sorted(systems.items()))}")
    print(f"By type: {dict(sorted(types.items()))}")
    bp_count = sum(1 for r in records if r["awards_blueprint"])
    illegal_count = sum(1 for r in records if r["is_illegal"])
    chain_count = sum(1 for r in records if r["is_chain"])
    print(f"Blueprints: {bp_count}, Illegal: {illegal_count}, Chain: {chain_count}")


if __name__ == "__main__":
    main()
