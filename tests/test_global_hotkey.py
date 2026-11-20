"""#523: the SCO drawer's hotkey, through Windows' RegisterHotKey and, for a
game with focus that keeps WM_HOTKEY away, a look at the hotkey's own keys
(#587, which took out the keyboard's raw input).

The key mapping is checked on its own, with the rule that a key other than
an F key or Pause needs Ctrl, Alt or Win. ``KeyCheck`` runs against a
stand-in keyboard that records every key it is asked about: the
combination's key alone while it is up, and the modifiers only while it is
down. ``GlobalHotkey`` runs against a recorded stand-in for user32 (one
toggle per press, the native filter), and once for real: a combination no
keyboard can press (F24) is registered with Windows, the process then has
no keyboard raw input registered, a WM_HOTKEY for it is posted to this
thread and must come out of the Qt event loop as ``activated``, and a second
owner of the same combination is refused by Windows itself. No module in
``src/`` takes the keyboard's raw input or hooks it.
"""
import ast
import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

import pytest

from src.gui import global_hotkey
from src.gui.global_hotkey import (
    HOTKEY_TAKEN, HOTKEY_UNSUPPORTED, MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, MOD_SHIFT, MOD_WIN,
    WM_HOTKEY, GlobalHotkey, windows_hotkey,
)
from tests.event_loop import pump_until


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
    """RegisterHotKey and UnregisterHotKey, recorded instead of called, and a
    keyboard: keys in ``down`` read as down, a key in ``tapped`` reads with
    only Windows' "pressed since" bit, which a read clears as Windows does,
    and every key asked about is recorded in ``asked``."""

    def __init__(self, refuse=False):
        self.calls, self.refuse = [], refuse
        self.down, self.tapped, self.asked = set(), set(), []

    def RegisterHotKey(self, hwnd, hotkey_id, modifiers, key):  # noqa: N802
        self.calls.append(("register", hwnd, hotkey_id, modifiers, key))
        return not self.refuse

    def UnregisterHotKey(self, hwnd, hotkey_id):  # noqa: N802
        self.calls.append(("unregister", hwnd, hotkey_id))
        return True

    def GetAsyncKeyState(self, virtual_key):  # noqa: N802
        self.asked.append(virtual_key)
        if virtual_key in self.down:
            return -0x8000                                     # the high bit: down now
        if virtual_key in self.tapped:                         # down and up since last asked
            self.tapped.discard(virtual_key)
            return 1
        return 0


CTRL, ALT, SHIFT, LWIN, RWIN, O_KEY, PAUSE = 0x11, 0x12, 0x10, 0x5B, 0x5C, 0x4F, 0x13
MODIFIER_KEYS_IN_ORDER = [SHIFT, CTRL, ALT, LWIN, RWIN]


def _key_check(modifiers=MOD_CONTROL | MOD_ALT, key=O_KEY):
    from src.gui.global_hotkey import KeyCheck

    keyboard = _FakeUser32()
    return KeyCheck(modifiers, key, keyboard), keyboard


def _press(check, keyboard, *held):
    """Let go of every key, then press the check's key with *held* down."""
    keyboard.down = set()
    check.look()
    keyboard.down = {*held, check.key}
    return check.look()


def test_a_key_check_finds_the_combination_going_down_exactly():
    """#587: the looks make the combination as RegisterHotKey matches it,
    its key going down with exactly its modifiers held, once a press."""
    check, keyboard = _key_check()
    keyboard.down = {CTRL, ALT, O_KEY}
    assert not check.look()                                    # held as it was set: no press
    assert _press(check, keyboard, CTRL, ALT)
    assert not check.look()                                    # still held: the same press
    assert _press(check, keyboard, CTRL, ALT)                  # pressed again
    assert not _press(check, keyboard, CTRL, ALT, SHIFT)       # one modifier too many
    assert not _press(check, keyboard, ALT)                    # one too few
    assert not _press(check, keyboard)                         # none
    keyboard.down = {CTRL, ALT}
    check.look()
    keyboard.down = {CTRL, ALT, 0x50}
    assert not check.look()                                    # another key
    keyboard.down, keyboard.tapped = {CTRL, ALT}, {O_KEY}
    assert not check.look()                                    # only tapped since: not down


def test_either_win_key_is_win():
    check, keyboard = _key_check(MOD_WIN | MOD_SHIFT, 0x20)    # Win+Shift+Space
    for win in (LWIN, RWIN):
        assert _press(check, keyboard, win, SHIFT)
    assert not _press(check, keyboard, LWIN, RWIN, SHIFT, CTRL)


def test_the_modifiers_must_be_held_as_the_key_goes_down():
    """A modifier pressed after the key makes no press, as with
    RegisterHotKey, which matches only as the key goes down."""
    check, keyboard = _key_check()
    check.look()
    keyboard.down = {O_KEY}
    assert not check.look()
    keyboard.down = {CTRL, ALT, O_KEY}
    assert not check.look()                                    # the key was already down


def test_a_key_check_asks_about_its_key_alone_until_it_is_down():
    """#587: nothing else on the keyboard is ever asked about. While the
    combination's key is up only it is, whatever else is pressed, and the
    modifier keys only on the look that finds it newly down, stopping at the
    first that settles the answer."""
    check, keyboard = _key_check()                             # Ctrl+Alt+O
    keyboard.down = {0x41, 0x42, SHIFT}                        # typing, the key up
    for _ in range(3):
        check.look()
    assert keyboard.asked == [O_KEY] * 3
    keyboard.asked.clear()
    keyboard.down = {CTRL, ALT, O_KEY, 0x41}
    assert check.look()                                        # a match asks all five
    assert keyboard.asked == [O_KEY, *MODIFIER_KEYS_IN_ORDER]
    for down, asked in (({O_KEY}, [O_KEY, SHIFT, CTRL]),       # Ctrl up: settled
                        ({SHIFT, CTRL, ALT, O_KEY}, [O_KEY, SHIFT]),   # Shift extra
                        ({CTRL, ALT, LWIN, O_KEY}, [O_KEY, SHIFT, CTRL, ALT, LWIN])):
        keyboard.down = set()
        check.look()
        keyboard.down, keyboard.asked = down, []
        assert not check.look()
        assert keyboard.asked == asked, down


def test_a_combination_held_when_the_hotkey_is_set_is_no_press():
    check, keyboard = _key_check()
    keyboard.down = {CTRL, ALT, O_KEY}
    assert not check.look() and not check.look()
    assert _press(check, keyboard, CTRL, ALT)                  # pressed again


def test_after_forget_a_held_combination_is_a_press():
    """#587 review: the first look after ``forget`` (another window was in
    front) comes up to a slow tick after the game is back, so a combination
    already held then counts: it may have gone down just as the game came
    back. GlobalHotkey's one-press rule keeps one WM_HOTKEY already took to a
    single toggle."""
    check, keyboard = _key_check()
    check.look()
    check.forget()
    keyboard.down = {CTRL, ALT, O_KEY}
    assert check.look()
    assert not check.look()                                    # then held: the same press
    check.forget()
    keyboard.down = {CTRL, O_KEY}
    assert not check.look()                                    # held, but not the combination


def test_a_pause_press_is_found_by_its_pressed_since_bit():
    """#587 review: Windows reports a Pause press down and up at once, so a
    look never finds Pause down and takes its "pressed since" bit instead,
    alone or with modifiers. Not on the first look after the hotkey is set
    or after ``forget``, when the bit may be from a press made before, or in
    another window. Any other key's bit is no press (as above)."""
    check, keyboard = _key_check(0, PAUSE)
    keyboard.tapped = {PAUSE}                                  # pressed before it was set
    assert not check.look()
    keyboard.tapped = {PAUSE}
    assert check.look()                                        # pressed between two looks
    assert not check.look()                                    # the bit is cleared by a read
    keyboard.tapped = {PAUSE}
    check.forget()                                             # pressed in another window
    assert not check.look()
    keyboard.tapped = {PAUSE}
    assert check.look()
    alt_pause, keyboard = _key_check(MOD_ALT, PAUSE)
    alt_pause.look()
    keyboard.down, keyboard.tapped = {ALT}, {PAUSE}
    assert alt_pause.look()
    keyboard.down, keyboard.tapped = {ALT, CTRL}, {PAUSE}
    assert not alt_pause.look()                                # one modifier too many


def _hotkey_with_keys(qapp):
    clock = [50.0]
    fake = _FakeUser32()
    hotkey = GlobalHotkey(user32=fake, clock=lambda: clock[0])
    fired = []
    hotkey.activated.connect(lambda: fired.append(clock[0]))
    assert hotkey.register("Ctrl+Alt+O") == ""
    return hotkey, fake, clock, fired


def _press_keys(hotkey, fake):
    """Ctrl+Alt+O pressed and let go, looked at as the overlay's ticks do."""
    for down in (set(), {CTRL, ALT, O_KEY}, set()):
        fake.down = down
        hotkey.check_keys()


def test_keys_are_asked_about_only_while_the_hotkey_is_held(qapp):
    """#587: no key is asked about before the hotkey is registered or after
    it goes."""
    fake = _FakeUser32()
    hotkey = GlobalHotkey(user32=fake)
    hotkey.check_keys()
    hotkey.forget_keys()
    assert fake.asked == []
    assert hotkey.register("Ctrl+Alt+O") == ""
    hotkey.check_keys()
    assert fake.asked == [O_KEY]
    hotkey.unregister()
    hotkey.check_keys()
    assert fake.asked == [O_KEY]


def test_the_first_check_after_a_registration_is_logged(qapp, caplog):
    """#587 review: the in-game hotkey hangs on the overlay seeing the game in
    front, so the first check after each registration says so at INFO, and a
    log without that line shows the game was never seen."""
    hotkey, _fake, _clock, _fired = _hotkey_with_keys(qapp)

    def lines():
        return [r for r in caplog.records if "drawer hotkey's keys are checked" in r.getMessage()]

    with caplog.at_level("INFO", logger="src.gui.global_hotkey"):
        assert lines() == []
        for _ in range(3):
            hotkey.check_keys()
        assert [r.levelname for r in lines()] == ["INFO"]
        hotkey.unregister()
        assert hotkey.register("Ctrl+Alt+O") == ""
        hotkey.check_keys()
        assert len(lines()) == 2
    hotkey.unregister()


def test_in_game_a_key_check_toggles_once_per_press(qapp):
    """A game with focus keeps WM_HOTKEY away: a press the key check finds
    acts after KEY_GRACE_MS, once per press, and a later press acts again."""
    from src.gui.global_hotkey import SAME_PRESS_S
    hotkey, fake, clock, fired = _hotkey_with_keys(qapp)
    _press_keys(hotkey, fake)
    assert fired == [] and hotkey._key_wait.isActive()         # a queued WM_HOTKEY first
    assert pump_until(lambda: fired) and fired == [50.0]
    clock[0] += SAME_PRESS_S + 0.1
    _press_keys(hotkey, fake)
    assert pump_until(lambda: len(fired) == 2)
    hotkey.unregister()


def test_a_press_just_as_the_game_comes_back_counts(qapp):
    """#587 review: after forget_keys (another window in front), the
    combination already down at the first check is a press, and one that
    WM_HOTKEY toggled in the other window, still held as the game comes
    back, toggles only once."""
    from src.gui.global_hotkey import SAME_PRESS_S
    hotkey, fake, clock, fired = _hotkey_with_keys(qapp)
    hotkey.check_keys()                                        # the game in front, keys up
    hotkey.forget_keys()                                       # another window in front
    fake.down = {CTRL, ALT, O_KEY}                             # pressed as the game came back
    hotkey.check_keys()
    assert pump_until(lambda: fired) and len(fired) == 1
    fake.down = set()
    hotkey.check_keys()
    clock[0] += SAME_PRESS_S + 0.1
    hotkey.forget_keys()                                       # another window in front
    fake.down = {CTRL, ALT, O_KEY}
    hotkey.hotkey_message()                                    # toggled there by WM_HOTKEY
    hotkey.check_keys()                                        # still held as the game is back
    assert len(fired) == 2 and not hotkey._key_wait.isActive()
    hotkey.unregister()


def test_one_press_seen_both_ways_toggles_once(qapp):
    """Should the game let a press through as WM_HOTKEY too, it is one
    toggle, by WM_HOTKEY when it is in time, whichever comes first."""
    from PyQt6.QtTest import QTest

    from src.gui.global_hotkey import KEY_GRACE_MS, SAME_PRESS_S
    hotkey, fake, clock, fired = _hotkey_with_keys(qapp)
    _press_keys(hotkey, fake)                                  # the key check first
    hotkey.hotkey_message()
    assert len(fired) == 1 and not hotkey._key_wait.isActive()   # its wait is over
    QTest.qWait(KEY_GRACE_MS + 60)
    assert len(fired) == 1
    clock[0] += SAME_PRESS_S + 0.1
    hotkey.hotkey_message()                                    # WM_HOTKEY first
    _press_keys(hotkey, fake)
    assert len(fired) == 2 and not hotkey._key_wait.isActive()  # nothing to wait for
    clock[0] += SAME_PRESS_S + 0.1
    _press_keys(hotkey, fake)                                  # the key check acts first
    assert pump_until(lambda: len(fired) == 3)
    hotkey.hotkey_message()                                    # its WM_HOTKEY, late
    assert len(fired) == 3
    hotkey.unregister()


def test_the_filter_takes_only_its_own_hotkey(qapp):
    """WM_HOTKEY for its id is consumed. Another id, and any other message,
    a keyboard's WM_INPUT or WM_KEYDOWN among them, is left alone."""
    from src.gui.global_hotkey import WM_HOTKEY
    hotkey, fake, _clock, fired = _hotkey_with_keys(qapp)

    def deliver(message, hwnd=0, wparam=0, lparam=0, kind=b"windows_dispatcher_MSG"):
        msg = wintypes.MSG(hwnd or None, message, wparam, lparam)
        return hotkey._filter.nativeEventFilter(kind, ctypes.addressof(msg))

    assert deliver(WM_HOTKEY, wparam=hotkey.hotkey_id) == (True, 0) and len(fired) == 1
    assert deliver(WM_HOTKEY, wparam=hotkey.hotkey_id + 1) == (False, 0) and len(fired) == 1
    wm_input, wm_keydown = 0x00FF, 0x0100
    for message in (wm_input, wm_keydown):
        assert deliver(message, hwnd=0x1234, wparam=O_KEY, lparam=7,
                       kind=b"windows_generic_MSG") == (False, 0)
    assert len(fired) == 1 and fake.asked == []
    hotkey.unregister()


# Calls that would hand the app keys it was not asked for: raw input and
# keyboard hooks. And the calls that ask about a key's state, which only the
# key check may make (#587).
_RAW_INPUT_OR_HOOK = {"RegisterRawInputDevices", "GetRawInputData", "GetRawInputBuffer",
                      "RIDEV_INPUTSINK", "RIDEV_EXINPUTSINK", "SetWindowsHookEx",
                      "SetWindowsHookExA", "SetWindowsHookExW"}
_KEY_STATE_CALLS = {"GetAsyncKeyState", "GetKeyState", "GetKeyboardState"}


def _names_used(source):
    """``(line, name)`` for each name a module uses: attributes, names, what an
    import brings in (aliased or not) and str or bytes constants (ctypes takes
    a function's name as bytes too). Prose in a docstring is one long string,
    so it names nothing."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute):
            name = node.attr
        elif isinstance(node, ast.Name):
            name = node.id
        elif isinstance(node, ast.alias):
            name = node.name.rsplit(".", 1)[-1]
        elif isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
            name = node.value.decode("latin-1") if isinstance(node.value, bytes) else node.value
        else:
            continue
        found.append((node.lineno, name))
    return found


def test_no_module_takes_raw_input_hooks_or_other_keys():
    """#587: the hotkey's keys are asked about, never sent to the app. No
    module in src/ or scripts/ (the enhancement generator runs inside the
    app) names a raw input or hook call, and only the key check
    (src/gui/global_hotkey.py) asks about a key's state, so nothing else
    can ask about other keys. A file that names none of them as text is not
    parsed."""
    root = Path(__file__).resolve().parents[1]
    watched = _RAW_INPUT_OR_HOOK | _KEY_STATE_CALLS
    banned, key_state = [], set()
    for folder in ("src", "scripts"):
        for path in sorted((root / folder).rglob("*.py")):
            text = path.read_text(encoding="utf-8-sig")
            if not any(name in text for name in watched):
                continue
            where = path.relative_to(root).as_posix()
            for line, name in _names_used(text):
                if name in _RAW_INPUT_OR_HOOK:
                    banned.append(f"{where}:{line} {name}")
                elif name in _KEY_STATE_CALLS:
                    key_state.add(where)
    assert banned == []
    assert key_state == {"src/gui/global_hotkey.py"}          # and the scan read the key check
    # The scan sees each kind of use, and leaves prose alone.
    snippet = ("user32.RegisterRawInputDevices(x)\nRIDEV_INPUTSINK = 1\n"
               "getattr(user32, 'SetWindowsHookExW')\nuser32[b'SetWindowsHookExA']\n"
               "from win32con import RIDEV_EXINPUTSINK as SINK\nuser32.GetKeyState(0x46)\n"
               "'''RegisterRawInputDevices and GetKeyboardState in prose'''\n")
    assert sorted(name for _, name in _names_used(snippet) if name in watched) == [
        "GetKeyState", "RIDEV_EXINPUTSINK", "RIDEV_INPUTSINK", "RegisterRawInputDevices",
        "SetWindowsHookExA", "SetWindowsHookExW"]


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


KEYBOARD, JOYSTICK = (0x01, 0x06), (0x01, 0x04)     # raw input's usage page and usage


class _RawInputDevice(ctypes.Structure):
    _fields_ = [("usUsagePage", wintypes.USHORT), ("usUsage", wintypes.USHORT),
                ("dwFlags", wintypes.DWORD), ("hwndTarget", wintypes.HWND)]


def _raw_input_user32():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetRegisteredRawInputDevices.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.UINT),
                                                    wintypes.UINT]
    user32.GetRegisteredRawInputDevices.restype = wintypes.UINT
    user32.RegisterRawInputDevices.argtypes = [ctypes.POINTER(_RawInputDevice), wintypes.UINT,
                                               wintypes.UINT]
    user32.RegisterRawInputDevices.restype = wintypes.BOOL
    return user32


def _registered_raw_input() -> set:
    """The devices this process has raw input registered for, from any window
    or none (GetRegisteredRawInputDevices), as (usage page, usage)."""
    user32 = _raw_input_user32()
    size, count = ctypes.sizeof(_RawInputDevice), wintypes.UINT(0)
    user32.GetRegisteredRawInputDevices(None, ctypes.byref(count), size)
    devices = (_RawInputDevice * max(count.value, 1))()
    if count.value and user32.GetRegisteredRawInputDevices(
            devices, ctypes.byref(count), size) == 0xFFFFFFFF:
        raise ctypes.WinError(ctypes.get_last_error())
    return {(d.usUsagePage, d.usUsage) for d in devices[:count.value]}


@pytest.mark.skipif(sys.platform != "win32", reason="raw input is Windows only")
def test_the_raw_input_check_sees_a_registration():
    """The control for the next test: the check finds a device this test
    registers for raw input (a joystick, never the keyboard), and not once it
    is removed."""
    user32 = _raw_input_user32()

    def register(flags):
        device = _RawInputDevice(*JOYSTICK, flags, None)
        assert user32.RegisterRawInputDevices(ctypes.byref(device), 1, ctypes.sizeof(device))

    assert JOYSTICK not in _registered_raw_input()
    register(0)
    try:
        assert JOYSTICK in _registered_raw_input()
    finally:
        register(0x0001)                                       # RIDEV_REMOVE
    assert JOYSTICK not in _registered_raw_input()


@pytest.mark.skipif(sys.platform != "win32", reason="RegisterHotKey is Windows only")
def test_a_real_hotkey_reaches_activated_and_a_second_owner_is_refused(qapp):
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
        # #587: the hotkey takes no keyboard input from Windows, and its key
        # check asks Windows through the typed copy (F24 is never down).
        assert KEYBOARD not in _registered_raw_input()
        first.check_keys()
        first.check_keys()
        assert not first._key_wait.isActive()
        assert second.register(combo) == HOTKEY_TAKEN          # Windows' own refusal
        post(first.hotkey_id)
        assert fired == [True] and other == []
        post(first.hotkey_id + 1000)
        assert fired == [True]                                 # another id is not ours
        first.unregister()
        post(first.hotkey_id)
        assert fired == [True]                                 # no filter left to hear it
        assert second.register(combo) == ""                    # free again
        assert KEYBOARD not in _registered_raw_input()
    finally:
        first.unregister()
        second.unregister()
