"""SCO: ``LiveBlueprintLogWorker``'s run loop on a real thread.

``GameLogTail`` itself is covered in ``test_game_log_tail.py``; this checks the
thread around it: new events reach the GUI thread as (names, newest
timestamp), a stop returns promptly, and a poll that raises neither ends
the thread nor logs a traceback every poll.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import pytest

from src.gui.workers import LiveBlueprintLogWorker
from src.utils.blueprint_log_scanner import GameLogTail

pytestmark = pytest.mark.unit


def _event(ts_iso: str, name: str) -> str:
    return (f"<{ts_iso}> [Notice] <SHUDEvent_OnNotification> Added notification "
            f'"Received Blueprint: {name}: " [7] to queue. New queue size: 1\n')


def _wait_for(qapp, condition, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        qapp.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def fast_poll(monkeypatch):
    monkeypatch.setattr(LiveBlueprintLogWorker, "POLL_MS", 200)


def test_new_events_arrive_and_a_stop_returns_promptly(qapp, tmp_path, fast_poll):
    log = tmp_path / "Game.log"
    log.write_text(_event("2026-10-07T20:01:00.000Z", "Agni"), encoding="utf-8")
    worker = LiveBlueprintLogWorker(log, None)
    found = []
    worker.blueprints_found.connect(lambda names, newest: found.append((names, newest)))
    worker.start()
    try:
        assert _wait_for(qapp, lambda: len(found) == 1)
        assert found[0] == (["Agni"], datetime(2026, 10, 7, 20, 1, tzinfo=timezone.utc))
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(_event("2026-10-07T20:05:00.000Z", "Norfield")
                     + _event("2026-10-07T20:06:00.000Z", "Bracer"))
        assert _wait_for(qapp, lambda: len(found) == 2)
        assert found[1] == (["Norfield", "Bracer"],
                            datetime(2026, 10, 7, 20, 6, tzinfo=timezone.utc))
    finally:
        worker.requestInterruption()
        started = time.monotonic()
        assert worker.wait(2000)
    assert time.monotonic() - started < 1.0


def test_a_failing_poll_keeps_the_thread_and_logs_one_traceback(
        qapp, tmp_path, fast_poll, monkeypatch, caplog):
    calls = []

    def broken(self):
        calls.append(True)
        raise RuntimeError("bad read")

    monkeypatch.setattr(GameLogTail, "poll", broken)
    worker = LiveBlueprintLogWorker(tmp_path / "Game.log", None)
    with caplog.at_level(logging.DEBUG, logger="src.gui.workers"):
        worker.start()
        try:
            assert _wait_for(qapp, lambda: len(calls) >= 3)
            assert worker.isRunning()
        finally:
            worker.requestInterruption()
            assert worker.wait(2000)
    failures = [r for r in caplog.records if "poll failed" in r.getMessage()]
    assert [r.levelno for r in failures][:1] == [logging.ERROR]
    assert all(r.levelno == logging.DEBUG for r in failures[1:]) and len(failures) >= 3
