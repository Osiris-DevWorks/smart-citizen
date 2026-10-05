"""Every tab's scrollbars must sit in the same place.

This is the contract the whole change exists to deliver, and it had no test.
It is produced by declarative settings scattered across five builders
(create_strings_tab, create_about_tab, create_faq_tab, create_legal_tab and
LogTab.setup_ui) plus the two status labels being moved above their views, so
reverting any one of them reinstates the misalignment with nothing failing.

The faults being locked out, both reported from the real app:

* The String Editor was the only content tab with no scroll area of its own,
  so its overflow fell through to the window-level scroll area, which renders
  below the tab widget. Measured 70px away from where Config and Enhancements
  put theirs, and outside the tab area entirely.
* A widget below a view stops that view's horizontal bar reaching the tab's
  bottom edge, which left the Log tab 24px out of line.

Deliberately excluded from the comparison:

* ``SingleRowScrollArea`` (the String Editor's filter strip) owns a bar
  *inside* its own 60px box by design, so it is not a tab-level bar.
* The outer content scroll area is the window's last-resort chrome scroller;
  a separate test asserts it stays out of the way entirely.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, Qt  # noqa: E402
from PyQt6.QtWidgets import (  # noqa: E402
    QAbstractScrollArea, QApplication, QScrollArea, QScrollBar,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from src.utils.settings import AppSettings  # noqa: E402
from tests.gui_window import build_main_window, retire_main_window  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]

NARROW = (900, 700)


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def window(qapp, tmp_path_factory):
    """One real MainWindow in Advanced mode, narrow enough to need scrollbars.

    Module-scoped on purpose. Building one per test made the suite crash
    intermittently with an access violation (measured 1 run in 6 with four
    constructions, and this file was the only unstable one). Every test here
    walks all eight tabs from wherever the last one left off, so they don't
    need a fresh window, and one construction is a quarter of the exposure.
    The crash itself turned out to be stale PyQt wrappers left behind by a
    destroyed QApplication (fixed by ``one_qapplication_per_session`` in
    tests/conftest.py), so the module scope is now only about speed.

    MonkeyPatch.context() rather than a bare pytest.MonkeyPatch(): the
    built-in fixture is function-scoped so it can't be used here, and calling
    undo() by hand after the yield would skip it entirely if construction
    raised, leaving the settings backend redirected for every later test in
    the session. The context manager guarantees the undo either way.
    """
    tmp = tmp_path_factory.mktemp("tab_scrollbars")
    with pytest.MonkeyPatch.context() as patch:
        win = build_main_window(tmp, patch, AppSettings.UI_MODE_ADVANCED)
        # A long unwrapped line guarantees the Log tab actually has a
        # horizontal bar to compare; its view is NoWrap precisely so long
        # lines scroll.
        win.log_tab._view.appendPlainText("Y" * 400)
        win.show()
        win.resize(*NARROW)
        for _ in range(8):
            qapp.processEvents()

        yield win

        retire_main_window(win)


def _outer_scroll_area(win):
    for area in win.findChildren(QScrollArea):
        if area.widget() is win._content_widget:
            return area
    return None


def _owning_area(bar):
    parent = bar.parent()
    while parent is not None and not isinstance(parent, QAbstractScrollArea):
        parent = parent.parent()
    return parent


def _is_nested(area, outer):
    """True if this scroll area lives inside another one, ignoring ``outer``.

    A widget inside a scroll area can sit anywhere, including past the
    viewport, because that is what scrolling means: it is below or beside the
    fold, not misplaced. Only a tab's own outermost scrolling widget has a
    position worth asserting against the window.

    ``outer`` is the window-level chrome scroller, which wraps the entire
    content widget and therefore every tab. It has to be excluded from the
    walk or nothing counts as top-level at all.
    """
    parent = area.parent() if area is not None else None
    while parent is not None:
        if parent is outer:
            return False
        if isinstance(parent, QAbstractScrollArea):
            return True
        parent = parent.parent()
    return False


def _tab_level_hbars(win):
    """Visible horizontal bars belonging to a tab's own scrolling widget."""
    from src.gui.main_window import SingleRowScrollArea

    outer = _outer_scroll_area(win)
    found = []
    for bar in win.findChildren(QScrollBar):
        if not bar.isVisible() or bar.orientation() is not Qt.Orientation.Horizontal:
            continue
        area = _owning_area(bar)
        if area is None or area is outer or isinstance(area, SingleRowScrollArea):
            continue
        # Nested areas scroll within their own container, so their bars sit
        # wherever that container has scrolled them and have no business in
        # a comparison of where each tab puts its bar.
        if _is_nested(area, outer):
            continue
        found.append(bar)
    return found


def _walk_tabs(win, qapp):
    """Yield (tab name, visible tab-level horizontal bars) for every tab."""
    for index in range(win.tabs.count()):
        win.tabs.setCurrentIndex(index)
        for _ in range(4):
            qapp.processEvents()
        yield win.tabs.tabText(index), _tab_level_hbars(win)


def test_every_tab_puts_its_horizontal_bar_on_the_same_line(window, qapp):
    seen = {}
    for name, bars in _walk_tabs(window, qapp):
        for bar in bars:
            seen.setdefault(bar.mapTo(window, QPoint(0, 0)).y(), []).append(name)

    # A lower bound on the comparison itself, not just on the result: with a
    # single contributing tab "they all share a y" is vacuously true, so this
    # would still pass while checking nothing. Four tabs overflow at this
    # size today (Config, Enhancements, Blueprint Tracker, Log).
    contributors = {name for names in seen.values() for name in names}
    assert len(contributors) >= 2, (
        f"only {contributors} produced a bar, so nothing was actually "
        f"compared; the alignment assertion below is vacuous"
    )
    assert len(seen) == 1, f"tab bars landed on different lines: {seen}"


def test_no_tab_bar_is_pushed_off_the_right_edge(window, qapp):
    """Pinning each tab's page to its natural width used to push the tabs'
    own bars off the right edge (Config's vertical bar at x=1611 in a 900px
    window), so they looked absent until you scrolled the app sideways.

    Horizontal axis only, and only a tab's own outermost scrolling widget.
    A nested widget legitimately sits past the viewport when scrolled, so
    asserting on its position flags ordinary scrolling as a bug: an earlier
    version of this test did exactly that and failed in CI on the
    Enhancements tab, where content below the fold reported y=802 in a 700px
    window.
    """
    outer = _outer_scroll_area(window)
    pushed_off = []
    for name, _bars in _walk_tabs(window, qapp):
        for bar in window.findChildren(QScrollBar):
            if not bar.isVisible():
                continue
            area = _owning_area(bar)
            if area is None or area is outer or _is_nested(area, outer):
                continue
            x = bar.mapTo(window, QPoint(0, 0)).x()
            if x >= window.width():
                pushed_off.append((name, type(area).__name__, x, window.width()))
    assert not pushed_off, f"tab bars pushed off the right edge: {pushed_off}"


def test_window_level_scrollbar_stays_out_of_the_way(window, qapp):
    """The String Editor's overflow used to fall through to this one, which
    renders below the tab widget and so sat on a different line from every
    other tab's bar."""
    outer = _outer_scroll_area(window)
    assert outer is not None
    for _name, _bars in _walk_tabs(window, qapp):
        assert not outer.horizontalScrollBar().isVisible()


def test_switching_tabs_does_not_resize_the_window(window, qapp):
    """Issue #65: an earlier scroll-area attempt was reverted for causing a
    resize on every tab switch."""
    sizes = {(window.width(), window.height())
             for _name, _bars in _walk_tabs(window, qapp)}
    assert len(sizes) == 1, f"window resized while switching tabs: {sizes}"
