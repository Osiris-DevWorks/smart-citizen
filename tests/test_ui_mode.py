"""Simple/Advanced UI mode (#180).

Three layers:

* The AppSettings contract: default is 'simple', round-trips, and any
  unrecognized stored value coerces back to 'simple'.
* The SimpleModeWidget: its two buttons emit the right intent signals,
  ``set_busy`` disables the action, and ``set_apply_dirty`` (#397) mirrors
  the Advanced-mode Apply button's red/green convention -- busy always
  wins for enabled state, dirty always decides color.
* ``MainWindow._apply_ui_mode``: shows one view and hides the other, along
  with the advanced toolbar. Driven on a lightweight stand-in ``self`` (the
  real unbound method) so we don't construct the whole window, which pulls in
  the full startup pipeline (no pytest-qt in dev deps — see tests/CLAUDE.md).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSettings, QSize, QRect  # noqa: E402
from PyQt6.QtWidgets import (  # noqa: E402
    QApplication, QTabWidget, QWidget,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Import via the same path src/gui/main_window.py uses (`src.utils.settings`)
# so monkeypatching AppSettings.settings affects the exact class the window
# sees — `utils.settings` and `src.utils.settings` are distinct module objects
# under this repo's dual pythonpath.
from src.utils.settings import AppSettings  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    shared = QSettings(str(tmp_path / "reg.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(AppSettings, "settings", staticmethod(lambda: shared))


# ── Settings contract ───────────────────────────────────────────────────────

def test_default_is_simple(isolated_settings):
    assert AppSettings.get_ui_mode() == AppSettings.UI_MODE_SIMPLE


def test_roundtrip(isolated_settings):
    AppSettings.set_ui_mode(AppSettings.UI_MODE_ADVANCED)
    assert AppSettings.get_ui_mode() == AppSettings.UI_MODE_ADVANCED
    AppSettings.set_ui_mode(AppSettings.UI_MODE_SIMPLE)
    assert AppSettings.get_ui_mode() == AppSettings.UI_MODE_SIMPLE


def test_unknown_stored_value_coerces_to_simple(isolated_settings):
    AppSettings.settings().setValue(AppSettings.UI_MODE, "banana")
    assert AppSettings.get_ui_mode() == AppSettings.UI_MODE_SIMPLE


def test_set_unknown_value_coerces_to_simple(isolated_settings):
    AppSettings.set_ui_mode("nonsense")
    assert AppSettings.get_ui_mode() == AppSettings.UI_MODE_SIMPLE


# ── SimpleModeWidget ────────────────────────────────────────────────────────

def test_simple_widget_signals(qapp):
    from src.gui.simple_mode_widget import SimpleModeWidget

    w = SimpleModeWidget()
    hits = []
    w.generate_and_apply_requested.connect(lambda: hits.append("generate"))
    w.switch_to_advanced_requested.connect(lambda: hits.append("advanced"))
    w.generate_apply_btn.click()
    w.advanced_btn.click()
    assert hits == ["generate", "advanced"]


def test_simple_widget_set_busy(qapp):
    from src.gui.simple_mode_widget import SimpleModeWidget

    w = SimpleModeWidget()
    assert w.generate_apply_btn.isEnabled()
    w.set_busy(True)
    assert not w.generate_apply_btn.isEnabled()
    w.set_busy(False)
    assert w.generate_apply_btn.isEnabled()


def test_simple_widget_starts_dirty(qapp):
    """#397: matches MainWindow._apply_dirty's own pre-load default -- red
    and clickable from construction, not the old hardcoded-green button."""
    from src.gui.simple_mode_widget import SimpleModeWidget
    from src.gui.theme import get_button_color
    from src.utils.i18n import tr

    w = SimpleModeWidget()
    assert w.generate_apply_btn.isEnabled()
    assert get_button_color("needs_apply") in w.generate_apply_btn.styleSheet()
    assert w.generate_apply_btn.toolTip() == tr("simple_mode.generate_apply_tip")


def test_simple_widget_set_apply_dirty_toggles_color_enabled_and_tooltip(qapp):
    """#397 follow-up: the tooltip has to swap with dirty state too, not
    just color/enabled -- it was still showing the same static string in
    both states even after the color/enabled half of the fix landed."""
    from src.gui.simple_mode_widget import SimpleModeWidget
    from src.gui.theme import get_button_color
    from src.utils.i18n import tr

    w = SimpleModeWidget()
    w.set_apply_dirty(False)
    assert not w.generate_apply_btn.isEnabled()
    assert get_button_color("apply") in w.generate_apply_btn.styleSheet()
    assert w.generate_apply_btn.toolTip() == tr("simple_mode.generate_apply_tip_disabled")

    w.set_apply_dirty(True)
    assert w.generate_apply_btn.isEnabled()
    assert get_button_color("needs_apply") in w.generate_apply_btn.styleSheet()
    assert w.generate_apply_btn.toolTip() == tr("simple_mode.generate_apply_tip")


def test_simple_widget_busy_overrides_dirty_for_enabled_not_color(qapp):
    """A run in progress must disable the button regardless of dirty state,
    but the color keeps reflecting dirty -- busy is a transient interaction
    lock, not a verdict about whether there's anything to apply."""
    from src.gui.simple_mode_widget import SimpleModeWidget
    from src.gui.theme import get_button_color

    w = SimpleModeWidget()
    w.set_apply_dirty(True)
    w.set_busy(True)
    assert not w.generate_apply_btn.isEnabled()
    assert get_button_color("needs_apply") in w.generate_apply_btn.styleSheet()

    # Clean (green) while busy: still disabled for the busy reason, not
    # re-enabled just because dirty flipped mid-run.
    w.set_apply_dirty(False)
    assert not w.generate_apply_btn.isEnabled()

    # Busy clears: enabled now reflects the dirty state set while busy,
    # not whatever it was before the run started.
    w.set_busy(False)
    assert not w.generate_apply_btn.isEnabled()


# ── _apply_ui_mode swap ─────────────────────────────────────────────────────

class _StubWindow:
    """Minimal stand-in carrying just the widgets _apply_ui_mode touches."""

    def __init__(self, page_width=800):
        # A real QTabWidget, not a bare QWidget: the page's own width hint is
        # what the regression guard below inspects.
        self.tabs = QTabWidget()

        class _Page(QWidget):
            def sizeHint(self):
                return QSize(page_width, 400)

        self.tabs.addTab(_Page(), "page")
        # Siblings in a real layout, swapped by visibility. A hidden widget's
        # layout item is empty, which is the whole mechanism: the page that
        # isn't showing contributes nothing to the window's size.
        from PyQt6.QtWidgets import QVBoxLayout

        self.simple_page = QWidget()
        self.toolbar_container = QWidget()
        self._content_widget = QWidget()
        content_layout = QVBoxLayout(self._content_widget)
        content_layout.addWidget(self.tabs, 1)
        content_layout.addWidget(self.simple_page, 1)
        # _apply_ui_mode only resizes the window when it's already shown; this
        # never-shown stub reports not-visible so the swap is exercised in
        # isolation, without the sizing helper.
        self.isVisible = lambda: False


def test_apply_ui_mode_swaps_page(qapp, isolated_settings):
    from src.gui.main_window import MainWindow

    stub = _StubWindow()

    MainWindow._apply_ui_mode(stub, AppSettings.UI_MODE_SIMPLE)
    assert not stub.simple_page.isHidden()
    assert stub.tabs.isHidden()
    assert stub.toolbar_container.isHidden()
    assert AppSettings.get_ui_mode() == AppSettings.UI_MODE_SIMPLE

    MainWindow._apply_ui_mode(stub, AppSettings.UI_MODE_ADVANCED)
    assert not stub.tabs.isHidden()
    assert stub.simple_page.isHidden()
    assert not stub.toolbar_container.isHidden()
    assert AppSettings.get_ui_mode() == AppSettings.UI_MODE_ADVANCED


def test_hidden_page_contributes_no_height(qapp, isolated_settings):
    """The reason the stack went: a QStackedWidget reports its tallest page,
    so Simple kept reserving height for the Advanced tabs (measured 323px
    against the 214 it needed). A hidden sibling reserves nothing."""
    from src.gui.main_window import MainWindow

    stub = _StubWindow(page_width=800)
    layout = stub._content_widget.layout()

    MainWindow._apply_ui_mode(stub, AppSettings.UI_MODE_ADVANCED)
    with_tabs = layout.sizeHint().height()

    MainWindow._apply_ui_mode(stub, AppSettings.UI_MODE_SIMPLE)
    with_simple = layout.sizeHint().height()

    # The tabs page is the taller of the two, so Simple must ask for less.
    assert with_simple < with_tabs


# ── Scrollbar placement ─────────────────────────────────────────────────────
#
# An earlier attempt pinned the active tab page's minimumWidth to its natural
# width, to stop widgets squishing as the window narrowed. That backfired: a
# minimumWidth on a QStackedWidget page is a hard constraint that propagates
# into the window's own minimum, so the String Editor's 2238px page inflated
# the whole canvas to 2258px inside a 900px window. Two visible faults came
# out of that, both reported by the user:
#
#   * the only reachable scrollbar was the window-level one, sitting outside
#     the tab area on a different line from every other tab's bar, and
#   * each tab's own bars rendered off the right edge (Config's vertical bar
#     at x=1611 in a 900px window), so they looked absent until you scrolled
#     the whole application sideways to find them.
#
# The floor was also redundant: the only widget it protected was the filter
# row, which already contains its own overflow via SingleRowScrollArea, and
# the floor was defeating that wrapper. Each tab now contains its own
# overflow, which is what keeps every tab's bars in the same pixel row.

def test_apply_ui_mode_never_pins_a_tab_page_width(qapp, isolated_settings):
    """A minimumWidth on a QStackedWidget page propagates into the window's
    own minimum, which is what pushed the tab's scrollbars off the right
    edge and moved the only visible bar outside the tab area."""
    from src.gui.main_window import MainWindow

    stub = _StubWindow(page_width=800)
    MainWindow._apply_ui_mode(stub, AppSettings.UI_MODE_ADVANCED)
    assert stub.tabs.widget(0).minimumWidth() == 0


# ── Reset Window Proportions ────────────────────────────────────────────────
#
# The settings-layer clear is covered in test_window_state_portable.py; this
# covers the action itself, which also has to restore the dock layout snapshot,
# hand the columns back to the default layout, and re-apply the mode-driven
# window size.

class _ResetStub:
    """Stand-in carrying what _reset_window_proportions touches."""

    def __init__(self):
        from src.gui.main_window import MainWindow

        self.calls = []
        self._default_window_state = b"DOCKSTATE"
        self._user_resized_columns = True
        self._geometry_restored = True

    def restoreState(self, state):
        self.calls.append(("restoreState", state))

    def _apply_default_column_layout(self):
        self.calls.append("columns")

    def _size_window_for_mode(self, mode):
        self.calls.append(("size", mode))

    def statusBar(self):
        stub = self

        class _Bar:
            def showMessage(self, msg, timeout=0):
                stub.calls.append("status")

        return _Bar()


def _run_reset(stub, monkeypatch, confirm=True):
    """Drive the real method with the confirmation dialog answered."""
    from PyQt6.QtWidgets import QMessageBox
    from src.gui.main_window import MainWindow

    answer = (QMessageBox.StandardButton.Yes if confirm
              else QMessageBox.StandardButton.No)
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: answer))
    MainWindow._reset_window_proportions(stub)


def test_reset_restores_defaults(qapp, isolated_settings, monkeypatch):
    AppSettings.set_ui_mode(AppSettings.UI_MODE_ADVANCED)
    AppSettings.set_string_column_widths([10, 20, 30])
    stub = _ResetStub()

    _run_reset(stub, monkeypatch)

    assert AppSettings.get_string_column_widths() == []
    assert ("restoreState", b"DOCKSTATE") in stub.calls
    assert "columns" in stub.calls
    assert ("size", AppSettings.UI_MODE_ADVANCED) in stub.calls


def test_reset_hands_columns_back_to_the_default_layout(qapp, isolated_settings,
                                                        monkeypatch):
    """Clearing the handover flag is what lets the default layout be
    recomputed and keep tracking the window again."""
    stub = _ResetStub()
    _run_reset(stub, monkeypatch)
    assert stub._user_resized_columns is False


def test_reset_lets_the_mode_driven_size_apply_again(qapp, isolated_settings,
                                                     monkeypatch):
    """With the saved geometry gone, the window must fall back to the
    mode-driven default rather than staying where the user left it."""
    stub = _ResetStub()
    _run_reset(stub, monkeypatch)
    assert stub._geometry_restored is False


def test_reset_does_nothing_when_declined(qapp, isolated_settings, monkeypatch):
    AppSettings.set_string_column_widths([10, 20, 30])
    stub = _ResetStub()

    _run_reset(stub, monkeypatch, confirm=False)

    assert AppSettings.get_string_column_widths() == [10, 20, 30]
    assert stub.calls == []
    assert stub._user_resized_columns is True


# ── Saved geometry vs the mode-driven default size ──────────────────────────
#
# Advanced opens maximized and Simple opens compact, but only on a first run.
# Once the user has moved or resized the window, their saved geometry must
# win: without the guard, showEvent's mode-driven sizing fires immediately
# after restoreGeometry() and persisting geometry has no visible effect.

class _ShowEventStub:
    """Stand-in for the bits of MainWindow.showEvent's sizing branch."""

    def __init__(self, geometry_restored):
        self._geometry_restored = geometry_restored
        self.sized_for_mode = []
        self._tutorial_started = False

    def _size_window_for_mode(self, mode):
        self.sized_for_mode.append(mode)

    def _maybe_start_first_run_tutorial(self):
        self._tutorial_started = True


def _run_show_event_sizing(stub):
    """Mirror showEvent's guarded sizing branch against the stub."""
    if not getattr(stub, "_initial_size_applied", False):
        stub._initial_size_applied = True
        if not getattr(stub, "_geometry_restored", False):
            stub._size_window_for_mode(AppSettings.get_ui_mode())


def test_saved_geometry_suppresses_mode_driven_sizing(qapp, isolated_settings):
    AppSettings.set_ui_mode(AppSettings.UI_MODE_ADVANCED)
    stub = _ShowEventStub(geometry_restored=True)
    _run_show_event_sizing(stub)
    assert stub.sized_for_mode == []


def test_first_run_still_gets_mode_driven_sizing(qapp, isolated_settings):
    """No saved geometry: every fresh install opens at the same default."""
    AppSettings.set_ui_mode(AppSettings.UI_MODE_ADVANCED)
    stub = _ShowEventStub(geometry_restored=False)
    _run_show_event_sizing(stub)
    assert stub.sized_for_mode == [AppSettings.UI_MODE_ADVANCED]


def test_mode_sizing_applies_only_once(qapp, isolated_settings):
    AppSettings.set_ui_mode(AppSettings.UI_MODE_ADVANCED)
    stub = _ShowEventStub(geometry_restored=False)
    for _ in range(3):
        _run_show_event_sizing(stub)
    assert stub.sized_for_mode == [AppSettings.UI_MODE_ADVANCED]


# ── User-resizable columns ──────────────────────────────────────────────────
#
# Every column is Interactive, permanently, because that is the only mode Qt
# lets the user drag and the only one it auto-fits on a divider double-click.
# Interactive has no opinion about width, so the default layout is computed
# arithmetically to match what Stretch/ResizeToContents used to produce, and
# recomputed on every table resize until the user takes over.
#
# It has to be computed rather than measured: Qt defers the real section
# layout, so reading sectionSize() straight after setting a mode returns the
# PREVIOUS layout. That stale read left the columns summing to 1598 in an
# 1886px viewport after a Simple-to-Advanced switch and never catching up.
# Flipping the modes back and forth around a deferred capture fixed the width
# but left the sections non-draggable in between, silently discarding a drag
# that landed in that window — hence computing them outright.

class _ColumnStub:
    """Carries just what _apply_default_column_layout touches."""

    N_COLUMNS = 9        # matches the real table, so the modes map applies

    def __init__(self, viewport_width=1000):
        from PyQt6.QtWidgets import QTableView
        from src.gui.main_window import MainWindow

        self.table = QTableView()
        self.table.setModel(_widths_model(self.N_COLUMNS))
        self.filter_header = self.table.horizontalHeader()
        self._user_resized_columns = False
        self._suppress_column_capture = False
        # Bound for real, like _SizeStub does with _window_size_for_content.
        self._default_column_modes = MainWindow._default_column_modes
        self._default_column_widths = lambda: MainWindow._default_column_widths(self)
        self._section_hint_cache = None
        self._section_size_hints = (
            lambda header, count: MainWindow._section_size_hints(self, header, count)
        )
        # Shown, because an unshown QTableView never lays its viewport out and
        # viewport().width() is what the default layout divides up.
        self.table.show()
        self.resize_to(viewport_width)

    def resize_to(self, width):
        QApplication.processEvents()
        self.table.resize(width, 300)
        QApplication.processEvents()


def _widths_model(n):
    from PyQt6.QtGui import QStandardItemModel

    m = QStandardItemModel(2, n)
    return m


def _stretch_columns():
    from PyQt6.QtWidgets import QHeaderView
    from src.gui.main_window import MainWindow

    return [c for c, m in MainWindow._default_column_modes().items()
            if m == QHeaderView.ResizeMode.Stretch]


def test_default_layout_makes_every_column_interactive(qapp, isolated_settings):
    """Interactive is the only mode Qt lets the user drag, and the only one
    it auto-fits on a divider double-click."""
    from PyQt6.QtWidgets import QHeaderView
    from src.gui.main_window import MainWindow

    stub = _ColumnStub()
    MainWindow._apply_default_column_layout(stub)
    h = stub.filter_header
    assert all(h.sectionResizeMode(i) == QHeaderView.ResizeMode.Interactive
               for i in range(h.count()))


def test_default_layout_fills_the_viewport(qapp, isolated_settings):
    """The Stretch columns split whatever the fixed columns leave, so the
    layout spans the viewport exactly — the behaviour the old Stretch modes
    gave, and what makes a fresh install look unchanged."""
    from src.gui.main_window import MainWindow

    stub = _ColumnStub()
    MainWindow._apply_default_column_layout(stub)
    h = stub.filter_header
    total = sum(h.sectionSize(i) for i in range(h.count()))
    assert total == stub.table.viewport().width()
    assert not stub._user_resized_columns   # nothing to persist yet


def test_default_layout_splits_the_remainder_evenly(qapp, isolated_settings):
    """Qt hands the leftover pixels out one at a time rather than dropping
    them, so the stretch columns differ by at most 1px."""
    from src.gui.main_window import MainWindow

    stub = _ColumnStub()
    MainWindow._apply_default_column_layout(stub)
    h = stub.filter_header
    widths = [h.sectionSize(c) for c in _stretch_columns()]
    assert max(widths) - min(widths) <= 1


def test_default_layout_tracks_a_wider_viewport(qapp, isolated_settings):
    """The Simple-to-Advanced bug: the columns were computed while the window
    was still Simple-sized and stayed tiny once it maximised."""
    from src.gui.main_window import MainWindow

    stub = _ColumnStub(viewport_width=700)
    MainWindow._apply_default_column_layout(stub)
    narrow = sum(stub.filter_header.sectionSize(i)
                 for i in range(stub.filter_header.count()))

    stub.resize_to(1600)
    MainWindow._apply_default_column_layout(stub)
    wide = sum(stub.filter_header.sectionSize(i)
               for i in range(stub.filter_header.count()))

    assert wide > narrow
    assert wide == stub.table.viewport().width()


def test_default_layout_prefers_saved_widths(qapp, isolated_settings):
    from src.gui.main_window import MainWindow

    saved = [110, 220, 330, 120, 60, 60, 140, 90, 80]
    AppSettings.set_string_column_widths(saved)
    stub = _ColumnStub()
    MainWindow._apply_default_column_layout(stub)
    h = stub.filter_header
    assert [h.sectionSize(i) for i in range(h.count())] == saved
    assert stub._user_resized_columns       # keep persisting their choice


def test_saved_width_below_the_minimum_is_clamped_not_dropped(qapp, isolated_settings):
    """Qt refuses to size a section below minimumSectionSize. A saved width
    under it must still be applied (clamped), never rejected outright — a
    column the user dragged tiny should come back tiny, not at its default."""
    from src.gui.main_window import MainWindow

    stub = _ColumnStub()
    floor = stub.filter_header.minimumSectionSize()
    AppSettings.set_string_column_widths([1, 220, 330, 120, 60, 60, 140, 90, 80])
    MainWindow._apply_default_column_layout(stub)
    h = stub.filter_header
    assert h.sectionSize(0) == floor
    assert h.sectionSize(1) == 220


def test_default_layout_ignores_saved_widths_of_wrong_length(qapp, isolated_settings):
    """A stored layout from a build with a different column count must be
    dropped wholesale rather than applied piecemeal."""
    from src.gui.main_window import MainWindow

    AppSettings.set_string_column_widths([11, 22])       # 2, table has 9
    stub = _ColumnStub()
    MainWindow._apply_default_column_layout(stub)
    h = stub.filter_header
    assert sum(h.sectionSize(i) for i in range(h.count())) == stub.table.viewport().width()
    assert not stub._user_resized_columns


def test_default_layout_stops_once_the_user_takes_over(qapp, isolated_settings):
    """Once the user owns the layout, neither a data reload nor a window
    resize may recompute it out from under them."""
    from src.gui.main_window import MainWindow

    stub = _ColumnStub()
    stub._user_resized_columns = True            # as if they dragged one
    stub.filter_header.resizeSection(1, 555)
    MainWindow._apply_default_column_layout(stub)
    assert stub.filter_header.sectionSize(1) == 555


def test_programmatic_resize_is_not_a_user_resize(qapp, isolated_settings):
    """QHeaderView emits sectionResized for our own sizing too; only a real
    drag should mark the layout as the user's."""
    from src.gui.main_window import MainWindow

    stub = _ColumnStub()
    stub._suppress_column_capture = True
    MainWindow._on_column_resized(stub, 1, 200, 400)
    assert not stub._user_resized_columns

    stub._suppress_column_capture = False
    MainWindow._on_column_resized(stub, 1, 200, 400)
    assert stub._user_resized_columns


def test_apply_ui_mode_unknown_falls_back_to_simple(qapp, isolated_settings):
    from src.gui.main_window import MainWindow

    stub = _StubWindow()
    MainWindow._apply_ui_mode(stub, "garbage")
    assert not stub.simple_page.isHidden()
    assert stub.tabs.isHidden()


# ── _size_window_for_mode (mode-driven startup size, #180 follow-up) ─────────

from src.gui.main_window import MainWindow  # noqa: E402


class _ContentWidgetStub:
    """Stand-in for MainWindow._content_widget (the real widget wrapped by
    the QScrollArea central widget -- see setup_ui)."""

    def minimumSizeHint(self):
        return QSize(80, 40)

    def sizeHint(self):
        # Same as the minimum here: the height-for-width case that forces
        # them apart on the real window is covered separately below.
        return QSize(80, 40)

    def layout(self):
        return None


class _StyleStub:
    """Stand-in for centralWidget().style() -- only PM_ScrollBarExtent is
    queried, for the anti-flicker padding (see _window_size_for_content)."""

    def pixelMetric(self, metric):
        return 10


class _CentralWidgetStub:
    """Stand-in for self.centralWidget() (the QScrollArea) -- only its
    current actual size matters for the chrome calculation, not any hint."""

    def width(self):
        return 96

    def height(self):
        return 64

    def style(self):
        return _StyleStub()


class _ScreenStub:
    """Stand-in for self.screen() -- only availableGeometry() is queried,
    for _default_advanced_windowed_size's first-run default."""

    def availableGeometry(self):
        return QRect(0, 0, 2000, 1000)


class _SizeStub:
    """Records the window-sizing calls _size_window_for_mode makes, so the
    Advanced=maximized / Simple=shrink-to-fit contract is tested without a
    real top-level window (offscreen QPA doesn't report maximize reliably)."""

    # Bind the real implementation: it's a pure function of self.width()/
    # height() and self.centralWidget().width()/height(), all stubbed below,
    # so there's no need to duplicate its chrome-delta math here.
    _window_size_for_content = MainWindow._window_size_for_content
    # Likewise a pure function of screen().availableGeometry(), stubbed below.
    _default_advanced_windowed_size = MainWindow._default_advanced_windowed_size
    # Reads only _content_widget's hints and layout, both stubbed below.
    _simple_content_size = MainWindow._simple_content_size

    def __init__(self, maximized=False):
        self.calls = []
        self._maximized = maximized
        self._content_widget = _ContentWidgetStub()
        self._central = _CentralWidgetStub()

    def screen(self):
        return _ScreenStub()

    def showMaximized(self):
        self.calls.append("max")
        self._maximized = True

    def showNormal(self):
        self.calls.append("normal")
        self._maximized = False

    def resize(self, size):
        self.calls.append(("resize", size))

    def centralWidget(self):
        return self._central

    def width(self):
        # Window (100, 80) vs central widget (96, 64) -> chrome (4, 16).
        return 100

    def height(self):
        return 80

    def isMaximized(self):
        return self._maximized

    def isFullScreen(self):
        return False


def test_advanced_mode_sizes_window_before_maximizing(qapp):
    """Advanced must set a real windowed size *before* maximizing.

    Windows records the geometry a window last had while un-maximized as
    the rectangle restore-down returns to; maximizing straight from the
    QScrollArea-wrapped startup geometry left that recorded rectangle at a
    useless ~592x444 (confirmed natively via GetWindowPlacement), so
    restore-down handed back a tiny window. The resize below is what makes
    the native restore land somewhere sane.
    """
    from src.gui.main_window import MainWindow

    s = _SizeStub()
    MainWindow._size_window_for_mode(s, AppSettings.UI_MODE_ADVANCED)
    # 85% of the stubbed screen's (2000, 1000) available geometry, then maximize.
    assert s.calls == [("resize", QSize(1700, 850)), "max"]


def test_advanced_mode_already_maximized_does_not_resize(qapp):
    """Resizing an already-maximized window would clobber the real
    windowed geometry Windows has recorded (the size the user actually
    picked while windowed), so the pre-size only applies when there's a
    normal-state geometry to establish in the first place."""
    from src.gui.main_window import MainWindow

    s = _SizeStub(maximized=True)
    MainWindow._size_window_for_mode(s, AppSettings.UI_MODE_ADVANCED)
    assert s.calls == ["max"]


def test_simple_mode_shrinks_to_minimum_when_normal(qapp):
    from src.gui.main_window import MainWindow

    s = _SizeStub()
    MainWindow._size_window_for_mode(s, AppSettings.UI_MODE_SIMPLE)
    # content minimumSizeHint (80, 40) + chrome (4, 16) + scrollbar pad (2*10, 2*10)
    assert s.calls == [("resize", QSize(104, 76))]


def test_switch_from_maximized_unmaximizes_then_defers_shrink(qapp):
    # From a maximized (Advanced) window the shrink is deferred past the async
    # geometry restore, so only the un-maximize is synchronous here.
    from src.gui.main_window import MainWindow

    s = _SizeStub(maximized=True)
    MainWindow._size_window_for_mode(s, AppSettings.UI_MODE_SIMPLE)
    assert s.calls == ["normal"]


def test_deferred_shrink_resizes_when_still_simple(qapp, isolated_settings):
    from src.gui.main_window import MainWindow

    AppSettings.set_ui_mode(AppSettings.UI_MODE_SIMPLE)
    s = _SizeStub()
    MainWindow._shrink_to_fit_if_simple(s)
    # content minimumSizeHint (80, 40) + chrome (4, 16) + scrollbar pad (2*10, 2*10)
    assert s.calls == [("resize", QSize(104, 76))]


def test_deferred_shrink_skipped_if_switched_to_advanced(qapp, isolated_settings):
    # Guards the race: if the user flips back to Advanced before the deferred
    # shrink fires, it must not shrink the maximized window.
    from src.gui.main_window import MainWindow

    AppSettings.set_ui_mode(AppSettings.UI_MODE_ADVANCED)
    s = _SizeStub()
    MainWindow._shrink_to_fit_if_simple(s)
    assert s.calls == []


def test_default_advanced_windowed_size_is_85pct_of_screen(qapp, isolated_settings):
    from src.gui.main_window import MainWindow

    AppSettings.set_ui_mode(AppSettings.UI_MODE_ADVANCED)
    s = _SizeStub()
    # 85% of the stubbed screen's (2000, 1000) available geometry.
    assert MainWindow._default_advanced_windowed_size(s) == QSize(1700, 850)


# ── SingleRowScrollArea ─────────────────────────────────────────────────────
#
# The String Editor's filter row is wrapped in one of these so its ~1300px
# natural width can't propagate up through the outer QScrollArea (see
# setup_ui) and force the whole window wider than a narrow screen. A plain
# QScrollArea reports a generic 576x384 sizeHint with an Expanding vertical
# policy, which made the row render 358px tall for a 44px row (a large
# empty background with the controls floating in it) and let the layout
# squeeze it below its natural width, clipping the trailing buttons. These
# lock the hint/policy contract that fixes both.

def _row_scroll(qapp, row_hint=QSize(1327, 44), row_min=QSize(1327, 44),
                matched_height=0):
    from PyQt6.QtWidgets import QWidget
    from src.gui.main_window import SingleRowScrollArea

    class _Row(QWidget):
        def sizeHint(self):
            return row_hint

        def minimumSizeHint(self):
            return row_min

    sa = SingleRowScrollArea(matched_height=matched_height)
    sa.setWidget(_Row())
    return sa


def test_row_scroll_height_tracks_the_row_not_the_viewport(qapp):
    """The bug: 358px tall for a 44px row. Height must follow the row's own
    hint (plus the reserved scrollbar strip), never the available space."""
    sa = _row_scroll(qapp)
    hbar = sa.horizontalScrollBar().sizeHint().height()
    assert sa.sizeHint().height() == 44 + hbar
    assert sa.minimumSizeHint().height() == 44 + hbar


def test_row_scroll_vertical_policy_is_fixed(qapp):
    """Qt's default Expanding vertical policy is what let the row grow into
    all the spare space; Fixed makes the layout honour sizeHint exactly."""
    from PyQt6.QtWidgets import QSizePolicy

    sa = _row_scroll(qapp)
    assert sa.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed


def test_row_scroll_prefers_the_rows_natural_width(qapp):
    """So a layout with room to spare hands over the full width and the
    trailing buttons stay reachable without scrolling."""
    sa = _row_scroll(qapp)
    assert sa.sizeHint().width() == 1327


def test_row_scroll_minimum_width_is_zero(qapp):
    """The entire reason the wrapper exists: the row's natural width must
    not become a floor on the window's own minimum width, or the
    free-resize experiment's narrow-window support regresses."""
    sa = _row_scroll(qapp)
    assert sa.minimumSizeHint().width() == 0


def test_row_scroll_matched_height_floors_the_box(qapp):
    """The filter row is padded out to the preview pane's height so the two
    boxes line up instead of the row sitting a few px short."""
    sa = _row_scroll(qapp, matched_height=60)
    assert sa.sizeHint().height() == 60
    assert sa.minimumSizeHint().height() == 60


def test_row_scroll_matched_height_never_clips_a_taller_row(qapp):
    """It's a floor, not a fixed size: a row whose natural height exceeds
    the match (bigger font, higher DPI) must still get the height it needs
    rather than being cut off."""
    sa = _row_scroll(qapp, row_hint=QSize(1327, 90), matched_height=60)
    hbar = sa.horizontalScrollBar().sizeHint().height()
    assert sa.sizeHint().height() == 90 + hbar


def test_row_scroll_pins_the_wrapped_row_height(qapp):
    """setWidgetResizable(True) otherwise makes the row track the viewport,
    so the ~12px the viewport loses when the horizontal scrollbar appears
    shifted the row's centred controls ~6px out of alignment with the
    preview pane, right as the window crossed that width. Pinned to the
    full box height (not the row's own 44) so the row's layout centres the
    controls in the box."""
    sa = _row_scroll(qapp, matched_height=60)
    row = sa.widget()
    assert row.minimumHeight() == row.maximumHeight() == 60
    assert sa.sizeHint().height() == 60


def test_row_scroll_anchors_content_to_the_top(qapp):
    """Top anchoring is the other half of that fix: centring inside a
    viewport that changes height would move the controls even with the row
    itself pinned."""
    from PyQt6.QtCore import Qt

    sa = _row_scroll(qapp)
    assert sa.alignment() & Qt.AlignmentFlag.AlignTop


def test_row_scroll_without_a_widget_falls_back_to_qt_defaults(qapp):
    """setWidget() happens after construction, so both hint paths are
    reachable with widget() still None."""
    from src.gui.main_window import SingleRowScrollArea

    sa = SingleRowScrollArea()
    assert sa.sizeHint().isValid()
    assert sa.minimumSizeHint().isValid()
