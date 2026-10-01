"""AppliedStateWorker: the thin QThread around the already-applied check.

The logic it runs is covered in test_apply_already_applied.py; this runs the
real thread. Results are collected over a DirectConnection so no event loop
is needed (the slot runs on the worker thread, which is fine for a list
append), same offscreen-Qt approach as the other widget tests, no pytest-qt.
"""
from __future__ import annotations

import os
import threading

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.gui.workers import AppliedStateWorker  # noqa: E402

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _run(worker):
    results = []
    worker.finished.connect(results.append, Qt.ConnectionType.DirectConnection)
    worker.start()
    assert worker.wait(5000), "worker did not finish"
    return results


def test_emits_the_computed_verdict_once(qapp):
    worker = AppliedStateWorker(lambda snapshot, should_stop: True, "snapshot", 7)
    assert _run(worker) == [True]
    assert worker.result is True


def test_false_verdict_is_passed_through(qapp):
    worker = AppliedStateWorker(lambda snapshot, should_stop: False, "snapshot", 7)
    assert _run(worker) == [False]
    assert worker.result is False


def test_the_token_comes_back_untouched(qapp):
    """MainWindow compares it against its current token to spot a stale result."""
    worker = AppliedStateWorker(lambda snapshot, should_stop: True, "snapshot", 41)
    _run(worker)
    assert worker.token == 41


def test_the_snapshot_is_handed_to_the_compute_function_as_is(qapp):
    seen = []
    snapshot = object()

    def compute(snap, should_stop):
        seen.append(snap)
        return True

    _run(AppliedStateWorker(compute, snapshot, 1))
    assert seen == [snapshot]


def test_an_error_in_the_compute_function_reads_as_not_applied(qapp):
    """Any failure must land in the safe (red) direction, and the thread must
    still report back so MainWindow can release it."""
    def compute(snapshot, should_stop):
        raise RuntimeError("could not read the applied file")

    worker = AppliedStateWorker(compute, "snapshot", 1)
    assert _run(worker) == [False]
    assert worker.result is False


def test_a_truthy_non_bool_result_is_coerced(qapp):
    worker = AppliedStateWorker(lambda snapshot, should_stop: "yes", "snapshot", 1)
    assert _run(worker) == [True]


@pytest.mark.parametrize("interrupt, expected", [(False, False), (True, True)])
def test_should_stop_reflects_interruption_requests(qapp, interrupt, expected):
    """The compute function gets a callable it can poll between expensive
    steps; it must report True exactly when the thread was asked to stop."""
    gate = threading.Event()
    seen = []

    def compute(snapshot, should_stop):
        gate.wait(5)
        seen.append(should_stop())
        return False

    worker = AppliedStateWorker(compute, "snapshot", 1)
    results = []
    worker.finished.connect(results.append, Qt.ConnectionType.DirectConnection)
    worker.start()
    if interrupt:
        worker.requestInterruption()
    gate.set()
    assert worker.wait(5000)
    assert seen == [expected]
    assert results == [False]


# ── MainWindow's lifecycle on a real thread ──────────────────────────────────
# The fake-worker tests in test_apply_already_applied.py prove the decisions;
# these prove the Qt mechanics they rely on: the verdict really is delivered
# to the GUI thread through a queued lambda connection, the slot's worker.wait()
# doesn't deadlock, a disconnect on close really stops delivery, and a stale
# result from a real thread is dropped.

import time  # noqa: E402

from PyQt6.QtCore import QCoreApplication  # noqa: E402

import src.gui.main_window as main_window  # noqa: E402
from src.gui.main_window import MainWindow  # noqa: E402
from src.utils.settings import AppSettings  # noqa: E402


class _RealWindow:
    _refresh_apply_dirty_after_reload = MainWindow._refresh_apply_dirty_after_reload
    _invalidate_applied_check = MainWindow._invalidate_applied_check
    _launch_applied_state_check = MainWindow._launch_applied_state_check
    _on_applied_state_ready = MainWindow._on_applied_state_ready
    _apply_applied_state_verdict = MainWindow._apply_applied_state_verdict
    _settle_applied_state_check = MainWindow._settle_applied_state_check
    _mark_apply_dirty = MainWindow._mark_apply_dirty
    _mark_applied = MainWindow._mark_applied

    def __init__(self):
        self._applied_state_worker = None
        self._applied_check_token = 0
        self._applied_check_rerun_pending = False
        self._initial_load_done = True
        self._session_has_unapplied_edit = True
        self.dirty_calls = []
        self.dirty_threads = []

    def _apply_merge_inputs(self):
        return "merge-inputs"

    def _set_apply_btn_dirty(self, dirty):
        self.dirty_calls.append(dirty)
        self.dirty_threads.append(threading.current_thread())


@pytest.fixture
def real_window(qapp, monkeypatch):
    monkeypatch.setattr(AppSettings, "get_global_ini_path", staticmethod(lambda: "applied.ini"))
    monkeypatch.setattr(AppSettings, "get_game_install_path", staticmethod(lambda: "C:/SC/LIVE"))
    monkeypatch.setattr(AppSettings, "get_selected_language", staticmethod(lambda: "french"))
    return _RealWindow()


def _pump(condition, timeout=5.0):
    """Run the Qt event loop (which delivers queued cross-thread signals)
    until *condition* holds."""
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    assert condition(), "timed out waiting for the background check"


def _idle(window):
    return window._applied_state_worker is None


def test_the_verdict_reaches_the_gui_thread_through_the_real_signal(real_window, monkeypatch):
    monkeypatch.setattr(main_window, "_compute_already_applied", lambda snapshot, should_stop: True)
    real_window._refresh_apply_dirty_after_reload()
    _pump(lambda: _idle(real_window))

    assert real_window.dirty_calls == [False]
    assert real_window._session_has_unapplied_edit is False
    assert real_window.dirty_threads == [threading.main_thread()]


def test_an_edit_while_the_thread_is_running_discards_its_verdict(real_window, monkeypatch):
    gate = threading.Event()

    def compute(snapshot, should_stop):
        gate.wait(5)
        return True  # would read green, from a snapshot that predates the edit

    monkeypatch.setattr(main_window, "_compute_already_applied", compute)
    real_window._refresh_apply_dirty_after_reload()
    real_window._mark_apply_dirty()  # the user edits a cell
    gate.set()
    _pump(lambda: _idle(real_window))

    assert real_window.dirty_calls == [True]  # only the edit's red


def test_a_reload_mid_check_interrupts_it_and_reruns_on_a_second_thread(real_window, monkeypatch):
    first_gate = threading.Event()
    calls = []

    def compute(snapshot, should_stop):
        calls.append(len(calls))
        if len(calls) == 1:
            first_gate.wait(5)
            calls.append(("first saw stop", should_stop()))
            return True  # superseded: must be ignored
        return False

    monkeypatch.setattr(main_window, "_compute_already_applied", compute)
    real_window._refresh_apply_dirty_after_reload()
    first = real_window._applied_state_worker
    _pump(lambda: len(calls) >= 1)
    real_window._refresh_apply_dirty_after_reload()  # a second reload arrives mid-check
    assert first.isInterruptionRequested()
    assert real_window._applied_state_worker is first  # still one thread at a time
    first_gate.set()
    _pump(lambda: _idle(real_window) and len(calls) >= 3)

    assert ("first saw stop", True) in calls
    assert real_window.dirty_calls == [True]  # only the rerun's verdict landed


def test_settling_waits_for_a_real_running_check_and_applies_its_verdict(real_window, monkeypatch):
    def compute(snapshot, should_stop):
        time.sleep(0.2)
        return True

    monkeypatch.setattr(main_window, "_compute_already_applied", compute)
    real_window._refresh_apply_dirty_after_reload()
    real_window._settle_applied_state_check()  # what closeEvent does; blocks until done

    assert real_window.dirty_calls == [False]
    assert real_window._applied_state_worker is None
    # Any signal Qt had already queued must not deliver a second verdict.
    for _ in range(20):
        QCoreApplication.processEvents()
        time.sleep(0.005)
    assert real_window.dirty_calls == [False]


def test_settling_with_a_pending_rerun_does_not_start_another_thread(real_window, monkeypatch):
    gate = threading.Event()
    started = []

    def compute(snapshot, should_stop):
        started.append(1)
        gate.wait(5)
        return False

    monkeypatch.setattr(main_window, "_compute_already_applied", compute)
    real_window._refresh_apply_dirty_after_reload()
    _pump(lambda: len(started) == 1)
    real_window._refresh_apply_dirty_after_reload()  # rerun now queued behind it
    gate.set()
    real_window._settle_applied_state_check()
    for _ in range(20):
        QCoreApplication.processEvents()
        time.sleep(0.005)

    assert started == [1]  # no second compute ever started
    assert real_window._applied_state_worker is None
