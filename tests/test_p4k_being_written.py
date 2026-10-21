"""Extraction refuses a Data.p4k the RSI Launcher is still writing (#516).

The launcher does not always lock the archive against readers while it
patches, and unp4k then reads a half-written archive and crashes inside
SharpZipLib's ReadEntries. Both extractions check first, before any tool
runs: another program holding Data.p4k open for writing, or a modified time
in the last two minutes, raises P4kLockedError with the "wait for the
launcher" message. Qt-free.
"""

import logging
import os
import sys
import time

import pytest

import src.utils.pak_extractor as pe
from src.utils.i18n import set_language, tr

WINDOW = 120


@pytest.fixture(autouse=True)
def _english_and_real_window(monkeypatch):
    # conftest sets the window to 0 for the session; these tests use the real one.
    set_language("english")
    monkeypatch.setattr(pe, "_P4K_RECENT_WRITE_SECONDS", WINDOW)


@pytest.fixture
def tools(tmp_path):
    folder = tmp_path / "tools"
    folder.mkdir()
    for name in ("unp4k.exe", "unforge.exe", "Data.p4k"):
        (folder / name).write_bytes(b"x")
    return folder


def _age(path, seconds):
    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))


def _no_tool(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a tool ran on a Data.p4k that is being written")
    monkeypatch.setattr(pe, "_run_tool", refuse)
    monkeypatch.setattr(pe, "_begin_scratch", refuse)


class TestChangedRecently:
    def test_just_written_counts(self, tools):
        assert pe._p4k_changed_recently(tools / "Data.p4k")

    def test_inside_the_window_counts(self, tools):
        _age(tools / "Data.p4k", WINDOW - 10)
        assert pe._p4k_changed_recently(tools / "Data.p4k")

    def test_older_than_the_window_does_not(self, tools):
        _age(tools / "Data.p4k", WINDOW + 10)
        assert not pe._p4k_changed_recently(tools / "Data.p4k")

    def test_a_time_in_the_future_does_not(self, tools):
        _age(tools / "Data.p4k", -3600)
        assert not pe._p4k_changed_recently(tools / "Data.p4k")

    def test_a_missing_file_does_not(self, tmp_path):
        assert not pe._p4k_changed_recently(tmp_path / "Data.p4k")


class TestHasWriter:
    def test_false_off_windows(self, tools, monkeypatch):
        monkeypatch.setattr(pe.sys, "platform", "linux")
        assert not pe._p4k_has_writer(tools / "Data.p4k")

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows share modes")
    def test_no_other_handle(self, tools):
        assert not pe._p4k_has_writer(tools / "Data.p4k")

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows share modes")
    def test_a_handle_open_for_writing(self, tools):
        with open(tools / "Data.p4k", "r+b"):
            assert pe._p4k_has_writer(tools / "Data.p4k")
        assert not pe._p4k_has_writer(tools / "Data.p4k")

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows share modes")
    def test_a_reader_is_not_a_writer(self, tools):
        """The game and an idle launcher only read the archive."""
        with open(tools / "Data.p4k", "rb"):
            assert not pe._p4k_has_writer(tools / "Data.p4k")

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows share modes")
    def test_a_missing_file_is_left_to_the_extraction(self, tmp_path):
        assert not pe._p4k_has_writer(tmp_path / "Data.p4k")


class TestGate:
    def test_quiet_archive_passes(self, tools):
        _age(tools / "Data.p4k", WINDOW + 10)
        pe._refuse_if_p4k_being_written(tools / "Data.p4k")

    def test_writer_is_refused_with_the_locked_message(self, tools, monkeypatch):
        _age(tools / "Data.p4k", WINDOW + 10)
        monkeypatch.setattr(pe, "_p4k_has_writer", lambda path: True)
        with pytest.raises(pe.P4kLockedError) as exc:
            pe._refuse_if_p4k_being_written(tools / "Data.p4k")
        assert str(exc.value) == tr("extract.p4k_locked")

    def test_logs_at_warning_not_error(self, tools, caplog):
        """ERROR would open the global error dialog on top of the box the
        worker's error signal opens, as for the locked case."""
        with caplog.at_level(logging.DEBUG, logger=pe.logger.name):
            with pytest.raises(pe.P4kLockedError):
                pe._refuse_if_p4k_being_written(tools / "Data.p4k")
        assert any(r.levelno == logging.WARNING and "Data.p4k" in r.getMessage()
                   for r in caplog.records)
        assert not any(r.levelno >= logging.ERROR for r in caplog.records)

    def test_is_an_anticipated_error(self):
        assert issubclass(pe.P4kLockedError, pe.ANTICIPATED_EXTRACTION_ERRORS)


class TestBothExtractionsCheckFirst:
    def test_global_ini(self, tools, tmp_path, monkeypatch):
        _no_tool(monkeypatch)
        output = tmp_path / "base.ini"
        with pytest.raises(pe.P4kLockedError):
            pe.extract_global_ini(tools / "Data.p4k", output, tools / "unp4k.exe",
                                  scratch_near=tmp_path / "cache")
        assert not output.exists()

    def test_dataforge(self, tools, tmp_path, monkeypatch):
        _no_tool(monkeypatch)
        cache = tmp_path / "cache" / "dataforge"
        cache.mkdir(parents=True)
        (cache / "kept.xml").write_text("old")
        with pytest.raises(pe.P4kLockedError):
            pe.extract_dataforge(tools / "Data.p4k", tools / "unp4k.exe",
                                 tools / "unforge.exe", cache)
        assert (cache / "kept.xml").read_text() == "old"
