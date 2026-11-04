"""A system-wide hotkey for the SCO drawer (#523), through Windows'
``RegisterHotKey`` and, for when a game has focus, Windows raw input.

``RegisterHotKey`` is not a keyboard hook. Windows posts ``WM_HOTKEY`` to
this thread when the one registered combination is pressed, and the app
with focus does not get that key press. Windows also lets a process that
just received its hotkey bring its own window to the front, which is how the
drawer takes focus over another program, and the window that had focus is
handed it back when the drawer closes: only its window handle is used,
never its process.

A game that reads the keyboard through raw input can switch every other
program's registered hotkeys off while it has focus (``RIDEV_NOHOTKEYS``),
and in Star Citizen the hotkey never arrived (#523). So while a hotkey is
held, a message-only window also takes the keyboard's raw input
(``RIDEV_INPUTSINK``), the read-only way Windows tells a background program
about key presses: not a hook, nothing is held up, changed or sent, and
only the one combination is acted on. The game still gets those keys.
Windows does not let a background program take focus from the game after
such a press (found in testing), so the drawer opens on top without it and
the player holds F, as usual, to use the mouse in it.
"""
from __future__ import annotations

import ctypes
import itertools
import logging
import math
import sys
import time
from ctypes import wintypes
from typing import Callable, Optional

from PyQt6.QtCore import (
    QAbstractNativeEventFilter, QCoreApplication, QKeyCombination, QObject, Qt, QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QKeySequence

logger = logging.getLogger(__name__)

WM_HOTKEY = 0x0312
WM_INPUT = 0x00FF
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x1, 0x2, 0x4, 0x8
RID_INPUT = 0x10000003
RIM_TYPEKEYBOARD = 1
RIDEV_REMOVE, RIDEV_INPUTSINK = 0x0001, 0x0100
RI_KEY_BREAK = 0x0001
# The parent that makes a window message-only: never shown, only there to
# be sent the raw input.
HWND_MESSAGE = -3
# Each modifier's virtual keys (raw input names Ctrl, Alt and Shift by the
# shared key, some keyboards by the left or right one) and its MOD_ flag.
_MODIFIER_VKS = {
    0x10: MOD_SHIFT, 0xA0: MOD_SHIFT, 0xA1: MOD_SHIFT,
    0x11: MOD_CONTROL, 0xA2: MOD_CONTROL, 0xA3: MOD_CONTROL,
    0x12: MOD_ALT, 0xA4: MOD_ALT, 0xA5: MOD_ALT,
    0x5B: MOD_WIN, 0x5C: MOD_WIN,
}
# Outside a game one press arrives both ways. A raw-input sighting waits
# this long for the press's WM_HOTKEY, which may bring the drawer to the
# front where raw input may not, and acts only if none came.
RAW_GRACE_MS = 80
# One press is one toggle, whichever way it arrived.
SAME_PRESS_S = 0.3
# Held down, the combination fires once, not again on every key repeat.
MOD_NOREPEAT = 0x4000
VK_F1, VK_NUMPAD0, VK_PAUSE = 0x70, 0x60, 0x13
# Any key but an F key or Pause needs one of these held with it. Alone, or
# with Shift only, a letter, digit, Space, Tab or arrow would toggle the
# drawer on every press in game, and Windows would take that key from every
# other program while the overlay runs.
MODIFIERS_NEEDED = MOD_CONTROL | MOD_ALT | MOD_WIN

# Why a hotkey is not in use, for the Overlay tab to say.
HOTKEY_TAKEN = "taken"
HOTKEY_UNSUPPORTED = "unsupported"

_MODIFIERS = (
    (Qt.KeyboardModifier.ControlModifier, MOD_CONTROL),
    (Qt.KeyboardModifier.AltModifier, MOD_ALT),
    (Qt.KeyboardModifier.ShiftModifier, MOD_SHIFT),
    (Qt.KeyboardModifier.MetaModifier, MOD_WIN),
)

# Keys whose virtual-key code is the same on every keyboard layout, besides
# letters, digits and F keys.
_NAMED_KEYS = {
    Qt.Key.Key_Tab: 0x09, Qt.Key.Key_Pause: VK_PAUSE, Qt.Key.Key_Space: 0x20,
    Qt.Key.Key_PageUp: 0x21, Qt.Key.Key_PageDown: 0x22, Qt.Key.Key_End: 0x23,
    Qt.Key.Key_Home: 0x24, Qt.Key.Key_Left: 0x25, Qt.Key.Key_Up: 0x26,
    Qt.Key.Key_Right: 0x27, Qt.Key.Key_Down: 0x28, Qt.Key.Key_Insert: 0x2D,
    Qt.Key.Key_Delete: 0x2E,
}
# Symbol keys (Windows' "OEM" virtual keys). Which symbol each one types is
# the keyboard layout's choice ("/" on a US layout is Shift+7 on a German
# one), so a symbol key is saved as the symbol it types unshifted on the
# player's layout and found again through that layout (#523). 0xC1 is a
# Brazilian (ABNT2) keyboard's own "/" key, 0xE2 the extra key next to the
# left Shift on most non-US keyboards.
_SYMBOL_VKS = frozenset(range(0xBA, 0xC2)) | frozenset(range(0xDB, 0xE0)) | {0xE2}
MAPVK_VK_TO_CHAR = 2
# MapVirtualKeyW sets this bit for a dead key (an accent waiting for a letter).
_DEAD_KEY = 0x80000000

# RegisterHotKey ids are per thread; each GlobalHotkey takes its own.
_ids = itertools.count(0x5C00)


def windows_hotkey(sequence: str) -> Optional[tuple[int, int]]:
    """``(modifiers, virtual key)`` for one key combination in QKeySequence
    portable text ("Ctrl+Shift+O", "Ctrl+/"), or None when the text is
    empty, holds more than one combination, ends in a key Windows has no
    code for (Esc, Enter) or a symbol no key types unshifted on this
    keyboard layout, or holds none of ``MODIFIERS_NEEDED`` with a key other
    than an F key or Pause."""
    keys = QKeySequence.fromString(sequence or "", QKeySequence.SequenceFormat.PortableText)
    if keys.count() != 1:
        return None
    combo = keys[0]
    key, held = combo.key(), combo.keyboardModifiers()
    modifiers = 0
    for qt_modifier, win_modifier in _MODIFIERS:
        if held & qt_modifier:
            modifiers |= win_modifier
    if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        if held & Qt.KeyboardModifier.KeypadModifier:
            code = VK_NUMPAD0 + key - Qt.Key.Key_0
        else:
            code = int(key)           # Qt's code is the digit's ASCII code, as is Windows'
    elif Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
        code = int(key)               # the capital letter's code, in both
    elif Qt.Key.Key_F1 <= key <= Qt.Key.Key_F24:
        code = VK_F1 + key - Qt.Key.Key_F1
    else:
        code = _NAMED_KEYS.get(key)
        if code is None and 0x21 <= key < Qt.Key.Key_Escape:   # a character, not a named key
            code = layout_symbol_key(chr(key))
        if code is None:
            return None
    stands_alone = VK_F1 <= code <= VK_F1 + 23 or code == VK_PAUSE
    if not stands_alone and not modifiers & MODIFIERS_NEEDED:
        return None
    return modifiers, code


def hotkey_text(modifiers: Qt.KeyboardModifier, virtual_key: int) -> Optional[str]:
    """The portable text ``windows_hotkey`` reads back as this same key, for
    Qt *modifiers* held with Windows *virtual_key*, or None for a
    combination it does not take (a key with no code, a dead key, one that
    needs Ctrl, Alt or Win, or a symbol another key also types).

    Built from the key Windows reports, not the character the keyboard
    layout makes of it with the modifiers held: where Ctrl+Alt is AltGr,
    Ctrl+Alt+O makes a character such as "ó", and Shift+1 makes "!",
    neither of which is a key Windows can register (#523). A symbol key is
    named by the symbol it types unshifted ("Ctrl+/")."""
    held = modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
                        | Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.MetaModifier)
    if 0x30 <= virtual_key <= 0x39 or 0x41 <= virtual_key <= 0x5A:
        key = Qt.Key(virtual_key)                 # digits and capitals share their codes
    elif VK_NUMPAD0 <= virtual_key <= VK_NUMPAD0 + 9:
        key = Qt.Key(Qt.Key.Key_0 + virtual_key - VK_NUMPAD0)
        held |= Qt.KeyboardModifier.KeypadModifier
    elif VK_F1 <= virtual_key <= VK_F1 + 23:
        key = Qt.Key(Qt.Key.Key_F1 + virtual_key - VK_F1)
    else:
        key = next((qt_key for qt_key, code in _NAMED_KEYS.items() if code == virtual_key), None)
        if key is None:
            symbol = layout_symbol(virtual_key)
            if symbol is None:
                return None
            key = ord(_capital(symbol))                # Qt names a letter by its capital
    text = QKeySequence(QKeyCombination.fromCombined(held.value | int(key))).toString(
        QKeySequence.SequenceFormat.PortableText)
    # Its rule, in one place, and the same key back: a symbol two keys type
    # (a UK keyboard's two backslash keys) would register the other one.
    keys = windows_hotkey(text)
    return text if keys and keys[1] == virtual_key else None


def _capital(symbol: str) -> str:
    capital = symbol.upper()
    return capital if len(capital) == 1 else symbol    # "ß" has no one-letter capital


_user32_dll = None


def _user32():
    """user32 with argument types set on a private copy, so nothing else that
    uses ctypes in the process is affected. None off Windows."""
    global _user32_dll
    if _user32_dll is None and sys.platform == "win32":
        dll = ctypes.WinDLL("user32", use_last_error=True)
        dll.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        dll.RegisterHotKey.restype = wintypes.BOOL
        dll.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        dll.UnregisterHotKey.restype = wintypes.BOOL
        dll.GetForegroundWindow.argtypes = []
        dll.GetForegroundWindow.restype = wintypes.HWND
        dll.SetForegroundWindow.argtypes = [wintypes.HWND]
        dll.SetForegroundWindow.restype = wintypes.BOOL
        dll.IsWindow.argtypes = [wintypes.HWND]
        dll.IsWindow.restype = wintypes.BOOL
        dll.RegisterRawInputDevices.argtypes = [ctypes.POINTER(RAWINPUTDEVICE), wintypes.UINT,
                                                wintypes.UINT]
        dll.RegisterRawInputDevices.restype = wintypes.BOOL
        dll.GetRawInputData.argtypes = [wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p,
                                        ctypes.POINTER(wintypes.UINT), wintypes.UINT]
        dll.GetRawInputData.restype = wintypes.UINT
        dll.GetAsyncKeyState.argtypes = [ctypes.c_int]
        dll.GetAsyncKeyState.restype = ctypes.c_short
        dll.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
            wintypes.HINSTANCE, wintypes.LPVOID]
        dll.CreateWindowExW.restype = wintypes.HWND
        dll.DestroyWindow.argtypes = [wintypes.HWND]
        dll.DestroyWindow.restype = wintypes.BOOL
        dll.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
        dll.MapVirtualKeyW.restype = wintypes.UINT
        dll.VkKeyScanW.argtypes = [wintypes.WCHAR]
        dll.VkKeyScanW.restype = ctypes.c_short
        _user32_dll = dll
    return _user32_dll


def layout_symbol(virtual_key: int) -> Optional[str]:
    """The symbol a symbol key types unshifted on this thread's keyboard
    layout ("/" for 0xBF on a US layout, "#" on a German one), or None: not
    a symbol key, a dead key, a key that types nothing, or off Windows."""
    user32 = _user32()
    if virtual_key not in _SYMBOL_VKS or not user32:
        return None
    value = user32.MapVirtualKeyW(virtual_key, MAPVK_VK_TO_CHAR)
    if not value or value & _DEAD_KEY:
        return None
    symbol = chr(value & 0xFFFF)
    return symbol if symbol.isprintable() and not symbol.isspace() else None


def layout_symbol_key(symbol: str) -> Optional[int]:
    """The symbol key that types *symbol* unshifted on this thread's keyboard
    layout, or None when none does (on a German layout "/" is Shift+7)."""
    user32 = _user32()
    if not user32 or len(symbol) != 1 or ord(symbol) > 0xFFFF:
        return None
    for typed in dict.fromkeys((symbol, symbol.lower())):  # a letter's key types it small
        found = user32.VkKeyScanW(typed)
        if found == -1:
            continue
        virtual_key = found & 0xFF
        base = layout_symbol(virtual_key)
        if base is not None and _capital(base) == _capital(symbol):
            return virtual_key
    return None


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", wintypes.USHORT), ("usUsage", wintypes.USHORT),
                ("dwFlags", wintypes.DWORD), ("hwndTarget", wintypes.HWND)]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [("dwType", wintypes.DWORD), ("dwSize", wintypes.DWORD),
                ("hDevice", wintypes.HANDLE), ("wParam", wintypes.WPARAM)]


class RAWKEYBOARD(ctypes.Structure):
    _fields_ = [("MakeCode", wintypes.USHORT), ("Flags", wintypes.USHORT),
                ("Reserved", wintypes.USHORT), ("VKey", wintypes.USHORT),
                ("Message", wintypes.UINT), ("ExtraInformation", wintypes.ULONG)]


def _keyboard_device(flags: int, hwnd) -> RAWINPUTDEVICE:
    return RAWINPUTDEVICE(0x01, 0x06, flags, hwnd)     # generic desktop page, keyboard


def read_raw_key(user32, handle: int) -> Optional[tuple[int, bool]]:
    """``(virtual key, released)`` from a ``WM_INPUT`` message's lParam, or
    None when it is not keyboard input."""
    header_size = ctypes.sizeof(RAWINPUTHEADER)
    size = wintypes.UINT(0)
    if user32.GetRawInputData(handle, RID_INPUT, None, ctypes.byref(size), header_size) != 0 \
            or not size.value:
        return None
    buffer = (ctypes.c_ubyte * size.value)()
    if user32.GetRawInputData(handle, RID_INPUT, buffer, ctypes.byref(size),
                              header_size) != size.value:
        return None
    header = RAWINPUTHEADER.from_buffer(buffer)
    if header.dwType != RIM_TYPEKEYBOARD or size.value < header_size + ctypes.sizeof(RAWKEYBOARD):
        return None
    keyboard = RAWKEYBOARD.from_buffer(buffer, header_size)
    return keyboard.VKey, bool(keyboard.Flags & RI_KEY_BREAK)


def modifiers_down_now() -> int:
    """The MOD_ flags of the modifiers Windows says are down right now."""
    user32 = _user32()
    if not user32:
        return 0
    held = 0
    for vk, flag in _MODIFIER_VKS.items():
        if user32.GetAsyncKeyState(vk) & 0x8000:
            held |= flag
    return held


class RawCombination:
    """Turns the raw stream of key presses and releases into the moment one
    combination goes down: its key pressed (not repeated) with exactly its
    modifiers held, as ``RegisterHotKey`` matches.

    The modifiers come from the same stream, in order: by the time a message
    is handled, a quick Ctrl+Alt+O may already be over. A modifier held
    longer than ``STALE_AFTER`` is checked with Windows, so a release that
    never arrived (a lock screen, a secure desktop) does not leave it down.
    For the same reason a press of the key last seen longer ago than that is
    a new press, not a repeat: a held key repeats far more often.
    """

    STALE_AFTER = 3.0

    def __init__(self, modifiers: int, key: int,
                 modifiers_now: Callable[[], int] = modifiers_down_now,
                 clock: Callable[[], float] = time.monotonic):
        self.modifiers, self.key = modifiers, key
        self._modifiers_now, self._clock = modifiers_now, clock
        self._held: dict[int, float] = {}       # virtual key -> when it went down

    def feed(self, virtual_key: int, released: bool) -> bool:
        if released:
            self._held.pop(virtual_key, None)
            return False
        now = self._clock()
        since = self._held.get(virtual_key)
        repeat = since is not None and now - since < self.STALE_AFTER
        self._held[virtual_key] = now
        if virtual_key != self.key or repeat:
            return False
        return self._held_modifiers(now) == self.modifiers

    def _held_modifiers(self, now: float) -> int:
        held, windows_says = 0, None
        for virtual_key, since in list(self._held.items()):
            flag = _MODIFIER_VKS.get(virtual_key)
            if not flag:
                continue
            if now - since >= self.STALE_AFTER:
                if windows_says is None:
                    windows_says = self._modifiers_now()
                if not windows_says & flag:
                    del self._held[virtual_key]
                    continue
            held |= flag
        return held


def foreground_window() -> int:
    """The window that has focus now, 0 when none or off Windows."""
    user32 = _user32()
    return int(user32.GetForegroundWindow() or 0) if user32 else 0


def give_focus_back(hwnd: int) -> bool:
    """Bring *hwnd* back to the front, if it is still a window."""
    user32 = _user32()
    if not user32 or not hwnd or not user32.IsWindow(hwnd):
        return False
    return bool(user32.SetForegroundWindow(hwnd))


class _HotkeyFilter(QAbstractNativeEventFilter):
    """Hands this thread's ``WM_HOTKEY`` for one id, and the raw input for
    its hidden window, to its GlobalHotkey."""

    def __init__(self, owner: "GlobalHotkey"):
        super().__init__()
        self._owner = owner

    def nativeEventFilter(self, event_type, message):  # noqa: N802 (Qt's name)
        # Thread messages (RegisterHotKey with no window) come through the
        # event dispatcher; window messages through both kinds.
        if bytes(event_type) in (b"windows_dispatcher_MSG", b"windows_generic_MSG") and message:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == self._owner.hotkey_id:
                self._owner.hotkey_message()
                return True, 0
            if (msg.message == WM_INPUT and self._owner.sink_hwnd
                    and (msg.hWnd or 0) == self._owner.sink_hwnd):
                self._owner.raw_message(msg.lParam)
                # Windows needs WM_INPUT to reach the default handling to tidy up.
        return False, 0


class GlobalHotkey(QObject):
    """One key combination, held with Windows while asked for, that emits
    ``activated`` when pressed anywhere, once per press: by ``WM_HOTKEY``,
    or by raw input where a game with focus keeps ``WM_HOTKEY`` away.
    Register and unregister it from the GUI thread: Windows posts the
    hotkey to the registering one."""

    activated = pyqtSignal()

    def __init__(self, parent=None, user32=None, clock: Callable[[], float] = time.monotonic):
        super().__init__(parent)
        self._dll = user32
        self._clock = clock
        self.hotkey_id = next(_ids)
        self._registered: Optional[str] = None
        self._filter: Optional[_HotkeyFilter] = None
        self.sink_hwnd = 0                        # the window raw input goes to, while on
        self._raw_on = False
        self._combination: Optional[RawCombination] = None
        self._last_raw_message = None
        self._last_fired = -math.inf
        self._raw_wait = QTimer(self)
        self._raw_wait.setSingleShot(True)
        self._raw_wait.setInterval(RAW_GRACE_MS)
        self._raw_wait.timeout.connect(self._fire_from_raw)

    @property
    def registered(self) -> Optional[str]:
        """The sequence registered now, or None."""
        return self._registered

    def register(self, sequence: str) -> str:
        """Use *sequence* (QKeySequence portable text) as the hotkey, or none
        for an empty one. Returns "" when done, else ``HOTKEY_UNSUPPORTED``
        (no Windows key for it) or ``HOTKEY_TAKEN`` (Windows refused it,
        usually because another program has it)."""
        if sequence == self._registered:
            return ""
        self.unregister()
        if not sequence:
            return ""
        keys = windows_hotkey(sequence)
        user32 = self._dll or _user32()
        if keys is None or user32 is None:
            return HOTKEY_UNSUPPORTED
        modifiers, key = keys
        if not user32.RegisterHotKey(None, self.hotkey_id, modifiers | MOD_NOREPEAT, key):
            logger.warning("SCO: Windows refused the drawer hotkey %s (error %s)",
                           sequence, ctypes.get_last_error())
            return HOTKEY_TAKEN
        if self._filter is None:
            self._filter = _HotkeyFilter(self)
            QCoreApplication.instance().installNativeEventFilter(self._filter)
        self._registered = sequence
        self._combination = RawCombination(modifiers, key)
        self._raw_on = self._watch_raw_input(user32, True)
        logger.info("SCO: drawer hotkey %s registered%s", sequence,
                    "" if self._raw_on else " (raw input refused: not while a game has focus)")
        return ""

    def unregister(self) -> None:
        if self._registered is None:
            return
        user32 = self._dll or _user32()
        user32.UnregisterHotKey(None, self.hotkey_id)
        if self._raw_on:
            self._watch_raw_input(user32, False)
            self._raw_on = False
        self._raw_wait.stop()
        self._combination = None
        self._registered = None
        if self._filter is not None:
            QCoreApplication.instance().removeNativeEventFilter(self._filter)
            self._filter = None

    def _watch_raw_input(self, user32, on: bool) -> bool:
        """Have the keyboard's raw input sent to a message-only window of
        this thread, whatever has focus (``RIDEV_INPUTSINK``), or stop it and
        close the window. True when Windows agreed. The window is a plain
        STATIC one, so Qt's event loop hands its messages to the filter and
        Windows' own handling tidies each one up."""
        size = ctypes.sizeof(RAWINPUTDEVICE)
        if not on:
            user32.RegisterRawInputDevices(
                ctypes.byref(_keyboard_device(RIDEV_REMOVE, None)), 1, size)
            if self.sink_hwnd:
                user32.DestroyWindow(self.sink_hwnd)
                self.sink_hwnd = 0
            return False
        self.sink_hwnd = int(user32.CreateWindowExW(
            0, "STATIC", "Smart Citizen drawer hotkey", 0, 0, 0, 0, 0, HWND_MESSAGE,
            None, None, None) or 0)
        if not self.sink_hwnd:
            return False
        if user32.RegisterRawInputDevices(
                ctypes.byref(_keyboard_device(RIDEV_INPUTSINK, self.sink_hwnd)), 1, size):
            return True
        user32.DestroyWindow(self.sink_hwnd)
        self.sink_hwnd = 0
        return False

    def hotkey_message(self) -> None:
        """``WM_HOTKEY`` for this hotkey: toggle now, as this press's raw
        input is then not acted on."""
        self._raw_wait.stop()
        if self._clock() - self._last_fired < SAME_PRESS_S:
            return                                    # raw input already did
        self._last_fired = self._clock()
        self.activated.emit()

    def raw_message(self, handle: int) -> None:
        """A ``WM_INPUT`` for the hidden window (it can come through Qt twice)."""
        if handle == self._last_raw_message or self._combination is None:
            return
        self._last_raw_message = handle
        key = read_raw_key(self._dll or _user32(), handle)
        if key is not None:
            self.raw_key(*key)

    def raw_key(self, virtual_key: int, released: bool) -> None:
        if self._combination is None or not self._combination.feed(virtual_key, released):
            return
        if self._clock() - self._last_fired >= SAME_PRESS_S:
            self._raw_wait.start()                    # give WM_HOTKEY its chance first

    def _fire_from_raw(self) -> None:
        if self._clock() - self._last_fired < SAME_PRESS_S:
            return
        self._last_fired = self._clock()
        self.activated.emit()
