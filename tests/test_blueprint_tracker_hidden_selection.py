"""BlueprintTrackerTab._selected_names: hidden rows must not be actionable.

Review finding on #374/PR #376 (Osiris, 2026-08-27): hiding a QListWidgetItem
does not deselect it, and both the Available and Owned lists allow
ExtendedSelection. Once the search box / dropdowns started filtering the
Owned list too, a selection made before filtering could survive a filter
change with some rows now hidden -- and Remove read selectedItems() with no
visibility check, so it could silently un-own items the user could no longer
see. Same class of silent ownership loss #372 was filed over, reached
through a filter instead of a foreign log name.

`_selected_names` doesn't reference `self` at all, so it's driven directly
against a real QListWidget -- no stub, no constructed tab, no pytest-qt.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import (  # noqa: E402
    QAbstractItemView, QListWidget, QListWidgetItem,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _list_with(names, hidden=()) -> QListWidget:
    lst = QListWidget()
    # Matches the real tab's lists (blueprint_tracker_tab.py:325,349) -- a
    # bare QListWidget defaults to SingleSelection, under which selecting a
    # second item silently deselects the first, which made an earlier draft
    # of this test's _select_all() collapse to "only the last item" and fail
    # against the real (correct) fix.
    lst.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    for name in names:
        item = QListWidgetItem(name)
        item.setData(Qt.ItemDataRole.UserRole, name)
        lst.addItem(item)
        # setHidden is a no-op before the item has a listWidget() -- must
        # follow addItem, not precede it (caught by this test failing
        # against the real fix on first run).
        item.setHidden(name in hidden)
    return lst


def _select_all(lst: QListWidget) -> None:
    for i in range(lst.count()):
        lst.item(i).setSelected(True)


def test_hidden_selected_rows_are_excluded(qapp):
    from src.gui.blueprint_tracker_tab import BlueprintTrackerTab

    lst = _list_with(["Colossus", "Defiant", "Endurance"], hidden={"Defiant", "Endurance"})
    _select_all(lst)  # selected before the filter hid two of them, exactly the reported sequence

    assert BlueprintTrackerTab._selected_names(None, lst) == ["Colossus"]


def test_all_visible_selected_rows_are_returned(qapp):
    from src.gui.blueprint_tracker_tab import BlueprintTrackerTab

    lst = _list_with(["Colossus", "Defiant"])
    _select_all(lst)

    assert BlueprintTrackerTab._selected_names(None, lst) == ["Colossus", "Defiant"]


def test_all_selected_hidden_returns_empty(qapp):
    """The exact shape that must not silently un-own anything: everything the
    user can currently see selected is nothing, because everything selected
    is hidden -- Remove must no-op, not act on the invisible selection."""
    from src.gui.blueprint_tracker_tab import BlueprintTrackerTab

    lst = _list_with(["Colossus", "Defiant"], hidden={"Colossus", "Defiant"})
    _select_all(lst)

    assert BlueprintTrackerTab._selected_names(None, lst) == []


def test_unselected_hidden_rows_are_irrelevant(qapp):
    """A hidden row that was never selected shouldn't matter either way --
    only 'selected AND hidden' is the case being guarded against."""
    from src.gui.blueprint_tracker_tab import BlueprintTrackerTab

    lst = _list_with(["Colossus", "Defiant"], hidden={"Defiant"})
    lst.item(0).setSelected(True)  # Colossus only; Defiant never selected

    assert BlueprintTrackerTab._selected_names(None, lst) == ["Colossus"]
