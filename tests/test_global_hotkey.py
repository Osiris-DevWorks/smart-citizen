"""Key mapping, shortcut lifecycle, and Windows hotkey delivery without Raw Input."""
import sys

import pytest

from src.gui import global_hotkey
from src.gui.global_hotkey import (
    HOTKEY_TAKEN, HOTKEY_UNSUPPORTED, MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, MOD_SHIFT, MOD_WIN,
    WM_HOTKEY, GlobalHotkey, windows_hotkey,
)


class _Layout:
    """A keyboard layout for MapVirtualKeyW and VkKeyScanW: each symbol
    key's unshifted symbol, the dead keys among them (an accent waiting
    for a letter), and the symbols that need Shift, by the key that types
    them."""

    def __init__(self, base, shifted=(), dead=()):
        self.base, self.shifted, self.dead = base, dict(shifted), set(dead)

    def MapVirtualKeyW(self, virtual_key, kind):  # noqa: N802
        assert kind == global_hotkey.MAPVK_VK_TO_CHAR
        if virtual_key not in self.base:
            return 0
        flag = 0x80000000 if virtual_key in self.dead else 0
        return flag | ord(self.base[virtual_key])

    def VkKeyScanW(self, symbol):  # noqa: N802
        for virtual_key, typed in self.base.items():
            if typed == symbol:
                return virtual_key
        if symbol in self.shifted:
            return 0x100 | self.shifted[symbol]
        return -1


US = _Layout({0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/", 0xC0: "`",
              0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'"},
             {"!": 0x31, ":": 0xBA, "+": 0xBB, "?": 0xBF})
# "/" is Shift+7, the key with "/" on a US layout types "#", two are dead
# keys (^ and an accent), and the umlaut keys type their small letter.
GERMAN = _Layout({0xBA: "ü", 0xBB: "+", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "#", 0xC0: "ö",
                  0xDB: "ß", 0xDC: "^", 0xDD: "´", 0xDE: "ä", 0xE2: "<"},
                 {"/": 0x37, "*": 0xBB, "?": 0xDB, "Ü": 0xBA, "Ö": 0xC0, "Ä": 0xDE},
                 dead={0xDC, 0xDD})
# Two keys type a backslash on some layouts; VkKeyScanW names the first.
TWO_BACKSLASHES = _Layout({0xBF: "/", 0xDC: "\\", 0xE2: "\\"})
# A letter key VkKeyScanW knows only by its small letter.
SMALL_LETTERS_ONLY = _Layout({0xC0: "ö"})
# Brazilian ABNT2: "/" has a key of its own (0xC1), and the key with "/" on a
# US layout types ";".
BRAZILIAN = _Layout({0xBA: "ç", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: ";",
                     0xC0: "'", 0xC1: "/", 0xDB: "´", 0xDC: "]", 0xDD: "[", 0xDE: "~",
                     0xE2: "\\"},
                    {"Ç": 0xBA, "?": 0xC1, ":": 0xBF}, dead={0xDB, 0xDE})


@pytest.fixture
def layout(monkeypatch):
    """Use a stand-in keyboard layout: the real one is the test machine's."""
    def use(table):
        monkeypatch.setattr(global_hotkey, "_user32", lambda: table)
    return use


@pytest.mark.parametrize("text, keys", [
    ("Ctrl+Shift+O", (MOD_CONTROL | MOD_SHIFT, 0x4F)),
    ("Alt+1", (MOD_ALT, 0x31)),
    ("F9", (0, 0x78)),
    ("Shift+F5", (MOD_SHIFT, 0x74)),
    ("Pause", (0, 0x13)),
    ("Ctrl+F24", (MOD_CONTROL, 0x87)),
    ("Meta+Space", (MOD_WIN, 0x20)),
    ("Ctrl+PgDown", (MOD_CONTROL, 0x22)),
    ("Alt+Shift+Del", (MOD_ALT | MOD_SHIFT, 0x2E)),
    ("Ctrl+Num+5", (MOD_CONTROL, 0x65)),
])
def test_windows_codes(text, keys):
    assert windows_hotkey(text) == keys


@pytest.mark.parametrize("text", ["", "Ctrl+A, B", "Ctrl+Shift+!", "Ctrl+Esc", "Ctrl+Return",
                                  "Ctrl+?"])
def test_keys_with_no_code_or_symbol_key_are_refused(layout, text):
    # Two combinations are no hotkey; Esc and Enter are left alone; "!" and
    # "?" need Shift, so no key types them unshifted.
    layout(US)
    assert windows_hotkey(text) is None


@pytest.mark.parametrize("table, text, keys", [
    (US, "Ctrl+/", (MOD_CONTROL, 0xBF)), (US, "Alt+;", (MOD_ALT, 0xBA)),
    (US, "Ctrl+,", (MOD_CONTROL, 0xBC)), (US, "Ctrl+Shift+=", (MOD_CONTROL | MOD_SHIFT, 0xBB)),
    (US, "Meta+\\", (MOD_WIN, 0xDC)),
    (GERMAN, "Ctrl+#", (MOD_CONTROL, 0xBF)), (GERMAN, "Ctrl++", (MOD_CONTROL, 0xBB)),
    (GERMAN, "Ctrl+Ü", (MOD_CONTROL, 0xBA)), (GERMAN, "Ctrl+<", (MOD_CONTROL, 0xE2)),
    (SMALL_LETTERS_ONLY, "Ctrl+Ö", (MOD_CONTROL, 0xC0)),   # Qt names it by its capital
    (BRAZILIAN, "Ctrl+/", (MOD_CONTROL, 0xC1)), (BRAZILIAN, "Alt+;", (MOD_ALT, 0xBF)),
])
def test_symbol_keys_are_found_through_the_layout(layout, table, text, keys):
    """#523: a symbol key is the key that types that symbol unshifted on the
    player's layout (what "/" is depends on it)."""
    layout(table)
    assert windows_hotkey(text) == keys


@pytest.mark.parametrize("text", ["Ctrl+/", "Ctrl+=", "Ctrl+;", "Ctrl+*", "Ctrl+^", "/",
                                  "Shift+#"])
def test_a_symbol_the_layout_has_no_key_for_is_refused(layout, text):
    # "/" is Shift+7 on a German layout, "=" is Shift+0, ";" is Shift+comma,
    # "*" is Shift on the "+" key (registering that key would be Ctrl++),
    # "^" is a dead key, and a symbol alone or with Shift only toggles on
    # every press.
    layout(GERMAN)
    assert windows_hotkey(text) is None


def test_symbol_keys_are_named_by_what_they_type(layout):
    """The Overlay tab saves a symbol key as the symbol it types unshifted
    on the layout, and that text reads back as the same key, with every mix
    of Ctrl, Alt, Shift and Win that has Ctrl, Alt or Win in it."""
    from PyQt6.QtCore import Qt

    from src.gui.global_hotkey import _MODIFIERS, MODIFIERS_NEEDED, hotkey_text
    m = Qt.KeyboardModifier
    expected = {US: {0xBF: "Ctrl+/", 0xBA: "Ctrl+;", 0xDC: "Ctrl+\\"},
                GERMAN: {0xBF: "Ctrl+#", 0xBA: "Ctrl+Ü", 0xDB: "Ctrl+ß", 0xE2: "Ctrl+<"},
                BRAZILIAN: {0xC1: "Ctrl+/", 0xBF: "Ctrl+;", 0xBA: "Ctrl+Ç"}}
    for table, names in expected.items():
        layout(table)
        for virtual_key, text in names.items():
            assert hotkey_text(m.ControlModifier, virtual_key) == text
        for virtual_key in table.base:
            for mix in range(16):
                held, wanted = m.NoModifier, 0
                for bit, (qt_modifier, win_modifier) in enumerate(_MODIFIERS):
                    if mix >> bit & 1:
                        held |= qt_modifier
                        wanted |= win_modifier
                text = hotkey_text(held, virtual_key)
                if virtual_key in table.dead or not wanted & MODIFIERS_NEEDED:
                    assert text is None, (hex(virtual_key), mix)  # a dead key, or alone
                else:
                    assert windows_hotkey(text) == (wanted, virtual_key), (hex(virtual_key), mix)


def test_a_symbol_two_keys_type_is_saved_only_for_the_one_windows_finds(layout):
    from PyQt6.QtCore import Qt

    from src.gui.global_hotkey import hotkey_text
    layout(TWO_BACKSLASHES)
    assert hotkey_text(Qt.KeyboardModifier.ControlModifier, 0xDC) == "Ctrl+\\"
    # The other key would save "Ctrl+\\" and register 0xDC instead.
    assert hotkey_text(Qt.KeyboardModifier.ControlModifier, 0xE2) is None


def test_the_layout_lookups_off_windows_find_nothing(layout):
    layout(None)
    assert global_hotkey.layout_symbol(0xBF) is None
    assert global_hotkey.layout_symbol_key("/") is None
    assert windows_hotkey("Ctrl+/") is None


def test_a_symbol_hotkey_is_registered_by_its_key_and_refused_without_one(qapp, layout):
    fake = _FakeUser32()
    hotkey = GlobalHotkey(user32=fake)
    layout(US)
    assert hotkey.register("Ctrl+/") == ""
    assert fake.calls[0] == ("register", None, hotkey.hotkey_id, MOD_CONTROL | MOD_NOREPEAT, 0xBF)
    hotkey.unregister()
    layout(GERMAN)                           # the player switched layouts
    assert hotkey.register("Ctrl+/") == HOTKEY_UNSUPPORTED
    assert len(fake.calls) == 2              # nothing asked of Windows


@pytest.mark.parametrize("text", ["P", "Shift+P", "1", "Num+5", "Space", "Tab", "Left",
                                  "Shift+Del", "Shift+Home"])
def test_a_typing_key_needs_ctrl_alt_or_win(text):
    """#523 review: alone, or with Shift only, the key would toggle the
    drawer on every press in game and be taken from every other program."""
    assert windows_hotkey(text) is None


_SUPPORTED_KEYS = (list(range(0x30, 0x3A)) + list(range(0x41, 0x5B)) + list(range(0x60, 0x6A))
                   + list(range(0x70, 0x88))
                   + [0x09, 0x13, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E])


def test_virtual_keys_round_trip_with_every_modifier_mix():
    """#523: the Overlay tab records the key Windows reports, so every key
    it takes, with any mix of Ctrl, Alt, Shift and Win, reads back as that
    same key and those same modifiers. Without Ctrl, Alt or Win only an F
    key or Pause is taken."""
    from PyQt6.QtCore import Qt

    from src.gui.global_hotkey import _MODIFIERS, MODIFIERS_NEEDED, hotkey_text
    alone = set(range(0x70, 0x88)) | {0x13}
    for key in _SUPPORTED_KEYS:
        for mix in range(16):
            held, expected = Qt.KeyboardModifier.NoModifier, 0
            for bit, (qt_modifier, win_modifier) in enumerate(_MODIFIERS):
                if mix >> bit & 1:
                    held |= qt_modifier
                    expected |= win_modifier
            text = hotkey_text(held, key)
            if key in alone or expected & MODIFIERS_NEEDED:
                assert windows_hotkey(text) == (expected, key), (hex(key), mix)
            else:
                assert text is None, (hex(key), mix)


def test_virtual_key_text():
    from PyQt6.QtCore import Qt

    from src.gui.global_hotkey import hotkey_text
    m = Qt.KeyboardModifier
    assert hotkey_text(m.ControlModifier | m.AltModifier, 0x4F) == "Ctrl+Alt+O"
    assert hotkey_text(m.ControlModifier | m.ShiftModifier, 0x31) == "Ctrl+Shift+1"
    assert hotkey_text(m.ControlModifier, 0x65) == "Ctrl+Num+5"
    assert hotkey_text(m.NoModifier, 0x78) == "F9"
    assert hotkey_text(m.ShiftModifier, 0x4F) is None          # Shift alone is not enough
    # AltGr's and the number pad's own flags are no modifiers Windows
    # registers: a number pad arrow (NumLock off) is the arrow.
    assert hotkey_text(m.ControlModifier | m.AltModifier | m.GroupSwitchModifier, 0x4F) == \
        "Ctrl+Alt+O"
    assert hotkey_text(m.ControlModifier | m.KeypadModifier, 0x25) == "Ctrl+Left"
    for key in (0x1B, 0x0D, 0x08, 0x00):     # Esc, Enter, Backspace, nothing
        assert hotkey_text(m.ControlModifier, key) is None


class _FakeUser32:
    def __init__(self, refuse=False):
        self.calls, self.refuse = [], refuse

    def RegisterHotKey(self, hwnd, hotkey_id, modifiers, key):  # noqa: N802
        self.calls.append(("register", hwnd, hotkey_id, modifiers, key))
        return not self.refuse

    def UnregisterHotKey(self, hwnd, hotkey_id):  # noqa: N802
        self.calls.append(("unregister", hwnd, hotkey_id))
        return True


def test_the_filter_takes_only_its_own_messages(qapp):
    import ctypes
    from ctypes import wintypes

    hotkey = GlobalHotkey(user32=_FakeUser32())
    assert hotkey.register("Ctrl+Alt+O") == ""
    fired = []
    hotkey.activated.connect(lambda: fired.append(True))

    def deliver(message, identifier):
        msg = wintypes.MSG(None, message, identifier)
        return hotkey._filter.nativeEventFilter(b"windows_dispatcher_MSG", ctypes.addressof(msg))

    try:
        assert deliver(WM_HOTKEY, hotkey.hotkey_id) == (True, 0)
        assert deliver(WM_HOTKEY, hotkey.hotkey_id + 1) == (False, 0)
        assert deliver(0x00FF, hotkey.hotkey_id) == (False, 0)   # WM_INPUT
        assert fired == [True]
    finally:
        hotkey.unregister()


def test_register_change_and_clear(qapp):
    fake = _FakeUser32()
    hotkey = GlobalHotkey(user32=fake)
    key_id = hotkey.hotkey_id
    assert hotkey.register("Ctrl+Shift+O") == "" and hotkey.registered == "Ctrl+Shift+O"
    assert fake.calls == [("register", None, key_id, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, 0x4F)]
    assert hotkey.register("Ctrl+Shift+O") == "" and len(fake.calls) == 1   # held already
    assert hotkey.register("F9") == ""
    assert fake.calls[1:] == [("unregister", None, key_id),
                              ("register", None, key_id, MOD_NOREPEAT, 0x78)]
    assert hotkey.register("") == "" and hotkey.registered is None
    assert fake.calls[-1] == ("unregister", None, key_id)
    assert hotkey.register("Ctrl+Esc") == HOTKEY_UNSUPPORTED and len(fake.calls) == 4
    hotkey.unregister()                                       # nothing held: nothing asked
    assert len(fake.calls) == 4


def test_each_hotkey_has_its_own_id(qapp):
    first, second = GlobalHotkey(user32=_FakeUser32()), GlobalHotkey(user32=_FakeUser32())
    assert first.hotkey_id != second.hotkey_id


def test_a_refusal_is_reported_and_logged(qapp, caplog):
    hotkey = GlobalHotkey(user32=_FakeUser32(refuse=True))
    with caplog.at_level("WARNING", logger="src.gui.global_hotkey"):
        assert hotkey.register("Ctrl+Shift+O") == HOTKEY_TAKEN
    assert hotkey.registered is None
    assert any("refused the drawer hotkey Ctrl+Shift+O" in r.getMessage() for r in caplog.records)


def _has_keyboard_raw_input(user32):
    """Read registered device types in this process without reading input events."""
    import ctypes
    from ctypes import wintypes

    class RawInputDevice(ctypes.Structure):
        _fields_ = [
            ("usage_page", wintypes.USHORT), ("usage", wintypes.USHORT),
            ("flags", wintypes.DWORD), ("target", wintypes.HWND),
        ]

    get_devices = user32.GetRegisteredRawInputDevices
    get_devices.argtypes = [
        ctypes.POINTER(RawInputDevice), ctypes.POINTER(wintypes.UINT), wintypes.UINT,
    ]
    get_devices.restype = wintypes.UINT
    entries = (RawInputDevice * 16)()
    count = wintypes.UINT(len(entries))
    received = get_devices(entries, ctypes.byref(count), ctypes.sizeof(RawInputDevice))
    assert received <= len(entries), ctypes.get_last_error()
    return any((entry.usage_page, entry.usage) == (1, 6) for entry in entries[:received])


@pytest.mark.skipif(sys.platform != "win32", reason="RegisterHotKey is Windows only")
def test_a_real_hotkey_reaches_activated_and_a_second_owner_is_refused(qapp):
    import ctypes
    from ctypes import wintypes

    from PyQt6.QtCore import QCoreApplication

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM,
                                          wintypes.LPARAM]
    user32.PostThreadMessageW.restype = wintypes.BOOL
    thread = ctypes.WinDLL("kernel32").GetCurrentThreadId()
    combo = "Ctrl+Alt+Shift+F24"
    first = GlobalHotkey()
    second = GlobalHotkey()

    def post(hotkey_id):
        assert user32.PostThreadMessageW(thread, WM_HOTKEY, hotkey_id, 0)
        QCoreApplication.processEvents()

    fired, other = [], []
    first.activated.connect(lambda: fired.append(True))
    second.activated.connect(lambda: other.append(True))
    try:
        assert first.register(combo) == ""
        assert not _has_keyboard_raw_input(user32)
        assert second.register(combo) == HOTKEY_TAKEN          # Windows' own refusal
        post(first.hotkey_id)
        assert fired == [True] and other == []
        post(first.hotkey_id + 1000)
        assert fired == [True]                                 # another id is not ours
        first.unregister()
        assert not _has_keyboard_raw_input(user32)
        post(first.hotkey_id)
        assert fired == [True]                                 # no filter left to hear it
        assert second.register(combo) == ""                    # free again
        assert not _has_keyboard_raw_input(user32)
    finally:
        first.unregister()
        second.unregister()
