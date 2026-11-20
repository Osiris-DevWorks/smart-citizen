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
from src.utils import blueprint_log_scanner
from src.utils.blueprint_log_scanner import NOTIFICATION_LOC_KEY, GameLogTail
from tests.event_loop import pump_until

pytestmark = pytest.mark.unit


def _event(ts_iso: str, name: str) -> str:
    return (f"<{ts_iso}> [Notice] <SHUDEvent_OnNotification> Added notification "
            f'"Received Blueprint: {name}: " [7] to queue. New queue size: 1\n')


def _spanish_event(ts_iso: str, name: str) -> str:
    return (f"<{ts_iso}> [Notice] <SHUDEvent_OnNotification> Added notification "
            f'"Plano recibido: {name}: " [8] to queue. New queue size: 1\n')


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
        assert pump_until(lambda: len(found) == 1, 5.0)
        assert found[0] == (["Agni"], datetime(2026, 10, 7, 20, 1, tzinfo=timezone.utc))
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(_event("2026-10-07T20:05:00.000Z", "Norfield")
                     + _event("2026-10-07T20:06:00.000Z", "Bracer"))
        assert pump_until(lambda: len(found) == 2, 5.0)
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
            assert pump_until(lambda: len(calls) >= 3, 5.0)
            assert worker.isRunning()
        finally:
            worker.requestInterruption()
            assert worker.wait(2000)
    failures = [r for r in caplog.records if "poll failed" in r.getMessage()]
    assert [r.levelno for r in failures][:1] == [logging.ERROR]
    assert all(r.levelno == logging.DEBUG for r in failures[1:]) and len(failures) >= 3


def test_the_watch_reads_the_notification_text_from_its_loc_files(
        qapp, tmp_path, fast_poll, caplog):
    """#564: the worker reads the notification's text from the files MainWindow
    names, on its own thread, so a Spanish player's blueprints are found,
    English ones still are, and a file that is not there is passed over."""
    base_ini = tmp_path / "base.ini"
    base_ini.write_text(f"{NOTIFICATION_LOC_KEY},P=Plano recibido: %s\n", encoding="utf-8-sig")
    log = tmp_path / "Game.log"
    log.write_text(_spanish_event("2026-11-13T00:41:23.867Z", "Pistola Coda")
                   + _event("2026-11-13T00:42:00.000Z", "Agni"), encoding="utf-8")
    worker = LiveBlueprintLogWorker(log, None, (base_ini, tmp_path / "not-applied.ini"))
    found = []
    worker.blueprints_found.connect(lambda names, newest: found.append(names))
    with caplog.at_level(logging.INFO, logger="src.gui.workers"):
        worker.start()
        try:
            assert pump_until(lambda: len(found) == 1, 5.0)
        finally:
            worker.requestInterruption()
            assert worker.wait(2000)
    assert found == [["Pistola Coda", "Agni"]]
    assert "'Received Blueprint: %s', 'Plano recibido: %s'" in caplog.text


def test_a_failure_reading_the_texts_keeps_the_watch_on_english(
        qapp, tmp_path, fast_poll, monkeypatch, caplog):
    """#564 review: the texts are read outside the poll's own guard, so a
    failure there is caught where it happens. The watch goes on with English
    alone and logs one traceback at WARNING, rather than the thread ending,
    and nothing at ERROR, which would open the error box over the game."""
    def broken(loc_files):
        raise RuntimeError("bad loc file")

    monkeypatch.setattr(blueprint_log_scanner, "notification_templates", broken)
    log = tmp_path / "Game.log"
    log.write_text(_spanish_event("2026-11-13T00:41:23.867Z", "Pistola Coda")
                   + _event("2026-11-13T00:42:00.000Z", "Agni"), encoding="utf-8")
    worker = LiveBlueprintLogWorker(log, None, (tmp_path / "base.ini",))
    found = []
    worker.blueprints_found.connect(lambda names, newest: found.append(names))
    with caplog.at_level(logging.DEBUG, logger="src.gui.workers"):
        worker.start()
        try:
            assert pump_until(lambda: len(found) == 1, 5.0)
            assert worker.isRunning()
        finally:
            worker.requestInterruption()
            assert worker.wait(2000)
    assert found == [["Agni"]]
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    warned = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warned) == 1 and warned[0].exc_info is not None
    assert "watching for English alone" in warned[0].getMessage()
