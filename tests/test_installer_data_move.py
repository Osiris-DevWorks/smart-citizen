"""#455: a YES on Setup's OneDrive warning moves the data.

Setup's data-folder page warns when the folder is inside OneDrive and offers a
local one. A YES used to change only the folder name, so the user's edits
stayed behind in the OneDrive folder and the box had to say so. Now Setup
writes the folder the data was in to ``pending_data_move_from``, and the app's
next start moves Smart Citizen's own folders out of it
(``AppSettings.migrate_installer_data_move`` and
``user_ini_manager.move_owned_user_data``) before anything reads the data
folder, then says what it did (``MainWindow._report_installer_data_move``).

Nobody is asked at that point, so only what the app writes in its data folder
moves: the channel folders and ``logs``. Each goes through
``migrate_user_data_dir(move=True)``, which merges and never overwrites. The
value is deleted before the move, so it is tried once. Everything moved: a
status bar note. Something stayed: a box naming both folders.

The installer side is checked as text here (``tests/test_installer_onedrive_check.py``
has the box's wording): the registry value name the app reads, and when Setup
writes it.
"""
from __future__ import annotations

import ast
import json
import re
import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.gui.main_window as main_window  # noqa: E402
import src.utils.user_ini_manager as user_ini_manager  # noqa: E402
from src.gui.main_window import MainWindow  # noqa: E402
from src.utils.i18n import tr  # noqa: E402
from src.utils.install_scanner import SC_CHANNELS  # noqa: E402
from src.utils.json_settings import JsonSettings  # noqa: E402
from src.utils.settings import AppSettings  # noqa: E402
from src.utils.user_ini_manager import DataMoveResult, move_owned_user_data  # noqa: E402

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parent.parent


def _write(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _files(root: Path) -> set:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


# ── The move ─────────────────────────────────────────────────────────────────

class TestMoveOwnedUserData:
    def test_the_channel_folders_and_logs_move_and_the_old_folder_goes(self, tmp_path):
        old, new = tmp_path / "OneDrive" / "Smart Citizen", tmp_path / "local" / "Smart Citizen"
        _write(old / "LIVE" / "user.ini", "favourite=1")
        _write(old / "LIVE" / "backups" / "user.ini.bak_1")
        _write(old / "PTU" / "cache" / "base.ini")
        _write(old / "logs" / "crash_20261017.log")
        result = move_owned_user_data(old, new)
        assert _files(new) == {"LIVE/user.ini", "LIVE/backups/user.ini.bak_1",
                               "PTU/cache/base.ini", "logs/crash_20261017.log"}
        assert (new / "LIVE" / "user.ini").read_text(encoding="utf-8") == "favourite=1"
        assert result == DataMoveResult(old, new, 4, ())
        assert not old.exists()

    def test_other_files_in_the_old_folder_stay_put(self, tmp_path):
        """A data folder set to a general folder (OneDrive's Documents itself)
        keeps everything that is not Smart Citizen's, and so does the folder."""
        old, new = tmp_path / "OneDrive" / "Documents", tmp_path / "local"
        _write(old / "LIVE" / "user.ini")
        _write(old / "notes.txt")
        _write(old / "backups" / "tax-return.pdf")
        _write(old / "Photos" / "LIVE.jpg")
        result = move_owned_user_data(old, new)
        assert _files(new) == {"LIVE/user.ini"}
        assert _files(old) == {"notes.txt", "backups/tax-return.pdf", "Photos/LIVE.jpg"}
        assert result.moved == 1 and result.left == ()

    def test_a_file_already_in_the_new_folder_wins_and_its_old_copy_stays(self, tmp_path, caplog):
        """And the Log tab names it, as the box says: migrate_user_data_dir
        skips such a file without a word."""
        old, new = tmp_path / "old", tmp_path / "new"
        _write(old / "LIVE" / "user.ini", "old")
        _write(old / "LIVE" / "cache" / "base.ini")
        _write(new / "LIVE" / "user.ini", "new")
        result = move_owned_user_data(old, new)
        assert (new / "LIVE" / "user.ini").read_text(encoding="utf-8") == "new"
        assert (new / "LIVE" / "cache" / "base.ini").exists()
        assert result.moved == 1
        assert result.left == (old / "LIVE" / "user.ini",)
        assert old.exists()
        assert str(old / "LIVE" / "user.ini") in caplog.text

    def test_a_file_that_cannot_be_moved_is_listed_and_logged(self, tmp_path, monkeypatch, caplog):
        old, new = tmp_path / "old", tmp_path / "new"
        stuck = _write(old / "LIVE" / "user.ini")
        _write(old / "LIVE" / "cache" / "base.ini")
        real_copy = shutil.copy2

        def copy2(src, dst, *args, **kwargs):
            if Path(src) == stuck:
                raise PermissionError("held open by OneDrive")
            return real_copy(src, dst, *args, **kwargs)

        monkeypatch.setattr(user_ini_manager.shutil, "copy2", copy2)
        result = move_owned_user_data(old, new)
        assert result.moved == 1 and result.left == (stuck,)
        assert str(stuck) in caplog.text

    def test_the_old_dataforge_cache_trees_stay_and_are_not_counted(self, tmp_path):
        """An old data folder can still hold the pre-1.0 DataForge cache in a
        channel's cache folder (about 28,000 files). An extraction rebuilds it,
        a queued cleanup may name it where it is, and copying it out of OneDrive
        would hold up the start, so it stays, and the box does not count it."""
        old, new = tmp_path / "old", tmp_path / "new"
        _write(old / "LIVE" / "user.ini")
        _write(old / "LIVE" / "cache" / "base.ini")
        _write(old / "LIVE" / "cache" / "lang" / "german" / "base.ini")
        kept = [
            _write(old / "LIVE" / "cache" / "dataforge" / "Data" / "Libs" / "a.xml"),
            _write(old / "LIVE" / "cache" / "DataForge.migrating" / "b.xml"),
            _write(old / "PTU" / "cache" / "dataforge.extracting-ab12cd34" / "Game2.dcb"),
            _write(old / "PTU" / "cache" / "globalini.extracting-ab12cd34" / "global.ini"),
        ]
        result = move_owned_user_data(old, new)
        assert _files(new) == {"LIVE/user.ini", "LIVE/cache/base.ini",
                               "LIVE/cache/lang/german/base.ini"}
        assert all(path.exists() for path in kept)
        assert result.moved == 3 and result.left == ()

    def test_channel_folder_names_match_in_any_case(self, tmp_path):
        old, new = tmp_path / "old", tmp_path / "new"
        _write(old / "live" / "user.ini")
        _write(old / "Logs" / "export.txt")
        move_owned_user_data(old, new)
        assert _files(new) == {"live/user.ini", "Logs/export.txt"}

    def test_every_channel_folder_counts_as_its_own(self, tmp_path):
        old, new = tmp_path / "old", tmp_path / "new"
        for channel in SC_CHANNELS:
            _write(old / channel / "user.ini")
        result = move_owned_user_data(old, new)
        assert result.moved == len(SC_CHANNELS)
        assert _files(new) == {f"{channel}/user.ini" for channel in SC_CHANNELS}

    def test_the_same_folder_moves_nothing(self, tmp_path):
        folder = tmp_path / "Smart Citizen"
        _write(folder / "LIVE" / "user.ini")
        assert move_owned_user_data(folder, tmp_path / "." / "Smart Citizen") == \
            DataMoveResult(folder, tmp_path / "." / "Smart Citizen", 0, ())
        assert _files(folder) == {"LIVE/user.ini"}

    def test_an_old_folder_that_is_gone_moves_nothing(self, tmp_path):
        result = move_owned_user_data(tmp_path / "gone", tmp_path / "new")
        assert result.moved == 0 and result.left == ()
        assert not (tmp_path / "new").exists()


# ── The one-shot migrator ────────────────────────────────────────────────────

@pytest.fixture
def settings(tmp_path, monkeypatch):
    """A throwaway settings store in registry mode, with the data folder
    override pointing at tmp_path/new (where Setup's YES put it)."""
    monkeypatch.setattr("src.utils.build_mode.IS_PORTABLE", False)
    saved = AppSettings._backend
    AppSettings._backend = JsonSettings(tmp_path / "config.json")
    AppSettings.set_user_data_dir(tmp_path / "new")
    yield AppSettings._backend
    AppSettings._backend = saved


class TestTheMigrator:
    def test_nothing_asked_does_nothing(self, settings, tmp_path):
        assert AppSettings.migrate_installer_data_move() is None
        assert _files(tmp_path / "new") == set()

    def test_setup_s_folder_is_moved_into_the_data_folder_in_use(self, settings, tmp_path):
        old = tmp_path / "OneDrive" / "Smart Citizen"
        _write(old / "LIVE" / "user.ini")
        settings.setValue(AppSettings.PENDING_DATA_MOVE_FROM, str(old))
        result = AppSettings.migrate_installer_data_move()
        assert result.moved == 1 and result.left == ()
        assert result.new_root == AppSettings.get_user_data_dir()
        assert _files(tmp_path / "new") == {"LIVE/user.ini"}

    def test_it_is_tried_once(self, settings, tmp_path):
        """The value goes before the move, so a move that left files behind is
        reported, never retried at the next start."""
        old = tmp_path / "old"
        _write(old / "LIVE" / "user.ini", "old")
        _write(tmp_path / "new" / "LIVE" / "user.ini", "new")
        settings.setValue(AppSettings.PENDING_DATA_MOVE_FROM, str(old))
        assert AppSettings.migrate_installer_data_move().left
        assert settings.value(AppSettings.PENDING_DATA_MOVE_FROM, "") == ""
        assert AppSettings.migrate_installer_data_move() is None

    def test_a_folder_that_is_gone_clears_the_request(self, settings, tmp_path):
        settings.setValue(AppSettings.PENDING_DATA_MOVE_FROM, str(tmp_path / "gone"))
        result = AppSettings.migrate_installer_data_move()
        assert result.moved == 0 and result.left == ()
        assert settings.value(AppSettings.PENDING_DATA_MOVE_FROM, "") == ""

    def test_it_never_travels_in_a_settings_backup(self):
        assert AppSettings.PENDING_DATA_MOVE_FROM in AppSettings.PROFILE_EXCLUDE_KEYS


# ── The installer side and the startup order ─────────────────────────────────

def _installer() -> str:
    return (ROOT / "installer.iss").read_text(encoding="utf-8-sig")


def _pascal_routine(source: str, kind: str, name: str) -> str:
    match = re.search(rf"^{kind} {name}\(.*?^end;$", source, re.S | re.M)
    assert match, f"{kind} {name} not found in installer.iss"
    return re.sub(r"\{.*?\}", "", match.group(0), flags=re.S)


class TestTheInstallerWritesWhatTheAppReads:
    def test_setup_writes_the_value_the_app_reads(self):
        written = re.findall(
            r"RegWriteStringValue\(HKCU, SCRegNode, '([^']+)', PendingDataMoveFrom\)", _installer())
        assert written == [AppSettings.PENDING_DATA_MOVE_FROM]

    def test_only_when_the_page_left_a_move_to_make(self):
        code = _pascal_routine(_installer(), "procedure", "WriteInstallerChoicesToRegistry")
        write = code.index("'pending_data_move_from'")
        guard = code.rindex("if PendingDataMoveFrom <> '' then", 0, write)
        assert code[guard:write].count("end;") == 0

    def test_next_click_names_only_the_folder_the_data_is_in(self):
        """A YES remembers the folder only when it is the data folder the app
        uses now, a NO forgets it, and leaving the page drops it when the
        folder chosen in the end is that same one."""
        code = " ".join(_pascal_routine(_installer(), "function", "NextButtonClick").split())
        yes = code.index("if Response = IDYES then")
        assert ("if CompareText(CanonDir(Chosen), CanonDir(GetDocumentsDir())) = 0 then "
                "OneDriveMoveFrom := CanonDir(GetDocumentsDir());") in code[yes:]
        assert "OneDriveMoveFrom := '';" in code[yes:]
        assert ("if (OneDriveMoveFrom <> '') and (CompareText(CanonDir(Chosen), OneDriveMoveFrom) "
                "<> 0) then PendingDataMoveFrom := OneDriveMoveFrom else PendingDataMoveFrom := '';"
                ) in code

    def test_a_silent_setup_never_reaches_the_move(self):
        code = " ".join(_pascal_routine(_installer(), "function", "NextButtonClick").split())
        assert code.index("if WizardSilent() then Exit;") < code.index("OneDriveMoveFrom")

    def test_the_helpers_are_declared_before_next_click(self):
        source = _installer()
        for helper in ("function CanonDir(", "function GetDocumentsDir("):
            assert source.index(helper) < source.index("function NextButtonClick(")


class TestStartupOrder:
    @pytest.fixture(scope="class")
    def main_source(self):
        return (ROOT / "src" / "main.py").read_text(encoding="utf-8")

    def test_it_runs_in_the_registry_build_before_the_layout_migrators(self, main_source):
        call = main_source.index("installer_data_move = AppSettings.migrate_installer_data_move()")
        registry = main_source.index("if not build_mode.IS_PORTABLE:")
        portable = main_source.index("else:", registry)
        assert registry < call < portable
        assert main_source.index("AppSettings.migrate_docs_folder_rename()") < call
        assert call < main_source.index("AppSettings.migrate_game_path_to_channel_layout()")
        assert call < main_source.index("AppSettings.migrate_dataforge_cache_to_local()")

    def test_the_window_gets_the_result(self, main_source):
        tree = ast.parse(main_source)
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", "") == "MainWindow"]
        assert len(calls) == 1
        assert [k.arg for k in calls[0].keywords] == ["installer_data_move"]


# ── What the window says ─────────────────────────────────────────────────────

def _report(monkeypatch, result):
    box = MagicMock()
    monkeypatch.setattr(main_window, "QMessageBox", box)
    me = MagicMock()
    me._installer_data_move = result
    MainWindow._report_installer_data_move(me)
    return me, box


class TestTheReport:
    def test_nothing_asked_says_nothing(self, monkeypatch):
        me, box = _report(monkeypatch, None)
        me.statusBar.assert_not_called()
        box.warning.assert_not_called()

    def test_nothing_to_move_says_nothing(self, monkeypatch, tmp_path):
        me, box = _report(monkeypatch, DataMoveResult(tmp_path / "old", tmp_path / "new", 0, ()))
        me.statusBar.assert_not_called()
        box.warning.assert_not_called()

    def test_everything_moved_is_a_status_bar_note(self, monkeypatch, tmp_path):
        new = tmp_path / "new"
        me, box = _report(monkeypatch, DataMoveResult(tmp_path / "old", new, 7, ()))
        me.statusBar().showMessage.assert_called_once_with(
            tr("onedrive.installer_move_done", new=str(new), count=7))
        box.warning.assert_not_called()

    def test_files_left_behind_get_a_box_naming_both_folders(self, monkeypatch, tmp_path):
        old, new = tmp_path / "old", tmp_path / "new"
        left = (old / "LIVE" / "user.ini", old / "logs" / "a.log")
        me, box = _report(monkeypatch, DataMoveResult(old, new, 3, left))
        box.warning.assert_called_once_with(
            me, tr("onedrive.installer_move_left_title"),
            tr("onedrive.installer_move_left_body", old=str(old), new=str(new), moved=3, left=2))
        body = box.warning.call_args.args[2]
        assert str(old) in body and str(new) in body
        me.statusBar().showMessage.assert_not_called()

    def test_it_is_said_once(self, monkeypatch, tmp_path):
        me, _box = _report(monkeypatch, DataMoveResult(tmp_path / "o", tmp_path / "n", 1, ()))
        assert me._installer_data_move is None

    def test_the_startup_gate_says_it_before_the_onedrive_warning(self):
        me = MagicMock()
        me._startup_gate_pending = True
        order = []
        me._report_installer_data_move.side_effect = lambda: order.append("report")
        me._maybe_warn_onedrive_data_dir.side_effect = lambda: order.append("warning")
        MainWindow._continue_startup_after_update_gate(me)
        assert order == ["report", "warning"]


# ── The strings ──────────────────────────────────────────────────────────────

_PLACEHOLDERS = {
    "installer_move_done": {"count", "new"},
    "installer_move_left_title": set(),
    "installer_move_left_body": {"moved", "left", "old", "new"},
}


class TestEveryLanguage:
    @pytest.fixture(scope="class")
    def languages(self):
        return {f.parent.name: json.loads(f.read_text(encoding="utf-8"))["onedrive"]
                for f in sorted((ROOT / "languages").glob("*/ui.json"))}

    def test_each_text_is_there_english_in_ht_the_rest_in_at(self, languages):
        assert "english" in languages and len(languages) == 11
        for language, onedrive in languages.items():
            for key in _PLACEHOLDERS:
                node = onedrive[key]
                if language == "english":
                    assert node["ht"] and node["at"] == "", key
                else:
                    assert node["ht"] == "" and node["at"], f"{language} {key}"

    def test_each_text_takes_the_values_the_window_passes(self, languages):
        for language, onedrive in languages.items():
            for key, names in _PLACEHOLDERS.items():
                text = onedrive[key]["ht"] or onedrive[key]["at"]
                assert set(re.findall(r"\{(\w+)\}", text)) == names, f"{language} {key}"
