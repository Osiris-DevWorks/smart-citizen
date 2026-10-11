"""Diff cached mission_rewards_enhancements.ini between two SC channels.

Surfaces missions that newly got blueprint annotations (`[BP]` / `[BP?]`
tags on titles + structured *POTENTIAL BLUEPRINTS* / *ITEM REWARDS*
blocks in descriptions) when comparing PTU against LIVE — so you can
quickly see what new BP-paying mission families CIG added in a patch
without re-eyeballing 2500+ entries.

Usage:
    python scripts/diff_mission_rewards_channels.py LIVE PTU
    python scripts/diff_mission_rewards_channels.py LIVE PTU --out diff.md
    python scripts/diff_mission_rewards_channels.py LIVE PTU --full

Categorises by mission family (the loc-key prefix up to the first
underscore — e.g. `BountyHuntersGuild_*`, `CFP_*`, `GoblinG_*`,
`Refuel_*`, etc.) so the report groups related changes together.

Reads from ``Documents\\Smart Citizen\\<channel>\\cache\\mission_rewards_enhancements.ini``;
override with ``--user-data`` for a redirected Documents folder.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from pathlib import Path


# Match `[BP]` or `[BP?]` anywhere in a title value. Both indicate the
# mission awards (or might award) a blueprint pool from the contract
# generator's BlueprintMissionPool refs. See scan_contract_generators
# in generate_enhancements_ini.py for the assignment logic.
_BP_TAG_RE = re.compile(r"<EM4>\[BP\??\]</EM4>")

# Title vs description vs other key — derive from the loc-key suffix.
# Mission output is keyed on title+desc loc-keys; we focus on titles
# because that's where the [BP] tag actually lives.
_TITLE_SUFFIX_RE = re.compile(r"_title(?:_\d+|$)|_Title$", re.IGNORECASE)


def parse_mission_ini(path: Path) -> dict[str, str]:
    """Parse a mission_rewards_enhancements.ini into key→value dict."""
    out: dict[str, str] = {}
    if not path.exists():
        raise FileNotFoundError(f"Mission file not found: {path}")
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.rstrip("\r\n")
            if not line or line.startswith((";", "#")):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v
    return out


def is_title_key(key: str) -> bool:
    return bool(_TITLE_SUFFIX_RE.search(key))


def has_bp_tag(value: str) -> bool:
    return bool(_BP_TAG_RE.search(value))


def mission_family(key: str) -> str:
    """Group missions by the loc-key prefix up to the first underscore.

    Examples:
        BountyHuntersGuild_FPS_Nyx_title_001 → BountyHuntersGuild
        CFP_Salvage_FPS_title_001            → CFP
        Refuel_Cargo_title_001               → Refuel
        bhg_bounty_title_gen_001             → bhg
    """
    return key.split("_", 1)[0] if "_" in key else key


def default_user_data_root() -> Path:
    return Path(os.environ.get("USERPROFILE", "~")).expanduser() / "Documents" / "Smart Citizen"


def mission_ini_path(user_data_root: Path, channel: str) -> Path:
    return user_data_root / channel / "cache" / "mission_rewards_enhancements.ini"


def write_report(
    out_lines: list[str],
    a_label: str,
    b_label: str,
    a: dict[str, str],
    b: dict[str, str],
    *,
    full: bool,
) -> None:
    a_keys = set(a.keys())
    b_keys = set(b.keys())

    # Brand-new keys: present in B (e.g. PTU) but not A (e.g. LIVE)
    new_keys = b_keys - a_keys
    # Removed keys (less interesting for "what's new" but worth noting)
    removed_keys = a_keys - b_keys
    # Common keys with diverged values — focus on BP tag changes
    common_keys = a_keys & b_keys

    # Bucket: new BP-tagged titles (BP appeared in B that wasn't in A)
    newly_bp: list[tuple[str, str]] = []
    for k in common_keys:
        if not is_title_key(k):
            continue
        a_bp = has_bp_tag(a[k])
        b_bp = has_bp_tag(b[k])
        if b_bp and not a_bp:
            newly_bp.append((k, b[k]))
    newly_bp.sort()

    # Bucket: BP tags that disappeared (regressions / loot-table edits)
    lost_bp: list[tuple[str, str]] = []
    for k in common_keys:
        if not is_title_key(k):
            continue
        if has_bp_tag(a[k]) and not has_bp_tag(b[k]):
            lost_bp.append((k, b[k]))
    lost_bp.sort()

    # Bucket: brand-new missions, split by whether the title carries a BP tag
    new_titles_with_bp: list[tuple[str, str]] = []
    new_titles_no_bp: list[tuple[str, str]] = []
    for k in sorted(new_keys):
        if not is_title_key(k):
            continue
        if has_bp_tag(b[k]):
            new_titles_with_bp.append((k, b[k]))
        else:
            new_titles_no_bp.append((k, b[k]))

    # ── Header ────────────────────────────────────────────────────────────
    out_lines.append(f"# Mission rewards diff: {a_label} → {b_label}")
    out_lines.append("")
    out_lines.append(f"- {a_label} keys: {len(a_keys):,}")
    out_lines.append(f"- {b_label} keys: {len(b_keys):,}")
    out_lines.append(f"- New keys in {b_label}: {len(new_keys):,}")
    out_lines.append(f"- Removed in {b_label}: {len(removed_keys):,}")
    out_lines.append("")

    # ── Newly BP-tagged (most actionable section) ─────────────────────────
    out_lines.append(f"## Newly BP-tagged titles ({len(newly_bp)})")
    out_lines.append("")
    out_lines.append("Missions present in BOTH channels whose title gained a `[BP]` / `[BP?]` tag")
    out_lines.append(f"in {b_label} that wasn't there in {a_label}. CIG added these missions to a")
    out_lines.append("blueprint reward pool in this patch.")
    out_lines.append("")
    if newly_bp:
        for fam, items in _group_by_family(newly_bp).items():
            out_lines.append(f"### {fam} ({len(items)})")
            for k, v in items:
                out_lines.append(f"- `{k}` — {_strip_html(v)[:120]}")
            out_lines.append("")
    else:
        out_lines.append("_(none — no missions gained a BP tag between channels)_")
        out_lines.append("")

    # ── New mission titles WITH BP (also actionable) ──────────────────────
    out_lines.append(f"## Brand-new mission titles WITH BP tag ({len(new_titles_with_bp)})")
    out_lines.append("")
    out_lines.append(f"Mission keys that don't exist in {a_label} at all and arrive in {b_label}")
    out_lines.append("with a `[BP]` / `[BP?]` tag — entirely new BP-paying missions.")
    out_lines.append("")
    if new_titles_with_bp:
        for fam, items in _group_by_family(new_titles_with_bp).items():
            out_lines.append(f"### {fam} ({len(items)})")
            for k, v in items:
                out_lines.append(f"- `{k}` — {_strip_html(v)[:120]}")
            out_lines.append("")
    else:
        out_lines.append("_(none)_")
        out_lines.append("")

    # ── New mission titles WITHOUT BP ─────────────────────────────────────
    out_lines.append(f"## Brand-new mission titles without BP tag ({len(new_titles_no_bp)})")
    out_lines.append("")
    if full and new_titles_no_bp:
        for fam, items in _group_by_family(new_titles_no_bp).items():
            out_lines.append(f"### {fam} ({len(items)})")
            for k, v in items:
                out_lines.append(f"- `{k}` — {_strip_html(v)[:120]}")
            out_lines.append("")
    else:
        out_lines.append(
            f"_({len(new_titles_no_bp)} titles — pass `--full` to list them)_"
            if new_titles_no_bp else "_(none)_"
        )
        out_lines.append("")

    # ── Lost BP tags (regression watch) ───────────────────────────────────
    out_lines.append(f"## BP tags removed from titles ({len(lost_bp)})")
    out_lines.append("")
    if lost_bp:
        out_lines.append(
            f"Titles that had `[BP]` / `[BP?]` in {a_label} and lost it in {b_label}. "
            "Could be a loot-table change or a regression in the contract generator data."
        )
        out_lines.append("")
        for fam, items in _group_by_family(lost_bp).items():
            out_lines.append(f"### {fam} ({len(items)})")
            for k, v in items:
                out_lines.append(f"- `{k}` — {_strip_html(v)[:120]}")
            out_lines.append("")
    else:
        out_lines.append("_(none — no regressions between channels)_")
        out_lines.append("")


def _group_by_family(pairs: list[tuple[str, str]]) -> dict[str, list[tuple[str, str]]]:
    """Group (key, value) pairs by mission_family(key), preserving sort order."""
    grouped: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for k, v in pairs:
        grouped[mission_family(k)].append((k, v))
    # Return families sorted alphabetically.
    return dict(sorted(grouped.items()))


def _strip_html(s: str) -> str:
    """Strip the EM3/EM4 styling tags so report lines stay readable."""
    return re.sub(r"<[^>]+>", "", s).strip()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("a", help="Channel A (e.g. LIVE)")
    p.add_argument("b", help="Channel B (e.g. PTU) — focus is on what's new in B")
    p.add_argument("--user-data", help="Override the user data root", default=None)
    p.add_argument("--out", help="Write report to file instead of stdout", default=None)
    p.add_argument("--full", action="store_true", help="Include the no-BP new-titles list verbatim")
    args = p.parse_args()

    user_data_root = Path(args.user_data) if args.user_data else default_user_data_root()
    a_path = mission_ini_path(user_data_root, args.a)
    b_path = mission_ini_path(user_data_root, args.b)

    a = parse_mission_ini(a_path)
    b = parse_mission_ini(b_path)

    out_lines: list[str] = []
    write_report(out_lines, args.a, args.b, a, b, full=args.full)

    text = "\n".join(out_lines) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"Wrote report: {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
