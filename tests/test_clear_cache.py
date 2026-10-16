"""#479: More > Clear Cache clears the DataForge cache in use.

``MainWindow.clear_cache`` looked for the DataForge cache in the data
folder's cache folder (``get_cache_dir() / "dataforge"``), where it lived
before 1.x, so on a current install the DataForge question never appeared
and the real cache was never cleared, while a leftover there was offered and
reported deleted. It now reads the cache folder in use through
``AppSettings.get_dataforge_cache_leaf()`` (the default, the portable
build's or a cache folder override), named without creating it, and offers
it only when it holds a cache (its freshness stamp or its records). A
leftover in the old place is the queued old-cache cleanup's. A cache folder
on a drive that is not there is named in the summary while the rest clears,
nothing is cleared while an extraction or a generation runs (the status bar
says why), the Enhancements tab is refreshed afterwards, failures are logged
once at WARNING (an ERROR record opened a second box, twice), and every text
goes through ``tr()``.

``MainWindow.clear_cache`` runs on a stub window with real settings
(``tmp_profile``), real files and a fake ``QMessageBox`` that answers each
question in turn and fails the test on a question it has no answer for.
"""
from __future__ import annotations

import ast
import inspect
import json
import logging
import string
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import src.gui.main_window as main_window
import src.utils.pak_extractor as pe
from src.gui.main_window import MainWindow
from src.utils.i18n import tr
from src.utils.pak_extractor import DATAFORGE_RECORDS_SUBPATH, P4K_MTIME_STAMP
from src.utils.settings import AppSettings
from tests.unusable_folder import missing_drive_folder

pytestmark = pytest.mark.unit

_LANGUAGES = Path(__file__).resolve().parent.parent / "languages"
_UI_FILES = sorted(_LANGUAGES.glob("*/ui.json"))
# Clear Cache's texts and the fields each takes.
_KEYS = {
    "dialogs.clear_cache_busy": set(),
    "dialogs.clear_cache_files_body": {"files"},
    "dialogs.clear_cache_dataforge_body": {"folder"},
    "dialogs.clear_cache_dataforge_unreachable": {"folder"},
    "dialogs.clear_cache_progress_title": set(),
    "dialogs.clear_cache_progress_files": set(),
    "dialogs.clear_cache_progress_file": {"name"},
    "dialogs.clear_cache_progress_dataforge": set(),
    "dialogs.cache_cleared_body": {"count"},
    "dialogs.cache_cleared_failed": {"failures"},
}
_FILES_QUESTION = tr("dialogs.clear_cache_title")
_DATAFORGE_QUESTION = tr("dialogs.dataforge_cache_title")


@pytest.fixture
def clear(tmp_profile, monkeypatch, qapp):
    """``run(*answers, **window_attrs)`` runs the real Clear Cache on a stub
    window whose workers are idle (unless set), answering its questions with
    *answers* in turn (True for Yes). Returns the window and the fake box."""
    box = MagicMock()
    monkeypatch.setattr(main_window, "QMessageBox", box)
    monkeypatch.setattr(main_window, "AnimatedProgressDialog", MagicMock())

    def run(*answers, **attrs):
        replies = [box.StandardButton.Yes if a else box.StandardButton.No for a in answers]

        def answer(*args):
            assert replies, f"an unexpected question: {args[1]}"
            return replies.pop(0)

        box.question.side_effect = answer
        me = MagicMock(_p4k_worker=None, _forge_worker=None, _enhancements_worker=None,
                       _startup_sync_worker=object())
        for name, value in attrs.items():
            setattr(me, name, value)
        MainWindow.clear_cache(me)
        assert replies == [], "a question the test expected was not asked"
        return me, box

    return run


def _cached_files() -> list[Path]:
    """base.ini and one enhancement INI in the active channel's cache."""
    cache = AppSettings.get_cache_dir()
    files = [cache / "base.ini", cache / "ships_desc_enhancements.ini"]
    for f in files:
        f.write_text("k=v\n", encoding="utf-8")
    return files


def _dataforge_cache(leaf: Path) -> Path:
    """An extracted DataForge cache in *leaf*: its stamp and one record."""
    records = leaf / DATAFORGE_RECORDS_SUBPATH
    records.mkdir(parents=True)
    (records / "ship.xml").write_text("<ship/>", encoding="utf-8")
    (leaf / P4K_MTIME_STAMP).write_text("1", encoding="utf-8")
    return leaf


def _questions(box) -> list[str]:
    return [c.args[1] for c in box.question.call_args_list]


def _summary(box) -> str:
    [call] = box.information.call_args_list
    assert call.args[1] == tr("dialogs.cache_cleared_title")
    return call.args[2]


class TestTheDataForgeCacheInUse:
    def test_the_default_cache_is_offered_and_cleared(self, clear):
        """The reported case: before the fix the question never came."""
        files = _cached_files()
        leaf = _dataforge_cache(AppSettings.get_dataforge_cache_leaf())

        me, box = clear(True, True)

        assert _questions(box) == [_FILES_QUESTION, _DATAFORGE_QUESTION]
        assert box.question.call_args_list[1].args[2] == tr(
            "dialogs.clear_cache_dataforge_body", folder=str(leaf))
        assert not any(f.exists() for f in files)
        assert not leaf.exists()
        assert _summary(box) == tr("dialogs.cache_cleared_body", count=3)
        me.enhancements_tab.refresh_enhancements_status.assert_called_once_with()
        me.config_tab._refresh_p4k_status.assert_called_once_with()

    def test_a_cache_folder_override_is_the_one_cleared(self, clear, tmp_profile):
        default = _dataforge_cache(AppSettings.get_dataforge_cache_leaf())
        AppSettings.set_cache_dir(tmp_profile / "D" / "SC Cache")
        leaf = _dataforge_cache(AppSettings.get_dataforge_cache_leaf())
        assert leaf != default

        _me, box = clear(True)

        assert _questions(box) == [_DATAFORGE_QUESTION]
        assert not leaf.exists()
        assert (default / P4K_MTIME_STAMP).exists()

    def test_the_portable_builds_cache_is_the_one_cleared(self, clear, tmp_profile, monkeypatch):
        monkeypatch.setattr("src.utils.build_mode.IS_PORTABLE", True)
        monkeypatch.setattr(AppSettings, "_portable_data_dir",
                            staticmethod(lambda: tmp_profile / "portable" / "data"))
        leaf = _dataforge_cache(AppSettings.get_dataforge_cache_leaf())
        assert (tmp_profile / "portable" / "data" / "cache") in leaf.parents

        _me, box = clear(True)

        assert _questions(box) == [_DATAFORGE_QUESTION]
        assert not leaf.exists()

    def test_a_cache_folder_with_no_cache_in_it_is_not_offered(self, clear):
        files = _cached_files()
        leaf = AppSettings.get_dataforge_cache_leaf()
        leaf.mkdir(parents=True)

        _me, box = clear(True)

        assert _questions(box) == [_FILES_QUESTION]
        assert not any(f.exists() for f in files)
        assert leaf.is_dir()

    def test_records_without_the_stamp_are_offered(self, clear):
        """An extraction that ended before writing the stamp leaves records
        without one, which is when a clear is wanted most."""
        leaf = AppSettings.get_dataforge_cache_leaf()
        records = leaf / DATAFORGE_RECORDS_SUBPATH
        records.mkdir(parents=True)
        (records / "ship.xml").write_text("<ship/>", encoding="utf-8")

        _me, box = clear(True)

        assert _questions(box) == [_DATAFORGE_QUESTION]
        assert not leaf.exists()

    def test_the_old_leftover_is_left_to_the_queued_cleanup(self, clear):
        """Before the fix this was the only DataForge folder offered."""
        files = _cached_files()
        leftover = _dataforge_cache(AppSettings.get_cache_dir() / "dataforge")

        _me, box = clear(True)

        assert _questions(box) == [_FILES_QUESTION]
        assert not any(f.exists() for f in files)
        assert (leftover / P4K_MTIME_STAMP).exists()
        assert _summary(box) == tr("dialogs.cache_cleared_body", count=2)


class TestTheQuestions:
    def test_only_a_dataforge_cache_skips_the_file_question(self, clear):
        """It used to ask about an empty list of files first."""
        leaf = _dataforge_cache(AppSettings.get_dataforge_cache_leaf())
        _me, box = clear(True)
        assert _questions(box) == [_DATAFORGE_QUESTION]
        assert not leaf.exists()
        assert _summary(box) == tr("dialogs.cache_cleared_body", count=1)

    def test_no_to_the_only_question_changes_nothing(self, clear):
        """With no files to clear, the DataForge question is the only one. A
        No there changes nothing, just as No to the file question: no
        summary, and the table and the tabs left alone."""
        leaf = _dataforge_cache(AppSettings.get_dataforge_cache_leaf())
        me, box = clear(False)
        assert _questions(box) == [_DATAFORGE_QUESTION]
        assert (leaf / P4K_MTIME_STAMP).exists()
        box.information.assert_not_called()
        me._model.set_data_source.assert_not_called()
        me.config_tab._refresh_p4k_status.assert_not_called()
        me.enhancements_tab.refresh_enhancements_status.assert_not_called()

    def test_no_to_the_dataforge_question_keeps_it(self, clear):
        files = _cached_files()
        leaf = _dataforge_cache(AppSettings.get_dataforge_cache_leaf())
        _me, box = clear(True, False)
        assert not any(f.exists() for f in files)
        assert (leaf / P4K_MTIME_STAMP).exists()
        assert _summary(box) == tr("dialogs.cache_cleared_body", count=2)

    def test_no_to_the_file_question_clears_nothing(self, clear):
        files = _cached_files()
        leaf = _dataforge_cache(AppSettings.get_dataforge_cache_leaf())
        _me, box = clear(False)
        assert _questions(box) == [_FILES_QUESTION]
        assert all(f.exists() for f in files)
        assert (leaf / P4K_MTIME_STAMP).exists()
        box.information.assert_not_called()

    def test_the_file_question_lists_the_files(self, clear):
        _cached_files()
        _me, box = clear(False)
        assert box.question.call_args.args[2] == tr(
            "dialogs.clear_cache_files_body",
            files="  base.ini\n  ships_desc_enhancements.ini")

    def test_nothing_to_clear_says_so(self, clear):
        _me, box = clear()
        box.question.assert_not_called()
        box.information.assert_called_once()
        assert box.information.call_args.args[1:] == (
            tr("dialogs.cache_empty_title"), tr("dialogs.cache_empty_body"))


class TestADriveThatIsNotThere:
    def test_the_rest_clears_and_the_summary_names_the_folder(self, clear, caplog):
        AppSettings.set_cache_dir(missing_drive_folder())
        leaf = AppSettings.get_dataforge_cache_leaf()
        files = _cached_files()

        with caplog.at_level(logging.WARNING):
            _me, box = clear(True)

        assert _questions(box) == [_FILES_QUESTION]
        assert not any(f.exists() for f in files)
        assert _summary(box) == (
            tr("dialogs.cache_cleared_body", count=2) + "\n\n"
            + tr("dialogs.clear_cache_dataforge_unreachable", folder=str(leaf)))
        assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == [
            f"Clear Cache could not reach the DataForge cache folder {leaf}"]

    def test_with_nothing_else_to_clear_it_still_says_so(self, clear):
        AppSettings.set_cache_dir(missing_drive_folder())
        leaf = AppSettings.get_dataforge_cache_leaf()
        _me, box = clear()
        box.question.assert_not_called()
        assert box.information.call_args.args[1:] == (
            tr("dialogs.cache_empty_title"),
            tr("dialogs.cache_empty_body") + "\n\n"
            + tr("dialogs.clear_cache_dataforge_unreachable", folder=str(leaf)))


class TestWhileSomethingRuns:
    @pytest.mark.parametrize("worker", ["_p4k_worker", "_forge_worker", "_enhancements_worker"])
    def test_nothing_is_cleared_and_the_status_bar_says_why(self, clear, worker):
        """An extraction or a generation writes into these folders."""
        files = _cached_files()
        leaf = _dataforge_cache(AppSettings.get_dataforge_cache_leaf())

        me, box = clear(**{worker: object()})

        box.question.assert_not_called()
        box.information.assert_not_called()
        assert all(f.exists() for f in files)
        assert (leaf / P4K_MTIME_STAMP).exists()
        me.statusBar().showMessage.assert_called_once_with(tr("dialogs.clear_cache_busy"))


class TestAFailedDelete:
    def test_a_file_is_listed_and_logged_once_at_warning(self, clear, monkeypatch, caplog):
        """It used to be logged at ERROR, which opened the global error box
        on top of the summary. The other file is still deleted."""
        base, enhancements = _cached_files()
        error = PermissionError(13, "Access is denied", str(base))
        real_unlink = Path.unlink

        def unlink(path, *args, **kwargs):
            if path == base:
                raise error
            return real_unlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", unlink)
        with caplog.at_level(logging.INFO):
            _me, box = clear(True)

        assert _summary(box) == (
            tr("dialogs.cache_cleared_body", count=1) + "\n\n"
            + tr("dialogs.cache_cleared_failed", failures=f"base.ini: {error}"))
        assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []
        assert [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING] == [
            f"Clear Cache could not delete {base}: {error}"]
        assert base.exists()
        assert not enhancements.exists()

    def test_a_dataforge_cache_is_listed_and_logged_once_at_warning(
            self, clear, monkeypatch, caplog):
        """It used to be logged twice at ERROR, which opened the global
        error box on top of the summary."""
        _cached_files()
        leaf = _dataforge_cache(AppSettings.get_dataforge_cache_leaf())
        error = PermissionError(13, "Access is denied", str(leaf))

        def refuse(path, *args, **kwargs):
            raise error

        monkeypatch.setattr(pe, "robust_rmtree", refuse)
        with caplog.at_level(logging.INFO):
            _me, box = clear(True, True)

        assert _summary(box) == (
            tr("dialogs.cache_cleared_body", count=2) + "\n\n"
            + tr("dialogs.cache_cleared_failed", failures=f"{leaf}: {error}"))
        assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []
        assert [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING] == [
            f"Clear Cache could not delete the DataForge cache {leaf}: {error}"]
        assert (leaf / P4K_MTIME_STAMP).exists()


def _node(strings: dict, key: str) -> dict:
    node = strings
    for part in key.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    return node if isinstance(node, dict) else {}


def _placeholders(text: str) -> set[str]:
    return {field for _lit, field, _spec, _conv in string.Formatter().parse(text) if field}


class TestEveryLanguage:
    def test_each_text_is_there_with_its_fields(self):
        assert "english" in {ui.parent.name for ui in _UI_FILES}
        for ui_json in _UI_FILES:
            strings = json.loads(ui_json.read_text(encoding="utf-8"))
            for key, fields in _KEYS.items():
                text = _node(strings, key).get("ht") or _node(strings, key).get("at") or ""
                where = f"{ui_json.parent.name} {key}"
                assert text, where
                assert _placeholders(text) == fields, where
                if "folder" in fields:
                    lines = text.format(folder="E:\\SC Cache").split("\n")
                    assert "E:\\SC Cache" in lines, where

    def test_english_is_the_source_text_and_the_rest_are_ai_texts(self):
        for ui_json in _UI_FILES:
            strings = json.loads(ui_json.read_text(encoding="utf-8"))
            for key in _KEYS:
                node = _node(strings, key)
                if ui_json.parent.name == "english":
                    assert node["ht"] and node["at"] == "", key
                else:
                    assert node["ht"] == "" and node["at"], f"{ui_json.parent.name} {key}"

    def test_clear_cache_shows_no_text_of_its_own(self):
        """Every word Clear Cache shows comes through tr(): once the log
        lines, the tr() keys and the file patterns are set aside, no string
        in it holds a letter. Its question, progress labels and summary used
        to be English in every language."""
        tree = ast.parse(textwrap.dedent(inspect.getsource(MainWindow.clear_cache)))
        func = tree.body[0]
        skipped = set()
        for node in ast.walk(func):
            if isinstance(node, ast.Call):
                callee = ast.unparse(node.func)
                if callee.startswith("logger."):
                    skipped.update(id(n) for n in ast.walk(node))
                elif callee == "tr" and node.args:
                    skipped.add(id(node.args[0]))
                elif callee.endswith(".glob") and node.args:
                    skipped.add(id(node.args[0]))
        docstring = func.body[0].value
        texts = [n.value for n in ast.walk(func)
                 if isinstance(n, ast.Constant) and isinstance(n.value, str)
                 and id(n) not in skipped and n is not docstring]
        assert texts, "the scan found no strings at all"
        assert [t for t in texts if any(c.isalpha() for c in t)] == []
