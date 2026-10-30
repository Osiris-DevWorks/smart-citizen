"""A reload keeps the edits user.ini does not have, and only those (#531).

Every reload builds the table from disk, so MainWindow puts the user's unsaved
edits back on top (_snapshot_pending_user_edits / _restore_pending_user_edits).
It used to put back every non-empty value in the table. An override the user
had reset came back from the old user.ini (and reached the game at the next
Apply), and Restore user.ini and Import INI lost to the table's old values. An
edit is now a value that differs from what user.ini held at the last load or
save, a cleared one included. A reload that reads another user.ini (a channel
switch) still carries every override, which is intended. A reload that reads
no override from a user.ini that held some is not trusted, so a file another
program held for a moment costs nothing. Reset user.ini records user.ini as
empty, so the reload after it is trusted. user.ini is written in one step, so a
failed save keeps the old file. A cleared override reads as a load would show
the row: Enhanced, New or Unmodified (status_without_override). Import
Settings with Restart Later puts the imported user.ini into the table, which
kept its old overrides and saved them over the import at the next close or
Apply, and an import that switches channel offers only Restart Now.

A real MainWindow (tests/gui_window.py) on a tmp data folder, reloaded with the
real perform_merge_and_reload or the async loader's _on_loading_finished.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QDialog

import src.utils.atomic_io as atomic_io
import src.utils.ini_io as ini_io
from src.gui import enhancements_tab, import_dialog, main_window
from src.gui.string_table_model import COL_CUSTOM
from src.parser.ini_parser import load_source_files, load_sources_from_settings, parse_ini_file
from src.utils import settings_profile, user_ini_manager
from src.utils.i18n import tr
from src.utils.settings import AppSettings
from src.utils.user_ini_manager import backup_user_ini
from tests.gui_window import build_main_window, retire_main_window

pytestmark = [pytest.mark.unit, pytest.mark.regression]

BASE = "k_one=Stock one\nk_two=Stock two\n"


class _Box:
    """QMessageBox stand-in: every question answered Yes, nothing shown."""

    class StandardButton:
        Yes, No = 1, 2

    @staticmethod
    def question(*_args, **_kwargs):
        return _Box.StandardButton.Yes

    warning = question
    information = question
    critical = question


def _seed(user_text: str):
    """This channel's base.ini and user.ini, with the sources pointed at them."""
    base = AppSettings.get_base_ini_path()
    base.parent.mkdir(parents=True, exist_ok=True)
    base.write_text(BASE, encoding="utf-8")
    AppSettings.set_source_path(AppSettings.SOURCE_GLOBAL, str(base))
    user_ini = AppSettings.get_user_ini_path()
    user_ini.parent.mkdir(parents=True, exist_ok=True)
    user_ini.write_text(user_text, encoding="utf-8")
    AppSettings.set_source_path(AppSettings.SOURCE_USER, str(user_ini))
    return user_ini


def _seed_enhancements(text: str) -> None:
    """A generated Ships INI, which the loader merges as the enhancements source."""
    enh_dir = AppSettings.get_enhancements_dir()
    enh_dir.mkdir(parents=True, exist_ok=True)
    (enh_dir / AppSettings.ENHANCEMENTS_FILES["ship_descs"]).write_text(text, encoding="utf-8")


def _entry(window, key):
    return next(e for e in window.entries if e.key == key)


def _row(window, key) -> int:
    return next(r for r in range(window._model.rowCount())
                if window.entries[window._entry_index_for_row(r)].key == key)


def _edit(window, key, text):
    """Type *text* into the key's Custom cell, as the table's editor does."""
    index = window._model.index(_row(window, key), COL_CUSTOM)
    assert window._model.setData(index, text, Qt.ItemDataRole.EditRole) is True


def _async_reload(window):
    """What the loader worker hands _on_loading_finished, loaded here."""
    sources, hierarchy, categories = load_sources_from_settings()
    entries = load_source_files(sources, hierarchy, enhancements_key_categories=categories)
    window._on_loading_finished(entries, dict(sources.get(AppSettings.SOURCE_GLOBAL, {})), None)


def _reload(window, kind: str):
    if kind == "sync":
        window.perform_merge_and_reload()
    else:
        _async_reload(window)


def _swap_fails(monkeypatch):
    """Make every one-step write fail at its swap, as a full drive or a held
    file would, so the old file is all that is left."""
    def refuse(_source, target):
        raise OSError(5, "the swap failed", str(target))

    monkeypatch.setattr(atomic_io, "_replace_retrying", refuse)


def _plain_user_ini(tmp_path, text: str = "k_one=Mine\n") -> Path:
    """A user.ini in a channel folder of its own, with no window."""
    user_ini = tmp_path / "LIVE" / "user.ini"
    user_ini.parent.mkdir()
    user_ini.write_text(text, encoding="utf-8")
    return user_ini


def _pick_oldest_snapshot(monkeypatch):
    """Restore user.ini's picker, answered with the oldest snapshot."""
    class Picker:
        @staticmethod
        def getItem(_parent, _title, _label, items, *_args):
            return items[-1], True

    monkeypatch.setattr(main_window, "QInputDialog", Picker)


def _empty_editor_dock(window, key):
    """Show the key's row in the String Editor dock and delete its text."""
    window._ensure_editor_dock()
    window._load_editor_dock_from_row(_row(window, key))
    assert window.editor_dock_text.toPlainText() == _entry(window, key).custom_value
    window.editor_dock_text.setPlainText("")


def _reload_unread(window, monkeypatch, user_ini, reload: str, failure: str):
    """A reload that reads nothing from user.ini: another program holds it
    (its read raises), or it is moved away for the reload and back after."""
    with monkeypatch.context() as patch:
        if failure == "unreadable":
            real = ini_io.read_bytes_retrying

            def held(path):
                if Path(path).name == user_ini.name:
                    raise PermissionError(32, "another program holds it", str(path))
                return real(path)

            patch.setattr(ini_io, "read_bytes_retrying", held)
        else:
            away = user_ini.with_name("user.ini.away")
            user_ini.rename(away)
        try:
            _reload(window, reload)
        finally:
            if failure == "missing":
                away.rename(user_ini)


def _import_settings(window, tmp_path, monkeypatch, overrides: dict, click, settings=None):
    """Run the real Import Settings on a backup of *overrides* and *settings*.
    Its done box clicks the button labelled *click* (None: shut with Esc or
    its X), and a restart is only recorded. Returns the buttons the box
    offered and the restarts."""
    backup = tmp_path / "settings.zip"
    settings_profile.write_profile_zip(
        backup, settings=settings or {}, overrides=overrides,
        app_version="2.5.0", source_mode=settings_profile.SOURCE_MODE_PORTABLE)
    monkeypatch.setattr(main_window.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *_a, **_k: (str(backup), "")))
    offered, restarts = [], []

    class Box(_Box):
        """_Box, plus the boxes a flow builds itself (the done box, the
        close prompt): their buttons are recorded and *click* is clicked."""

        class StandardButton(_Box.StandardButton):
            Cancel = 3

        class Icon:
            Information = Warning = 1

        class ButtonRole:
            AcceptRole = RejectRole = DestructiveRole = 1

        def __init__(self, _parent=None):
            self.buttons = {}

        def addButton(self, text, _role=None):
            offered.append(text)
            return self.buttons.setdefault(text, object())

        def clickedButton(self):
            return self.buttons.get(click)

        def __getattr__(self, _name):    # setText, exec and the rest
            return lambda *_a, **_k: None

    monkeypatch.setattr(main_window, "QMessageBox", Box)
    monkeypatch.setattr(window, "_relaunch_app", lambda: restarts.append(True))
    window._handle_import_settings()
    return offered, restarts


@pytest.fixture
def window(qapp, tmp_path, monkeypatch, slot_errors):
    """A real MainWindow, its boxes answered. A slot that raises (an edit's
    dataChanged, a signal the flow sends) fails the test (slot_errors)."""
    win = build_main_window(tmp_path, monkeypatch, AppSettings.UI_MODE_ADVANCED)
    monkeypatch.setattr(main_window, "QMessageBox", _Box)
    # The flows below start the async loader. Run its work inline instead.
    monkeypatch.setattr(win, "_show_loading_progress", lambda *_a, **_k: _async_reload(win))
    try:
        yield win
        assert slot_errors == []
    finally:
        retire_main_window(win)


@pytest.fixture
def game(tmp_path, monkeypatch):
    """A game folder for apply_to_game to write into."""
    folder = tmp_path / "game"
    target = folder / "global.ini"
    monkeypatch.setattr(AppSettings, "get_game_install_path", staticmethod(lambda: str(folder)))
    monkeypatch.setattr(AppSettings, "get_global_ini_path",
                        staticmethod(lambda language=None: target))
    return target


class TestAClearedOverrideStaysCleared:
    @pytest.mark.parametrize("reload", ["sync", "async"])
    def test_a_reset_survives_a_reload(self, window, reload):
        """Reset to Original lives in memory until Apply saves it. A reload
        (a finished Generate, the category Apply button) used to bring the
        override straight back from the old user.ini."""
        _seed("k_one=Mine\n")
        window.perform_merge_and_reload()
        assert _entry(window, "k_one").custom_value == "Mine"

        window.reset_to_original(_row(window, "k_one"))
        _reload(window, reload)

        entry = _entry(window, "k_one")
        assert entry.custom_value == ""
        assert entry.status == "Unmodified"

    @pytest.mark.parametrize("reload", ["sync", "async"])
    def test_an_emptied_cell_survives_a_reload(self, window, reload):
        _seed("k_one=Mine\n")
        window.perform_merge_and_reload()
        _edit(window, "k_one", "")
        assert _entry(window, "k_one").status == "Unmodified"

        _reload(window, reload)

        entry = _entry(window, "k_one")
        assert entry.custom_value == ""
        assert entry.status == "Unmodified"

    def test_the_next_apply_writes_the_reset(self, window, game):
        """What the bug cost: the override came back, and Apply then saved
        it to user.ini and wrote it into the game."""
        user_ini = _seed("k_one=Mine\n")
        window.perform_merge_and_reload()
        window.reset_to_original(_row(window, "k_one"))
        window.perform_merge_and_reload()

        assert window.apply_to_game() is True

        assert "k_one" not in user_ini.read_text(encoding="utf-8")
        assert "k_one=Stock one" in game.read_text(encoding="utf-8-sig")


class TestAClearedRowReadsAsALoadWould:
    """A cleared override labelled the row whatever its value came from:
    Unmodified after Reset to Original, a removed favourite or a cleared sort
    order, Modified after an emptied cell or editor dock. It now reads as a
    load would show it (status_without_override)."""

    @pytest.mark.parametrize("reload", ["none", "sync", "async"])
    def test_a_reset_enhanced_row_reads_enhanced(self, window, reload):
        _seed("k_one=Mine\n")
        _seed_enhancements("k_one=Enhanced one\n")
        window.perform_merge_and_reload()
        assert _entry(window, "k_one").status == "Modified"

        window.reset_to_original(_row(window, "k_one"))
        if reload != "none":
            _reload(window, reload)

        entry = _entry(window, "k_one")
        assert entry.custom_value == ""
        assert entry.status == "Enhanced"

    @pytest.mark.parametrize("reload", ["none", "sync", "async"])
    @pytest.mark.parametrize("where", ["cell", "editor dock"])
    def test_an_emptied_enhanced_value_reads_enhanced(self, window, where, reload):
        _seed("k_one=Mine\n")
        _seed_enhancements("k_one=Enhanced one\n")
        window.perform_merge_and_reload()

        if where == "cell":
            _edit(window, "k_one", "")
        else:
            _empty_editor_dock(window, "k_one")
        if reload != "none":
            _reload(window, reload)

        entry = _entry(window, "k_one")
        assert entry.custom_value == ""
        assert entry.status == "Enhanced"

    def test_a_cleared_sort_order_on_an_enhanced_name_reads_enhanced(self, qapp):
        """Clearing a ship's sort order collapses its override to "" when
        nothing else was changed (set_order), so the row is cleared too."""
        from src.gui.string_table_model import COL_ORDER, StringTableModel
        from src.models.string_model import StringEntry

        entry = StringEntry(key="vehicle_NameANVL_Carrack",
                            source_file=AppSettings.SOURCE_ENHANCEMENTS,
                            category="Ships", original_value="Carrack [S3]",
                            custom_value="05-Carrack [S3]", status="Modified")
        model = StringTableModel()
        model.set_data_source([entry], {"vehicle_NameANVL_Carrack": "Carrack"}, "*")

        assert model.setData(model.index(0, COL_ORDER), "", Qt.ItemDataRole.EditRole) is True

        assert entry.custom_value == ""
        assert entry.status == "Enhanced"

    @pytest.mark.parametrize("reload", ["none", "sync"])
    def test_a_reset_discovered_key_reads_new_and_apply_leaves_it_out(self, window, reload):
        """A key only the enhancements have is New, and with Include
        discovered items off Apply leaves New keys out. Read as Unmodified,
        a reset one went into the merge."""
        assert AppSettings.get_include_new_lines() is False
        _seed("k_new=Mine new\n")
        _seed_enhancements("k_new=Discovered\n")
        window.perform_merge_and_reload()

        window.reset_to_original(_row(window, "k_new"))
        if reload != "none":
            _reload(window, reload)

        assert _entry(window, "k_new").status == "New"
        assert "k_new" in window._apply_merge_inputs().discarded_new_keys


class TestUnsavedEditsStillSurvive:
    @pytest.mark.parametrize("reload", ["sync", "async"])
    def test_an_edit_survives_two_reloads(self, window, reload):
        """The reload's whole point, kept: an edit not yet applied stays,
        and still counts as unsaved at the reload after that."""
        _seed("")
        window.perform_merge_and_reload()
        _edit(window, "k_two", "Edited")

        for _ in range(2):
            _reload(window, reload)

        entry = _entry(window, "k_two")
        assert entry.custom_value == "Edited"
        assert entry.status == "Modified"


class TestAnUnreadUserIniIsNotTrusted:
    """A reload that reads no override from the user.ini that held some last
    time keeps the table's overrides. Trusting it dropped every saved one from
    the table, and from user.ini at the next Apply or close."""

    @pytest.mark.parametrize("failure", ["unreadable", "missing"])
    @pytest.mark.parametrize("reload", ["sync", "async"])
    def test_the_table_keeps_its_overrides(self, window, game, monkeypatch, caplog,
                                           reload, failure):
        user_ini = _seed("k_one=Mine\n")
        window.perform_merge_and_reload()
        _edit(window, "k_two", "Edited")

        with caplog.at_level(logging.WARNING, logger=main_window.logger.name):
            _reload_unread(window, monkeypatch, user_ini, reload, failure)

        assert _entry(window, "k_one").custom_value == "Mine"
        assert _entry(window, "k_two").custom_value == "Edited"
        assert any("read no overrides" in r.getMessage() for r in caplog.records)
        assert window.apply_to_game() is True
        assert sorted(user_ini.read_text(encoding="utf-8").splitlines()) == [
            "k_one=Mine", "k_two=Edited"]

    @pytest.mark.parametrize("failure", ["unreadable", "missing"])
    @pytest.mark.parametrize("reload", ["sync", "async"])
    def test_it_keeps_the_record_too(self, window, monkeypatch, reload, failure):
        """What user.ini held stays recorded, so a Reset to Original after
        that reload is still a change at the next one that reads user.ini."""
        user_ini = _seed("k_one=Mine\n")
        window.perform_merge_and_reload()
        _reload_unread(window, monkeypatch, user_ini, reload, failure)
        assert window._saved_overrides == {"k_one": "Mine"}

        window.reset_to_original(_row(window, "k_one"))
        _reload(window, reload)

        assert _entry(window, "k_one").custom_value == ""


class TestAFailedSaveKeepsUserIni:
    """user.ini is written in one step. Opened for writing, it was emptied
    before the write, so a write that failed part-way (a full drive, a share
    that dropped) left an empty user.ini for the next reload or start."""

    def test_save_user_ini(self, tmp_path, monkeypatch):
        from src.models.string_model import StringEntry

        user_ini = _plain_user_ini(tmp_path)
        before = user_ini.read_bytes()
        entry = StringEntry(key="k_two", source_file=AppSettings.SOURCE_GLOBAL,
                            category="Other", original_value="Stock two",
                            custom_value="Edited", status="Modified")
        _swap_fails(monkeypatch)

        with pytest.raises(OSError):
            user_ini_manager.save_user_ini([entry], user_ini)

        assert user_ini.read_bytes() == before

    def test_save_user_ini_dict(self, tmp_path, monkeypatch):
        user_ini = _plain_user_ini(tmp_path)
        before = user_ini.read_bytes()
        _swap_fails(monkeypatch)

        with pytest.raises(OSError):
            user_ini_manager.save_user_ini_dict({"k_two": "Imported"}, user_ini)

        assert user_ini.read_bytes() == before

    def test_restore_user_ini_backup(self, tmp_path, monkeypatch):
        user_ini = _plain_user_ini(tmp_path)
        before = user_ini.read_bytes()
        snapshot = tmp_path / "snapshot.ini"
        snapshot.write_text("k_one=Old\n", encoding="utf-8")
        _swap_fails(monkeypatch)

        with pytest.raises(OSError):
            user_ini_manager.restore_user_ini_backup(snapshot, user_ini)

        assert user_ini.read_bytes() == before

    def test_import_settings(self, window, tmp_path, monkeypatch):
        """Import Settings writes each channel's user.ini from the backup."""
        user_ini = _seed("k_one=Mine\n")
        before = user_ini.read_bytes()
        backup = tmp_path / "settings.zip"
        settings_profile.write_profile_zip(
            backup, settings={},
            overrides={AppSettings.get_active_channel(): "k_one=Imported\n"},
            app_version="2.5.0", source_mode=settings_profile.SOURCE_MODE_PORTABLE)
        monkeypatch.setattr(main_window.QFileDialog, "getOpenFileName",
                            staticmethod(lambda *_a, **_k: (str(backup), "")))
        _swap_fails(monkeypatch)
        boxes = []
        monkeypatch.setattr(_Box, "critical",
                            staticmethod(lambda *a, **_k: boxes.append(a[1])))
        monkeypatch.setattr(main_window.logger, "exception", lambda *_a, **_k: None)

        window._handle_import_settings()

        assert user_ini.read_bytes() == before
        assert len(boxes) == 1

    def test_the_favourite_prefix_migration(self, window, monkeypatch):
        user_ini = _seed("k_one=*Mine\n")
        before = user_ini.read_bytes()
        tab = window.enhancements_tab
        assert tab._loaded_prefix == "*"
        tab.favorite_prefix_combo.setCurrentIndex(tab.favorite_prefix_combo.findData("+"))
        _swap_fails(monkeypatch)
        boxes = []
        monkeypatch.setattr(enhancements_tab.QMessageBox, "critical",
                            staticmethod(lambda *a, **_k: boxes.append(a[1])))
        monkeypatch.setattr(enhancements_tab.logger, "exception", lambda *_a, **_k: None)

        tab._apply_favorite_prefix()

        assert user_ini.read_bytes() == before
        assert len(boxes) == 1
        assert AppSettings.get_favorite_prefix() == "*"

    def test_the_favourite_prefix_migration_sweeps_old_temps(self, window):
        """It writes through write_user_ini_text, as every user.ini write
        does, so it sweeps a temp a killed write left beside user.ini too."""
        user_ini = _seed("k_one=*Mine\n")
        left = user_ini.with_name(f"{atomic_io.TEMP_PREFIX}0123abcd{atomic_io.TEMP_SUFFIX}")
        left.write_text("k_one=*Mi", encoding="utf-8")
        then = time.time() - atomic_io.STALE_TEMP_AGE_S - 60
        os.utime(left, (then, then))
        tab = window.enhancements_tab
        tab.favorite_prefix_combo.setCurrentIndex(tab.favorite_prefix_combo.findData("+"))

        tab._apply_favorite_prefix()

        assert parse_ini_file(user_ini, strip_values=False) == {"k_one": "+Mine"}
        assert not left.exists()

    @pytest.mark.parametrize("writer", ["write_user_ini_text", "restore_user_ini_backup"])
    def test_the_writes_sweep_old_temps(self, tmp_path, writer):
        """A write killed before its swap leaves its temp beside user.ini, and
        no run sweeps the channel folder, so the user.ini writes do."""
        user_ini = _plain_user_ini(tmp_path)
        left = user_ini.with_name(f"{atomic_io.TEMP_PREFIX}0123abcd{atomic_io.TEMP_SUFFIX}")
        left.write_text("k_one=Mi", encoding="utf-8")
        then = time.time() - atomic_io.STALE_TEMP_AGE_S - 60
        os.utime(left, (then, then))

        if writer == "write_user_ini_text":
            user_ini_manager.write_user_ini_text(user_ini, "k_one=Edited\n")
        else:
            snapshot = tmp_path / "snapshot.ini"
            snapshot.write_text("k_one=Old\n", encoding="utf-8")
            user_ini_manager.restore_user_ini_backup(snapshot, user_ini)

        assert not left.exists()


class TestAFileWrittenOutsideTheTableWins:
    @pytest.mark.parametrize("reset_first", [False, True])
    def test_restore_user_ini_restores(self, window, monkeypatch, reset_first):
        """Restore user.ini writes the snapshot and reloads. The table's own
        value for the key used to win, so nothing it already had changed, and
        then a Reset to Original of that key not yet applied."""
        user_ini = _seed("k_one=Old\n")
        assert backup_user_ini(user_ini) is not None
        user_ini.write_text("k_one=Mine\n", encoding="utf-8")
        _async_reload(window)    # the startup load
        assert _entry(window, "k_one").custom_value == "Mine"
        if reset_first:
            window.reset_to_original(_row(window, "k_one"))

        _pick_oldest_snapshot(monkeypatch)    # "Old"
        window._handle_restore_user_ini()

        assert user_ini.read_text(encoding="utf-8") == "k_one=Old\n"
        assert _entry(window, "k_one").custom_value == "Old"

    def test_restore_user_ini_when_its_reload_fails(self, window, game, monkeypatch):
        """The table takes the whole snapshot, not only its keys: an override
        the user had not changed goes with the file it came from. A reload
        that fails leaves the table as it is (_on_loading_error), which used
        to keep such an override there for the next Apply to save into the
        restored user.ini."""
        user_ini = _seed("k_one=Old\n")
        assert backup_user_ini(user_ini) is not None
        user_ini.write_text("k_one=Mine\nk_two=Saved\n", encoding="utf-8")
        _async_reload(window)    # the startup load
        monkeypatch.setattr(window, "_show_loading_progress", lambda *_a, **_k: None)

        _pick_oldest_snapshot(monkeypatch)    # "Old"
        window._handle_restore_user_ini()

        assert _entry(window, "k_one").custom_value == "Old"
        assert _entry(window, "k_two").custom_value == ""
        assert window.apply_to_game() is True
        assert parse_ini_file(user_ini, strip_values=False) == {"k_one": "Old"}

    @pytest.mark.parametrize("reset_first", [False, True])
    def test_import_ini_takes_the_imported_value(self, window, tmp_path, monkeypatch,
                                                 reset_first):
        """Import INI writes the merged user.ini and reloads. A conflict
        resolved to the imported value used to lose to the table's old one,
        and then to a Reset to Original of that key not yet applied."""
        _seed("k_one=Mine\n")
        _async_reload(window)    # the startup load
        if reset_first:
            window.reset_to_original(_row(window, "k_one"))
        imported = tmp_path / "shared.ini"
        imported.write_text("k_one=Imported\n", encoding="utf-8")

        class Resolve:
            def __init__(self, conflicts, *_args):
                assert set(conflicts) == {"k_one"}

            def exec(self):
                return QDialog.DialogCode.Accepted

            def get_resolutions(self):
                return {"k_one": "Imported"}

        monkeypatch.setattr(window, "_get_import_source", lambda: str(imported))
        monkeypatch.setattr("src.gui.import_dialog.ImportConflictDialog", Resolve)
        window._handle_import_ini()

        assert _entry(window, "k_one").custom_value == "Imported"

    @pytest.mark.parametrize("change", ["edit", "reset"])
    def test_import_ini_keep_current_leaves_the_tables_change(self, window, tmp_path,
                                                              monkeypatch, change):
        """A conflict kept as it is (Keep Current, the dialog's default)
        leaves user.ini's value, so the import changed nothing there and the
        table's own change of that key, not yet applied, stays."""
        user_ini = _seed("k_one=Mine\n")
        _async_reload(window)    # the startup load
        if change == "edit":
            _edit(window, "k_one", "Edited")
        else:
            window.reset_to_original(_row(window, "k_one"))
        kept = _entry(window, "k_one").custom_value
        imported = tmp_path / "shared.ini"
        imported.write_text("k_one=Imported\n", encoding="utf-8")
        monkeypatch.setattr(window, "_get_import_source", lambda: str(imported))
        monkeypatch.setattr(import_dialog.ImportConflictDialog, "exec",
                            lambda _dialog: QDialog.DialogCode.Accepted)

        window._handle_import_ini()

        assert user_ini.read_text(encoding="utf-8") == "k_one=Mine\n"
        assert _entry(window, "k_one").custom_value == kept


class TestAResetUserIniIsRecorded:
    """Reset user.ini records user.ini as empty, by the user's choice. With the
    old file still recorded, the reload after the reset read as one that could
    not read user.ini, and a later Restore user.ini, or the backup renamed back,
    came back blank."""

    def test_a_restore_after_it_restores(self, window, monkeypatch, caplog):
        """With nothing saved before it: the reset's own snapshot is the one
        Restore user.ini lists (it listed none, found in testing)."""
        user_ini = _seed("k_one=Mine\n")
        _async_reload(window)    # the startup load
        _pick_oldest_snapshot(monkeypatch)

        with caplog.at_level(logging.WARNING, logger=main_window.logger.name):
            window._handle_reset_user_ini()
            assert not user_ini.exists()
            assert _entry(window, "k_one").custom_value == ""
            window._handle_restore_user_ini()

        assert user_ini.read_text(encoding="utf-8") == "k_one=Mine\n"
        assert _entry(window, "k_one").custom_value == "Mine"
        assert not any("read no overrides" in r.getMessage() for r in caplog.records)

    def test_an_empty_user_ini_has_nothing_to_reset(self, window, monkeypatch):
        """An Apply with no override in the table saves an empty user.ini.
        Reset set it aside and reported a reset that Restore user.ini could
        not undo, since an empty file leaves no snapshot (the user's test).
        It now shows the nothing-to-reset box and changes nothing."""
        user_ini = _seed("")
        _async_reload(window)    # the startup load
        boxes = []
        monkeypatch.setattr(_Box, "information",
                            staticmethod(lambda *a, **_k: boxes.append(("information", a[1]))))
        monkeypatch.setattr(_Box, "warning",
                            staticmethod(lambda *a, **_k: boxes.append(("warning", a[1]))))

        window._handle_reset_user_ini()

        assert boxes == [("information", tr("dialogs.nothing_to_reset_title"))]
        assert user_ini.exists()
        assert list(user_ini.parent.glob("user.ini.bak-*")) == []

    def test_a_user_ini_whose_size_cannot_be_read_is_asked_about(self, window, monkeypatch):
        """Only a missing or an empty user.ini has nothing to reset. One whose
        size Windows will not give is not known to be either, so Reset asks
        as usual, with the size unknown, and a reset that then fails reports
        its own error."""
        user_ini = _seed("k_one=Mine\n")
        _async_reload(window)    # the startup load
        boxes = []
        monkeypatch.setattr(_Box, "information",
                            staticmethod(lambda *a, **_k: boxes.append(("information", a[1]))))
        monkeypatch.setattr(_Box, "warning", staticmethod(
            lambda *a, **_k: boxes.append(("warning", a[1], a[2])) or _Box.StandardButton.No))
        real_stat = Path.stat

        def refused(path, *args, **kwargs):
            if path == user_ini:
                raise PermissionError(5, "Access is denied", str(path))
            return real_stat(path, *args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(Path, "stat", refused)
            window._handle_reset_user_ini()

        assert [box[:2] for box in boxes] == [("warning", tr("dialogs.reset_user_ini_title"))]
        assert "unknown size" in boxes[0][2]
        assert user_ini.read_text(encoding="utf-8") == "k_one=Mine\n"

    @pytest.mark.parametrize("reload", ["sync", "async"])
    def test_the_backup_renamed_back_is_read(self, window, caplog, reload):
        """What the Reset dialog says to do to undo it."""
        user_ini = _seed("k_one=Mine\n")
        _async_reload(window)    # the startup load

        with caplog.at_level(logging.WARNING, logger=main_window.logger.name):
            window._handle_reset_user_ini()
            backup, = user_ini.parent.glob("user.ini.bak-*")
            backup.rename(user_ini)
            _reload(window, reload)

        assert _entry(window, "k_one").custom_value == "Mine"
        assert not any("read no overrides" in r.getMessage() for r in caplog.records)


class TestImportSettingsRestartLater:
    """Import Settings writes user.ini, then offers a restart. Restart Later
    kept the table's overrides from before the import, so the next close or
    Apply saved them over the imported user.ini (found in review, in release
    3.0 too). The table now takes the imported file. An import that switches
    channel offers only Restart Now: carrying on, the old channel's table was
    saved into the new channel's user.ini."""

    NOW = "settings_backup.restart_now_btn"
    LATER = "settings_backup.restart_later_btn"

    @pytest.mark.parametrize("reload_fails", [False, True])
    def test_a_close_keeps_the_import(self, window, tmp_path, monkeypatch, reload_fails):
        """Also when the reload that follows fails, which leaves the table as
        it is (_on_loading_error): the table already holds the import then.
        A close while the reload runs saves nothing, since closeEvent skips
        the autosave while the loader runs."""
        user_ini = _seed("k_one=Mine\nk_two=Saved\n")
        _async_reload(window)    # the startup load
        if reload_fails:
            monkeypatch.setattr(window, "_show_loading_progress", lambda *_a, **_k: None)
        _offered, restarts = _import_settings(
            window, tmp_path, monkeypatch,
            {AppSettings.get_active_channel(): "k_one=Imported\n"}, tr(self.LATER))
        assert restarts == []
        assert _entry(window, "k_one").custom_value == "Imported"
        assert _entry(window, "k_two").custom_value == ""
        saves = []
        real_save = user_ini_manager.save_user_ini
        monkeypatch.setattr(user_ini_manager, "save_user_ini",
                            lambda *a, **k: saves.append(True) or real_save(*a, **k))

        window.closeEvent(QCloseEvent())

        assert saves    # the close's autosave ran
        assert user_ini.read_text(encoding="utf-8") == "k_one=Imported\n"

    @pytest.mark.parametrize("edited", [None, "k_one", "k_two"])
    def test_an_apply_keeps_the_import(self, window, game, tmp_path, monkeypatch, edited):
        """The import's values win over an unapplied change to the keys it
        holds (k_one), an override the user had not changed goes with the
        file it came from (k_two), and an unapplied change to a key the
        import does not hold stays."""
        user_ini = _seed("k_one=Mine\nk_two=Saved\n")
        _async_reload(window)    # the startup load
        if edited:
            _edit(window, edited, "Edited")
        _import_settings(window, tmp_path, monkeypatch,
                         {AppSettings.get_active_channel(): "k_one=Imported\n"}, tr(self.LATER))
        expected = {"k_one": "Imported"}
        if edited == "k_two":
            expected["k_two"] = "Edited"
        assert {key: _entry(window, key).custom_value for key in ("k_one", "k_two")} == \
            {"k_two": "", **expected}

        assert window.apply_to_game() is True

        assert parse_ini_file(user_ini, strip_values=False) == expected

    def test_an_import_with_no_override_is_read(self, window, tmp_path, monkeypatch, caplog):
        """A backup's user.ini can hold no override at all (a hand-edited one
        with only a comment). That is what the import wrote, not a file the
        reload could not read, so the old override goes, with nothing logged
        at WARNING."""
        _seed("k_one=Mine\n")
        _async_reload(window)    # the startup load

        with caplog.at_level(logging.WARNING, logger=main_window.logger.name):
            _import_settings(window, tmp_path, monkeypatch,
                             {AppSettings.get_active_channel(): "# no overrides\n"},
                             tr(self.LATER))

        assert _entry(window, "k_one").custom_value == ""
        assert not any("read no overrides" in r.getMessage() for r in caplog.records)

    def test_the_import_is_taken_from_the_backup_not_read_back(self, window, tmp_path,
                                                               monkeypatch):
        """The table takes the overrides from the backup's own text. Read back
        from the file just written, a read another program blocked for a
        moment (an antivirus scan, a sync client) parsed as no overrides, and
        a reload blocked the same way then kept nothing of the import."""
        user_ini = _seed("k_one=Mine\n")
        _async_reload(window)    # the startup load
        real = ini_io.read_bytes_retrying

        def held(path):
            if Path(path).name == user_ini.name:
                raise PermissionError(32, "another program holds it", str(path))
            return real(path)

        with monkeypatch.context() as patch:
            patch.setattr(ini_io, "read_bytes_retrying", held)
            _import_settings(window, tmp_path, monkeypatch,
                             {AppSettings.get_active_channel(): "k_one=Imported\n"},
                             tr(self.LATER))

        assert _entry(window, "k_one").custom_value == "Imported"
        assert user_ini.read_text(encoding="utf-8") == "k_one=Imported\n"

    def test_restart_now_still_restarts(self, window, tmp_path, monkeypatch):
        """And leaves the table alone, since the window is closing."""
        _seed("k_one=Mine\n")
        _async_reload(window)    # the startup load

        offered, restarts = _import_settings(
            window, tmp_path, monkeypatch,
            {AppSettings.get_active_channel(): "k_one=Imported\n"}, tr(self.NOW))

        assert offered == [tr(self.NOW), tr(self.LATER)]
        assert restarts == [True]
        assert _entry(window, "k_one").custom_value == "Mine"

    @pytest.mark.parametrize("click", [NOW, None])
    def test_an_import_that_switches_channel_only_restarts(self, window, tmp_path,
                                                           monkeypatch, click):
        """Every backup carries its active channel. One made on PTU switched
        this LIVE window to PTU, and carrying on saved LIVE's table into PTU's
        user.ini at the next close or Apply, over the import or PTU's own
        overrides. Shutting the box restarts too."""
        AppSettings.set_active_channel("LIVE")
        _seed("k_one=Mine\n")
        _async_reload(window)    # the startup load

        offered, restarts = _import_settings(
            window, tmp_path, monkeypatch, {"PTU": "k_one=Imported\n"},
            tr(click) if click else None, settings={AppSettings.ACTIVE_CHANNEL: "PTU"})

        assert offered == [tr(self.NOW)]
        assert restarts == [True]


class TestAChannelSwitchCarriesTheOverrides:
    def test_live_overrides_follow_to_ptu(self, window, monkeypatch):
        """Intended: the table's overrides follow the user to another channel
        (they reach its user.ini at the next Apply). Only a reload of the same
        user.ini narrows what it restores."""
        AppSettings.set_active_channel("LIVE")
        _seed("k_one=Live mine\n")
        window.perform_merge_and_reload()
        AppSettings.set_active_channel("PTU")
        _seed("k_two=Ptu mine\n")
        monkeypatch.setattr(window, "_check_p4k_freshness", lambda **_k: False)
        monkeypatch.setattr(window, "_maybe_prompt_dataforge_refresh", lambda *_a, **_k: None)

        window._on_channel_changed("PTU")

        assert _entry(window, "k_one").custom_value == "Live mine"
        assert _entry(window, "k_two").custom_value == "Ptu mine"


class TestApplyRecordsWhatItSaved:
    def test_an_applied_edit_loses_to_a_later_restore(self, window, game):
        """After Apply saved an edit it is in user.ini, so a file written
        later (a restore) wins over it at the next reload."""
        user_ini = _seed("")
        window.perform_merge_and_reload()
        _edit(window, "k_two", "Edited")
        assert window.apply_to_game() is True
        assert user_ini.read_text(encoding="utf-8") == "k_two=Edited\n"

        user_ini.write_text("k_two=Restored\n", encoding="utf-8")
        window.perform_merge_and_reload()

        assert _entry(window, "k_two").custom_value == "Restored"

    def test_a_failed_save_keeps_the_edit_unsaved(self, window, game, monkeypatch):
        """Apply that could not save user.ini (a locked file, Controlled
        Folder Access) records nothing, so the next reload keeps the edit.
        user.ini holds another override, so that reload is trusted."""
        _seed("k_one=Mine\n")
        window.perform_merge_and_reload()
        _edit(window, "k_two", "Edited")

        def refuse(_entries, path):
            raise PermissionError(5, "access denied", str(path))

        monkeypatch.setattr(user_ini_manager, "save_user_ini", refuse)
        monkeypatch.setattr(main_window.logger, "exception", lambda *_a, **_k: None)
        assert window.apply_to_game() is False

        window.perform_merge_and_reload()

        assert _entry(window, "k_two").custom_value == "Edited"

    def test_an_override_equal_to_the_stock_text_stays_unsaved(self, window, game):
        """save_user_ini leaves out an override equal to its original, so
        Apply must not record it as saved. When the stock text then changes,
        the reload keeps the user's text as an override. user.ini holds
        another override, so that reload is trusted."""
        user_ini = _seed("k_two=Mine\n")
        window.perform_merge_and_reload()
        _edit(window, "k_one", "Stock one")
        assert window.apply_to_game() is True
        assert user_ini.read_text(encoding="utf-8") == "k_two=Mine\n"
        base = AppSettings.get_base_ini_path()
        base.write_text("k_one=Stock one v2\nk_two=Stock two\n", encoding="utf-8")

        window.perform_merge_and_reload()

        entry = _entry(window, "k_one")
        assert entry.custom_value == "Stock one"
        assert entry.status == "Modified"
