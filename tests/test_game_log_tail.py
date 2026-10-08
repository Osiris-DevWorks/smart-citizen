"""Smart Citizen Overlay (SCO): live Game.log blueprint tail.

``GameLogTail`` reads only appended bytes per poll, buffers a half-written
trailing line, restarts on rotation, and honours the watermark and epoch
floor. Fabricated logs via ``tmp_path``; no SC install or Qt.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.utils.blueprint_log_scanner import GameLogTail

pytestmark = [pytest.mark.unit]


def _event(ts_iso: str, name: str) -> str:
    return (f"<{ts_iso}> [Notice] <SHUDEvent_OnNotification> Added notification "
            f'"Received Blueprint: {name}: " [7] to queue. New queue size: 1\n')


def _append(path, text):
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(text)


def _names(events):
    return [e.name for e in events]


def test_reads_only_new_lines(tmp_path):
    log = tmp_path / "Game.log"
    log.write_text("<2026-10-07T20:00:00.000Z> boot\n" + _event("2026-10-07T20:01:00.000Z", "Agni"))
    tail = GameLogTail(log)
    assert _names(tail.poll()) == ["Agni"]
    assert tail.poll() == []
    _append(log, _event("2026-10-07T20:05:00.000Z", "Norfield"))
    assert _names(tail.poll()) == ["Norfield"]


def test_half_written_line_waits_for_its_newline(tmp_path):
    log = tmp_path / "Game.log"
    line = _event("2026-10-07T20:01:00.000Z", "Agni")
    log.write_text(line[:40])
    tail = GameLogTail(log)
    assert tail.poll() == []
    _append(log, line[40:])
    assert _names(tail.poll()) == ["Agni"]


def test_rotation_restarts_from_the_top(tmp_path):
    log = tmp_path / "Game.log"
    log.write_text("x" * 500 + "\n" + _event("2026-10-07T20:01:00.000Z", "Agni"))
    tail = GameLogTail(log)
    tail.poll()
    log.unlink()
    assert tail.poll() == []            # between rotation and the new file
    log.write_text(_event("2026-10-07T21:00:00.000Z", "Norfield"))
    assert _names(tail.poll()) == ["Norfield"]


def test_shrunk_file_counts_as_rotation(tmp_path):
    log = tmp_path / "Game.log"
    log.write_text("x" * 500 + "\n")
    tail = GameLogTail(log)
    tail.poll()
    log.write_text(_event("2026-10-07T21:00:00.000Z", "Norfield"))
    assert _names(tail.poll()) == ["Norfield"]


def test_watermark_and_epoch_filter(tmp_path):
    log = tmp_path / "Game.log"
    log.write_text(
        _event("2025-12-01T00:00:00.000Z", "Ancient")        # before blueprints existed
        + _event("2026-10-07T20:00:00.000Z", "AlreadySeen")  # at the watermark
        + _event("2026-10-07T20:30:00.000Z", "Fresh")
    )
    tail = GameLogTail(log, since=datetime(2026, 10, 7, 20, 0, tzinfo=timezone.utc))
    assert _names(tail.poll()) == ["Fresh"]


def test_watermark_advances_so_a_reread_never_double_counts(tmp_path):
    log = tmp_path / "Game.log"
    text = _event("2026-10-07T20:30:00.000Z", "Fresh")
    log.write_text(text)
    tail = GameLogTail(log)
    assert _names(tail.poll()) == ["Fresh"]
    log.write_text("")                  # rotate, then the same content reappears
    tail.poll()
    log.write_text(text)
    assert tail.poll() == []


def test_missing_file_is_quiet(tmp_path):
    assert GameLogTail(tmp_path / "Game.log").poll() == []
