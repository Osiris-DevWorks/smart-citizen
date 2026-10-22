"""base.ini freshness follows Data.p4k's size, not its modified time (perf
proposal).

The RSI launcher's file verification moves Data.p4k's modified time on an
ordinary game launch without changing a byte (#209, which moved the
DataForge cache's freshness to a size stamp for that reason). base.ini kept
the old rule, Data.p4k newer than base.ini, so after nothing more than
playing the next start, channel switch or data folder change asked to
extract global.ini again (20 to 26 s and up to ~9 GB of memory), and the
Config tab's Extract button turned red.

``pak_extractor.base_ini_is_fresh`` now reads ``BASE_INI_STAMP`` beside
base.ini: the size of the Data.p4k it was extracted from, which
``extract_global_ini`` records (read before unp4k runs), and base.ini's own
size, so a stamp left beside another base.ini counts for nothing. With no
usable stamp, the old modified-time rule decides, and a base.ini it reads as
fresh gets its stamp then, so an upgrade asks for nothing the old rule did
not, and reads a patch as the old rule reads it at that check.
``extract_global_ini`` removes the old stamp once the new base.ini is in
place, so a new one that cannot be written leaves none, and a failed copy
keeps it. Both callers use it:
``MainWindow._check_p4k_freshness`` (startup, a channel switch and a data
folder change) and ``ConfigTab._refresh_p4k_status`` (the Extract button).
The windows are stub
selves with ``AppSettings`` and ``QMessageBox`` faked; the files are real,
under ``tmp_path``, with modified times set by hand.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import src.gui.config_tab as config_tab
import src.gui.main_window as main_window
import src.utils.pak_extractor as pe
from src.gui.config_tab import ConfigTab
from src.gui.main_window import MainWindow
from src.utils.i18n import tr
from src.utils.onedrive import _ONEDRIVE_ENV_VARS

pytestmark = pytest.mark.unit

# Modified times, set by hand: Data.p4k as a game patch left it, base.ini
# extracted from it afterwards, and Data.p4k after a later game launch whose
# file check moved its modified time without changing a byte. The launch is
# in the future, so it is also later than a base.ini an extraction in the
# test writes now.
_PATCHED = 1_600_000_000
_EXTRACTED = 1_700_000_000
_LAUNCHED = 2_000_000_000
# Data.p4k's size before and after the patch a test applies.
_P4K_SIZE = 4096
_PATCH_BYTES = 512


class _Install:
    """A Data.p4k, an unp4k beside it and the channel's cache folder, the
    way the window's checks find them."""

    def __init__(self, root: Path):
        self.p4k = root / "StarCitizen" / "LIVE" / "Data.p4k"
        self.unp4k = root / "tools" / "unp4k.exe"
        self.cache = root / "data" / "LIVE" / "cache"
        self.base_ini = self.cache / "base.ini"
        self.stamp = self.cache / pe.BASE_INI_STAMP
        for folder in (self.p4k.parent, self.unp4k.parent, self.cache):
            folder.mkdir(parents=True)
        self.p4k.write_bytes(b"p" * _P4K_SIZE)
        os.utime(self.p4k, (_PATCHED, _PATCHED))
        self.unp4k.write_bytes(b"x")

    def extract(self, *, stamp: bool = True, text: str = "Frontend_PU_Version=4.3\n") -> None:
        """base.ini as an extraction leaves it, with its stamp, or without
        for a base.ini extracted before the stamp existed."""
        self.base_ini.write_text(text, encoding="utf-8")
        if stamp:
            pe._write_base_ini_stamp(self.base_ini, self.p4k.stat().st_size)
        os.utime(self.base_ini, (_EXTRACTED, _EXTRACTED))

    def launch_game(self) -> None:
        """The launcher's file check on a game launch: a new modified time,
        the same bytes."""
        os.utime(self.p4k, (_LAUNCHED, _LAUNCHED))

    def patch_game(self, mtime: float = _LAUNCHED) -> None:
        """A game patch: Data.p4k's size changes. *mtime* older than base.ini
        shows the size alone decides."""
        with self.p4k.open("ab") as p4k:
            p4k.write(b"q" * _PATCH_BYTES)
        os.utime(self.p4k, (mtime, mtime))

    def fresh(self) -> bool:
        return pe.base_ini_is_fresh(self.p4k, self.base_ini)

    def settings(self) -> MagicMock:
        """AppSettings as the window's checks read it."""
        settings = MagicMock()
        settings.get_unp4k_exe_path.return_value = self.unp4k
        settings.get_p4k_path.return_value = self.p4k
        settings.get_cache_dir.return_value = self.cache
        return settings


@pytest.fixture
def install(tmp_path):
    return _Install(tmp_path)


def _stamp_text(install: _Install) -> str:
    return install.stamp.read_text(encoding="utf-8")


def _recorded(install: _Install) -> str:
    """The stamp that records base.ini as taken from Data.p4k as it is now."""
    return f"{install.p4k.stat().st_size} {install.base_ini.stat().st_size}"


# ── the rule ───────────────────────────────────────────────────────────────

class TestBaseIniIsFresh:
    def test_a_game_launch_alone_keeps_it_fresh(self, install):
        install.extract()
        install.launch_game()
        assert install.p4k.stat().st_mtime > install.base_ini.stat().st_mtime
        assert install.fresh() is True

    @pytest.mark.parametrize("mtime", [_PATCHED, _LAUNCHED], ids=["older", "newer"])
    def test_a_game_patch_makes_it_stale(self, install, mtime):
        """Whatever Data.p4k's modified time says: the older one is a patch
        the old rule would have missed."""
        install.extract()
        install.patch_game(mtime)
        assert install.fresh() is False

    def test_a_stamp_written_for_another_base_ini_counts_for_nothing(self, install):
        """A data folder change copies a file only where the new folder has
        none, so the old folder's stamp can land beside an older base.ini
        there. Its Data.p4k size matches, but it does not describe this
        base.ini, so the old rule decides: Data.p4k is newer, so stale."""
        install.extract()
        stamp = _stamp_text(install)
        install.extract(stamp=False, text="Frontend_PU_Version=4.2.1\n")
        os.utime(install.base_ini, (_PATCHED - 1, _PATCHED - 1))
        assert install.fresh() is False
        assert _stamp_text(install) == stamp

    @pytest.mark.parametrize("content", [
        b"", b"4096", b"4096 23 1", b"4096 twenty", b"\xff\xfe\x00 1",
    ], ids=["empty", "one-number", "three-numbers", "not-a-number", "not-text"])
    def test_an_unreadable_stamp_falls_back_to_the_modified_times(self, install, content):
        install.extract(stamp=False)
        install.stamp.write_bytes(content)
        install.launch_game()
        assert install.fresh() is False
        assert install.stamp.read_bytes() == content

    def test_missing_files_read_stale(self, install):
        assert install.fresh() is False            # no base.ini
        install.extract()
        install.p4k.unlink()
        assert install.fresh() is False            # no Data.p4k


class TestUpgradeFromABaseIniWithNoStamp:
    """A base.ini extracted before the stamp existed has only its modified
    time, so the old rule decides until it has a stamp."""

    def test_one_newer_than_data_p4k_reads_fresh_and_gets_its_stamp(self, install):
        install.extract(stamp=False)
        assert install.fresh() is True
        assert _stamp_text(install) == _recorded(install)
        # The next game launch then needs no extraction first...
        install.launch_game()
        assert install.fresh() is True
        # ...while a patch still reads as one.
        install.patch_game()
        assert install.fresh() is False

    def test_one_older_than_data_p4k_still_asks(self, install):
        """A launch or a patch: nothing tells them apart, and a missed patch
        costs more than one extraction, so it reads stale as before, and no
        stamp is made up for it."""
        install.extract(stamp=False)
        install.launch_game()
        assert install.fresh() is False
        assert not install.stamp.exists()


# ── the extraction records the size ────────────────────────────────────────

class _FakeUnp4k:
    """Stands in for _run_tool on the global.ini extraction: writes the
    English global.ini where unp4k does, and can grow Data.p4k meanwhile."""

    def __init__(self, grow: Path | None = None):
        self.grow = grow

    def __call__(self, args, *, cwd, timeout, should_cancel=None):
        extracted = Path(cwd) / pe._GLOBAL_INI_RELATIVE
        extracted.parent.mkdir(parents=True)
        extracted.write_text("Frontend_PU_Version=4.3\n", encoding="utf-8")
        if self.grow is not None:
            with self.grow.open("ab") as p4k:
                p4k.write(b"q" * _PATCH_BYTES)
        return subprocess.CompletedProcess(args, 0, "", "")


@pytest.fixture
def extraction(install, tmp_path, monkeypatch):
    """extract_global_ini with a fake unp4k, beside a DataForge cache folder
    under tmp_path, with a private %TEMP% and no OneDrive or drive probe."""
    systemp = tmp_path / "systemp"
    systemp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(systemp))
    for var in _ONEDRIVE_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(pe, "_drive_is_removable_or_network", lambda path: False)
    leaf = tmp_path / "LocalAppData" / "LIVE" / "cache" / "dataforge"
    leaf.parent.mkdir(parents=True)

    def run(fake: _FakeUnp4k) -> bool:
        monkeypatch.setattr(pe, "_run_tool", fake)
        return pe.extract_global_ini(install.p4k, install.base_ini, install.unp4k,
                                     scratch_near=leaf)

    return run


class TestExtractionRecordsTheSize:
    def test_a_launch_after_an_extraction_needs_no_other(self, install, extraction):
        assert extraction(_FakeUnp4k()) is True
        assert _stamp_text(install) == f"{_P4K_SIZE} {install.base_ini.stat().st_size}"
        install.launch_game()
        assert install.fresh() is True
        install.patch_game()
        assert install.fresh() is False

    def test_the_size_is_read_before_unp4k_runs(self, install, extraction):
        """A Data.p4k that changes while unp4k reads it reads as changed
        afterwards: the global.ini may be the old one's."""
        assert extraction(_FakeUnp4k(grow=install.p4k)) is True
        assert install.p4k.stat().st_size == _P4K_SIZE + _PATCH_BYTES
        assert install.fresh() is False

    def test_a_stamp_that_cannot_be_written_fails_nothing(self, install, extraction, caplog):
        """A folder in the stamp's place can be neither removed nor written
        over: each is logged at WARNING, and the extraction succeeds."""
        install.stamp.mkdir()   # Windows refuses to write a file there
        with caplog.at_level(logging.INFO):
            assert extraction(_FakeUnp4k()) is True
        assert install.base_ini.read_text(encoding="utf-8") == "Frontend_PU_Version=4.3\n"
        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        removal = f"Could not remove the old {pe.BASE_INI_STAMP}"
        assert [w for w in warnings if w.startswith(removal)]
        assert [w for w in warnings if w.startswith("Could not record Data.p4k's size beside")]
        assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []

    def test_a_stamp_that_cannot_be_replaced_leaves_none(
        self, install, extraction, monkeypatch, caplog
    ):
        """The old stamp goes once the new base.ini is in place, so a new one that
        cannot be written (here the drive is full) leaves no stamp, and the
        modified times decide. Kept, the old stamp spoke for the new base.ini
        too, the two being the same size after a patch that left global.ini
        as it was, so base.ini read stale straight after every extraction."""
        install.extract(text="Frontend_PU_Version=4.3\n")
        install.patch_game(_PATCHED)
        assert install.fresh() is False
        real_write_text = Path.write_text

        def write_text(path, *args, **kwargs):
            if path.name == pe.BASE_INI_STAMP:
                raise OSError(28, "There is not enough space on the disk", str(path))
            return real_write_text(path, *args, **kwargs)

        with monkeypatch.context() as full:
            full.setattr(Path, "write_text", write_text)
            with caplog.at_level(logging.WARNING, logger=pe.logger.name):
                assert extraction(_FakeUnp4k()) is True
        [warning] = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert warning.startswith(f"Could not record Data.p4k's size beside {install.base_ini}")
        assert not install.stamp.exists()
        # base.ini is newer than the patched Data.p4k, so it is fresh, and
        # gets the stamp the extraction could not write.
        assert install.fresh() is True
        assert _stamp_text(install) == _recorded(install)

    def test_a_failed_copy_keeps_the_old_stamp(self, install, extraction, monkeypatch):
        """The old stamp goes only once the new base.ini is in place. Gone
        before a copy that failed (base.ini read-only, or held by another
        program), it left the old base.ini with no stamp, and after a patch
        that left Data.p4k's modified time older than base.ini's the
        modified times read it fresh and stamped the patched size on it, so
        it read fresh until the next patch."""
        install.extract(text="Frontend_PU_Version=4.3\n")
        install.patch_game(_PATCHED)
        assert install.fresh() is False
        before = _stamp_text(install)

        def held(src, dst, *args, **kwargs):
            raise PermissionError(32, "The process cannot access the file", dst)

        with monkeypatch.context() as copy_fails:
            copy_fails.setattr(shutil, "copy2", held)
            with pytest.raises(PermissionError):
                extraction(_FakeUnp4k())
        assert _stamp_text(install) == before
        assert install.fresh() is False


# ── the callers ────────────────────────────────────────────────────────────

def _window() -> MagicMock:
    """A stub MainWindow whose freshness check is the real one."""
    me = MagicMock()
    me._close_committed = False
    me._p4k_worker = None
    me._after_unfinished_p4k_extraction = None
    me._startup_sync_worker = None
    me._startup_progress = None
    me._run_p4k_extraction.return_value = True
    me._check_p4k_freshness.side_effect = (
        lambda if_unfinished=None: MainWindow._check_p4k_freshness(me, if_unfinished=if_unfinished)
    )
    return me


# Each caller of _check_p4k_freshness, and what it does once no extraction is
# pending: startup loads the strings, a channel switch and a data folder
# change reload.
_CALLERS = {
    "startup": (lambda me: MainWindow._on_startup_sync_finished(me),
                "_finish_startup_load", ()),
    "channel-switch": (lambda me: MainWindow._on_channel_changed(me, "PTU"),
                       "_reload_after_channel_switch", ("PTU",)),
    "data-folder-change": (lambda me: MainWindow._on_data_dir_changed(me, "E:/SC data"),
                           "_reload_after_data_dir_change", ("E:/SC data",)),
}


@pytest.fixture
def window(install, monkeypatch):
    """A stub window over *install*, with a QMessageBox that answers Yes."""
    monkeypatch.setattr(main_window, "AppSettings", install.settings())
    box = MagicMock()
    box.StandardButton = main_window.QMessageBox.StandardButton
    box.question.return_value = box.StandardButton.Yes
    monkeypatch.setattr(main_window, "QMessageBox", box)
    return _window(), box


class TestCallers:
    @pytest.mark.parametrize("caller", _CALLERS)
    def test_a_game_launch_asks_nothing(self, install, window, caller):
        install.extract()
        install.launch_game()
        me, box = window
        run, carry_on, args = _CALLERS[caller]
        run(me)
        box.question.assert_not_called()
        me._run_p4k_extraction.assert_not_called()
        getattr(me, carry_on).assert_called_once_with(*args)

    @pytest.mark.parametrize("caller", _CALLERS)
    def test_a_game_patch_still_asks_and_yes_extracts(self, install, window, caller):
        """Data.p4k's modified time older than base.ini: the old rule would
        not have asked."""
        install.extract()
        install.patch_game(_PATCHED)
        me, box = window
        run, carry_on, args = _CALLERS[caller]
        run(me)
        box.question.assert_called_once()
        assert box.question.call_args.args[2] == tr("extract.p4k_prompt_p4k_newer")
        me._run_p4k_extraction.assert_called_once_with()
        getattr(me, carry_on).assert_not_called()   # the extraction reloads
        assert me._after_unfinished_p4k_extraction is not None

    def test_an_upgraded_base_ini_is_stamped_at_startup_and_a_launch_asks_nothing(
        self, install, window
    ):
        """The upgrade end to end: startup reads a base.ini with no stamp by
        the old rule, which says fresh, and stamps it, so the channel switch
        after the next game launch asks nothing."""
        install.extract(stamp=False)
        me, box = window
        MainWindow._on_startup_sync_finished(me)
        assert _stamp_text(install) == _recorded(install)
        install.launch_game()
        MainWindow._on_channel_changed(me, "LIVE")
        box.question.assert_not_called()
        me._reload_after_channel_switch.assert_called_once_with("LIVE")


class TestConfigTabExtractButton:
    """The Config tab's Extract button turns red when base.ini needs
    extracting again, by the same rule as the prompt."""

    @pytest.fixture
    def refresh(self, install, monkeypatch):
        monkeypatch.setattr(config_tab, "AppSettings", install.settings())

        def run() -> bool:
            me = MagicMock()
            ConfigTab._refresh_p4k_status(me)
            [(needs_update,), _] = me._set_extract_btn_needs_update.call_args
            return needs_update

        return run

    def test_a_game_launch_leaves_it_alone(self, install, refresh):
        install.extract()
        install.launch_game()
        assert refresh() is False

    def test_a_game_patch_turns_it_red(self, install, refresh):
        install.extract()
        install.patch_game(_PATCHED)
        assert refresh() is True
