"""Compare mission fixture CSVs and Kraken's contracts.ini against our output.

Usage:
    python scripts/diff_mission_fixtures.py [--old FILE] [--new FILE] [--kraken FILE]

Defaults:
    --old    tests/fixtures/missions_4.7.177.csv
    --new    tests/fixtures/missions_latest.csv
    --kraken tests/fixtures/kraken_contracts_latest.ini
"""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def load_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_kraken(path: Path) -> dict[str, str]:
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith(";"):
            key, _, val = line.partition("=")
            out[key.strip()] = val.strip()
    return out


def csv_title_set(records: list[dict]) -> set[str]:
    return {r["title"] for r in records}


def csv_by_title_system(records: list[dict]) -> dict[tuple[str, str], dict]:
    out = {}
    for r in records:
        key = (r["title"], r["system"])
        out[key] = r
    return out


def diff_fixtures(old_path: Path, new_path: Path):
    old = load_csv(old_path)
    new = load_csv(new_path)

    old_titles = csv_title_set(old)
    new_titles = csv_title_set(new)

    added = sorted(new_titles - old_titles)
    removed = sorted(old_titles - new_titles)

    old_by_key = csv_by_title_system(old)
    new_by_key = csv_by_title_system(new)

    common_keys = set(old_by_key.keys()) & set(new_by_key.keys())
    changed = []
    for key in sorted(common_keys):
        o, n = old_by_key[key], new_by_key[key]
        diffs = []
        for field in ["faction", "mission_type", "is_illegal", "is_chain",
                       "awards_blueprint", "base_xp", "reward"]:
            ov, nv = str(o.get(field, "")), str(n.get(field, ""))
            if ov != nv:
                diffs.append(f"  {field}: {ov!r} -> {nv!r}")
        if diffs:
            changed.append((key, diffs))

    print(f"=== Fixture Diff: {old_path.name} vs {new_path.name} ===")
    print(f"Old: {len(old)} records, New: {len(new)} records")
    print(f"\nAdded titles ({len(added)}):")
    for t in added[:30]:
        print(f"  + {t}")
    if len(added) > 30:
        print(f"  ... and {len(added) - 30} more")

    print(f"\nRemoved titles ({len(removed)}):")
    for t in removed[:30]:
        print(f"  - {t}")
    if len(removed) > 30:
        print(f"  ... and {len(removed) - 30} more")

    print(f"\nChanged fields ({len(changed)} mission variants):")
    for (title, system), diffs in changed[:20]:
        print(f"  [{system}] {title}")
        for d in diffs:
            print(f"    {d}")
    if len(changed) > 20:
        print(f"  ... and {len(changed) - 20} more")


def compare_kraken(new_csv_path: Path, kraken_path: Path):
    """Compare our generated output against Kraken's contracts.ini."""
    new_records = load_csv(new_csv_path)
    kraken = load_kraken(kraken_path)

    print("\n=== Kraken Comparison ===")
    print(f"Our missions: {len(new_records)} records")
    print(f"Kraken entries: {len(kraken)} loc keys")

    # Kraken's file has loc keys (like desc keys). We can check:
    # 1. How many of our mission titles appear referenced in Kraken's data
    # 2. Kraken entries that don't appear in our data

    # Extract title-like patterns from Kraken keys
    kraken_title_keys = {k for k in kraken if "_title" in k.lower() or "_name" in k.lower()}
    kraken_desc_keys = {k for k in kraken if "_desc" in k.lower() or "_description" in k.lower()}

    print(f"Kraken title keys: {len(kraken_title_keys)}")
    print(f"Kraken desc keys: {len(kraken_desc_keys)}")

    # Check for mission details content in Kraken
    missions_with_details = sum(1 for v in kraken.values() if "MISSION DETAILS" in v)
    missions_with_bp = sum(1 for v in kraken.values() if "POTENTIAL BLUEPRINTS" in v)
    missions_with_rep = sum(1 for v in kraken.values() if "Reputation XP" in v or "Tier " in v)

    print("\nKraken content analysis:")
    print(f"  Entries with MISSION DETAILS: {missions_with_details}")
    print(f"  Entries with POTENTIAL BLUEPRINTS: {missions_with_bp}")
    print(f"  Entries with rep tier info: {missions_with_rep}")

    # Check for rank names vs Tier N in Kraken
    rank_name_pattern = re.compile(
        r"<EM4>(Rookie|Junior|Member|Experienced|Senior|Master|Trainee|"
        r"Applicant|Jr\.|Sr\.|Runner|Tracker|Salvager|Scavenger|"
        r"Contractor|Responder|Pilot|Racer|Assassin)"
    )
    tier_pattern = re.compile(r"<EM4>Tier \d+:")

    kraken_with_rank_names = sum(1 for v in kraken.values() if rank_name_pattern.search(v))
    kraken_with_tier_n = sum(1 for v in kraken.values() if tier_pattern.search(v))
    print(f"  Entries with rank names: {kraken_with_rank_names}")
    print(f"  Entries with 'Tier N': {kraken_with_tier_n}")


def main():
    parser = argparse.ArgumentParser(description="Compare mission fixtures")
    parser.add_argument("--old", default=str(REPO / "tests/fixtures/missions_4.7.177.csv"))
    parser.add_argument("--new", default=str(REPO / "tests/fixtures/missions_latest.csv"))
    parser.add_argument("--kraken", default=str(REPO / "tests/fixtures/kraken_contracts_latest.ini"))
    args = parser.parse_args()

    diff_fixtures(Path(args.old), Path(args.new))

    kraken_path = Path(args.kraken)
    if kraken_path.exists():
        compare_kraken(Path(args.new), kraken_path)


if __name__ == "__main__":
    main()
