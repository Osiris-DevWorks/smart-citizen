"""#502: the ``global`` source stays on the selected language's base.ini.

With a language other than English selected, the ``global`` merge source is
that language's own base.ini (``{channel}\\cache\\lang\\{language}\\base.ini``,
downloaded from its sources.json URL), which a language switch sets and
``main()`` sets again at every start. A successful global.ini extraction, a
channel switch and a data-folder change pointed it back at the English
base.ini whatever the language, and the bundled ``languages/<language>/
global.ini`` overlays are empty, so the table, and the next Apply, turned
English until the next start. All four now share one rule,
``AppSettings.get_global_source_base_ini``: the language's own base.ini when
the active channel's cache has it, otherwise the English one.

Real settings (a JsonSettings file in tmp_path, never the registry), the
real path helpers and the real loader (``load_sources_from_settings``), and
the real ``MainWindow`` methods on stub windows. German is selected unless a
test says otherwise. Each base.ini holds one ``ui_Greeting``, so the value
the loader returns says which file the table shows.
"""
from __future__ import annotations

import ast
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.gui.main_window import MainWindow
from src.parser.ini_parser import load_sources_from_settings
from src.utils.json_settings import JsonSettings
from src.utils.settings import AppSettings

pytestmark = pytest.mark.unit

GERMAN = "german"
ENGLISH = AppSettings.DEFAULT_LANGUAGE
_MAIN = Path(__file__).resolve().parent.parent / "src" / "main.py"
_URL = "https://example.invalid/global.ini"


@pytest.fixture
def profile(tmp_path, monkeypatch):
    """A profile entirely under tmp_path: settings in a JsonSettings file,
    registry-mode paths, the data folder in tmp_path, LIVE active, no
    enhancement categories (so the loader reads only base.ini and user.ini)
    and German selected. Returns tmp_path."""
    monkeypatch.setattr(AppSettings, "_backend", JsonSettings(tmp_path / "config.json"))
    monkeypatch.setattr("src.utils.build_mode.IS_PORTABLE", False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    monkeypatch.setattr(AppSettings, "get_enabled_enhancement_categories",
                        staticmethod(lambda: set()))
    AppSettings.set_user_data_dir(tmp_path / "data")
    AppSettings.set_selected_language(GERMAN)
    return tmp_path


def _write_base(language: str, greeting: str) -> Path:
    """*language*'s base.ini for the active channel and data folder."""
    path = AppSettings.get_base_ini_path(language)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"ui_Greeting={greeting}\n", encoding="utf-8")
    return path


def _global_source() -> str:
    return AppSettings.get_source_path(AppSettings.SOURCE_GLOBAL)


def _table_greeting() -> str:
    sources, _hierarchy, _categories = load_sources_from_settings()
    return sources[AppSettings.SOURCE_GLOBAL]["ui_Greeting"]


def _switch_to_german(german_base: Path) -> None:
    """The end of a real language switch whose base.ini fetch worked."""
    me = MagicMock()
    me._lang_dl_worker = None
    MainWindow._on_language_base_ready(me, GERMAN, german_base, None, True)


class TestTheRule:
    def test_english_reads_the_english_base_ini(self, profile):
        AppSettings.set_selected_language(ENGLISH)
        english = _write_base(ENGLISH, "Hello")
        _write_base(GERMAN, "Hallo")
        assert AppSettings.get_global_source_base_ini() == english

    def test_a_language_with_its_own_base_ini_reads_it(self, profile):
        _write_base(ENGLISH, "Hello")
        german = _write_base(GERMAN, "Hallo")
        assert AppSettings.get_global_source_base_ini() == german

    def test_a_language_not_fetched_yet_reads_english(self, profile):
        """As at startup: the table still loads, until a language switch or
        Map Language File fetches the language's file."""
        english = _write_base(ENGLISH, "Hello")
        assert AppSettings.get_global_source_base_ini() == english

    def test_another_language_can_be_asked_for(self, profile):
        english = _write_base(ENGLISH, "Hello")
        _write_base(GERMAN, "Hallo")
        assert AppSettings.get_global_source_base_ini(ENGLISH) == english


class TestStartup:
    """``AppSettings.sync_global_source_path`` is what ``main()`` runs at
    every start: the code it used to have inline, now shared."""

    def test_a_source_left_on_english_goes_back_to_the_language(self, profile, caplog):
        english = _write_base(ENGLISH, "Hello")
        german = _write_base(GERMAN, "Hallo")
        AppSettings.set_source_path(AppSettings.SOURCE_GLOBAL, str(english))

        with caplog.at_level(logging.INFO):
            AppSettings.sync_global_source_path("at startup")

        assert _global_source() == str(german)
        assert _table_greeting() == "Hallo"
        assert f"Re-synced global source path at startup: {english} → {german}" in [
            r.getMessage() for r in caplog.records]

    def test_a_url_source_is_left_alone(self, profile):
        _write_base(ENGLISH, "Hello")
        _write_base(GERMAN, "Hallo")
        AppSettings.set_source_path(AppSettings.SOURCE_GLOBAL, _URL)
        AppSettings.sync_global_source_path("at startup")
        assert _global_source() == _URL

    def test_a_source_already_right_is_left_as_it_is(self, profile, caplog):
        _write_base(ENGLISH, "Hello")
        german = _write_base(GERMAN, "Hallo")
        AppSettings.set_source_path(AppSettings.SOURCE_GLOBAL, str(german))
        with caplog.at_level(logging.INFO):
            AppSettings.sync_global_source_path("at startup")
        assert _global_source() == str(german)
        assert not [r for r in caplog.records if "Re-synced" in r.getMessage()]

    def test_main_runs_it_and_keeps_no_rule_of_its_own(self):
        """``main()`` calls the shared method and sets the ``global`` source
        nowhere else, so its rule cannot drift from the other three."""
        tree = ast.parse(_MAIN.read_text(encoding="utf-8"))
        main = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == "main")
        calls = [node for node in ast.walk(main) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute)]
        assert [ast.literal_eval(c.args[0]) for c in calls
                if c.func.attr == "sync_global_source_path"] == ["at startup"]
        assert not [c for c in calls if c.func.attr == "set_source_path"
                    and ast.unparse(c.args[0]) == "AppSettings.SOURCE_GLOBAL"]


def _finish_extraction() -> MagicMock:
    """The real success slot of a global.ini extraction, on a stub window."""
    worker = MagicMock()
    me = MagicMock(_p4k_worker=worker, _p4k_progress=None,
                   _after_unfinished_p4k_extraction=None, _close_committed=False)
    MainWindow._on_p4k_extract_finished(me, True, worker)
    return me


class TestASuccessfulExtraction:
    def test_the_language_is_kept(self, profile):
        """The reported case: after a game patch startup extracts global.ini,
        and the table and the next Apply used to turn English."""
        _write_base(ENGLISH, "Hello")
        german = _write_base(GERMAN, "Hallo")
        _switch_to_german(german)

        me = _finish_extraction()

        assert _global_source() == str(german)
        assert _table_greeting() == "Hallo"
        me._show_loading_progress.assert_called_once()

    def test_english_still_gets_the_file_it_extracted(self, profile):
        AppSettings.set_selected_language(ENGLISH)
        english = _write_base(ENGLISH, "Hello")
        _write_base(GERMAN, "Hallo")
        _finish_extraction()
        assert _global_source() == str(english)
        assert _table_greeting() == "Hello"

    def test_a_language_not_fetched_yet_gets_english(self, profile):
        english = _write_base(ENGLISH, "Hello")
        _finish_extraction()
        assert _global_source() == str(english)
        assert _table_greeting() == "Hello"

    def test_a_url_source_is_still_replaced_by_a_local_file(self, profile):
        """The extraction locks the source to a local file with auto-update
        off, so a remote source never overwrites it: still so, with the
        language's own file."""
        _write_base(ENGLISH, "Hello")
        german = _write_base(GERMAN, "Hallo")
        AppSettings.set_source_path(AppSettings.SOURCE_GLOBAL, _URL)
        _finish_extraction()
        assert _global_source() == str(german)
        assert AppSettings.get_source_auto_update(AppSettings.SOURCE_GLOBAL) is False


def _switch_channel(channel: str) -> MagicMock:
    """The real channel switch, on a stub window whose resync is the real
    one: the Config tab saves the channel, then the window reacts. No
    global.ini extraction is needed, so it reloads at once."""
    AppSettings.set_active_channel(channel)
    me = MagicMock()
    me._sync_canonical_source_paths = MainWindow._sync_canonical_source_paths.__get__(me)
    me._check_p4k_freshness.return_value = False
    MainWindow._on_channel_changed(me, channel)
    return me


class TestAChannelSwitchOrADataFolderChange:
    def test_a_channel_switch_keeps_the_language(self, profile):
        _write_base(ENGLISH, "Hello")
        _switch_to_german(_write_base(GERMAN, "Hallo"))
        AppSettings.set_active_channel("PTU")
        _write_base(ENGLISH, "Hello PTU")
        ptu_german = _write_base(GERMAN, "Hallo PTU")

        me = _switch_channel("PTU")

        assert _global_source() == str(ptu_german)
        assert _table_greeting() == "Hallo PTU"
        me._reload_after_channel_switch.assert_called_once_with("PTU")

    def test_a_channel_without_the_language_gets_its_english_base_ini(self, profile):
        _write_base(ENGLISH, "Hello")
        _switch_to_german(_write_base(GERMAN, "Hallo"))
        AppSettings.set_active_channel("PTU")
        ptu_english = _write_base(ENGLISH, "Hello PTU")

        _switch_channel("PTU")

        assert _global_source() == str(ptu_english)
        assert _table_greeting() == "Hello PTU"

    def test_a_data_folder_change_keeps_the_language(self, profile):
        _write_base(ENGLISH, "Hello")
        _switch_to_german(_write_base(GERMAN, "Hallo"))
        AppSettings.set_user_data_dir(profile / "other data")
        _write_base(ENGLISH, "Hello there")
        other_german = _write_base(GERMAN, "Hallo dort")
        me = MagicMock()
        me._sync_canonical_source_paths = MainWindow._sync_canonical_source_paths.__get__(me)
        me._check_p4k_freshness.return_value = False

        MainWindow._on_data_dir_changed(me, str(profile / "other data"))

        assert _global_source() == str(other_german)
        assert _table_greeting() == "Hallo dort"

    def test_user_ini_still_follows_the_channel(self, profile):
        _write_base(ENGLISH, "Hello")
        _switch_to_german(_write_base(GERMAN, "Hallo"))
        AppSettings.set_active_channel("PTU")
        _write_base(ENGLISH, "Hello PTU")
        _switch_channel("PTU")
        assert AppSettings.get_source_path(AppSettings.SOURCE_USER) == str(
            AppSettings.get_user_ini_path())
        assert "PTU" in Path(AppSettings.get_user_ini_path()).parts

    def test_url_sources_are_left_alone(self, profile):
        _write_base(ENGLISH, "Hello")
        _write_base(GERMAN, "Hallo")
        user_url = "https://example.invalid/user.ini"
        AppSettings.set_source_path(AppSettings.SOURCE_GLOBAL, _URL)
        AppSettings.set_source_path(AppSettings.SOURCE_USER, user_url)
        _switch_channel("LIVE")
        assert _global_source() == _URL
        assert AppSettings.get_source_path(AppSettings.SOURCE_USER) == user_url
