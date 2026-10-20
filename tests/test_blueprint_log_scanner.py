"""Blueprint log scanner core (#222). Regex/parsing verified against real
Game.log / logbackups output (2026-07).

Pure parsing / filtering over fabricated log text and files — no SC install or
Qt needed. The worker (``BlueprintLogScanWorker``) and the MainWindow slot that
folds names into the owned set stay manual-test only (they need pytest-qt).
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.blueprint_log_scanner import (  # noqa: E402
    BLUEPRINT_EPOCH,
    find_log_files,
    parse_events,
    scan_channel,
    scan_files,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]

NBSP = chr(0xA0)


def _event(ts_iso: str, name: str, notif_id: int = 1) -> str:
    """One authoritative received-blueprint line, as SC writes it."""
    return (f"<{ts_iso}> [Notice] <SHUDEvent_OnNotification> Added notification "
            f'"Received Blueprint: {name}: " [{notif_id}] to queue. New queue size: 2, '
            "MissionId: [00000000-0000-0000-0000-000000000000], ObjectiveId: [] "
            "[Team_CoreGameplayFeatures][Missions][Comms]")


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class TestParseEvents:
    def test_single_event(self):
        evs = list(parse_events(_event("2026-03-26T17:15:41.684Z", "Coda Pistol")))
        assert len(evs) == 1
        assert evs[0].name == "Coda Pistol"
        assert evs[0].timestamp == _dt("2026-03-26T17:15:41.684Z")

    def test_embedded_quotes_survive(self):
        # Paint/skin variant names carry their own literal quotes — a naive
        # capture-to-next-quote would truncate at "Demeco.
        name = 'Demeco "Purgatory Camo" LMG'
        evs = list(parse_events(_event("2026-03-27T00:18:06.320Z", name)))
        assert evs[0].name == name  # non-greedy stops at the trailing `: "`

    def test_nbsp_preserved_raw(self):
        # The scanner returns raw names; nbsp folding is the normalizer's job
        # (owned_items.normalize_item_name).
        evs = list(parse_events(_event("2026-03-26T23:59:59.272Z", "Lynx" + NBSP + "Legs")))
        assert NBSP in evs[0].name

    def test_ignores_update_notification_echo(self):
        # The UI-echo line quotes the same text but is not the authoritative
        # event — it must not produce a duplicate.
        echo = ('<2026-03-26T17:15:47.126Z> [Notice] <UpdateNotificationItem> '
                'Notification "Received Blueprint: Coda Pistol: " [23], Action: Next')
        assert list(parse_events(echo)) == []

    def test_ignores_bare_continuation_line(self):
        bare = '<2026-03-26T17:15:41.684Z>    "Received Blueprint: Coda Pistol: " [23]'
        assert list(parse_events(bare)) == []

    def test_unrelated_blueprint_mentions_ignored(self):
        text = (
            '<2026-06-07T04:27:45.846Z> [Notice] <ReuseChannel> Reusing channel '
            "for 'sc.external.services.blueprint_library.v1.BlueprintLibraryService' "
            "to endpoint pub-sc-alpha.example.com:443 (transport security: 1) "
            "[Team_OnlineTech][gRPC]"
        )
        assert list(parse_events(text)) == []

    def test_no_fractional_seconds(self):
        evs = list(parse_events(_event("2026-03-26T17:15:41Z", "F55 LMG")))
        assert evs[0].timestamp == _dt("2026-03-26T17:15:41Z")

    def test_malformed_timestamp_skipped(self):
        bad = _event("2026-13-99T99:99:99Z", "Nope")
        assert list(parse_events(bad)) == []

    def test_empty_text(self):
        assert list(parse_events("")) == []


class TestScanFiles:
    def _write(self, tmp_path, name, lines):
        p = tmp_path / name
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return p

    def test_epoch_floor_drops_pre_march_2026(self, tmp_path):
        p = self._write(tmp_path, "a.log", [
            _event("2026-02-15T10:00:00Z", "Ancient"),   # before epoch
            _event("2026-03-05T10:00:00Z", "Kept"),
        ])
        res = scan_files([p])
        assert res.names == {"Kept"}
        assert res.events_matched == 1

    def test_watermark_is_exclusive(self, tmp_path):
        wm = _dt("2026-03-10T00:00:00Z")
        p = self._write(tmp_path, "a.log", [
            _event("2026-03-10T00:00:00Z", "AtWatermark"),   # == since -> skipped
            _event("2026-03-11T00:00:00Z", "AfterWatermark"),
        ])
        res = scan_files([p], since=wm)
        assert res.names == {"AfterWatermark"}

    def test_latest_ignores_watermark(self, tmp_path):
        # latest_timestamp tracks the newest at/after-epoch event even when the
        # watermark filters it out of `names`, so the mark advances monotonically.
        wm = _dt("2026-04-01T00:00:00Z")
        p = self._write(tmp_path, "a.log", [_event("2026-03-15T00:00:00Z", "Old")])
        res = scan_files([p], since=wm)
        assert res.names == set()
        assert res.latest_timestamp == _dt("2026-03-15T00:00:00Z")

    def test_dedup_across_files(self, tmp_path):
        a = self._write(tmp_path, "a.log", [_event("2026-03-05T10:00:00Z", "Coda Pistol")])
        b = self._write(tmp_path, "b.log", [_event("2026-03-06T10:00:00Z", "Coda Pistol")])
        res = scan_files([a, b])
        assert res.names == {"Coda Pistol"}
        assert res.events_matched == 2  # both events counted, one unique name

    def test_repeated_notification_events_dedupe(self, tmp_path):
        # A single earned blueprint fires 4 log lines (queued + Next/
        # StartFade/Remove), all with identical notification text; only the
        # authoritative SHUDEvent_OnNotification line counts.
        p = self._write(tmp_path, "a.log", [
            _event("2026-03-09T07:54:03.720Z", "Torrez", notif_id=5),
            '<2026-03-09T07:54:18.830Z> [Notice] <UpdateNotificationItem> '
            'Notification "Received Blueprint: Torrez: " [5], Action: Next',
            '<2026-03-09T07:54:23.847Z> [Notice] <UpdateNotificationItem> '
            'Notification "Received Blueprint: Torrez: " [5], Action: StartFade',
        ])
        res = scan_files([p])
        assert res.names == {"Torrez"}
        assert res.events_matched == 1

    def test_latest_timestamp_is_max(self, tmp_path):
        p = self._write(tmp_path, "a.log", [
            _event("2026-03-05T10:00:00Z", "A"),
            _event("2026-03-20T10:00:00Z", "B"),
            _event("2026-03-12T10:00:00Z", "C"),
        ])
        res = scan_files([p])
        assert res.latest_timestamp == _dt("2026-03-20T10:00:00Z")

    def test_empty_result_when_no_events(self, tmp_path):
        p = self._write(tmp_path, "a.log", ["just noise", "nothing to see"])
        res = scan_files([p])
        assert res.names == set()
        assert res.latest_timestamp is None
        assert res.files_scanned == 1

    def test_progress_callback_invoked(self, tmp_path):
        a = self._write(tmp_path, "a.log", [_event("2026-03-05T10:00:00Z", "A")])
        calls = []
        scan_files([a], progress=lambda done, total, name: calls.append((done, total, name)))
        assert calls[0] == (0, 1, "a.log")
        assert calls[-1] == (1, 1, "")   # terminal 100% tick

    def test_missing_file_tolerated(self, tmp_path):
        good = self._write(tmp_path, "a.log", [_event("2026-03-05T10:00:00Z", "A")])
        res = scan_files([tmp_path / "gone.log", good])
        assert res.names == {"A"}

    def test_empty_paths_yields_empty_result(self):
        res = scan_files([])
        assert res.names == set()
        assert res.files_scanned == 0


class TestFindLogFiles:
    def _touch(self, path, when: datetime, body="x"):
        path.write_text(body, encoding="utf-8")
        os.utime(path, (when.timestamp(), when.timestamp()))

    def test_discovers_logbackups_and_live_game_log(self, tmp_path):
        backups = tmp_path / "logbackups"
        backups.mkdir()
        self._touch(backups / "old.log", _dt("2026-03-10T00:00:00Z"))
        self._touch(tmp_path / "Game.log", _dt("2026-03-20T00:00:00Z"))
        names = [p.name for p in find_log_files(tmp_path)]
        assert names == ["old.log", "Game.log"]  # oldest-first

    def test_no_live_log_present(self, tmp_path):
        backups = tmp_path / "logbackups"
        backups.mkdir()
        self._touch(backups / "x.log", _dt("2026-03-10T00:00:00Z"))
        assert [p.name for p in find_log_files(tmp_path)] == ["x.log"]

    def test_mtime_prefilter_drops_pre_epoch_files(self, tmp_path):
        backups = tmp_path / "logbackups"
        backups.mkdir()
        self._touch(backups / "ancient.log", _dt("2026-01-01T00:00:00Z"))  # < epoch
        self._touch(backups / "recent.log", _dt("2026-03-15T00:00:00Z"))
        names = [p.name for p in find_log_files(tmp_path)]
        assert names == ["recent.log"]

    def test_mtime_prefilter_uses_watermark_when_later(self, tmp_path):
        backups = tmp_path / "logbackups"
        backups.mkdir()
        self._touch(backups / "before.log", _dt("2026-03-05T00:00:00Z"))
        self._touch(backups / "after.log", _dt("2026-05-01T00:00:00Z"))
        since = _dt("2026-04-01T00:00:00Z")
        names = [p.name for p in find_log_files(tmp_path, since=since)]
        assert names == ["after.log"]

    def test_missing_directory_yields_empty(self, tmp_path):
        assert find_log_files(tmp_path / "nonexistent") == []


class TestScanChannel:
    def test_scan_channel_end_to_end(self, tmp_path):
        backups = tmp_path / "logbackups"
        backups.mkdir()
        (backups / "a.log").write_text(_event("2026-03-05T10:00:00Z", "Coda Pistol") + "\n",
                                       encoding="utf-8")
        os.utime(backups / "a.log", (_dt("2026-03-05T10:00:00Z").timestamp(),) * 2)
        res = scan_channel(tmp_path)
        assert res.names == {"Coda Pistol"}
        assert res.files_scanned == 1


def test_epoch_constant_is_march_2026():
    assert BLUEPRINT_EPOCH == datetime(2026, 3, 1, tzinfo=timezone.utc)
