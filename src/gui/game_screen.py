"""Which screen Star Citizen is on, so the overlay can follow it (#573).

The game window is found by its window class and title (``FindWindowW``) and
its monitor by the window handle (``MonitorFromWindow``, ``GetMonitorInfoW``).
That is all: no handle to the game process, no memory reads, no hooks and no
input, so Easy Anti-Cheat has nothing to see. Off Windows, or with the game
not running, ``game_screen()`` falls back to the primary screen.

A Win32 monitor is matched to a ``QScreen`` by its device name, and failing
that by its rectangle: Qt on Windows keeps a screen's top-left in native
pixels and divides only its size by the screen's device pixel ratio.
"""
from __future__ import annotations

import ctypes
import logging
import sys
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from PyQt6.QtGui import QGuiApplication, QScreen

logger = logging.getLogger(__name__)

# Star Citizen's main window (CryEngine): its class first, its title as the
# fallback in case a build renames the class.
GAME_WINDOW_CLASS = "CryENGINE"
GAME_WINDOW_TITLE = "Star Citizen"
MONITOR_DEFAULTTONULL = 0
# A size off by this many native pixels still matches (DPI rounding).
SIZE_SLACK = 2


@dataclass(frozen=True)
class GameMonitor:
    """The monitor the game window is on, in native (physical) pixels."""
    device: str                         # "\\\\.\\DISPLAY2"
    left: int
    top: int
    width: int
    height: int


_user32_dll = None


def _user32():
    """user32 with argument types set on a private copy. None off Windows."""
    global _user32_dll
    if _user32_dll is None and sys.platform == "win32":
        from ctypes import wintypes
        dll = ctypes.WinDLL("user32", use_last_error=True)
        dll.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        dll.FindWindowW.restype = wintypes.HWND
        dll.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        dll.MonitorFromWindow.restype = wintypes.HMONITOR
        dll.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MonitorInfoEx)]
        dll.GetMonitorInfoW.restype = wintypes.BOOL
        _user32_dll = dll
    return _user32_dll


class _Rect(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _MonitorInfoEx(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", _Rect), ("rcWork", _Rect),
                ("dwFlags", ctypes.c_ulong), ("szDevice", ctypes.c_wchar * 32)]


def find_game_window(user32=None) -> int:
    """Star Citizen's window handle, 0 when it is not running or off Windows."""
    user32 = user32 or _user32()
    if not user32:
        return 0
    hwnd = user32.FindWindowW(GAME_WINDOW_CLASS, None) \
        or user32.FindWindowW(None, GAME_WINDOW_TITLE)
    return int(hwnd or 0)


def find_game_monitor(user32=None) -> Optional[GameMonitor]:
    """The monitor Star Citizen's window is on (for a minimized window, the one
    it was on), None when the game is not found."""
    user32 = user32 or _user32()
    hwnd = find_game_window(user32)
    if not hwnd:
        return None
    monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONULL)
    if not monitor:
        return None
    info = _MonitorInfoEx()
    info.cbSize = ctypes.sizeof(_MonitorInfoEx)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None
    rect = info.rcMonitor
    return GameMonitor(info.szDevice, rect.left, rect.top,
                       rect.right - rect.left, rect.bottom - rect.top)


def _native_size_matches(screen: QScreen, monitor: GameMonitor) -> bool:
    size, ratio = screen.geometry().size(), screen.devicePixelRatio()
    return (abs(round(size.width() * ratio) - monitor.width) <= SIZE_SLACK
            and abs(round(size.height() * ratio) - monitor.height) <= SIZE_SLACK)


def screen_for_monitor(monitor: GameMonitor, screens: Iterable[QScreen]) -> Optional[QScreen]:
    """The ``QScreen`` showing *monitor*: by device name, else by native
    top-left and size, else by top-left alone. None when none fits."""
    screens = list(screens)
    for screen in screens:
        if screen.name() == monitor.device:
            return screen
    same_corner = [s for s in screens
                   if (s.geometry().x(), s.geometry().y()) == (monitor.left, monitor.top)]
    for screen in same_corner:
        if _native_size_matches(screen, monitor):
            return screen
    return same_corner[0] if same_corner else None


def game_screen(find: Callable[[], Optional[GameMonitor]] = find_game_monitor) -> Optional[QScreen]:
    """The screen Star Citizen is on, else the primary screen."""
    primary = QGuiApplication.primaryScreen()
    try:
        monitor = find()
    except OSError:
        logger.debug("SCO: could not look up the game window", exc_info=True)
        return primary
    if monitor is None:
        return primary
    return screen_for_monitor(monitor, QGuiApplication.screens()) or primary
