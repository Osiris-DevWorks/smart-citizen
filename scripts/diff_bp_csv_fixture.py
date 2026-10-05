"""Diff missions_4.7.177.csv fixture BP signals against 0.9.3 mission_rewards_enhancements.ini.

CSV fixture is per-variant: each row = one contract variant with its own
awards_blueprint flag. Multiple rows can share a title (different systems,
different desc_keys, different tiers).

For each unique title in the fixture, compute:
  - any_bp  = any variant awards a blueprint
  - all_bp  = every variant awards a blueprint

Expected tag:
  - all_bp  → [BP]
  - any_bp but not all → [BP?]
  - no BP at all → no tag

Compare against the tag our 0.9.3 mission_rewards_enhancements.ini writes on
the loc-key whose base value matches the title. Keys are looked up by their
*base.ini* value (stripped of any annotation) against the fixture title.
"""
from __future__ import annotations
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path


BP_RE = re.compile(r"\s*<EM4>\[BP[*?]?\]</EM4>\s*")
XP_RE = re.compile(r"\s*<EM4>\[[\d,– \-]+XP\]</EM4>\s*")
OURS_BP = re.compile(r"\[BP[*?]?\]")
BASE_TOKEN_RE = re.compile(r"~mission\([^)]*\)")
FIXTURE_TOKEN_RE = re.compile(r"\[[A-Z][A-Z ]*\]")


def parse_ini(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.rstrip("\r\n")
            if not line or line.startswith(";") or line.startswith("[") or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v
    return out


def strip_annotations(v: str) -> str:
    v = BP_RE.sub("", v)
    v = XP_RE.sub("", v)
    return v.strip()


def normalize_base_title(v: str) -> str:
    """Replace ~mission(...) tokens with a generic marker for matching."""
    return BASE_TOKEN_RE.sub("«TOK»", strip_annotations(v)).strip()


def normalize_fixture_title(v: str) -> str:
    """Replace [TOKEN] placeholders with the same marker."""
    return FIXTURE_TOKEN_RE.sub("«TOK»", v).strip()


def our_bp_tag(v: str) -> str | None:
    m = OURS_BP.search(v)
    return m.group(0) if m else None


def load_fixture(path: Path) -> dict[str, tuple[bool, bool, int]]:
    """title → (any_bp, all_bp, count)."""
    title_bp: dict[str, list[bool]] = defaultdict(list)
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            title = row["title"].strip()
            awards = row["awards_blueprint"].strip().lower() == "true"
            title_bp[title].append(awards)
    return {
        title: (any(bps), all(bps), len(bps))
        for title, bps in title_bp.items()
    }


def main() -> int:
    csv_path = Path(sys.argv[1])
    base_path = Path(sys.argv[2])
    mission_path = Path(sys.argv[3])

    fixture = load_fixture(csv_path)
    base = parse_ini(base_path)
    mission = parse_ini(mission_path)

    # Build base title → list of loc-keys. Titles are normalized so that
    # ~mission(...) template tokens match the fixture's [TOKEN] placeholders.
    # Case-insensitive on _title_/_name_/_Title_ since CIG is inconsistent.
    title_to_keys: dict[str, list[str]] = defaultdict(list)
    for k, v in base.items():
        kl = k.lower()
        if "_title_" in kl or kl.endswith("_title") or "_name_" in kl:
            title_to_keys[normalize_base_title(v)].append(k)

    missing_bp_all: list[tuple[str, int, list[str]]] = []  # fixture says [BP], we don't tag
    missing_bp_partial: list[tuple[str, int, list[str]]] = []  # fixture says [BP?], we don't tag
    no_match: list[tuple[str, int]] = []

    for title, (any_bp, all_bp, count) in fixture.items():
        if not any_bp:
            continue
        keys = title_to_keys.get(normalize_fixture_title(title), [])
        if not keys:
            no_match.append((title, count))
            continue

        # Check the mission_rewards_enhancements.ini for any of those keys
        tagged = False
        for k in keys:
            mv = mission.get(k)
            if mv is None:
                continue
            t = our_bp_tag(mv)
            if t:
                tagged = True
                break

        if not tagged:
            if all_bp:
                missing_bp_all.append((title, count, keys))
            else:
                missing_bp_partial.append((title, count, keys))

    print(f"Fixture titles with any BP: {sum(1 for _, (a, *_) in fixture.items() if a)}")
    print(f"  Missing [BP] (all variants award): {len(missing_bp_all)}")
    print(f"  Missing [BP?] (some variants award): {len(missing_bp_partial)}")
    print(f"  Fixture title not found in base.ini: {len(no_match)}")
    print()

    if missing_bp_all:
        print("=" * 80)
        print("FIXTURE: every variant awards BP — 0.9.3 is missing [BP]:")
        print("=" * 80)
        for title, n, keys in sorted(missing_bp_all):
            print(f"\n  '{title}'  ({n} variants, all award BP)")
            for k in keys:
                mv = mission.get(k, "(not in mission output)")
                print(f"    KEY {k}")
                print(f"    OUR {mv[:150]}")

    if missing_bp_partial:
        print("\n" + "=" * 80)
        print("FIXTURE: some variants award BP — 0.9.3 is missing [BP?]:")
        print("=" * 80)
        for title, n, keys in sorted(missing_bp_partial):
            print(f"\n  '{title}'  ({n} variants, some award BP)")
            for k in keys:
                mv = mission.get(k, "(not in mission output)")
                print(f"    KEY {k}")
                print(f"    OUR {mv[:150]}")

    if no_match:
        print("\n" + "=" * 80)
        print("FIXTURE: title has BP but not found in base.ini by exact match")
        print("(most likely template-placeholder titles that don't match raw loc-strings)")
        print("=" * 80)
        for title, n in sorted(no_match):
            print(f"  ({n}x)  '{title}'")

    return 0


if __name__ == "__main__":
    sys.exit(main())
