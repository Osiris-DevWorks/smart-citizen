"""PyQt6 must still notice when Qt deletes an object Qt created itself.

PyQt6 marks the Python wrapper of a Qt-created object (a view's own scroll
bar, the action ``QMenu.addAction(str)`` returns, ``QMainWindow.statusBar()``)
as deleted when Qt destroys it, but only while the process's first
QApplication is alive. The suite used to destroy and rebuild its app at the
end of every GUI module, which silently switched that off: wrappers outlived
their objects, Qt reused the memory, and ``findChildren`` then handed back a
dead QScrollBar wrapper for a live QVBoxLayout. That was the intermittent
access violation in tests/test_tab_scrollbar_placement.py.

tests/conftest.py now keeps one QApplication for the whole run (the ``qapp``
fixture), and its ``qapp_still_in_place`` guard fails any module that
destroys or replaces it, or makes its own. This file checks the effect PyQt6
depends on. It fails if the run had a second app before this file ran (the
GUI modules that sort after it are covered by the guard alone).
"""
from __future__ import annotations

import pytest
from PyQt6 import sip
from PyQt6.QtWidgets import QMainWindow, QMenu, QTableView

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _scroll_bar_of_a_table():
    table = QTableView()
    return table, table.horizontalScrollBar()


def _action_of_a_menu():
    menu = QMenu()
    return menu, menu.addAction("Restore backup")


def _status_bar_of_a_window():
    window = QMainWindow()
    return window, window.statusBar()


@pytest.mark.parametrize("make", [
    _scroll_bar_of_a_table,
    _action_of_a_menu,
    _status_bar_of_a_window,
], ids=["scroll_bar", "menu_action", "status_bar"])
def test_wrapper_of_a_qt_created_child_dies_with_its_parent(make, qapp):
    parent, child = make()
    assert not sip.isdeleted(child)

    sip.delete(parent)

    assert sip.isdeleted(child), (
        f"PyQt6 no longer marks a dead Qt-created {type(child).__name__} as "
        "deleted. Either the run has had more than one QApplication (see the "
        "qapp fixture in tests/conftest.py) or PyQt6 changed how it tracks "
        "objects Qt creates itself"
    )
