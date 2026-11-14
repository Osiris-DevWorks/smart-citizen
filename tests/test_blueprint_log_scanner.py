"""Blueprint log scanner core (#222). Regex/parsing verified against real
Game.log / logbackups output (2026-07), and the Spanish notification (#564)
against a reporter's real Spanish log lines and the Spanish global.ini
``languages/sources.json`` maps (2026-11).

Pure parsing / filtering over fabricated log text and files — no SC install or
Qt needed. The workers and the MainWindow wiring of the notification's texts
are in ``test_blueprint_scan_language.py``.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.blueprint_log_scanner import (  # noqa: E402
    BLUEPRINT_EPOCH,
    ENGLISH_NOTIFICATION,
    NOTIFICATION_LOC_KEY,
    _loc_value,
    find_log_files,
    notification_templates,
    parse_events,
    scan_channel,
    scan_files,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]

NBSP = chr(0xA0)

# #564: the notification's text in the Spanish global.ini languages/sources.json
# maps (Thord82's), which a Spanish player's logs carry.
SPANISH = "Plano recibido: %s"
ENGLISH_AND_SPANISH = (ENGLISH_NOTIFICATION, SPANISH)


def _event(ts_iso: str, name: str, notif_id: int = 1) -> str:
    """One authoritative received-blueprint line, as SC writes it."""
    return (f"<{ts_iso}> [Notice] <SHUDEvent_OnNotification> Added notification "
            f'"Received Blueprint: {name}: " [{notif_id}] to queue. New queue size: 2, '
            "MissionId: [00000000-0000-0000-0000-000000000000], ObjectiveId: [] "
            "[Team_CoreGameplayFeatures][Missions][Comms]")


def _notification(ts_iso: str, text: str, notif_id: int = 1) -> str:
    """One "Added notification" line carrying *text*, as SC writes any
    notification, a blueprint or not (#564)."""
    return (f"<{ts_iso}> [Notice] <SHUDEvent_OnNotification> Added notification "
            f'"{text}: " [{notif_id}] to queue. New queue size: 2, '
            "MissionId: [00000000-0000-0000-0000-000000000000], ObjectiveId: [] "
            "[Team_CoreGameplayFeatures][Missions][Comms]")


def _event_as(template: str, ts_iso: str, name: str, notif_id: int = 1) -> str:
    """A received-blueprint line in the language *template* is the text of."""
    return _notification(ts_iso, template.replace("%s", name), notif_id)


def _names(events):
    return [e.name for e in events]


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


class TestOtherLanguages:
    """#564: the game logs the notification in the language it shows, so a
    notification is a received blueprint when its text matches one of the
    templates a scan is given (English alone by default)."""

    TS = "2026-11-13T00:41:23.867Z"

    def test_a_spanish_line_is_missed_with_english_alone(self):
        # The reported bug: nothing a Spanish player logged was found.
        assert list(parse_events(_event_as(SPANISH, self.TS, "Pistola Coda"))) == []

    def test_a_spanish_line_is_read_with_its_template(self):
        evs = list(parse_events(_event_as(SPANISH, self.TS, "Pistola Coda"), ENGLISH_AND_SPANISH))
        assert [(e.timestamp, e.name) for e in evs] == [(_dt(self.TS), "Pistola Coda")]

    def test_english_lines_are_still_read_beside_spanish_ones(self):
        # A player's older logs can be in English (the reporter's October
        # ones are), the newer ones in Spanish.
        text = "\n".join([
            _event("2026-10-19T22:28:47.907Z", "Sens"),
            _event_as(SPANISH, self.TS, "Pistola Coda"),
        ])
        assert _names(parse_events(text, ENGLISH_AND_SPANISH)) == ["Sens", "Pistola Coda"]

    @pytest.mark.parametrize("name", [
        'Pistola Coda "Nighthawk"',                        # its own quotes
        "Scalpel  cargador para Rifle Francotirador (12 cap)",   # a double space, kept
        "Cañón láser S3",
    ])
    def test_a_spanish_name_is_read_whole(self, name):
        line = _event_as(SPANISH, self.TS, name)
        assert _names(parse_events(line, ENGLISH_AND_SPANISH)) == [name]

    def test_text_after_the_name(self):
        template = "Bauplan %s erhalten!"
        line = _event_as(template, self.TS, "Coda-Pistole")
        assert _names(parse_events(line, (ENGLISH_NOTIFICATION, template))) == ["Coda-Pistole"]

    @pytest.mark.parametrize("logged", [
        "Plano recibido: Pistola Coda ",     # a name that ends in a space, as
                                             # "Antium Legs Moss Camo : " does
        " Plano recibido: Pistola Coda",     # a value with a space in front
    ])
    @pytest.mark.parametrize("template", [SPANISH, "  Plano recibido: %s  "])
    def test_spaces_around_a_template_or_the_text_do_not_count(self, logged, template):
        # A file can give the value with spaces around it (parse_ini_file
        # strips them, another tool's file may not), and the game logs it as
        # it shows it.
        line = _notification(self.TS, logged)
        assert _names(parse_events(line, (template,))) == ["Pistola Coda"]

    def test_a_template_that_holds_another_is_tried_first(self):
        # An override that adds to the English text, given in either order:
        # tried after English, its extra text would end up in the name.
        override = "Received Blueprint: %s (new)"
        line = _event_as(override, self.TS, "Coda Pistol")
        assert _names(parse_events(line, (ENGLISH_NOTIFICATION, override))) == ["Coda Pistol"]
        assert _names(parse_events(line, (override, ENGLISH_NOTIFICATION))) == ["Coda Pistol"]
        assert _names(parse_events(line)) == ["Coda Pistol (new)"]   # English alone, the control

    def test_other_notifications_are_not_blueprints(self):
        text = "\n".join([
            _notification(self.TS, "Contrato aceptado: Entrega"),
            _notification(self.TS, "Plano: Pistola Coda"),
            _notification(self.TS, "Received Blueprints: Coda Pistol"),
        ])
        assert list(parse_events(text, ENGLISH_AND_SPANISH)) == []

    def test_spanish_echo_and_continuation_lines_are_ignored(self):
        echo = (f"<{self.TS}> [Notice] <UpdateNotificationItem> "
                'Notification "Plano recibido: Pistola Coda: " [23], Action: Next')
        bare = f'<{self.TS}>    "Plano recibido: Pistola Coda: " [23]'
        assert list(parse_events(echo + "\n" + bare, ENGLISH_AND_SPANISH)) == []

    @pytest.mark.parametrize("template", [
        "%s",                          # would take every notification for a blueprint
        " %s: ",
        "Plano recibido",              # no name to read
        "Plano %s recibido: %s",       # two names
        "",
    ])
    def test_a_template_a_scan_cannot_use_is_left_out(self, template, caplog):
        lines = "\n".join([
            _notification(self.TS, template.replace("%s", "Pistola Coda")),
            _notification(self.TS, "Contrato aceptado: Entrega"),
        ])
        with caplog.at_level(logging.INFO, logger="src.utils.blueprint_log_scanner"):
            assert list(parse_events(lines, (template,))) == []
        assert f"not using the notification text {template!r}" in caplog.text


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

    def _spanish_player_log(self, tmp_path):
        """The reporter's shape (#564): English events in October, Spanish
        ones in November, each with its UI echo."""
        return self._write(tmp_path, "a.log", [
            _event("2026-10-19T22:28:47.907Z", "Sens", notif_id=118),
            '<2026-10-19T22:28:47.913Z> [Notice] <UpdateNotificationItem> '
            'Notification "Received Blueprint: Sens: " [118], Action: RemoveIgnore',
            _event_as(SPANISH, "2026-11-13T00:40:02.100Z", "Pistola Coda", notif_id=30),
            '<2026-11-13T00:40:09.000Z> [Notice] <UpdateNotificationItem> '
            'Notification "Plano recibido: Pistola Coda: " [30], Action: Next',
            _event_as(SPANISH, "2026-11-13T00:41:23.867Z", "Casco Antium", notif_id=31),
        ])

    def test_spanish_and_english_events_in_one_scan(self, tmp_path):
        res = scan_files([self._spanish_player_log(tmp_path)], templates=ENGLISH_AND_SPANISH)
        assert res.names == {"Sens", "Pistola Coda", "Casco Antium"}
        assert res.events_matched == 3
        assert res.latest_timestamp == _dt("2026-11-13T00:41:23.867Z")

    def test_english_alone_stops_at_the_last_english_event(self, tmp_path):
        # The control: what the scan did before #564, the watermark left at
        # the last English event.
        res = scan_files([self._spanish_player_log(tmp_path)])
        assert res.names == {"Sens"}
        assert res.latest_timestamp == _dt("2026-10-19T22:28:47.907Z")

    def test_a_watermark_left_at_the_last_english_event_finds_the_spanish_ones(self, tmp_path):
        # The reporter's next scan after the fix: the watermark an English-only
        # scan left behind, then the Spanish events after it.
        res = scan_files([self._spanish_player_log(tmp_path)],
                         since=_dt("2026-10-19T22:28:47.907Z"), templates=ENGLISH_AND_SPANISH)
        assert res.names == {"Pistola Coda", "Casco Antium"}

    def test_the_epoch_floor_holds_for_spanish_events(self, tmp_path):
        p = self._write(tmp_path, "a.log", [
            _event_as(SPANISH, "2026-02-15T10:00:00Z", "Antigua"),
            _event_as(SPANISH, "2026-03-05T10:00:00Z", "Pistola Coda"),
        ])
        assert scan_files([p], templates=ENGLISH_AND_SPANISH).names == {"Pistola Coda"}


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

    def test_scan_channel_hands_the_templates_on(self, tmp_path):
        live = tmp_path / "Game.log"
        live.write_text(_event_as(SPANISH, "2026-11-13T00:41:23.867Z", "Pistola Coda") + "\n",
                        encoding="utf-8")
        assert scan_channel(tmp_path).names == set()
        assert scan_channel(tmp_path, templates=ENGLISH_AND_SPANISH).names == {"Pistola Coda"}


class TestNotificationTemplates:
    """#564: English, then the notification's text from each loc file given."""

    KEY_LINE = f"{NOTIFICATION_LOC_KEY},P=Plano recibido: %s"

    def _ini(self, tmp_path, name, *lines, encoding="utf-8-sig"):
        p = tmp_path / name
        p.write_text("\n".join(lines) + "\n", encoding=encoding)
        return p

    def test_english_alone_without_files(self):
        assert notification_templates() == (ENGLISH_NOTIFICATION,)

    def test_each_files_text_follows_english_in_order(self, tmp_path):
        es = self._ini(tmp_path, "es.ini", "a,P=1", self.KEY_LINE, "b=2")
        de = self._ini(tmp_path, "de.ini", f"{NOTIFICATION_LOC_KEY}=Bauplan erhalten: %s")
        assert notification_templates([es, de]) == (
            ENGLISH_NOTIFICATION, SPANISH, "Bauplan erhalten: %s")

    def test_each_text_is_listed_once(self, tmp_path):
        es = self._ini(tmp_path, "es.ini", self.KEY_LINE)
        en = self._ini(tmp_path, "en.ini", f"{NOTIFICATION_LOC_KEY},P=Received Blueprint: %s")
        assert notification_templates([es, en, es]) == ENGLISH_AND_SPANISH

    def test_the_key_is_found_whatever_its_case_suffix_spaces_or_bom(self, tmp_path):
        crlf = tmp_path / "crlf.ini"
        crlf.write_bytes(("﻿" + NOTIFICATION_LOC_KEY.upper()
                          + " ,P =  Plano recibido: %s  \r\nnext=1\r\n").encode("utf-8"))
        assert notification_templates([crlf]) == ENGLISH_AND_SPANISH

    def test_files_that_give_nothing(self, tmp_path):
        missing = tmp_path / "gone.ini"
        without = self._ini(tmp_path, "without.ini", "other_key=Plano recibido: %s")
        empty = self._ini(tmp_path, "empty.ini", f"{NOTIFICATION_LOC_KEY}=")
        commented = self._ini(tmp_path, "commented.ini", ";" + self.KEY_LINE)
        a_folder = tmp_path / "folder.ini"
        a_folder.mkdir()
        assert notification_templates([missing, without, empty, commented, a_folder]) == (
            ENGLISH_NOTIFICATION,)

    def test_the_key_is_the_one_the_games_english_file_uses(self):
        # tests/fixtures/kraken_global_latest.ini is a whole global.ini:
        # the key is there, with the English text as its value.
        fixture = Path(__file__).resolve().parent / "fixtures" / "kraken_global_latest.ini"
        assert _loc_value(fixture, NOTIFICATION_LOC_KEY) == ENGLISH_NOTIFICATION


def test_epoch_constant_is_march_2026():
    assert BLUEPRINT_EPOCH == datetime(2026, 3, 1, tzinfo=timezone.utc)
