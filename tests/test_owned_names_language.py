"""Owned names follow the loaded language (#569).

The Owned set holds display names, in the language that was loaded when each
was added. Nothing renamed them when the language changed, so after a switch
an item owned under its old name stayed in Owned under that name and showed
again in Available under its new one. #564's reporter, a Spanish player, had
the S-38 Pistol and its magazine in Owned twice, once under each language's
name. Each load now renames an owned name the loaded strings do not know
through its loc key, and a scan and Import Owned Blueprints rename their names
the same way. The other languages' names come from every channel's cached
base.ini files (the Owned set is shared by all channels), read by each load on
the loader's thread and kept for the session, so the rename itself reads no
file on the GUI thread.

The keys are the starter blueprints' real ones, and the S-38's names, its
short label included, are the LIVE 4.10 files' (English, and the community
Spanish file the user tested with).
"""
from __future__ import annotations

import ast
import inspect
import logging
import os
import sys
import textwrap
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.gui.blueprint_tracker_tab as blueprint_tracker_tab  # noqa: E402
import src.gui.main_window as main_window  # noqa: E402
import src.gui.workers as workers  # noqa: E402
from src.gui.blueprint_tracker_tab import BlueprintTrackerTab  # noqa: E402
from src.gui.main_window import MainWindow  # noqa: E402
from src.gui.workers import (  # noqa: E402
    FileLoaderWorker,
    LanguageNameTablesRead,
    read_language_name_tables,
)
from src.models.string_model import StringEntry  # noqa: E402
from src.parser import ini_parser  # noqa: E402
from src.utils.blueprint_export import export_owned_blueprints_json  # noqa: E402
from src.utils.blueprint_meta import (  # noqa: E402
    BlueprintItem,
    item_keys_by_name,
    item_name_sets,
    other_language_files,
    read_item_keys_by_name,
)
from src.utils.owned_items import drop_short_labels, rename_across_languages  # noqa: E402
from src.utils.settings import AppSettings  # noqa: E402
from src.utils.win_paths import win_long_path  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_PISTOL = "item_Namebehr_pistol_ballistic_01"
_MAG = "item_Namebehr_pistol_ballistic_01_mag"

# The S-38's real lines, short label included: the community Spanish file
# leaves the label untranslated, so "S-38 Pistol" is a Spanish short label and
# the pistol's English name at once (the user's #569 portable test).
ENGLISH = {
    _PISTOL: "S-38 Pistol",
    _PISTOL + "_short": "S-38 Pistol",
    _MAG: "S-38 Magazine (20 cap)",
    "item_NameColossus": "Colossus",
}
SPANISH = {
    _PISTOL: "S-38 Pistola",
    _PISTOL + "_short": "S-38 Pistol",
    _MAG: "S-38 Cargador (20 cap)",
    "item_NameColossus": "Colossus",
}


def _entry(key, value):
    return StringEntry(
        key=key, source_file="global", category="Gear",
        original_value=value, custom_value="", status="Unmodified",
    )


def _catalogue(values):
    """The loaded strings' item names, short labels left out, as a load
    builds its catalogue."""
    return item_name_sets([_entry(k, v) for k, v in values.items()], default_values=values)[0]


def _by_key(values):
    """The loaded strings' names by loc key, as item_name_sets gives them."""
    return item_name_sets([_entry(k, v) for k, v in values.items()], default_values=values)[2]


def _rename(owned, loaded, *others):
    """rename_across_languages with *loaded* as the loaded strings (its
    catalogue and names by key built as a load builds them) and each of
    *others* as another cached language's base.ini."""
    catalogue, _labels, names_by_key = item_name_sets(
        [_entry(k, v) for k, v in loaded.items()], default_values=loaded,
    )
    return rename_across_languages(
        set(owned), catalogue, [item_keys_by_name(o) for o in others], names_by_key,
    )


def _unread():
    """A table source that fails the test if anything reads it."""
    raise AssertionError("the other languages' tables were read")
    yield  # pragma: no cover


def _write(path: Path, values: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    return path


def _cache_file(channel: str, language: str = "english") -> Path:
    """Where *channel*'s cache keeps *language*'s base.ini, made by hand so a
    channel other than the active one can be written."""
    cache = AppSettings.get_user_data_dir() / channel / "cache"
    if language == "english":
        return cache / "base.ini"
    return cache / "lang" / language / "base.ini"


class _Reads(list):
    """Every file parse_ini_file reads, in order, with the ones read off the
    main thread also in ``off_main``."""

    def __init__(self):
        super().__init__()
        self.off_main: list = []

    def on_main(self) -> list:
        """The files read on the main thread, the GUI thread in the app."""
        off = list(self.off_main)
        main = []
        for path in self:
            if path in off:
                off.remove(path)
            else:
                main.append(path)
        return main

    def clear(self):
        super().clear()
        self.off_main.clear()


@pytest.fixture
def reads(monkeypatch):
    """Every file parse_ini_file reads (see _Reads)."""
    seen = _Reads()
    real = ini_parser.parse_ini_file

    def recording(path, **kwargs):
        if threading.current_thread() is not threading.main_thread():
            seen.off_main.append(Path(path))
        seen.append(Path(path))
        return real(path, **kwargs)

    monkeypatch.setattr(ini_parser, "parse_ini_file", recording)
    return seen


class _NoBoxes:
    """Stands in for QMessageBox in main_window: a reload that would open a
    box fails the test with its text instead."""

    @staticmethod
    def warning(parent, title, text, *args, **kwargs):
        raise AssertionError(f"unexpected warning box: {text}")

    @staticmethod
    def critical(parent, title, text, *args, **kwargs):
        raise AssertionError(f"unexpected error box: {text}")


@pytest.fixture(autouse=True)
def no_window_boxes(monkeypatch):
    monkeypatch.setattr(main_window, "QMessageBox", _NoBoxes)


class TestRenameAcrossLanguages:
    def test_the_reporters_two_entries_become_one(self):
        owned = {
            "S-38 Pistol", "S-38 Pistola", "S-38 Magazine (20 cap)", "S-38 Cargador (20 cap)",
        }
        result, renamed = _rename(owned, SPANISH, ENGLISH)
        assert result == {"S-38 Pistola", "S-38 Cargador (20 cap)"}
        assert renamed == {
            "S-38 Pistol": "S-38 Pistola",
            "S-38 Magazine (20 cap)": "S-38 Cargador (20 cap)",
        }

    def test_a_switch_renames_both_ways(self):
        owned, _ = _rename({"S-38 Pistol", "Colossus"}, SPANISH, ENGLISH)
        assert owned == {"S-38 Pistola", "Colossus"}
        owned, _ = _rename(owned, ENGLISH, SPANISH)
        assert owned == {"S-38 Pistol", "Colossus"}

    def test_a_name_two_items_share_in_another_language_stays(self):
        german = {"item_NameA": "Falke", "item_NameB": "Falke"}
        spanish = {"item_NameA": "Halcón", "item_NameB": "Rapaz"}
        result, renamed = _rename({"Falke"}, spanish, german)
        assert (result, renamed) == ({"Falke"}, {})

    def test_two_keys_with_one_loaded_name_rename(self):
        english = {"item_NameA": "Cutter", "item_NameA_tint": "Cutter"}
        spanish = {"item_NameA": "Cortador", "item_NameA_tint": "Cortador"}
        result, renamed = _rename({"Cutter"}, spanish, english)
        assert (result, renamed) == ({"Cortador"}, {"Cutter": "Cortador"})

    def test_an_item_the_loaded_strings_lack_stays(self):
        english = {**ENGLISH, "item_NameRetired": "Retired Rifle"}
        result, renamed = _rename({"Retired Rifle"}, SPANISH, english)
        assert (result, renamed) == ({"Retired Rifle"}, {})

    def test_a_name_no_language_knows_stays(self):
        result, renamed = _rename({"Ind/1/B Colossus"}, SPANISH, ENGLISH)
        assert (result, renamed) == ({"Ind/1/B Colossus"}, {})

    def test_two_other_languages_naming_one_item_rename(self):
        german = {"item_NameA": "Wächter"}
        english = {"item_NameA": "Warden"}
        french = {"item_NameA": "Gardien"}
        result, _ = _rename({"Wächter", "Warden"}, french, german, english)
        assert result == {"Gardien"}

    def test_two_other_languages_naming_two_items_alike_stays(self):
        german = {"item_NameA": "Falke", "item_NameB": "Habicht"}
        english = {"item_NameA": "Hawk", "item_NameB": "Falke"}
        french = {"item_NameA": "Faucon", "item_NameB": "Autour"}
        result, renamed = _rename({"Falke"}, french, german, english)
        assert (result, renamed) == ({"Falke"}, {})

    def test_a_short_label_is_never_the_new_name(self):
        """The Dust Devil set's short label shares the set's key stem, but a
        label is no item anyone owns, so neither side counts it."""
        english = {"item_Name_srvl_armor_heavy_armor_02_short": "Dust Devil"}
        spanish = {"item_Name_srvl_armor_heavy_armor_02_short": "Diablo de Polvo"}
        result, renamed = _rename({"Dust Devil"}, {**spanish, **SPANISH}, english)
        assert (result, renamed) == ({"Dust Devil"}, {})

    @pytest.mark.parametrize("owned, catalogue, names_by_key", [
        ({"S-38 Pistola"}, _catalogue(SPANISH), _by_key(SPANISH)),
        ({"S-38 Pistol"}, set(), _by_key(SPANISH)),
        ({"S-38 Pistol"}, _catalogue(SPANISH), {}),
        (set(), _catalogue(SPANISH), _by_key(SPANISH)),
    ], ids=["every-name-known", "no-catalogue", "no-names-by-key", "nothing-owned"])
    def test_the_tables_are_read_only_when_a_name_needs_them(self, owned, catalogue, names_by_key):
        result, renamed = rename_across_languages(owned, catalogue, _unread(), names_by_key)
        assert (result, renamed) == (owned, {})

    def test_the_set_handed_in_is_left_alone(self):
        owned = {"S-38 Pistol"}
        rename_across_languages(
            owned, _catalogue(SPANISH), [item_keys_by_name(ENGLISH)], _by_key(SPANISH),
        )
        assert owned == {"S-38 Pistol"}


class TestTheLabelDropKeepsAnotherLanguagesNames:
    """#570 drops an item's short label saved in the Owned set, but the
    Spanish file keeps the S-38's short label as "S-38 Pistol", the pistol's
    English name: a Spanish load dropped it from an Owned set seeded in
    English (the user's #569 portable test). The real files make the same
    trap of Demeco LMG, Liberator and S71 Rifle."""

    def test_a_label_another_language_names_an_item_is_kept(self):
        owned = {"S-38 Pistol", "Dust Devil", "Colossus"}
        labels = {"S-38 Pistol", "Dust Devil"}
        kept, dropped = drop_short_labels(owned, labels, [item_keys_by_name(ENGLISH)])
        assert (kept, dropped) == ({"S-38 Pistol", "Colossus"}, {"Dust Devil"})

    def test_with_no_other_language_every_owned_label_goes(self):
        kept, dropped = drop_short_labels({"S-38 Pistol", "Colossus"}, {"S-38 Pistol"})
        assert (kept, dropped) == ({"Colossus"}, {"S-38 Pistol"})

    def test_the_tables_are_read_only_when_a_label_is_owned(self):
        assert drop_short_labels({"Colossus"}, {"S-38 Pistol"}, _unread()) == ({"Colossus"}, set())

    def test_with_a_language_unread_nothing_goes(self):
        """None: another language's file went unread, so whether a label is
        its item name is unknown, and the drop waits."""
        owned = {"S-38 Pistol", "Dust Devil"}
        assert drop_short_labels(owned, set(owned), None) == (owned, set())

    @pytest.mark.parametrize("tables, complete", [
        ({}, True),
        ({"read": ((1, 1), {})}, True),
        ({"read": ((1, 1), {}), "unread": (None, {})}, False),
        ({"": (None, {})}, False),
    ], ids=["no-other-language", "all-read", "one-unread", "listing-failed"])
    def test_the_window_counts_its_tables_complete_only_when_all_were_read(
        self, tables, complete,
    ):
        window = SimpleNamespace(_language_name_tables=tables)
        assert MainWindow._language_tables_complete(window) is complete


class TestTheNameTables:
    def test_item_keys_by_name_maps_each_item_name_to_its_keys(self):
        values = {
            _PISTOL: "S-38 Pistol",
            "vehicle_NameAEGS_Avenger_Titan": "Avenger Titan",
            "item_fuelnozzle_misc_standard": "RN-7s",
            "item_NameTwinB": "Twin",
            "item_NameTwinA": "Twin",
            "item_Name_srvl_armor_heavy_armor_02_short": "Dust Devil",
            "item_NameBlank": "",
            "ui_Greeting": "Hello",
        }
        assert item_keys_by_name(values) == {
            "S-38 Pistol": (_PISTOL.lower(),),
            "Avenger Titan": ("vehicle_nameaegs_avenger_titan",),
            "RN-7s": ("item_fuelnozzle_misc_standard",),
            "Twin": ("item_nametwina", "item_nametwinb"),
        }

    def test_a_language_reads_as_a_load_of_it_named_it(self):
        """An owned name was saved as a load of its language named it: a Tag
        Builder tag stripped through the stock value, a non-breaking space
        folded, an alias resolved. The table names each item the same way."""
        nbsp = chr(0xA0)
        plain = {
            "item_NamePOWR_ACOM_S01_StarHeart": "StarHeart",
            "item_NameMining_Head_S00_Hofstede_SCItem": "Hofstede",
            "item_Name_lynx_legs": f"Lynx{nbsp}Legs",
            _PISTOL: "S-38 Pistola",
        }
        tagged = {k: (f"{v} [MIL-S1-A]" if "POWR" in k else v) for k, v in plain.items()}
        loaded = item_name_sets([_entry(k, v) for k, v in tagged.items()], default_values=plain)[0]
        assert set(item_keys_by_name(plain)) == loaded
        assert {"StarHeart", "S00 Hofstede", "Lynx Legs"} <= loaded

    def test_names_by_key_holds_every_item_and_no_short_label(self):
        entries = [
            _entry(_PISTOL, "S-38 Pistol"),
            _entry("item_Name_srvl_armor_heavy_legs_02", "Dust Devil Legs"),
            _entry("item_Name_srvl_armor_heavy_armor_02_short", "Dust Devil"),
            _entry("ui_Greeting", "Hello"),
        ]
        real, labels, by_key = item_name_sets(entries)
        assert by_key == {
            _PISTOL.lower(): "S-38 Pistol",
            "item_name_srvl_armor_heavy_legs_02": "Dust Devil Legs",
        }
        assert set(by_key.values()) == real
        assert labels == {"Dust Devil"}


def _upper(path: Path) -> str:
    return str(path).upper()


def _forward(path: Path) -> str:
    return str(path).replace("\\", "/")


class TestReadItemKeysByName:
    def test_each_file_with_its_size_and_modified_time(self, tmp_path):
        english = _write(tmp_path / "en" / "base.ini", ENGLISH)
        tables = read_item_keys_by_name([english])
        st = english.stat()
        assert tables == {str(english): ((st.st_size, st.st_mtime_ns), item_keys_by_name(ENGLISH))}

    def test_an_unchanged_file_is_not_read_again(self, tmp_path, reads):
        english = _write(tmp_path / "en" / "base.ini", ENGLISH)
        first = read_item_keys_by_name([english])
        second = read_item_keys_by_name([english], cached=first)
        assert second[str(english)] is first[str(english)]
        assert reads == [english]
        _write(english, {**ENGLISH, "item_NameNew": "New Thing"})
        third = read_item_keys_by_name([english], cached=second)
        assert "New Thing" in third[str(english)][1]
        assert reads == [english, english]

    def test_a_file_no_longer_listed_drops_out(self, tmp_path):
        english = _write(tmp_path / "en" / "base.ini", ENGLISH)
        spanish = _write(tmp_path / "es" / "base.ini", SPANISH)
        both = read_item_keys_by_name([english, spanish])
        assert set(read_item_keys_by_name([english], cached=both)) == {str(english)}

    def test_a_file_that_cannot_be_read_is_marked_unread(self, tmp_path, monkeypatch, caplog):
        """No names and no stamp: the next call reads it again, and the
        window can tell its tables are not complete."""
        english = _write(tmp_path / "en" / "base.ini", ENGLISH)
        spanish = _write(tmp_path / "es" / "base.ini", SPANISH)
        real_stat = os.stat

        def stat(path, *args, **kwargs):
            if Path(path) == spanish:
                raise PermissionError(13, "Permission denied", str(path))
            return real_stat(path, *args, **kwargs)

        monkeypatch.setattr(os, "stat", stat)
        with caplog.at_level(logging.WARNING, logger="src.utils.blueprint_meta"):
            tables = read_item_keys_by_name([english, spanish])
        assert tables[str(spanish)] == (None, {})
        assert tables[str(english)][1] == item_keys_by_name(ENGLISH)
        assert [r.levelno for r in caplog.records] == [logging.WARNING]
        assert str(spanish) in caplog.records[0].message

    def test_a_file_nothing_could_be_read_from_is_marked_unread(self, tmp_path, caplog):
        """Something in it and no line read (as when parse_ini_file fails
        and gives {}): unread, so the label drop waits for it."""
        garbled = tmp_path / "garbled.ini"
        garbled.write_text("no key and value on any line\n", encoding="utf-8")
        with caplog.at_level(logging.WARNING, logger="src.utils.blueprint_meta"):
            assert read_item_keys_by_name([garbled]) == {str(garbled): (None, {})}
        assert [r.levelno for r in caplog.records] == [logging.WARNING]

    def test_an_empty_file_counts_as_read(self, tmp_path, caplog):
        """Nothing in it to wait for: one a cut-off download left must not
        hold the label drop back for as long as it is there."""
        empty = tmp_path / "empty.ini"
        empty.write_text("", encoding="utf-8")
        with caplog.at_level(logging.WARNING, logger="src.utils.blueprint_meta"):
            tables = read_item_keys_by_name([empty])
        assert tables == {str(empty): ((0, empty.stat().st_mtime_ns), {})}
        assert caplog.records == []

    def test_an_unread_file_is_read_at_the_next_call(self, tmp_path):
        english = _write(tmp_path / "en" / "base.ini", ENGLISH)
        tables = read_item_keys_by_name([english], cached={str(english): (None, {})})
        assert tables[str(english)][1] == item_keys_by_name(ENGLISH)


def _files(tmp_path, *copies):
    """``(channel, language, path)`` for each ``(channel, language)`` in
    *copies*, each a real file, in the order given."""
    out = []
    for channel, language in copies:
        out.append((channel, language, _write(tmp_path / channel / language / "base.ini", ENGLISH)))
    return out


class TestOtherLanguageFiles:
    def test_one_copy_of_each_language_but_the_loaded_one(self, tmp_path):
        files = _files(
            tmp_path, ("LIVE", "english"), ("LIVE", "spanish"),
            ("PTU", "english"), ("PTU", "german"), ("PTU", "spanish"),
        )
        live_es = files[1][2]
        chosen = other_language_files(files, str(live_es), "LIVE")
        assert chosen == [files[0][2], files[3][2]]

    def test_the_active_channels_copy_is_preferred(self, tmp_path):
        files = _files(tmp_path, ("LIVE", "english"), ("PTU", "english"), ("PTU", "spanish"))
        assert other_language_files(files, str(files[2][2]), "PTU") == [files[1][2]]
        assert other_language_files(files, str(files[2][2]), "EPTU") == [files[0][2]]

    @pytest.mark.parametrize("spell", [
        str,
        pytest.param(_upper, marks=pytest.mark.skipif(
            sys.platform != "win32", reason="Windows file names ignore case")),
        _forward,
        pytest.param(win_long_path, marks=pytest.mark.skipif(
            sys.platform != "win32", reason="the long-path prefix is Windows only")),
    ], ids=["as-listed", "other-case", "forward-slashes", "long-path-prefix"])
    def test_the_loaded_language_is_found_however_its_file_is_spelled(self, tmp_path, spell):
        files = _files(tmp_path, ("LIVE", "english"), ("LIVE", "spanish"))
        assert other_language_files(files, spell(files[1][2]), "LIVE") == [files[0][2]]

    def test_the_loaded_language_is_found_through_a_junction(self, tmp_path):
        from tests.junction import make_junction

        files = _files(tmp_path, ("LIVE", "english"), ("LIVE", "spanish"))
        make_junction(tmp_path / "linked", files[1][2].parent)
        linked = tmp_path / "linked" / "base.ini"
        assert other_language_files(files, str(linked), "LIVE") == [files[0][2]]

    @pytest.mark.parametrize("loaded", [
        "https://example.invalid/global.ini", "", None,
    ], ids=["url", "empty", "none"])
    def test_a_source_that_is_no_cached_file_leaves_out_nothing(self, tmp_path, loaded):
        files = _files(tmp_path, ("LIVE", "english"), ("LIVE", "spanish"))
        assert other_language_files(files, loaded, "LIVE") == [files[0][2], files[1][2]]


class TestCachedBaseIniPaths:
    def test_nothing_cached(self, tmp_profile):
        assert AppSettings.get_cached_base_ini_paths() == []

    def test_every_channel_and_language_that_holds_a_base_ini(self, tmp_profile):
        live_en = _write(_cache_file("LIVE"), ENGLISH)
        live_es = _write(_cache_file("LIVE", "spanish"), SPANISH)
        ptu_en = _write(_cache_file("PTU"), ENGLISH)
        _cache_file("PTU", "german").parent.mkdir(parents=True)  # a folder with no base.ini
        _write(_cache_file("PTU").parent / "lang" / "notes.txt", {})  # a file, not a folder
        assert AppSettings.get_cached_base_ini_paths() == [
            ("LIVE", "english", live_en), ("LIVE", "spanish", live_es), ("PTU", "english", ptu_en),
        ]

    def test_a_hidden_language_counts_and_a_backup_folder_does_not(
        self, tmp_profile, tmp_path, monkeypatch,
    ):
        """The languages are the ones the app ships, offered or not: Spanish
        here has only a stub ui.json, so the selector hides it, and its file
        is still found, while a backup copy and a language the app does not
        ship are no languages. No ui.json is read to find them."""
        shipped = tmp_path / "languages"
        (shipped / "english").mkdir(parents=True)
        (shipped / "spanish").mkdir()
        (shipped / "spanish" / "ui.json").write_text('{"_comment": "stub"}', encoding="utf-8")
        (shipped / "sources.json").write_text("{}", encoding="utf-8")
        monkeypatch.setattr(AppSettings, "get_languages_dir", staticmethod(lambda: shipped))
        assert AppSettings.get_available_languages() == ["english"]

        def not_read(path):
            raise AssertionError(f"{path} was read")

        monkeypatch.setattr(AppSettings, "_ui_json_has_translations", staticmethod(not_read))
        english = _write(_cache_file("LIVE"), ENGLISH)
        hidden = _write(_cache_file("LIVE", "spanish"), SPANISH)
        _write(_cache_file("LIVE", "spanish.bak"), SPANISH)
        _write(_cache_file("LIVE", "klingon"), SPANISH)
        assert AppSettings.get_cached_base_ini_paths() == [
            ("LIVE", "english", english), ("LIVE", "spanish", hidden),
        ]

    @pytest.mark.parametrize("folders", [["spanish"], None], ids=["no-english-folder", "no-folder"])
    def test_english_counts_however_the_languages_folder_reads(
        self, tmp_profile, tmp_path, monkeypatch, folders,
    ):
        shipped = tmp_path / "languages"
        for name in folders or ():
            (shipped / name).mkdir(parents=True)
        monkeypatch.setattr(AppSettings, "get_languages_dir", staticmethod(lambda: shipped))
        english = _write(_cache_file("LIVE"), ENGLISH)
        assert AppSettings.get_cached_base_ini_paths() == [("LIVE", "english", english)]

    def test_the_files_are_where_get_base_ini_path_puts_them(self, tmp_profile):
        """Both name the files through _base_ini_in, so they cannot drift."""
        for language in ("english", "spanish"):
            _write(AppSettings.get_base_ini_path(language), ENGLISH)
        assert [path for _c, _l, path in AppSettings.get_cached_base_ini_paths()] == [
            AppSettings.get_base_ini_path("english"), AppSettings.get_base_ini_path("spanish"),
        ]

    def test_english_is_the_file_at_the_cache_root(self, tmp_profile):
        english = _write(_cache_file("LIVE"), ENGLISH)
        _write(english.parent / "lang" / "english" / "base.ini", SPANISH)
        assert AppSettings.get_cached_base_ini_paths() == [("LIVE", "english", english)]

    def test_it_makes_no_folder(self, tmp_profile):
        root = AppSettings.get_user_data_dir()
        _write(_cache_file("LIVE"), ENGLISH)
        before = sorted(root.rglob("*"))
        AppSettings.get_cached_base_ini_paths()
        assert sorted(root.rglob("*")) == before

    def test_a_cache_that_cannot_be_read_is_skipped(self, tmp_profile, monkeypatch, caplog):
        live_en = _write(_cache_file("LIVE"), ENGLISH)
        refused = _write(_cache_file("LIVE", "spanish"), SPANISH)
        ptu_es = _write(_cache_file("PTU", "spanish"), SPANISH)
        real_is_file = Path.is_file

        def is_file(self):
            if self == refused:
                raise PermissionError(5, "Access is denied", str(self))
            return real_is_file(self)

        monkeypatch.setattr(Path, "is_file", is_file)
        with caplog.at_level(logging.WARNING, logger="src.utils.settings"):
            found = AppSettings.get_cached_base_ini_paths()
        assert found == [("LIVE", "english", live_en), ("PTU", "spanish", ptu_es)]
        assert [r.levelno for r in caplog.records] == [logging.WARNING]
        assert str(live_en.parent) in caplog.records[0].message


class _Window:
    """What a load, a scan and an import touch on the window here, with the
    real methods. ``load`` runs the real synchronous reload
    (``perform_merge_and_reload``): the sources read and merged for real, the
    other languages' tables read by its ``LanguageNameTablesRead`` and the
    metadata rebuilt, whose Owned-set repair renames through them. The
    reload's other steps (the table model, filters, Apply's check, the
    status bar) do nothing here."""

    perform_merge_and_reload = MainWindow.perform_merge_and_reload
    _rebuild_blueprint_metadata = MainWindow._rebuild_blueprint_metadata
    _repair_foreign_owned_names = MainWindow._repair_foreign_owned_names
    _other_language_item_keys = MainWindow._other_language_item_keys
    _language_tables_complete = MainWindow._language_tables_complete
    _rename_from_other_languages = MainWindow._rename_from_other_languages
    _rename_imported_names = MainWindow._rename_imported_names
    _owned_names_from_log = MainWindow._owned_names_from_log

    def __init__(self):
        self.entries = []
        self.default_values = {}
        self._deferred_starter_report = []
        self._known_item_names = set()
        self._item_names_by_key = {}
        self._language_name_tables = {}
        self._model = MagicMock()

    def load(self, language):
        """A real synchronous reload of *language*, as a channel switch
        runs one, with the ``global`` source on its base.ini (as a language
        switch leaves it)."""
        path = AppSettings.get_base_ini_path(language)
        AppSettings.set_source_path(AppSettings.SOURCE_GLOBAL, str(path))
        self.perform_merge_and_reload()
        assert self.entries, "the reload loaded no strings"

    def _bp_header(self):
        return None

    def statusBar(self):
        return SimpleNamespace(showMessage=lambda *args: None)

    def _snapshot_pending_user_edits(self):
        return {}

    def _record_reloaded_overrides(self, entries, pending):
        return pending

    def _restore_pending_user_edits(self, entries, pending, global_values):
        return 0

    def update_category_combo(self):
        pass

    def apply_filters(self):
        pass

    def _recompute_owned(self):
        pass

    def _refresh_apply_dirty_after_reload(self):
        pass

    def _update_status_bar(self):
        pass

    def _queue_deferred_starter_report(self):
        pass

    def _queue_asks_after_the_job(self):
        pass


@pytest.fixture
def two_languages(tmp_profile):
    """English and Spanish base.ini files cached for LIVE, Spanish picked."""
    _write(AppSettings.get_base_ini_path("english"), ENGLISH)
    _write(AppSettings.get_base_ini_path("spanish"), SPANISH)
    AppSettings.set_selected_language("spanish")
    return tmp_profile


def _info_569(caplog):
    return [r.message for r in caplog.records if r.levelno == logging.INFO and "#569" in r.message]


class TestTheLoadRenamesTheOwnedSet:
    def test_the_reporters_two_entries_become_one(self, two_languages, caplog):
        AppSettings.set_owned_items({"S-38 Pistol", "S-38 Pistola", "S-38 Magazine (20 cap)"})
        with caplog.at_level(logging.INFO, logger="src.gui.main_window"):
            _Window().load("spanish")
        assert AppSettings.get_owned_items() == {"S-38 Pistola", "S-38 Cargador (20 cap)"}
        lines = _info_569(caplog)
        assert (
            "Owned set: renamed 'S-38 Pistol' -> 'S-38 Pistola', its name in the loaded "
            "language (#569)" in lines
        )
        assert any("'S-38 Magazine (20 cap)' -> 'S-38 Cargador (20 cap)'" in m for m in lines)

    def test_each_switch_renames_the_owned_set(self, two_languages):
        AppSettings.set_owned_items({"S-38 Pistol", "Colossus"})
        window = _Window()
        window.load("english")
        assert AppSettings.get_owned_items() == {"S-38 Pistol", "Colossus"}
        window.load("spanish")
        assert AppSettings.get_owned_items() == {"S-38 Pistola", "Colossus"}
        window.load("english")
        assert AppSettings.get_owned_items() == {"S-38 Pistol", "Colossus"}

    def test_a_name_no_language_knows_stays(self, two_languages):
        AppSettings.set_owned_items({"S-38 Pistola", "Retired Rifle"})
        _Window().load("spanish")
        assert AppSettings.get_owned_items() == {"S-38 Pistola", "Retired Rifle"}

    def test_the_rename_comes_before_the_372_repair(self, tmp_profile):
        """'Karna Rifle' ends in the name of the Spanish item 'Rifle', so the
        #372 repair alone folds it into that item, as the control shows.
        Renamed first, it takes its own Spanish name."""
        english = {"item_NameKarna": "Karna Rifle"}
        spanish = {"item_NameKarna": "Fusil Karna", "item_NameGeneric": "Rifle"}
        english_file = _write(AppSettings.get_base_ini_path("english"), english)
        _write(AppSettings.get_base_ini_path("spanish"), spanish)
        AppSettings.set_owned_items({"Karna Rifle"})
        _Window().load("spanish")
        assert AppSettings.get_owned_items() == {"Fusil Karna"}

        english_file.unlink()
        AppSettings.set_owned_items({"Karna Rifle"})
        _Window().load("spanish")
        assert AppSettings.get_owned_items() == {"Rifle"}

    def test_a_name_saved_in_another_channels_language_is_renamed(self, tmp_profile):
        """The Owned set is shared by every channel. Spanish was used on LIVE
        only, so PTU's cache has no Spanish file: on PTU in English, a Spanish
        owned name is traced through LIVE's."""
        _write(_cache_file("LIVE"), ENGLISH)
        _write(_cache_file("LIVE", "spanish"), SPANISH)
        AppSettings.set_active_channel("PTU")
        _write(AppSettings.get_base_ini_path("english"), ENGLISH)
        AppSettings.set_owned_items({"S-38 Pistola"})
        _Window().load("english")
        assert AppSettings.get_owned_items() == {"S-38 Pistol"}

    def test_one_copy_of_each_other_language_is_read(self, tmp_profile, reads):
        """With LIVE's Spanish loaded, LIVE's English is the one English copy
        read and no Spanish copy is, so a name only PTU's Spanish build uses
        stays as it is: the price of one table per language."""
        live_en = _write(_cache_file("LIVE"), ENGLISH)
        _write(_cache_file("LIVE", "spanish"), SPANISH)
        _write(_cache_file("PTU"), ENGLISH)
        _write(_cache_file("PTU", "spanish"), {**SPANISH, _PISTOL: "S-38 Pistola Mk II"})
        AppSettings.set_owned_items({"S-38 Pistol", "S-38 Pistola Mk II"})
        _Window().load("spanish")
        assert reads.off_main == [live_en]
        assert AppSettings.get_owned_items() == {"S-38 Pistola", "S-38 Pistola Mk II"}

    def test_the_gui_thread_reads_only_the_sources(self, two_languages, reads):
        """The reload reads its sources on the GUI thread (the loaded
        language's own base.ini among them) and the other language's
        base.ini on the thread of its own; the loaded file is never read as
        a table."""
        _Window().load("spanish")
        assert reads.off_main == [AppSettings.get_base_ini_path("english")]
        assert AppSettings.get_base_ini_path("spanish") in reads.on_main()
        assert AppSettings.get_base_ini_path("english") not in reads.on_main()

    def test_each_file_is_read_once_a_session_and_again_once_changed(self, two_languages, reads):
        window = _Window()
        window.load("spanish")
        window.load("spanish")
        assert len(reads.off_main) == 1
        _write(AppSettings.get_base_ini_path("english"), {**ENGLISH, "item_NameNew": "New Thing"})
        window.load("spanish")
        assert len(reads.off_main) == 2

    def test_the_rename_itself_reads_no_file(self, two_languages, reads):
        """Only a load reads the files (on the loader's thread for the async
        load). The repair, a scan's names and an import's names all rename
        from the tables it left, reading nothing on the GUI thread."""
        window = _Window()
        window.load("spanish")
        reads.clear()
        AppSettings.set_owned_items({"S-38 Pistol"})
        window._repair_foreign_owned_names()
        assert AppSettings.get_owned_items() == {"S-38 Pistola"}
        scanned = window._owned_names_from_log(["S-38 Magazine (20 cap)"])
        assert scanned == {"S-38 Cargador (20 cap)"}
        assert window._rename_imported_names({"S-38 Pistol"})[0] == {"S-38 Pistola"}
        assert reads == []

    def test_a_file_that_reads_as_empty_is_tried_again(self, two_languages, monkeypatch):
        """parse_ini_file gives {} for a file it cannot read. Nothing is
        renamed or kept then, and the next load reads the file again. (The
        magazine, which has no short label for #570's drop to take.)"""
        english = AppSettings.get_base_ini_path("english")
        english_reads = []
        real = ini_parser.parse_ini_file

        def first_english_read_fails(path, **kwargs):
            if Path(path) != english:
                return real(path, **kwargs)
            english_reads.append(path)
            return {} if len(english_reads) == 1 else real(path, **kwargs)

        monkeypatch.setattr(ini_parser, "parse_ini_file", first_english_read_fails)
        AppSettings.set_owned_items({"S-38 Magazine (20 cap)"})
        window = _Window()
        window.load("spanish")
        assert AppSettings.get_owned_items() == {"S-38 Magazine (20 cap)"}
        window.load("spanish")
        assert AppSettings.get_owned_items() == {"S-38 Cargador (20 cap)"}
        assert len(english_reads) == 2

    def test_a_label_no_language_names_an_item_still_goes(self, tmp_profile):
        """#570 still drops a saved short label that no cached language uses
        as an item's own name (the Dust Devil set's), while the S-38's label,
        the pistol's English name, is renamed."""
        label = {"item_Name_srvl_armor_heavy_armor_02_short": "Dust Devil"}
        _write(AppSettings.get_base_ini_path("english"), {**ENGLISH, **label})
        _write(AppSettings.get_base_ini_path("spanish"), {**SPANISH, **label})
        AppSettings.set_owned_items({"Dust Devil", "S-38 Pistol"})
        _Window().load("spanish")
        assert AppSettings.get_owned_items() == {"S-38 Pistola"}

    def test_an_empty_cached_file_does_not_hold_the_drop_back(self, tmp_profile):
        """A German base.ini a cut-off download left empty: the saved Dust
        Devil label still goes on the Spanish load."""
        label = {"item_Name_srvl_armor_heavy_armor_02_short": "Dust Devil"}
        _write(AppSettings.get_base_ini_path("english"), {**ENGLISH, **label})
        _write(AppSettings.get_base_ini_path("spanish"), {**SPANISH, **label})
        AppSettings.get_base_ini_path("german").write_text("", encoding="utf-8")
        AppSettings.set_owned_items({"Dust Devil", "S-38 Pistol"})
        _Window().load("spanish")
        assert AppSettings.get_owned_items() == {"S-38 Pistola"}

    def test_a_failure_to_read_the_tables_keeps_the_ones_read(
        self, two_languages, monkeypatch, caplog,
    ):
        window = _Window()
        window.load("spanish")
        tables = window._language_name_tables

        def refused():
            raise RuntimeError("simulated")

        monkeypatch.setattr(AppSettings, "get_cached_base_ini_paths", staticmethod(refused))
        AppSettings.set_owned_items({"S-38 Pistol"})
        with caplog.at_level(logging.WARNING):
            window.load("spanish")
        assert window._language_name_tables == {**tables, "": (None, {})}
        assert AppSettings.get_owned_items() == {"S-38 Pistola"}
        assert [r.levelno for r in caplog.records if "#569" in r.message] == [logging.WARNING]

    def test_the_label_drop_waits_while_a_language_is_unread(
        self, two_languages, monkeypatch, caplog,
    ):
        """The English file cannot be read at the session's first load: the
        English-seeded "S-38 Pistol", a Spanish short label, is kept rather
        than dropped, with an INFO line, and the next load, which reads the
        file, renames it."""
        english = AppSettings.get_base_ini_path("english")
        english_reads = []
        real = ini_parser.parse_ini_file

        def first_english_read_fails(path, **kwargs):
            if Path(path) != english:
                return real(path, **kwargs)
            english_reads.append(path)
            return {} if len(english_reads) == 1 else real(path, **kwargs)

        monkeypatch.setattr(ini_parser, "parse_ini_file", first_english_read_fails)
        AppSettings.set_owned_items({"S-38 Pistol"})
        window = _Window()
        with caplog.at_level(logging.INFO, logger="src.gui.main_window"):
            window.load("spanish")
        assert AppSettings.get_owned_items() == {"S-38 Pistol"}
        assert any("short labels kept for a later load" in r.message for r in caplog.records)
        window.load("spanish")
        assert AppSettings.get_owned_items() == {"S-38 Pistola"}

    def test_a_url_source_reads_every_language(self, two_languages):
        AppSettings.set_source_path(AppSettings.SOURCE_GLOBAL, "https://example.invalid/global.ini")
        assert set(read_language_name_tables({})) == {
            str(AppSettings.get_base_ini_path("english")),
            str(AppSettings.get_base_ini_path("spanish")),
        }

    def test_the_synchronous_reload_reads_on_a_thread_of_its_own(self, monkeypatch):
        seen = []

        def recording(cached):
            seen.append((threading.current_thread(), cached))
            return {"read": ((1, 1), {})}

        monkeypatch.setattr(workers, "read_language_name_tables", recording)
        cached = {"kept": ((2, 2), {})}
        result = LanguageNameTablesRead(cached).result()
        assert result == {"read": ((1, 1), {})}
        ((thread, handed),) = seen
        assert thread is not threading.main_thread() and thread.daemon
        assert handed == cached and handed is not cached


class TestTheLoaderReadsTheTables:
    def test_the_worker_hands_over_the_other_languages_tables(self, two_languages, qapp, reads):
        english = AppSettings.get_base_ini_path("english")
        spanish = AppSettings.get_base_ini_path("spanish")
        AppSettings.set_source_path(AppSettings.SOURCE_GLOBAL, str(spanish))

        def run(cached):
            worker = FileLoaderWorker(language_tables=cached)
            got = []
            worker.finished.connect(lambda *args: got.append(args))
            worker.error.connect(lambda message: got.append(("error", message)))
            worker.run()
            (result,) = got
            assert result[0] != "error", result
            return result[3]

        tables = run({})
        assert list(tables) == [str(english)]
        assert tables[str(english)][1] == item_keys_by_name(ENGLISH)
        assert reads.count(english) == 1
        again = run(tables)
        assert again[str(english)] is tables[str(english)]
        assert reads.count(english) == 1

    def test_a_failure_hands_back_the_tables_marked_incomplete(self, monkeypatch, caplog):
        """The tables read before still serve the rename, and one entry with
        no stamp tells the window some language may have gone unread."""
        def refused():
            raise PermissionError(5, "Access is denied")

        monkeypatch.setattr(AppSettings, "get_cached_base_ini_paths", staticmethod(refused))
        kept = {"kept": ((1, 1), {"S-38 Pistol": ("item_namebehr_pistol_ballistic_01",)})}
        with caplog.at_level(logging.WARNING, logger="src.gui.workers"):
            tables = read_language_name_tables(kept)
        assert tables == {**kept, "": (None, {})}
        assert [r.levelno for r in caplog.records] == [logging.WARNING]
        assert "#569" in caplog.records[0].message


class TestTheWindowsLoadWiring:
    @pytest.fixture(autouse=True)
    def _isolate(self, monkeypatch):
        monkeypatch.setattr(AppSettings, "get_favorite_prefix", staticmethod(lambda: "*"))
        monkeypatch.setattr(main_window, "QTimer", MagicMock())

    @staticmethod
    def _window():
        """A stand-in carrying what _on_loading_finished touches (as in
        test_drop_none_entries.py), recording the tables the rebuild sees."""
        win = MagicMock()
        win._loading_progress = None
        win._loader_worker = None
        win._snapshot_pending_user_edits.return_value = {}
        win._restore_pending_user_edits.return_value = 0
        win._check_enhancements_after_loading = False
        win._initial_load_done = True
        win._language_name_tables = {"kept": ((1, 1), {})}
        seen = []
        win._rebuild_blueprint_metadata.side_effect = lambda: seen.append(win._language_name_tables)
        return win, seen

    def test_the_workers_tables_are_in_place_before_the_rebuild(self):
        win, seen = self._window()
        tables = {"read": ((2, 2), {})}
        MainWindow._on_loading_finished(win, [], {}, [], tables)
        assert seen == [tables]

    def test_none_keeps_the_windows_tables(self):
        win, seen = self._window()
        MainWindow._on_loading_finished(win, [], {}, [], None)
        assert seen == [{"kept": ((1, 1), {})}]

    def test_the_load_hands_the_worker_the_windows_tables(self, monkeypatch):
        made = []
        monkeypatch.setattr(
            main_window, "FileLoaderWorker", lambda **kwargs: made.append(kwargs) or MagicMock(),
        )
        monkeypatch.setattr(main_window, "AnimatedProgressDialog", MagicMock())
        win = MagicMock()
        win._loader_worker = None
        win._loading_progress = None
        win._language_name_tables = {"kept": ((1, 1), {})}
        MainWindow._show_loading_progress(win, "Loading")
        assert made == [{"language_tables": win._language_name_tables}]

    @pytest.mark.parametrize("read, expected", [
        ({"read": ((2, 2), {})}, {"read": ((2, 2), {})}),
        ({"kept": ((1, 1), {}), "": (None, {})}, {"kept": ((1, 1), {}), "": (None, {})}),
    ], ids=["read", "failed-read-marked-incomplete"])
    def test_the_synchronous_reload_reads_the_tables_beside_its_merge(
        self, monkeypatch, read, expected,
    ):
        """perform_merge_and_reload starts the read before it reads the
        sources and takes it before its rebuild renames the Owned set."""
        events = []

        class _Read:
            def __init__(self, cached):
                events.append(("start", dict(cached)))

            def result(self):
                events.append(("result",))
                return read

        def load_sources():
            events.append(("sources",))
            return {AppSettings.SOURCE_GLOBAL: {}}, [AppSettings.SOURCE_GLOBAL], {}

        monkeypatch.setattr(main_window, "LanguageNameTablesRead", _Read)
        monkeypatch.setattr(main_window, "load_sources_from_settings", load_sources)
        monkeypatch.setattr(main_window, "load_source_files", lambda *a, **k: [])
        monkeypatch.setattr(main_window, "QMessageBox", MagicMock())
        win, seen = self._window()
        win._rebuild_blueprint_metadata.side_effect = lambda: (
            events.append(("rebuild",)), seen.append(win._language_name_tables))
        MainWindow.perform_merge_and_reload(win)
        assert events == [
            ("start", {"kept": ((1, 1), {})}), ("sources",), ("result",), ("rebuild",),
        ]
        assert seen == [expected]


class TestAScanRenamesLogNames:
    def test_english_log_names_come_back_in_spanish(self, two_languages, caplog):
        window = _Window()
        window.load("spanish")
        with caplog.at_level(logging.INFO, logger="src.gui.main_window"):
            scanned = window._owned_names_from_log(
                ["S-38 Pistol", "S-38 Magazine (20 cap)", "Colossus"],
            )
        assert scanned == {"S-38 Pistola", "S-38 Cargador (20 cap)", "Colossus"}
        assert (
            "BP scan: renamed 'S-38 Pistol' -> 'S-38 Pistola', its name in the loaded "
            "language (#569)" in _info_569(caplog)
        )

    def test_the_rename_comes_before_the_372_recovery(self, tmp_profile):
        """As at load time: 'Karna Rifle' ends in the Spanish item 'Rifle',
        which the #372 recovery alone would read it as."""
        _write(AppSettings.get_base_ini_path("english"), {"item_NameKarna": "Karna Rifle"})
        _write(AppSettings.get_base_ini_path("spanish"),
               {"item_NameKarna": "Fusil Karna", "item_NameGeneric": "Rifle"})
        window = _Window()
        window.load("spanish")
        assert window._owned_names_from_log(["Karna Rifle"]) == {"Fusil Karna"}

    def test_before_any_load_a_scan_keeps_the_names_as_logged(self, two_languages, reads):
        scanned = _Window()._owned_names_from_log(["S-38 Pistol"])
        assert scanned == {"S-38 Pistol"}
        assert reads == []


class _FakeBox:
    """Stands in for QMessageBox on the Blueprint Tracker tab."""

    Icon = SimpleNamespace(Information="information")
    shown: list = []

    def __init__(self, parent=None):
        self.text = ""
        self.detailed = ""
        _FakeBox.shown.append(self)

    @staticmethod
    def critical(parent, title, text):
        raise AssertionError(f"unexpected error box: {text}")

    def setIcon(self, icon):
        pass

    def setWindowTitle(self, title):
        pass

    def setText(self, text):
        self.text = text

    def setDetailedText(self, text):
        self.detailed = text

    def exec(self):
        pass


_TO_SPANISH = {"S-38 Pistol": "S-38 Pistola", "Retired Rifle": "Fusil retirado"}


def _rename_to_spanish(names):
    """Stands in for MainWindow._rename_imported_names."""
    return (
        {_TO_SPANISH.get(n, n) for n in names},
        {n: _TO_SPANISH[n] for n in names if n in _TO_SPANISH},
    )


class TestImportRenamesNamesSavedInAnotherLanguage:
    def test_the_window_renames_imported_names(self, two_languages, caplog):
        window = _Window()
        window.load("spanish")
        with caplog.at_level(logging.INFO, logger="src.gui.main_window"):
            names, renamed = window._rename_imported_names({"S-38 Pistol", "Colossus"})
        assert names == {"S-38 Pistola", "Colossus"}
        assert renamed == {"S-38 Pistol": "S-38 Pistola"}
        assert (
            "Import Owned Blueprints: renamed 'S-38 Pistol' -> 'S-38 Pistola', its name in "
            "the loaded language (#569)" in _info_569(caplog)
        )

    @staticmethod
    def _import(tmp_path, monkeypatch, names, tracked, renamer):
        """Import an export holding *names* on a real tab offering *tracked*,
        with *renamer* (or none), and return the one summary box."""
        export = tmp_path / "owned.json"
        export.write_text(export_owned_blueprints_json(set(names), {}), encoding="utf-8")
        _FakeBox.shown = []
        monkeypatch.setattr(blueprint_tracker_tab, "QMessageBox", _FakeBox)
        monkeypatch.setattr(blueprint_tracker_tab, "_relabel_details_button", lambda *a, **k: None)
        monkeypatch.setattr(
            blueprint_tracker_tab, "QFileDialog",
            SimpleNamespace(getOpenFileName=lambda *a, **k: (str(export), "")),
        )
        tab = BlueprintTrackerTab()
        try:
            tab.set_blueprint_items({n: BlueprintItem(name=n) for n in tracked})
            if renamer is not None:
                tab.set_name_renamer(renamer)
            tab._import_owned_blueprints()
        finally:
            tab.deleteLater()
        (box,) = _FakeBox.shown
        return box

    @pytest.mark.parametrize("renamer, owned", [
        (_rename_to_spanish, {"S-38 Pistola"}),
        (None, set()),
    ], ids=["renamed", "control-without-a-renamer"])
    def test_an_english_export_imports_into_spanish(
        self, tmp_profile, qapp, tmp_path, monkeypatch, renamer, owned,
    ):
        self._import(tmp_path, monkeypatch, {"S-38 Pistol"}, {"S-38 Pistola"}, renamer)
        assert AppSettings.get_owned_items() == owned

    def test_a_skipped_name_is_listed_as_the_file_spells_it(
        self, tmp_profile, qapp, tmp_path, monkeypatch,
    ):
        """'Retired Rifle' is renamed to 'Fusil retirado', which no mission
        offers, so it is skipped, and listed as the file has it."""
        box = self._import(
            tmp_path, monkeypatch, {"S-38 Pistol", "Retired Rifle"}, {"S-38 Pistola"},
            _rename_to_spanish,
        )
        assert AppSettings.get_owned_items() == {"S-38 Pistola"}
        assert box.detailed == "Retired Rifle"


def _method_tree(method):
    return ast.parse(textwrap.dedent(inspect.getsource(method)))


def test_the_window_starts_with_the_rename_state():
    """A scan can finish before the first load, so __init__ must give the
    window both, as it gives _known_item_names."""
    tree = _method_tree(MainWindow.__init__)
    assigned = {
        node.target.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Attribute)
    } | {
        target.attr
        for node in ast.walk(tree) if isinstance(node, ast.Assign)
        for target in node.targets if isinstance(target, ast.Attribute)
    }
    assert {"_known_item_names", "_item_names_by_key", "_language_name_tables"} <= assigned


def test_the_window_hands_the_tab_its_renamer():
    """setup_ui, where the Blueprint Tracker tab is built, hands it the
    window's renamer for Import Owned Blueprints."""
    calls = [
        node for node in ast.walk(_method_tree(MainWindow.setup_ui))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr == "set_name_renamer"
    ]
    assert len(calls) == 1
    (arg,) = calls[0].args
    assert isinstance(arg, ast.Attribute) and arg.attr == "_rename_imported_names"
