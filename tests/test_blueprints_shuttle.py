"""Blueprints shuttle available/owned split (#157 follow-up; tab split #222).

The Blueprint Tracker tab splits the full blueprint-item universe into an
Available list (not yet owned) and an Owned list. The split itself is a pure
staticmethod so it can be tested without a QApplication.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.gui.blueprint_tracker_tab import BlueprintTrackerTab  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_split = BlueprintTrackerTab._available_blueprints


def test_available_excludes_owned():
    out = _split({"Balandin", "Erebos", "Norfield"}, {"Erebos"})
    assert out == ["Balandin", "Norfield"]


def test_available_sorted_case_insensitively():
    out = _split({"zeus", "Apollo", "balandin"}, set())
    assert out == ["Apollo", "balandin", "zeus"]


def test_owned_not_in_universe_does_not_appear_in_available():
    # An owned item that fell out of the universe (channel switch, CIG drop)
    # must not surface as available — it is simply absent here. The Owned list
    # still renders it from the persisted set, so the user can un-own it.
    out = _split({"Norfield"}, {"GhostItem"})
    assert out == ["Norfield"]


def test_empty_universe_yields_empty_available():
    assert _split(set(), {"Erebos"}) == []
    assert _split(set(), set()) == []


def test_accepts_list_inputs():
    out = _split(["B", "A", "C"], ["A"])
    assert out == ["B", "C"]


_sort_key = BlueprintTrackerTab._facet_sort_key


class TestFacetSortKey:
    def test_size_sorts_numerically_not_lexicographically(self):
        values = sorted(["10", "2", "1", "0", "9"], key=lambda v: _sort_key("size", v))
        assert values == ["0", "1", "2", "9", "10"]

    def test_type_sorts_alphabetically_with_other_last(self):
        values = sorted(["Other", "Shield", "Armor"], key=lambda v: _sort_key("type", v))
        assert values == ["Armor", "Shield", "Other"]

    def test_size_non_numeric_falls_back_to_string_sort(self):
        # Defensive: shouldn't happen in practice (size is always bare digits
        # after strip_size_prefix), but must not raise.
        values = sorted(["b", "a"], key=lambda v: _sort_key("size", v))
        assert values == ["a", "b"]
