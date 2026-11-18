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
from src.utils.settings import AppSettings  # noqa: E402


@pytest.fixture
def json_backend(tmp_path):
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
