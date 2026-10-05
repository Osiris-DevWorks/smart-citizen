"""PyQt6 must still notice when Qt deletes an object Qt created itself.

PyQt6 marks the Python wrapper of a Qt-created object (a view's own scroll
bar, the action ``QMenu.addAction(str)`` returns, ``QMainWindow.statusBar()``)
as deleted when Qt destroys it, but only while the process's first
QApplication is alive. The suite used to destroy and rebuild its app at the
end of every GUI module, which silently switched that off: wrappers outlived
their objects, Qt reused the memory, and ``findChildren`` then handed back a
dead QScrollBar wrapper for a live QVBoxLayout. That was the intermittent
access violation in tests/test_tab_scrollbar_placement.py.

tests/conftest.py now keeps one QApplication for the whole run. If anything
brings the churn back, these checks fail on every full run instead of the
crash coming back about one run in five, and without that fixture they
error at setup. On their own they only show that one app is enough.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import sip  # noqa: E402
from PyQt6.QtWidgets import QMainWindow, QMenu, QTableView  # noqa: E402

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
], ids=["scroll bar", "menu action", "status bar"])
def test_wrapper_of_a_qt_created_child_dies_with_its_parent(make, one_qapplication_per_session):
    assert one_qapplication_per_session is not None
    parent, child = make()
    assert not sip.isdeleted(child)

    sip.delete(parent)

    assert sip.isdeleted(child), (
        f"PyQt6 no longer tracks Qt-created {type(child).__name__} objects, so "
        "the run has had more than one QApplication; see "
        "one_qapplication_per_session in tests/conftest.py"
    )
