"""Copies of the Owned set kept before a change that removes a name.

A player lost most of their Owned list after switching the Config channel to
PTU and back, and had already deleted the game's logbackups, so no scan could
rebuild it. Nothing kept a copy of the list. ``AppSettings.set_owned_items``
now keeps one whenever a write would drop a name (newest first, at most
``OWNED_SNAPSHOTS_KEPT``), Import Settings does the same before a backup's
Owned set replaces this one, and the Blueprint Tracker's Restore Owned
Blueprints adds a copy's names back.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.json_settings import JsonSettings  # noqa: E402
from src.utils.settings import (  # noqa: E402
    OWNED_BACKUP_FILE,
    OWNED_BACKUP_FOLDER,
    AppSettings,
)


@pytest.fixture
def json_backend(tmp_path, monkeypatch):
    """Settings in a tmp JsonSettings file and the data folder (where the
    Owned list's backup file goes) in tmp_path, never the real ones."""
    folder = tmp_path / "data"
    monkeypatch.setattr(AppSettings, "get_user_data_dir", staticmethod(lambda: folder))
    # conftest points the backup file at tmp_path for every test; these
    # tests check the real path, under the tmp data folder above.
    monkeypatch.setattr(
        AppSettings, "get_owned_items_backup_path",
        staticmethod(lambda: folder / OWNED_BACKUP_FOLDER / OWNED_BACKUP_FILE),
    )
    saved = AppSettings._backend
    AppSettings._backend = JsonSettings(tmp_path / "config.json")
    yield AppSettings._backend
    AppSettings._backend = saved


def _names(snapshots):
    return [names for _saved, names in snapshots]


class TestKeptBeforeARemoval:
    def test_adding_keeps_no_copy(self, json_backend):
        AppSettings.set_owned_items({"A"})
        AppSettings.set_owned_items({"A", "B"})
        assert AppSettings.get_owned_items_snapshots() == []

    def test_a_removal_keeps_the_set_it_replaces(self, json_backend):
        AppSettings.set_owned_items({"A", "B", "C"})
        AppSettings.set_owned_items({"A"})
        assert AppSettings.get_owned_items() == {"A"}
        assert _names(AppSettings.get_owned_items_snapshots()) == [["A", "B", "C"]]

    def test_a_rename_counts_as_a_removal(self, json_backend):
        AppSettings.set_owned_items({"A", "B"})
        AppSettings.set_owned_items({"A", "B2"})
        assert _names(AppSettings.get_owned_items_snapshots()) == [["A", "B"]]

    def test_newest_first_and_only_the_last_ones_kept(self, json_backend):
        kept = AppSettings.OWNED_SNAPSHOTS_KEPT
        AppSettings.set_owned_items({str(i) for i in range(kept + 5)})
        for n in range(kept + 4, 0, -1):
            AppSettings.set_owned_items({str(i) for i in range(n)})
        snapshots = _names(AppSettings.get_owned_items_snapshots())
        assert len(snapshots) == kept
        # The newest copy is the set just before the last write (2 names).
        assert len(snapshots[0]) == 2
        assert [len(s) for s in snapshots] == list(range(2, kept + 2))

    def test_the_saved_time_is_recorded(self, json_backend):
        AppSettings.set_owned_items({"A", "B"})
        AppSettings.set_owned_items(set())
        (saved, _names_), = AppSettings.get_owned_items_snapshots()
        assert len(saved) == len("2026-11-18T13:24:00") and saved[10] == "T"

    def test_a_failed_copy_still_writes_the_change(self, json_backend, monkeypatch):
        AppSettings.set_owned_items({"A", "B"})

        def broken():
            raise RuntimeError("boom")

        monkeypatch.setattr(AppSettings, "get_owned_items_snapshots", staticmethod(broken))
        AppSettings.set_owned_items({"A"})
        assert AppSettings.get_owned_items() == {"A"}

    def test_an_unreadable_stored_value_reads_as_no_copies(self, json_backend):
        json_backend.setValue(AppSettings.OWNED_ITEMS_SNAPSHOTS, "not json")
        assert AppSettings.get_owned_items_snapshots() == []
        json_backend.setValue(
            AppSettings.OWNED_ITEMS_SNAPSHOTS,
            json.dumps([{"saved": "x", "names": ["A"]}, "junk", {"saved": 1}]),
        )
        assert AppSettings.get_owned_items_snapshots() == [("x", ["A"])]


class TestImportSettings:
    def test_a_smaller_imported_set_keeps_a_copy_of_this_one(self, json_backend):
        AppSettings.set_owned_items({"A", "B", "C"})
        AppSettings.import_values({AppSettings.OWNED_ITEMS: json.dumps(["A"])})
        assert AppSettings.get_owned_items() == {"A"}
        assert _names(AppSettings.get_owned_items_snapshots()) == [["A", "B", "C"]]

    def test_a_larger_imported_set_keeps_none(self, json_backend):
        AppSettings.set_owned_items({"A"})
        AppSettings.import_values({AppSettings.OWNED_ITEMS: json.dumps(["A", "B"])})
        assert AppSettings.get_owned_items_snapshots() == []

    def test_the_copies_are_never_exported_or_imported(self, json_backend):
        AppSettings.set_owned_items({"A", "B"})
        AppSettings.set_owned_items({"A"})
        assert AppSettings.OWNED_ITEMS_SNAPSHOTS not in AppSettings.export_all_values()
        mine = AppSettings.get_owned_items_snapshots()
        AppSettings.import_values({
            AppSettings.OWNED_ITEMS_SNAPSHOTS: json.dumps([{"saved": "old", "names": ["Z"]}]),
        })
        assert AppSettings.get_owned_items_snapshots() == mine


class TestRestoreButton:
    @pytest.fixture
    def tab(self, qapp, json_backend, monkeypatch):
        from src.gui import blueprint_tracker_tab as module

        boxes = []
        monkeypatch.setattr(
            module.QMessageBox, "information",
            staticmethod(lambda *a, **k: boxes.append(a[2] if len(a) > 2 else "")),
        )
        tab = module.BlueprintTrackerTab()
        tab.boxes = boxes
        yield tab, module, monkeypatch
        tab.deleteLater()

    def test_puts_back_what_the_copy_had_and_keeps_newer_names(self, tab):
        tab, module, monkeypatch = tab
        AppSettings.set_owned_items({"A", "B", "C"})
        AppSettings.set_owned_items({"A"})
        AppSettings.set_owned_items({"A", "New"})
        monkeypatch.setattr(
            module.QInputDialog, "getItem",
            staticmethod(lambda _p, _t, _l, items, *a: (items[0], True)),
        )
        changed = []
        tab.owned_items_changed.connect(lambda: changed.append(True))
        tab._restore_owned_blueprints()
        assert AppSettings.get_owned_items() == {"A", "B", "C", "New"}
        assert changed == [True]

    def test_cancel_changes_nothing(self, tab):
        tab, module, monkeypatch = tab
        AppSettings.set_owned_items({"A", "B"})
        AppSettings.set_owned_items({"A"})
        monkeypatch.setattr(
            module.QInputDialog, "getItem", staticmethod(lambda *a: ("", False)),
        )
        tab._restore_owned_blueprints()
        assert AppSettings.get_owned_items() == {"A"}

    def test_no_copies_says_so(self, tab):
        tab, module, monkeypatch = tab
        asked = []
        monkeypatch.setattr(
            module.QInputDialog, "getItem", staticmethod(lambda *a: asked.append(a)),
        )
        tab._restore_owned_blueprints()
        assert asked == [] and len(tab.boxes) == 1


class TestBackupFile:
    @pytest.fixture
    def data_dir(self, json_backend):
        return AppSettings.get_user_data_dir()

    def _file(self, data_dir):
        return json.loads(
            (data_dir / "owned_blueprints_backup" / "owned_blueprints.json").read_text("utf-8")
        )

    def test_every_write_mirrors_the_list_and_its_copies(self, data_dir):
        AppSettings.set_owned_items({"A", "B"})
        assert self._file(data_dir)["names"] == ["A", "B"]
        AppSettings.set_owned_items({"A"})
        data = self._file(data_dir)
        assert data["names"] == ["A"]
        assert [s["names"] for s in data["snapshots"]] == [["A", "B"]]

    def test_nothing_is_written_while_everything_is_empty(self, data_dir):
        assert AppSettings.write_owned_items_backup_file() is False
        assert not (data_dir / "owned_blueprints_backup").exists()

    def test_a_settings_reset_keeps_the_file_and_restore_offers_it(self, data_dir, tmp_path):
        AppSettings.set_owned_items({"A", "B", "C"})
        # The settings are wiped (uninstaller, reset), the file stays.
        AppSettings._backend = JsonSettings(tmp_path / "fresh.json")
        assert AppSettings.write_owned_items_backup_file() is False
        assert self._file(data_dir)["names"] == ["A", "B", "C"]
        assert _names(AppSettings.get_owned_items_restore_points()) == [["A", "B", "C"]]
        # A scan then writes a small new list: the old one stays in the file.
        AppSettings.set_owned_items({"New"})
        data = self._file(data_dir)
        assert data["names"] == ["New"]
        assert ["A", "B", "C"] in [s["names"] for s in data["snapshots"]]

    def test_restore_points_list_each_list_once(self, data_dir):
        AppSettings.set_owned_items({"A", "B"})
        AppSettings.set_owned_items({"A"})
        points = _names(AppSettings.get_owned_items_restore_points())
        assert sorted(map(tuple, points)) == [("A",), ("A", "B")]

    def test_an_unreadable_file_offers_nothing(self, data_dir):
        path = data_dir / "owned_blueprints_backup" / "owned_blueprints.json"
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        assert AppSettings.read_owned_items_backup_file() == []

    def test_a_failed_file_write_still_writes_the_list(self, data_dir, monkeypatch):
        def broken():
            raise OSError("no data folder")

        monkeypatch.setattr(AppSettings, "get_user_data_dir", staticmethod(broken))
        AppSettings.set_owned_items({"A"})
        assert AppSettings.get_owned_items() == {"A"}

    def test_the_path_is_in_the_data_folder(self, monkeypatch, tmp_path):
        monkeypatch.undo()  # drop conftest's tmp path for the real function
        monkeypatch.setattr(AppSettings, "get_user_data_dir", staticmethod(lambda: tmp_path))
        assert AppSettings.get_owned_items_backup_path() == (
            tmp_path / OWNED_BACKUP_FOLDER / OWNED_BACKUP_FILE
        )

    def test_the_folder_moves_with_the_data(self):
        from src.utils.user_ini_manager import OWNED_DATA_FOLDERS
        assert OWNED_BACKUP_FOLDER in OWNED_DATA_FOLDERS

    def test_the_uninstaller_never_names_the_folder(self):
        text = (Path(__file__).resolve().parent.parent / "installer.iss").read_text("utf-8")
        code = [ln for ln in text.splitlines() if OWNED_BACKUP_FOLDER in ln]
        # Only the warning text names it: the wipe keeps the folder.
        assert code and all("'" in ln and "DelTree" not in ln for ln in code)
