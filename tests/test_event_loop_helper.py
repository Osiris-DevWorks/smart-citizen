"""tests/event_loop.py's ``pump_until``, the one loop the tests run the Qt
event loop with while they wait for a queued slot (perf proposal review: it
replaced a copy each in test_applied_state_worker.py, test_extraction_stop.py,
test_live_blueprint_log_worker.py and test_pending_cache_cleanup.py).

A signal from a real thread reaches a slot on the GUI thread only while the
loop runs, and the helper returns as soon as the condition holds, asks once
more at the deadline and otherwise gives up there. Offscreen Qt via the
session ``qapp`` fixture, no pytest-qt.
"""
from __future__ import annotations

import threading
import time

import pytest

from PyQt6.QtCore import QThread, pyqtSignal

import tests.event_loop as event_loop
from tests.event_loop import pump_until

pytestmark = pytest.mark.unit


class _Emitter(QThread):
    said = pyqtSignal(int)

    def run(self):
        self.said.emit(7)


def test_a_signal_from_a_real_thread_reaches_the_gui_thread(qapp):
    """Queued: nothing arrives until the loop runs, and then on the GUI
    thread."""
    got = []
    thread = _Emitter()
    thread.said.connect(lambda value: got.append((value, threading.get_ident())))
    thread.start()
    assert thread.wait(5000)
    assert got == []
    assert pump_until(lambda: got != [], seconds=5)
    assert got == [(7, threading.get_ident())]


def test_it_returns_as_soon_as_the_condition_holds(qapp):
    asked = []

    def third_time():
        asked.append(1)
        return len(asked) == 3

    started = time.monotonic()
    assert pump_until(third_time, seconds=5) is True
    assert len(asked) == 3
    assert time.monotonic() - started < 1


def test_it_gives_up_at_the_deadline(qapp):
    started = time.monotonic()
    assert pump_until(lambda: False, seconds=0.2) is False
    assert 0.2 <= time.monotonic() - started < 2


class _Clock:
    """Stands in for the helper's ``time``: each sleep moves it on."""

    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_it_asks_once_more_at_the_deadline(qapp, monkeypatch):
    """A condition that turns true just as the time runs out still counts.
    Inside the loop the clock is always short of the deadline, so only the
    last ask can see it true."""
    clock = _Clock()
    monkeypatch.setattr(event_loop, "time", clock)
    asked_at = []

    def from_the_deadline_on():
        asked_at.append(clock.now)
        return clock.now >= 0.2

    assert pump_until(from_the_deadline_on, seconds=0.2) is True
    assert all(now < 0.2 for now in asked_at[:-1]) and asked_at[-1] >= 0.2
