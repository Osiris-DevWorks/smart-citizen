"""Export/import owned blueprints as JSON or CSV.

Qt-free -- covers format shape, name-matching, and malformed-file handling.
The GUI wiring (file dialogs, QMessageBox summaries) lives in
blueprint_tracker_tab.py and is manual-test only here. Some QFileDialog-
driven features in this codebase (see test_settings_profile.py,
test_restore_backup.py) do monkeypatch the dialog to unit-test their wiring
directly -- that pattern was skipped here since GUI wiring is exempt per
test_coverage_check.md, but it's a real option for a future pass if the
extension-detection logic in _export_owned_blueprints grows more branches.
"""
from __future__ import annotations

import csv
import io
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.blueprint_export import (  # noqa: E402
    InvalidImportFileError,
    export_owned_blueprints_csv,
    export_owned_blueprints_json,
    match_import_names,
    parse_import_names,
)

pytestmark = pytest.mark.unit


@dataclass
class _Item:
    tagged_name: str = ""
    type: str = "Other"


class TestExportJson:
    def test_shape_matches_scmdb_top_level_fields(self):
        payload = json.loads(export_owned_blueprints_json({"Norfield"}, {}))
        assert set(payload.keys()) == {"version", "exportedAt", "missions", "blueprints"}
        assert payload["missions"] == []
        assert payload["version"] == 1

    def test_blueprint_entries_have_no_tag_or_url(self):
        """Deliberate: Smart Citizen has no real SCMDB tag/url, so those
        fields are omitted rather than faked (see module docstring)."""
        payload = json.loads(export_owned_blueprints_json({"Norfield"}, {}))
        entry = payload["blueprints"][0]
        assert set(entry.keys()) == {"name", "completed", "favorite"}
        assert entry["completed"] is True
        assert entry["favorite"] is False

    def test_prefers_tagged_name_over_bare_key(self):
        meta = {"Norfield": _Item(tagged_name="[FN] Norfield")}
        payload = json.loads(export_owned_blueprints_json({"Norfield"}, meta))
        assert payload["blueprints"][0]["name"] == "[FN] Norfield"

    def test_falls_back_to_bare_name_without_meta(self):
        payload = json.loads(export_owned_blueprints_json({"Norfield"}, {}))
        assert payload["blueprints"][0]["name"] == "Norfield"

    def test_sorted_case_insensitively(self):
        payload = json.loads(export_owned_blueprints_json({"zeta", "Alpha", "beta"}, {}))
        names = [b["name"] for b in payload["blueprints"]]
        assert names == ["Alpha", "beta", "zeta"]

    def test_empty_owned_set_produces_empty_blueprints_list(self):
        payload = json.loads(export_owned_blueprints_json(set(), {}))
        assert payload["blueprints"] == []


class TestExportCsv:
    def test_header_row(self):
        rows = list(csv.reader(io.StringIO(export_owned_blueprints_csv(set(), {}))))
        assert rows[0] == ["name", "type"]

    def test_includes_name_and_type(self):
        meta = {"Norfield": _Item(tagged_name="Norfield", type="Fuel Nozzle")}
        text = export_owned_blueprints_csv({"Norfield"}, meta)
        rows = list(csv.DictReader(io.StringIO(text)))
        assert rows[0]["name"] == "Norfield"
        assert rows[0]["type"] == "Fuel Nozzle"

    def test_falls_back_to_bare_name_and_empty_type_without_meta(self):
        text = export_owned_blueprints_csv({"Norfield"}, {})
        rows = list(csv.DictReader(io.StringIO(text)))
        assert rows[0]["name"] == "Norfield"
        assert rows[0]["type"] == ""


class TestParseImportNamesJson:
    def test_reads_our_own_export_shape(self, tmp_path):
        path = tmp_path / "export.json"
        path.write_text(export_owned_blueprints_json({"Norfield", "Harkin"}, {}), encoding="utf-8")
        assert parse_import_names(path) == {"Norfield", "Harkin"}

    def test_reads_a_genuine_scmdb_shaped_export(self, tmp_path):
        """SCMDB's own export carries tag/url/completed/favorite per entry
        -- must still resolve on "name" alone, ignoring fields Smart
        Citizen doesn't use."""
        path = tmp_path / "scmdb.json"
        path.write_text(json.dumps({
            "version": 3,
            "exportedAt": "2026-08-01T05:14:29.670Z",
            "missions": [],
            "blueprints": [
                {"tag": "BP_CRAFT_COOL_JSPN_S00_FrostStarSL_SCItem",
                 "name": "Frost-Star SL", "url": "https://scmdb.net/...",
                 "completed": True, "favorite": False},
            ],
        }), encoding="utf-8")
        assert parse_import_names(path) == {"Frost-Star SL"}

    def test_strips_component_tags_via_normalize(self, tmp_path):
        path = tmp_path / "export.json"
        path.write_text(json.dumps({
            "blueprints": [{"name": "[FN] Norfield"}],
        }), encoding="utf-8")
        assert parse_import_names(path) == {"Norfield"}

    def test_strips_non_square_tag_when_enclosing_passed(self, tmp_path):
        """#352: a name tagged with a Round-enclosed Tag Builder style must
        still resolve when the caller passes the actual configured
        enclosing."""
        path = tmp_path / "export.json"
        path.write_text(json.dumps({
            "blueprints": [{"name": "(FN) Norfield"}],
        }), encoding="utf-8")
        assert parse_import_names(path, enclosings=(("(", ")"),)) == {"Norfield"}

    def test_entries_with_no_name_are_skipped(self, tmp_path):
        path = tmp_path / "export.json"
        path.write_text(json.dumps({
            "blueprints": [{"name": ""}, {"name": "Norfield"}, {}],
        }), encoding="utf-8")
        assert parse_import_names(path) == {"Norfield"}

    def test_malformed_json_raises_invalid_import_file_error(self, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(InvalidImportFileError):
            parse_import_names(path)

    def test_missing_blueprints_array_raises(self, tmp_path):
        path = tmp_path / "wrong_shape.json"
        path.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
        with pytest.raises(InvalidImportFileError):
            parse_import_names(path)

    def test_blueprints_present_but_not_a_list_raises(self, tmp_path):
        """Distinct from test_missing_blueprints_array_raises above -- this
        is the key present but wrong-typed, not absent entirely."""
        path = tmp_path / "wrong_type.json"
        path.write_text(json.dumps({"blueprints": "not a list"}), encoding="utf-8")
        with pytest.raises(InvalidImportFileError):
            parse_import_names(path)


class TestParseImportNamesCsv:
    def test_reads_our_own_export_shape(self, tmp_path):
        path = tmp_path / "export.csv"
        path.write_text(export_owned_blueprints_csv({"Norfield", "Harkin"}, {}), encoding="utf-8")
        assert parse_import_names(path) == {"Norfield", "Harkin"}

    def test_extra_columns_are_ignored(self, tmp_path):
        path = tmp_path / "export.csv"
        path.write_text("name,type,extra\nNorfield,Fuel Nozzle,whatever\n", encoding="utf-8")
        assert parse_import_names(path) == {"Norfield"}

    def test_missing_name_column_raises(self, tmp_path):
        path = tmp_path / "wrong.csv"
        path.write_text("type\nFuel Nozzle\n", encoding="utf-8")
        with pytest.raises(InvalidImportFileError):
            parse_import_names(path)

    def test_bom_prefixed_csv_still_parses(self, tmp_path):
        """A CSV saved from Excel often carries a UTF-8 BOM -- must not
        corrupt the "name" header into "\\ufeffname"."""
        path = tmp_path / "excel_export.csv"
        path.write_bytes(b"\xef\xbb\xbfname,type\r\nNorfield,Fuel Nozzle\r\n")
        assert parse_import_names(path) == {"Norfield"}

    def test_non_utf8_csv_raises_invalid_import_file_error(self, tmp_path):
        """A CSV saved from Excel on Windows often lands as cp1252/Latin-1,
        not UTF-8 -- must surface as the same clean error as any other
        malformed file, not an uncaught UnicodeDecodeError."""
        path = tmp_path / "bad_encoding.csv"
        path.write_bytes(b"name,type\r\nNorf\xffield,Fuel Nozzle\r\n")
        with pytest.raises(InvalidImportFileError):
            parse_import_names(path)


class TestParseImportNamesUnsupportedExtension:
    def test_unsupported_extension_raises(self, tmp_path):
        path = tmp_path / "notes.txt"
        path.write_text("Norfield", encoding="utf-8")
        with pytest.raises(InvalidImportFileError):
            parse_import_names(path)


class TestMatchImportNames:
    def test_splits_matched_and_unmatched(self):
        matched, unmatched = match_import_names(
            {"Norfield", "Harkin", "Unknown Thing"}, {"Norfield", "Harkin"}
        )
        assert matched == {"Norfield", "Harkin"}
        assert unmatched == {"Unknown Thing"}

    def test_empty_known_set_leaves_everything_unmatched(self):
        matched, unmatched = match_import_names({"Norfield"}, set())
        assert matched == set()
        assert unmatched == {"Norfield"}

    def test_empty_imported_set_matches_nothing(self):
        matched, unmatched = match_import_names(set(), {"Norfield"})
        assert matched == set()
        assert unmatched == set()

    def test_known_side_is_normalized_for_comparison(self):
        """*imported* always arrives normalized (parse_import_names runs it
        through normalize_item_name), but *known* -- the Blueprint Tracker's
        own dict keys -- is not. A bracketed known name must still match a
        plain imported one; the *original* known name comes back in
        *matched*, not the normalized form, since that's what has to be
        persisted into the Owned set to stay valid for a later
        blueprint_meta.get(name) lookup."""
        matched, unmatched = match_import_names(
            {"Norfield"}, {"[FN] Norfield"}
        )
        assert matched == {"[FN] Norfield"}
        assert unmatched == set()

    def test_recovers_a_foreign_formatted_import_name_via_catalogue(self):
        """#372: an owned set exported before upgrading can still carry a
        foreign editor's decoration (e.g. StarStrings' "Ind/1/B Colossus").
        Passing the wider known-item catalogue lets that recover the same
        way a log scan would, as long as the recovered real name is also
        currently Blueprint-Tracker-eligible (present in *known*)."""
        matched, unmatched = match_import_names(
            {"Ind/1/B Colossus"}, {"Colossus"}, catalogue={"Colossus"}
        )
        assert matched == {"Colossus"}
        assert unmatched == set()

    def test_recovered_name_not_currently_eligible_stays_unmatched(self):
        """The recovered real name must ALSO be in *known* to count as
        matched -- catalogue only proves it's a real item, not that the
        Blueprint Tracker has anywhere to mark it owned right now (e.g. it
        rotated out of every mission's current reward pool)."""
        matched, unmatched = match_import_names(
            {"Ind/1/B Colossus"}, set(), catalogue={"Colossus"}
        )
        assert matched == set()
        assert unmatched == {"Ind/1/B Colossus"}

    def test_omitting_catalogue_skips_recovery_entirely(self):
        """No catalogue means the original exact-match-only behavior --
        recovery is opt-in, not a silent behavior change for existing
        callers that don't pass it."""
        matched, unmatched = match_import_names(
            {"Ind/1/B Colossus"}, {"Colossus"}
        )
        assert matched == set()
        assert unmatched == {"Ind/1/B Colossus"}

    def test_matches_non_square_known_set_when_enclosing_passed(self):
        """#352: a known-set entry tagged with a Round-enclosed style must
        still match a bare imported name when the actual configured
        enclosing is passed through."""
        matched, unmatched = match_import_names(
            {"Norfield"}, {"(FN) Norfield"}, enclosings=(("(", ")"),)
        )
        assert matched == {"(FN) Norfield"}
        assert unmatched == set()
