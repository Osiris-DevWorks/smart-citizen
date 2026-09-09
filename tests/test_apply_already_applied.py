"""Tests for _matches_applied_output (#387): the Apply button should start
green, not unconditionally red, when the currently loaded state already
matches what's on disk in the game's global.ini.

The comparison walks stock_dict's own keys, not merged_dict's, because
merge_ini_files (the real writer) only ever overwrites a key present in its
structure-preservation source file -- a key merged_dict carries that
stock_dict lacks is never actually written, so it must never influence this
result, or a profile with such a key would show a false "dirty" on every
launch even immediately after a genuine apply.
"""
from __future__ import annotations

import pytest

from src.gui.main_window import _matches_applied_output

pytestmark = pytest.mark.unit


class TestMatchesAppliedOutput:
    def test_empty_stock_dict_is_vacuously_true(self):
        assert _matches_applied_output({}, {}, {}) is True

    def test_untouched_stock_values_match(self):
        """No overrides in merged_dict: applied_dict must equal stock as-is."""
        stock = {"a": "1", "b": "2"}
        applied = {"a": "1", "b": "2"}
        assert _matches_applied_output(stock, {}, applied) is True

    def test_stale_stock_value_on_disk_is_dirty(self):
        """Nothing overrides "a", but the on-disk value has drifted from
        stock (e.g. a stock update since the last apply) -- needs re-apply."""
        stock = {"a": "1"}
        applied = {"a": "stale"}
        assert _matches_applied_output(stock, {}, applied) is False

    def test_applied_override_already_matches(self):
        """merged_dict overrides "a"; the file already has that override."""
        stock = {"a": "1"}
        merged = {"a": "overridden"}
        applied = {"a": "overridden"}
        assert _matches_applied_output(stock, merged, applied) is True

    def test_applied_override_not_yet_written_is_dirty(self):
        """merged_dict overrides "a", but the file still has the stock
        value -- a real apply would change it."""
        stock = {"a": "1"}
        merged = {"a": "overridden"}
        applied = {"a": "1"}
        assert _matches_applied_output(stock, merged, applied) is False

    def test_merged_key_outside_stock_is_ignored(self):
        """merge_ini_files never writes a key stock_dict doesn't have --
        such a key in merged_dict must not affect the verdict either way."""
        stock = {"a": "1"}
        merged = {"a": "1", "enhancement_only_key": "something new"}
        applied = {"a": "1"}  # the extra key was never written
        assert _matches_applied_output(stock, merged, applied) is True

    def test_missing_key_in_applied_file_is_dirty(self):
        stock = {"a": "1"}
        applied = {}  # key absent from the file entirely
        assert _matches_applied_output(stock, {}, applied) is False

    def test_mixed_stock_keys_some_overridden_some_not(self):
        stock = {"a": "1", "b": "2", "c": "3"}
        merged = {"b": "overridden"}
        applied = {"a": "1", "b": "overridden", "c": "3"}
        assert _matches_applied_output(stock, merged, applied) is True

        # Flip one stock-passthrough key stale -> dirty.
        applied_stale = {"a": "1", "b": "overridden", "c": "STALE"}
        assert _matches_applied_output(stock, merged, applied_stale) is False
