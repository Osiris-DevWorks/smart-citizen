"""#573: the overlay follows the screen Star Citizen is on.

``game_screen.py`` finds the game window by class and title and its monitor by
handle, through a fake user32 here; a monitor is matched to a ``QScreen`` by
name, then by native rectangle. ``ScoOverlay`` docks the drawer to that screen,
captures it with screen-local coordinates and follows it when it changes.
Offscreen Qt (``QT_QPA_PLATFORM=offscreen``), fake screens.
"""
from __future__ import annotations

import ctypes

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QObject, QRect, QSize, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QImage

from src.gui import game_screen as gs
from src.gui import sco_overlay as so
from src.gui.game_screen import (
    GAME_WINDOW_CLASS, GAME_WINDOW_TITLE, GameMonitor, find_game_monitor, game_screen,
    screen_for_monitor,
)
from src.gui.sco_overlay import (
    DEFAULT_OVERLAY_COLORS, SCREEN_CHANGE_DOCK_MS, BlueprintDrawer, OverlayColors,
    ScoOverlay, scan_region_rect,
)
from src.utils.settings import AppSettings
from tests.event_loop import pump_until


class FakeScreen(QObject):
    # The change signals the drawer follows on the screen it docks to (#583).
    geometryChanged = pyqtSignal(QRect)
    availableGeometryChanged = pyqtSignal(QRect)

    def __init__(self, name, x, y, w, h, ratio=1.0):
        super().__init__()
        self._name, self._geometry, self._ratio = name, QRect(x, y, w, h), ratio
        # The work area: the whole screen until a test moves a taskbar in.
        self._available = QRect(x, y, w, h)
        self.grabs = []

    def name(self):
        return self._name

    def geometry(self):
        return QRect(self._geometry)

    def availableGeometry(self):
        return QRect(self._available)

    def devicePixelRatio(self):
        return self._ratio

    def grabWindow(self, window, x, y, w, h):
        self.grabs.append((window, x, y, w, h))
        image = QImage(QSize(w, h), QImage.Format.Format_RGB32)
        image.fill(0)

        class _Pixmap:
            def toImage(self):
                return image
        return _Pixmap()


class FakeUser32:
    """FindWindowW / MonitorFromWindow / GetMonitorInfoW over a set table."""

    def __init__(self, by_class=0, by_title=0, monitor=7, rect=(1920, 0, 4480, 1440),
                 device="\\\\.\\DISPLAY2", info_ok=True):
        self.by_class, self.by_title = by_class, by_title
        self.monitor, self.rect, self.device, self.info_ok = monitor, rect, device, info_ok
        self.calls = []

    def FindWindowW(self, cls, title):
        self.calls.append(("FindWindowW", cls, title))
        if cls == GAME_WINDOW_CLASS:
            return self.by_class
        if title == GAME_WINDOW_TITLE:
            return self.by_title
        return 0

    def MonitorFromWindow(self, hwnd, flags):
        self.calls.append(("MonitorFromWindow", hwnd, flags))
        return self.monitor

    def GetMonitorInfoW(self, monitor, pointer):
        if not self.info_ok:
            return 0
        info = pointer._obj
        assert info.cbSize == ctypes.sizeof(type(info))
        info.rcMonitor.left, info.rcMonitor.top, info.rcMonitor.right, info.rcMonitor.bottom = \
            self.rect
        info.szDevice = self.device
        return 1


# --- finding the game's monitor -------------------------------------------------

def test_the_game_is_found_by_its_window_class():
    user32 = FakeUser32(by_class=42)
    assert find_game_monitor(user32) == GameMonitor("\\\\.\\DISPLAY2", 1920, 0, 2560, 1440)
    assert ("MonitorFromWindow", 42, gs.MONITOR_DEFAULTTONULL) in user32.calls


def test_the_title_is_the_fallback_when_the_class_is_not_found():
    user32 = FakeUser32(by_title=43)
    assert find_game_monitor(user32).left == 1920
    assert ("MonitorFromWindow", 43, gs.MONITOR_DEFAULTTONULL) in user32.calls


@pytest.mark.parametrize("user32", [
    FakeUser32(),                              # game not running
    FakeUser32(by_class=42, monitor=0),        # no monitor for the window
    FakeUser32(by_class=42, info_ok=False),    # monitor info refused
])
def test_no_game_monitor_is_none(user32):
    assert find_game_monitor(user32) is None


def test_only_window_lookups_are_used():
    """EAC: the game is never opened, read or sent anything (#573)."""
    user32 = FakeUser32(by_class=42)
    find_game_monitor(user32)
    assert {call[0] for call in user32.calls} <= {"FindWindowW", "MonitorFromWindow"}


def test_off_windows_nothing_is_found(monkeypatch):
    monkeypatch.setattr(gs, "_user32", lambda: None)
    assert find_game_monitor() is None


# --- matching a monitor to a QScreen --------------------------------------------

def test_a_monitor_matches_its_screen_by_name():
    one = FakeScreen("\\\\.\\DISPLAY1", 0, 0, 1920, 1080)
    two = FakeScreen("\\\\.\\DISPLAY2", 1920, 0, 2560, 1440)
    monitor = GameMonitor("\\\\.\\DISPLAY2", 5000, 5000, 1, 1)
    assert screen_for_monitor(monitor, [one, two]) is two


def test_a_monitor_matches_by_native_rectangle_when_names_differ():
    """Qt keeps the top-left native and divides the size by the DPI ratio."""
    one = FakeScreen("DELL U2720Q", 0, 0, 1536, 864, ratio=1.25)        # 1920x1080 at 125%
    two = FakeScreen("LG 27GL850", 1920, 0, 1707, 960, ratio=1.5)       # 2560x1440 at 150%
    monitor = GameMonitor("\\\\.\\DISPLAY2", 1920, 0, 2560, 1440)
    assert screen_for_monitor(monitor, [one, two]) is two


def test_the_top_left_alone_is_the_last_match():
    two = FakeScreen("LG", 1920, 0, 1000, 1000)
    assert screen_for_monitor(GameMonitor("x", 1920, 0, 2560, 1440), [two]) is two


def test_no_screen_fits():
    one = FakeScreen("A", 0, 0, 1920, 1080)
    assert screen_for_monitor(GameMonitor("B", 1920, 0, 2560, 1440), [one]) is None


def test_game_screen_falls_back_to_the_primary_screen(qapp, monkeypatch):
    primary = QGuiApplication.primaryScreen()
    assert game_screen(lambda: None) is primary

    def broken():
        raise OSError("user32")
    assert game_screen(broken) is primary
    # A monitor no QScreen shows (unplugged between the two lookups).
    assert game_screen(lambda: GameMonitor("gone", 99999, 99999, 1, 1)) is primary


# --- the overlay follows it -----------------------------------------------------

@pytest.fixture
def screens(monkeypatch):
    """A two-screen desk where the test says which one the game is on."""
    monkeypatch.setattr(OverlayColors, "from_theme",
                        classmethod(lambda cls: DEFAULT_OVERLAY_COLORS))
    desk = {"left": FakeScreen("L", 0, 0, 1920, 1080),
            "right": FakeScreen("R", 1920, 0, 2560, 1440)}
    desk["game"] = desk["right"]
    monkeypatch.setattr("src.gui.sco_overlay.game_screen", lambda: desk["game"])
    return desk


def test_the_drawer_docks_on_the_games_screen_and_follows_it(qapp, screens):
    overlay = ScoOverlay()
    overlay.start()
    try:
        assert overlay.screen() is screens["right"]
        assert screens["right"].geometry().contains(overlay.drawer.geometry())
        screens["game"] = screens["left"]
        overlay._follow_game_screen()
        assert overlay.screen() is screens["left"]
        assert screens["left"].geometry().contains(overlay.drawer.geometry())
    finally:
        overlay.stop()


def test_a_running_overlay_checks_the_screen_and_stops_checking_on_stop(qapp, screens):
    overlay = ScoOverlay()
    overlay.start()
    assert overlay._screen_timer.isActive()
    overlay.stop()
    assert not overlay._screen_timer.isActive()


def test_the_capture_reads_the_games_screen_in_its_own_coordinates(qapp, screens):
    overlay = ScoOverlay()
    overlay.set_reader(lambda image: None)
    overlay.start()
    try:
        overlay._capture_once()
        overlay.wait_for_reader(5000)
        right = screens["right"]
        region = scan_region_rect(right.geometry())
        assert right.grabs == [(0, region.x() - 1920, region.y(), region.width(),
                                region.height())]
        assert not screens["left"].grabs
    finally:
        overlay.stop()


def test_a_move_hides_the_label_and_voids_a_capture_in_flight(qapp, screens):
    overlay = ScoOverlay()
    overlay.start()
    try:
        overlay._candidate, overlay._candidate_count = 7200, 1
        token = overlay._read_token
        screens["game"] = screens["left"]
        overlay._follow_game_screen()
        assert overlay._read_token != token
        assert overlay._candidate is None and not overlay.label.isVisible()
        # Same screen again: nothing changes.
        token = overlay._read_token
        overlay._follow_game_screen()
        assert overlay._read_token == token
    finally:
        overlay.stop()


def test_a_removed_screen_is_let_go(qapp, screens):
    overlay = ScoOverlay()
    overlay.start()
    try:
        gone = screens["right"]
        screens["game"] = screens["left"]
        overlay._on_screen_removed(gone)
        assert overlay.screen() is screens["left"]
        # The drawer follows no change of the screen that went (#583).
        assert _followers(gone) == 0
        assert _followers(screens["left"]) == 1
    finally:
        overlay.stop()


# --- #583: the drawer docks again when its screen changes ------------------------
#
# Only placing the drawer (it shows, opens, closes or moves) docked it, so a new
# scale, resolution or taskbar left it partly off the screen or over the taskbar.
# The expected place is where a drawer docked from scratch on the changed screen
# goes, so these tests hold whatever _dock's own sums are. Each test that sends a
# screen signal or lets the dock's timer run records what reaches sys.excepthook
# (slot_errors), and each wait for a dock shows it when it times out: a slot that
# raised with no hook stopped the whole run at that test, with no failure and no
# summary (measured with _dock made to raise).

def _followers(screen) -> int:
    """How many slots each change signal of *screen* reaches (the same for both)."""
    counts = {screen.receivers(signal) for signal in (
        screen.geometryChanged, screen.availableGeometryChanged)}
    assert len(counts) == 1, counts
    return counts.pop()


def _taskbar_on_the_right(screen):
    """A 60 px taskbar moved to the right edge (Windows 10): the work area shrinks."""
    area = screen.availableGeometry()
    screen._available = QRect(area.x(), area.y(), area.width() - 60, area.height())
    return screen.availableGeometryChanged, screen.availableGeometry()


def _new_resolution(screen):
    """1920 x 1080 where it was 2560 x 1440, its taskbar 40 px tall at the bottom."""
    corner = screen.geometry().topLeft()
    screen._geometry = QRect(corner.x(), corner.y(), 1920, 1080)
    screen._available = QRect(corner.x(), corner.y(), 1920, 1040)
    return screen.geometryChanged, screen.geometry()


def _rescale(screen, ratio=1.5):
    """*ratio* where it was 100%: the same monitor, fewer logical pixels, its
    top-left kept (Qt on Windows keeps it in native pixels)."""
    old, area = screen.geometry(), screen.availableGeometry()
    screen._ratio = ratio
    screen._geometry = QRect(old.x(), old.y(), round(old.width() / ratio),
                             round(old.height() / ratio))
    screen._available = QRect(area.x(), area.y(), round(area.width() / ratio),
                              round(area.height() / ratio))


def _new_scale(screen):
    """150% where it was 100%. Windows sends geometryChanged for it (the
    logical size changes) and no logicalDotsPerInchChanged (measured)."""
    _rescale(screen)
    return screen.geometryChanged, screen.geometry()


CHANGES = {"taskbar": _taskbar_on_the_right, "resolution": _new_resolution,
           "scale": _new_scale}


@pytest.fixture
def docked(qapp, screens, monkeypatch):
    """A running overlay, its drawer docked on the right screen. The device
    pixel fit asks Windows nothing about these made-up screens."""
    monkeypatch.setattr(so, "native_work_area", lambda screen: None)
    overlay = ScoOverlay()
    overlay.start()
    yield overlay
    overlay.stop()


def _docked_from_scratch(screen, position: str, expanded: bool) -> QRect:
    """Where a new drawer docks on *screen* as it is now. It docks on a copy:
    PyQt keeps a deleted drawer's connections to the screen (measured), which
    would count among the screen's followers."""
    area = screen.geometry()
    copy = FakeScreen(screen.name(), area.x(), area.y(), area.width(), area.height(),
                      screen.devicePixelRatio())
    copy._available = screen.availableGeometry()
    fresh = BlueprintDrawer(DEFAULT_OVERLAY_COLORS)
    try:
        fresh.set_position(position)
        fresh.set_screen(copy)
        if expanded:
            fresh.open_last_section()
        return fresh.geometry()
    finally:
        sip.delete(fresh)


def _wait_past_the_dock():
    pump_until(lambda: False, seconds=3 * SCREEN_CHANGE_DOCK_MS / 1000)


@pytest.mark.parametrize("expanded", [False, True], ids=["closed", "open"])
@pytest.mark.parametrize("change", list(CHANGES))
def test_a_change_to_its_screen_docks_the_drawer_again(docked, screens, change, expanded,
                                                       slot_errors):
    drawer, screen = docked.drawer, screens["right"]
    if expanded:
        drawer.open_last_section()
    before = drawer.geometry()
    signal, value = CHANGES[change](screen)
    expected = _docked_from_scratch(screen, drawer._position, expanded)
    assert expected != before, "the change should move the drawer's place"
    signal.emit(value)
    # Not at once: the wait folds the signals one change sends into one dock.
    assert drawer.geometry() == before
    assert pump_until(lambda: drawer.geometry() == expected, seconds=2), slot_errors
    assert screen.availableGeometry().contains(drawer.geometry())
    assert drawer.is_open() == expanded
    assert not slot_errors


@pytest.mark.parametrize("expanded", [False, True], ids=["closed", "open"])
@pytest.mark.parametrize("position", AppSettings.SCO_DRAWER_POSITIONS)
def test_every_position_is_placed_again(docked, screens, position, expanded, slot_errors):
    """A smaller resolution with the taskbar at the top (Windows 10) moves
    every position's place, corners and middles alike."""
    drawer, screen = docked.drawer, screens["right"]
    drawer.set_position(position)
    if expanded:
        drawer.open_last_section()
    before = drawer.geometry()
    corner = screen.geometry().topLeft()
    screen._geometry = QRect(corner.x(), corner.y(), 1920, 1080)
    screen._available = QRect(corner.x(), corner.y() + 40, 1920, 1040)
    expected = _docked_from_scratch(screen, position, expanded)
    assert expected != before
    screen.geometryChanged.emit(screen.geometry())
    screen.availableGeometryChanged.emit(screen.availableGeometry())
    assert pump_until(lambda: drawer.geometry() == expected, seconds=2), slot_errors
    assert screen.availableGeometry().contains(drawer.geometry())
    assert not slot_errors


def test_one_change_docks_the_drawer_once(docked, screens, monkeypatch, slot_errors):
    """A new scale reaches Qt as both signals (measured), and the drawer is
    placed once."""
    drawer, screen = docked.drawer, screens["right"]
    placed = []
    real = drawer.setGeometry
    monkeypatch.setattr(drawer, "setGeometry",
                        lambda *args: (placed.append(args), real(*args)))
    _rescale(screen)
    screen.geometryChanged.emit(screen.geometry())
    screen.availableGeometryChanged.emit(screen.availableGeometry())
    assert pump_until(lambda: placed, seconds=2), slot_errors
    _wait_past_the_dock()
    assert len(placed) == 1
    assert not slot_errors


@pytest.mark.parametrize("expanded", [False, True], ids=["closed", "open"])
def test_a_size_the_drawer_did_not_set_docks_it_again(docked, screens, expanded, slot_errors):
    """After a new scale Qt can keep the drawer's window at its old size in
    device pixels and then resize the drawer to match: a closed drawer, the
    same logical size at every scale, went from 22 x 212 to 18 x 170 at 125%
    just after its dock, off its edge (measured at 125%, 175% and 225%). Here
    the window is resized behind the drawer's back, as Qt did."""
    drawer = docked.drawer
    if expanded:
        drawer.open_last_section()
    place = drawer.geometry()
    drawer.windowHandle().resize(place.width() - 4, place.height() - 42)
    assert pump_until(lambda: drawer.size() != place.size(), seconds=1), \
        "the window's resize should reach the drawer"
    assert pump_until(lambda: drawer.geometry() == place, seconds=2), slot_errors
    assert drawer.windowHandle().geometry() == place
    assert drawer._size_fixes == 1
    assert not slot_errors


def test_a_size_the_window_keeps_refusing_stops_the_docks(docked, monkeypatch, slot_errors):
    """A window that never takes the drawer's size docks it a few times, not
    forever."""
    drawer = docked.drawer
    docks = []
    real = drawer.setGeometry

    def refused(x, y, width, height):
        docks.append((x, y, width, height))
        real(x, y, width - 3, height)
    monkeypatch.setattr(drawer, "setGeometry", refused)
    drawer._dock()
    _wait_past_the_dock()
    pump_until(lambda: False, seconds=1)
    assert len(docks) == 1 + so.SIZE_FIX_LIMIT, slot_errors
    assert not drawer._screen_change_timer.isActive()
    # A new screen change gets its tries again.
    docks.clear()
    docked.drawer._on_screen_changed()
    _wait_past_the_dock()
    pump_until(lambda: False, seconds=1)
    assert len(docks) == 1 + so.SIZE_FIX_LIMIT, slot_errors
    assert not slot_errors


def test_a_screen_the_drawer_has_left_moves_it_no_more(docked, screens, slot_errors):
    drawer, left, right = docked.drawer, screens["left"], screens["right"]
    assert (_followers(right), _followers(left)) == (1, 0)
    screens["game"] = left
    docked._follow_game_screen()
    assert (_followers(right), _followers(left)) == (0, 1)
    before = drawer.geometry()
    signal, value = _taskbar_on_the_right(right)
    signal.emit(value)
    assert not drawer._screen_change_timer.isActive()
    _wait_past_the_dock()
    assert drawer.geometry() == before
    # The screen it is on now still moves it.
    signal, value = _taskbar_on_the_right(left)
    expected = _docked_from_scratch(left, drawer._position, False)
    signal.emit(value)
    assert pump_until(lambda: drawer.geometry() == expected, seconds=2), slot_errors
    assert not slot_errors


@pytest.fixture
def primary(screens, monkeypatch):
    """QGuiApplication.primaryScreen as the test sets it (left to start)."""
    monkeypatch.setattr(so, "native_work_area", lambda screen: None)
    current = {"screen": screens["left"]}
    monkeypatch.setattr(so.QGuiApplication, "primaryScreen",
                        staticmethod(lambda: current["screen"]))
    return current


def test_every_drawer_hooks_a_new_primary_screen(qapp):
    """The signal itself is never sent in these tests: it would reach every
    drawer still alive in the session, so its handler is called directly and
    the hook is counted here."""
    before = qapp.receivers(qapp.primaryScreenChanged)
    drawer = BlueprintDrawer(DEFAULT_OVERLAY_COLORS)
    try:
        assert qapp.receivers(qapp.primaryScreenChanged) == before + 1
    finally:
        sip.delete(drawer)


def test_with_no_screen_set_it_follows_the_primary_screen(qapp, screens, primary, slot_errors):
    """The drawer's own fallback: docked to the primary screen while no screen
    is set, it follows that screen's changes and a new primary screen."""
    drawer = BlueprintDrawer(DEFAULT_OVERLAY_COLORS)
    try:
        left, right = screens["left"], screens["right"]
        assert left.geometry().contains(drawer.geometry())
        assert (_followers(left), _followers(right)) == (1, 0)
        signal, value = _taskbar_on_the_right(left)
        expected = _docked_from_scratch(left, drawer._position, False)
        signal.emit(value)
        assert pump_until(lambda: drawer.geometry() == expected, seconds=2), slot_errors
        primary["screen"] = right
        drawer._on_primary_screen_changed(right)
        assert pump_until(lambda: right.geometry().contains(drawer.geometry()),
                          seconds=2), slot_errors
        assert (_followers(left), _followers(right)) == (0, 1)
        assert not slot_errors
    finally:
        sip.delete(drawer)


def test_a_new_primary_screen_leaves_a_drawer_on_the_games_screen(docked, screens):
    """While the overlay names a screen, its own check follows the game."""
    docked.drawer._on_primary_screen_changed(screens["left"])
    assert not docked.drawer._screen_change_timer.isActive()


def test_with_no_screen_at_all_the_drawer_waits_for_one(qapp, screens, primary, slot_errors):
    """For a moment while Windows changes monitors Qt can have no screen, and
    primaryScreen() gives None: the dock does nothing and raises nothing, and
    the next primary screen docks it."""
    drawer = BlueprintDrawer(DEFAULT_OVERLAY_COLORS)
    try:
        place = drawer.geometry()
        primary["screen"] = None
        drawer._dock()                  # raised AttributeError on None
        assert drawer.geometry() == place
        primary["screen"] = screens["right"]
        drawer._on_primary_screen_changed(screens["right"])
        assert pump_until(
            lambda: screens["right"].geometry().contains(drawer.geometry()),
            seconds=2), slot_errors
        assert not slot_errors
    finally:
        sip.delete(drawer)


def test_a_new_primary_screen_gets_the_size_fixes_again(qapp, screens, primary, slot_errors):
    """With no screen at all for a moment, resizes Qt made then could use up
    the size fixes. The new primary screen's dock gets them again, so a size
    Qt then gives the drawer is put right."""
    drawer = BlueprintDrawer(DEFAULT_OVERLAY_COLORS)
    drawer.show()
    try:
        drawer._size_fixes = so.SIZE_FIX_LIMIT      # used up during the gap
        primary["screen"] = screens["right"]
        drawer._on_primary_screen_changed(screens["right"])
        assert pump_until(
            lambda: screens["right"].geometry().contains(drawer.geometry()),
            seconds=2), slot_errors
        place = drawer.geometry()
        drawer.windowHandle().resize(place.width() - 4, place.height() - 42)
        assert pump_until(lambda: drawer.size() != place.size(), seconds=1)
        assert pump_until(lambda: drawer.geometry() == place, seconds=2), slot_errors
        assert not slot_errors
    finally:
        drawer.hide()
        sip.delete(drawer)


def test_with_no_screen_at_all_nothing_is_captured(qapp, screens, primary):
    """The capture reads the screen every tick, so it waits for one too."""
    overlay = ScoOverlay()
    overlay.set_reader(lambda image: None)
    overlay.start()
    try:
        overlay._screen = None
        primary["screen"] = None
        overlay._capture_once()         # raised AttributeError on None
        assert not overlay._reading
        assert not screens["left"].grabs and not screens["right"].grabs
    finally:
        overlay.stop()


class _Hook:
    """A signal stand-in that records its disconnect, or fails it."""

    def __init__(self, fails_with=None):
        self.fails_with, self.disconnected = fails_with, False

    def connect(self, slot):
        pass

    def disconnect(self, slot):
        if self.fails_with is not None:
            raise self.fails_with("disconnect")
        self.disconnected = True


def test_each_signal_of_the_old_screen_is_let_go_on_its_own(qapp, primary, monkeypatch):
    """One signal that cannot be let go (deleted while being let go) does
    not leave the other one hooked, and a disconnect that fails for any other
    reason is not hidden."""
    drawer = BlueprintDrawer(DEFAULT_OVERLAY_COLORS)
    try:
        hooks = {"old": (_Hook(RuntimeError), _Hook()), "new": (_Hook(), _Hook())}
        monkeypatch.setattr(so, "_screen_change_signals", lambda screen: hooks[screen])
        drawer._followed_screen = "old"
        drawer._follow_screen("new")
        assert hooks["old"][1].disconnected
        hooks["broken"] = (_Hook(TypeError), _Hook())
        drawer._followed_screen = "broken"
        with pytest.raises(TypeError):
            drawer._follow_screen("new2")
    finally:
        monkeypatch.undo()
        sip.delete(drawer)


def test_a_screen_qt_has_deleted_is_let_go_quietly(qapp, screens, monkeypatch):
    """Qt deletes a screen once it is removed, and its connections with it, so
    moving on from it must not trip over the deleted object."""
    monkeypatch.setattr(so, "native_work_area", lambda screen: None)
    drawer = BlueprintDrawer(DEFAULT_OVERLAY_COLORS)
    try:
        gone = FakeScreen("gone", 0, 0, 1920, 1080)
        drawer.set_screen(gone)
        sip.delete(gone)
        drawer.set_screen(screens["left"])
        assert _followers(screens["left"]) == 1
    finally:
        sip.delete(drawer)
