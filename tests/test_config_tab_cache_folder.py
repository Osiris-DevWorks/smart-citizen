"""#494: the Config tab's DataForge cache folder change, with a folder that
cannot be used.

``ConfigTab._maybe_apply_cache_change`` saved the new folder and then made
its cache folder, and only Cancel undid the save. So a folder Windows refused
(its permissions, Controlled folder access) stayed saved behind a box saying
it could not be used, and every later launch stopped before the window
opened. Reset, and a cleared field, did the same when the default folder was
the refused one, and Reset sent the error to the crash dialog. It also read
the old cache folder with the getter that creates it, so a saved folder
Windows refused, or one on a drive that is gone, stopped every change, Reset
included: the app gave no way off it. The box was in English.

Now the old folder is only read, a new one whose cache folder cannot be made
is undone as Cancel undoes it, and one translated box names the folder that
was tried, with the Windows error logged at WARNING. These tests build the
real ConfigTab offscreen (``qapp``), with settings in ``tmp_profile``, a fake
QMessageBox, and real refusals from ``tests/unusable_folder.py`` (a folder
whose permissions deny new folders, a drive that is not there).

Qt also sends the field's editingFinished when it loses focus after a
setText nobody typed, so a click into the field and out again tried the
saved folder once more, and one that cannot be used opened a box for a
change nobody asked for. The field now saves only a folder the user typed.
``TestOnlyATypedFolderIsSaved`` shows the tab as a window and clicks and
types with QTest, so the focus moves as a user's does.
"""
from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

import src.gui.config_tab as config_tab
from src.gui.config_tab import ConfigTab
from src.utils.i18n import tr
from src.utils.json_settings import JsonSettings
from src.utils.pak_extractor import P4K_MTIME_STAMP
from src.utils.settings import AppSettings
from tests.junction import make_junction
from tests.unusable_folder import missing_drive_folder, new_folders_denied

pytestmark = [pytest.mark.unit, pytest.mark.regression,
              pytest.mark.usefixtures("qapp", "english_ui")]

# What the fake migration prompt can click, in the order the tab adds them.
_ANSWERS = ("delete", "keep", "cancel")


@pytest.fixture
def boxes(monkeypatch):
    """The Config tab's QMessageBox, faked. ``boxes.warning`` records each
    warning box, and ``boxes.prompts`` the migration prompts made, each of
    which clicks ``boxes.answer`` ("delete", "keep" or "cancel")."""
    fake = MagicMock()
    fake.prompts = []
    fake.answer = "keep"

    def make(*_args):
        prompt = MagicMock()
        buttons = [MagicMock(name=name) for name in _ANSWERS]
        prompt.addButton.side_effect = buttons
        prompt.clickedButton.return_value = buttons[_ANSWERS.index(fake.answer)]
        fake.prompts.append(prompt)
        return prompt

    fake.side_effect = make
    monkeypatch.setattr(config_tab, "QMessageBox", fake)
    return fake


def _new_tab():
    """A real Config tab, and the list its cache_dir_changed signals land in."""
    tab = ConfigTab()
    changes = []
    tab.cache_dir_changed.connect(changes.append)
    return tab, changes


def _type(tab, folder) -> None:
    """Type *folder* in the cache folder field and press Enter. The tab
    saves only a folder the user typed, which it reads from the field's
    modified flag: typing sets it and setText clears it, so it is set here
    as typing sets it."""
    tab.cache_dir_input.setText(str(folder))
    tab.cache_dir_input.setModified(True)
    tab.cache_dir_input.editingFinished.emit()


def _browse(tab, folder, monkeypatch) -> None:
    """Pick *folder* with Browse. The picker is faked and, like the real one,
    answers with forward slashes."""
    picker = MagicMock()
    picker.getExistingDirectory.return_value = Path(folder).as_posix()
    monkeypatch.setattr(config_tab, "QFileDialog", picker)
    tab._cache_browse_btn.click()


def _pick(how: str, tab, folder, monkeypatch) -> None:
    if how == "typed":
        _type(tab, folder)
    else:
        _browse(tab, folder, monkeypatch)


def _clear(tab) -> None:
    """Empty the field and press Enter: back to the default folder."""
    _type(tab, "")


def _reset(tab) -> None:
    tab._cache_reset_btn.click()


def _saved_override(profile: Path) -> str:
    """The cache folder override as the settings file holds it, read afresh."""
    return JsonSettings(profile / "config.json").value(AppSettings.CACHE_DIR, "", type=str)


def _resolved(folder) -> str:
    """A folder as the tab shows and names it once picked: resolved."""
    return os.path.normpath(str(Path(folder).resolve()))


def _default_base(profile: Path) -> str:
    """The default cache folder (registry mode), as the tab shows and names
    it: %LOCALAPPDATA%\\Smart Citizen, which the settings do not resolve."""
    return os.path.normpath(str(profile / "LocalAppData" / "Smart Citizen"))


def _stamped_cache(base: Path) -> Path:
    """A populated LIVE cache under *base*, which a change away from it
    prompts for. Returns its folder."""
    leaf = base / "LIVE" / "cache" / "dataforge"
    leaf.mkdir(parents=True)
    (leaf / P4K_MTIME_STAMP).write_text("1", encoding="utf-8")
    return leaf


def _refused_text(folder: str) -> str:
    return (tr("config.cache_folder_refused", folder=folder) + "\n\n"
            + tr("extract.folder_refused_fix"))


def _reason_for(folder: Path, winerror: int) -> str:
    """What Windows says to making *folder* (which fails with *winerror*),
    read here so the test holds in any Windows language."""
    with pytest.raises(OSError) as raised:
        folder.mkdir(parents=True, exist_ok=True)
    assert raised.value.winerror == winerror
    assert raised.value.strerror
    return raised.value.strerror


def _unusable_saved_folder(profile: Path, kind: str):
    """A cache folder to save whose own cache folder cannot be made
    (Smart Citizen opens like this since #494): for "refused" one that
    denies new folders, for "missing drive" one on a drive that is not
    there. Returns it and the context to hold while it should refuse."""
    if kind == "refused":
        saved = profile / "saved"
        saved.mkdir()
        return saved, new_folders_denied(saved)
    return missing_drive_folder(), contextlib.nullcontext()


def _reported_once(boxes, tab, caplog, text: str, folder: str, windows_error: str) -> None:
    """One translated box with *text*, the Windows error logged once at
    WARNING naming *folder*, and nothing at ERROR, which would open a second
    box (the global error dialog)."""
    boxes.warning.assert_called_once_with(tab, tr("config.invalid_cache_folder_title"), text)
    logged = [r.getMessage() for r in caplog.records
              if r.name == config_tab.logger.name and r.levelno == logging.WARNING]
    assert len(logged) == 1, logged
    assert folder in logged[0] and windows_error in logged[0], logged[0]
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []


class TestCacheFolderChangeIsAtomic:
    @pytest.mark.parametrize("how", ["typed", "browsed"])
    @pytest.mark.parametrize("inside", [False, True],
                             ids=["the refused folder", "a new folder inside it"])
    def test_a_refused_folder_is_not_saved(self, tmp_profile, boxes, caplog, monkeypatch,
                                           how, inside):
        """With a populated old cache, which a change prompts for: the
        previous folder stays saved and shown, one box says why, and there is
        no prompt, no re-extract and no cleanup queued."""
        old_leaf = _stamped_cache(tmp_profile / "old")
        AppSettings.set_cache_dir(tmp_profile / "old")
        refused = tmp_profile / "refused"
        refused.mkdir()
        target = refused / "new" if inside else refused
        tab, changes = _new_tab()

        with new_folders_denied(refused), caplog.at_level(logging.WARNING):
            _pick(how, tab, target, monkeypatch)

        folder = _resolved(target)
        assert _saved_override(tmp_profile) == str(tmp_profile / "old")
        assert tab.cache_dir_input.text() == _resolved(tmp_profile / "old")
        _reported_once(boxes, tab, caplog, _refused_text(folder), folder, "[WinError 5]")
        assert boxes.warning.call_args.args[2] == (
            f"Windows denied Smart Citizen permission to create its cache in:\n{folder}\n\n"
            "The DataForge cache folder was not changed.\n\n"
            "Check the permissions on that folder, or allow Smart Citizen through "
            "Controlled folder access in Windows Security, then try again.")
        assert boxes.prompts == [] and changes == []
        assert AppSettings.get_pending_cache_cleanup() == ""
        assert list(refused.iterdir()) == []
        assert (old_leaf / P4K_MTIME_STAMP).exists()

    def test_a_folder_on_a_drive_that_is_gone_is_not_saved(self, tmp_profile, boxes, caplog):
        (tmp_profile / "old").mkdir()
        AppSettings.set_cache_dir(tmp_profile / "old")
        target = missing_drive_folder()
        tab, changes = _new_tab()

        with caplog.at_level(logging.WARNING):
            _type(tab, target)

        folder = _resolved(target)
        assert _saved_override(tmp_profile) == str(tmp_profile / "old")
        assert tab.cache_dir_input.text() == _resolved(tmp_profile / "old")
        _reported_once(boxes, tab, caplog, tr("config.cache_folder_unreachable", folder=folder),
                       folder, "[WinError 3]")
        assert boxes.warning.call_args.args[2] == (
            f"Smart Citizen could not reach:\n{folder}\n\n"
            "The DataForge cache folder was not changed.")
        assert changes == []

    def test_any_error_making_the_new_cache_folder_is_undone(
        self, tmp_profile, boxes, caplog, monkeypatch
    ):
        """The folder is there, but its drive goes away before its cache
        folder is made (faked: a FileNotFoundError from making it, after the
        new folder was saved). The save is undone too, and the box says the
        folder could not be reached."""
        (tmp_profile / "old").mkdir()
        AppSettings.set_cache_dir(tmp_profile / "old")
        new = tmp_profile / "new"
        new.mkdir()
        error = FileNotFoundError(3, "The system cannot find the path specified",
                                  str(new / "LIVE"))

        def unreachable():
            raise error

        monkeypatch.setattr(AppSettings, "get_dataforge_cache_dir", staticmethod(unreachable))
        tab, changes = _new_tab()

        with caplog.at_level(logging.WARNING):
            _type(tab, new)

        folder = _resolved(new)
        assert _saved_override(tmp_profile) == str(tmp_profile / "old")
        assert tab.cache_dir_input.text() == _resolved(tmp_profile / "old")
        _reported_once(boxes, tab, caplog, tr("config.cache_folder_unreachable", folder=folder),
                       folder, str(error))
        assert changes == []

    def test_a_drive_that_is_not_ready_could_not_be_reached(
        self, tmp_profile, boxes, caplog, monkeypatch
    ):
        """The new cache folder is on a drive letter with no media in it, a
        card reader with the card taken out (faked: ERROR_NOT_READY, which
        Python raises as a PermissionError). Nothing was refused, so the box
        says the folder could not be reached, with no permission advice."""
        (tmp_profile / "old").mkdir()
        AppSettings.set_cache_dir(tmp_profile / "old")
        new = tmp_profile / "new"
        new.mkdir()
        error = OSError(None, "The device is not ready", str(new / "LIVE"), 21)
        assert isinstance(error, PermissionError)

        def not_ready():
            raise error

        monkeypatch.setattr(AppSettings, "get_dataforge_cache_dir", staticmethod(not_ready))
        tab, changes = _new_tab()

        with caplog.at_level(logging.WARNING):
            _type(tab, new)

        folder = _resolved(new)
        assert _saved_override(tmp_profile) == str(tmp_profile / "old")
        assert tab.cache_dir_input.text() == _resolved(tmp_profile / "old")
        _reported_once(boxes, tab, caplog, tr("config.cache_folder_unreachable", folder=folder),
                       folder, str(error))
        assert changes == []

    @pytest.mark.parametrize("name, winerror", [("SC|Cache", 123), ("notes.txt/cache", 183)],
                             ids=["a name Windows does not take", "a path through a file"])
    def test_a_folder_windows_rejects_gets_its_reason(
        self, tmp_profile, boxes, caplog, name, winerror
    ):
        """A typed name with a character Windows does not allow in a folder
        name, or a path that runs through a file. Neither is a refusal or a
        drive that is gone (it used to say the folder could not be reached),
        so the box gives Windows' own reason, in the user's Windows language,
        as the box before #494 did."""
        (tmp_profile / "old").mkdir()
        AppSettings.set_cache_dir(tmp_profile / "old")
        (tmp_profile / "notes.txt").write_text("not a folder", encoding="utf-8")
        target = tmp_profile / name
        reason = _reason_for(target, winerror)
        tab, changes = _new_tab()

        with caplog.at_level(logging.WARNING):
            _type(tab, target)

        folder = _resolved(target)
        assert _saved_override(tmp_profile) == str(tmp_profile / "old")
        assert tab.cache_dir_input.text() == _resolved(tmp_profile / "old")
        _reported_once(boxes, tab, caplog,
                       tr("config.cache_folder_unusable", folder=folder, reason=reason),
                       folder, f"[WinError {winerror}]")
        assert boxes.warning.call_args.args[2] == (
            f"Smart Citizen could not use:\n{folder}\n\n{reason}\n\n"
            "The DataForge cache folder was not changed.")
        assert boxes.prompts == [] and changes == []

    def test_a_new_cache_folder_windows_rejects_is_undone(
        self, tmp_profile, boxes, caplog, slot_errors
    ):
        """The folder is there and takes new folders, but a file named LIVE
        sits where the channel's folder goes. So its cache folder cannot be
        made once the new folder is saved, for a reason that is neither a
        refusal nor a folder that is not there (WinError 183, for real). The
        save is undone, and the box gives Windows' own reason."""
        (tmp_profile / "old").mkdir()
        AppSettings.set_cache_dir(tmp_profile / "old")
        new = tmp_profile / "new"
        new.mkdir()
        (new / "LIVE").write_text("not a folder", encoding="utf-8")
        reason = _reason_for(new / "LIVE" / "cache" / "dataforge", 183)
        tab, changes = _new_tab()

        with caplog.at_level(logging.WARNING):
            _type(tab, new)

        folder = _resolved(new)
        assert slot_errors == []
        assert _saved_override(tmp_profile) == str(tmp_profile / "old")
        assert tab.cache_dir_input.text() == _resolved(tmp_profile / "old")
        _reported_once(boxes, tab, caplog,
                       tr("config.cache_folder_unusable", folder=folder, reason=reason),
                       folder, "[WinError 183]")
        assert boxes.prompts == [] and changes == []
        assert (new / "LIVE").is_file()

    def test_a_typed_variable_is_named_as_the_folder_it_stands_for(
        self, tmp_profile, boxes, caplog
    ):
        """The box and the log name the folder a typed variable stands for,
        not the text typed: %LOCALAPPDATA%\\refused here, expanded. The
        folder is already resolved, so this cannot tell expanding from
        resolving: the junction test below pins that."""
        (tmp_profile / "old").mkdir()
        AppSettings.set_cache_dir(tmp_profile / "old")
        refused = tmp_profile / "LocalAppData" / "refused"
        refused.mkdir(parents=True)
        typed = "%LOCALAPPDATA%" + os.sep + "refused"
        tab, changes = _new_tab()

        with new_folders_denied(refused), caplog.at_level(logging.WARNING):
            _type(tab, typed)

        folder = os.path.normpath(str(refused))
        assert folder == _resolved(refused) and folder != typed
        assert _saved_override(tmp_profile) == str(tmp_profile / "old")
        _reported_once(boxes, tab, caplog, _refused_text(folder), folder, "[WinError 5]")
        # The Windows error names the folder too, so pin where the log line
        # names it.
        logged = [r.getMessage() for r in caplog.records
                  if r.name == config_tab.logger.name and r.levelno == logging.WARNING]
        assert logged[0].startswith(f"Could not use DataForge cache folder {folder}: ")
        assert changes == []

    def test_a_typed_junction_is_named_as_the_folder_it_leads_to(
        self, tmp_profile, boxes, caplog
    ):
        """A junction typed in the field, leading to a folder that denies
        new folders. The box and the log name the folder Windows refused,
        where the junction leads, not the junction typed: the typed path is
        resolved, not only expanded."""
        (tmp_profile / "old").mkdir()
        AppSettings.set_cache_dir(tmp_profile / "old")
        real, link = tmp_profile / "real", tmp_profile / "link"
        make_junction(link, real)
        tab, changes = _new_tab()

        with new_folders_denied(real), caplog.at_level(logging.WARNING):
            _type(tab, link)

        folder = os.path.normpath(str(real.resolve()))
        assert folder == _resolved(link) and folder != os.path.normpath(str(link))
        assert _saved_override(tmp_profile) == str(tmp_profile / "old")
        _reported_once(boxes, tab, caplog, _refused_text(folder), folder, "[WinError 5]")
        # The Windows error names the real folder whatever the box names,
        # so pin where the log line names it.
        logged = [r.getMessage() for r in caplog.records
                  if r.name == config_tab.logger.name and r.levelno == logging.WARNING]
        assert logged[0].startswith(f"Could not use DataForge cache folder {folder}: ")
        assert changes == []
        assert list(real.iterdir()) == []

    @pytest.mark.parametrize("how", ["reset", "cleared"])
    @pytest.mark.parametrize("portable", [False, True], ids=["registry", "portable"])
    def test_a_refused_default_keeps_the_saved_folder(
        self, tmp_profile, boxes, caplog, slot_errors, monkeypatch, how, portable
    ):
        """The default folder refuses new folders and holds no cache yet.
        Reset used to raise into the crash dialog, and a cleared field left
        the default saved. The box names the default folder of the build
        mode: %LOCALAPPDATA%\\Smart Citizen, or data\\cache next to the
        portable exe."""
        if portable:
            monkeypatch.setattr("src.utils.build_mode.IS_PORTABLE", True)
            monkeypatch.setattr(AppSettings, "_portable_data_dir",
                                staticmethod(lambda: tmp_profile / "portable" / "data"))
            default = tmp_profile / "portable" / "data" / "cache"
        else:
            default = tmp_profile / "LocalAppData" / "Smart Citizen"
        (tmp_profile / "saved").mkdir()
        AppSettings.set_cache_dir(tmp_profile / "saved")
        default.mkdir(parents=True)
        tab, changes = _new_tab()

        with new_folders_denied(default), caplog.at_level(logging.WARNING):
            _reset(tab) if how == "reset" else _clear(tab)

        folder = os.path.normpath(str(default))
        assert slot_errors == []
        assert _saved_override(tmp_profile) == str(tmp_profile / "saved")
        assert tab.cache_dir_input.text() == _resolved(tmp_profile / "saved")
        _reported_once(boxes, tab, caplog, _refused_text(folder), folder, "[WinError 5]")
        assert changes == []
        assert list(default.iterdir()) == []

    @pytest.mark.parametrize("how", ["reset", "cleared"])
    def test_a_default_whose_cache_folder_windows_rejects_keeps_the_saved_folder(
        self, tmp_profile, boxes, caplog, slot_errors, how
    ):
        """The default folder takes new folders, but a file named LIVE sits
        where the channel's folder goes (WinError 183, for real: neither a
        refusal nor a folder that is not there). The saved folder is kept,
        nothing reaches the crash dialog, and one box names the default
        folder with Windows' own reason."""
        (tmp_profile / "saved").mkdir()
        AppSettings.set_cache_dir(tmp_profile / "saved")
        default = tmp_profile / "LocalAppData" / "Smart Citizen"
        default.mkdir(parents=True)
        (default / "LIVE").write_text("not a folder", encoding="utf-8")
        reason = _reason_for(default / "LIVE" / "cache" / "dataforge", 183)
        tab, changes = _new_tab()

        with caplog.at_level(logging.WARNING):
            _reset(tab) if how == "reset" else _clear(tab)

        folder = os.path.normpath(str(default))
        assert slot_errors == []
        assert _saved_override(tmp_profile) == str(tmp_profile / "saved")
        assert tab.cache_dir_input.text() == _resolved(tmp_profile / "saved")
        _reported_once(boxes, tab, caplog,
                       tr("config.cache_folder_unusable", folder=folder, reason=reason),
                       folder, "[WinError 183]")
        assert changes == []
        assert (default / "LIVE").is_file()

    @pytest.mark.parametrize("kind", ["refused", "missing drive"])
    @pytest.mark.parametrize("how", ["reset", "typed"])
    def test_a_saved_folder_that_cannot_be_used_can_be_left(
        self, tmp_profile, boxes, slot_errors, kind, how
    ):
        """The saved folder denies new folders, or its drive is gone, so its
        cache folder cannot be made (Smart Citizen now opens like this). The
        old cache folder is only read, so Reset and a good typed folder both
        go through: no box, no prompt (nothing was extracted there), and one
        re-extract asked for."""
        saved, unusable = _unusable_saved_folder(tmp_profile, kind)
        AppSettings.set_cache_dir(saved)
        good = tmp_profile / "good"

        with unusable:
            tab, changes = _new_tab()
            if how == "reset":
                _reset(tab)
            else:
                _type(tab, good)

        if how == "reset":
            base, shown, override = Path(_default_base(tmp_profile)), _default_base(tmp_profile), ""
        else:
            base, shown, override = good.resolve(), _resolved(good), str(good.resolve())
        leaf = base / "LIVE" / "cache" / "dataforge"
        assert slot_errors == []
        boxes.warning.assert_not_called()
        assert boxes.prompts == []
        assert _saved_override(tmp_profile) == override
        assert tab.cache_dir_input.text() == shown
        assert changes == [str(leaf)] and leaf.is_dir()
        if kind == "refused":
            assert list(saved.iterdir()) == []

    def test_cancel_still_undoes_the_change(self, tmp_profile, boxes):
        old_leaf = _stamped_cache(tmp_profile / "old")
        AppSettings.set_cache_dir(tmp_profile / "old")
        boxes.answer = "cancel"
        tab, changes = _new_tab()

        _type(tab, tmp_profile / "new")

        assert len(boxes.prompts) == 1
        assert _saved_override(tmp_profile) == str(tmp_profile / "old")
        assert tab.cache_dir_input.text() == _resolved(tmp_profile / "old")
        assert changes == []
        assert AppSettings.get_pending_cache_cleanup() == ""
        boxes.warning.assert_not_called()
        assert (old_leaf / P4K_MTIME_STAMP).exists()

    def test_an_accepted_change_is_saved_and_asks_for_one_re_extract(self, tmp_profile, boxes):
        """Re-extract and delete old: saved, the new cache folder made, the
        old one queued for after the re-extract, and one signal."""
        _stamped_cache(tmp_profile / "old")
        AppSettings.set_cache_dir(tmp_profile / "old")
        boxes.answer = "delete"
        new = tmp_profile / "new"
        tab, changes = _new_tab()

        _type(tab, new)

        new_leaf = new.resolve() / "LIVE" / "cache" / "dataforge"
        assert len(boxes.prompts) == 1
        assert _saved_override(tmp_profile) == str(new.resolve())
        assert tab.cache_dir_input.text() == _resolved(new)
        assert changes == [str(new_leaf)] and new_leaf.is_dir()
        assert AppSettings.get_pending_cache_cleanup() == str(
            (tmp_profile / "old").resolve() / "LIVE" / "cache" / "dataforge")
        boxes.warning.assert_not_called()

    def test_the_same_folder_again_changes_nothing(self, tmp_profile, boxes):
        """The same-folder early return: no prompt, no re-extract."""
        _stamped_cache(tmp_profile / "old")
        AppSettings.set_cache_dir(tmp_profile / "old")
        tab, changes = _new_tab()

        _type(tab, tmp_profile / "old")

        assert boxes.prompts == [] and changes == []
        boxes.warning.assert_not_called()
        assert _saved_override(tmp_profile) == str((tmp_profile / "old").resolve())
        assert tab.cache_dir_input.text() == _resolved(tmp_profile / "old")

    def test_the_same_refused_folder_again_says_it_was_not_changed(
        self, tmp_profile, boxes, caplog
    ):
        """The saved folder typed again and Enter, while it denies new
        folders and holds no cache folder yet (Smart Citizen opens like this
        now). The same-folder return comes after the cache folder is made,
        so this is not a quiet no-op: one refused box names the folder,
        there is no prompt and no signal, and the saved folder stays as it
        was."""
        saved = tmp_profile / "saved"
        saved.mkdir()
        AppSettings.set_cache_dir(saved)
        tab, changes = _new_tab()

        with new_folders_denied(saved), caplog.at_level(logging.WARNING):
            _type(tab, saved)

        folder = _resolved(saved)
        _reported_once(boxes, tab, caplog, _refused_text(folder), folder, "[WinError 5]")
        assert boxes.prompts == [] and changes == []
        assert _saved_override(tmp_profile) == str(saved)
        assert tab.cache_dir_input.text() == folder
        assert list(saved.iterdir()) == []

    def test_a_file_is_not_taken_for_a_cache_folder(self, tmp_profile, boxes):
        (tmp_profile / "old").mkdir()
        AppSettings.set_cache_dir(tmp_profile / "old")
        a_file = tmp_profile / "cache.txt"
        a_file.write_text("not a folder", encoding="utf-8")
        tab, changes = _new_tab()

        _type(tab, a_file)

        folder = _resolved(a_file)
        boxes.warning.assert_called_once_with(
            tab, tr("config.invalid_cache_folder_title"),
            tr("config.cache_folder_is_file", folder=folder))
        assert boxes.warning.call_args.args[2] == (
            f"The selected cache folder is a file, not a folder:\n{folder}")
        assert _saved_override(tmp_profile) == str(tmp_profile / "old")
        assert tab.cache_dir_input.text() == _resolved(tmp_profile / "old")
        assert changes == []


@pytest.fixture
def shown_tab(qapp):
    """Builds a real Config tab shown as the active window, so QTest's
    clicks and keys move the focus as a user's do. Call it once the settings
    are in place. Each tab built is closed afterwards."""
    built = []

    def build():
        tab, changes = _new_tab()
        built.append(tab)
        tab.resize(900, 700)
        tab.show()
        tab.activateWindow()
        assert QTest.qWaitForWindowActive(tab, 5000), "the Config tab never became active"
        return tab, changes

    yield build
    for tab in built:
        tab.close()


def _click(widget) -> None:
    """A real mouse click, which moves the focus as a user's click does."""
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
    QApplication.processEvents()


class TestOnlyATypedFolderIsSaved:
    """Qt sends the field's editingFinished on Enter, and when the field
    loses focus after its text was set, by typing or by setText: the tab
    sets it when it is built and after every box. So with a saved folder
    that cannot be used, a click into the field and out again tried it
    again and opened a box, Enter with nothing typed did too, and the click
    away after a failed change opened a second box naming the saved folder.
    Each case here failed that way before. The fake QMessageBox takes no
    focus, so the field keeps it after a box, as it gets it back on Windows
    when a real box closes."""

    @pytest.mark.parametrize("away", ["the data folder field", "Browse"])
    @pytest.mark.parametrize("kind", ["refused", "missing drive"])
    def test_a_click_in_and_out_tries_nothing(
        self, tmp_profile, boxes, caplog, monkeypatch, shown_tab, kind, away
    ):
        """Nothing typed, then a click on another field, or on Browse with
        the picker cancelled: no box, nothing logged at WARNING, and the
        saved folder stays saved and shown."""
        saved, unusable = _unusable_saved_folder(tmp_profile, kind)
        AppSettings.set_cache_dir(saved)
        picker = MagicMock()
        picker.getExistingDirectory.return_value = ""
        monkeypatch.setattr(config_tab, "QFileDialog", picker)

        with unusable, caplog.at_level(logging.WARNING):
            tab, changes = shown_tab()
            field = tab.cache_dir_input
            shown = field.text()
            finished = []
            field.editingFinished.connect(lambda: finished.append(field.text()))
            caplog.clear()
            _click(field)
            assert field.hasFocus()
            _click(tab.data_dir_input if away == "the data folder field" else tab._cache_browse_btn)
            assert not field.hasFocus()

        # Qt did send the signal that used to try the saved folder again.
        assert finished == [shown]
        boxes.warning.assert_not_called()
        assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == []
        assert _saved_override(tmp_profile) == str(saved)
        assert field.text() == shown
        assert changes == []
        assert picker.getExistingDirectory.called is (away == "Browse")

    @pytest.mark.parametrize("typed", ["another folder", "the saved folder"])
    @pytest.mark.parametrize("kind", ["refused", "missing drive"])
    def test_a_failed_change_then_a_click_away_gives_one_box(
        self, tmp_profile, boxes, caplog, shown_tab, kind, typed
    ):
        """A folder typed key by key, another one on a drive that is not
        there or the saved folder again, then Enter: one box names it, the
        field goes back to the saved folder, and the click away that follows
        tries nothing more."""
        saved, unusable = _unusable_saved_folder(tmp_profile, kind)
        AppSettings.set_cache_dir(saved)
        target = missing_drive_folder("Other") if typed == "another folder" else saved

        with unusable, caplog.at_level(logging.WARNING):
            tab, changes = shown_tab()
            field = tab.cache_dir_input
            shown = field.text()
            finished = []
            field.editingFinished.connect(lambda: finished.append(field.text()))
            caplog.clear()
            _click(field)
            field.selectAll()
            QTest.keyClicks(field, str(target))
            QTest.keyClick(field, Qt.Key.Key_Return)
            assert field.hasFocus()
            _click(tab.data_dir_input)
            assert not field.hasFocus()

        folder = _resolved(target)
        if kind == "refused" and typed == "the saved folder":
            text, windows_error = _refused_text(folder), "[WinError 5]"
        else:
            text = tr("config.cache_folder_unreachable", folder=folder)
            windows_error = "[WinError 3]"
        # Enter sent the signal, and so did the click away, after the box
        # set the field back.
        assert len(finished) == 2
        _reported_once(boxes, tab, caplog, text, folder, windows_error)
        assert _saved_override(tmp_profile) == str(saved)
        assert field.text() == shown
        assert changes == []

    @pytest.mark.parametrize("kind", ["refused", "missing drive"])
    def test_enter_with_nothing_typed_tries_nothing(
        self, tmp_profile, boxes, caplog, shown_tab, kind
    ):
        """Enter in the field with nothing typed asks for no change, so it
        tries nothing either, and nor does the click away after it: no box
        and nothing logged at WARNING. (The saved folder typed again is a
        change, above.)"""
        saved, unusable = _unusable_saved_folder(tmp_profile, kind)
        AppSettings.set_cache_dir(saved)

        with unusable, caplog.at_level(logging.WARNING):
            tab, changes = shown_tab()
            field = tab.cache_dir_input
            shown = field.text()
            finished = []
            field.editingFinished.connect(lambda: finished.append(field.text()))
            caplog.clear()
            _click(field)
            QTest.keyClick(field, Qt.Key.Key_Return)
            assert field.hasFocus()
            _click(tab.data_dir_input)

        assert finished[:1] == [shown]   # Enter sent the signal
        boxes.warning.assert_not_called()
        assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == []
        assert _saved_override(tmp_profile) == str(saved)
        assert field.text() == shown
        assert changes == []
