"""Tests for _drop_none_entries (#389): a fresh entries list must never carry
a stray ``None`` past the point it's first received.

Filtering only where a crash was actually observed (update_category_combo's
``e.category`` read) wasn't enough -- ``_restore_pending_user_edits`` reads
``e.key`` on every entry earlier in the same reload path and would crash
there first whenever the snapshot is non-empty, and the table model reads
entries straight from ``self.entries`` afterward regardless. The fix filters
once, at the source, so every downstream consumer sees a clean list.
"""
from __future__ import annotations

import pytest

from src.gui.main_window import _drop_none_entries

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
