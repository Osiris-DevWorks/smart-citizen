"""Tests for _drop_none_entries (#389): a fresh entries list must never carry
a stray ``None`` past the point it's first received, and the loader's
per-entry sort keys must not be left misaligned when one is dropped.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.gui import main_window
from src.gui.main_window import MainWindow, _drop_none_entries
from src.gui.string_table_model import StringTableModel, _group_sort_key
from src.models.string_model import StringEntry
from src.utils.settings import AppSettings

pytestmark = pytest.mark.unit


class _FakeEntry:
    def __init__(self, key):
        self.key = key


class TestDropNoneEntries:
    def test_no_nones_returns_an_equal_list(self):
        entries = [_FakeEntry("a"), _FakeEntry("b")]
        assert _drop_none_entries(entries) == entries

    def test_empty_list_stays_empty(self):
        assert _drop_none_entries([]) == []

    def test_drops_a_single_none_preserving_order(self):
        a, b, c = _FakeEntry("a"), _FakeEntry("b"), _FakeEntry("c")
        assert _drop_none_entries([a, None, b, c]) == [a, b, c]

    def test_drops_multiple_nones(self):
        a, b = _FakeEntry("a"), _FakeEntry("b")
        assert _drop_none_entries([None, a, None, b, None]) == [a, b]

    def test_all_none_returns_empty_list(self):
        assert _drop_none_entries([None, None]) == []

    def test_logs_a_warning_only_when_something_was_actually_dropped(self, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger="src.gui.main_window"):
            _drop_none_entries([_FakeEntry("a"), _FakeEntry("b")])
        assert not caplog.records

        with caplog.at_level(logging.WARNING, logger="src.gui.main_window"):
            _drop_none_entries([_FakeEntry("a"), None])
        assert len(caplog.records) == 1
        assert "#389" in caplog.records[0].message


def _entry(key):
    return StringEntry(key=key, source_file="global", category="Misc",
                       original_value=key, custom_value="", status="Unmodified")


def _window(model):
    """A stand-in for MainWindow carrying just what _on_loading_finished touches."""
    win = MagicMock()
    win._loading_progress = None
    win._loader_worker = None
    win._snapshot_pending_user_edits.return_value = {}
    win._restore_pending_user_edits.return_value = 0
    win._check_enhancements_after_loading = False
    win._initial_load_done = True
    win._model = model
    return win


class TestLoadingFinishedSortKeys:
    """FileLoaderWorker builds one sort key per entry before the slot runs, so
    dropping an entry would leave every later key one slot off."""

    KEYS = ("item_NameCharlie", "item_NameAlpha", "item_DescCharlie",
            "item_NameBravo", "item_DescAlpha", "item_DescBravo")

    @pytest.fixture(autouse=True)
    def _isolate(self, monkeypatch):
        monkeypatch.setattr(
            AppSettings, "get_favorite_prefix", staticmethod(lambda: "*"))
        monkeypatch.setattr(main_window, "QTimer", MagicMock())

    def test_keys_reach_the_model_untouched_when_nothing_was_dropped(self):
        entries = [_entry(k) for k in self.KEYS]
        sort_keys = [_group_sort_key(k) for k in self.KEYS]
        model = MagicMock()

        MainWindow._on_loading_finished(_window(model), entries, {}, sort_keys)

        assert model.set_data_source.call_args.kwargs["sort_keys"] is sort_keys

    def test_keys_stay_aligned_with_entries_after_a_drop(self):
        entries = [_entry(k) for k in self.KEYS]
        sort_keys = [_group_sort_key(k) for k in self.KEYS]
        entries[1] = None
        model = StringTableModel()

        MainWindow._on_loading_finished(_window(model), entries, {}, sort_keys)

        assert len(model._entries) == len(self.KEYS) - 1
        assert model._sort_keys == [_group_sort_key(e.key) for e in model._entries]
