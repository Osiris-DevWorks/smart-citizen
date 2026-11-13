"""Tests for the main-menu text added at apply-to-game time: the
Frontend_PU_Version watermark and the Play button reminder."""
from unittest.mock import patch

import pytest

from src.gui.main_window import (
    _BLENDER_PRO_MEDIUM,
    _FRONTEND_VERSION_KEY,
    _FRONTEND_VERSION_STAMP_RE,
    _MENU_PAD,
    _NOTO_SANS,
    _NOTO_SANS_SLOTS,
    _PLAY_BUTTON_KEY,
    _PLAY_BUTTON_REMINDER,
    _add_play_button_reminder,
    _centre_menu_lines,
    _menu_text_width,
    _stamp_frontend_version,
)
from src.utils.settings import SC_LANGUAGE_IDS


@pytest.fixture
def mock_version():
    with patch("src.utils.version.get_version", return_value="1.3.1"):
        yield "1.3.1"


class TestFrontendVersionStamp:
    def test_appends_watermark_to_stock_value(self, mock_version):
        merged = {_FRONTEND_VERSION_KEY: "Star Citizen Alpha 4.8.0 PTU"}
        _stamp_frontend_version(merged)
        assert merged[_FRONTEND_VERSION_KEY] == (
            "Star Citizen Alpha 4.8.0 PTU\\nLocalizations Enhanced with Smart Citizen v1.3.1"
        )

    def test_skips_when_key_missing(self, mock_version):
        merged = {"SomeOtherKey": "value"}
        _stamp_frontend_version(merged)
        assert _FRONTEND_VERSION_KEY not in merged

    def test_idempotent_same_version(self, mock_version):
        merged = {_FRONTEND_VERSION_KEY: "Star Citizen Alpha 4.8.0 PTU"}
        _stamp_frontend_version(merged)
        once = merged[_FRONTEND_VERSION_KEY]
        _stamp_frontend_version(merged)
        assert merged[_FRONTEND_VERSION_KEY] == once

    def test_rolls_forward_to_new_version(self):
        merged = {
            _FRONTEND_VERSION_KEY:
                "Star Citizen Alpha 4.8.0 PTU\\nLocalizations Enhanced with Smart Citizen v1.3.0"
        }
        with patch("src.utils.version.get_version", return_value="1.3.1"):
            _stamp_frontend_version(merged)
        assert merged[_FRONTEND_VERSION_KEY] == (
            "Star Citizen Alpha 4.8.0 PTU\\nLocalizations Enhanced with Smart Citizen v1.3.1"
        )

    def test_rolls_forward_from_old_pipe_format(self):
        # Pre-2.3.0 installs have the original " | "-separated watermark on
        # disk (#296-adjacent request: move the watermark to its own line) —
        # the next apply must replace it with the new "\n"-separated form,
        # not leave the old one dangling or double-stamp.
        merged = {
            _FRONTEND_VERSION_KEY:
                "Star Citizen Alpha 4.8.0 PTU | Localizations Enhanced with Smart Citizen v1.3.0"
        }
        with patch("src.utils.version.get_version", return_value="1.3.1"):
            _stamp_frontend_version(merged)
        assert merged[_FRONTEND_VERSION_KEY] == (
            "Star Citizen Alpha 4.8.0 PTU\\nLocalizations Enhanced with Smart Citizen v1.3.1"
        )

    @pytest.mark.parametrize("legacy_suffix", [
        # First-cut watermark (heart emoji as text, "by") — pre-1.3.1 prereleases
        "| Enhanced with <3 by Smart Citizen v1.3.0",
        "| Enhanced with <3 by Smart Citizen 1.2.9",
        # Second-cut watermark ("Enhanced by", no v) — interim 1.3.1 build
        "| Localizations Enhanced by Smart Citizen 1.3.0",
        "| Localizations Enhanced by Smart Citizen v1.3.0",
        # Third-cut watermark (" | "-separated "Enhanced with") — pre-2.3.0
        "| Localizations Enhanced with Smart Citizen v1.3.0",
    ])
    def test_strips_legacy_phrasings(self, mock_version, legacy_suffix):
        # Every prior on-disk watermark wording must be stripped, not
        # left to accumulate, so users who applied with an earlier
        # build get the current phrasing on next Apply.
        merged = {
            _FRONTEND_VERSION_KEY: f"Star Citizen Alpha 4.8.0 PTU {legacy_suffix}"
        }
        _stamp_frontend_version(merged)
        assert merged[_FRONTEND_VERSION_KEY] == (
            "Star Citizen Alpha 4.8.0 PTU\\nLocalizations Enhanced with Smart Citizen v1.3.1"
        )

    def test_preserves_user_edited_base_value(self, mock_version):
        merged = {_FRONTEND_VERSION_KEY: "My Custom Build"}
        _stamp_frontend_version(merged)
        assert merged[_FRONTEND_VERSION_KEY] == (
            "My Custom Build\\nLocalizations Enhanced with Smart Citizen v1.3.1"
        )

    def test_stamp_regex_matches_with_extra_whitespace(self):
        cases = [
            " | Localizations Enhanced with Smart Citizen v1.3.1",
            "  |  Localizations Enhanced with Smart Citizen v1.3.1",
            " | Localizations Enhanced with Smart Citizen 1.3.1",  # no-v tolerated
            " | Localizations Enhanced with Smart Citizen v1.3.1   ",
            "\\nLocalizations Enhanced with Smart Citizen v1.3.1",  # new form
            "\\nLocalizations Enhanced with Smart Citizen 1.3.1   ",  # no-v tolerated
        ]
        for suffix in cases:
            full = "Base value" + suffix
            assert _FRONTEND_VERSION_STAMP_RE.search(full), (
                f"regex did not match expected suffix: {suffix!r}"
            )

    def test_does_not_strip_pipe_in_base_value(self, mock_version):
        # Plain pipe in the middle isn't our watermark — leave it alone.
        merged = {_FRONTEND_VERSION_KEY: "Star Citizen | Build A"}
        _stamp_frontend_version(merged)
        assert merged[_FRONTEND_VERSION_KEY] == (
            "Star Citizen | Build A\\nLocalizations Enhanced with Smart Citizen v1.3.1"
        )


class TestPlayButtonReminder:
    """The Play button's second line, which tells players to run Smart Citizen
    again after a patch, with both lines centred."""

    STOCK = "Play Star Citizen"
    # 19 no-break spaces centre the English label under the reminder in the
    # menu font (19.3 worked out).
    WITH_REMINDER = _MENU_PAD * 19 + f"Play Star Citizen\\n{_PLAY_BUTTON_REMINDER}"

    def test_the_key_and_wording(self):
        # What players see in game. If the wording changes, make
        # _PLAY_BUTTON_REMINDER_RE strip the old wording too, as
        # _FRONTEND_VERSION_STAMP_RE strips the watermark's old phrasings.
        assert _PLAY_BUTTON_KEY == "Frontend_play_star_citizen"
        assert _PLAY_BUTTON_REMINDER == "Run Smart Citizen after every patch"

    def test_the_padding_is_a_no_break_space(self):
        # The source spells it as an escape, since the character itself looks
        # like a plain space there, and a plain space can be trimmed or
        # collapsed where a no-break space is kept.
        assert _MENU_PAD == "\u00a0"

    def test_adds_the_reminder_under_the_stock_label(self):
        merged = {_PLAY_BUTTON_KEY: self.STOCK}
        _add_play_button_reminder(merged)
        assert merged[_PLAY_BUTTON_KEY] == self.WITH_REMINDER

    def test_skips_when_key_missing(self):
        merged = {"SomeOtherKey": "value"}
        _add_play_button_reminder(merged)
        assert merged == {"SomeOtherKey": "value"}

    def test_idempotent(self):
        merged = {_PLAY_BUTTON_KEY: self.STOCK}
        _add_play_button_reminder(merged)
        _add_play_button_reminder(merged)
        assert merged[_PLAY_BUTTON_KEY] == self.WITH_REMINDER

    @pytest.mark.parametrize("earlier", [
        f"\\n{_PLAY_BUTTON_REMINDER}",
        f" \\n{_PLAY_BUTTON_REMINDER}",
        f"\\n\\n{_PLAY_BUTTON_REMINDER}",
        f"\\n {_PLAY_BUTTON_REMINDER}  ",
        f"\\n{_MENU_PAD * 3}{_PLAY_BUTTON_REMINDER}",  # one pushed right to centre it
    ])
    def test_replaces_an_earlier_reminder(self, earlier):
        # A label that already ends with the reminder, such as a user.ini
        # override imported from an applied global.ini, still gets just one.
        merged = {_PLAY_BUTTON_KEY: self.STOCK + earlier}
        _add_play_button_reminder(merged)
        assert merged[_PLAY_BUTTON_KEY] == self.WITH_REMINDER

    @pytest.mark.parametrize("blank", ["", "   ", "\u00a0\u00a0", " \\n "])
    def test_a_blank_label_leaves_just_the_reminder(self, blank):
        # No empty line above the reminder, padded or not, and a second apply
        # over the reminder alone keeps just the one.
        merged = {_PLAY_BUTTON_KEY: blank}
        _add_play_button_reminder(merged)
        assert merged[_PLAY_BUTTON_KEY] == _PLAY_BUTTON_REMINDER
        _add_play_button_reminder(merged)
        assert merged[_PLAY_BUTTON_KEY] == _PLAY_BUTTON_REMINDER

    def test_keeps_a_user_label(self):
        merged = {_PLAY_BUTTON_KEY: "Launch"}
        _add_play_button_reminder(merged)
        label, reminder = merged[_PLAY_BUTTON_KEY].split("\\n")
        assert label.lstrip(_MENU_PAD) == "Launch"
        assert label != "Launch"  # centred under the longer reminder
        assert reminder == _PLAY_BUTTON_REMINDER

    def test_does_not_strip_the_words_without_a_line_break(self):
        # Only a line of its own is the reminder: the same words at the end
        # of the label's own line are the user's text. That label is the
        # wider line, so the reminder is the one pushed right.
        label = f"Please {_PLAY_BUTTON_REMINDER}"
        merged = {_PLAY_BUTTON_KEY: label}
        _add_play_button_reminder(merged)
        first, second = merged[_PLAY_BUTTON_KEY].split("\\n")
        assert first == label
        assert second.lstrip(_MENU_PAD) == _PLAY_BUTTON_REMINDER
        assert second != _PLAY_BUTTON_REMINDER


class TestCentreMenuLines:
    """The game left-aligns the Play button's lines, so shorter ones are
    pushed right with no-break spaces to sit centred under the widest."""

    def test_the_widest_line_is_left_alone(self):
        lines = _centre_menu_lines(["Play Star Citizen", _PLAY_BUTTON_REMINDER])
        assert lines[1] == _PLAY_BUTTON_REMINDER

    @pytest.mark.parametrize("short", [
        "Play Star Citizen", "Launch", "Jouer à Star Citizen", "I", "WWW",
    ])
    def test_a_shorter_line_ends_up_centred_within_half_a_space(self, short):
        padded, widest = _centre_menu_lines([short, _PLAY_BUTTON_REMINDER])
        pad = len(padded) - len(short)
        assert padded == _MENU_PAD * pad + short
        space = _menu_text_width(" ")
        centre_short = pad * space + _menu_text_width(short) / 2
        assert abs(centre_short - _menu_text_width(widest) / 2) <= space / 2

    def test_widths_follow_the_capitals_the_game_draws(self):
        # Lower case is drawn in capitals, an accented capital as its letter,
        # and a no-break space as a space.
        assert _menu_text_width("play") == _menu_text_width("PLAY")
        assert _menu_text_width("É") == _menu_text_width("E")
        assert _menu_text_width(_MENU_PAD) == _menu_text_width(" ")
        assert _menu_text_width("I") < _menu_text_width("W")


def _noto(text):
    return _menu_text_width(text, _NOTO_SANS)


class TestMenuFonts:
    """The language slots that bring their own fonts draw the Play button in
    Noto Sans, so the reminder is centred in Noto Sans there and in Blender
    Pro Medium everywhere else."""

    def test_the_slots_that_draw_it_in_noto_sans(self):
        # The four with their own Data/Localization/<slot>/UI/fonts/Shared,
        # which Russian's borrowed Korean slot is one of.
        assert _NOTO_SANS_SLOTS == {
            "chinese_(simplified)", "chinese_(traditional)",
            "japanese_(japan)", "korean_(south_korea)",
        }
        assert SC_LANGUAGE_IDS["russian"] in _NOTO_SANS_SLOTS
        assert SC_LANGUAGE_IDS["turkish"] not in _NOTO_SANS_SLOTS

    def test_noto_sans_widths(self):
        # Read from the slots' fonts_en.swf in Data.p4k: the space and the
        # no-break space alike, the Latin and Cyrillic capitals (lower case is
        # drawn in capitals, an accented capital as its letter), a full em for
        # a CJK character, kana or a full-width form, 0.92 em for Hangul.
        assert _noto(" ") == _noto(_MENU_PAD) == 4580
        assert _noto("A") == 12440
        assert _noto("д") == _noto("Д") == 14580
        assert _noto("Й") == _noto("И")
        assert _noto("开") == _noto("プ") == _noto("Ａ") == 20480
        assert _noto("가") == 18840
        # Blender Pro Medium draws none of them, so it counts an average capital.
        assert _menu_text_width("开") == _BLENDER_PRO_MEDIUM.other

    @pytest.mark.parametrize("label, language", [
        ("开始游戏", "chinese"),
        ("開始遊戲", "chinese_traditional"),
        ("プレイ", "japanese"),
        ("플레이", "korean"),
        ("Играть", "russian"),
        ("Play Star Citizen", "korean"),
    ])
    def test_a_noto_sans_slot_is_centred_in_noto_sans(self, label, language):
        merged = {_PLAY_BUTTON_KEY: label}
        _add_play_button_reminder(merged, SC_LANGUAGE_IDS[language])
        padded, reminder = merged[_PLAY_BUTTON_KEY].split("\\n")
        assert reminder == _PLAY_BUTTON_REMINDER
        pad = len(padded) - len(label)
        assert padded == _MENU_PAD * pad + label
        space = _noto(" ")
        assert abs(pad * space + _noto(label) / 2 - _noto(reminder) / 2) <= space / 2
        # Blender Pro Medium's widths would pad it to another place.
        assert pad != len(_centre_menu_lines([label, _PLAY_BUTTON_REMINDER])[0]) - len(label)

    @pytest.mark.parametrize("language", ["english", "german", "french", "turkish"])
    def test_other_slots_are_centred_in_blender_pro(self, language):
        merged = {_PLAY_BUTTON_KEY: "Play Star Citizen"}
        _add_play_button_reminder(merged, SC_LANGUAGE_IDS[language])
        assert merged[_PLAY_BUTTON_KEY] == TestPlayButtonReminder.WITH_REMINDER
