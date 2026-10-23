"""#523: the SCO drawer's hotkey, through Windows' RegisterHotKey and, for a
game with focus that keeps WM_HOTKEY away, the keyboard's raw input.

The key mapping is checked on its own, with the rule that a key other than
an F key or Pause needs Ctrl, Alt or Win. ``RawCombination`` is fed press
and release streams. ``GlobalHotkey`` runs against a recorded stand-in for
user32 (the raw input window, one toggle per press, the native filter), and
once for real: a combination no keyboard can press (F24) is registered with
Windows along with its raw input, a WM_HOTKEY for it is posted to this
thread and must come out of the Qt event loop as ``activated``, and a second
owner of the same combination is refused by Windows itself.
"""
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
    def __init__(self, refuse=False, refuse_raw=False):
        self.calls, self.refuse, self.refuse_raw, self.raw = [], refuse, refuse_raw, []

    def RegisterHotKey(self, hwnd, hotkey_id, modifiers, key):  # noqa: N802
        self.calls.append(("register", hwnd, hotkey_id, modifiers, key))
        return not self.refuse

    def UnregisterHotKey(self, hwnd, hotkey_id):  # noqa: N802
        self.calls.append(("unregister", hwnd, hotkey_id))
        return True

    def RegisterRawInputDevices(self, device, count, size):  # noqa: N802
        d = device._obj
        self.raw.append((d.usUsagePage, d.usUsage, d.dwFlags, d.hwndTarget or 0, count))
        return not self.refuse_raw

    SINK = 0x5150

    def CreateWindowExW(self, ex_style, cls, title, style, x, y, w, h, parent,  # noqa: N802
                        menu, instance, param):
        self.windows = getattr(self, "windows", []) + [(cls, parent)]
        return self.SINK

    def DestroyWindow(self, hwnd):  # noqa: N802
        self.destroyed = getattr(self, "destroyed", []) + [hwnd]
        return True


CTRL, ALT, SHIFT, O_KEY = 0x11, 0x12, 0x10, 0x4F


def _combination(modifiers=MOD_CONTROL | MOD_ALT, key=O_KEY, windows_says=0):
    from src.gui.global_hotkey import RawCombination

    clock = [100.0]
    tracker = RawCombination(modifiers, key, modifiers_now=lambda: windows_says,
                             clock=lambda: clock[0])
    return tracker, clock


def test_raw_presses_match_the_combination_exactly():
    """#523: the raw stream, in order, makes the combination: its key going
    down with exactly its modifiers held, as RegisterHotKey matches."""
    tracker, _clock = _combination()
    presses = [tracker.feed(vk, False) for vk in (CTRL, ALT, O_KEY)]
    assert presses == [False, False, True]
    assert not tracker.feed(O_KEY, False)                      # a key repeat
    tracker.feed(O_KEY, True)
    assert tracker.feed(O_KEY, False)                          # pressed again
    tracker.feed(O_KEY, True)
    tracker.feed(SHIFT, False)
    assert not tracker.feed(O_KEY, False)                      # one modifier too many
    tracker.feed(O_KEY, True)
    tracker.feed(SHIFT, True)
    tracker.feed(ALT, True)
    assert not tracker.feed(O_KEY, False)                      # one too few
    tracker.feed(O_KEY, True)
    tracker.feed(0xA4, False)                                  # left Alt by its own key
    assert tracker.feed(O_KEY, False)
    assert not tracker.feed(0x50, False)                       # another key


def test_a_stale_modifier_is_checked_with_windows():
    """A release that never arrived (a lock screen) must not leave Ctrl down
    for good: a modifier held past STALE_AFTER is asked about."""
    from src.gui.global_hotkey import RawCombination

    tracker, clock = _combination(modifiers=MOD_ALT, windows_says=MOD_ALT)
    tracker.feed(CTRL, False)                                  # its release is lost
    tracker.feed(ALT, False)
    clock[0] += RawCombination.STALE_AFTER + 1
    assert tracker.feed(O_KEY, False)                          # Windows: only Alt is down
    held, clock = _combination(windows_says=MOD_CONTROL | MOD_ALT)
    held.feed(CTRL, False)
    held.feed(ALT, False)
    clock[0] += RawCombination.STALE_AFTER + 1
    assert held.feed(O_KEY, False)                             # still down, still counted


def test_a_lost_release_of_the_key_misses_no_press():
    """A press of the key last seen longer ago than STALE_AFTER is a new
    press: its release was lost (a lock screen), and a held key repeats
    far more often than that."""
    from src.gui.global_hotkey import RawCombination

    tracker, clock = _combination(windows_says=MOD_CONTROL | MOD_ALT)   # both still held
    for vk in (CTRL, ALT):
        tracker.feed(vk, False)
    assert tracker.feed(O_KEY, False)                          # its release is lost
    clock[0] += 0.5
    assert not tracker.feed(O_KEY, False)                      # a repeat in time is a repeat
    clock[0] += RawCombination.STALE_AFTER + 1
    assert tracker.feed(O_KEY, False)


def test_modifiers_down_now_asks_windows_about_each_modifier(monkeypatch):
    from src.gui import global_hotkey

    class _Keys:
        def __init__(self, down):
            self.down, self.asked = down, []

        def GetAsyncKeyState(self, vk):  # noqa: N802
            self.asked.append(vk)
            return -0x8000 if vk in self.down else 0           # the high bit: down now

    keys = _Keys({0x11, 0x5C})                                 # Ctrl and the right Win key
    monkeypatch.setattr(global_hotkey, "_user32", lambda: keys)
    assert global_hotkey.modifiers_down_now() == MOD_CONTROL | MOD_WIN
    assert set(keys.asked) == set(global_hotkey._MODIFIER_VKS)
    keys.down = {0xA4}                                         # left Alt by its own key
    assert global_hotkey.modifiers_down_now() == MOD_ALT
    monkeypatch.setattr(global_hotkey, "_user32", lambda: None)  # off Windows
    assert global_hotkey.modifiers_down_now() == 0


def _raw_hotkey(qapp, fake=None):
    clock = [50.0]
    hotkey = GlobalHotkey(user32=fake or _FakeUser32(), clock=lambda: clock[0])
    fired = []
    hotkey.activated.connect(lambda: fired.append(clock[0]))
    assert hotkey.register("Ctrl+Alt+O") == ""
    return hotkey, clock, fired


def _press_raw(hotkey):
    for vk, released in ((CTRL, False), (ALT, False), (O_KEY, False),
                         (O_KEY, True), (ALT, True), (CTRL, True)):
        hotkey.raw_key(vk, released)


def test_raw_input_is_switched_on_with_the_hotkey(qapp):
    from src.gui.global_hotkey import HWND_MESSAGE, RIDEV_INPUTSINK, RIDEV_REMOVE

    fake = _FakeUser32()
    hotkey, _clock, _fired = _raw_hotkey(qapp, fake)
    # A message-only window, keyboard input sent to it whatever has focus.
    assert fake.windows == [("STATIC", HWND_MESSAGE)] and hotkey.sink_hwnd == fake.SINK
    assert fake.raw == [(1, 6, RIDEV_INPUTSINK, fake.SINK, 1)]
    hotkey.unregister()
    assert fake.raw[-1] == (1, 6, RIDEV_REMOVE, 0, 1)
    assert fake.destroyed == [fake.SINK] and hotkey.sink_hwnd == 0
    hotkey.raw_key(O_KEY, False)                               # nothing held: nothing done
    assert not hotkey._raw_wait.isActive()


def test_raw_input_refused_still_leaves_the_hotkey(qapp, caplog):
    fake = _FakeUser32(refuse_raw=True)
    with caplog.at_level("INFO", logger="src.gui.global_hotkey"):
        hotkey, _clock, _fired = _raw_hotkey(qapp, fake)
    assert hotkey.registered == "Ctrl+Alt+O"
    assert fake.destroyed == [fake.SINK] and hotkey.sink_hwnd == 0   # its window closed
    assert any("raw input refused" in r.getMessage() for r in caplog.records)
    hotkey.unregister()
    assert fake.destroyed == [fake.SINK]                       # nothing left to close


def test_in_game_raw_input_toggles_once_per_press(qapp):
    """A game with focus keeps WM_HOTKEY away: raw input's sighting acts
    after RAW_GRACE_MS, once per press, and a later press acts again."""
    from PyQt6.QtTest import QTest

    from src.gui.global_hotkey import RAW_GRACE_MS, SAME_PRESS_S
    hotkey, clock, fired = _raw_hotkey(qapp)
    _press_raw(hotkey)
    assert fired == [] and hotkey._raw_wait.isActive()         # WM_HOTKEY gets its chance
    QTest.qWait(RAW_GRACE_MS + 60)
    assert fired == [50.0]
    clock[0] += SAME_PRESS_S + 0.1
    _press_raw(hotkey)
    QTest.qWait(RAW_GRACE_MS + 60)
    assert len(fired) == 2
    hotkey.unregister()


def test_one_press_seen_both_ways_toggles_once(qapp):
    """Outside a game a press brings WM_HOTKEY and raw input: one toggle,
    by WM_HOTKEY when it is in time, whichever comes first."""
    from PyQt6.QtTest import QTest

    from src.gui.global_hotkey import RAW_GRACE_MS, SAME_PRESS_S
    hotkey, clock, fired = _raw_hotkey(qapp)
    _press_raw(hotkey)                                         # raw input first
    hotkey.hotkey_message()
    assert len(fired) == 1 and not hotkey._raw_wait.isActive()   # its wait is over
    QTest.qWait(RAW_GRACE_MS + 60)
    assert len(fired) == 1
    clock[0] += SAME_PRESS_S + 0.1
    hotkey.hotkey_message()                                    # WM_HOTKEY first
    _press_raw(hotkey)
    QTest.qWait(RAW_GRACE_MS + 60)
    assert len(fired) == 2
    clock[0] += SAME_PRESS_S + 0.1
    _press_raw(hotkey)                                         # raw acted, WM_HOTKEY late
    QTest.qWait(RAW_GRACE_MS + 60)
    hotkey.hotkey_message()
    assert len(fired) == 3
    hotkey.unregister()


class _RawEvents(_FakeUser32):
    """GetRawInputData answering from a table of handles."""

    def __init__(self, events):
        super().__init__()
        self.events, self.reads = events, []

    def GetRawInputData(self, handle, command, buffer, size_ref, header_size):  # noqa: N802
        import ctypes

        from src.gui.global_hotkey import RAWINPUTHEADER, RAWKEYBOARD
        size = size_ref._obj
        total = ctypes.sizeof(RAWINPUTHEADER) + ctypes.sizeof(RAWKEYBOARD)
        if buffer is None:
            size.value = total
            return 0
        self.reads.append(handle)
        kind, vk, released = self.events[handle]
        RAWINPUTHEADER.from_buffer(buffer).dwType = kind
        keyboard = RAWKEYBOARD.from_buffer(buffer, ctypes.sizeof(RAWINPUTHEADER))
        keyboard.VKey, keyboard.Flags = vk, 1 if released else 0
        return total


def test_raw_messages_are_read_once_each(qapp):
    """Qt can hand one WM_INPUT to the filter twice; it is read once."""
    from PyQt6.QtTest import QTest

    from src.gui.global_hotkey import RAW_GRACE_MS
    events = {1: (1, CTRL, False), 2: (1, ALT, False), 3: (1, O_KEY, False),
              4: (0, O_KEY, False)}                            # 4: a mouse, not a keyboard
    fake = _RawEvents(events)
    hotkey, _clock, fired = _raw_hotkey(qapp, fake)
    for handle in (1, 1, 2, 2, 4, 3, 3):
        hotkey.raw_message(handle)
    assert fake.reads == [1, 2, 4, 3]
    QTest.qWait(RAW_GRACE_MS + 60)
    assert len(fired) == 1
    hotkey.unregister()


def test_the_filter_takes_only_its_own_messages(qapp):
    """WM_HOTKEY for its id is consumed; WM_INPUT for its hidden window is
    read and then left to Windows' default handling, which tidies it up."""
    import ctypes
    from ctypes import wintypes

    from src.gui.global_hotkey import WM_HOTKEY, WM_INPUT
    fake = _RawEvents({7: (1, CTRL, False)})
    hotkey, _clock, fired = _raw_hotkey(qapp, fake)

    def deliver(message, hwnd=0, wparam=0, lparam=0, kind=b"windows_dispatcher_MSG"):
        msg = wintypes.MSG(hwnd or None, message, wparam, lparam)
        return hotkey._filter.nativeEventFilter(kind, ctypes.addressof(msg))

    assert deliver(WM_HOTKEY, wparam=hotkey.hotkey_id) == (True, 0) and len(fired) == 1
    assert deliver(WM_HOTKEY, wparam=hotkey.hotkey_id + 1) == (False, 0) and len(fired) == 1
    assert deliver(WM_INPUT, hwnd=0x1234, lparam=7) == (False, 0)   # another window's
    assert fake.reads == []
    assert deliver(WM_INPUT, hwnd=fake.SINK, lparam=7, kind=b"windows_generic_MSG") == (False, 0)
    assert fake.reads == [7]
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
    combo = "Ctrl+Alt+Shift+F24"          # no keyboard has F24, so nobody presses it meanwhile
    # Each post is a press of its own: a second WM_HOTKEY within SAME_PRESS_S
    # would be taken as the same press, whatever its id.
    clock = [0.0]
    first = GlobalHotkey(clock=lambda: clock[0])
    second = GlobalHotkey()

    def post(hotkey_id):
        clock[0] += 10
        assert user32.PostThreadMessageW(thread, WM_HOTKEY, hotkey_id, 0)
        QCoreApplication.processEvents()

    fired, other = [], []
    first.activated.connect(lambda: fired.append(True))
    second.activated.connect(lambda: other.append(True))
    try:
        assert first.register(combo) == ""
        assert first._raw_on and first.sink_hwnd               # Windows took the raw input too
        assert second.register(combo) == HOTKEY_TAKEN          # Windows' own refusal
        post(first.hotkey_id)
        assert fired == [True] and other == []
        post(first.hotkey_id + 1000)
        assert fired == [True]                                 # another id is not ours
        first.unregister()
        assert not first._raw_on
        post(first.hotkey_id)
        assert fired == [True]                                 # no filter left to hear it
        assert second.register(combo) == ""                    # free again
    finally:
        first.unregister()
        second.unregister()
