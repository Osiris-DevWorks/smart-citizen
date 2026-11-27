"""#565: Export CSV and Import CSV, and the skip rule Import INI shares.

Qt-free: ``src/utils/strings_csv.py`` on real files under ``tmp_path``.
"""
from __future__ import annotations

import locale

import pytest

from src.utils.strings_csv import (
    CSV_COLUMNS,
    CsvColumnsMissing,
    CsvRow,
    default_csv_filename,
    parse_strings_csv_text,
    plan_override_import,
    read_strings_csv,
    write_strings_csv,
)


def _row(key, custom="", current="Text", default="Text", status="Unmodified", category="Other"):
    return CsvRow(key=key, category=category, default_value=default,
                  current_value=current, custom_value=custom, status=status)


class TestExport:
    def test_writes_the_header_and_rows_in_order_with_a_bom(self, tmp_path):
        path = tmp_path / "out.csv"
        count = write_strings_csv(path, [_row("b_key", "B"), _row("a_key", "A")])
        assert count == 2
        data = path.read_bytes()
        assert data.startswith(b"\xef\xbb\xbf")
        lines = data.decode("utf-8-sig").splitlines()
        assert lines[0] == ",".join(CSV_COLUMNS)
        assert lines[1].startswith("b_key,")
        assert lines[2].startswith("a_key,")

    def test_round_trips_commas_quotes_line_break_tokens_and_other_scripts(self, tmp_path):
        tricky = 'Size: 1, "Grade" C\\nŻółć 日本語 Привет'
        path = tmp_path / "out.csv"
        write_strings_csv(path, [_row("k", tricky, current=tricky)])
        assert read_strings_csv(path) == {"k": tricky}

    def test_default_filename_names_the_channel_and_date(self):
        from datetime import datetime
        assert (default_csv_filename("PTU", datetime(2026, 11, 26))
                == "SmartCitizen-Strings-PTU-20261126.csv")


class TestImportReading:
    def test_reads_key_and_custom_value_only(self):
        text = "Key,Category,Default Value,Current Value,Custom Value,Status\r\nui_A,Other,A,A,Ä,Unmodified\r\n"
        assert parse_strings_csv_text(text) == {"ui_A": "Ä"}

    def test_finds_the_columns_by_header_in_any_order_and_case(self):
        text = "custom value;STATUS;key\nNew;Modified;ui_A\n"
        assert parse_strings_csv_text(text) == {"ui_A": "New"}

    def test_a_semicolon_or_tab_file_from_excel_reads(self):
        assert parse_strings_csv_text("Key;Custom Value\nui_A;x, y\n") == {"ui_A": "x, y"}
        assert parse_strings_csv_text("Key\tCustom Value\nui_A\tx\n") == {"ui_A": "x"}

    def test_rows_without_a_key_or_too_short_are_skipped(self):
        text = "Key,Custom Value\n,orphan\nui_A\nui_B,b\n"
        assert parse_strings_csv_text(text) == {"ui_A": "", "ui_B": "b"}

    def test_missing_columns_raise(self):
        with pytest.raises(CsvColumnsMissing):
            parse_strings_csv_text("Key,Status\nui_A,Modified\n")
        with pytest.raises(CsvColumnsMissing):
            parse_strings_csv_text("")

    def test_a_file_that_is_not_utf8_reads_in_the_system_code_page(self, tmp_path, monkeypatch):
        monkeypatch.setattr(locale, "getpreferredencoding", lambda do_setlocale=True: "cp1250")
        path = tmp_path / "excel.csv"
        path.write_bytes("Key;Custom Value\nui_A;Zażółć\n".encode("cp1250"))
        assert read_strings_csv(path) == {"ui_A": "Zażółć"}


class TestSkipRule:
    DEFAULTS = {"ui_A": "Accept", "ui_B": "Decline", "item_C": "Cooler", "ui_D": "Done"}
    CURRENT = {"ui_A": "Accept", "ui_B": "Decline", "item_C": "Size 1\\nCooler", "ui_D": "Done"}

    def test_sorts_values_into_add_conflict_skip_and_unknown(self):
        imported = {
            "ui_A": "Akceptuj",          # new override
            "ui_B": "",                  # empty: skipped
            "item_C": "Size 1\\nCooler",  # same as the enhanced text: skipped
            "ui_D": "Gotowe",            # differs from the override there
            "nope": "x",                 # not in base.ini
        }
        plan = plan_override_import(imported, self.DEFAULTS, self.CURRENT, {"ui_D": "Fertig"})
        assert plan.auto_add == {"ui_A": "Akceptuj"}
        assert plan.conflicts == {"ui_D": ("Fertig", "Gotowe")}
        assert plan.unchanged == 2
        assert plan.unknown == 1
        assert plan.has_work

    def test_a_full_export_imports_nothing(self):
        plan = plan_override_import(dict(self.CURRENT), self.DEFAULTS, self.CURRENT, {})
        assert not plan.has_work
        assert plan.unchanged == len(self.CURRENT)

    def test_a_value_equal_to_the_default_is_skipped_even_when_enhanced(self):
        plan = plan_override_import({"item_C": "Cooler"}, self.DEFAULTS, self.CURRENT, {})
        assert not plan.has_work and plan.unchanged == 1

    def test_the_same_override_already_there_is_skipped(self):
        plan = plan_override_import({"ui_A": "Akceptuj"}, self.DEFAULTS, self.CURRENT,
                                    {"ui_A": "Akceptuj"})
        assert not plan.has_work and plan.unchanged == 1
