"""#349: the Help / Test Plan docks must open wide enough to read.

Two halves to the bug. The hard cap came from the strings tab's preview
pane demanding a 420px minimum: a minimum on any central-widget child is a
floor on the whole central widget, and QMainWindow will not grow a dock past
the point where the central widget would breach it, so the docks could never
get wider than `window - central_minimum`. The soft half is that a dock Qt
has never sized opens at a sliver.

`_widen_dock_for_reading` is driven on a real QMainWindow (offscreen) rather
than a stub, because the behaviour under test IS Qt's dock layout arithmetic.
No settings are touched.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import (  # noqa: E402
    QDockWidget,
    QMainWindow,
    QTextBrowser,
    QWidget,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from src.gui.main_window import MainWindow  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]


class _DockWindow(QMainWindow):
    """A real main window with a right-hand text dock, no app dependencies."""

    _READABLE_DOCK_WIDTH = MainWindow._READABLE_DOCK_WIDTH
    _widen_dock_for_reading = MainWindow._widen_dock_for_reading

    def __init__(self, central_min_width: int):
        super().__init__()
        central = QWidget()
        central.setMinimumWidth(central_min_width)
        self.setCentralWidget(central)
        self.dock = QDockWidget("Help", self)
        self.dock.setObjectName("helpDock")
        self.dock.setWidget(QTextBrowser(self.dock))
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
        self.resize(1280, 800)


def test_widens_a_sliver_dock(qapp):
    win = _DockWindow(central_min_width=400)
    win.show()
    win.resizeDocks([win.dock], [80], Qt.Orientation.Horizontal)
    qapp.processEvents()

    win._widen_dock_for_reading(win.dock)
    qapp.processEvents()
    assert win.dock.width() >= win._READABLE_DOCK_WIDTH
    win.close()


def test_leaves_an_already_wide_dock_alone(qapp):
    """A width the user dragged (or restoreState brought back) must survive;
    the helper only ever rescues a dock from below the readable floor."""
    win = _DockWindow(central_min_width=400)
    win.show()
    wide = win._READABLE_DOCK_WIDTH + 260
    win.resizeDocks([win.dock], [wide], Qt.Orientation.Horizontal)
    qapp.processEvents()
    before = win.dock.width()

    win._widen_dock_for_reading(win.dock)
    qapp.processEvents()
    assert win.dock.width() == before
    win.close()


def test_never_forces_the_window_wider(qapp):
    """Qt clamps the request against the central widget's minimum. Even with
    a greedy central minimum the helper must not grow the window itself."""
    win = _DockWindow(central_min_width=1100)
    win.show()
    qapp.processEvents()
    width_before = win.width()

    win._widen_dock_for_reading(win.dock)
    qapp.processEvents()
    assert win.width() == width_before
    win.close()


def test_preview_pane_minimum_leaves_room_for_a_readable_dock(qapp):
    """The regression that caused #349. The preview pane's minimum width is
    a floor on the central widget, so it directly bounds every side dock. At
    the old 420 a 1280-wide window had ~254px of dock left; assert the
    current value keeps a readable dock reachable at that window size.
    """
    import inspect

    from src.gui import main_window as mw

    src = inspect.getsource(mw.MainWindow.create_strings_tab)
    assert "self.preview_pane.setMinimumWidth(220)" in src, (
        "preview pane minimum changed; re-check the dock width budget in #349"
    )

    # The rest of the filter row (combos + capped buttons) measured ~606px;
    # the assertion below is on the pane's own contribution, which is the
    # part #349 moved.
    narrow_window = 1280
    other_row_widgets = 606
    dock_budget = narrow_window - (other_row_widgets + 220)
    assert dock_budget >= MainWindow._READABLE_DOCK_WIDTH
