"""Tests for ensure_user_cfg_language — guarding against the duplicate-append bug."""
from unittest.mock import patch

import pytest

from src.utils.user_cfg import ensure_user_cfg_language, get_user_cfg_language


@pytest.fixture
def channel_dir(tmp_path):
    """Patch AppSettings so user.cfg lives under a clean tmp dir."""
    with patch("src.utils.user_cfg.AppSettings") as mock_settings:
        mock_settings.get_game_install_path.return_value = str(tmp_path)
        mock_settings.get_active_channel.return_value = "LIVE"
        mock_settings.get_selected_language.return_value = "english"
        yield tmp_path


def _user_cfg(channel_dir):
    return (channel_dir / "user.cfg").read_text(encoding="utf-8")


class TestEnsureUserCfgLanguage:
    def test_creates_user_cfg_when_missing(self, channel_dir):
        assert ensure_user_cfg_language() is True
        assert _user_cfg(channel_dir) == "g_language = english\n"

    def test_appends_when_key_absent(self, channel_dir):
        (channel_dir / "user.cfg").write_text("r_VSync = 1\n", encoding="utf-8")
        assert ensure_user_cfg_language() is True
        content = _user_cfg(channel_dir)
        assert content.count("g_language") == 1
        assert "g_language = english" in content
        assert "r_VSync = 1" in content

    @pytest.mark.regression
    @pytest.mark.parametrize("existing_line", [
        "g_language = english",          # canonical
        "g_language=english",            # no spaces
        "g_language= english",           # left-tight
        "g_language =english",           # right-tight
        "g_language  =  english",        # extra spaces
        "G_Language = english",          # mixed key case
        "g_language = English",          # mixed value case
        "g_language = ENGLISH",          # upper value
        'g_language = "english"',        # quoted value
        "g_language = english   ",       # trailing whitespace
        "g_language = english ; comment",  # trailing comment
    ])
    def test_does_not_duplicate_existing_english_setting(self, channel_dir, existing_line):
        original = f"r_VSync = 1\n{existing_line}\nr_Width = 1920\n"
        (channel_dir / "user.cfg").write_text(original, encoding="utf-8")

        assert ensure_user_cfg_language() is True

        content = _user_cfg(channel_dir)
        # The bug: every spacing/casing variant above used to cause a
        # second canonical line to be appended on each apply.
        assert content.lower().count("g_language") == 1, (
            f"Duplicate g_language appended for input {existing_line!r}\n"
            f"Got:\n{content}"
        )
        # And we must not have mutated the user's preferred format.
        assert existing_line in content

    def test_writes_sc_language_id_for_non_english(self, channel_dir):
        """Internal IDs (e.g. portuguese_br) map to SC language IDs in user.cfg."""
        (channel_dir / "user.cfg").write_text(
            "r_VSync = 1\n", encoding="utf-8"
        )
        assert ensure_user_cfg_language(language="portuguese_br") is True

        content = _user_cfg(channel_dir)
        assert "g_language = portuguese_(brazil)" in content
        assert "portuguese_br" not in content

    def test_returns_false_when_install_path_unset(self, tmp_path):
        with patch("src.utils.user_cfg.AppSettings") as mock_settings:
            mock_settings.get_game_install_path.return_value = ""
            assert ensure_user_cfg_language() is False

    def test_returns_false_when_install_path_missing(self, tmp_path):
        with patch("src.utils.user_cfg.AppSettings") as mock_settings:
            mock_settings.get_game_install_path.return_value = str(tmp_path / "nope")
            mock_settings.get_active_channel.return_value = "LIVE"
            assert ensure_user_cfg_language() is False

    def test_appends_without_blank_separator_when_file_ends_in_newline(self, channel_dir):
        (channel_dir / "user.cfg").write_text("r_VSync = 1\n\n", encoding="utf-8")
        ensure_user_cfg_language()
        # Should not introduce a spurious second blank line.
        content = _user_cfg(channel_dir)
        assert "\n\n\n" not in content


class TestGetUserCfgLanguage:
    """#398 review: a pure read, added alongside ensure_user_cfg_language
    (which also writes) so MainWindow._entries_already_applied can check
    the current value without side effects."""

    def test_reads_existing_value(self, tmp_path):
        (tmp_path / "user.cfg").write_text("g_language = french_(france)\n", encoding="utf-8")
        assert get_user_cfg_language(tmp_path) == "french_(france)"

    def test_case_and_spacing_tolerant_same_as_ensure(self, tmp_path):
        (tmp_path / "user.cfg").write_text("G_Language=  German_(Germany)  \n", encoding="utf-8")
        assert get_user_cfg_language(tmp_path) == "German_(Germany)"

    def test_returns_none_when_key_absent(self, tmp_path):
        (tmp_path / "user.cfg").write_text("r_VSync = 1\n", encoding="utf-8")
        assert get_user_cfg_language(tmp_path) is None

    def test_returns_none_when_file_missing(self, tmp_path):
        assert get_user_cfg_language(tmp_path) is None

    def test_returns_none_when_channel_path_empty(self):
        with patch("src.utils.user_cfg.AppSettings") as mock_settings:
            mock_settings.get_game_install_path.return_value = ""
            assert get_user_cfg_language() is None

    def test_does_not_modify_the_file(self, tmp_path):
        """Pure read -- unlike ensure_user_cfg_language, must never write."""
        original = "r_VSync = 1\ng_language = english\nr_Width = 1920\n"
        cfg_path = tmp_path / "user.cfg"
        cfg_path.write_text(original, encoding="utf-8")
        get_user_cfg_language(tmp_path)
        assert cfg_path.read_text(encoding="utf-8") == original

    def test_defaults_to_appsettings_game_install_path_when_unspecified(self, tmp_path):
        (tmp_path / "user.cfg").write_text("g_language = japanese_(japan)\n", encoding="utf-8")
        with patch("src.utils.user_cfg.AppSettings") as mock_settings:
            mock_settings.get_game_install_path.return_value = str(tmp_path)
            assert get_user_cfg_language() == "japanese_(japan)"
