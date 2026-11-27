"""Minimize to tray: the tray icon, the trip there and the way back.

With the Config tab's Minimize to Tray ticked (``AppSettings.
get_minimize_to_tray``), minimizing the window hides it in the system tray,
the icons next to the clock, instead of on the taskbar. A click on the tray
icon, or its Show Smart Citizen, brings the window back as it was (a
maximized window comes back maximized), and its Quit closes the app the way
the window's X does. The first trip to the tray ever shows a notice by the
clock that Smart Citizen is still running, as other tray apps do.

While the window is in the tray, starting Smart Citizen again brings it back
instead of opening a second copy. The hidden copy listens on a local socket
named for the settings it uses (``instance_name``), and ``src/main.py`` asks
``bring_back_hidden_copy`` first, before any migrator runs or any window is
built. Either the copy takes the request and comes back, or it never sees it
and stays in the tray while this start opens: never both. A copy on screen
does not listen, so a second copy still opens beside it, as before.

The overlay's label and drawer are top-level windows of their own, not
children of the main window, so they stay up while it is in the tray.
"""
import functools
import getpass
import hashlib
import logging
import os
import sys
import time
from typing import Optional

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon

from src.gui.global_hotkey import allow_any_foreground
from src.utils.i18n import tr
from src.utils.settings import AppSettings

logger = logging.getLogger(__name__)

# What a second start sends the copy in the tray. One line.
WAKE_MESSAGE = b"show\n"
# How long a second start waits for the copy to take it before it opens as
# usual. A copy busy for a moment still comes back, and only one that stays
# busy longer than this lets a second copy open.
WAKE_TIMEOUT_MS = 5000

# How long the one-time "still running" notice asks to stay up. Windows 10
# and 11 show it as a notification and go by their own timing.
NOTICE_MS = 8000

# Where Windows keeps named pipes. QLocalServer listens on <this><name>.
_PIPE_PREFIX = "\\\\.\\pipe\\"


def tray_available() -> bool:
    """Whether this desktop has a system tray to minimize to."""
    return QSystemTrayIcon.isSystemTrayAvailable()


def messages_supported() -> bool:
    """Whether the tray can show a notice (Windows: unless Explorer's
    balloon tips are turned off)."""
    return QSystemTrayIcon.supportsMessages()


def instance_name() -> str:
    """The name a copy in the tray listens on for a second start.

    Copies that share settings share it: every installed copy of one Windows
    user (they share the registry), or one portable folder (its settings sit
    beside the exe). Another user or another portable folder gets a name of
    its own, so starting one never brings back the other. Only a hash of the
    user and the folder goes into the name.
    """
    from src.utils import build_mode
    if build_mode.IS_PORTABLE:
        scope = "portable:" + os.path.normcase(os.path.abspath(AppSettings.get_user_data_dir()))
    else:
        scope = "registry"
    try:
        user = getpass.getuser()
    except Exception:  # no user name to be had: one name for all of them
        user = ""
    digest = hashlib.sha256(f"{user}\n{scope}".encode("utf-8")).hexdigest()[:16]
    return f"SmartCitizen-tray-{digest}"


def bring_back_hidden_copy(name: str, timeout_ms: int = WAKE_TIMEOUT_MS) -> bool:
    """Ask a copy minimized to the tray to come back.

    True when a copy listening on *name* took the request, so this start
    should end without opening a window: the copy brings its window back as
    it reads it. False when nothing listens (no copy is in the tray), or the
    copy did not take it within *timeout_ms*: this start then opens as usual,
    and the copy never sees the request, so it stays in the tray. Never both,
    so a busy copy cannot leave two windows open.

    Plain Windows pipe calls, no Qt, so ``main()`` can ask before it builds
    the QApplication or runs a migrator, and a start that ends here does
    nothing else. Qt's local server makes its pipes with no buffer, so a
    write finishes only once the copy has read it, and a write cancelled
    before that leaves the copy nothing to read (both measured).
    """
    if sys.platform != "win32":
        return False
    import _winapi

    deadline = time.monotonic() + timeout_ms / 1000
    try:
        handle = _open_pipe(_PIPE_PREFIX + name, deadline)
        if handle is None:
            return False  # no copy is in the tray
        try:
            # Windows lets only the program the user just started take the
            # foreground, which here is this start, so it hands that right on
            # first. Without it the copy's window comes back behind the one
            # in front, with its taskbar button flashing.
            if not allow_any_foreground():
                logger.debug("Windows did not let this start hand on the foreground")
            write, error = _winapi.WriteFile(handle, WAKE_MESSAGE, overlapped=True)
            if error == _winapi.ERROR_IO_PENDING:
                wait_ms = max(0, round((deadline - time.monotonic()) * 1000))
                done = _winapi.WaitForMultipleObjects([write.event], False, wait_ms)
                if done != _winapi.WAIT_OBJECT_0:
                    write.cancel()  # not read by now, so it never will be
            written, error = write.GetOverlappedResult(True)
        finally:
            _winapi.CloseHandle(handle)
    except OSError as exc:
        logger.warning(
            "Could not ask the copy of Smart Citizen in the system tray to come back (%s), "
            "so another copy opens", exc)
        return False
    if error == 0 and written == len(WAKE_MESSAGE):
        return True
    logger.warning(
        "A copy of Smart Citizen in the system tray did not answer within %.1f s, so "
        "another copy opens and that one stays in the tray", timeout_ms / 1000)
    return False


def _open_pipe(path: str, deadline: float):
    """A handle on the pipe at *path* for overlapped writes, or None when
    nothing listens there or every instance of it stayed busy until
    *deadline* (monotonic seconds)."""
    import _winapi

    while True:
        try:
            return _winapi.CreateFile(
                path, _winapi.GENERIC_READ | _winapi.GENERIC_WRITE, 0, _winapi.NULL,
                _winapi.OPEN_EXISTING, _winapi.FILE_FLAG_OVERLAPPED, _winapi.NULL)
        except FileNotFoundError:
            return None
        except OSError as exc:
            if exc.winerror != _winapi.ERROR_PIPE_BUSY:
                raise
        wait_ms = round((deadline - time.monotonic()) * 1000)
        if wait_ms <= 0:
            return None
        try:
            _winapi.WaitNamedPipe(path, wait_ms)
        except OSError:
            return None


def _quit_app() -> None:
    QApplication.quit()


class TrayController(QObject):
    """The tray icon and the main window's trips to and from the tray.

    It watches the window's state changes through an event filter, so the
    window needs no code of its own for it beyond building this, wiring the
    Config tab's tick box to ``set_enabled`` and calling ``retranslate_ui``
    and ``shut_down``.
    """

    def __init__(self, window) -> None:
        super().__init__(window)
        self._window = window
        self._icon: Optional[QSystemTrayIcon] = None
        self._menu: Optional[QMenu] = None
        self._show_action = None
        self._quit_action = None
        # Only while the window is in the tray (see _start_listening).
        self._server: Optional[QLocalServer] = None
        self._hidden = False
        # What the window was before its last minimize, so it comes back so.
        self._state_before_minimize = Qt.WindowState.WindowNoState
        # The app's quit-on-last-window rule while the window is in the tray.
        self._quit_rule: Optional[bool] = None
        # Set by shut_down: the app is closing, so nothing brings it back.
        self._shut_down = False
        window.installEventFilter(self)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shut_down)

    @property
    def enabled(self) -> bool:
        """Whether minimize to tray is on (its icon made)."""
        return self._icon is not None

    @property
    def hidden_in_tray(self) -> bool:
        """Whether the window is hidden in the tray right now."""
        return self._hidden

    def set_enabled(self, enabled: bool) -> None:
        """Turn minimize to tray on or off (the Config tab's tick box).

        The icon is made even where the desktop has no system tray yet (a
        start before the taskbar is up): Qt puts it in the tray once one
        appears. Until then a minimize stays on the taskbar (``_may_hide``),
        so the window is never hidden with no icon to bring it back with.
        Turning it off while the window is in the tray brings it back.
        """
        if enabled and self._icon is None:
            if not tray_available():
                logger.info(
                    "No system tray yet, so Smart Citizen minimizes to the taskbar until one "
                    "appears")
            self._create_icon()
        elif not enabled and self._icon is not None:
            if self._hidden:
                self.restore()
            self._remove_icon()

    def retranslate_ui(self) -> None:
        """Set the tray texts again after a language switch."""
        if self._icon is None:
            return
        self._icon.setToolTip(self._window.windowTitle())
        self._show_action.setText(tr("tray.show"))
        self._quit_action.setText(tr("tray.quit"))

    def restore(self) -> None:
        """Bring the window back on screen as it was before it was minimized.

        A window already on screen only comes to the front, keeping its size.
        """
        self._stop_listening()
        if self._hidden:
            self._hidden = False
            self._put_back_quit_rule()
        window = self._window
        if window.isMinimized() or not window.isVisible():
            state = self._state_before_minimize
            if state & Qt.WindowState.WindowFullScreen:
                window.showFullScreen()
            elif state & Qt.WindowState.WindowMaximized:
                window.showMaximized()
            else:
                window.showNormal()
        window.raise_()
        window.activateWindow()

    def quit(self) -> None:
        """Close the app as the window's X does (the tray menu's Quit).

        The window comes back first, so a question the close asks (unapplied
        changes) has its window behind it, and the window's place and size
        are saved as they show.
        """
        self.restore()
        self._window.close()

    def shut_down(self) -> None:
        """The app is closing: take the icon down and stop listening.

        A window that closes while in the tray (Windows signing the user out,
        say) never counted as shown, so Qt would not quit when it closed and
        the app would run on with no window: the app is told to quit instead.
        A request a second start sent just before is not acted on any more.
        """
        self._shut_down = True
        self._stop_listening()
        if self._icon is not None:
            self._remove_icon()
        if self._hidden:
            self._hidden = False
            self._put_back_quit_rule()
            QTimer.singleShot(0, _quit_app)

    def eventFilter(self, watched, event) -> bool:
        if watched is self._window and event.type() == QEvent.Type.WindowStateChange:
            old = event.oldState()
            if self._window.isMinimized() and not (old & Qt.WindowState.WindowMinimized):
                self._state_before_minimize = old
                if self._may_hide():
                    # On the next pass of the event loop: hiding from inside
                    # Windows' own minimize leaves its taskbar state behind.
                    QTimer.singleShot(0, self._hide_to_tray)
        return super().eventFilter(watched, event)

    def _may_hide(self) -> bool:
        # A window with a modal box open stays on the taskbar, where the box
        # minimized with it can be found again. So does one with no system
        # tray to show its icon in, asked at each minimize, so a tray that
        # appears after the start is used from then on.
        return (self._icon is not None and not self._hidden
                and QApplication.activeModalWidget() is None and tray_available())

    def _hide_to_tray(self) -> None:
        window = self._window
        if not (window.isMinimized() and self._may_hide()):
            return  # brought back, turned off or a box opened meanwhile
        app = QApplication.instance()
        # While the window is hidden, a box or other window that closes would
        # otherwise be taken for the last one and quit the app behind the
        # user's back, with no closeEvent to stop the running jobs.
        self._quit_rule = app.quitOnLastWindowClosed()
        app.setQuitOnLastWindowClosed(False)
        self._hidden = True
        window.hide()
        self._start_listening()
        logger.info("Minimized to the system tray")
        self._show_notice_once()

    def _show_notice_once(self) -> None:
        """On the first trip to the tray only, ever: a notice by the clock
        that Smart Citizen is still running, which a click brings the window
        back from. Windows shows it as a notification, so Do Not Disturb or
        notifications turned off for the app keep it quiet. Where the tray
        cannot show notices at all, it waits for a trip where it can."""
        if not messages_supported() or AppSettings.get_tray_notice_shown():
            return
        self._icon.showMessage(tr("tray.notice_title"), tr("tray.notice_body"),
                               self._icon.icon(), NOTICE_MS)
        AppSettings.set_tray_notice_shown(True)

    def _put_back_quit_rule(self) -> None:
        if self._quit_rule is not None:
            QApplication.instance().setQuitOnLastWindowClosed(self._quit_rule)
            self._quit_rule = None

    def _create_icon(self) -> None:
        self._menu = QMenu(self._window)
        self._show_action = self._menu.addAction("")
        self._show_action.triggered.connect(self.restore)
        self._menu.addSeparator()
        self._quit_action = self._menu.addAction("")
        self._quit_action.triggered.connect(self.quit)
        icon = self._window.windowIcon()
        if icon.isNull():
            icon = self._window.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self._icon = QSystemTrayIcon(icon, self)
        self._icon.setContextMenu(self._menu)
        self._icon.activated.connect(self._on_activated)
        # A click on the "still running" notice brings the window back too.
        self._icon.messageClicked.connect(self.restore)
        self.retranslate_ui()
        self._icon.show()

    def _remove_icon(self) -> None:
        self._icon.hide()
        self._icon.deleteLater()
        self._menu.deleteLater()
        self._icon = None
        self._menu = None
        self._show_action = None
        self._quit_action = None

    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.restore()

    def _start_listening(self) -> None:
        if self._server is not None:
            return
        server = QLocalServer(self)
        # Only this Windows user's programs may connect.
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        server.newConnection.connect(functools.partial(self._take_connections, server))
        if not server.listen(instance_name()):
            logger.warning(
                "Could not listen for a second start of Smart Citizen (%s), so one "
                "would open another copy",
                server.errorString(),
            )
            server.deleteLater()
            return
        self._server = server

    def _stop_listening(self) -> None:
        if self._server is None:
            return
        self._server.close()
        self._server.deleteLater()
        self._server = None

    def _take_connections(self, server: QLocalServer) -> None:
        while server.hasPendingConnections():
            socket = server.nextPendingConnection()
            # Its own, so it outlives the server, which goes once the window
            # is back, until the line has been read.
            socket.setParent(self)
            socket.disconnected.connect(socket.deleteLater)
            socket.readyRead.connect(functools.partial(self._read_wake, socket))
            self._read_wake(socket)  # the line may be in already

    def _read_wake(self, socket: QLocalSocket) -> None:
        # No answer is sent: the second start's write finishing is the answer
        # (see bring_back_hidden_copy), so reading the line commits this copy.
        if not socket.canReadLine():
            return
        if bytes(socket.readLine()) == WAKE_MESSAGE and not self._shut_down:
            logger.info(
                "Smart Citizen was started again while in the system tray: "
                "showing this copy instead of opening another"
            )
            self.restore()
        socket.disconnectFromServer()
