"""Apply to Game when Windows refuses the game's global.ini (Errno 13).

A player saw "Error merging INI files: [Errno 13] Permission denied" with the
game under Program Files. The same error comes from a running game holding
the file, a read-only global.ini, a folder normal users cannot write to, or
Controlled folder access. A read-only file is now cleared before the write
(and backups no longer inherit the flag), and anything else gets a box that
says what to try, naming a running game first.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.gui.main_window import MainWindow
from src.utils.read_only import clear_read_only

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
KEY = "ui_Greeting"
NEW_KEYS = ("refused_title", "refused_game_running_body", "refused_body")


def _is_read_only(path: Path) -> bool:
    return not (os.stat(path).st_mode & stat.S_IWRITE)


def _make_read_only(path: Path) -> None:
    os.chmod(path, stat.S_IREAD)


class TestClearReadOnly:
    def test_clears_the_flag(self, tmp_path):
        f = tmp_path / "global.ini"
        f.write_text("a=b\n", encoding="utf-8")
        _make_read_only(f)
        assert clear_read_only(f) is True
        assert not _is_read_only(f)

    def test_writable_file_is_left_alone(self, tmp_path):
        f = tmp_path / "global.ini"
        f.write_text("a=b\n", encoding="utf-8")
        assert clear_read_only(f) is False
        assert not _is_read_only(f)

    def test_missing_file(self, tmp_path):
        assert clear_read_only(tmp_path / "nope.ini") is False

    def test_a_refused_change_is_logged_not_raised(self, tmp_path, monkeypatch, caplog):
        import src.utils.read_only as read_only

        f = tmp_path / "global.ini"
        f.write_text("a=b\n", encoding="utf-8")
        _make_read_only(f)

        def refuse(path, mode):
            raise PermissionError(13, "Permission denied", str(path))

        monkeypatch.setattr(read_only.os, "chmod", refuse)
        assert clear_read_only(f) is False
        assert "Could not clear the read-only flag" in caplog.text
        monkeypatch.undo()
        os.chmod(f, stat.S_IREAD | stat.S_IWRITE)


class TestMergeKeepsPermissionError:
    def test_permission_error_is_not_wrapped(self, tmp_path, monkeypatch):
        import builtins

        import src.merger.ini_merger as ini_merger

        base = tmp_path / "base.ini"
        base.write_text(f"{KEY}=Hello\n", encoding="utf-8")
        target = tmp_path / "game" / "global.ini"
        real_open = builtins.open

        def refusing_open(path, mode="r", *args, **kwargs):
            if Path(path) == target and "w" in mode:
                raise PermissionError(13, "Permission denied", str(path))
            return real_open(path, mode, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", refusing_open)
        with pytest.raises(PermissionError) as info:
            ini_merger.merge_ini_files(base, {}, target)
        assert info.value.filename == str(target)

    def test_other_errors_are_still_wrapped(self, tmp_path, monkeypatch):
        import src.merger.ini_merger as ini_merger

        base = tmp_path / "base.ini"
        base.write_text(f"{KEY}=Hello\n", encoding="utf-8")

        def broken(path):
            raise ValueError("boom")

        monkeypatch.setattr(ini_merger, "read_ini_text", broken)
        with pytest.raises(IOError, match="Error merging INI files: boom"):
            ini_merger.merge_ini_files(base, {}, tmp_path / "out.ini")


class _Boxes:
    def __init__(self):
        self.shown = []

    def make(self):
        shown = self.shown

        class FakeMessageBox:
            class StandardButton:
                Yes = 1
                No = 2

            @staticmethod
            def information(parent, title, text, *a, **k):
                shown.append(("information", title, text))

            @staticmethod
            def warning(parent, title, text, *a, **k):
                shown.append(("warning", title, text))

            @staticmethod
            def critical(parent, title, text, *a, **k):
                shown.append(("critical", title, text))

        return FakeMessageBox


@pytest.fixture
def apply_env(tmp_path, monkeypatch):
    """apply_to_game on a MagicMock self, as test_enhancement_count_report
    drives it, with the game file and backups under tmp_path."""
    import src.utils.user_cfg as user_cfg
    import src.utils.user_ini_manager as user_ini_manager
    from src.gui import main_window
    from src.utils.i18n import set_language
    from src.utils.settings import AppSettings

    set_language("english")
    base = tmp_path / "base.ini"
    base.write_text(f"{KEY}=Hello\n", encoding="utf-8")
    game = tmp_path / "game" / "global.ini"
    backups = tmp_path / "backups"
    backups.mkdir()
    boxes = _Boxes()

    monkeypatch.setattr(main_window, "QMessageBox", boxes.make())
    monkeypatch.setattr(main_window, "load_sources_from_settings", lambda: (
        {AppSettings.SOURCE_GLOBAL: {KEY: "Hello"}},
        [AppSettings.SOURCE_GLOBAL, AppSettings.SOURCE_USER],
        {},
    ))
    for name, value in {
        "get_game_install_path": lambda: str(tmp_path),
        "get_user_ini_path": lambda: tmp_path / "user.ini",
        "get_global_ini_path": lambda: game,
        "get_backups_dir": lambda: backups,
        "get_source_path": lambda name: str(base),
        "is_source_enabled": lambda name: True,
        "get_language_languages_ini_path": lambda: None,
        "get_selected_language": lambda: "english",
    }.items():
        monkeypatch.setattr(AppSettings, name, staticmethod(value))
    monkeypatch.setattr(user_ini_manager, "save_user_ini", lambda entries, path: 0)
    monkeypatch.setattr(user_cfg, "ensure_user_cfg_language", lambda: None)

    window = MagicMock()
    window.entries = [object()]
    window._build_apply_merged_dict.return_value = {KEY: "Hi"}
    window._validate_applied_file.return_value = None
    window._show_game_folder_refused.side_effect = (
        lambda path: MainWindow._show_game_folder_refused(window, path))
    return window, game, backups, boxes


def _refuse_writes_to(monkeypatch, target: Path):
    import builtins

    real_open = builtins.open

    def refusing_open(path, mode="r", *args, **kwargs):
        if Path(path) == target and "w" in mode:
            raise PermissionError(13, "Permission denied", str(path))
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", refusing_open)


class TestApplyToGame:
    def test_read_only_global_ini_is_cleared_and_written(self, apply_env):
        window, game, backups, boxes = apply_env
        game.parent.mkdir()
        game.write_text(f"{KEY}=Old\n", encoding="utf-8")
        _make_read_only(game)

        assert MainWindow.apply_to_game(window) is True

        assert not _is_read_only(game)
        assert f"{KEY}=Hi" in game.read_text(encoding="utf-8-sig")
        [backup] = list(backups.glob("global.ini.bak_*"))
        assert not _is_read_only(backup), "copy2 carried the flag into the backup"
        assert [kind for kind, *_ in boxes.shown] == ["information"]

    def test_a_read_only_old_backup_still_rotates(self, apply_env):
        window, game, backups, boxes = apply_env
        game.parent.mkdir()
        game.write_text(f"{KEY}=Old\n", encoding="utf-8")
        old = []
        for i in range(5):
            b = backups / f"global.ini.bak_2026010{i}_000000"
            b.write_text("x", encoding="utf-8")
            os.utime(b, (1000 + i, 1000 + i))
            _make_read_only(b)
            old.append(b)

        assert MainWindow.apply_to_game(window) is True
        assert not old[0].exists()
        assert len(list(backups.glob("global.ini.bak_*"))) == 5

    @pytest.mark.parametrize("running", [True, False])
    def test_refused_write_explains_what_to_try(self, apply_env, monkeypatch, running):
        import src.utils.shader_cache as shader_cache

        window, game, backups, boxes = apply_env
        monkeypatch.setattr(shader_cache, "is_star_citizen_running", lambda: running)
        _refuse_writes_to(monkeypatch, game)

        assert MainWindow.apply_to_game(window) is False

        window._mark_apply_dirty.assert_called()
        window._mark_applied.assert_not_called()
        [(kind, title, text)] = boxes.shown
        assert kind == "critical"
        assert title == "Windows Blocked the Game Folder"
        assert str(game) in text
        assert "Errno" not in text
        if running:
            assert "Star Citizen is running" in text
            assert "Run as administrator" not in text
        else:
            assert "Controlled folder access" in text
            assert "Run as administrator" in text

    def test_other_failures_keep_the_old_box(self, apply_env, monkeypatch):
        import src.merger.ini_merger as ini_merger

        window, game, backups, boxes = apply_env

        def fail(*a, **k):
            raise IOError("Error merging INI files: boom")

        monkeypatch.setattr(ini_merger, "merge_ini_files", fail)
        assert MainWindow.apply_to_game(window) is False
        [(kind, title, text)] = boxes.shown
        assert kind == "critical"
        assert "Failed to apply to game" in text and "boom" in text


class TestStrings:
    @pytest.mark.parametrize(
        "ui_json", sorted((REPO / "languages").glob("*/ui.json")), ids=lambda p: p.parent.name)
    def test_every_language_has_the_texts(self, ui_json):
        apply = json.loads(ui_json.read_text(encoding="utf-8"))["apply"]
        english = ui_json.parent.name == "english"
        for key in NEW_KEYS:
            leaf = apply[key]
            text = leaf["ht"] if english else leaf["at"]
            assert text, (ui_json.parent.name, key)
            if not english:
                assert leaf["ht"] == ""
            if key != "refused_title":
                assert "\n{path}\n" in text, (ui_json.parent.name, key)
                text.format(path="C:\\x")
