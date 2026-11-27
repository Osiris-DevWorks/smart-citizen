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
from PyQt6.QtCore import QRect, QSize
from PyQt6.QtGui import QGuiApplication, QImage

from src.gui import game_screen as gs
from src.gui.game_screen import (
    GAME_WINDOW_CLASS, GAME_WINDOW_TITLE, GameMonitor, find_game_monitor, game_screen,
    screen_for_monitor,
)
from src.gui.sco_overlay import (
    DEFAULT_OVERLAY_COLORS, OverlayColors, ScoOverlay, scan_region_rect,
)


class FakeScreen:
    def __init__(self, name, x, y, w, h, ratio=1.0):
        self._name, self._geometry, self._ratio = name, QRect(x, y, w, h), ratio
        self.grabs = []

    def name(self):
        return self._name

    def geometry(self):
        return QRect(self._geometry)

    def availableGeometry(self):
        return QRect(self._geometry)

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
    finally:
        overlay.stop()
