"""
Mission enhancements tests for SC Localization Editor v0.8.0

Tests cover:
- Generating global.ini from mission enhancements via the merge pipeline
- Validating that generated INI mission data aligns with the missions CSV fixture
- Structural validation of mission title XP tags and desc stats blocks
"""

import csv
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from merger.ini_merger import merge_sources_by_hierarchy, merge_ini_files
from parser.ini_parser import parse_ini_file

FIXTURES_DIR = Path(__file__).parent / "fixtures"
ENHANCEMENTS_INI = FIXTURES_DIR / "mission_rewards_enhancements.ini"
MISSIONS_CSV = FIXTURES_DIR / "missions_4.7.177.csv"

# Regex patterns for extracting data from INI values.
# Labels may be wrapped in <EM4>...</EM4> (blue styling) per the annotation
# paradigm — patterns must tolerate both wrapped and bare forms.
XP_TAG_RE = re.compile(r"(?:<EM4>)?\[(\d[\d,]*(?:[–\-]\d[\d,]*)?)\s*XP\](?:</EM4>)?\s*$")
REP_XP_RE = re.compile(r"(?:<EM4>)?Reputation XP:(?:</EM4>)?\s*\+([\d,]+)")


def _load_csv_missions():
    """Load the missions CSV fixture into a list of dicts."""
    with open(MISSIONS_CSV, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _parse_enhancements():
    """Parse enhancements INI into separate title and desc dicts.

    Returns:
        (titles, descs) where each maps INI key -> value
    """
    data = parse_ini_file(ENHANCEMENTS_INI)
    titles = {k: v for k, v in data.items() if "_Title_" in k}
    descs = {k: v for k, v in data.items() if "_Desc_" in k}
    return titles, descs


def _strip_xp_tag(title_value):
    """Strip the [N XP] suffix from a title value, returning (clean_title, xp_str|None)."""
    m = XP_TAG_RE.search(title_value)
    if m:
        clean = title_value[: m.start()].rstrip()
        return clean, m.group(1)
    return title_value.strip(), None


def _extract_desc_stats(desc_value):
    """Extract reputation XP from a desc value's stats block.

    Returns:
        rep_xp_str|None — raw formatted string like '32,000'
    """
    xp_match = REP_XP_RE.search(desc_value)
    return xp_match.group(1) if xp_match else None


def _key_prefix(key):
    """Get the key prefix before _Title_ or _Desc_ for pairing."""
    for marker in ("_Title_", "_Desc_"):
        if marker in key:
            return key[: key.index(marker)]
    return key


@pytest.fixture
def generated_global_ini(tmp_path):
    """Generate a global.ini in a temp directory using the merge pipeline.

    Creates a base.ini from the enhancements keys (with placeholder values),
    then merges the enhancements over it — exactly as the app would.
    """
    enhancements_data = parse_ini_file(ENHANCEMENTS_INI)

    # Build a minimal base with placeholder values for every key
    base_data = {k: f"[base] {k}" for k in enhancements_data}

    # Merge: base (low priority) → enhancements (high priority)
    merged = merge_sources_by_hierarchy(
        {"global": base_data, "enhancements": enhancements_data},
        ["global", "enhancements"],
    )

    # Write base.ini so merge_ini_files has a source to read line-by-line
    base_ini = tmp_path / "base.ini"
    with open(base_ini, "w", encoding="utf-8") as f:
        for key, value in base_data.items():
            f.write(f"{key}={value}\n")

    # Generate the final global.ini via the file-level merge
    output_ini = tmp_path / "global.ini"
    merge_ini_files(str(base_ini), merged, str(output_ini))

    return output_ini


class TestMissionGlobalIniGeneration:
    """Test that the merge pipeline produces a valid global.ini from mission enhancements."""

    def test_global_ini_created(self, generated_global_ini):
        """The merge pipeline should produce a non-empty global.ini."""
        assert generated_global_ini.exists()
        assert generated_global_ini.stat().st_size > 0

    def test_global_ini_has_all_enhancement_keys(self, generated_global_ini):
        """Every key from the enhancements INI should appear in the generated global.ini."""
        enhancements_data = parse_ini_file(ENHANCEMENTS_INI)
        global_data = parse_ini_file(generated_global_ini)

        missing = set(enhancements_data.keys()) - set(global_data.keys())
        assert not missing, f"{len(missing)} enhancement keys missing from global.ini: {list(missing)[:5]}"

    def test_enhancements_overwrite_base(self, generated_global_ini):
        """Enhancement values should overwrite the base placeholders."""
        enhancements_data = parse_ini_file(ENHANCEMENTS_INI)
        global_data = parse_ini_file(generated_global_ini)

        for key, expected in enhancements_data.items():
            assert global_data[key] == expected, (
                f"Key {key}: expected enhancement value, got base placeholder"
            )


class TestMissionTitleStructure:
    """Validate structural properties of mission title entries."""

    def test_title_entries_exist(self):
        """The enhancements INI should contain title entries."""
        titles, _ = _parse_enhancements()
        assert len(titles) > 0, "No _Title_ entries found in enhancements INI"

    def test_title_xp_tags_are_numeric(self):
        """Every [XP] tag in a title should contain a valid number or range."""
        titles, _ = _parse_enhancements()
        for key, value in titles.items():
            m = XP_TAG_RE.search(value)
            if m:
                xp_str = m.group(1).replace(",", "")
                # Could be a single number or a range like "100–500"
                parts = re.split(r"[–\-]", xp_str)
                for part in parts:
                    assert part.isdigit(), (
                        f"Non-numeric XP in title {key}: '{m.group(1)}'"
                    )

    def test_title_descs_paired(self):
        """Every title key should have a corresponding desc key (same prefix)."""
        titles, descs = _parse_enhancements()
        desc_prefixes = {_key_prefix(k) for k in descs}
        title_prefixes = {_key_prefix(k) for k in titles}

        unpaired = title_prefixes - desc_prefixes
        # Allow some unpaired (game data may have title-only entries)
        unpaired_ratio = len(unpaired) / len(title_prefixes) if title_prefixes else 0
        assert unpaired_ratio < 0.15, (
            f"{len(unpaired)}/{len(title_prefixes)} title prefixes have no matching desc "
            f"({unpaired_ratio:.0%}): {list(unpaired)[:5]}"
        )


class TestMissionDescStructure:
    """Validate structural properties of mission desc entries."""

    def test_desc_entries_exist(self):
        """The enhancements INI should contain desc entries."""
        _, descs = _parse_enhancements()
        assert len(descs) > 0, "No _Desc_ entries found in enhancements INI"

    def test_stats_block_format(self):
        """Desc entries with stats should use the MISSION DETAILS separator.

        The canonical header is '<EM3>MISSION DETAILS</EM3>'. Older fixtures
        may still contain '== Mission Details ==' or '== Stats =='.
        """
        _, descs = _parse_enhancements()
        markers = (
            "<EM3>MISSION DETAILS</EM3>",
            "== Mission Details ==",
            "== Stats ==",
        )
        stats_count = 0
        for key, value in descs.items():
            if not any(m in value for m in markers):
                continue
            stats_count += 1
            for marker in markers:
                if marker in value:
                    stats_section = value[value.index(marker):]
                    break
            # At least one recognizable line: stats (Reputation XP, Tier XP),
            # flags (Mission Type), or encounter data (Hostiles / Friendlies /
            # Objectives — the player-facing buckets; the internal Unknown
            # bucket is no longer rendered, see #187).
            has_content = (
                "Reputation XP" in stats_section
                or "Tier" in stats_section
                or "Mission Type:" in stats_section
                or "Hostiles:" in stats_section
                or "Friendlies:" in stats_section
                or "Objectives:" in stats_section
            )
            assert has_content, (
                f"Stats block in {key} has no recognizable content"
            )
        assert stats_count > 0, "No desc entries contain stats blocks"

    def test_reputation_xp_format(self):
        """Reputation XP values should be properly formatted positive numbers."""
        _, descs = _parse_enhancements()
        for key, value in descs.items():
            m = REP_XP_RE.search(value)
            if m:
                raw = m.group(1).replace(",", "")
                assert raw.isdigit(), f"Non-numeric Rep XP in {key}: '{m.group(1)}'"
                assert int(raw) > 0, f"Zero/negative Rep XP in {key}"


class TestMissionCsvAlignment:
    """Validate that the generated global.ini mission data aligns with the CSV fixture."""

    def test_csv_fixture_loads(self):
        """The missions CSV fixture should load with expected columns."""
        rows = _load_csv_missions()
        assert len(rows) == 1288, f"Expected 1288 CSV rows, got {len(rows)}"
        expected_cols = {
            "system", "title", "faction", "mission_type",
            "base_xp", "reward",
        }
        assert expected_cols.issubset(rows[0].keys()), (
            f"Missing CSV columns: {expected_cols - rows[0].keys()}"
        )

    def test_ini_xp_values_found_in_csv(self):
        """XP values from INI title tags should all appear in the CSV base_xp column."""
        titles, _ = _parse_enhancements()
        csv_rows = _load_csv_missions()

        # Build set of all XP values from the CSV (normalize: strip commas)
        csv_xp_values = set()
        for row in csv_rows:
            xp = row["base_xp"].strip()
            if xp and xp != "—":
                csv_xp_values.add(xp.replace(",", ""))

        # Check that INI XP values are a subset of CSV XP values
        ini_xp_values = set()
        for key, value in titles.items():
            _, xp_str = _strip_xp_tag(value)
            if xp_str:
                # Handle ranges — take each endpoint
                parts = re.split(r"[–\-]", xp_str.replace(",", ""))
                ini_xp_values.update(parts)

        unmatched = ini_xp_values - csv_xp_values
        # Allow small discrepancy (range endpoints may not all appear individually)
        assert len(unmatched) <= len(ini_xp_values) * 0.15, (
            f"Too many INI XP values not found in CSV: {unmatched}"
        )

    def test_csv_xp_coverage_in_ini(self):
        """CSV missions with base XP should have corresponding XP tags in the INI."""
        titles, _ = _parse_enhancements()
        csv_rows = _load_csv_missions()

        # Build set of all XP values from INI titles
        ini_xp_values = set()
        for key, value in titles.items():
            _, xp_str = _strip_xp_tag(value)
            if xp_str:
                ini_xp_values.add(xp_str.replace(",", ""))

        # Check CSV base_xp values appear in INI
        csv_with_xp = [
            row for row in csv_rows
            if row["base_xp"].strip() and row["base_xp"].strip() != "—"
        ]
        matched = 0
        for row in csv_with_xp:
            normalized = row["base_xp"].strip().replace(",", "")
            if normalized in ini_xp_values:
                matched += 1

        coverage = matched / len(csv_with_xp) if csv_with_xp else 0
        assert coverage > 0.5, (
            f"Only {coverage:.0%} of CSV XP values found in INI "
            f"({matched}/{len(csv_with_xp)})"
        )

    def test_title_xp_matches_desc_xp(self):
        """When a title has [N XP] and its desc has Reputation XP, they should be consistent."""
        titles, descs = _parse_enhancements()

        mismatches = []
        for title_key, title_value in titles.items():
            _, title_xp = _strip_xp_tag(title_value)
            if not title_xp:
                continue
            # Skip range XP tags — can't compare directly
            if "–" in title_xp or "-" in title_xp:
                continue

            prefix = _key_prefix(title_key)
            # Find matching desc suffix (Title_001 → Desc_001)
            suffix = title_key[title_key.index("_Title_"):]
            desc_key_candidate = prefix + suffix.replace("_Title_", "_Desc_")

            if desc_key_candidate in descs:
                desc_xp = _extract_desc_stats(descs[desc_key_candidate])
                if desc_xp:
                    title_xp_norm = title_xp.replace(",", "")
                    desc_xp_norm = desc_xp.replace(",", "")
                    if title_xp_norm != desc_xp_norm:
                        mismatches.append(
                            f"{title_key}: title=[{title_xp} XP] vs desc=+{desc_xp}"
                        )

        assert len(mismatches) <= 5, (
            f"{len(mismatches)} title/desc XP mismatches:\n" +
            "\n".join(mismatches[:10])
        )
