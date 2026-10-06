"""#471: stopping an extraction, from the progress dialog or by closing.

Closing the window used to leave unp4k.exe or unforge.exe running on their
own, and Esc or the X on the DataForge progress dialog only hid it while the
extraction carried on unseen. This pins the Qt side of the fix:

* AnimatedProgressDialog's close guard: Esc and the title-bar X ask, a
  programmatic close() never does.
* DataForgeExtractWorker / P4kExtractWorker on real threads: a stop ends with
  finished(False), no error signal and nothing at ERROR (an ERROR record would
  pop the global error dialog), while a real failure still reports.
* MainWindow on stub selves (no full window): the DataForge stop prompt,
  the global.ini dialog's stop, the identity-bound slots, the guards that
  keep anything new from starting once the close is committed, and
  closeEvent's order (commit, ask the tools to stop ahead of the loader
  wait, save the window state, then wait).

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
        """Stop picked in the question while 'Applying DataForge patches' shows:
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
        assert worker.stopped is True

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
        assert worker.stopped is False

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
        assert worker.stopped is True

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
        assert worker.stopped is True

    def test_a_real_failure_still_reports(self, qapp, monkeypatch, caplog):
        def extract(*args, **kwargs):
            raise RuntimeError("unp4k exited with code 3")

        monkeypatch.setattr(pe, "extract_global_ini", extract)
        worker = P4kExtractWorker("Data.p4k", "base.ini", "unp4k.exe")
        finished, errors = _collect(worker)
        worker.start()
        assert worker.wait(5000)
        assert finished == [False]
        assert errors == ["unp4k exited with code 3"]
        assert worker.stopped is False


# ── MainWindow, on stub selves ──────────────────────────────────────────────

class _Signal:
    def __init__(self):
        self.slots = []
        self.disconnects = 0

    def connect(self, slot, *args):
        self.slots.append(slot)

    def disconnect(self, slot=None):
        self.disconnects += 1
        if slot is None:
            if not self.slots:
                raise TypeError("nothing connected")
            self.slots.clear()
        elif slot in self.slots:
            self.slots.remove(slot)
        else:
            raise TypeError("not connected")


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
    me._after_unfinished_p4k_extraction = None
    me._p4k_error_box_open = False
    me._p4k_follow_up_after_error = None
    me._EXTRACTION_WORKER_ATTRS = MainWindow._EXTRACTION_WORKER_ATTRS
    me._detach_progress_dialog = MainWindow._detach_progress_dialog
    for name, value in attrs.items():
        setattr(me, name, value)
    return me


class TestStopExtractionsForClose:
    def test_both_extractions_are_stopped_hidden_and_released(self):
        p4k, forge = _Worker(), _Worker()
        p4k_dialog, forge_dialog = MagicMock(), MagicMock()
        for worker, dlg in ((p4k, p4k_dialog), (forge, forge_dialog)):
            worker.progress.connect(dlg.setLabelText)
            worker.progress_pct.connect(dlg.set_progress)
        forge.progress.connect(print)   # stands in for the status bar
        me = _window(_p4k_worker=p4k, _p4k_progress=p4k_dialog,
                     _forge_worker=forge, _forge_progress_dialog=forge_dialog)

        MainWindow._stop_extractions_for_close(me, timeout_ms=5000)

        assert p4k.interrupted and forge.interrupted
        for dlg in (p4k_dialog, forge_dialog):
            # Detached, and cancelled rather than hidden: a hidden one comes
            # back while progress keeps arriving, or by itself when it is
            # under 4 s old (TestDismissedDialogStaysHidden).
            dlg.cancel.assert_called_once_with()
            dlg.hide.assert_not_called()
            dlg.close.assert_not_called()
        assert p4k.progress.slots == [] and p4k.progress_pct.slots == []
        assert forge.progress.slots == [print] and forge.progress_pct.slots == []
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

    @pytest.mark.parametrize("released, closing", [(True, False), (False, True)])
    def test_an_error_while_closing_opens_no_dialog(self, monkeypatch, released, closing):
        box = MagicMock()
        monkeypatch.setattr(main_window, "QMessageBox", box)
        worker = _Worker()
        me = _window(_p4k_worker=None if released else worker, _close_committed=closing)
        MainWindow._on_p4k_extract_error(me, "boom", worker)
        box.warning.assert_not_called()

    def test_an_ordinary_error_still_shows_its_dialog(self, monkeypatch):
        box = MagicMock()
        monkeypatch.setattr(main_window, "QMessageBox", box)
        worker = _Worker()
        me = _window(_p4k_worker=worker)
        MainWindow._on_p4k_extract_error(me, "boom", worker)
        box.warning.assert_called_once()

    def test_a_stop_from_the_dialog_says_stopped(self):
        worker = _Worker(running=False)
        worker.stopped = True
        progress = MagicMock()
        me = _window(_p4k_worker=worker, _p4k_progress=progress)
        MainWindow._on_p4k_extract_finished(me, False, worker)
        progress.close.assert_called_once_with()
        assert me._p4k_worker is None
        me.statusBar().showMessage.assert_called_once_with(tr("extract.p4k_stopped"))
        me._show_loading_progress.assert_not_called()

    def test_a_failure_adds_nothing_to_its_error_dialog(self):
        worker = _Worker(running=False)
        me = _window(_p4k_worker=worker)
        MainWindow._on_p4k_extract_finished(me, False, worker)
        me.statusBar().showMessage.assert_not_called()

    @pytest.mark.parametrize("stopped", [True, False])
    def test_an_unfinished_run_carries_on_as_if_declined(self, stopped):
        """Startup, a channel switch and a data-folder change leave their
        reload to the extraction. Only a success used to reload, so a stop
        (or a failure such as a locked Data.p4k) left no strings, or the old
        channel's, until a restart."""
        worker = _Worker(running=False)
        worker.stopped = stopped
        carry_on = MagicMock()
        me = _window(_p4k_worker=worker, _after_unfinished_p4k_extraction=carry_on)
        MainWindow._on_p4k_extract_finished(me, False, worker)
        carry_on.assert_called_once_with()
        assert me._after_unfinished_p4k_extraction is None

    def test_a_success_reloads_once_and_drops_the_fallback(self, monkeypatch):
        monkeypatch.setattr(main_window, "AppSettings", MagicMock())
        worker = _Worker(running=False)
        carry_on = MagicMock()
        me = _window(_p4k_worker=worker, _after_unfinished_p4k_extraction=carry_on)
        MainWindow._on_p4k_extract_finished(me, True, worker)
        me._show_loading_progress.assert_called_once()
        carry_on.assert_not_called()
        assert me._after_unfinished_p4k_extraction is None

    def test_the_fallback_is_dropped_when_closing(self):
        worker = _Worker(running=False)
        worker.stopped = True
        carry_on = MagicMock()
        me = _window(_p4k_worker=worker, _after_unfinished_p4k_extraction=carry_on,
                     _close_committed=True)
        MainWindow._on_p4k_extract_finished(me, False, worker)
        carry_on.assert_not_called()
        me.statusBar().showMessage.assert_not_called()
        assert me._after_unfinished_p4k_extraction is None

    def test_a_failed_runs_follow_up_waits_for_its_error_box(self, monkeypatch):
        """The worker emits error, then finished, so the finished slot runs
        inside the error box's own event loop. The caller's follow-up (a
        reload, maybe a prompt) must wait until the box has closed."""
        worker = _Worker(running=False)
        carry_on = MagicMock()
        me = _window(_p4k_worker=worker, _after_unfinished_p4k_extraction=carry_on)
        box = MagicMock()
        inside = []

        def warning(*args):
            MainWindow._on_p4k_extract_finished(me, False, worker)   # its nested loop
            inside.append(carry_on.called)

        box.warning.side_effect = warning
        monkeypatch.setattr(main_window, "QMessageBox", box)

        MainWindow._on_p4k_extract_error(me, "Data.p4k is locked", worker)

        assert inside == [False]
        carry_on.assert_called_once_with()
        assert me._p4k_error_box_open is False
        assert me._p4k_follow_up_after_error is None

    def test_a_follow_up_parked_by_the_error_box_is_dropped_when_closing(self, monkeypatch):
        worker = _Worker(running=False)
        carry_on = MagicMock()
        me = _window(_p4k_worker=worker, _after_unfinished_p4k_extraction=carry_on)
        box = MagicMock()

        def warning(*args):
            MainWindow._on_p4k_extract_finished(me, False, worker)
            me._close_committed = True   # e.g. the update installer's relaunch

        box.warning.side_effect = warning
        monkeypatch.setattr(main_window, "QMessageBox", box)

        MainWindow._on_p4k_extract_error(me, "boom", worker)

        carry_on.assert_not_called()
        assert me._p4k_follow_up_after_error is None

    def test_a_follow_up_with_no_error_box_runs_at_once(self):
        worker = _Worker(running=False)
        carry_on = MagicMock()
        me = _window(_p4k_worker=worker, _after_unfinished_p4k_extraction=carry_on)
        MainWindow._on_p4k_extract_finished(me, False, worker)
        carry_on.assert_called_once_with()
        assert me._p4k_follow_up_after_error is None

    def test_a_released_worker_leaves_the_fallback_alone(self):
        stale, current = _Worker(running=False), _Worker()
        carry_on = MagicMock()
        me = _window(_p4k_worker=current, _after_unfinished_p4k_extraction=carry_on)
        MainWindow._on_p4k_extract_finished(me, False, stale)
        carry_on.assert_not_called()
        assert me._after_unfinished_p4k_extraction is carry_on


class TestCallersCarryOnAfterAnUnfinishedExtraction:
    """_check_p4k_freshness records what its caller does when the extraction
    is declined, and each caller that leaves its reload to the extraction
    passes exactly that (#471)."""

    @pytest.fixture
    def stale(self, monkeypatch, tmp_path):
        """A missing base.ini with unp4k and Data.p4k present: the prompt fires."""
        (tmp_path / "unp4k.exe").write_text("", encoding="utf-8")
        (tmp_path / "Data.p4k").write_text("", encoding="utf-8")
        settings = MagicMock()
        settings.get_unp4k_exe_path.return_value = tmp_path / "unp4k.exe"
        settings.get_p4k_path.return_value = tmp_path / "Data.p4k"
        settings.get_cache_dir.return_value = tmp_path / "cache"
        monkeypatch.setattr(main_window, "AppSettings", settings)
        box = MagicMock()
        box.StandardButton = main_window.QMessageBox.StandardButton
        monkeypatch.setattr(main_window, "QMessageBox", box)
        return box

    def test_yes_records_the_fallback(self, stale):
        stale.question.return_value = stale.StandardButton.Yes
        me = _window()
        me._run_p4k_extraction.return_value = True
        carry_on = MagicMock()
        assert MainWindow._check_p4k_freshness(me, if_unfinished=carry_on) is True
        assert me._after_unfinished_p4k_extraction is carry_on

    def test_yes_while_one_is_running_carries_on_at_once(self, stale):
        stale.question.return_value = stale.StandardButton.Yes
        me = _window()
        me._run_p4k_extraction.return_value = False
        carry_on = MagicMock()
        assert MainWindow._check_p4k_freshness(me, if_unfinished=carry_on) is False
        assert me._after_unfinished_p4k_extraction is None

    def test_no_records_nothing(self, stale):
        stale.question.return_value = stale.StandardButton.No
        me = _window()
        assert MainWindow._check_p4k_freshness(me, if_unfinished=MagicMock()) is False
        me._run_p4k_extraction.assert_not_called()
        assert me._after_unfinished_p4k_extraction is None

    @pytest.mark.parametrize("started", [True, False])
    def test_startup(self, monkeypatch, started):
        monkeypatch.setattr(main_window, "AppSettings", MagicMock())
        me = _window(_startup_sync_worker=None, _startup_progress=None)
        me._check_p4k_freshness.return_value = started
        MainWindow._on_startup_sync_finished(me)
        me._check_p4k_freshness.assert_called_once_with(if_unfinished=me._finish_startup_load)
        assert me._finish_startup_load.called is not started

    @pytest.mark.parametrize("started", [True, False])
    def test_a_channel_switch(self, monkeypatch, started):
        monkeypatch.setattr(main_window, "AppSettings", MagicMock())
        me = _window()
        me._check_p4k_freshness.return_value = started
        MainWindow._on_channel_changed(me, "PTU")
        carry_on = me._check_p4k_freshness.call_args.kwargs["if_unfinished"]
        assert me._reload_after_channel_switch.called is not started
        me._reload_after_channel_switch.reset_mock()
        carry_on()
        me._reload_after_channel_switch.assert_called_once_with("PTU")

    @pytest.mark.parametrize("started", [True, False])
    def test_a_data_folder_change(self, monkeypatch, started):
        monkeypatch.setattr(main_window, "AppSettings", MagicMock())
        me = _window()
        me._check_p4k_freshness.return_value = started
        MainWindow._on_data_dir_changed(me, "E:/SC data")
        carry_on = me._check_p4k_freshness.call_args.kwargs["if_unfinished"]
        assert me._reload_after_data_dir_change.called is not started
        me._reload_after_data_dir_change.reset_mock()
        carry_on()
        me._reload_after_data_dir_change.assert_called_once_with("E:/SC data")


class TestDeclinedPaths:
    """The declined paths themselves, moved into methods unchanged (#471)."""

    def test_startup_with_no_base_ini_loads_nothing(self, monkeypatch, tmp_path):
        settings = MagicMock()
        settings.get_cache_dir.return_value = tmp_path
        monkeypatch.setattr(main_window, "AppSettings", settings)
        me = _window()
        MainWindow._finish_startup_load(me)
        me.statusBar().showMessage.assert_called_once_with(tr("status_bar.no_strings_loaded"))
        me._show_loading_progress.assert_not_called()
        me._maybe_prompt_dataforge_refresh.assert_not_called()

    def test_startup_with_a_base_ini_loads_it(self, monkeypatch, tmp_path):
        (tmp_path / "base.ini").write_text("item_Name=Thing\n", encoding="utf-8")
        settings = MagicMock()
        settings.get_cache_dir.return_value = tmp_path
        monkeypatch.setattr(main_window, "AppSettings", settings)
        me = _window()
        me._check_enhancements_after_loading = False
        MainWindow._finish_startup_load(me)
        me._maybe_prompt_dataforge_refresh.assert_called_once_with()
        assert me._check_enhancements_after_loading is True
        me._show_loading_progress.assert_called_once_with()

    def test_a_channel_switch_reloads(self):
        me = _window()
        MainWindow._reload_after_channel_switch(me, "PTU")
        me._maybe_prompt_dataforge_refresh.assert_called_once_with()
        me.statusBar().showMessage.assert_called_once_with(
            tr("status_bar.channel_switched_reloading", channel="PTU"))
        me.perform_merge_and_reload.assert_called_once_with()

    def test_a_data_folder_change_reloads(self):
        me = _window()
        MainWindow._reload_after_data_dir_change(me, "E:/SC data")
        me._maybe_prompt_dataforge_refresh.assert_called_once_with()
        me.statusBar().showMessage.assert_called_once_with(
            tr("status_bar.data_folder_changed_reloading", data_dir="E:/SC data"))
        me.perform_merge_and_reload.assert_called_once_with()


class TestGlobalIniDialogStops:
    """Esc or the X on the global.ini dialog stops the extraction (#471).
    It used to hide the dialog while unp4k carried on unseen, and with one
    run at a time the Extract button then did nothing until it ended."""

    @staticmethod
    def _setup(**worker_kwargs):
        worker = _Worker(**worker_kwargs)
        dialog = MagicMock()
        worker.progress.connect(dialog.setLabelText)
        worker.progress_pct.connect(dialog.set_progress)
        me = _window(_p4k_worker=worker, _p4k_progress=dialog)
        return worker, dialog, me

    def test_a_running_extraction_is_stopped(self):
        worker, dialog, me = self._setup()
        assert MainWindow._stop_p4k_extraction_from_dialog(me, worker) is True
        assert worker.interrupted
        me.statusBar().showMessage.assert_called_once_with(tr("extract.p4k_stopping"))
        # dismissed for good: no progress may bring it back, nor its timer
        assert worker.progress.slots == [] and worker.progress_pct.slots == []
        dialog.cancel.assert_called_once_with()
        assert me._p4k_progress is dialog   # the finished slot closes it

    @pytest.mark.parametrize("state", ["over", "stopping", "released"])
    def test_otherwise_the_dialog_just_closes(self, state):
        worker, dialog, me = self._setup(running=state != "over")
        if state == "stopping":
            worker.interrupted = True
        if state == "released":
            me._p4k_worker = _Worker()
        assert MainWindow._stop_p4k_extraction_from_dialog(me, worker) is True
        assert worker.interrupted is (state == "stopping")
        me.statusBar().showMessage.assert_not_called()
        assert worker.progress.slots == [dialog.setLabelText]
        dialog.cancel.assert_not_called()

    @pytest.mark.parametrize("how", ["esc", "x"])
    def test_the_real_dialog_stops_a_real_thread(self, qapp, monkeypatch, how):
        started = threading.Event()

        def extract(*args, should_cancel=None, progress_callback=None, **kwargs):
            progress_callback("Launching unp4k…")
            started.set()
            while not should_cancel():
                time.sleep(0.01)
            raise pe.ExtractionCancelled("unp4k.exe was stopped")

        monkeypatch.setattr(pe, "extract_global_ini", extract)
        worker = P4kExtractWorker("Data.p4k", "base.ini", "unp4k.exe")
        dialog = AnimatedProgressDialog("Extracting global.ini…", title="P4K Extraction")
        worker.progress.connect(dialog.setLabelText)
        worker.progress_pct.connect(dialog.set_progress)
        me = _window(_p4k_worker=worker, _p4k_progress=dialog)
        dialog.set_close_guard(
            lambda w=worker: MainWindow._stop_p4k_extraction_from_dialog(me, w))
        try:
            worker.start()
            assert started.wait(5)
            qapp.processEvents()
            if how == "esc":
                QTest.keyClick(dialog, Qt.Key.Key_Escape)
            else:
                dialog.closeEvent(_TitleBarClose())
            assert not dialog.isVisible()
            assert worker.wait(5000)
            assert worker.stopped is True

            MainWindow._on_p4k_extract_finished(me, False, worker)

            assert me._p4k_worker is None and me._p4k_progress is None
            me.statusBar().showMessage.assert_called_with(tr("extract.p4k_stopped"))
        finally:
            dialog.set_close_guard(None)
            dialog.close()
            dialog.deleteLater()
            qapp.processEvents()


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

    def test_no_second_global_ini_extraction_while_one_runs(self, monkeypatch, settings):
        """Closing stops only the worker that _p4k_worker holds, and one
        stopped from its dialog takes a moment to end."""
        made = MagicMock()
        monkeypatch.setattr(main_window, "P4kExtractWorker", made)
        assert MainWindow._run_p4k_extraction(_window(_p4k_worker=_Worker())) is False
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
    """Esc or X on the DataForge dialog asks: Stop or Cancel. The dialog stays
    modal while the run goes on, so nothing it depends on can change."""

    @pytest.fixture
    def box(self, monkeypatch):
        cls = MagicMock()
        box = cls.return_value
        box.choices = {name: MagicMock(name=name) for name in ("stop", "cancel")}
        box.addButton.side_effect = [box.choices["stop"], box.choices["cancel"]]
        monkeypatch.setattr(main_window, "QMessageBox", cls)
        return box

    @staticmethod
    def _answer(box, choice, meanwhile=None):
        box.exec.side_effect = lambda: meanwhile() if meanwhile else None
        box.clickedButton.return_value = box.choices[choice]

    @staticmethod
    def _setup():
        worker, dialog = _Worker(), MagicMock(name="dialog")
        worker.progress.connect(dialog.setLabelText)
        worker.progress_pct.connect(dialog.set_progress)
        worker.progress.connect(print)   # stands in for the status bar
        return worker, dialog, _window(_forge_worker=worker, _forge_progress_dialog=dialog)

    def test_an_extraction_that_is_over_closes_without_asking(self, box):
        worker = _Worker()
        me = _window(_forge_worker=None)
        assert MainWindow._confirm_stop_dataforge_extraction(me, worker) is True
        box.exec.assert_not_called()

    def test_cancel_keeps_the_dialog_and_the_run(self, box):
        self._answer(box, "cancel")
        worker, dialog, me = self._setup()
        assert MainWindow._confirm_stop_dataforge_extraction(me, worker) is False
        assert not worker.interrupted
        assert me._forge_progress_dialog is dialog
        assert dialog.set_progress in worker.progress_pct.slots
        me._end_simple_run.assert_not_called()

    def test_stop_stops_it_and_dismisses_the_dialog_for_good(self, box):
        self._answer(box, "stop")
        worker, dialog, me = self._setup()
        assert MainWindow._confirm_stop_dataforge_extraction(me, worker) is True
        assert worker.interrupted
        me.statusBar().showMessage.assert_called_with(tr("extract.dataforge_stopping"))
        # Whatever the worker does next, a Simple-mode run can't apply now,
        # but the Simple page stays busy until the stop has finished (the
        # finished slot ends the run), so its button never looks ready.
        assert me._simple_run_active is False
        me._end_simple_run.assert_not_called()
        # A hidden QProgressDialog comes back while progress keeps arriving.
        assert worker.progress.slots == [print] and worker.progress_pct.slots == []
        assert me._forge_progress_dialog is None
        dialog.deleteLater.assert_called_once_with()

    def test_stop_after_it_finished_meanwhile_still_keeps_simple_mode_from_applying(self, box):
        """The run finished while the question was open, so its slot already
        handed over to generation. There is nothing left to stop, but Stop
        must still keep a Simple-mode run from applying to the game."""
        worker, dialog, me = self._setup()
        self._answer(box, "stop", meanwhile=lambda: setattr(worker, "running", False))
        assert MainWindow._confirm_stop_dataforge_extraction(me, worker) is True
        assert not worker.interrupted
        me._end_simple_run.assert_called_once_with()
        dialog.deleteLater.assert_not_called()   # generation owns it now

    def test_the_question_and_its_safe_default(self, box):
        self._answer(box, "cancel")
        worker, _dialog, me = self._setup()
        MainWindow._confirm_stop_dataforge_extraction(me, worker)
        box.setWindowTitle.assert_called_once_with(tr("extract.dataforge_running_title"))
        box.setText.assert_called_once_with(tr("extract.dataforge_running_body"))
        assert box.addButton.call_count == 2   # Stop and Cancel, nothing else
        assert box.addButton.call_args_list[0].args[0] == tr("extract.dataforge_stop_btn")
        # Enter and Esc both mean Cancel: nothing is stopped by accident.
        box.setDefaultButton.assert_called_once_with(box.choices["cancel"])
        box.setEscapeButton.assert_called_once_with(box.choices["cancel"])


class TestDismissedDialogStaysHidden:
    """A hidden QProgressDialog shows itself again while progress keeps
    arriving (measured: within a second, after Esc as well as the X), so a
    dialog dismissed with Stop (or for a close) is detached from the
    worker. Real dialog, real worker signals."""

    @staticmethod
    def _keep_reporting(qapp, worker, seconds=2.0):
        # Slow progress, like the real snapshot: QProgressDialog shows a
        # hidden dialog again once its own estimate of the time left passes
        # its 4 s minimum duration (or the phase has run that long already).
        deadline = time.monotonic() + seconds
        step = 0
        while time.monotonic() < deadline:
            step += 1
            worker.progress_pct.emit(step * 100, 30000, "Snapshotting cache for diff…")
            worker.progress.emit("Snapshotting cache for diff…")
            qapp.processEvents()
            time.sleep(0.05)

    @staticmethod
    def _dialog(worker):
        dlg = AnimatedProgressDialog("Snapshotting cache for diff…", title="DataForge Extraction")
        worker.progress.connect(dlg.setLabelText)
        worker.progress_pct.connect(dlg.set_progress)
        worker.progress_pct.emit(0, 30000, "Snapshotting cache for diff…")
        return dlg

    def test_without_the_detach_it_comes_back(self, qapp):
        """The control: proves the next test can tell the two apart."""
        worker = _forge_worker()   # never started: its signals are emitted here
        dlg = self._dialog(worker)
        dlg.hide()
        self._keep_reporting(qapp, worker)
        try:
            assert dlg.isVisible()
        finally:
            dlg.close()
            dlg.deleteLater()

    def test_a_detached_dialog_stays_hidden(self, qapp):
        worker = _forge_worker()
        dlg = self._dialog(worker)
        MainWindow._detach_progress_dialog(worker, dlg)
        dlg.hide()
        self._keep_reporting(qapp, worker)
        try:
            assert not dlg.isVisible()
        finally:
            dlg.close()
            dlg.deleteLater()

    @staticmethod
    def _watch(qapp, dialog, seconds):
        """True if *dialog* shows itself within *seconds*."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            qapp.processEvents()
            if dialog.isVisible():
                return True
            time.sleep(0.02)
        return False

    @pytest.mark.parametrize("dismiss, comes_back", [("hide", True), ("cancel", False)])
    def test_a_young_dialog_comes_back_after_a_hide_but_not_a_cancel(
        self, qapp, dismiss, comes_back
    ):
        """Esc only hides, and a QProgressDialog under 4 s old shows itself
        again when its show timer fires, with no progress at all. The
        control (hide) proves the timer is real here; cancel() stops it."""
        dialog = AnimatedProgressDialog("Launching unp4k…", title="P4K Extraction")
        try:
            dialog.set_progress(0, 2, "Launching")
            qapp.processEvents()
            getattr(dialog, dismiss)()
            assert not dialog.isVisible()
            # 8 s: the timer fires about 4 s in, with room for a slow runner.
            assert self._watch(qapp, dialog, 8.0) is comes_back
        finally:
            dialog.close()
            dialog.deleteLater()
            qapp.processEvents()

    def test_esc_on_a_young_global_ini_dialog_stays_dismissed_while_it_stops(
        self, qapp
    ):
        """The global.ini stop (Esc) on a dialog under 4 s old, with the
        stop taking longer than that, must not let the dialog come back."""
        worker = _Worker()
        dialog = AnimatedProgressDialog("Launching unp4k…", title="P4K Extraction")
        me = _window(_p4k_worker=worker, _p4k_progress=dialog)
        dialog.set_close_guard(
            lambda w=worker: MainWindow._stop_p4k_extraction_from_dialog(me, w))
        try:
            dialog.set_progress(0, 2, "Launching")
            qapp.processEvents()
            QTest.keyClick(dialog, Qt.Key.Key_Escape)
            assert worker.interrupted and not dialog.isVisible()
            assert self._watch(qapp, dialog, 8.0) is False
        finally:
            dialog.set_close_guard(None)
            dialog.close()
            dialog.deleteLater()
            qapp.processEvents()

    def test_detaching_twice_is_harmless(self, qapp):
        worker = _forge_worker()
        dlg = self._dialog(worker)
        MainWindow._detach_progress_dialog(worker, dlg)
        MainWindow._detach_progress_dialog(worker, dlg)
        dlg.close()
        dlg.deleteLater()


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

    def test_the_global_ini_dialog_stops_it_on_esc_or_x(self, monkeypatch):
        made = []

        def make_worker(*args, **kwargs):
            made.append(_Worker(*args))
            return made[-1]

        dialog = MagicMock()
        monkeypatch.setattr(main_window, "AppSettings", MagicMock())
        monkeypatch.setattr(main_window, "P4kExtractWorker", make_worker)
        monkeypatch.setattr(main_window, "AnimatedProgressDialog", MagicMock(return_value=dialog))
        me = _window()
        me._stop_p4k_extraction_from_dialog.return_value = True

        assert MainWindow._run_p4k_extraction(me) is True

        worker = made[0]
        assert me._p4k_worker is worker and me._p4k_progress is dialog
        guard = dialog.set_close_guard.call_args.args[0]
        assert guard() is True
        me._stop_p4k_extraction_from_dialog.assert_called_once_with(worker)

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

    @pytest.mark.parametrize("simple_run", [False, True])
    def test_generation_that_ends_releases_the_simple_page(self, monkeypatch, simple_run):
        """A Stop that came too late to stop anything (the run had already
        finished) leaves the Simple page busy with no Simple run active. The
        generation that follows releases it, and still applies only for a
        real Simple run."""
        monkeypatch.setattr(main_window, "AppSettings", MagicMock())
        me = _window(_simple_run_active=simple_run)
        me._enhancements_progress_dialog = None
        me._enhancements_worker = MagicMock()

        MainWindow._on_enhancements_generation_finished(me, True)

        me._end_simple_run.assert_called_once_with()
        assert me.apply_to_game.called is simple_run
