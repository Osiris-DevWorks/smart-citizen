"""Compare the kraken_4.7.ini ground-truth fixture against our generated
mission_rewards_enhancements.ini output, focusing on blueprint list deltas.

Usage:
    python scripts/compare_kraken_fixture.py [fixture_path] [ours_path]

Defaults:
    fixture_path = tests/fixtures/kraken_4.7.ini
    ours_path    = %USERPROFILE%/OneDrive/Documents/Smart Citizen/cache/mission_rewards_enhancements.ini

Prints a summary report to stdout. Research/reporting only; makes no changes.
"""
from __future__ import annotations

import io
import os
import re
import sys
from pathlib import Path

# Make stdout UTF-8-safe on Windows consoles (cp1252 chokes on smart quotes etc.)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

# --- Config ---------------------------------------------------------------

DEFAULT_FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "kraken_4.7.ini"
DEFAULT_OURS = Path(os.path.expanduser("~")) / "OneDrive" / "Documents" / "Smart Citizen" / "cache" / "mission_rewards_enhancements.ini"

# The ground-truth fixture uses EM4 "Potential Blueprints" (title case).
# Our output uses EM3 "POTENTIAL BLUEPRINTS" (all caps).
# Accept either form when locating the blueprints section, case-insensitively.
BLUEPRINTS_HEADER_RE = re.compile(
    r"<EM[34]>\s*potential blueprints\s*</EM[34]>", re.IGNORECASE
)

# Regional subheader:
#   Fixture form:   <EM4>[Regional Variants] example locations: Nyx, ...</EM4>
#   Our form:       <EM4>[Stanton]</EM4>  /  <EM4>[Pyro]</EM4>  (bare system)
# Accept either so our per-system output counts as "regional" in the report.
_SYS = r"(?:Stanton|Pyro|Nyx|ArcCorp|Crusader|Desert)(?:/(?:Stanton|Pyro|Nyx|ArcCorp|Crusader|Desert))*"
_SYS_WITH_REGION = rf"{_SYS}(?:\s+Region[A-Z][0-9]*)?"
REGIONAL_HEADER_RE = re.compile(
    rf"<EM[34]>\s*\[(?:Regional Variants\][^<]*|{_SYS_WITH_REGION}(?:,\s*{_SYS_WITH_REGION})*\]\s*)</EM[34]>",
    re.IGNORECASE,
)


# --- Parsing --------------------------------------------------------------

def parse_ini(path: Path) -> dict[str, str]:
    """Parse an INI-style file as key=value, splitting on first '=' only.

    Blank lines and lines without '=' are skipped. Strips UTF-8 BOM if present.
    """
    result: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if not line:
                continue
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            # Strip any stray BOM just in case (utf-8-sig only handles leading one)
            result[key.strip().lstrip("\ufeff")] = val
    return result


def extract_blueprint_section(value: str) -> str | None:
    """Return everything from the Potential Blueprints header onward, or None."""
    m = BLUEPRINTS_HEADER_RE.search(value)
    if not m:
        return None
    return value[m.end():]


def split_sublines(text: str) -> list[str]:
    """Split a value on literal ``\\n`` sequences into sub-lines."""
    # Literal two-character sequence backslash + n, not a real newline.
    return text.split("\\n")


def extract_blueprint_sets(value: str) -> tuple[list[tuple[str, set[str]]], bool]:
    """Extract blueprint sets from a value.

    Returns (regions, has_regional) where regions is a list of
    (region_label, items_set). If no regional headers are present, the
    list contains a single entry with label "__flat__". has_regional is
    True iff at least one regional subheader was found.
    """
    section = extract_blueprint_section(value)
    if section is None:
        return ([], False)

    sublines = split_sublines(section)

    regions: list[tuple[str, set[str]]] = []
    current_label: str = "__flat__"
    current_items: set[str] = set()
    has_regional = False

    def flush() -> None:
        # Only record non-empty regions, OR the implicit flat region even if
        # empty (so callers can distinguish "no blueprints section" from
        # "blueprints section with no bullets").
        if current_items or current_label != "__flat__" or not regions:
            regions.append((current_label, set(current_items)))

    for raw in sublines:
        sub = raw.strip()
        if not sub:
            continue

        reg_m = REGIONAL_HEADER_RE.search(sub)
        if reg_m:
            has_regional = True
            # If we've been accumulating under __flat__ or previous region, flush.
            if current_items or current_label != "__flat__":
                regions.append((current_label, set(current_items)))
            current_label = sub
            current_items = set()
            continue

        if sub.startswith("- "):
            item = sub[2:].strip()
            if item:
                current_items.add(item)
            continue
        # Any other line terminates the blueprint section.
        # (e.g. another EM block after the list.) Stop collecting.
        # But the fixture only has blueprints as the tail, so in practice
        # we keep going; we just don't record non-bullet lines.

    # Final flush
    if has_regional:
        regions.append((current_label, set(current_items)))
    else:
        regions.append(("__flat__", set(current_items)))

    # Remove accidental duplicate empty trailing flush if any
    seen_labels: set[str] = set()
    unique_regions: list[tuple[str, set[str]]] = []
    for lbl, items in regions:
        if lbl in seen_labels:
            continue
        seen_labels.add(lbl)
        unique_regions.append((lbl, items))

    return (unique_regions, has_regional)


def union_of_regions(regions: list[tuple[str, set[str]]]) -> set[str]:
    out: set[str] = set()
    for _, items in regions:
        out |= items
    return out


# --- Report ---------------------------------------------------------------

def format_item_list(items: set[str], indent: str = "    ") -> str:
    if not items:
        return f"{indent}(none)"
    return "\n".join(f"{indent}- {it}" for it in sorted(items))


def main(argv: list[str]) -> int:
    fixture_path = Path(argv[1]) if len(argv) > 1 else DEFAULT_FIXTURE
    ours_path = Path(argv[2]) if len(argv) > 2 else DEFAULT_OURS

    print(f"Fixture:  {fixture_path}")
    print(f"Our file: {ours_path}")
    print()

    if not fixture_path.exists():
        print(f"ERROR: fixture not found: {fixture_path}", file=sys.stderr)
        return 2
    if not ours_path.exists():
        print(f"ERROR: our output not found: {ours_path}", file=sys.stderr)
        return 2

    fixture = parse_ini(fixture_path)
    ours = parse_ini(ours_path)

    print(f"Fixture keys:  {len(fixture)}")
    print(f"Our file keys: {len(ours)}")
    print()

    missing_keys: list[str] = []
    matching_keys: list[str] = []
    differing: list[dict] = []
    regional_vs_flat: list[str] = []  # fixture has regions, ours is flat

    for key, fval in fixture.items():
        if key not in ours:
            missing_keys.append(key)
            continue

        oval = ours[key]

        f_regions, f_has_regional = extract_blueprint_sets(fval)
        o_regions, o_has_regional = extract_blueprint_sets(oval)

        f_union = union_of_regions(f_regions)
        o_union = union_of_regions(o_regions)

        only_fixture = f_union - o_union
        only_ours = o_union - f_union

        flag_regional_gap = f_has_regional and not o_has_regional
        if flag_regional_gap:
            regional_vs_flat.append(key)

        if not only_fixture and not only_ours and not flag_regional_gap:
            matching_keys.append(key)
            continue

        differing.append({
            "key": key,
            "only_fixture": only_fixture,
            "only_ours": only_ours,
            "fixture_has_regional": f_has_regional,
            "ours_has_regional": o_has_regional,
            "fixture_regions": f_regions,
            "ours_regions": o_regions,
        })

    # --- Print report -----------------------------------------------------

    print("=" * 72)
    print("SUMMARY")
    print("=" * 72)
    print(f"Total fixture keys:                      {len(fixture)}")
    print(f"Keys missing from our output:            {len(missing_keys)}")
    print(f"Keys with matching blueprint sets:       {len(matching_keys)}")
    print(f"Keys with differing blueprint sets:      {len(differing)}")
    print("Keys where fixture has regional variants")
    print(f"  but our output is a single flat list:  {len(regional_vs_flat)}")
    print()

    if missing_keys:
        print("-" * 72)
        print(f"MISSING FROM OUR OUTPUT ({len(missing_keys)})")
        print("-" * 72)
        for k in missing_keys:
            print(f"  {k}")
        print()

    if regional_vs_flat:
        print("-" * 72)
        print(f"FIXTURE HAS REGIONAL VARIANTS, OURS IS FLAT ({len(regional_vs_flat)})")
        print("-" * 72)
        for k in regional_vs_flat:
            print(f"  {k}")
        print()

    if differing:
        print("-" * 72)
        print(f"DIFFERING BLUEPRINT SETS ({len(differing)})")
        print("-" * 72)
        for d in differing:
            print()
            print(f"KEY: {d['key']}")
            print(f"  fixture has regional variants: {d['fixture_has_regional']}")
            print(f"  ours has regional variants:    {d['ours_has_regional']}")
            if d['fixture_has_regional']:
                print("  fixture region labels:")
                for lbl, items in d['fixture_regions']:
                    print(f"    * {lbl}  ({len(items)} items)")
            if d['only_fixture']:
                print(f"  only in fixture ({len(d['only_fixture'])}):")
                print(format_item_list(d['only_fixture'], indent="    "))
            if d['only_ours']:
                print(f"  only in ours ({len(d['only_ours'])}):")
                print(format_item_list(d['only_ours'], indent="    "))
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
