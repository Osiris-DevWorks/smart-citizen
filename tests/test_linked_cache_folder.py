"""#491: nothing is ever deleted through a DataForge cache folder that is a link.

A user can turn the cache folder (``...\\cache\\dataforge``) into a junction
or a symbolic link by hand, usually to keep the cache on another drive.
``shutil.rmtree`` refuses a link and deletes nothing, and ``robust_rmtree``'s
error hook called the refusing ``os.path.islink`` again, which returned
instead of raising, so the refusal read as a delete that worked. Every
re-extract then met the old cache after unforge and failed with a raw
``FileExistsError``, and Clear Cache and the queued old-cache cleanup said a
folder was gone when nothing had been deleted.

Option B on the issue:

* ``linked_folder_target`` reads a link the way rmtree does (a symbolic link
  or a junction), without following it, so a link whose target is gone
  counts, and names the folder it leads to;
* ``robust_rmtree`` raises ``LinkedFolderError`` at once for a link, with
  nothing deleted and no retries, and still deletes a folder that only holds
  a link (the link goes, its target stays);
* ``extract_dataforge`` refuses a cache folder that is a link before anything
  runs, with ``CacheFolderIsLinkError`` (anticipated, so one box): no working
  folder, no tool, the old cache and the link as they were. A link higher up
  the path is not refused;
* Clear Cache and the queued cleanup report the link instead of a delete;
* ``extract.cache_folder_is_link`` in every language.

``MainWindow._run_dataforge_extraction`` (one box before any worker) and the
worker (one box from the real extraction) are in ``test_extraction_stop.py``.
Real junctions from ``tests/junction.py`` (which fails rather than skips
under CI), and a symbolic link where Windows lets this account make one
(also failing under CI, whose runner may). Windows only.
"""
from __future__ import annotations

import json
import logging
import os
import stat
import string
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import src.gui.main_window as main_window
import src.utils.pak_extractor as pe
from src.gui.main_window import MainWindow
from src.utils.i18n import tr
from src.utils.pak_extractor import DATAFORGE_RECORDS_SUBPATH, P4K_MTIME_STAMP, P4K_SIZE_STAMP
from src.utils.settings import AppSettings
from src.utils.win_paths import win_long_path
from tests.junction import make_junction

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(sys.platform != "win32", reason="junctions are Windows only"),
]

_LANGUAGES = Path(__file__).resolve().parent.parent / "languages"
_UI_FILES = sorted(_LANGUAGES.glob("*/ui.json"))
_KEY = "extract.cache_folder_is_link"
_NOT_THROUGH_A_LINK = "and nothing is deleted through a link"


def _fill(folder: Path) -> dict:
    """An old cache in *folder*: both stamps and one record. Returns each
    file with its content, to show later that nothing changed."""
    records = folder / DATAFORGE_RECORDS_SUBPATH
    records.mkdir(parents=True)
    files = {folder / P4K_MTIME_STAMP: "1700000000.0", folder / P4K_SIZE_STAMP: "123",
             records / "ship.xml": "<ship/>"}
    for path, text in files.items():
        path.write_text(text, encoding="utf-8")
    return files


def _unchanged(files: dict) -> bool:
    return all(path.read_text(encoding="utf-8") == text for path, text in files.items())


def _make_symlink(link: Path, target: Path) -> None:
    """Make *link* a symbolic link to the folder *target*. Windows lets an
    account make one only with Developer Mode or the privilege, so this
    skips where it refuses, except under CI (as ``make_junction`` does)."""
    target.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError as exc:
        reason = f"cannot make a symbolic link here: {exc}"
        if os.environ.get("CI"):
            pytest.fail(reason, pytrace=False)
        pytest.skip(reason)


def _gone_junction(link: Path, target: Path) -> None:
    """A junction to *target*, then *target* removed."""
    make_junction(link, target)
    target.rmdir()


# Each kind of link a cache folder can be: a junction, a symbolic link, and a
# junction whose target is gone (no old cache to keep there).
_LINKS = [
    pytest.param(make_junction, id="junction"),
    pytest.param(_make_symlink, id="symbolic-link"),
    pytest.param(_gone_junction, id="junction-to-nothing"),
]


def _link(make, link: Path, target: Path) -> dict:
    """*link* made by *make* to *target*, filled with an old cache first
    unless the target goes. Returns the old cache's files ({} if none)."""
    if make is _gone_junction:
        make(link, target)
        return {}
    target.mkdir(parents=True)
    files = _fill(target)
    make(link, target)
    return files


class TestLinkedFolderTarget:
    def test_a_junction_names_the_folder_it_leads_to(self, tmp_path):
        target = tmp_path / "D" / "SC Cache"
        make_junction(tmp_path / "link", target)
        assert pe.linked_folder_target(tmp_path / "link") == os.path.realpath(target)

    def test_the_long_path_prefix_is_read_and_not_given_back(self, tmp_path):
        """extract_dataforge hands it the cache folder with the prefix."""
        target = tmp_path / "target"
        make_junction(tmp_path / "link", target)
        assert pe.linked_folder_target(win_long_path(tmp_path / "link")) == \
            os.path.realpath(target)

    def test_a_symbolic_link_names_the_folder_it_leads_to(self, tmp_path):
        target = tmp_path / "target"
        _make_symlink(tmp_path / "link", target)
        assert pe.linked_folder_target(tmp_path / "link") == os.path.realpath(target)

    def test_a_symbolic_link_is_read_from_its_mode(self, monkeypatch):
        """The symbolic-link half of the rule, run where this account cannot
        make one (the real case above then skips): lstat's mode says it is a
        link."""
        link = os.stat_result((stat.S_IFLNK | 0o777, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        monkeypatch.setattr(pe.os, "lstat", lambda path: link)
        monkeypatch.setattr(pe.os.path, "realpath", lambda path: "D:\\SC Cache")
        assert pe.linked_folder_target("C:\\SC\\LIVE\\cache\\dataforge") == "D:\\SC Cache"

    def test_a_junction_whose_target_is_gone_still_counts(self, tmp_path):
        """It is read without following it. Path.exists() is False for it,
        which is how robust_rmtree used to return without a word."""
        _gone_junction(tmp_path / "link", tmp_path / "gone")
        assert not (tmp_path / "link").exists()
        assert pe.linked_folder_target(tmp_path / "link") == os.path.realpath(tmp_path / "gone")

    def test_a_target_realpath_cannot_read_is_named_by_the_link(self, tmp_path, monkeypatch):
        """realpath raises for an error it does not expect while it follows
        the link (a network that cannot be reached, WinError 1231): the
        link's own text names the target instead, and "" is left when even
        that cannot be read. It is still a link either way."""
        target = tmp_path / "target"
        make_junction(tmp_path / "link", target)

        def unreachable(path):
            raise OSError(None, "The network location cannot be reached", str(path), 1231)

        monkeypatch.setattr(pe.os.path, "realpath", unreachable)
        assert pe.linked_folder_target(tmp_path / "link") == str(target)
        monkeypatch.setattr(pe.os, "readlink", unreachable)
        assert pe.linked_folder_target(tmp_path / "link") == ""

    def test_a_junction_to_a_junction_names_the_last_folder(self, tmp_path):
        target = tmp_path / "target"
        make_junction(tmp_path / "middle", target)
        make_junction(tmp_path / "link", tmp_path / "middle")
        assert pe.linked_folder_target(tmp_path / "link") == os.path.realpath(target)

    def test_anything_else_is_not_a_link(self, tmp_path):
        """A folder, a file, a path that is not there, and a folder reached
        through a link (only the folder itself counts)."""
        target = tmp_path / "target"
        (target / "inside").mkdir(parents=True)
        (target / "file.txt").write_text("x", encoding="utf-8")
        make_junction(tmp_path / "link", target)
        for path in (target, target / "file.txt", tmp_path / "missing",
                     tmp_path / "link" / "inside"):
            assert pe.linked_folder_target(path) is None, path


class TestRobustRmtreeRefusesALink:
    @pytest.mark.parametrize("make", _LINKS)
    @pytest.mark.parametrize("spell", [Path, win_long_path], ids=["plain", "long-path-prefix"])
    def test_a_link_raises_at_once_and_nothing_is_deleted(self, tmp_path, monkeypatch,
                                                          make, spell):
        """It used to return as if the delete had worked, and a junction
        whose target is gone returned before rmtree saw it."""
        sleeps = []
        monkeypatch.setattr(pe.time, "sleep", sleeps.append)
        link, target = tmp_path / "dataforge", tmp_path / "elsewhere"
        files = _link(make, link, target)
        expected = pe.linked_folder_target(link)

        with pytest.raises(pe.LinkedFolderError) as raised:
            pe.robust_rmtree(spell(link))

        assert str(raised.value) == f"{link} is a link to {expected}, {_NOT_THROUGH_A_LINK}"
        assert isinstance(raised.value, OSError)
        assert sleeps == []   # never tried again
        assert pe.linked_folder_target(link) == expected
        assert _unchanged(files)

    @pytest.mark.parametrize("make", [
        pytest.param(make_junction, id="junction"),
        pytest.param(_make_symlink, id="symbolic-link"),
    ])
    def test_a_folder_holding_a_link_is_deleted_and_the_target_kept(self, tmp_path, make):
        """Only the folder handed in counts: a link inside it is removed as
        a link, as before, and what it leads to stays. A directory symbolic
        link too: Windows' DirEntry follows one when its stat is asked to
        follow, but never a junction, so the junction alone could not show
        that the threaded pass's stat does not follow (perf proposal).
        Where Windows refuses this account a symbolic link it skips, and
        under CI it fails, as the other symbolic link tests do."""
        target = tmp_path / "elsewhere"
        target.mkdir()
        files = _fill(target)
        holder = tmp_path / "holder"
        holder.mkdir()
        (holder / "file.txt").write_text("x", encoding="utf-8")
        make(holder / "inner", target)

        pe.robust_rmtree(holder)

        assert not os.path.lexists(holder)
        assert _unchanged(files)

    def test_the_threaded_pass_never_follows_a_symbolic_link(self, tmp_path, monkeypatch):
        """The same without the privilege a real symbolic link needs: the
        listing of the folder handed in also holds an entry that reads as
        os.scandir lists a directory symbolic link on Windows, a link by
        its own lstat and the folder it leads to when followed (its path
        leads there too, as listing the link does). The pass deletes the
        folder's own file and leaves the target's, which a walk that
        followed it would delete."""
        target = tmp_path / "elsewhere"
        target.mkdir()
        files = _fill(target)
        holder = tmp_path / "holder"
        holder.mkdir()
        (holder / "file.txt").write_text("x", encoding="utf-8")
        top = win_long_path(holder)
        real_scandir = os.scandir

        class _SymlinkEntry:
            name = "inner"
            path = win_long_path(target)

            def stat(self, *, follow_symlinks=True):
                if follow_symlinks:
                    return os.stat(self.path)
                return os.stat_result((stat.S_IFLNK | 0o777,) + (0,) * 9)

            def is_symlink(self):
                return True

            def is_junction(self):
                return False

            def is_dir(self, *, follow_symlinks=True):
                return follow_symlinks

            def is_file(self, *, follow_symlinks=True):
                return False

        class _Listing:
            def __init__(self, folder):
                self._real = real_scandir(folder)
                self._extra = [_SymlinkEntry()] if folder == top else []

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                self._real.close()

            def __iter__(self):
                yield from self._real
                yield from self._extra

        with monkeypatch.context() as listed:
            listed.setattr(os, "scandir", _Listing)
            pe._delete_files_first(top)

        assert not (holder / "file.txt").exists()
        assert _unchanged(files)

    def test_a_folder_that_is_not_there_is_still_nothing_to_do(self, tmp_path):
        pe.robust_rmtree(tmp_path / "missing")


@pytest.fixture
def tools(tmp_path, monkeypatch):
    """A DataForge extraction whose tools must not run: the tools folder,
    and a private %TEMP% to show no working folder was made there either.
    Its work would go beside the cache, however long tmp_path is."""
    folder = tmp_path / "tools"
    folder.mkdir()
    for name in ("unp4k.exe", "unforge.exe", "Data.p4k"):
        (folder / name).write_bytes(b"x")
    systemp = tmp_path / "systemp"
    systemp.mkdir()
    monkeypatch.setattr(pe.tempfile, "tempdir", str(systemp))
    monkeypatch.setattr(pe, "_drive_is_removable_or_network", lambda path: False)
    monkeypatch.setattr(pe, "is_onedrive_path", lambda path: False)
    monkeypatch.setattr(pe, "_MAX_SCRATCH_CHARS", 10_000)
    monkeypatch.setattr(pe, "_run_tool", _ToolRan.raise_it)
    return folder, systemp


class _ToolRan(Exception):
    """A tool was started: the run got past every check before it."""

    @staticmethod
    def raise_it(*args, **kwargs):
        raise _ToolRan()


def _extract(tools_folder: Path, leaf: Path):
    return pe.extract_dataforge(tools_folder / "Data.p4k", tools_folder / "unp4k.exe",
                                tools_folder / "unforge.exe", leaf)


class TestExtractionRefusesALinkedCacheFolder:
    @pytest.mark.parametrize("make", _LINKS)
    def test_it_is_refused_before_anything_runs(self, tmp_path, tools, caplog,
                                                english_ui, make):
        """Before the fix the run went on to unforge (here, the fake tool
        that raises), and with real tools failed after it."""
        tools_folder, systemp = tools
        leaf = tmp_path / "SC" / "LIVE" / "cache" / "dataforge"
        leaf.parent.mkdir(parents=True)
        files = _link(make, leaf, tmp_path / "D" / "SC Cache")
        target = pe.linked_folder_target(leaf)

        with caplog.at_level(logging.INFO, logger=pe.logger.name):
            with pytest.raises(pe.CacheFolderIsLinkError) as raised:
                _extract(tools_folder, leaf)

        error = raised.value
        assert (error.folder, error.target) == (str(leaf), target)
        assert str(error) == (
            f"The DataForge cache folder is a link to another folder:\n{leaf}\n\n"
            f"It leads to:\n{target}\n\n"
            "Smart Citizen does not delete anything through a link, so the extraction did "
            "not start and nothing was changed. Choose the folder it leads to as the "
            "DataForge cache folder in the Config tab, then try again.")
        assert isinstance(error, pe.ANTICIPATED_EXTRACTION_ERRORS)
        assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == [
            f"The DataForge cache folder {leaf} is a link to {target}; an extraction "
            "deletes nothing through a link, so it was refused"]
        assert _unchanged(files)
        assert pe.linked_folder_target(leaf) == target
        assert sorted(p.name for p in leaf.parent.iterdir()) == ["dataforge"]
        assert list(systemp.iterdir()) == []

    def test_a_link_above_the_cache_folder_is_not_refused(self, tmp_path, tools):
        """The cache folder itself decides: a link higher up (here the
        folder that holds it, which the default location never resolves)
        is an ordinary path to the wipe."""
        tools_folder, _systemp = tools
        (tmp_path / "SC").mkdir()
        make_junction(tmp_path / "SC" / "cache", tmp_path / "D" / "cache")
        leaf = tmp_path / "SC" / "cache" / "dataforge"
        leaf.mkdir()
        assert pe.linked_cache_folder_error(leaf) is None
        with pytest.raises(_ToolRan):
            _extract(tools_folder, leaf)


class TestClearCacheReportsALink:
    def test_a_linked_dataforge_folder_is_reported_not_deleted(self, qapp, tmp_profile,
                                                               monkeypatch):
        """The DataForge cache folder Clear Cache offers (the one in use,
        #479) as a junction: the summary lists it as not deleted. It used to
        count it among the deleted items with nothing deleted."""
        box = MagicMock()
        box.question.return_value = box.StandardButton.Yes
        monkeypatch.setattr(main_window, "QMessageBox", box)
        monkeypatch.setattr(main_window, "AnimatedProgressDialog", MagicMock())
        cache = AppSettings.get_cache_dir()
        (cache / "base.ini").write_text("k=v", encoding="utf-8")
        target = tmp_profile / "D" / "SC Cache"
        target.mkdir(parents=True)
        files = _fill(target)
        link = AppSettings.get_dataforge_cache_leaf()
        link.parent.mkdir(parents=True)
        make_junction(link, target)
        me = MagicMock(_p4k_worker=None, _forge_worker=None, _enhancements_worker=None)
        me._startup_sync_worker = object()   # no sync started

        MainWindow.clear_cache(me)

        summary = box.information.call_args.args[2]
        assert summary == (
            tr("dialogs.cache_cleared_body", count=1) + "\n\n"
            + tr("dialogs.cache_cleared_failed", failures=(
                f"{link}: {link} is a link to {os.path.realpath(target)}, "
                f"{_NOT_THROUGH_A_LINK}")))
        assert not (cache / "base.ini").exists()
        assert _unchanged(files)
        assert pe.linked_folder_target(link) == os.path.realpath(target)


class TestQueuedCleanupReportsALink:
    def test_a_queued_link_is_reported_not_deleted(self, tmp_profile, caplog):
        """A queued old cache folder that is a junction to a folder the
        cache in use has nothing to do with (so #486's guard lets it
        through). It used to log "Removed old DataForge cache" with nothing
        deleted."""
        target = tmp_profile / "D" / "old cache"
        target.mkdir(parents=True)
        files = _fill(target)
        queued = tmp_profile / "old cache"
        make_junction(queued, target)
        AppSettings.set_pending_cache_cleanup(str(queued))

        with caplog.at_level(logging.INFO, logger=main_window.logger.name):
            MainWindow._cleanup_pending_old_cache(MagicMock())

        logged = [(r.levelno, r.getMessage()) for r in caplog.records
                  if r.name == main_window.logger.name]
        assert logged == [(logging.WARNING,
                           f"Could not remove old DataForge cache at {queued}: {queued} is a "
                           f"link to {os.path.realpath(target)}, {_NOT_THROUGH_A_LINK}. Delete "
                           "it manually if you want to reclaim the disk space.")]
        assert not AppSettings.get_pending_cache_cleanup()
        assert _unchanged(files)
        assert pe.linked_folder_target(queued) == os.path.realpath(target)


def _node(strings: dict, key: str) -> dict:
    node = strings
    for part in key.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    return node if isinstance(node, dict) else {}


def _placeholders(text: str) -> set[str]:
    return {field for _lit, field, _spec, _conv in string.Formatter().parse(text) if field}


def _recorded_calls(monkeypatch, tmp_path, tools_folder) -> list[dict]:
    """The arguments of every tr() call for the key, from a real refusal."""
    calls = []
    real_tr = pe.tr

    def recording_tr(key, **kwargs):
        if key == _KEY:
            calls.append(kwargs)
        return real_tr(key, **kwargs)

    monkeypatch.setattr(pe, "tr", recording_tr)
    leaf = tmp_path / "SC" / "LIVE" / "cache" / "dataforge"
    leaf.parent.mkdir(parents=True)
    make_junction(leaf, tmp_path / "D" / "SC Cache")
    with pytest.raises(pe.CacheFolderIsLinkError):
        _extract(tools_folder, leaf)
    return calls


class TestEveryLanguage:
    def test_each_language_has_the_message_with_its_two_folders(self, monkeypatch, tmp_path,
                                                                 tools):
        """Each language has a value that keeps both placeholders, formats
        with the arguments a real refusal passes, and puts the folder and
        the folder it leads to each on a line of its own."""
        [kwargs] = _recorded_calls(monkeypatch, tmp_path, tools[0])
        assert set(kwargs) == {"folder", "target"}
        assert "english" in {ui_json.parent.name for ui_json in _UI_FILES}
        for ui_json in _UI_FILES:
            node = _node(json.loads(ui_json.read_text(encoding="utf-8")), _KEY)
            text = node.get("ht") or node.get("at") or ""
            language = ui_json.parent.name
            assert text, language
            assert _placeholders(text) == {"folder", "target"}, language
            lines = text.format(**kwargs).split("\n")
            assert kwargs["folder"] in lines and kwargs["target"] in lines, language

    def test_english_is_the_source_text_and_the_rest_are_ai_texts(self):
        """languages/TRANSLATIONS.md: English in ``ht``, every other
        language an AI text in ``at`` with ``ht`` empty."""
        for ui_json in _UI_FILES:
            node = _node(json.loads(ui_json.read_text(encoding="utf-8")), _KEY)
            if ui_json.parent.name == "english":
                assert node["ht"] and node["at"] == ""
            else:
                assert node["ht"] == "" and node["at"], ui_json.parent.name
