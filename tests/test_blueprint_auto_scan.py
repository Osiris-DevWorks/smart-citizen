"""#386: automatic "Scan Logs for Owned Blueprints" on startup, opt-in.

Reuses the manual scan's own channel-queue/worker pipeline
(_start_next_blueprint_scan onward) -- the only new state is
self._bp_scan_silent, which _finish_blueprint_scan_queue reads to swap the
completion popups for a status bar message instead of interrupting every
launch with a modal dialog.

Driven on lightweight stub selfs (no QApplication, no real QThread), same
pattern as test_favorite_toggle_stranded.py / test_install_scan_finished_
stale_worker.py.
"""
from __future__ import annotations

import pytest

from src.gui.main_window import MainWindow
from src.utils.json_settings import JsonSettings
from src.utils.settings import AppSettings

pytestmark = pytest.mark.unit


@pytest.fixture
def json_backend(tmp_path):
    """Swap AppSettings._backend for a tmp JsonSettings so each test is hermetic."""
    saved = AppSettings._backend
    AppSettings._backend = JsonSettings(tmp_path / "config.json")
    yield AppSettings._backend
    AppSettings._backend = saved


class TestAutoScanSetting:
    def test_default_is_false(self, json_backend):
        assert AppSettings.get_auto_scan_blueprints_enabled() is False

    def test_round_trips(self, json_backend):
        AppSettings.set_auto_scan_blueprints_enabled(True)
        assert AppSettings.get_auto_scan_blueprints_enabled() is True
        AppSettings.set_auto_scan_blueprints_enabled(False)
        assert AppSettings.get_auto_scan_blueprints_enabled() is False


class TestAutoScanPopupSetting:
    def test_default_is_false(self, json_backend):
        assert AppSettings.get_auto_scan_show_popup_enabled() is False

    def test_round_trips(self, json_backend):
        AppSettings.set_auto_scan_show_popup_enabled(True)
        assert AppSettings.get_auto_scan_show_popup_enabled() is True
        AppSettings.set_auto_scan_show_popup_enabled(False)
        assert AppSettings.get_auto_scan_show_popup_enabled() is False


class _FakeTrackerTab:
    """Carries just what MainWindow's scan pipeline calls on the tab."""

    def __init__(self):
        self.force_rescan_reset = False
        self.marked_clean = False
        self.scan_logs_enabled_calls = []

    def reset_force_rescan_checkbox(self):
        self.force_rescan_reset = True

    def mark_owned_clean(self):
        self.marked_clean = True

    def set_scan_logs_enabled(self, enabled):
        self.scan_logs_enabled_calls.append(enabled)


class _ScanStub:
    """Carries just what _maybe_auto_scan_blueprints touches."""

    def __init__(self, worker=None):
        self._bp_log_scan_worker = worker
        self._bp_scan_queue = None
        self._bp_scan_new_names = None
        self._bp_scan_force_rescan = None
        self._bp_scan_silent = False
        self.blueprint_tracker_tab = _FakeTrackerTab()
        self.scan_started = False

    def _start_next_blueprint_scan(self):
        self.scan_started = True

    def maybe_auto_scan(self):
        MainWindow._maybe_auto_scan_blueprints(self)


class TestMaybeAutoScanGating:
    def test_does_nothing_when_setting_is_off(self, json_backend, monkeypatch, tmp_path):
        # A valid install path is deliberately supplied here -- if the
        # setting-off check were missing or broken, the scan would still
        # start on the strength of the path alone, so this isolates the
        # setting itself as what gates the call (not just "no path set").
        AppSettings.set_auto_scan_blueprints_enabled(False)
        monkeypatch.setattr(AppSettings, "get_channel_install_path", staticmethod(lambda: str(tmp_path)))
        stub = _ScanStub()
        stub.maybe_auto_scan()
        assert stub.scan_started is False

    def test_does_nothing_with_no_install_path(self, json_backend, monkeypatch):
        AppSettings.set_auto_scan_blueprints_enabled(True)
        monkeypatch.setattr(AppSettings, "get_channel_install_path", staticmethod(lambda: ""))
        stub = _ScanStub()
        stub.maybe_auto_scan()
        assert stub.scan_started is False
        assert stub._bp_scan_silent is False

    def test_does_nothing_with_a_nonexistent_install_path(self, json_backend, monkeypatch, tmp_path):
        AppSettings.set_auto_scan_blueprints_enabled(True)
        missing = str(tmp_path / "does-not-exist")
        monkeypatch.setattr(AppSettings, "get_channel_install_path", staticmethod(lambda: missing))
        stub = _ScanStub()
        stub.maybe_auto_scan()
        assert stub.scan_started is False

    def test_skips_when_a_scan_is_already_running(self, json_backend, monkeypatch, tmp_path):
        AppSettings.set_auto_scan_blueprints_enabled(True)
        monkeypatch.setattr(AppSettings, "get_channel_install_path", staticmethod(lambda: str(tmp_path)))
        stub = _ScanStub(worker=object())
        stub.maybe_auto_scan()
        assert stub.scan_started is False

    def test_starts_a_silent_scan_when_enabled_with_a_valid_path(self, json_backend, monkeypatch, tmp_path):
        AppSettings.set_auto_scan_blueprints_enabled(True)
        monkeypatch.setattr(AppSettings, "get_channel_install_path", staticmethod(lambda: str(tmp_path)))
        stub = _ScanStub()
        stub.maybe_auto_scan()
        assert stub.scan_started is True
        assert stub._bp_scan_silent is True
        # Never a forced full rescan -- that's a deliberate one-shot the
        # user ticks before a manual click, not something startup should do.
        assert stub._bp_scan_force_rescan is False
        # #386 review: the button is disabled before the run actually
        # starts, so a manual click mid-auto-scan is visibly blocked rather
        # than silently swallowed by the pre-existing reentrancy guard.
        assert stub.blueprint_tracker_tab.scan_logs_enabled_calls == [False]

    def test_gated_runs_never_touch_the_scan_logs_button(self, json_backend):
        """None of the early-return guards should disable the button --
        only a run that actually starts does."""
        stub = _ScanStub()  # setting off, the simplest gate
        stub.maybe_auto_scan()
        assert stub.blueprint_tracker_tab.scan_logs_enabled_calls == []


class _FakeStatusBar:
    def __init__(self):
        self.messages = []

    def showMessage(self, message):
        self.messages.append(message)


class _FinishStub:
    """Carries just what _finish_blueprint_scan_queue touches."""

    def __init__(self, silent, new_names):
        self._bp_scan_silent = silent
        self._bp_scan_new_names = set(new_names)
        self._status_bar = _FakeStatusBar()
        self.blueprint_tracker_tab = _FakeTrackerTab()
        self.recompute_called = False

    def statusBar(self):
        return self._status_bar

    def _recompute_owned(self):
        self.recompute_called = True

    def finish(self):
        MainWindow._finish_blueprint_scan_queue(self)


class TestFinishQueueSilentMode:
    def test_silent_with_nothing_new_shows_no_status_message(self, json_backend):
        stub = _FinishStub(silent=True, new_names=[])
        stub.finish()
        assert stub._status_bar.messages == []
        assert stub.recompute_called is False
        # One-shot regardless of outcome, same as the manual path.
        assert stub.blueprint_tracker_tab.force_rescan_reset is True
        # #386 review: re-enabled on every exit path, not just the ones that
        # found something new -- this is the single terminal point for every
        # run, so it's the one place that can reliably undo the disable.
        assert stub.blueprint_tracker_tab.scan_logs_enabled_calls == [True]

    def test_silent_with_new_names_updates_owned_set_and_status_bar(self, json_backend):
        AppSettings.set_owned_items(set())
        stub = _FinishStub(silent=True, new_names=["R97 Shotgun", "P4-AR"])
        stub.finish()

        assert AppSettings.get_owned_items() == {"R97 Shotgun", "P4-AR"}
        assert stub.recompute_called is True
        assert stub.blueprint_tracker_tab.marked_clean is True
        assert len(stub._status_bar.messages) == 1
        assert "2" in stub._status_bar.messages[0]

    def test_silent_flag_is_consumed_even_when_nothing_new(self, json_backend):
        """One-shot: a later manual scan's own reset (_run_blueprint_log_scan)
        isn't the only thing that must clear it -- this handler must not
        leave a stale True sitting around for whatever finishes next."""
        stub = _FinishStub(silent=True, new_names=[])
        stub.finish()
        assert stub._bp_scan_silent is False


class _FakeMessageBox:
    """Stands in for QMessageBox so the popup-opt-in path never needs a
    real QApplication -- same technique as test_install_scan_finished_
    stale_worker.py's fakes. Records enough to prove the popup path was
    actually reached, not just that the status-bar branch was skipped."""

    instances = []

    def __init__(self, parent=None):
        self.parent = parent
        self.icon = None
        self.title = None
        self.text = None
        self.detailed_text = None
        self.exec_called = False
        _FakeMessageBox.instances.append(self)

    def setIcon(self, icon):
        self.icon = icon

    def setWindowTitle(self, title):
        self.title = title

    def setText(self, text):
        self.text = text

    def setDetailedText(self, text):
        self.detailed_text = text

    def exec(self):
        self.exec_called = True

    class Icon:
        Information = "information"


class TestFinishQueuePopupOptIn:
    """#386 follow-up: the sibling checkbox brings the modal popup back for
    a silent run's "found something new" case specifically."""

    @pytest.fixture(autouse=True)
    def _fake_message_box(self, monkeypatch):
        _FakeMessageBox.instances = []
        monkeypatch.setattr("src.gui.main_window.QMessageBox", _FakeMessageBox)
        monkeypatch.setattr("src.gui.main_window._relabel_details_button", lambda *a, **k: None)
        yield

    def test_popup_disabled_stays_on_the_status_bar(self, json_backend):
        AppSettings.set_auto_scan_show_popup_enabled(False)
        stub = _FinishStub(silent=True, new_names=["R97 Shotgun"])
        stub.finish()
        assert len(stub._status_bar.messages) == 1
        assert _FakeMessageBox.instances == []

    def test_popup_enabled_shows_the_normal_summary_dialog_instead(self, json_backend):
        AppSettings.set_auto_scan_show_popup_enabled(True)
        stub = _FinishStub(silent=True, new_names=["R97 Shotgun", "P4-AR"])
        stub.finish()

        assert stub._status_bar.messages == []
        assert len(_FakeMessageBox.instances) == 1
        box = _FakeMessageBox.instances[0]
        assert box.exec_called is True
        assert "R97 Shotgun" in box.detailed_text
        assert "P4-AR" in box.detailed_text

    def test_popup_enabled_does_not_affect_a_quiet_run(self, json_backend):
        """Only the "found something new" branch reads this setting -- a
        run that finds nothing new stays silent regardless."""
        AppSettings.set_auto_scan_show_popup_enabled(True)
        stub = _FinishStub(silent=True, new_names=[])
        stub.finish()
        assert stub._status_bar.messages == []
        assert _FakeMessageBox.instances == []

    def test_manual_scans_are_unaffected_by_the_popup_setting(self, json_backend):
        """The setting only matters for a silent run -- a manual click
        already shows this same dialog regardless of either checkbox."""
        AppSettings.set_auto_scan_show_popup_enabled(False)
        stub = _FinishStub(silent=False, new_names=["R97 Shotgun"])
        stub.finish()
        assert stub._status_bar.messages == []
        assert len(_FakeMessageBox.instances) == 1
