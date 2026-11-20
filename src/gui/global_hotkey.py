"""A system-wide hotkey for the SCO drawer (#523), through Windows'
``RegisterHotKey`` and, while a game that keeps it away is in front, a look
at the hotkey's own keys.

``RegisterHotKey`` is not a keyboard hook. Windows posts ``WM_HOTKEY`` to
this thread when the one registered combination is pressed, and the app
with focus does not get that key press. Windows also lets a process that
just received its hotkey bring its own window to the front, which is how the
drawer takes focus over another program, and the window that had focus is
handed it back when the drawer closes: only its window handle is used,
never its process.

A game that reads the keyboard through raw input can switch every other
program's registered hotkeys off while it has focus (``RIDEV_NOHOTKEYS``),
and in Star Citizen the hotkey never arrived (#523). So while the game is in
front, the overlay's tick has the hotkey look at its own keys
(``GlobalHotkey.check_keys``; ``KeyCheck`` says what is asked and when). The
game still gets those keys. Windows does not let a background program take
focus from the game after such a press (found in testing), so the drawer
opens on top without it and the player holds F, as usual, to use the mouse
in it. Until #587 a hotkey took the keyboard's raw input instead
(``RIDEV_INPUTSINK``), which sent the app every key press, whatever window
had focus.
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
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x1, 0x2, 0x4, 0x8
# The modifier keys a key check asks about, each with its MOD_ flag: Shift,
# Ctrl and Alt by the code Windows gives either side of each, Win by its two
# keys, since Windows has no such code for it.
_MODIFIER_KEYS = ((MOD_SHIFT, (0x10,)), (MOD_CONTROL, (0x11,)), (MOD_ALT, (0x12,)),
                  (MOD_WIN, (0x5B, 0x5C)))
# GetAsyncKeyState's bits: the key is down now, and the key went down since
# any program last asked about it.
_KEY_DOWN, _PRESSED_SINCE = 0x8000, 0x0001
# A press a key check finds waits this long before it toggles. Windows posts
# WM_HOTKEY as the key goes down, so one for the same press, should the game
# in front let it through, is already queued and is handled first, and it
# can bring the drawer to the front where a key check cannot.
KEY_GRACE_MS = 10
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
        dll.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
        dll.AllowSetForegroundWindow.restype = wintypes.BOOL
        dll.GetAsyncKeyState.argtypes = [ctypes.c_int]
        dll.GetAsyncKeyState.restype = ctypes.c_short
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


class KeyCheck:
    """One combination's keys, looked at on each tick while the game is in
    front (``look``), for the moment the combination goes down: its key
    going down with exactly its modifiers held.

    Each look asks Windows about the combination's key (``GetAsyncKeyState``)
    and, only on the look that finds it newly down, about the modifier keys
    (``_MODIFIER_KEYS``), stopping at the first that settles the answer. No
    other key is asked about and no key press is sent to the app (#587).
    Asking clears the key's "pressed since" bit, which Windows keeps once for
    the whole session, as any program that asks does.

    The modifiers are read at that look, up to a tick after the key went
    down, so one let go or pressed within that tick can decide a press
    otherwise than ``RegisterHotKey`` would, and a press that goes down and
    up between two looks is not seen: in game the keys need a moment's hold.
    Pause is the exception, since Windows reports a Pause press down and up
    at once (the key sends no release): its "pressed since" bit counts as a
    press, but only when the look before was this check's own, as after
    ``forget`` the bit may be from a press made in another window.

    A combination held when the hotkey is set is no press. One held at the
    first look after ``forget`` (another window was in front) is, since it
    may have gone down just as the game came back; the owner's one-press
    rule keeps a press seen both ways to one toggle.
    """

    def __init__(self, modifiers: int, key: int, user32):
        self.modifiers, self.key = modifiers, key
        self._user32 = user32
        self._was_down = True       # held when the hotkey is set: no press
        self._own_look = False      # the look before was this check's own (Pause)

    def look(self) -> bool:
        """Whether the combination went down since the last look."""
        state = self._user32.GetAsyncKeyState(self.key)
        down = bool(state & _KEY_DOWN)
        went_down = down or (self.key == VK_PAUSE and self._own_look
                             and bool(state & _PRESSED_SINCE))
        was, self._was_down, self._own_look = self._was_down, down, True
        return went_down and not was and self._modifiers_held()

    def _modifiers_held(self) -> bool:
        for flag, keys in _MODIFIER_KEYS:
            held = any(self._user32.GetAsyncKeyState(key) & _KEY_DOWN for key in keys)
            if held != bool(self.modifiers & flag):
                return False
        return True

    def forget(self) -> None:
        """Another window is in front: a combination held at the next look
        counts as a press, and Pause's bit is left for that look to clear."""
        self._was_down = self._own_look = False


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


# AllowSetForegroundWindow's "any process" (ASFW_ANY, (DWORD)-1).
ASFW_ANY = 0xFFFFFFFF


def allow_any_foreground() -> bool:
    """Let another process bring its window to the front (AllowSetForegroundWindow
    with ASFW_ANY). Windows grants that right only to the process the user
    just started or the one in front, so that one hands it on: a second
    start of Smart Citizen does, for the copy in the tray (src/gui/tray.py).
    False off Windows or when Windows refuses."""
    user32 = _user32()
    return bool(user32.AllowSetForegroundWindow(ASFW_ANY)) if user32 else False


class _HotkeyFilter(QAbstractNativeEventFilter):
    """Hands this thread's ``WM_HOTKEY`` for one id to its GlobalHotkey."""

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
        return False, 0


class GlobalHotkey(QObject):
    """One key combination, held with Windows while asked for, that emits
    ``activated`` when pressed anywhere, once per press: by ``WM_HOTKEY``,
    or, where a game with focus keeps ``WM_HOTKEY`` away, by a key check its
    owner runs on a tick while that game is in front (``check_keys``).
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
        self._check: Optional[KeyCheck] = None    # the registered combination's keys
        self._told_checking = False               # the log says the keys are checked
        self._last_fired = -math.inf
        self._key_wait = QTimer(self)
        self._key_wait.setSingleShot(True)
        self._key_wait.setInterval(KEY_GRACE_MS)
        self._key_wait.timeout.connect(self._fire_from_keys)

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
        self._check = KeyCheck(modifiers, key, user32)
        self._told_checking = False
        logger.info("SCO: drawer hotkey %s registered", sequence)
        return ""

    def unregister(self) -> None:
        if self._registered is None:
            return
        user32 = self._dll or _user32()
        user32.UnregisterHotKey(None, self.hotkey_id)
        self._key_wait.stop()
        self._check = None
        self._registered = None
        if self._filter is not None:
            QCoreApplication.instance().removeNativeEventFilter(self._filter)
            self._filter = None

    def hotkey_message(self) -> None:
        """``WM_HOTKEY`` for this hotkey: toggle now, so a key check's find of
        the same press is not acted on."""
        self._key_wait.stop()
        if self._clock() - self._last_fired < SAME_PRESS_S:
            return                                    # a key check already did
        self._last_fired = self._clock()
        self.activated.emit()

    def check_keys(self) -> None:
        """Look at the hotkey's keys once (``KeyCheck``): the owner calls this
        on its ticks while the game is in front, and ``forget_keys`` on the
        others. Nothing is asked of Windows while no hotkey is held. The
        first look after a registration is logged, so a log without that
        line shows the game was never seen in front."""
        if self._check is None:
            return
        if not self._told_checking:
            self._told_checking = True
            logger.info("SCO: the game is in front: the drawer hotkey's keys are checked")
        if self._check.look() and self._clock() - self._last_fired >= SAME_PRESS_S:
            self._key_wait.start()                    # give a queued WM_HOTKEY its turn

    def forget_keys(self) -> None:
        """Another window is in front (``KeyCheck.forget``)."""
        if self._check is not None:
            self._check.forget()

    def _fire_from_keys(self) -> None:
        # The wait started only past SAME_PRESS_S, and the WM_HOTKEY that
        # resets the clock stops it, so the press is still a new one.
        self._last_fired = self._clock()
        self.activated.emit()
