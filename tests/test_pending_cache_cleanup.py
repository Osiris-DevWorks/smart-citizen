"""#486: the queued old-cache cleanup must never delete a cache in use.

Changing the DataForge cache folder with "Re-extract and delete old" queues
the old folder (``AppSettings.set_pending_cache_cleanup``), and
``MainWindow._cleanup_pending_old_cache`` deletes it after the next
successful extraction. Pick folder B, let B's extraction fail, switch back to
A: A is still queued, and the next successful extraction into A deleted the
cache it had just built.

The cleanup now skips the delete (and still clears the queue) when the queued
folder is, sits inside or holds a cache folder under the current cache
location, for any channel. Two folders overlap when their normalized text
does (case, separators, a trailing separator, the long-path prefix) or their
resolved paths do (a junction, a symlink, a subst drive, an 8.3 short name).
A folder the check cannot resolve is kept as well. A really old folder
elsewhere is still deleted, and the check creates nothing on disk.

Windows only, skipped elsewhere: the other-case, forward-slash and long-path
prefix spellings, the junction cases (which fail under CI if no junction can
be made) and the 8.3 short name cases (which also skip where the volume makes
no short names).

The perf proposal: a queued folder that is not in use also has the working
folders a crash left beside it swept, in the background, since after a cache
folder change no extraction sweeps there.

MainWindow and ConfigTab run on stub selves, with a JsonSettings backend in
``tmp_path`` so nothing touches the registry. No widget is built, so the
session ``qapp`` is only needed by the tests that run the background delete
of a working folder beside the cleanup and that sweep (perf proposal), for
their queued finished slots.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import src.gui.config_tab as config_tab
import src.utils.pak_extractor as pe
from src.gui.config_tab import ConfigTab
from src.gui.main_window import (
    MainWindow,
    _cache_folder_overlapping,
    _folders_overlap,
    _normalized_folder,
    _resolved_folder,
)
from src.utils.json_settings import JsonSettings
from src.utils.pak_extractor import DATAFORGE_RECORDS_SUBPATH, P4K_MTIME_STAMP
from src.utils.settings import AppSettings
from src.utils.win_paths import win_long_path
from tests.event_loop import pump_until
from tests.junction import make_junction

pytestmark = pytest.mark.unit

_WINDOWS_ONLY = pytest.mark.skipif(
    sys.platform != "win32", reason="Windows path spelling (case, separators, long-path prefix)"
)
_JUNCTIONS = pytest.mark.skipif(sys.platform != "win32", reason="junctions are Windows only")
_SHORT_NAMES = pytest.mark.skipif(
    sys.platform != "win32", reason="8.3 short names are Windows only"
)
_SKIPPED = "Skipped the queued cache cleanup"

# The cache folder spelled as the queue may hold it. The cleanup wraps the
# queued text in Path first, which on Windows already drops a trailing
# separator and turns / into \, and the resolved half of the check reads every
# one of these as the cache folder too. So only a direct call on the raw text
# shows that the normalized text half gets each spelling right by itself.
_SPELLINGS = [
    pytest.param(str, id="as-stored"),
    pytest.param(lambda leaf: str(leaf).swapcase(), id="other-case", marks=_WINDOWS_ONLY),
    pytest.param(lambda leaf: str(leaf) + os.sep, id="trailing-separator"),
    pytest.param(lambda leaf: str(leaf).replace("\\", "/"), id="forward-slashes",
                 marks=_WINDOWS_ONLY),
    pytest.param(win_long_path, id="long-path-prefix", marks=_WINDOWS_ONLY),
]


@pytest.fixture
def channel(tmp_path, monkeypatch):
    """A clean settings store in tmp_path (no registry), registry-mode paths,
    and an active channel the test can change: ``channel["name"]``."""
    monkeypatch.setattr(AppSettings, "_backend", JsonSettings(tmp_path / "config.json"))
    monkeypatch.setattr("src.utils.build_mode.IS_PORTABLE", False)
    active = {"name": "LIVE"}
    monkeypatch.setattr(AppSettings, "get_active_channel", staticmethod(lambda: active["name"]))
    return active


@pytest.fixture
def rmtree_calls(monkeypatch):
    """Every robust_rmtree call the cleanup makes, still deleting for real."""
    real = pe.robust_rmtree
    calls = []

    def record(path, *args, **kwargs):
        calls.append(Path(path))
        return real(path, *args, **kwargs)

    monkeypatch.setattr(pe, "robust_rmtree", record)
    return calls


def _fill(folder: Path) -> Path:
    """Make *folder* a populated cache: the freshness stamp and one record.
    Returns the record file."""
    records = folder / DATAFORGE_RECORDS_SUBPATH
    records.mkdir(parents=True, exist_ok=True)
    (folder / P4K_MTIME_STAMP).write_text("1", encoding="utf-8")
    record = records / "ship.xml"
    record.write_text("<ship/>", encoding="utf-8")
    return record


def _use_cache_location(folder: Path) -> Path:
    """Point the cache setting at *folder* and return the active channel's
    cache folder under it (not created)."""
    AppSettings.set_cache_dir(str(folder))
    return AppSettings.get_dataforge_cache_leaf()


def _run_cleanup(queued) -> MagicMock:
    """Queue *queued* and run the real cleanup on a stub window. Returns the
    stub, whose background sweep is a mock."""
    AppSettings.set_pending_cache_cleanup(queued)
    me = MagicMock()
    MainWindow._cleanup_pending_old_cache(me)
    return me


def _skip_messages(caplog) -> list:
    return [r for r in caplog.records
            if r.name == "src.gui.main_window" and _SKIPPED in r.getMessage()]


class TestTheCacheInUseIsKept:
    @pytest.mark.parametrize("spell", _SPELLINGS)
    def test_each_spelling_is_the_cache_folder_as_text(self, channel, tmp_path, spell):
        """The check itself on the raw queued text, not the Path the cleanup
        makes of it: normalized, each spelling is the cache folder exactly,
        not only one inside the other."""
        leaf = _use_cache_location(tmp_path / "A")
        queued = spell(leaf)
        assert isinstance(queued, str)
        assert queued != str(leaf) or spell is str

        assert _normalized_folder(queued) == _normalized_folder(leaf)
        assert _cache_folder_overlapping(queued) == leaf

    @pytest.mark.parametrize("spell", _SPELLINGS)
    def test_the_cache_folder_itself_is_kept(self, channel, tmp_path, rmtree_calls, spell):
        leaf = _use_cache_location(tmp_path / "A")
        record = _fill(leaf)
        queued = spell(leaf)
        assert queued != str(leaf) or spell is str

        _run_cleanup(queued)

        assert record.read_text(encoding="utf-8") == "<ship/>"
        assert rmtree_calls == []
        assert AppSettings.get_pending_cache_cleanup() == ""

    def test_a_folder_inside_the_cache_is_kept(self, channel, tmp_path, rmtree_calls):
        leaf = _use_cache_location(tmp_path / "A")
        record = _fill(leaf)

        _run_cleanup(leaf / DATAFORGE_RECORDS_SUBPATH)

        assert record.exists()
        assert rmtree_calls == []
        assert AppSettings.get_pending_cache_cleanup() == ""

    @pytest.mark.parametrize("levels_up", [
        pytest.param(1, id="its-cache-folder"),
        pytest.param(2, id="its-channel-folder"),
        pytest.param(3, id="the-cache-location"),
    ])
    def test_a_folder_holding_the_cache_is_kept(self, channel, tmp_path, rmtree_calls, levels_up):
        leaf = _use_cache_location(tmp_path / "A")
        record = _fill(leaf)
        holder = leaf.parents[levels_up - 1]

        _run_cleanup(holder)

        assert record.exists()
        assert rmtree_calls == []
        assert AppSettings.get_pending_cache_cleanup() == ""

    def test_another_channels_cache_is_kept(self, channel, tmp_path, rmtree_calls):
        """Each channel's folder under the current location is that
        channel's cache in use, not only the active channel's."""
        _use_cache_location(tmp_path / "A")
        ptu = AppSettings.get_dataforge_cache_leaf("PTU")
        record = _fill(ptu)

        _run_cleanup(ptu)

        assert record.exists()
        assert rmtree_calls == []
        assert AppSettings.get_pending_cache_cleanup() == ""

    def test_a_skip_is_logged_at_info(self, channel, tmp_path, rmtree_calls, caplog):
        caplog.set_level(logging.DEBUG, logger="src.gui.main_window")
        leaf = _use_cache_location(tmp_path / "A")
        _fill(leaf)

        _run_cleanup(leaf)

        skips = _skip_messages(caplog)
        assert [r.levelno for r in skips] == [logging.INFO]
        assert str(leaf) in skips[0].getMessage()


# ── The same folder spelled two ways on disk ────────────────────────────────

def _short_name(path: Path) -> str:
    """*path*, which must exist, in its 8.3 short spelling from
    GetShortPathNameW. Skips where the volume makes no short names."""
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetShortPathNameW.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD)
    k32.GetShortPathNameW.restype = wintypes.DWORD
    buffer = ctypes.create_unicode_buffer(32768)
    if not k32.GetShortPathNameW(str(path), buffer, len(buffer)):
        raise ctypes.WinError(ctypes.get_last_error())
    if os.path.normcase(buffer.value) == os.path.normcase(str(path)):
        pytest.skip(f"8.3 short names are turned off on this volume: {path}")
    return buffer.value


def _check_the_alias_is_kept(queued, in_use: Path, rmtree_calls) -> None:
    """Fill the cache in use, show that *queued* is that folder on disk but
    not as text, run the cleanup on it, and check the cache is kept."""
    record = _fill(in_use)
    assert os.path.samefile(queued, in_use)
    # The normalized text half alone does not see it.
    assert not _folders_overlap(_normalized_folder(queued), _normalized_folder(in_use))

    _run_cleanup(str(queued))

    assert record.read_text(encoding="utf-8") == "<ship/>"
    assert rmtree_calls == []
    assert AppSettings.get_pending_cache_cleanup() == ""


class TestALinkToTheCacheIsKept:
    """The default location (%LOCALAPPDATA%) is never resolved and an override
    always is, so a queue made under one and the cache in use under the other
    can name one folder in two ways."""

    @_JUNCTIONS
    @pytest.mark.parametrize("through_the_link", [
        pytest.param("queued", id="the-queued-folder"),
        pytest.param("in-use", id="the-cache-in-use"),
    ])
    def test_a_junction_to_the_cache_is_kept(self, channel, tmp_path, monkeypatch,
                                             rmtree_calls, through_the_link):
        """%LOCALAPPDATA% reaches the cache location through a junction, and an
        override naming the same location is resolved to the junction's
        target. The queue holds one spelling, the cache in use is the other
        (Browse back to A, or Reset back to the default)."""
        link = tmp_path / "link_local"
        make_junction(link, tmp_path / "real_local")
        monkeypatch.setenv("LOCALAPPDATA", str(link))
        by_link = AppSettings.get_dataforge_cache_leaf()
        AppSettings.set_cache_dir(str(link / "Smart Citizen"))
        by_target = AppSettings.get_dataforge_cache_leaf()
        if through_the_link == "queued":
            queued, in_use = by_link, by_target
        else:
            AppSettings.set_cache_dir(None)
            queued, in_use = by_target, by_link
        assert AppSettings.get_dataforge_cache_leaf() == in_use

        _check_the_alias_is_kept(queued, in_use, rmtree_calls)

    @_SHORT_NAMES
    @pytest.mark.parametrize("short", [
        pytest.param("queued", id="the-queued-folder"),
        pytest.param("in-use", id="the-cache-in-use"),
    ])
    def test_an_8_3_short_name_of_the_cache_is_kept(self, channel, tmp_path, monkeypatch,
                                                    rmtree_calls, short):
        """The queued text or %LOCALAPPDATA% holds an 8.3 short name
        (LOCALA~1 for Local App Data) where the other has the long one."""
        location = tmp_path / "Local App Data"
        spelled_long = location / "Smart Citizen" / "LIVE" / "cache" / "dataforge"
        spelled_long.mkdir(parents=True)
        if short == "queued":
            monkeypatch.setenv("LOCALAPPDATA", str(location))
            in_use = AppSettings.get_dataforge_cache_leaf()
            queued = _short_name(in_use)
        else:
            monkeypatch.setenv("LOCALAPPDATA", _short_name(location))
            in_use = AppSettings.get_dataforge_cache_leaf()
            queued = spelled_long

        _check_the_alias_is_kept(queued, in_use, rmtree_calls)


class TestTheResolvedComparison:
    """The resolved half of the check by itself. A fake realpath reads
    ``tmp_path/alias`` as ``tmp_path/real``, so it needs no link and runs on
    every platform."""

    @pytest.fixture
    def alias(self, tmp_path, monkeypatch):
        alias, real = tmp_path / "alias", tmp_path / "real"
        realpath = os.path.realpath

        def fake(path, *args, **kwargs):
            text = os.fspath(path)
            if text == str(alias) or text.startswith(os.path.join(str(alias), "")):
                text = str(real) + text[len(str(alias)):]
            return realpath(text, *args, **kwargs)

        monkeypatch.setattr(os.path, "realpath", fake)
        return alias, real

    @pytest.mark.parametrize("relation", [
        pytest.param(lambda leaf: leaf, id="the-cache-folder"),
        pytest.param(lambda leaf: leaf / DATAFORGE_RECORDS_SUBPATH, id="inside-it"),
        pytest.param(lambda leaf: leaf.parents[2], id="holding-it"),
    ])
    def test_an_alias_overlaps_once_resolved(self, channel, alias, relation):
        link, real = alias
        leaf = _use_cache_location(real)
        # Spelled under the alias. leaf is resolved, so its location is the
        # base to cut from, not real (a short name in tmp_path would differ).
        queued = link / relation(leaf).relative_to(leaf.parents[2])
        assert not _folders_overlap(_normalized_folder(queued), _normalized_folder(leaf))

        assert _folders_overlap(_resolved_folder(queued), _resolved_folder(leaf))
        assert _cache_folder_overlapping(queued) == leaf
        assert not real.exists() and not link.exists()

    @pytest.mark.parametrize("queued", [
        pytest.param(("alias", "LIVE", "cache", "dataforge-old"), id="a-sibling-through-it"),
        pytest.param(("elsewhere", "LIVE", "cache", "dataforge"), id="another-location"),
    ])
    def test_a_folder_that_only_resolves_near_the_cache_does_not(self, channel, tmp_path,
                                                                 alias, queued):
        _use_cache_location(alias[1])

        assert _cache_folder_overlapping(tmp_path.joinpath(*queued)) is None


def _refusing_realpath(monkeypatch, refused: Path) -> None:
    """Make the resolved half of the check raise for anything under
    *refused*: non-strict realpath still raises on an error it does not
    expect."""
    realpath = os.path.realpath

    def refuse(path, *args, **kwargs):
        if os.fspath(path).startswith(str(refused)):
            raise OSError(f"cannot resolve {path}")
        return realpath(path, *args, **kwargs)

    monkeypatch.setattr(os.path, "realpath", refuse)


class TestAFolderTheCheckCannotResolve:
    def test_it_is_kept_and_the_skip_is_logged_at_warning(self, channel, tmp_path, monkeypatch,
                                                          rmtree_calls, caplog):
        """Non-strict realpath still raises on an error it does not expect.
        The cleanup then keeps the folder, rather than deleting what it could
        not check or stopping the post-extract flow, and clears the queue."""
        caplog.set_level(logging.INFO, logger="src.gui.main_window")
        live = _fill(_use_cache_location(tmp_path / "new"))
        old = tmp_path / "old" / "LIVE" / "cache" / "dataforge"
        record = _fill(old)
        _refusing_realpath(monkeypatch, tmp_path / "old")

        _run_cleanup(old)

        assert record.exists()
        assert live.exists()
        assert rmtree_calls == []
        assert AppSettings.get_pending_cache_cleanup() == ""
        skips = _skip_messages(caplog)
        assert [r.levelno for r in skips] == [logging.WARNING]
        assert str(old) in skips[0].getMessage()


class TestAnOldFolderIsStillDeleted:
    def test_a_really_old_folder_is_deleted(self, channel, tmp_path, rmtree_calls, caplog):
        caplog.set_level(logging.INFO, logger="src.gui.main_window")
        live = _fill(_use_cache_location(tmp_path / "new"))
        old = tmp_path / "old" / "LIVE" / "cache" / "dataforge"
        _fill(old)

        _run_cleanup(old)

        assert not old.exists()
        assert live.exists()
        assert rmtree_calls == [old]
        assert AppSettings.get_pending_cache_cleanup() == ""
        assert _skip_messages(caplog) == []

    @pytest.mark.parametrize("name", [
        pytest.param("dataforge-old", id="longer-name"),
        pytest.param("data", id="shorter-name"),
    ])
    def test_a_folder_only_named_like_the_cache_is_deleted(self, channel, tmp_path,
                                                           rmtree_calls, name):
        """A sibling whose name starts like the cache folder's, or that the
        cache folder's name starts like, is neither inside it nor holding it."""
        leaf = _use_cache_location(tmp_path / "A")
        live = _fill(leaf)
        old = leaf.with_name(name)
        _fill(old)

        _run_cleanup(old)

        assert not old.exists()
        assert live.exists()
        assert rmtree_calls == [old]


class TestAnAbsentQueuedFolder:
    def test_an_absent_queued_folder_only_clears_the_queue(self, channel, tmp_path,
                                                           rmtree_calls, caplog):
        caplog.set_level(logging.INFO, logger="src.gui.main_window")
        live = _fill(_use_cache_location(tmp_path / "new"))
        gone = tmp_path / "gone" / "LIVE" / "cache" / "dataforge"

        _run_cleanup(gone)

        assert AppSettings.get_pending_cache_cleanup() == ""
        assert rmtree_calls == []
        assert not (tmp_path / "gone").exists()
        assert live.exists()
        assert any("already absent" in r.getMessage() for r in caplog.records)


class TestTheCheckCreatesNothing:
    def test_deleting_an_old_folder_makes_no_cache_folder(self, channel, tmp_path,
                                                          rmtree_calls):
        _use_cache_location(tmp_path / "new")
        old = tmp_path / "old" / "LIVE" / "cache" / "dataforge"
        _fill(old)

        _run_cleanup(old)

        assert not old.exists()
        assert not (tmp_path / "new").exists()

    def test_a_skipped_cleanup_makes_no_cache_folder(self, channel, tmp_path, rmtree_calls):
        leaf = _use_cache_location(tmp_path / "new")

        _run_cleanup(leaf)

        assert not (tmp_path / "new").exists()
        assert AppSettings.get_pending_cache_cleanup() == ""

    def test_the_leaf_getter_is_the_cache_dir_getter_without_the_mkdir(
            self, channel, tmp_path):
        leaf = _use_cache_location(tmp_path / "A")
        assert not (tmp_path / "A").exists()
        ptu = AppSettings.get_dataforge_cache_leaf("PTU")
        assert ptu == leaf.parents[2] / "PTU" / "cache" / "dataforge"
        assert not (tmp_path / "A").exists()

        assert AppSettings.get_dataforge_cache_dir() == leaf
        assert leaf.is_dir()


# ── The issue's own scenario, end to end ────────────────────────────────────

def _prompt_answering(monkeypatch, answer: str) -> list:
    """Replace the Config tab's migration prompt with one that clicks
    *answer* ("delete", "keep" or "cancel"). Returns the prompts made."""
    made = []
    order = ("delete", "keep", "cancel")

    def make(*_args):
        box = MagicMock()
        buttons = [MagicMock(name=name) for name in order]
        box.addButton.side_effect = buttons
        box.clickedButton.return_value = buttons[order.index(answer)]
        made.append(box)
        return box

    monkeypatch.setattr(config_tab, "QMessageBox", MagicMock(side_effect=make))
    return made


def _successful_extraction() -> MagicMock:
    """Run the real extraction-finished slot for a successful run on a stub
    window whose cleanup is the real one. Returns the stub."""
    worker = MagicMock()
    me = MagicMock()
    me._forge_worker = worker
    me._close_committed = False
    me._cleanup_pending_old_cache = lambda: MainWindow._cleanup_pending_old_cache(me)
    MainWindow._on_dataforge_extract_finished(me, True, worker)
    return me


def _queue_a_then_switch_to_b_and_back(monkeypatch, folder_a: Path, folder_b: Path) -> Path:
    """Steps 1 to 3 of the issue through the real
    ConfigTab._maybe_apply_cache_change, on a stub self with a fake prompt.
    Returns A's cache folder, which is left queued for deletion."""
    AppSettings.set_cache_dir(str(folder_a))
    cache_a = AppSettings.get_dataforge_cache_leaf()
    prompts = _prompt_answering(monkeypatch, "delete")
    tab = MagicMock()

    # 1. Pick B and choose "Re-extract and delete old": A is queued.
    assert ConfigTab._maybe_apply_cache_change(tab, str(folder_b)) is True
    assert len(prompts) == 1
    assert AppSettings.get_pending_cache_cleanup() == str(cache_a)
    # 2. The extraction into B fails, so B never gets a .p4k_mtime stamp.
    assert not (AppSettings.get_dataforge_cache_leaf() / P4K_MTIME_STAMP).exists()
    # 3. Switch back to A: B has no stamp, so there is no prompt and
    #    nothing clears the queue.
    assert ConfigTab._maybe_apply_cache_change(tab, str(folder_a)) is True
    assert len(prompts) == 1
    assert AppSettings.get_dataforge_cache_leaf() == cache_a
    assert AppSettings.get_pending_cache_cleanup() == str(cache_a)
    return cache_a


class TestIssueScenario:
    def test_switching_back_after_a_failed_change_keeps_the_cache_and_clears_the_queue(
            self, channel, tmp_path, monkeypatch, rmtree_calls):
        record = _fill(_use_cache_location(tmp_path / "A"))
        _queue_a_then_switch_to_b_and_back(monkeypatch, tmp_path / "A", tmp_path / "B")

        # 4. The next extraction into A succeeds.
        me = _successful_extraction()

        assert record.read_text(encoding="utf-8") == "<ship/>"
        assert rmtree_calls == []
        assert AppSettings.get_pending_cache_cleanup() == ""
        me._run_enhancements_generation.assert_called_once()

    def test_a_channel_switch_before_the_successful_extraction_keeps_it_too(
            self, channel, tmp_path, monkeypatch, rmtree_calls):
        """The extraction back into A fails as well, the user switches to
        PTU, and PTU's extraction into A succeeds: A's LIVE cache stays."""
        record = _fill(_use_cache_location(tmp_path / "A"))
        _queue_a_then_switch_to_b_and_back(monkeypatch, tmp_path / "A", tmp_path / "B")
        channel["name"] = "PTU"
        _fill(AppSettings.get_dataforge_cache_leaf())

        _successful_extraction()

        assert record.read_text(encoding="utf-8") == "<ship/>"
        assert rmtree_calls == []
        assert AppSettings.get_pending_cache_cleanup() == ""


# ── Beside a working folder's background delete (perf proposal) ─────────────

def _finished_run_window(run_dir: Path, marker) -> tuple[MagicMock, MagicMock]:
    """A stub window, and the worker of a successful run that kept *run_dir*,
    with the real cleanup, the real background delete, the real sweep of
    leftovers and their finished slot."""
    worker = MagicMock()
    worker.take_working_folder.return_value = pe.WorkingFolder(run_dir, marker)
    me = MagicMock()
    me._forge_worker = worker
    me._close_committed = False
    me._working_folder_deleters = []
    me._cleanup_pending_old_cache = lambda: MainWindow._cleanup_pending_old_cache(me)
    me._delete_working_folder_in_background = (
        lambda folder: MainWindow._delete_working_folder_in_background(me, folder))
    me._sweep_working_folders_in_background = (
        lambda parent: MainWindow._sweep_working_folders_in_background(me, parent))
    me._on_working_folder_deleted = (
        lambda deleter: MainWindow._on_working_folder_deleted(me, deleter))
    return me, worker


class TestBesideTheBackgroundDelete:
    """A successful extraction's finished slot starts the delete of its
    working folder, the old cache set aside in it included, on a thread of
    its own just before it runs the queued cleanup, so the two run side by
    side. Neither touches the other's folder: the queued folder is an old
    cache folder, and one that holds the working folder holds the cache
    folder in use as well, so it is kept (#486)."""

    @pytest.mark.parametrize("queued", ["an old cache elsewhere", "the folder holding both"])
    def test_each_delete_keeps_to_its_own_folder(self, channel, tmp_path, qapp, queued):
        leaf = _use_cache_location(tmp_path / "new")
        record = _fill(leaf)
        run_dir, marker = pe._open_scratch(leaf.parent, pe.DATAFORGE_SCRATCH_PREFIX)
        set_aside = run_dir / pe._SET_ASIDE_CACHE_NAME / DATAFORGE_RECORDS_SUBPATH / "ship.xml"
        set_aside.parent.mkdir(parents=True)
        set_aside.write_text("<old ship/>", encoding="utf-8")
        old = tmp_path / "old" / "LIVE" / "cache" / "dataforge"
        if queued == "an old cache elsewhere":
            _fill(old)
            AppSettings.set_pending_cache_cleanup(old)
        else:
            AppSettings.set_pending_cache_cleanup(leaf.parent)
        me, worker = _finished_run_window(run_dir, marker)

        MainWindow._on_dataforge_extract_finished(me, True, worker)

        assert pump_until(lambda: me._working_folder_deleters == [])
        assert not run_dir.exists()
        assert record.read_text(encoding="utf-8") == "<ship/>"
        assert AppSettings.get_pending_cache_cleanup() == ""
        if queued == "an old cache elsewhere":
            assert not old.exists()
        else:
            assert leaf.parent.is_dir()
        me._run_enhancements_generation.assert_called_once_with()


class TestLeftoverWorkingFoldersBesideIt:
    """A crash or a kill during a successful run's background delete leaves
    its working folder beside the cache folder, with the old cache set aside
    in it (perf proposal). After a cache folder change no extraction sweeps
    beside the old cache folder any more, so the cleanup sweeps there, in the
    background: beside a queued folder it deletes or finds gone, never beside
    a cache in use, where the extraction that just ran swept itself, or a
    folder it could not compare, whose cleanup is skipped out of caution."""

    @pytest.mark.parametrize("there", [True, False], ids=["deleted", "already gone"])
    def test_beside_an_old_folder(self, channel, tmp_path, rmtree_calls, there):
        _fill(_use_cache_location(tmp_path / "new"))
        old = tmp_path / "old" / "LIVE" / "cache" / "dataforge"
        if there:
            _fill(old)
        me = _run_cleanup(old)
        me._sweep_working_folders_in_background.assert_called_once_with(old.parent)

    def test_not_beside_a_cache_in_use(self, channel, tmp_path, rmtree_calls):
        leaf = _use_cache_location(tmp_path / "A")
        _fill(leaf)
        me = _run_cleanup(leaf)
        me._sweep_working_folders_in_background.assert_not_called()

    def test_not_beside_a_folder_the_check_cannot_resolve(self, channel, tmp_path, monkeypatch,
                                                          rmtree_calls):
        _fill(_use_cache_location(tmp_path / "new"))
        old = tmp_path / "old" / "LIVE" / "cache" / "dataforge"
        _fill(old)
        _refusing_realpath(monkeypatch, tmp_path / "old")
        me = _run_cleanup(old)
        me._sweep_working_folders_in_background.assert_not_called()

    def test_on_real_threads(self, channel, tmp_path, qapp, monkeypatch):
        """The case the review found, end to end: the cache folder was moved
        and a crashed run's working folder still sits beside the old one.
        The real finished slot deletes this run's working folder and the old
        cache, and the sweep then takes the crashed run's folder on a thread
        of its own, once this run's delete is over, and leaves one whose
        marker a live run in another window holds."""
        leaf = _use_cache_location(tmp_path / "new")
        record = _fill(leaf)
        run_dir, marker = pe._open_scratch(leaf.parent, pe.DATAFORGE_SCRATCH_PREFIX)
        old = tmp_path / "old" / "LIVE" / "cache" / "dataforge"
        _fill(old)
        crashed, crashed_marker = pe._open_scratch(old.parent, pe.DATAFORGE_SCRATCH_PREFIX)
        set_aside = crashed / pe._SET_ASIDE_CACHE_NAME / DATAFORGE_RECORDS_SUBPATH / "ship.xml"
        set_aside.parent.mkdir(parents=True)
        set_aside.write_text("<old ship/>", encoding="utf-8")
        crashed_marker.close()
        held, held_marker = pe._open_scratch(old.parent, pe.DATAFORGE_SCRATCH_PREFIX)
        held_dcb = held / "Data" / "Game2.dcb"
        held_dcb.parent.mkdir()
        held_dcb.write_bytes(b"dcb")
        AppSettings.set_pending_cache_cleanup(old)
        sweeps = []
        real_sweep = pe._sweep_stale_scratch

        def record_sweep(parent, prefix, should_cancel=None):
            sweeps.append((Path(parent), prefix, threading.get_ident(), run_dir.exists()))
            return real_sweep(parent, prefix, should_cancel=should_cancel)

        monkeypatch.setattr(pe, "_sweep_stale_scratch", record_sweep)
        me, worker = _finished_run_window(run_dir, marker)
        try:
            MainWindow._on_dataforge_extract_finished(me, True, worker)

            assert pump_until(lambda: me._working_folder_deleters == [])
            assert not crashed.exists()
            assert held_dcb.read_bytes() == b"dcb"   # a folder whose marker is held is left whole
            assert not old.exists() and not run_dir.exists()
            assert record.read_text(encoding="utf-8") == "<ship/>"
            assert [(parent, prefix) for parent, prefix, _thread, _run in sweeps] == [
                (old.parent, pe.DATAFORGE_SCRATCH_PREFIX)]
            assert sweeps[0][2] != threading.get_ident()   # never on the GUI thread
            assert sweeps[0][3] is False   # after this run's own delete was over
        finally:
            held_marker.close()
