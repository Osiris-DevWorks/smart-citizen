"""#564: "Scan Logs for Owned Blueprints" and the overlay's live watch find the
"Received Blueprint" notification in the language the game shows.

The game logs the notification as it shows it, from the loc key
``crafting_hud_notification_received_blueprint``: a player who plays in
Spanish logs ``"Plano recibido: <name>: "``, which a scan that looked for the
English text alone never found. MainWindow names the files that hold the
key's text for the channel being read (``_blueprint_notification_files``: that
channel's base.ini for the selected language and the English one, and the
global.ini applied to that channel's game), and each worker reads them on its
own thread.

Real settings under ``tmp_path`` (conftest's ``tmp_profile``), real files and
the real scan worker on a real thread. The matching itself is in
``test_blueprint_log_scanner.py`` and ``test_game_log_tail.py``, the live
worker's run in ``test_live_blueprint_log_worker.py``, both start sites
handing the files on in ``test_blueprint_scan_channels.py`` and
``test_overlay_tab.py``, and the settings paths in ``test_language_paths.py``.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest
from PyQt6.QtCore import Qt

from src.gui import main_window
from src.gui.workers import BlueprintLogScanWorker
from src.utils import blueprint_log_scanner
from src.utils.blueprint_log_scanner import NOTIFICATION_LOC_KEY
from src.utils.settings import AppSettings

pytestmark = pytest.mark.unit

SPANISH = "Plano recibido: %s"


def _notification(ts_iso, text, notif_id):
    """An "Added notification" line as the game writes it."""
    return (f"<{ts_iso}> [Notice] <SHUDEvent_OnNotification> Added notification "
            f'"{text}: " [{notif_id}] to queue. New queue size: 1, '
            "MissionId: [00000000-0000-0000-0000-000000000000], ObjectiveId: [] "
            "[Team_CoreGameplayFeatures][Missions][Comms]\n")


def _write_loc(path, value):
    """A global.ini-shaped file that gives the notification key *value*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"a,P=1\n{NOTIFICATION_LOC_KEY},P={value}\nb,P=2\n", encoding="utf-8-sig")


def _everything_under(folder):
    return sorted(str(p.relative_to(folder)) for p in folder.rglob("*"))


@pytest.fixture
def spanish_player(tmp_profile):
    """LIVE's logs as the reporter's are: blueprints in English in October,
    in Spanish in November. Returns LIVE's install folder."""
    live = tmp_profile / "StarCitizen" / "LIVE"
    (live / "logbackups").mkdir()
    (live / "logbackups" / "Game Build(12913470) 19 Oct 26 (22 58 53).log").write_text(
        _notification("2026-10-19T22:28:47.907Z", "Received Blueprint: Sens", 118),
        encoding="utf-8")
    (live / "Game.log").write_text(
        _notification("2026-11-13T00:40:02.100Z", "Plano recibido: Pistola Coda", 30)
        + _notification("2026-11-13T00:41:23.867Z", "Plano recibido: Casco Antium", 31),
        encoding="utf-8")
    return live


def _scan(channel_dir, loc_files):
    """BlueprintLogScanWorker on a real thread, as MainWindow starts it: its
    one ScanResult."""
    worker = BlueprintLogScanWorker(str(channel_dir), None, loc_files)
    results = []
    worker.finished.connect(results.append, Qt.ConnectionType.DirectConnection)
    worker.start()
    assert worker.wait(10000)
    assert len(results) == 1 and results[0] is not None
    return results[0]


class TestTheFilesMainWindowNames:
    def test_spanish_once_its_file_is_fetched(self, tmp_profile):
        AppSettings.set_selected_language("spanish")
        _write_loc(AppSettings.get_base_ini_path("spanish"), SPANISH)
        live = tmp_profile / "StarCitizen" / "LIVE"
        assert main_window._blueprint_notification_files("LIVE", live) == (
            tmp_profile / "data" / "LIVE" / "cache" / "lang" / "spanish" / "base.ini",
            live / "data" / "Localization" / "spanish_(spain)" / "global.ini",
        )

    def test_spanish_before_its_file_is_fetched(self, tmp_profile):
        # The English base.ini, which the table reads until then (#502).
        AppSettings.set_selected_language("spanish")
        live = tmp_profile / "StarCitizen" / "LIVE"
        assert main_window._blueprint_notification_files("LIVE", live) == (
            tmp_profile / "data" / "LIVE" / "cache" / "base.ini",
            live / "data" / "Localization" / "spanish_(spain)" / "global.ini",
        )

    def test_english(self, tmp_profile):
        live = tmp_profile / "StarCitizen" / "LIVE"
        assert main_window._blueprint_notification_files("LIVE", live) == (
            tmp_profile / "data" / "LIVE" / "cache" / "base.ini",
            live / "data" / "Localization" / "english" / "global.ini",
        )

    def test_the_channel_read_whichever_channel_is_selected(self, tmp_profile):
        # A scan reads LIVE and HOTFIX whatever Config has selected, so each
        # is read with its own files, never the selected channel's, even when
        # the selected channel has the language's file too.
        AppSettings.set_active_channel("PTU")
        AppSettings.set_selected_language("spanish")
        _write_loc(AppSettings.get_base_ini_path("spanish"), SPANISH)          # PTU's
        _write_loc(AppSettings.get_base_ini_leaf("spanish", "HOTFIX"), SPANISH)
        hotfix = tmp_profile / "StarCitizen" / "HOTFIX"
        assert main_window._blueprint_notification_files("HOTFIX", hotfix) == (
            tmp_profile / "data" / "HOTFIX" / "cache" / "lang" / "spanish" / "base.ini",
            hotfix / "data" / "Localization" / "spanish_(spain)" / "global.ini",
        )

    def test_no_folder_is_made(self, tmp_profile):
        AppSettings.set_selected_language("spanish")
        AppSettings.get_user_data_dir()          # the data folder itself is made at every start
        before = _everything_under(tmp_profile)
        main_window._blueprint_notification_files("HOTFIX", tmp_profile / "StarCitizen" / "HOTFIX")
        main_window._blueprint_notification_files("LIVE", tmp_profile / "StarCitizen" / "LIVE")
        assert _everything_under(tmp_profile) == before

    def test_a_data_folder_that_cannot_be_reached_leaves_the_applied_file(
            self, tmp_profile, monkeypatch, caplog):
        # The scan reads the install's logs, so it must not fail on the data
        # folder: what the game shows is still read from the applied file.
        monkeypatch.setattr(main_window, "_data_folder_warning", "")
        AppSettings.set_selected_language("spanish")

        def unreachable():
            raise PermissionError(13, "Access is denied", str(tmp_profile / "data"))

        monkeypatch.setattr(AppSettings, "get_user_data_dir", staticmethod(unreachable))
        live = tmp_profile / "StarCitizen" / "LIVE"
        with caplog.at_level(logging.DEBUG):
            files = main_window._blueprint_notification_files("LIVE", live)
        assert files == (live / "data" / "Localization" / "spanish_(spain)" / "global.ini",)
        warned = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert [(r.name, r.levelno) for r in warned] == [("src.gui.main_window", logging.WARNING)]
        assert "data folder could not be reached" in warned[0].getMessage()

    def test_a_language_file_that_cannot_be_checked_leaves_the_applied_file(
            self, tmp_profile, monkeypatch, caplog):
        # Seeing whether the language's own file is there can raise as well
        # (Path.exists passes a PermissionError on), with the data folder
        # itself fine: handled the same way, never out of the scan's start.
        monkeypatch.setattr(main_window, "_data_folder_warning", "")
        AppSettings.set_selected_language("spanish")
        spanish = AppSettings.get_base_ini_leaf("spanish", "LIVE")
        real_exists = Path.exists

        def refused(self, *args, **kwargs):
            if self == spanish:
                raise PermissionError(13, "Access is denied", str(self))
            return real_exists(self, *args, **kwargs)

        monkeypatch.setattr(Path, "exists", refused)
        live = tmp_profile / "StarCitizen" / "LIVE"
        with caplog.at_level(logging.DEBUG):
            files = main_window._blueprint_notification_files("LIVE", live)
        assert files == (live / "data" / "Localization" / "spanish_(spain)" / "global.ini",)
        warned = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert [(r.name, r.levelno) for r in warned] == [("src.gui.main_window", logging.WARNING)]
        assert "data folder could not be reached" in warned[0].getMessage()

    def test_one_failure_warns_once(self, tmp_profile, monkeypatch, caplog):
        # A run reads LIVE and HOTFIX, and the overlay starts too: the same
        # failure warns the first time and goes to DEBUG after that, until the
        # data folder answers again, after which a new failure warns again.
        monkeypatch.setattr(main_window, "_data_folder_warning", "")
        real = AppSettings.get_user_data_dir
        reachable = [False]

        def flaky():
            if reachable[0]:
                return real()
            raise PermissionError(13, "Access is denied", str(tmp_profile / "data"))

        monkeypatch.setattr(AppSettings, "get_user_data_dir", staticmethod(flaky))
        install = tmp_profile / "StarCitizen"

        def levels(*channels):
            caplog.clear()
            with caplog.at_level(logging.DEBUG, logger="src.gui.main_window"):
                for channel in channels:
                    main_window._blueprint_notification_files(channel, install / channel)
            return [r.levelno for r in caplog.records
                    if "data folder could not be reached" in r.getMessage()]

        assert levels("LIVE", "HOTFIX", "LIVE") == [logging.WARNING, logging.DEBUG, logging.DEBUG]
        reachable[0] = True
        assert levels("LIVE") == []
        reachable[0] = False
        assert levels("LIVE", "HOTFIX") == [logging.WARNING, logging.DEBUG]


class TestTheScanReadsTheLanguageTheGameShows:
    def test_a_spanish_players_blueprints_are_found(self, qapp, spanish_player, caplog):
        AppSettings.set_selected_language("spanish")
        _write_loc(AppSettings.get_base_ini_path("spanish"), SPANISH)
        with caplog.at_level(logging.INFO, logger="src.gui.workers"):
            result = _scan(spanish_player,
                           main_window._blueprint_notification_files("LIVE", spanish_player))
        assert result.names == {"Sens", "Pistola Coda", "Casco Antium"}
        assert result.latest_timestamp == datetime(
            2026, 11, 13, 0, 41, 23, 867000, tzinfo=timezone.utc)
        assert "BP Scan: looking for 'Received Blueprint: %s', 'Plano recibido: %s'" in caplog.text

    def test_english_selected_finds_the_english_ones_alone(self, qapp, spanish_player):
        # The control, and what every scan did before #564.
        _write_loc(AppSettings.get_base_ini_path("english"), "Received Blueprint: %s")
        result = _scan(spanish_player,
                       main_window._blueprint_notification_files("LIVE", spanish_player))
        assert result.names == {"Sens"}

    def test_the_text_of_the_file_applied_to_the_game_counts(self, qapp, spanish_player):
        # English selected, but the game shows Spanish from the file applied to
        # it (another tool's, or Smart Citizen's with an override): the game
        # logs what it shows.
        _write_loc(AppSettings.get_global_ini_path(), SPANISH)
        result = _scan(spanish_player,
                       main_window._blueprint_notification_files("LIVE", spanish_player))
        assert result.names == {"Sens", "Pistola Coda", "Casco Antium"}

    def test_lives_logs_are_read_with_lives_files_while_ptu_is_selected(
            self, qapp, spanish_player):
        # The tester's case: LIVE played in Spanish, PTU selected in Config
        # with no Spanish file of its own.
        AppSettings.set_selected_language("spanish")
        _write_loc(AppSettings.get_base_ini_path("spanish"), SPANISH)      # LIVE's cache
        AppSettings.set_active_channel("PTU")
        result = _scan(spanish_player,
                       main_window._blueprint_notification_files("LIVE", spanish_player))
        assert result.names == {"Sens", "Pistola Coda", "Casco Antium"}
        # The control: PTU's own files, which the first version of #564's fix
        # named, find the English blueprint alone.
        ptu_files = (AppSettings.get_global_source_base_ini(), AppSettings.get_global_ini_path())
        assert _scan(spanish_player, ptu_files).names == {"Sens"}

    def test_the_files_are_read_on_the_workers_thread(self, qapp, spanish_player, monkeypatch):
        # Each can be about 11 MB.
        threads = []
        real = blueprint_log_scanner.notification_templates

        def recording(loc_files):
            threads.append(threading.current_thread())
            return real(loc_files)

        monkeypatch.setattr(blueprint_log_scanner, "notification_templates", recording)
        _scan(spanish_player, main_window._blueprint_notification_files("LIVE", spanish_player))
        assert len(threads) == 1 and threads[0] is not threading.main_thread()
