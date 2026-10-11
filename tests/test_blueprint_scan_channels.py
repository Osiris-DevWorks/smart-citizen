"""Which channels "Scan Logs for Owned Blueprints" reads (#268, #446).

The scan always covers LIVE, plus HOTFIX when its folder is present. LIVE and
HOTFIX run on the same server and share one account progression, so a blueprint
earned on one shows up in the other's logs too. PTU, EPTU and TECH-PREVIEW are
separate test servers with their own progression that are wiped more often, so
they are NEVER scanned. There is no checkbox, and the channel selected in the
Config tab makes no difference.

Pure choice of channels: _channels_to_scan and _scan_queue_for_root. Both entry
points (the manual button and the startup auto-scan) are driven on stub selfs,
and so is the one place a scan worker is started, which refuses any channel
outside LIVE and HOTFIX as a second line of defence.
"""
from __future__ import annotations

import ast
import inspect
import itertools
import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.gui import main_window
from src.gui.main_window import (
    MainWindow, _SCANNED_CHANNELS, _channels_to_scan, _scan_queue_for_root,
)
from src.utils.blueprint_log_scanner import ScanResult
from src.utils.json_settings import JsonSettings
from src.utils.settings import AppSettings

pytestmark = pytest.mark.unit

TEST_CHANNELS = ("PTU", "EPTU", "TECH-PREVIEW")
ALL_CHANNELS = ("LIVE", "PTU", "EPTU", "HOTFIX", "TECH-PREVIEW")


@pytest.fixture
def json_backend(tmp_path_factory):
    """A tmp JsonSettings behind AppSettings, so nothing touches the registry."""
    saved = AppSettings._backend
    AppSettings._backend = JsonSettings(tmp_path_factory.mktemp("settings") / "config.json")
    yield AppSettings._backend
    AppSettings._backend = saved


def _root(tmp_path, *channels):
    """A fake Star Citizen install root with one folder per named channel."""
    for channel in channels:
        (tmp_path / channel).mkdir()
    return str(tmp_path)


class TestChannelsToScan:
    def test_the_allow_list_is_exactly_live_and_hotfix(self):
        assert _SCANNED_CHANNELS == ("LIVE", "HOTFIX")
        for channel in TEST_CHANNELS:
            assert channel not in _SCANNED_CHANNELS

    def test_live_alone(self):
        assert _channels_to_scan({"LIVE"}) == ["LIVE"]

    def test_live_then_hotfix_when_both_are_present(self):
        assert _channels_to_scan({"LIVE", "HOTFIX"}) == ["LIVE", "HOTFIX"]

    def test_the_order_does_not_depend_on_the_input_order(self):
        assert _channels_to_scan(["HOTFIX", "LIVE"]) == ["LIVE", "HOTFIX"]
        assert _channels_to_scan(("HOTFIX", "LIVE")) == ["LIVE", "HOTFIX"]

    def test_hotfix_alone_when_live_is_not_there(self):
        assert _channels_to_scan({"HOTFIX", "PTU"}) == ["HOTFIX"]

    def test_nothing_present_scans_nothing(self):
        assert _channels_to_scan(set()) == []

    @pytest.mark.parametrize("test_channel", TEST_CHANNELS)
    def test_a_test_channel_is_never_scanned(self, test_channel):
        assert test_channel not in _channels_to_scan(set(ALL_CHANNELS))
        assert _channels_to_scan({test_channel}) == []

    def test_only_test_channels_present_scans_nothing(self):
        assert _channels_to_scan(set(TEST_CHANNELS)) == []

    def test_every_combination_of_channels(self):
        """All 32 subsets of the five channels: the result is LIVE and/or
        HOTFIX as present, in that order, and never a test channel."""
        for size in range(len(ALL_CHANNELS) + 1):
            for present in itertools.combinations(ALL_CHANNELS, size):
                expected = [c for c in ("LIVE", "HOTFIX") if c in present]
                assert _channels_to_scan(present) == expected, present


class TestScanQueueForRoot:
    def test_no_root_scans_nothing(self):
        assert _scan_queue_for_root("") == []
        assert _scan_queue_for_root(None) == []

    def test_a_root_that_does_not_exist_scans_nothing(self, tmp_path):
        assert _scan_queue_for_root(str(tmp_path / "nope")) == []

    def test_live_only(self, tmp_path):
        assert _scan_queue_for_root(_root(tmp_path, "LIVE")) == ["LIVE"]

    def test_live_and_hotfix(self, tmp_path):
        assert _scan_queue_for_root(_root(tmp_path, "HOTFIX", "LIVE")) == ["LIVE", "HOTFIX"]

    def test_hotfix_only(self, tmp_path):
        assert _scan_queue_for_root(_root(tmp_path, "HOTFIX")) == ["HOTFIX"]

    def test_every_channel_folder_present_still_only_live_and_hotfix(self, tmp_path):
        assert _scan_queue_for_root(_root(tmp_path, *ALL_CHANNELS)) == ["LIVE", "HOTFIX"]

    def test_only_test_server_folders_scans_nothing(self, tmp_path):
        assert _scan_queue_for_root(_root(tmp_path, *TEST_CHANNELS)) == []

    def test_a_file_named_like_a_channel_does_not_count(self, tmp_path):
        (tmp_path / "LIVE").write_text("not a folder")
        assert _scan_queue_for_root(str(tmp_path)) == []

    def test_an_old_checkbox_value_changes_nothing(self, json_backend, tmp_path):
        """Older versions stored "blueprints/scan_other_channels". A user who
        had unticked it still gets LIVE and HOTFIX: nothing reads it any more."""
        json_backend.setValue("blueprints/scan_other_channels", False)
        assert _scan_queue_for_root(_root(tmp_path, "LIVE", "HOTFIX")) == ["LIVE", "HOTFIX"]


class _FakeBox:
    """Records the message boxes the manual scan shows."""

    shown: list = []

    @classmethod
    def reset(cls):
        cls.shown = []

    @staticmethod
    def warning(parent, title, text, *args, **kwargs):
        _FakeBox.shown.append(("warning", text))

    @staticmethod
    def information(parent, title, text, *args, **kwargs):
        _FakeBox.shown.append(("information", text))


class _FakeTab:
    def __init__(self):
        self.scan_logs_enabled_calls = []
        self.force_rescan = False

    def is_force_rescan_checked(self):
        return self.force_rescan

    def set_scan_logs_enabled(self, enabled):
        self.scan_logs_enabled_calls.append(enabled)


class _ManualScanStub:
    """Carries just what MainWindow._run_blueprint_log_scan touches."""

    def __init__(self, worker=None):
        self._bp_log_scan_worker = worker
        self._bp_scan_queue = None
        self._bp_scan_new_names = None
        self._bp_scan_force_rescan = None
        self._bp_scan_silent = True
        self.blueprint_tracker_tab = _FakeTab()
        self.queue_when_started = None

    def _start_next_blueprint_scan(self):
        self.queue_when_started = list(self._bp_scan_queue)

    def run(self):
        MainWindow._run_blueprint_log_scan(self)


def _config_says(monkeypatch, root, channel):
    """Config selects *channel* under *root*. The scan must not look at the
    Config channel, so anything that does fails the test."""
    def config_channel_must_not_matter(*args, **kwargs):
        raise AssertionError("the scan must not depend on the channel selected in Config")

    monkeypatch.setattr(AppSettings, "get_sc_install_root", staticmethod(lambda: root))
    monkeypatch.setattr(AppSettings, "get_active_channel", staticmethod(lambda: channel))
    monkeypatch.setattr(AppSettings, "get_channel_install_path", staticmethod(config_channel_must_not_matter))
    monkeypatch.setattr(AppSettings, "get_available_channels", staticmethod(config_channel_must_not_matter))
    monkeypatch.setattr(main_window, "QMessageBox", _FakeBox)
    _FakeBox.reset()


class TestManualScanIgnoresTheConfigChannel:
    @pytest.mark.parametrize("selected", ALL_CHANNELS)
    def test_live_and_hotfix_whichever_channel_is_selected(self, monkeypatch, tmp_path, selected):
        _config_says(monkeypatch, _root(tmp_path, *ALL_CHANNELS), selected)
        stub = _ManualScanStub()
        stub.run()
        assert stub.queue_when_started == ["LIVE", "HOTFIX"]
        assert _FakeBox.shown == []

    @pytest.mark.parametrize("selected", TEST_CHANNELS)
    def test_a_test_channel_selected_in_config_is_not_scanned(self, monkeypatch, tmp_path, selected):
        _config_says(monkeypatch, _root(tmp_path, "LIVE", selected), selected)
        stub = _ManualScanStub()
        stub.run()
        assert stub.queue_when_started == ["LIVE"]

    @pytest.mark.parametrize("selected", TEST_CHANNELS)
    def test_only_a_test_server_installed_says_there_is_nothing_to_scan(self, monkeypatch, tmp_path, selected):
        _config_says(monkeypatch, _root(tmp_path, selected), selected)
        stub = _ManualScanStub()
        stub.run()
        assert stub.queue_when_started is None
        assert _FakeBox.shown == [("information", main_window.tr("enhancements.bp_scan_no_live_hotfix"))]
        assert stub.blueprint_tracker_tab.scan_logs_enabled_calls == []

    def test_no_install_path_warns_as_before(self, monkeypatch):
        _config_says(monkeypatch, "", "LIVE")
        stub = _ManualScanStub()
        stub.run()
        assert stub.queue_when_started is None
        assert _FakeBox.shown == [("warning", main_window.tr("enhancements.bp_scan_no_path"))]

    def test_an_install_path_that_does_not_exist_warns_as_before(self, monkeypatch, tmp_path):
        _config_says(monkeypatch, str(tmp_path / "gone"), "LIVE")
        stub = _ManualScanStub()
        stub.run()
        assert _FakeBox.shown == [("warning", main_window.tr("enhancements.bp_scan_no_path"))]

    def test_a_scan_already_running_is_left_alone(self, monkeypatch, tmp_path):
        _config_says(monkeypatch, _root(tmp_path, "LIVE"), "LIVE")
        stub = _ManualScanStub(worker=object())
        stub.run()
        assert stub.queue_when_started is None

    def test_the_button_is_disabled_only_once_a_scan_really_starts(self, monkeypatch, tmp_path):
        _config_says(monkeypatch, _root(tmp_path, "LIVE"), "PTU")
        stub = _ManualScanStub()
        stub.run()
        assert stub.blueprint_tracker_tab.scan_logs_enabled_calls == [False]


class _FakeSignal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)


class _FakeWorker:
    created: list = []

    def __init__(self, channel_path, since):
        self.channel_path = channel_path
        self.since = since
        self.progress = _FakeSignal()
        self.progress_pct = _FakeSignal()
        self.error = _FakeSignal()
        self.finished = _FakeSignal()
        self.started = False
        _FakeWorker.created.append(self)

    def start(self):
        self.started = True


class _FakeStatusBar:
    def showMessage(self, message):
        pass


class _NextStub:
    """Carries just what MainWindow._start_next_blueprint_scan touches."""

    def __init__(self, queue):
        self._bp_scan_queue = list(queue)
        self._bp_scan_force_rescan = False
        self._bp_scan_silent = True
        self._bp_scan_channel = None
        self._bp_log_scan_worker = None
        self._bp_log_scan_progress = None
        self.finish_calls = 0

    def _start_next_blueprint_scan(self):
        MainWindow._start_next_blueprint_scan(self)

    def _finish_blueprint_scan_queue(self):
        self.finish_calls += 1

    def statusBar(self):
        return _FakeStatusBar()

    def _on_blueprint_log_scan_error(self, message):
        pass

    def _on_blueprint_log_scan_finished(self, result):
        pass


@pytest.fixture
def fake_worker(monkeypatch, tmp_path):
    """Folders for every channel under a fake root, and a worker that only records."""
    _FakeWorker.created = []
    root = _root(tmp_path, *ALL_CHANNELS)
    monkeypatch.setattr(AppSettings, "get_sc_install_root", staticmethod(lambda: root))
    monkeypatch.setattr(AppSettings, "get_blueprint_log_watermark", staticmethod(lambda channel=None: None))
    monkeypatch.setattr(main_window, "BlueprintLogScanWorker", _FakeWorker)
    return tmp_path


SRC = Path(main_window.__file__).resolve().parents[1]


def _call_sites(name):
    """Every file under src/ (relative, posix) that calls *name*. Parsed, so a
    mention in a comment, a docstring or a class definition does not count."""
    sites = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
                if called == name:
                    sites.append(path.relative_to(SRC).as_posix())
                    break
    return sites


class TestTheWorkerStartRefusesTestChannels:
    """The second line of defence: whatever ends up in the queue, a test
    channel never reaches a scan worker."""

    @pytest.mark.parametrize("channel", TEST_CHANNELS)
    def test_a_queued_test_channel_is_refused(self, fake_worker, caplog, channel):
        stub = _NextStub([channel])
        with caplog.at_level(logging.ERROR, logger="src.gui.main_window"):
            stub._start_next_blueprint_scan()
        assert _FakeWorker.created == []
        assert stub.finish_calls == 1
        assert stub._bp_log_scan_worker is None
        assert "refusing to scan" in caplog.text

    def test_every_test_channel_in_one_queue_starts_nothing(self, fake_worker):
        stub = _NextStub(["PTU", "EPTU", "TECH-PREVIEW"])
        stub._start_next_blueprint_scan()
        assert _FakeWorker.created == []
        assert stub.finish_calls == 1

    def test_a_test_channel_is_skipped_and_the_next_channel_still_runs(self, fake_worker):
        stub = _NextStub(["PTU", "LIVE"])
        stub._start_next_blueprint_scan()
        assert [w.channel_path for w in _FakeWorker.created] == [str(fake_worker / "LIVE")]
        assert stub._bp_scan_channel == "LIVE"
        assert _FakeWorker.created[0].started is True
        assert stub.finish_calls == 0

    @pytest.mark.parametrize("channel", _SCANNED_CHANNELS)
    def test_live_and_hotfix_each_start_a_worker(self, fake_worker, channel):
        stub = _NextStub([channel])
        stub._start_next_blueprint_scan()
        assert [w.channel_path for w in _FakeWorker.created] == [str(fake_worker / channel)]

    def test_an_unknown_channel_name_is_refused_too(self, fake_worker):
        stub = _NextStub(["SOMETHING-ELSE"])
        stub._start_next_blueprint_scan()
        assert _FakeWorker.created == []

    def test_a_scan_worker_is_created_in_exactly_one_place(self):
        """The guard above only protects if it is the only way to start a
        worker. Fails if a second construction site is added anywhere in src/,
        or if a log is read some other way (scan_channel, find_log_files and
        scan_files each have a single home)."""
        assert _call_sites("BlueprintLogScanWorker") == ["gui/main_window.py"]
        assert "BlueprintLogScanWorker(" in inspect.getsource(MainWindow._start_next_blueprint_scan)
        assert _call_sites("scan_channel") == ["gui/workers.py"]
        assert _call_sites("find_log_files") == ["utils/blueprint_log_scanner.py"]
        assert _call_sites("scan_files") == ["utils/blueprint_log_scanner.py"]


class _RunStub(_NextStub):
    """_NextStub plus what MainWindow._on_blueprint_log_scan_finished touches,
    so a whole queued run can be walked through with the real start and finish
    methods."""

    def __init__(self, queue):
        super().__init__(queue)
        self._known_item_names = set()
        self._bp_scan_new_names = set()

    def _reap_worker(self, worker):
        pass

    def _on_blueprint_log_scan_finished(self, result):
        MainWindow._on_blueprint_log_scan_finished(self, result)


def _result(when, *names):
    return ScanResult(names=set(names), latest_timestamp=when, events_matched=len(names), files_scanned=1)


T1 = datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 5, 2, 10, 0, tzinfo=timezone.utc)
T3 = datetime(2026, 5, 3, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def run_env(json_backend, monkeypatch, tmp_path):
    """A real settings backend (so watermarks really persist), folders for every
    channel, PTU selected in Config, and a worker that only records."""
    _FakeWorker.created = []
    root = _root(tmp_path, *ALL_CHANNELS)
    monkeypatch.setattr(AppSettings, "get_sc_install_root", staticmethod(lambda: root))
    monkeypatch.setattr(AppSettings, "get_active_channel", staticmethod(lambda: "PTU"))
    monkeypatch.setattr(main_window, "BlueprintLogScanWorker", _FakeWorker)
    return tmp_path


def _walk_run(root, live_result, hotfix_result):
    """Drive one whole run the way the button does: build the queue from the
    install root, start the first worker, feed back each channel's result."""
    stub = _RunStub(_scan_queue_for_root(root))
    stub._start_next_blueprint_scan()
    stub._on_blueprint_log_scan_finished(live_result)
    stub._on_blueprint_log_scan_finished(hotfix_result)
    return stub


class TestTheScanKeepsItsWatermarks:
    """The scan remembers how far it has read, per channel, so a re-run only
    reads log growth since the last run. That has to keep working with the
    channel now chosen from the install root instead of from Config."""

    def test_each_scanned_channel_stores_its_own_watermark_not_the_config_channels(self, run_env):
        stub = _walk_run(str(run_env), _result(T1, "A"), _result(T2, "B"))
        assert stub.finish_calls == 1
        assert [Path(w.channel_path).name for w in _FakeWorker.created] == ["LIVE", "HOTFIX"]
        assert AppSettings.get_blueprint_log_watermark(channel="LIVE") == T1
        assert AppSettings.get_blueprint_log_watermark(channel="HOTFIX") == T2
        for channel in TEST_CHANNELS:
            assert AppSettings.get_blueprint_log_watermark(channel=channel) is None

    def test_the_next_run_hands_each_worker_its_saved_watermark(self, run_env):
        _walk_run(str(run_env), _result(T1, "A"), _result(T2, "B"))
        _FakeWorker.created = []
        _walk_run(str(run_env), _result(T3), _result(T3))
        assert [w.since for w in _FakeWorker.created] == [T1, T2]

    def test_the_first_ever_run_starts_from_the_scanners_own_floor(self, run_env):
        _walk_run(str(run_env), _result(None), _result(None))
        assert [w.since for w in _FakeWorker.created] == [None, None]

    def test_a_forced_rescan_ignores_the_saved_watermarks(self, run_env):
        _walk_run(str(run_env), _result(T1, "A"), _result(T2, "B"))
        _FakeWorker.created = []
        stub = _RunStub(_scan_queue_for_root(str(run_env)))
        stub._bp_scan_force_rescan = True
        stub._start_next_blueprint_scan()
        stub._on_blueprint_log_scan_finished(_result(T3))
        assert [w.since for w in _FakeWorker.created] == [None, None]

    def test_a_run_that_finds_nothing_new_still_advances_the_watermark(self, run_env):
        AppSettings.set_owned_items({"A"})
        _walk_run(str(run_env), _result(T1, "A"), _result(T1, "A"))
        _walk_run(str(run_env), _result(T2, "A"), _result(T2, "A"))
        assert AppSettings.get_blueprint_log_watermark(channel="LIVE") == T2
        assert AppSettings.get_blueprint_log_watermark(channel="HOTFIX") == T2

    def test_the_watermark_never_moves_backwards(self, run_env):
        AppSettings.set_blueprint_log_watermark(T3, channel="LIVE")
        _walk_run(str(run_env), _result(T1, "A"), _result(T1, "B"))
        assert AppSettings.get_blueprint_log_watermark(channel="LIVE") == T3
        assert AppSettings.get_blueprint_log_watermark(channel="HOTFIX") == T1

    def test_a_run_with_no_events_leaves_the_watermark_alone(self, run_env):
        AppSettings.set_blueprint_log_watermark(T2, channel="LIVE")
        _walk_run(str(run_env), _result(None), _result(None))
        assert AppSettings.get_blueprint_log_watermark(channel="LIVE") == T2
        assert AppSettings.get_blueprint_log_watermark(channel="HOTFIX") is None

    def test_a_failed_channel_does_not_lose_or_move_the_other_ones_watermark(self, run_env):
        AppSettings.set_blueprint_log_watermark(T1, channel="HOTFIX")
        _walk_run(str(run_env), _result(T2, "A"), None)
        assert AppSettings.get_blueprint_log_watermark(channel="LIVE") == T2
        assert AppSettings.get_blueprint_log_watermark(channel="HOTFIX") == T1

    def test_a_watermark_saved_by_an_older_version_is_still_used(self, run_env, json_backend):
        """The on-disk key did not change in #446: a profile that already scanned
        LIVE and HOTFIX carries on from there instead of re-reading every log."""
        assert AppSettings.BLUEPRINT_LOG_WATERMARK == "blueprint_log_watermark"
        json_backend.setValue("blueprint_log_watermark/LIVE", T1.isoformat())
        json_backend.setValue("blueprint_log_watermark/HOTFIX", T2.isoformat())
        _walk_run(str(run_env), _result(None), _result(None))
        assert [w.since for w in _FakeWorker.created] == [T1, T2]

    def test_an_old_test_channel_watermark_is_left_untouched_and_unused(self, run_env):
        """A PTU watermark an older version stored while PTU was the Config
        channel stays where it is. It is never read, never advanced."""
        AppSettings.set_blueprint_log_watermark(T1, channel="PTU")
        _walk_run(str(run_env), _result(T3, "A"), _result(T3, "B"))
        assert AppSettings.get_blueprint_log_watermark(channel="PTU") == T1
        assert all(Path(w.channel_path).name in ("LIVE", "HOTFIX") for w in _FakeWorker.created)


class TestManualScanReadsTheTickboxAndResetsItsState:
    def test_a_manual_click_resets_the_run_flags_and_reads_the_rescan_tickbox(self, monkeypatch, tmp_path):
        _config_says(monkeypatch, _root(tmp_path, "LIVE"), "LIVE")
        stub = _ManualScanStub()
        stub.blueprint_tracker_tab.force_rescan = True
        stub.run()
        assert stub._bp_scan_silent is False
        assert stub._bp_scan_new_names == set()
        assert stub._bp_scan_force_rescan is True

    def test_an_unticked_tickbox_means_a_normal_incremental_scan(self, monkeypatch, tmp_path):
        _config_says(monkeypatch, _root(tmp_path, "LIVE"), "LIVE")
        stub = _ManualScanStub()
        stub.run()
        assert stub._bp_scan_force_rescan is False


def _deny_is_dir(monkeypatch, *names):
    """Make Path.is_dir() raise PermissionError for folders with these names,
    the way Python 3.11 does for access denied or an offline network drive."""
    real_is_dir = Path.is_dir

    def is_dir(self, *args, **kwargs):
        if self.name in names:
            raise PermissionError(13, "access denied")
        return real_is_dir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "is_dir", is_dir)


class TestAnUnreadableLocationIsNotACrash:
    def test_an_unreadable_channel_folder_counts_as_missing(self, monkeypatch, tmp_path):
        root = _root(tmp_path, "LIVE", "HOTFIX")
        _deny_is_dir(monkeypatch, "HOTFIX")
        assert _scan_queue_for_root(root) == ["LIVE"]

    def test_an_unreadable_root_counts_as_no_folders(self, monkeypatch, tmp_path):
        root = _root(tmp_path, "LIVE", "HOTFIX")
        _deny_is_dir(monkeypatch, tmp_path.name)
        assert _scan_queue_for_root(root) == []

    def test_an_unreadable_root_is_reported_like_a_missing_one(self, monkeypatch, tmp_path):
        root = _root(tmp_path, "LIVE", "HOTFIX")
        _config_says(monkeypatch, root, "LIVE")
        _deny_is_dir(monkeypatch, tmp_path.name)
        stub = _ManualScanStub()
        stub.run()
        assert _FakeBox.shown == [("warning", main_window.tr("enhancements.bp_scan_no_path"))]
        assert stub.queue_when_started is None
        assert stub.blueprint_tracker_tab.scan_logs_enabled_calls == []

    def test_a_channel_folder_that_turns_unreadable_is_skipped(self, fake_worker, monkeypatch):
        _deny_is_dir(monkeypatch, "HOTFIX")
        stub = _NextStub(["HOTFIX"])
        stub._start_next_blueprint_scan()
        assert _FakeWorker.created == []
        assert stub.finish_calls == 1


class TestNameRecoveryOnlyAgainstALiveFamilyList:
    """The #372 recovery matches log names against the item list of the
    channel selected in Config. That is only trustworthy for LIVE and HOTFIX,
    whose builds match the logs being read. A test channel's list can lack a
    LIVE item but hold a shorter real one, and recovery would mark that one
    owned instead."""

    @pytest.mark.parametrize(
        "config_channel, expected",
        [
            ("LIVE", {"Bar"}),
            ("HOTFIX", {"Bar"}),
            ("PTU", {"Foo Bar"}),
            ("EPTU", {"Foo Bar"}),
            ("TECH-PREVIEW", {"Foo Bar"}),
        ],
    )
    def test_recovery_runs_only_when_the_loaded_item_list_is_live_or_hotfix(
        self, run_env, monkeypatch, config_channel, expected
    ):
        monkeypatch.setattr(AppSettings, "get_active_channel", staticmethod(lambda: config_channel))
        stub = _RunStub([])
        stub._known_item_names = {"Bar"}
        stub._bp_scan_channel = "LIVE"
        stub._on_blueprint_log_scan_finished(_result(T1, "Foo Bar"))
        assert stub._bp_scan_new_names == expected

    @pytest.mark.parametrize("config_channel", ALL_CHANNELS)
    def test_a_name_is_kept_as_logged_when_there_is_no_item_list(self, run_env, monkeypatch, config_channel):
        monkeypatch.setattr(AppSettings, "get_active_channel", staticmethod(lambda: config_channel))
        stub = _RunStub([])
        stub._known_item_names = set()
        stub._bp_scan_channel = "LIVE"
        stub._on_blueprint_log_scan_finished(_result(T1, "Foo Bar"))
        assert stub._bp_scan_new_names == {"Foo Bar"}

    def test_a_test_channel_selection_does_not_stop_the_watermark_advancing(self, run_env, monkeypatch):
        monkeypatch.setattr(AppSettings, "get_active_channel", staticmethod(lambda: "PTU"))
        stub = _RunStub([])
        stub._known_item_names = {"Bar"}
        stub._bp_scan_channel = "LIVE"
        stub._on_blueprint_log_scan_finished(_result(T2, "Foo Bar"))
        assert AppSettings.get_blueprint_log_watermark(channel="LIVE") == T2
