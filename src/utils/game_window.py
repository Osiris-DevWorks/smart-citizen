"""Where the game's window is on the desktop (player ID test, Qt-free).

The scan decoder measures from the primary screen. Name tags are sized for
the game's own window, which on some setups is smaller than the screen (the
game in a 1920 by 1080 window on a 2560 by 1440 screen), so the player ID
test needs the window: ``foreground_game_area`` gives the place and size of
the game's picture when the game is the window in front, and nothing
otherwise.

Everything comes from Windows' own records of the window in front: its
handle, title, class, the id of the process that owns it, and that process's
file name from the system's process list (the list Task Manager shows). The
game's process is never opened, nothing is read from it and nothing is sent
to it, which is the overlay's anti-cheat rule (see ``src/gui/CLAUDE.md``).
"""
from __future__ import annotations

import ctypes
import sys
from typing import Optional

GAME_EXE = "StarCitizen.exe"
# Fallbacks for a window whose process name cannot be read.
GAME_TITLE = "star citizen"
GAME_WINDOW_CLASS = "cryengine"
# A window smaller than this is not the game's picture (minimised, a splash).
SMALLEST_WINDOW = (640, 360)

_WINDOWS = sys.platform == "win32"
_user32 = ctypes.WinDLL("user32", use_last_error=True) if _WINDOWS else None
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True) if _WINDOWS else None


class _ProcessEntry(ctypes.Structure):
    """PROCESSENTRY32W, one row of Windows' process list."""
    _fields_ = [("dwSize", ctypes.c_uint32), ("cntUsage", ctypes.c_uint32),
                ("th32ProcessID", ctypes.c_uint32), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", ctypes.c_uint32), ("cntThreads", ctypes.c_uint32),
                ("th32ParentProcessID", ctypes.c_uint32), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", ctypes.c_uint32), ("szExeFile", ctypes.c_wchar * 260)]


class _Rect(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


if _WINDOWS:
    _user32.GetForegroundWindow.restype = ctypes.c_void_p
    _user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    _user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    _user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    _user32.GetClientRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Rect)]
    _user32.ClientToScreen.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Point)]
    _user32.IsIconic.argtypes = [ctypes.c_void_p]
    _kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    _kernel32.CreateToolhelp32Snapshot.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    _kernel32.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ProcessEntry)]
    _kernel32.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ProcessEntry)]
    _kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

_TH32CS_SNAPPROCESS = 0x00000002
_program_names: dict[int, str] = {}


def program_name(pid: int) -> str:
    """The program file name of a process id, from Windows' process list.
    The process itself is never opened. "" when it cannot be read."""
    if not _WINDOWS or not pid:
        return ""
    if pid in _program_names:
        return _program_names[pid]
    name = ""
    snapshot = _kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if snapshot and snapshot != ctypes.c_void_p(-1).value:
        try:
            entry = _ProcessEntry()
            entry.dwSize = ctypes.sizeof(_ProcessEntry)
            more = _kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while more:
                if entry.th32ProcessID == pid:
                    name = entry.szExeFile
                    break
                more = _kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            _kernel32.CloseHandle(snapshot)
    if len(_program_names) > 200:
        _program_names.clear()
    _program_names[pid] = name
    return name


def foreground_window() -> tuple[int, str, str, str]:
    """Handle, title, class and program name of the window in front."""
    if not _WINDOWS:
        return 0, "", "", ""
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return 0, "", "", ""
    title = ctypes.create_unicode_buffer(256)
    cls = ctypes.create_unicode_buffer(256)
    pid = ctypes.c_uint32()
    _user32.GetWindowTextW(hwnd, title, 256)
    _user32.GetClassNameW(hwnd, cls, 256)
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return hwnd, title.value, cls.value, program_name(pid.value)


def is_game(title: str, cls: str, program: str) -> bool:
    """True when a window is the game's: by its program name, or failing
    that by the title or class its window has."""
    return (program.lower() == GAME_EXE.lower() or title.strip().lower() == GAME_TITLE
            or cls.strip().lower() == GAME_WINDOW_CLASS)


def client_area(hwnd: int) -> Optional[tuple[int, int, int, int]]:
    """Where a window's picture is on the desktop, in screen pixels:
    (left, top, width, height), without its title bar and borders. None for
    a minimised window or one too small to be the game's picture."""
    if not _WINDOWS or not hwnd or _user32.IsIconic(hwnd):
        return None
    rect = _Rect()
    origin = _Point(0, 0)
    if not _user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    if not _user32.ClientToScreen(hwnd, ctypes.byref(origin)):
        return None
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width < SMALLEST_WINDOW[0] or height < SMALLEST_WINDOW[1]:
        return None
    return origin.x, origin.y, width, height


def foreground_game_area(any_window: bool = False,
                         own_windows: tuple = ()) -> Optional[tuple[int, int, int, int]]:
    """The game's picture on the desktop (``client_area``) when the game is
    the window in front, else None. With *any_window*, whatever window is in
    front counts (for trying the reader on a saved picture), except the
    handles in *own_windows*."""
    hwnd, title, cls, program = foreground_window()
    if not hwnd:
        return None
    if any_window:
        if hwnd in own_windows:
            return None
    elif not is_game(title, cls, program):
        return None
    return client_area(hwnd)


def window_in_capture(area, screen, capture_size) -> tuple[int, int, int, int]:
    """A window's rectangle inside a capture of the screen it is on, cut to
    what the capture holds: (x, y, width, height). *area* is the window's
    ``client_area`` and *screen* the screen's (left, top) in screen pixels."""
    left, top, width, height = area
    x0, y0 = max(0, left - screen[0]), max(0, top - screen[1])
    x1 = min(capture_size[0], left - screen[0] + width)
    y1 = min(capture_size[1], top - screen[1] + height)
    return x0, y0, max(0, x1 - x0), max(0, y1 - y0)
