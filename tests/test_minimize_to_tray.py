"""Minimize to tray (src/gui/tray.py), and the second start that brings a
copy in the tray back instead of opening another. Only a copy in the tray
does that: a copy on screen does not stop a second one opening.

A plain QMainWindow stands in for MainWindow in most tests, because the
controller only watches the window's state changes. MainWindow's own part
(building the controller, the Config tab's tick box, ``retranslate_ui`` and
``closeEvent``) is checked on a real window, and ``src/main.py``'s by
running the real ``main()`` in a child process. The offscreen platform has
no system tray, so ``tray_available`` is patched where a test needs one.
Every socket name is made up per test, never ``instance_name()``'s, so a
real Smart Citizen in this PC's tray is never woken by the run.
"""
from __future__ import annotations

import getpass
import json
import logging
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import Qt, QThread
from PyQt6.QtNetwork import QLocalSocket
from PyQt6.QtWidgets import QApplication, QDialog, QMainWindow, QSystemTrayIcon

from src.gui import config_tab as config_tab_module
from src.gui import main_window as main_window_module
from src.gui import tray
from src.gui.config_tab import ConfigTab
from src.gui.main_window import MainWindow
from src.gui.tray import WAKE_MESSAGE, TrayController
from src.utils import i18n
from src.utils.i18n import tr
from src.utils.settings import AppSettings
from tests.event_loop import pump_until
from tests.gui_window import build_main_window, retire_main_window

REPO = Path(__file__).resolve().parent.parent
# Kept alive for the session, as tests/gui_window.py keeps its windows.
_LIVE: list = []
# What the child prints (see _second_start).
_OPENED = "SMART CITIZEN WOULD OPEN A WINDOW"
_ENDED = "SMART CITIZEN OPENED NO WINDOW"
# Patched by name: test_build_info_fallback.py reloads build_mode, so a module
# object imported here at collection can be stale by the time a test runs.
_PORTABLE_FLAG = "src.utils.build_mode.IS_PORTABLE"
_NEW_KEYS = [
    ("config", "minimize_to_tray_cb"),
    ("config", "minimize_to_tray_tooltip"),
    ("config", "minimize_to_tray_unavailable_tooltip"),
    ("tray", "show"),
    ("tray", "quit"),
    ("tray", "notice_title"),
    ("tray", "notice_body"),
]


def _new_name() -> str:
    return f"SmartCitizen-test-{uuid.uuid4().hex}"


def _listening(name: str) -> bool:
    """Whether something listens on *name*. A local connect needs no answer
    from the server, so this works while the server's thread is this one."""
    socket = QLocalSocket()
    socket.connectToServer(name)
    connected = socket.waitForConnected(500)
    socket.abort()
    return connected


def _ui_text(language: str, *path: str) -> str:
    """What ``tr()`` shows for a key in *language*, given by its parts: its
    ht, or its at."""
    leaf = json.loads((REPO / "languages" / language / "ui.json").read_text(encoding="utf-8"))
    for part in path:
        leaf = leaf[part]
    return leaf["ht"] or leaf["at"]


class _Window(QMainWindow):
    """A window that records its close events, as MainWindow's closeEvent
    would see them. It never quits the run's app when it closes."""

    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setWindowTitle("Smart Citizen test window")
        self.resize(400, 300)
        self.closes = 0

    def closeEvent(self, event):
        self.closes += 1
        event.accept()


@pytest.fixture
def wake_name(monkeypatch):
    name = _new_name()
    monkeypatch.setattr(tray, "instance_name", lambda: name)
    return name


@pytest.fixture
def quits(monkeypatch):
    """The app quits the controller asks for, recorded instead: the run's one
    app must live on."""
    calls = []
    monkeypatch.setattr(tray, "_quit_app", lambda: calls.append("quit"))
    return calls


@pytest.fixture
def with_tray(monkeypatch):
    monkeypatch.setattr(tray, "tray_available", lambda: True)


@pytest.fixture
def on_screen(qapp, tmp_profile, wake_name, with_tray, quits):
    """A window on screen with minimize to tray turned on. Its settings live
    in tmp_profile: a trip to the tray reads and writes the notice's record,
    which must never reach this PC's registry."""
    window = _Window()
    _LIVE.append(window)
    window.show()
    controller = TrayController(window)
    controller.set_enabled(True)
    yield window, controller
    controller.shut_down()
    window.hide()
    qapp.setQuitOnLastWindowClosed(True)
    QApplication.processEvents()


def _to_tray(window, controller) -> None:
    window.showMinimized()
    assert pump_until(lambda: controller.hidden_in_tray), "the window did not go to the tray"


def _settle(seconds: float = 0.1) -> None:
    """Run the event loop for *seconds*: a hide that was queued runs, and
    the copy gets to a connection that is waiting."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)


class TestTheSetting:
    def test_it_is_off_until_ticked(self, tmp_profile):
        assert AppSettings.get_minimize_to_tray() is False
        AppSettings.set_minimize_to_tray(True)
        assert AppSettings.get_minimize_to_tray() is True
        AppSettings.set_minimize_to_tray(False)
        assert AppSettings.get_minimize_to_tray() is False

    def test_a_settings_backup_carries_it(self, tmp_profile):
        assert AppSettings.profile_default_values()[AppSettings.MINIMIZE_TO_TRAY] is False


class TestTheConfigTab:
    @staticmethod
    def _tab(monkeypatch, available: bool) -> ConfigTab:
        monkeypatch.setattr(config_tab_module, "tray_available", lambda: available)
        tab = ConfigTab()
        _LIVE.append(tab)
        return tab

    def test_the_box_shows_the_setting_and_saves_it(self, qapp, tmp_profile, monkeypatch,
                                                    english_ui, slot_errors):
        AppSettings.set_minimize_to_tray(True)
        tab = self._tab(monkeypatch, True)
        box = tab.minimize_to_tray_cb
        changes = []
        tab.minimize_to_tray_changed.connect(changes.append)
        assert box.isChecked() and box.isEnabled()
        assert box.text() == "Minimize to Tray"
        assert box.toolTip() == tr("config.minimize_to_tray_tooltip")

        box.setChecked(False)
        assert changes == [False]
        assert AppSettings.get_minimize_to_tray() is False
        box.setChecked(True)
        assert changes == [False, True]
        assert AppSettings.get_minimize_to_tray() is True
        assert slot_errors == []

    def test_with_no_tray_the_box_is_greyed_out_and_says_why(
            self, qapp, tmp_profile, monkeypatch, english_ui):
        box = self._tab(monkeypatch, False).minimize_to_tray_cb
        assert not box.isEnabled()
        assert box.toolTip() == (
            "No system tray was found, so Smart Citizen minimizes to the taskbar.")

    def test_a_tray_that_appears_later_makes_the_box_usable(
            self, qapp, tmp_profile, monkeypatch, english_ui):
        """The tab looks again each time it shows, so a start before the
        taskbar was up needs no restart."""
        tab = self._tab(monkeypatch, False)
        box = tab.minimize_to_tray_cb
        assert not box.isEnabled()

        monkeypatch.setattr(config_tab_module, "tray_available", lambda: True)
        tab.show()
        try:
            assert box.isEnabled()
            assert box.toolTip() == tr("config.minimize_to_tray_tooltip")
        finally:
            tab.hide()

    @pytest.mark.parametrize("available", [True, False])
    def test_a_language_switch_shows_what_a_restart_shows(
            self, qapp, tmp_profile, monkeypatch, english_ui, available):
        switched = self._tab(monkeypatch, available)
        i18n.set_language("german")
        switched.retranslate_ui()
        restarted = self._tab(monkeypatch, available)

        shown = (switched.minimize_to_tray_cb.text(), switched.minimize_to_tray_cb.toolTip())
        assert shown == (restarted.minimize_to_tray_cb.text(),
                         restarted.minimize_to_tray_cb.toolTip())
        tooltip = ("minimize_to_tray_tooltip" if available
                   else "minimize_to_tray_unavailable_tooltip")
        assert shown == (_ui_text("german", "config", "minimize_to_tray_cb"),
                         _ui_text("german", "config", tooltip))


class TestMinimizing:
    def test_minimizing_hides_it_in_the_tray(self, qapp, on_screen, wake_name):
        window, controller = on_screen
        assert controller.enabled
        assert not _listening(wake_name)  # on screen, nothing is asked of a second start

        _to_tray(window, controller)

        assert not window.isVisible()
        assert _listening(wake_name)
        # A box or other window closing meanwhile must not quit the app behind
        # the user's back, with no closeEvent to stop the running jobs.
        assert qapp.quitOnLastWindowClosed() is False

    def test_its_icon_brings_it_back_as_it_was(self, qapp, on_screen, wake_name):
        window, controller = on_screen
        window.showMaximized()
        _to_tray(window, controller)

        controller._on_activated(QSystemTrayIcon.ActivationReason.Trigger)

        assert window.isVisible() and window.isMaximized() and not window.isMinimized()
        assert not controller.hidden_in_tray
        assert qapp.quitOnLastWindowClosed() is True
        assert not _listening(wake_name)

    def test_a_double_click_brings_it_back_too(self, on_screen):
        window, controller = on_screen
        _to_tray(window, controller)
        controller._on_activated(QSystemTrayIcon.ActivationReason.DoubleClick)
        assert window.isVisible() and not controller.hidden_in_tray

    def test_a_right_click_only_opens_the_menu(self, on_screen):
        window, controller = on_screen
        _to_tray(window, controller)
        controller._on_activated(QSystemTrayIcon.ActivationReason.Context)
        assert not window.isVisible() and controller.hidden_in_tray

    def test_show_in_its_menu_brings_back_a_window_that_was_not_maximized(self, on_screen):
        window, controller = on_screen
        window.showNormal()
        _to_tray(window, controller)

        controller._show_action.trigger()

        assert window.isVisible()
        assert not window.isMaximized() and not window.isMinimized()

    def test_a_window_on_screen_only_comes_to_the_front(self, on_screen):
        window, controller = on_screen
        window.showMaximized()
        controller.restore()
        assert window.isVisible() and window.isMaximized()

    def test_turned_off_it_minimizes_to_the_taskbar(self, on_screen, wake_name):
        window, controller = on_screen
        controller.set_enabled(False)
        assert not controller.enabled

        window.showMinimized()
        _settle()

        assert window.isVisible() and window.isMinimized()
        assert not controller.hidden_in_tray
        assert not _listening(wake_name)

    def test_with_no_tray_yet_it_minimizes_to_the_taskbar_until_one_appears(
            self, qapp, tmp_profile, monkeypatch, wake_name, quits):
        """A start before the taskbar is up: the icon is made anyway (Qt puts
        it in the tray once there is one), the window is never hidden with no
        tray, and a tray that appears later is used without a restart."""
        tray_up = [False]
        monkeypatch.setattr(tray, "tray_available", lambda: tray_up[0])
        window = _Window()
        _LIVE.append(window)
        window.show()
        controller = TrayController(window)
        try:
            controller.set_enabled(True)
            assert controller.enabled

            window.showMinimized()
            _settle()
            assert window.isVisible() and not controller.hidden_in_tray
            assert not _listening(wake_name)

            window.showNormal()
            tray_up[0] = True
            _to_tray(window, controller)
            assert not window.isVisible()
        finally:
            controller.shut_down()
            window.hide()
            qapp.setQuitOnLastWindowClosed(True)

    def test_a_modal_box_keeps_it_on_the_taskbar(self, on_screen):
        """The box minimizes with its window, and must be found again."""
        window, controller = on_screen
        box = QDialog(window)
        box.setModal(True)
        box.show()
        try:
            assert QApplication.activeModalWidget() is box
            window.showMinimized()
            _settle()
            assert window.isVisible() and not controller.hidden_in_tray
        finally:
            box.close()

    def test_coming_back_before_the_hide_runs_keeps_it_on_screen(self, on_screen):
        window, controller = on_screen
        window.showMinimized()
        window.showNormal()  # before the queued hide runs
        _settle()
        assert window.isVisible() and not controller.hidden_in_tray

    def test_turning_it_off_in_the_tray_brings_it_back(self, qapp, on_screen, wake_name):
        window, controller = on_screen
        _to_tray(window, controller)

        controller.set_enabled(False)

        assert window.isVisible() and not window.isMinimized()
        assert not controller.enabled and not controller.hidden_in_tray
        assert qapp.quitOnLastWindowClosed() is True
        assert not _listening(wake_name)

    def test_quit_brings_it_back_then_closes_it(self, qapp, on_screen, quits):
        window, controller = on_screen
        _to_tray(window, controller)

        controller._quit_action.trigger()

        assert window.closes == 1
        assert qapp.quitOnLastWindowClosed() is True
        assert quits == []  # the close of a window on screen quits as Qt always has

    def test_a_close_while_in_the_tray_quits_the_app(self, qapp, on_screen, quits, wake_name):
        """Windows signing out closes the hidden window. It never counted as
        shown, so Qt would not quit when it closes: the controller does."""
        window, controller = on_screen
        _to_tray(window, controller)

        controller.shut_down()

        assert pump_until(lambda: quits == ["quit"])
        assert not controller.enabled
        assert qapp.quitOnLastWindowClosed() is True
        assert not _listening(wake_name)

    def test_a_close_on_screen_leaves_quitting_to_qt(self, on_screen, quits):
        window, controller = on_screen
        controller.shut_down()
        _settle()
        assert quits == [] and not controller.enabled

    def test_its_texts_follow_the_language(self, on_screen, english_ui):
        window, controller = on_screen
        controller.retranslate_ui()
        assert controller._show_action.text() == "Show Smart Citizen"
        assert controller._quit_action.text() == "Quit"
        assert controller._icon.toolTip() == window.windowTitle()

        i18n.set_language("german")
        controller.retranslate_ui()

        assert controller._show_action.text() == _ui_text("german", "tray", "show")
        assert controller._quit_action.text() == _ui_text("german", "tray", "quit")


class _Ask(QThread):
    """``bring_back_hidden_copy`` on a thread of its own, as a second start
    runs it in a process of its own: the copy in the tray lives on the GUI
    thread here, and reads the request only while the test runs the event
    loop, so a test that blocks instead plays a busy copy. An exception the
    ask raises is kept for the test, since one that left ``run()`` would end
    the whole run."""

    def __init__(self, name: str, timeout_ms: int):
        super().__init__()
        self._name = name
        self._timeout_ms = timeout_ms
        self.result = None
        self.error = None

    def run(self):
        try:
            self.result = tray.bring_back_hidden_copy(self._name, self._timeout_ms)
        except Exception as exc:
            self.error = exc


def _ask(name: str, timeout_ms: int = 5000):
    thread = _Ask(name, timeout_ms)
    _LIVE.append(thread)
    thread.start()
    assert pump_until(thread.isFinished, seconds=timeout_ms / 1000 + 10)
    thread.wait()
    if thread.error is not None:
        raise thread.error
    return thread.result


class TestASecondStart:
    def test_with_nothing_in_the_tray_it_opens_at_once(self, qapp):
        started = time.monotonic()
        assert tray.bring_back_hidden_copy(_new_name(), 5000) is False
        assert time.monotonic() - started < 1.0  # nothing to wait for

    def test_a_copy_on_screen_does_not_stop_it(self, on_screen, wake_name):
        window, controller = on_screen
        assert _ask(wake_name) is False
        assert window.isVisible() and not window.isMinimized()

    def test_a_copy_in_the_tray_comes_back_and_this_start_ends(self, on_screen, wake_name):
        window, controller = on_screen
        window.showMaximized()
        _to_tray(window, controller)

        assert _ask(wake_name) is True

        # The write finishes once the copy has read the line, and the copy
        # comes back as it handles it.
        assert pump_until(window.isVisible)
        assert window.isMaximized()
        assert not controller.hidden_in_tray
        assert not _listening(wake_name)

    def test_a_copy_busy_for_a_moment_still_comes_back(self, on_screen, wake_name):
        window, controller = on_screen
        _to_tray(window, controller)
        thread = _Ask(wake_name, 5000)
        _LIVE.append(thread)
        thread.start()
        time.sleep(0.5)  # the copy's thread is busy meanwhile

        assert pump_until(thread.isFinished)
        thread.wait()

        assert thread.result is True
        assert pump_until(window.isVisible)

    def test_a_copy_busy_past_the_wait_stays_in_the_tray_and_this_start_opens(
            self, on_screen, wake_name, caplog):
        """One window, never two: the request the copy never read is taken
        back, so the copy has nothing to come back for once it is free."""
        window, controller = on_screen
        _to_tray(window, controller)
        thread = _Ask(wake_name, 300)
        _LIVE.append(thread)

        with caplog.at_level(logging.WARNING, logger=tray.__name__):
            thread.start()
            thread.wait()  # the copy's thread is busy all the while
        assert thread.result is False
        assert "did not answer within 0.3 s" in caplog.text

        _settle(0.5)  # the copy gets to the connection now
        assert controller.hidden_in_tray and not window.isVisible()

    def test_a_request_read_once_the_close_began_changes_nothing(self, on_screen, wake_name,
                                                                 quits):
        window, controller = on_screen
        _to_tray(window, controller)
        socket = QLocalSocket()
        socket.connectToServer(wake_name)
        assert socket.waitForConnected(1000)
        _settle()  # the copy has the connection

        controller.shut_down()
        socket.write(WAKE_MESSAGE)
        socket.flush()

        assert pump_until(
            lambda: socket.state() == QLocalSocket.LocalSocketState.UnconnectedState)
        assert not window.isVisible()

    def test_a_line_that_is_not_the_wake_leaves_it_in_the_tray(self, on_screen, wake_name):
        window, controller = on_screen
        _to_tray(window, controller)
        socket = QLocalSocket()
        socket.connectToServer(wake_name)
        assert socket.waitForConnected(1000)

        socket.write(b"hello\n")
        socket.flush()

        assert pump_until(
            lambda: socket.state() == QLocalSocket.LocalSocketState.UnconnectedState)
        assert controller.hidden_in_tray and not window.isVisible()


class TestHandingOnTheForeground:
    """Windows lets only the program the user just started bring a window to
    the front, so a second start hands that right on to the copy in the tray
    (``global_hotkey.allow_any_foreground``) before it asks the copy back."""

    @staticmethod
    def _record(monkeypatch, granted: bool = True) -> list:
        handed = []

        def hand_on():
            handed.append("hand on")
            return granted

        monkeypatch.setattr(tray, "allow_any_foreground", hand_on)
        return handed

    def test_it_is_handed_on_before_the_request_is_written(self, on_screen, wake_name,
                                                           monkeypatch):
        """The copy brings its window to the front as it reads the request,
        so the right must be handed on by then."""
        import _winapi

        window, controller = on_screen
        _to_tray(window, controller)
        order = self._record(monkeypatch)
        real_write = _winapi.WriteFile

        def write(handle, data, *args, **kwargs):
            order.append("write")
            return real_write(handle, data, *args, **kwargs)

        monkeypatch.setattr(_winapi, "WriteFile", write)

        assert _ask(wake_name) is True
        assert order == ["hand on", "write"]
        assert pump_until(window.isVisible)

    def test_with_no_copy_in_the_tray_it_is_kept(self, on_screen, wake_name, monkeypatch):
        """A start that opens its own window has no copy to hand it to."""
        handed = self._record(monkeypatch)

        assert tray.bring_back_hidden_copy(_new_name(), 5000) is False  # nothing listening
        assert _ask(wake_name) is False  # a copy on screen
        assert handed == []

    def test_a_refused_hand_on_still_brings_the_copy_back(self, on_screen, wake_name,
                                                          monkeypatch, caplog):
        """Behind the window in front, with its taskbar button flashing,
        rather than not at all."""
        window, controller = on_screen
        _to_tray(window, controller)
        handed = self._record(monkeypatch, granted=False)

        with caplog.at_level(logging.DEBUG, logger=tray.__name__):
            assert _ask(wake_name) is True

        assert handed == ["hand on"]
        assert pump_until(window.isVisible)
        assert not controller.hidden_in_tray
        assert "Windows did not let this start hand on the foreground" in caplog.text

    def test_it_asks_windows_for_any_process(self, monkeypatch):
        from src.gui import global_hotkey

        class _User32:
            def __init__(self, answer: int):
                self.answer, self.asked = answer, []

            def AllowSetForegroundWindow(self, process):  # noqa: N802
                self.asked.append(process)
                return self.answer

        granted = _User32(1)
        monkeypatch.setattr(global_hotkey, "_user32", lambda: granted)
        assert global_hotkey.allow_any_foreground() is True
        assert granted.asked == [0xFFFFFFFF]  # ASFW_ANY, (DWORD)-1

        monkeypatch.setattr(global_hotkey, "_user32", lambda: _User32(0))  # Windows refuses
        assert global_hotkey.allow_any_foreground() is False
        monkeypatch.setattr(global_hotkey, "_user32", lambda: None)  # off Windows
        assert global_hotkey.allow_any_foreground() is False


def _second_start(spec_file: str) -> None:
    """Runs in the child process (see ``_run_second_start``): the real
    ``main()`` as a second start of a portable copy kept in tmp_path, up to
    its window, which is swapped for a line saying one would open."""
    spec = json.loads(Path(spec_file).read_text(encoding="utf-8"))

    import src.utils.settings as settings_module
    from src.utils import build_mode as child_build_mode

    child_build_mode.IS_PORTABLE = True
    data = Path(spec["data"])
    settings_module.AppSettings._portable_data_dir = staticmethod(lambda: data)

    class NoRegistry:
        def __getattr__(self, name):
            raise AssertionError(f"startup used the registry: winreg.{name}")

    def no_qsettings(*args, **kwargs):
        raise AssertionError("startup used the registry: QSettings")

    settings_module.winreg = NoRegistry()
    settings_module.QSettings = no_qsettings
    settings_module.read_launcher_installs = lambda log_path=None: ({}, False)
    settings_module.iter_shallow_sc_install_locations = lambda drives=None: iter(())

    import src.main as app_main

    # Never the real name, so a real Smart Citizen in this PC's tray stays put.
    app_main.instance_name = lambda: spec["name"]

    class WouldOpen:
        def __init__(self, *args, **kwargs):
            print(_OPENED, flush=True)
            os._exit(0)

    app_main.MainWindow = WouldOpen
    app_main.main()
    print(_ENDED, flush=True)
    os._exit(0)


def _run_second_start(tmp_path: Path, name: str) -> str:
    """Start Smart Citizen again in a child process, running this one's event
    loop meanwhile (a copy in the tray answers only then), and return what
    the child printed."""
    spec = tmp_path / "second_start.json"
    spec.write_text(json.dumps({"data": str(tmp_path / "second_start_data"), "name": name}),
                    encoding="utf-8")
    out_path = tmp_path / "second_start.out"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8")
    with open(out_path, "w", encoding="utf-8") as out:
        child = subprocess.Popen(
            [sys.executable, "-c",
             "import sys; from tests.test_minimize_to_tray import _second_start; "
             "_second_start(sys.argv[1])", str(spec)],
            cwd=REPO, env=env, stdout=out, stderr=subprocess.STDOUT)
        try:
            finished = pump_until(lambda: child.poll() is not None, seconds=120)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
    output = out_path.read_text(encoding="utf-8", errors="replace")
    assert finished, f"the second start did not end:\n{output}"
    assert child.returncode == 0, output
    return output


class TestTheRealMainAsksFirst:
    def test_a_copy_in_the_tray_comes_back_and_no_window_opens(self, on_screen, wake_name,
                                                               tmp_path):
        window, controller = on_screen
        window.showMaximized()
        _to_tray(window, controller)

        output = _run_second_start(tmp_path, wake_name)

        assert _ENDED in output and _OPENED not in output, output
        assert pump_until(window.isVisible)
        assert window.isMaximized() and not controller.hidden_in_tray
        # Asked before anything else ran: no migrator seeded the settings and
        # no user.ini was made for the start that ended.
        data = tmp_path / "second_start_data"
        assert not (data / "config.json").exists()
        assert not list(data.rglob("user.ini"))

    def test_a_copy_on_screen_lets_a_second_one_open(self, on_screen, wake_name, tmp_path):
        window, controller = on_screen

        output = _run_second_start(tmp_path, wake_name)

        assert _OPENED in output and _ENDED not in output, output
        assert window.isVisible() and not window.isMinimized()
        # The start that opens went on through the migrators as always.
        data = tmp_path / "second_start_data"
        assert (data / "config.json").exists()
        assert list(data.rglob("user.ini"))


@pytest.fixture
def notices(monkeypatch):
    """The tray told it can show notices (the offscreen platform cannot)."""
    monkeypatch.setattr(tray, "messages_supported", lambda: True)


def _record_notices(controller) -> list:
    """The notices the controller's icon is asked to show, recorded instead."""
    shown = []
    controller._icon.showMessage = lambda *args: shown.append(args)
    return shown


class TestTheNotice:
    """The one-time "still running" notice on the first trip to the tray."""

    def test_the_first_trip_to_the_tray_shows_it_once(self, on_screen, notices, english_ui):
        window, controller = on_screen
        shown = _record_notices(controller)

        _to_tray(window, controller)

        assert len(shown) == 1
        title, body, icon, msecs = shown[0]
        assert title == "Smart Citizen is still running"
        assert body == (
            "It is in the system tray. Click its icon to bring the window back, or "
            "right-click it to quit. If you can't see the icon, it may be behind the ^ "
            "arrow by the clock.")
        assert icon.cacheKey() == controller._icon.icon().cacheKey()
        assert msecs == tray.NOTICE_MS
        assert AppSettings.get_tray_notice_shown() is True

        controller.restore()
        _to_tray(window, controller)
        assert len(shown) == 1  # once only

    def test_once_shown_a_new_session_shows_none(self, on_screen, notices):
        window, controller = on_screen
        AppSettings.set_tray_notice_shown(True)  # a session before showed it
        shown = _record_notices(controller)

        _to_tray(window, controller)

        assert shown == []

    def test_where_the_tray_cannot_show_notices_it_waits(self, on_screen, monkeypatch):
        window, controller = on_screen
        can_show = [False]
        monkeypatch.setattr(tray, "messages_supported", lambda: can_show[0])
        shown = _record_notices(controller)

        _to_tray(window, controller)
        assert shown == []
        assert AppSettings.get_tray_notice_shown() is False

        controller.restore()
        can_show[0] = True
        _to_tray(window, controller)
        assert len(shown) == 1

    def test_a_minimize_that_stays_on_the_taskbar_shows_none(self, on_screen, notices):
        window, controller = on_screen
        shown = _record_notices(controller)
        box = QDialog(window)
        box.setModal(True)
        box.show()
        try:
            window.showMinimized()
            _settle()
            assert shown == []
            assert AppSettings.get_tray_notice_shown() is False
        finally:
            box.close()

    def test_a_click_on_the_notice_brings_the_window_back(self, on_screen, notices):
        window, controller = on_screen
        _record_notices(controller)
        _to_tray(window, controller)

        controller._icon.messageClicked.emit()

        assert window.isVisible() and not controller.hidden_in_tray

    def test_a_backup_leaves_its_record_out_of_the_defaults(self, tmp_profile):
        """Per-install state, like the tour's completed version: an import
        does not bring the notice back, or take it away, by default."""
        assert AppSettings.TRAY_NOTICE_SHOWN not in AppSettings.profile_default_values()
        assert AppSettings.TRAY_NOTICE_SHOWN in AppSettings.PROFILE_DEFAULT_EXCLUDE_KEYS


class TestTheName:
    def test_copies_that_share_settings_share_it(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_PORTABLE_FLAG, False)
        installed = tray.instance_name()
        monkeypatch.setattr(AppSettings, "get_user_data_dir",
                            staticmethod(lambda: tmp_path / "another data folder"))
        # Installed copies share the registry, whatever their data folder.
        assert tray.instance_name() == installed

        monkeypatch.setattr(_PORTABLE_FLAG, True)
        here = tmp_path / "here" / "data"
        there = tmp_path / "there" / "data"
        monkeypatch.setattr(AppSettings, "get_user_data_dir", staticmethod(lambda: here))
        portable_here = tray.instance_name()
        monkeypatch.setattr(AppSettings, "get_user_data_dir", staticmethod(lambda: there))
        portable_there = tray.instance_name()
        assert len({installed, portable_here, portable_there}) == 3

        if sys.platform == "win32":  # Windows names a folder in any case
            monkeypatch.setattr(AppSettings, "get_user_data_dir",
                                staticmethod(lambda: Path(str(here).upper())))
            assert tray.instance_name() == portable_here

    def test_another_user_gets_another_and_no_name_is_in_it(self, monkeypatch):
        monkeypatch.setattr(_PORTABLE_FLAG, False)
        me = getpass.getuser()
        mine = tray.instance_name()
        monkeypatch.setattr(tray.getpass, "getuser", lambda: "someone-else")
        assert tray.instance_name() != mine
        assert me not in mine


class TestTheMainWindow:
    """MainWindow's own part, on a real window (tests/gui_window.py)."""

    def test_the_config_tab_box_turns_it_on_and_off(self, qapp, tmp_path, monkeypatch,
                                                    wake_name, with_tray, quits, slot_errors):
        monkeypatch.setattr(config_tab_module, "tray_available", lambda: True)
        window = build_main_window(tmp_path, monkeypatch, AppSettings.UI_MODE_ADVANCED)
        try:
            box = window.config_tab.minimize_to_tray_cb
            assert not window._tray.enabled  # off until ticked
            assert box.isEnabled() and not box.isChecked()

            box.setChecked(True)
            assert window._tray.enabled
            assert AppSettings.get_minimize_to_tray() is True

            window.show()
            _to_tray(window, window._tray)
            window._tray.restore()
            assert window.isVisible()

            box.setChecked(False)
            assert not window._tray.enabled
            assert AppSettings.get_minimize_to_tray() is False
            assert slot_errors == []
        finally:
            window._tray.shut_down()
            retire_main_window(window)

    def test_a_window_built_with_it_on_has_it_on(
            self, qapp, tmp_path, monkeypatch, wake_name, with_tray, quits, english_ui):
        monkeypatch.setattr(config_tab_module, "tray_available", lambda: True)
        monkeypatch.setattr(AppSettings, "get_minimize_to_tray", staticmethod(lambda: True))
        window = build_main_window(tmp_path, monkeypatch, AppSettings.UI_MODE_ADVANCED)
        try:
            assert window._tray.enabled
            assert window.config_tab.minimize_to_tray_cb.isChecked()
            assert window._tray._icon.toolTip() == window.windowTitle()

            # A language switch sets the tray's texts with the window's.
            i18n.set_language("german")
            window.retranslate_ui()

            assert window._tray._show_action.text() == _ui_text("german", "tray", "show")
            assert window._tray._icon.toolTip() == window.windowTitle()
        finally:
            window._tray.shut_down()
            retire_main_window(window)

    @staticmethod
    def _closing_window(order: list):
        me = MagicMock()
        me._session_has_unapplied_edit = False
        me._suppress_user_ini_autosave = False
        me._loader_worker = None
        me._user_resized_columns = False
        me.entries = []
        me._close_committed = False

        def icon_down():
            assert me._close_committed is True  # only once the close is final
            order.append("tray")

        me._tray.shut_down.side_effect = icon_down
        me._request_stops_for_close.side_effect = lambda: order.append("stops")
        return me

    def test_a_close_takes_the_icon_down_once_it_is_final(self, monkeypatch):
        """Before the workers are asked to stop, so the icon cannot bring the
        window back while the close waits for them with it hidden."""
        for setter in ("set_window_state", "set_window_geometry", "set_string_column_widths"):
            monkeypatch.setattr(AppSettings, setter, staticmethod(lambda *a, **k: None))
        order = []

        MainWindow.closeEvent(self._closing_window(order), MagicMock())

        assert order[:2] == ["tray", "stops"]

    def test_a_cancelled_close_keeps_the_icon(self, monkeypatch):
        buttons = [MagicMock(name="apply"), MagicMock(name="exit"), MagicMock(name="cancel")]
        box = MagicMock()
        box.addButton.side_effect = list(buttons)
        box.clickedButton.return_value = buttons[2]
        monkeypatch.setattr(main_window_module, "QMessageBox", MagicMock(return_value=box))
        me = self._closing_window([])
        me._session_has_unapplied_edit = True

        MainWindow.closeEvent(me, MagicMock())

        me._tray.shut_down.assert_not_called()


class TestEveryLanguage:
    def test_every_language_has_the_texts(self):
        for ui in sorted((REPO / "languages").glob("*/ui.json")):
            data = json.loads(ui.read_text(encoding="utf-8"))
            for section, key in _NEW_KEYS:
                leaf = data[section][key]
                where = f"{ui.parent.name} {section}.{key}"
                if ui.parent.name == "english":
                    assert leaf["ht"] and leaf["at"] == "", where
                else:
                    # An AI text, waiting for a translator (languages/TRANSLATIONS.md).
                    assert leaf["ht"] == "" and leaf["at"], where

    def test_every_help_names_the_box_by_its_own_label(self):
        for ui in sorted((REPO / "languages").glob("*/ui.json")):
            language = ui.parent.name
            help_md = REPO / ("docs/HELP.md" if language == "english"
                              else f"languages/{language}/HELP.md")
            label = _ui_text(language, "config", "minimize_to_tray_cb")
            assert f"**{label}**" in help_md.read_text(encoding="utf-8"), language

    def test_every_tour_appearance_step_names_the_box_by_its_own_label(self):
        """The guided tour's step on the group the box is in: English from
        ``assets/tutorial.json`` (English ui.json has no tour texts), the rest
        from their ui.json."""
        steps = json.loads((REPO / "assets" / "tutorial.json").read_text(encoding="utf-8"))
        english = next(step["description"] for step in steps["steps"]
                       if step["id"] == "cfg_appearance")
        for ui in sorted((REPO / "languages").glob("*/ui.json")):
            language = ui.parent.name
            shown = (english if language == "english"
                     else _ui_text(language, "tutorial", "cfg_appearance", "description"))
            assert _ui_text(language, "config", "minimize_to_tray_cb") in shown, language

    def test_every_notice_fits_what_windows_shows(self):
        """Windows cuts a notice's title at 63 characters and its body at
        255 (the tray's szInfoTitle and szInfo, which hold a null too)."""
        for ui in sorted((REPO / "languages").glob("*/ui.json")):
            language = ui.parent.name
            title = _ui_text(language, "tray", "notice_title")
            body = _ui_text(language, "tray", "notice_body")
            assert 0 < len(title) <= 63, (language, len(title))
            assert 0 < len(body) <= 255, (language, len(body))
