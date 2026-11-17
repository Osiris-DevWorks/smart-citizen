"""The SCO drawer shortcut is delivered by Windows through RegisterHotKey."""
from __future__ import annotations

import ctypes
import itertools
import logging
import sys
from ctypes import wintypes
from typing import Optional

from PyQt6.QtCore import (
    QAbstractNativeEventFilter, QCoreApplication, QKeyCombination, QObject, Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QKeySequence

logger = logging.getLogger(__name__)

WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x1, 0x2, 0x4, 0x8
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
    """Deliver this thread's hotkey notification for one registered ID."""

    def __init__(self, owner: "GlobalHotkey"):
        super().__init__()
        self._owner = owner

    def nativeEventFilter(self, event_type, message):  # noqa: N802 (Qt's name)
        # Thread messages (RegisterHotKey with no window) come through the
        # event dispatcher; window messages through both kinds.
        if bytes(event_type) in (b"windows_dispatcher_MSG", b"windows_generic_MSG") and message:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == self._owner.hotkey_id:
                self._owner.activated.emit()
                return True, 0
        return False, 0


class GlobalHotkey(QObject):
    """Register one shortcut on the GUI thread and emit when Windows notifies it."""

    activated = pyqtSignal()

    def __init__(self, parent=None, user32=None):
        super().__init__(parent)
        self._dll = user32
        self.hotkey_id = next(_ids)
        self._registered: Optional[str] = None
        self._filter: Optional[_HotkeyFilter] = None

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
        return ""

    def unregister(self) -> None:
        if self._registered is None:
            return
        user32 = self._dll or _user32()
        user32.UnregisterHotKey(None, self.hotkey_id)
        self._registered = None
        if self._filter is not None:
            QCoreApplication.instance().removeNativeEventFilter(self._filter)
            self._filter = None
