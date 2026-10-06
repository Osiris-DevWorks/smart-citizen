"""#471: stopping an extraction, from the progress dialog or by closing.

Closing the window used to leave unp4k.exe or unforge.exe running on their
own, and Esc or the X on the DataForge progress dialog only hid it while the
extraction carried on unseen. This pins the Qt side of the fix:

* AnimatedProgressDialog's close guard: Esc and the title-bar X ask, a
  programmatic close() never does.
* DataForgeExtractWorker / P4kExtractWorker on real threads: a stop ends with
  finished(False), no error signal and nothing at ERROR (an ERROR record would
  pop the global error dialog), while a real failure still reports.
* MainWindow on stub selves (no full window): the stop prompt, the
  identity-bound slots, the guards that keep anything new from starting once
  the close is committed, and closeEvent's order (commit, ask the tools to
  stop ahead of the loader wait, save the window state, then wait).

The P4K-side work (the stoppable runner, the working folder) is covered
Qt-free in test_extraction_working_folder.py. Offscreen Qt via the session
``qapp`` fixture, no pytest-qt.
"""
from __future__ import annotations

import logging
import threading
import time
from unittest.mock import MagicMock

import pytest

from PyQt6.QtCore import Qt, QThread
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtTest import QTest

import src.gui.main_window as main_window
import src.utils.pak_extractor as pe
from src.gui.main_window import MainWindow
from src.gui.workers import AnimatedProgressDialog, DataForgeExtractWorker, P4kExtractWorker
from src.utils.i18n import tr
from src.utils.settings import AppSettings

pytestmark = pytest.mark.unit


# ── AnimatedProgressDialog's close guard ────────────────────────────────────

class _TitleBarClose(QCloseEvent):
    """What the title-bar X (or Alt+F4) delivers: a spontaneous close event.
    A QCloseEvent made in Python is never spontaneous on its own."""

    def spontaneous(self):
        return True


@pytest.fixture
def dialog(qapp):
    dlg = AnimatedProgressDialog("Converting DataForge database…", title="DataForge Extraction")
    qapp.processEvents()
    yield dlg
    dlg.set_close_guard(None)
    dlg.close()
    dlg.deleteLater()
    qapp.processEvents()


class TestProgressDialogCloseGuard:
    def test_esc_asks_and_no_keeps_the_dialog_open(self, dialog):
        asked = []
        dialog.set_close_guard(lambda: asked.append(1) or False)
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        assert asked == [1]
        assert dialog.isVisible()

    def test_esc_with_yes_closes_it(self, dialog):
        dialog.set_close_guard(lambda: True)
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        assert not dialog.isVisible()

    def test_the_title_bar_x_asks_once_and_no_keeps_it_open(self, dialog):
        asked = []
        dialog.set_close_guard(lambda: asked.append(1) or False)
        event = _TitleBarClose()
        dialog.closeEvent(event)
        assert asked == [1]
        assert not event.isAccepted()
        assert dialog.isVisible()

    def test_the_title_bar_x_with_yes_closes_it_without_asking_twice(self, dialog):
        """QDialog.closeEvent goes on to call reject(), which must not ask
        again."""
        asked = []
        dialog.set_close_guard(lambda: asked.append(1) or True)
        dialog.closeEvent(_TitleBarClose())
        assert asked == [1]
        assert not dialog.isVisible()

    def test_a_programmatic_close_never_asks(self, dialog):
        """Every caller closes the dialog itself when a run ends; none of
        those may turn into a question."""
        asked = []
        dialog.set_close_guard(lambda: asked.append(1) or False)
        dialog.close()
        assert asked == []
        assert not dialog.isVisible()

    def test_without_a_guard_esc_hides_it_as_before(self, dialog):
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        assert not dialog.isVisible()


# ── the workers, on real threads ────────────────────────────────────────────

def _collect(worker):
    finished, errors = [], []
    worker.finished.connect(finished.append, Qt.ConnectionType.DirectConnection)
    worker.error.connect(errors.append, Qt.ConnectionType.DirectConnection)
    return finished, errors


def _error_records(caplog):
    return [r for r in caplog.records if r.levelno >= logging.ERROR]


class _Patches:
    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append(args)
        report = MagicMock()
        report.errors = []
        report.summary_line.return_value = "0 patches"
        return report


@pytest.fixture
def patches(monkeypatch):
    recorder = _Patches()
    monkeypatch.setattr("src.utils.dataforge_patcher.apply_patches", recorder)
    return recorder


def _forge_worker():
    return DataForgeExtractWorker("Data.p4k", "unp4k.exe", "unforge.exe", "cache")


class TestDataForgeExtractWorker:
    def test_a_stop_ends_quietly(self, qapp, monkeypatch, patches, caplog):
        started = threading.Event()

        def extract(*args, should_cancel=None, **kwargs):
            started.set()
            while not should_cancel():
                time.sleep(0.01)
            raise pe.ExtractionCancelled("unforge.exe was stopped")

        monkeypatch.setattr(pe, "extract_dataforge", extract)
        worker = _forge_worker()
        finished, errors = _collect(worker)
        worker.start()
        assert started.wait(5)
        worker.requestInterruption()
        assert worker.wait(5000)
        assert finished == [False]
        assert errors == []
        assert _error_records(caplog) == []
        assert patches.calls == []
        assert worker.stopped is True

    def test_the_finished_slot_reports_a_real_stopped_thread_as_stopped(
        self, qapp, monkeypatch, patches
    ):
        """QThread reports no interruption once the thread has finished, and
        the slot waits for the thread before it looks. Reading
        isInterruptionRequested() there said "failed" after every stop
        (caught by the frozen smoke test); the worker's own record does not."""
        started = threading.Event()

        def extract(*args, should_cancel=None, **kwargs):
            started.set()
            while not should_cancel():
                time.sleep(0.01)
            raise pe.ExtractionCancelled("unforge.exe was stopped")

        monkeypatch.setattr(pe, "extract_dataforge", extract)
        worker = _forge_worker()
        worker.start()
        assert started.wait(5)
        worker.requestInterruption()
        assert worker.wait(5000)
        assert not worker.isInterruptionRequested()   # the Qt behaviour itself
        me = _window(_forge_worker=worker)

        MainWindow._on_dataforge_extract_finished(me, False, worker)

        me.statusBar().showMessage.assert_called_with(tr("extract.dataforge_stopped"))

    def test_a_stop_after_the_cache_was_written_skips_the_patches(
        self, qapp, monkeypatch, patches
    ):
        holder = {}

        def extract(*args, **kwargs):
            holder["worker"].requestInterruption()
            return True

        monkeypatch.setattr(pe, "extract_dataforge", extract)
        worker = holder["worker"] = _forge_worker()
        finished, errors = _collect(worker)
        worker.start()
        assert worker.wait(5000)
        assert finished == [False]
        assert errors == []
        assert patches.calls == []
        assert worker.stopped is True

    def test_a_stop_during_the_patches_still_stops(self, qapp, monkeypatch):
        """Yes on the stop question while 'Applying DataForge patches' shows:
        the run must end stopped, not chain into generation (and a
        Simple-mode apply)."""
        holder = {}

        def extract(*args, **kwargs):
            return True

        def patches_then_stop(*args, **kwargs):
            holder["worker"].requestInterruption()
            report = MagicMock()
            report.errors = []
            report.summary_line.return_value = "0 patches"
            return report

        monkeypatch.setattr(pe, "extract_dataforge", extract)
        monkeypatch.setattr("src.utils.dataforge_patcher.apply_patches", patches_then_stop)
        worker = holder["worker"] = _forge_worker()
        finished, errors = _collect(worker)
        worker.start()
        assert worker.wait(5000)
        assert finished == [False]
        assert errors == []
        assert worker.stopped is True

    def test_a_failure_on_the_way_out_of_a_stop_is_quiet(self, qapp, monkeypatch, patches, caplog):
        holder = {}

        def extract(*args, **kwargs):
            holder["worker"].requestInterruption()
            raise OSError("a file the killed tool still held")

        monkeypatch.setattr(pe, "extract_dataforge", extract)
        worker = holder["worker"] = _forge_worker()
        finished, errors = _collect(worker)
        worker.start()
        assert worker.wait(5000)
        assert finished == [False]
        assert errors == []
        assert _error_records(caplog) == []

    def test_a_real_failure_still_reports(self, qapp, monkeypatch, patches, caplog):
        def extract(*args, **kwargs):
            raise RuntimeError("unforge.exe failed (code 1)")

        monkeypatch.setattr(pe, "extract_dataforge", extract)
        worker = _forge_worker()
        finished, errors = _collect(worker)
        worker.start()
        assert worker.wait(5000)
        assert finished == [False]
        assert errors == ["unforge.exe failed (code 1)"]
        assert _error_records(caplog)
        assert worker.stopped is False

    def test_success_applies_the_patches_and_passes_the_stop_check(
        self, qapp, monkeypatch, patches
    ):
        seen = {}

        def extract(*args, should_cancel=None, **kwargs):
            seen["should_cancel"] = should_cancel
            return True

        monkeypatch.setattr(pe, "extract_dataforge", extract)
        worker = _forge_worker()
        finished, errors = _collect(worker)
        worker.start()
        assert worker.wait(5000)
        assert finished == [True]
        assert len(patches.calls) == 1
        assert seen["should_cancel"] == worker.isInterruptionRequested


class TestP4kExtractWorker:
    def test_it_hands_the_dataforge_cache_folder_on(self, qapp, monkeypatch):
        """unp4k works beside the DataForge cache, not in %TEMP% (#471)."""
        seen = {}

        def extract(*args, scratch_near=None, **kwargs):
            seen["near"] = scratch_near
            return True

        monkeypatch.setattr(pe, "extract_global_ini", extract)
        worker = P4kExtractWorker("Data.p4k", "base.ini", "unp4k.exe",
                                  scratch_near="E:/SC/LIVE/cache/dataforge")
        finished, _errors = _collect(worker)
        worker.start()
        assert worker.wait(5000)
        assert finished == [True]
        assert seen["near"] == "E:/SC/LIVE/cache/dataforge"

    def test_a_stop_ends_quietly(self, qapp, monkeypatch, caplog):
        started = threading.Event()

        def extract(*args, should_cancel=None, **kwargs):
            started.set()
            while not should_cancel():
                time.sleep(0.01)
            raise pe.ExtractionCancelled("unp4k.exe was stopped")

        monkeypatch.setattr(pe, "extract_global_ini", extract)
        worker = P4kExtractWorker("Data.p4k", "base.ini", "unp4k.exe")
        finished, errors = _collect(worker)
        worker.start()
        assert started.wait(5)
        worker.requestInterruption()
        assert worker.wait(5000)
        assert finished == [False]
        assert errors == []
        assert _error_records(caplog) == []

    def test_a_failure_on_the_way_out_of_a_stop_is_quiet(self, qapp, monkeypatch, caplog):
        holder = {}

        def extract(*args, **kwargs):
            holder["worker"].requestInterruption()
            raise OSError("held")

        monkeypatch.setattr(pe, "extract_global_ini", extract)
        worker = holder["worker"] = P4kExtractWorker("Data.p4k", "base.ini", "unp4k.exe")
        finished, errors = _collect(worker)
        worker.start()
        assert worker.wait(5000)
        assert finished == [False]
        assert errors == []
        assert _error_records(caplog) == []


# ── MainWindow, on stub selves ──────────────────────────────────────────────

class _Signal:
    def __init__(self):
        self.slots = []
        self.disconnects = 0

    def connect(self, slot, *args):
        self.slots.append(slot)

    def disconnect(self):
        self.disconnects += 1
        if not self.slots:
            raise TypeError("nothing connected")
        self.slots.clear()


class _Worker:
    """Stands in for an extraction worker in the MainWindow tests."""

    def __init__(self, *args, running=True, finishes=True):
        self.args = args
        self.running = running
        self.finishes = finishes
        self.interrupted = False
        self.stopped = False
        self.waits = []
        self.calls = []
        self.progress, self.progress_pct = _Signal(), _Signal()
        self.error, self.finished = _Signal(), _Signal()

    def isRunning(self):
        return self.running

    def isInterruptionRequested(self):
        return self.interrupted

    def requestInterruption(self):
        self.interrupted = True

    def wait(self, ms=None):
        self.waits.append(ms)
        if self.finishes:
            self.running = False
            return True
        return False

    def start(self):
        self.calls.append("start")

    def quit(self):
        self.calls.append("quit")

    def deleteLater(self):
        self.calls.append("deleteLater")


def _window(**attrs):
    me = MagicMock()
    me._close_committed = False
    me._forge_worker = None
    me._p4k_worker = None
    me._forge_progress_dialog = None
    me._p4k_progress = None
    me._EXTRACTION_WORKER_ATTRS = MainWindow._EXTRACTION_WORKER_ATTRS
    for name, value in attrs.items():
        setattr(me, name, value)
    return me


class TestStopExtractionsForClose:
    def test_both_extractions_are_stopped_hidden_and_released(self):
        p4k, forge = _Worker(), _Worker()
        p4k.progress.connect(print)
        forge.progress_pct.connect(print)
        p4k_dialog, forge_dialog = MagicMock(), MagicMock()
        me = _window(_p4k_worker=p4k, _p4k_progress=p4k_dialog,
                     _forge_worker=forge, _forge_progress_dialog=forge_dialog)

        MainWindow._stop_extractions_for_close(me, timeout_ms=5000)

        assert p4k.interrupted and forge.interrupted
        for dlg in (p4k_dialog, forge_dialog):
            # hide, not close: close() would ask the stop question again
            dlg.hide.assert_called_once_with()
            dlg.close.assert_not_called()
        assert p4k.progress.slots == [] and forge.progress_pct.slots == []
        me.hide.assert_called_once_with()
        assert me._p4k_worker is None and me._forge_worker is None
        assert me._p4k_progress is None and me._forge_progress_dialog is None
        assert all(0 <= ms <= 5000 for ms in p4k.waits + forge.waits)

    def test_a_worker_still_busy_past_the_bound_is_kept(self, caplog):
        forge = _Worker(finishes=False)
        me = _window(_forge_worker=forge)
        with caplog.at_level(logging.WARNING, logger=main_window.logger.name):
            MainWindow._stop_extractions_for_close(me, timeout_ms=50)
        assert me._forge_worker is forge   # Qt must not destroy a live thread
        assert "still cleaning up" in caplog.text

    def test_nothing_running_hides_nothing(self):
        done = _Worker(running=False)
        me = _window(_forge_worker=done)
        MainWindow._stop_extractions_for_close(me)
        me.hide.assert_not_called()
        assert me._forge_worker is None

    def test_no_extraction_at_all_is_a_no_op(self):
        me = _window()
        MainWindow._stop_extractions_for_close(me)
        me.hide.assert_not_called()

    def test_a_real_thread_is_stopped_and_waited_for(self, qapp):
        class Spinning(QThread):
            def run(self):
                while not self.isInterruptionRequested():
                    self.msleep(10)

        thread = Spinning()
        thread.start()
        me = _window(_forge_worker=thread)
        MainWindow._stop_extractions_for_close(me, timeout_ms=5000)
        assert thread.isFinished()
        assert me._forge_worker is None

    def test_request_extraction_stops_only_asks(self):
        p4k, forge = _Worker(), _Worker()
        me = _window(_p4k_worker=p4k, _forge_worker=forge)
        MainWindow._request_extraction_stops(me)
        assert p4k.interrupted and forge.interrupted
        assert p4k.waits == [] and forge.waits == []


class TestCloseEventOrder:
    @staticmethod
    def _closing_self(order, unapplied=False):
        me = _window()
        me._session_has_unapplied_edit = unapplied
        me._suppress_user_ini_autosave = False
        me._user_resized_columns = False
        me.entries = []
        loader = MagicMock()
        loader.wait.side_effect = lambda *a: order.append("loader")
        me._loader_worker = loader
        me._settle_applied_state_check.side_effect = lambda: order.append("settle")

        def interrupt():
            assert me._close_committed is True   # committed before anything is stopped
            order.append("interrupt")

        me._request_extraction_stops.side_effect = interrupt
        me._stop_extractions_for_close.side_effect = lambda: order.append("stop")
        return me

    def test_the_tools_are_stopped_early_and_waited_for_last(self, monkeypatch):
        order = []
        monkeypatch.setattr(AppSettings, "set_window_state",
                            staticmethod(lambda *a: order.append("state")))
        monkeypatch.setattr(AppSettings, "set_window_geometry",
                            staticmethod(lambda *a: order.append("geometry")))
        monkeypatch.setattr(AppSettings, "set_string_column_widths", staticmethod(lambda *a: None))
        event = MagicMock()
        event.accept.side_effect = lambda: order.append("accept")

        MainWindow.closeEvent(self._closing_self(order), event)

        assert order == ["settle", "interrupt", "loader", "state", "geometry", "stop", "accept"]

    def test_cancelling_the_close_stops_nothing(self, monkeypatch):
        """Cancel keeps the window, so the extraction keeps running too."""
        buttons = [MagicMock(name="apply"), MagicMock(name="exit"), MagicMock(name="cancel")]
        box = MagicMock()
        box.addButton.side_effect = list(buttons)
        box.clickedButton.return_value = buttons[2]
        monkeypatch.setattr(main_window, "QMessageBox", MagicMock(return_value=box))
        order = []
        me = self._closing_self(order, unapplied=True)

        MainWindow.closeEvent(me, MagicMock())

        assert me._close_committed is False
        me._request_extraction_stops.assert_not_called()
        me._stop_extractions_for_close.assert_not_called()


class TestDataForgeSlots:
    def test_a_released_worker_finishing_changes_nothing(self):
        stale, current = _Worker(running=False), _Worker()
        me = _window(_forge_worker=current)
        MainWindow._on_dataforge_extract_finished(me, True, stale)
        assert stale.calls == ["quit", "deleteLater"]
        assert me._forge_worker is current
        me._run_enhancements_generation.assert_not_called()
        me._cleanup_pending_old_cache.assert_not_called()

    def test_finishing_during_the_close_chains_into_nothing(self):
        worker = _Worker(running=False)
        me = _window(_forge_worker=worker, _close_committed=True)
        MainWindow._on_dataforge_extract_finished(me, True, worker)
        assert me._forge_worker is None
        me._end_simple_run.assert_called_once_with()
        me._run_enhancements_generation.assert_not_called()
        me._cleanup_pending_old_cache.assert_not_called()

    def test_success_goes_on_to_generation(self):
        worker = _Worker(running=False)
        me = _window(_forge_worker=worker)
        MainWindow._on_dataforge_extract_finished(me, True, worker)
        me._cleanup_pending_old_cache.assert_called_once_with()
        me._run_enhancements_generation.assert_called_once_with()

    def test_a_stop_from_the_dialog_says_stopped_not_failed(self):
        worker = _Worker(running=False)
        worker.stopped = True
        me = _window(_forge_worker=worker)
        MainWindow._on_dataforge_extract_finished(me, False, worker)
        me.statusBar().showMessage.assert_called_with(tr("extract.dataforge_stopped"))
        me.enhancements_tab.set_operation_idle.assert_called_once_with(success=False)
        me._end_simple_run.assert_called_once_with()

    def test_a_failure_still_says_failed(self):
        worker = _Worker(running=False)
        me = _window(_forge_worker=worker)
        MainWindow._on_dataforge_extract_finished(me, False, worker)
        me.statusBar().showMessage.assert_called_with(tr("extract.dataforge_extraction_failed"))

    @pytest.mark.parametrize("released, closing", [(True, False), (False, True)])
    def test_an_error_while_closing_opens_no_dialog(self, monkeypatch, caplog, released, closing):
        box = MagicMock()
        monkeypatch.setattr(main_window, "QMessageBox", box)
        worker = _Worker()
        me = _window(_forge_worker=None if released else worker, _close_committed=closing)
        with caplog.at_level(logging.WARNING, logger=main_window.logger.name):
            MainWindow._on_dataforge_extract_error(me, "boom", worker)
        box.warning.assert_not_called()
        me._end_simple_run.assert_not_called()
        assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []

    def test_an_ordinary_error_still_shows_its_dialog(self, monkeypatch):
        box = MagicMock()
        monkeypatch.setattr(main_window, "QMessageBox", box)
        worker = _Worker()
        me = _window(_forge_worker=worker)
        MainWindow._on_dataforge_extract_error(me, "boom", worker)
        box.warning.assert_called_once()


class TestP4kSlots:
    def test_a_released_worker_finishing_changes_nothing(self):
        stale, current = _Worker(running=False), _Worker()
        me = _window(_p4k_worker=current)
        MainWindow._on_p4k_extract_finished(me, True, stale)
        assert me._p4k_worker is current
        me._show_loading_progress.assert_not_called()

    def test_finishing_during_the_close_reloads_nothing(self):
        worker = _Worker(running=False)
        progress = MagicMock()
        me = _window(_p4k_worker=worker, _p4k_progress=progress, _close_committed=True)
        MainWindow._on_p4k_extract_finished(me, True, worker)
        progress.close.assert_called_once_with()
        assert me._p4k_worker is None
        me._show_loading_progress.assert_not_called()

    def test_an_error_while_closing_opens_no_dialog(self, monkeypatch):
        box = MagicMock()
        monkeypatch.setattr(main_window, "QMessageBox", box)
        worker = _Worker()
        me = _window(_p4k_worker=worker, _close_committed=True)
        MainWindow._on_p4k_extract_error(me, "boom", worker)
        box.warning.assert_not_called()


class TestNothingStartsOnceClosing:
    @pytest.fixture
    def settings(self, monkeypatch):
        fake = MagicMock()
        monkeypatch.setattr(main_window, "AppSettings", fake)
        return fake

    def test_no_dataforge_extraction(self, monkeypatch, settings):
        made = MagicMock()
        monkeypatch.setattr(main_window, "DataForgeExtractWorker", made)
        MainWindow._run_dataforge_extraction(_window(_close_committed=True))
        made.assert_not_called()

    def test_no_global_ini_extraction(self, monkeypatch, settings):
        made = MagicMock()
        monkeypatch.setattr(main_window, "P4kExtractWorker", made)
        MainWindow._run_p4k_extraction(_window(_close_committed=True))
        made.assert_not_called()

    def test_no_generation(self, monkeypatch, settings):
        made = MagicMock()
        monkeypatch.setattr(main_window, "EnhancementsGeneratorWorker", made)
        me = _window(_close_committed=True)
        me._enhancements_worker = None
        MainWindow._run_enhancements_generation(me)
        made.assert_not_called()

    def test_no_freshness_prompts(self, settings):
        me = _window(_close_committed=True)
        me._enhancements_worker = None
        MainWindow._check_enhancements_freshness(me)
        MainWindow._maybe_prompt_dataforge_refresh(me)
        settings.get_base_ini_path.assert_not_called()
        settings.get_p4k_path.assert_not_called()


class TestStartupRefreshPrompt:
    """A cache with extracted content but no freshness stamp is an extraction
    cut off between the wipe and the stamps (a crash, or a close that
    outlasted its wait). It must prompt for a re-extract at startup instead of
    passing for "never extracted", which only the missing-INI check covers."""

    @pytest.fixture
    def env(self, tmp_path, monkeypatch):
        tools = tmp_path / "tools"
        tools.mkdir()
        for name in ("Data.p4k", "unp4k.exe", "unforge.exe"):
            (tools / name).write_bytes(b"x")
        leaf = tmp_path / "SC" / "LIVE" / "cache" / "dataforge"
        leaf.mkdir(parents=True)
        settings = MagicMock()
        settings.get_p4k_path.return_value = tools / "Data.p4k"
        settings.get_unp4k_exe_path.return_value = tools / "unp4k.exe"
        settings.get_unforge_exe_path.return_value = tools / "unforge.exe"
        settings.get_dataforge_cache_dir.return_value = leaf
        monkeypatch.setattr(main_window, "AppSettings", settings)
        box = MagicMock()
        box.question.return_value = box.StandardButton.Yes
        monkeypatch.setattr(main_window, "QMessageBox", box)
        me = _window()
        me._enhancements_worker = None
        return me, leaf, tools / "Data.p4k", box

    def test_a_cut_off_cache_prompts_for_a_re_extract(self, env):
        me, leaf, _p4k, box = env
        records = leaf / "raw" / "libs" / "foundry" / "records" / "entities"
        records.mkdir(parents=True)
        (records / "x.xml").write_text("<x/>", encoding="utf-8")
        MainWindow._maybe_prompt_dataforge_refresh(me)
        box.question.assert_called_once()
        me._run_dataforge_extraction.assert_called_once_with()

    def test_a_never_extracted_cache_stays_quiet(self, env):
        me, _leaf, _p4k, box = env
        MainWindow._maybe_prompt_dataforge_refresh(me)
        box.question.assert_not_called()

    def test_a_fresh_cache_stays_quiet(self, env):
        me, leaf, p4k, box = env
        (leaf / "raw" / "libs").mkdir(parents=True)
        (leaf / "raw" / "libs" / "x.xml").write_text("<x/>", encoding="utf-8")
        stat = p4k.stat()
        (leaf / pe.P4K_MTIME_STAMP).write_text(str(stat.st_mtime))
        (leaf / pe.P4K_SIZE_STAMP).write_text(str(stat.st_size))
        MainWindow._maybe_prompt_dataforge_refresh(me)
        box.question.assert_not_called()


class TestStopPrompt:
    @pytest.fixture
    def box(self, monkeypatch):
        fake = MagicMock()
        monkeypatch.setattr(main_window, "QMessageBox", fake)
        return fake

    def test_an_extraction_that_is_over_closes_without_asking(self, box):
        worker = _Worker()
        me = _window(_forge_worker=None)
        assert MainWindow._confirm_stop_dataforge_extraction(me, worker) is True
        box.question.assert_not_called()

    def test_no_keeps_it_running(self, box):
        box.question.return_value = box.StandardButton.No
        worker = _Worker()
        me = _window(_forge_worker=worker)
        assert MainWindow._confirm_stop_dataforge_extraction(me, worker) is False
        assert not worker.interrupted

    def test_yes_stops_it(self, box):
        box.question.return_value = box.StandardButton.Yes
        worker = _Worker()
        me = _window(_forge_worker=worker)
        assert MainWindow._confirm_stop_dataforge_extraction(me, worker) is True
        assert worker.interrupted
        me.statusBar().showMessage.assert_called_with(tr("extract.dataforge_stopping"))
        # Whatever the worker does next, a Simple-mode run can't apply now.
        me._end_simple_run.assert_called_once_with()

    def test_yes_after_it_finished_meanwhile_still_keeps_simple_mode_from_applying(self, box):
        """The run finished while the question was open, so its slot already
        handed over to generation. There is nothing left to stop, but Yes
        must still keep a Simple-mode run from applying to the game."""
        worker = _Worker()

        def finish_while_asking(*args, **kwargs):
            worker.running = False
            return box.StandardButton.Yes

        box.question.side_effect = finish_while_asking
        me = _window(_forge_worker=worker)
        assert MainWindow._confirm_stop_dataforge_extraction(me, worker) is True
        assert not worker.interrupted
        me._end_simple_run.assert_called_once_with()

    def test_no_after_it_finished_meanwhile_leaves_simple_mode_alone(self, box):
        worker = _Worker()

        def finish_while_asking(*args, **kwargs):
            worker.running = False
            return box.StandardButton.No

        box.question.side_effect = finish_while_asking
        me = _window(_forge_worker=worker)
        assert MainWindow._confirm_stop_dataforge_extraction(me, worker) is False
        me._end_simple_run.assert_not_called()

    def test_the_question_defaults_to_no(self, box):
        box.question.return_value = box.StandardButton.No
        worker = _Worker()
        MainWindow._confirm_stop_dataforge_extraction(_window(_forge_worker=worker), worker)
        args = box.question.call_args.args
        assert args[1] == tr("extract.dataforge_stop_title")
        assert args[2] == tr("extract.dataforge_stop_body")
        assert args[4] is box.StandardButton.No


class TestExtractionWiring:
    def test_the_dataforge_dialog_asks_before_it_closes(self, monkeypatch):
        made = []

        def make_worker(*args):
            made.append(_Worker(*args))
            return made[-1]

        dialog = MagicMock()
        monkeypatch.setattr(main_window, "AppSettings", MagicMock())
        monkeypatch.setattr(main_window, "DataForgeExtractWorker", make_worker)
        monkeypatch.setattr(main_window, "AnimatedProgressDialog", MagicMock(return_value=dialog))
        me = _window()

        MainWindow._run_dataforge_extraction(me)

        worker = made[0]
        assert me._forge_worker is worker
        assert worker.calls == ["start"]
        guard = dialog.set_close_guard.call_args.args[0]
        guard()
        me._confirm_stop_dataforge_extraction.assert_called_once_with(worker)
        worker.finished.slots[0](True)
        me._on_dataforge_extract_finished.assert_called_once_with(True, worker)
        worker.error.slots[0]("boom")
        me._on_dataforge_extract_error.assert_called_once_with("boom", worker)

    def test_the_global_ini_slots_are_bound_to_their_worker(self, monkeypatch):
        made = []

        def make_worker(*args, **kwargs):
            made.append(_Worker(*args))
            return made[-1]

        monkeypatch.setattr(main_window, "AppSettings", MagicMock())
        monkeypatch.setattr(main_window, "P4kExtractWorker", make_worker)
        monkeypatch.setattr(main_window, "AnimatedProgressDialog", MagicMock())
        me = _window()

        MainWindow._run_p4k_extraction(me)

        worker = made[0]
        worker.finished.slots[0](False)
        me._on_p4k_extract_finished.assert_called_once_with(False, worker)
        worker.error.slots[0]("boom")
        me._on_p4k_extract_error.assert_called_once_with("boom", worker)

    @pytest.mark.parametrize("offline", [False, True])
    def test_the_global_ini_extraction_works_beside_the_dataforge_cache(
        self, monkeypatch, offline
    ):
        """It is handed the DataForge cache folder (#471). A cache drive that
        is offline makes get_dataforge_cache_dir() raise (it creates the
        folder); the extraction then works in %TEMP% instead of not running."""
        kwargs_seen = []

        def make_worker(*args, **kwargs):
            kwargs_seen.append(kwargs)
            return _Worker(*args)

        settings = MagicMock()
        if offline:
            settings.get_dataforge_cache_dir.side_effect = OSError("drive E: is not ready")
        else:
            settings.get_dataforge_cache_dir.return_value = "E:/SC/LIVE/cache/dataforge"
        monkeypatch.setattr(main_window, "AppSettings", settings)
        monkeypatch.setattr(main_window, "P4kExtractWorker", make_worker)
        monkeypatch.setattr(main_window, "AnimatedProgressDialog", MagicMock())

        MainWindow._run_p4k_extraction(_window())

        expected = None if offline else "E:/SC/LIVE/cache/dataforge"
        assert kwargs_seen == [{"scratch_near": expected}]

    def test_generation_takes_the_dialog_without_the_stop_question(self, monkeypatch):
        """The same dialog lives on into generation, which has no stop."""
        monkeypatch.setattr(main_window, "AppSettings", MagicMock())
        monkeypatch.setattr(main_window, "EnhancementsGeneratorWorker", MagicMock())
        handed_over = MagicMock()
        me = _window(_forge_progress_dialog=handed_over)
        me._enhancements_worker = None

        MainWindow._run_enhancements_generation(me)

        handed_over.set_close_guard.assert_called_once_with(None)
        assert me._enhancements_progress_dialog is handed_over
