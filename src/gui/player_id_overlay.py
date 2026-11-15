"""Player ID test: a mark round each name tag the overlay reads.

``PlayerIdOverlay`` looks at the game's window a few times a second while
the game is the window in front, reads the name tags over ships and players
(``sco_tag_scan.TagScanner``), decides which readings are names and what
colour each gets (``player_id.PlayerIdTracker``, from the player's own lists),
and draws a placeholder mark round each one in ``PlayerMarkWindow``, a
see-through window over the game that clicks pass through.

It is a test of the reading. The marks are placeholders and nothing is
looked up anywhere: the lists are kept by hand on the Overlay tab
(``player_lists_dialog.py``) and saved with the settings
(``AppSettings.get_/set_player_lists``).

The same looks highlight the locations on the player's own list
(``AppSettings.get_/set_location_list``): a marker whose text is on it gets
a whole frame in its colour. Either switch, names or locations, runs the
looks. The names read are also kept from session to session for the lists
editor (``AppSettings.get_/set_player_history``), on this PC only.

The looks run on a pool thread of their own, one at a time, as the scan
decoder's reads do. A look is pure Python and takes a few tenths of a second,
so the marks trail a tag that moves. ``status`` says how it is going, for the
Overlay tab: waiting for the game, or what the last look read and marked.

Like the rest of the overlay it only captures the desktop: no hooks, no
handle to the game's process, nothing read from it or sent to it. The mark
window is left out of screen captures (``SetWindowDisplayAffinity`` on our
own window), so the next look does not read its own marks.
"""
from __future__ import annotations

import ctypes
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QRect, QRectF, QRunnable, Qt, QThreadPool, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from src.utils import game_window
from src.utils.player_id import (
    PastPlayers, PlaceList, PlayerIdTracker, PlayerLists, read_game_words,
)
from src.utils.sco_tag_reader import Frame
from src.utils.sco_tag_scan import TagScanner
from src.utils.settings import AppSettings

logger = logging.getLogger(__name__)

# How often a new look is tried. A look takes longer than this, and a tick
# that lands while one is running is skipped, so looks run back to back.
LOOK_INTERVAL_MS = 120
# How often the status is sent while looks are running.
STATUS_EVERY_S = 1.0
# How often the log gets a line on how the looks are going.
REPORT_EVERY_S = 60.0
# Tuning only, like sco_overlay.SAVE_SAMPLES_ENV: with this set when the app
# starts, whatever window is in front counts as the game, so the reader can
# be tried on a saved picture in an image viewer. The app has no switch for it.
ANY_WINDOW_ENV = "SMART_CITIZEN_PLAYER_ID_ANY_WINDOW"

# How a session is named in the record of past players: text that sorts by
# time, and reads as a date and a time.
SESSION_FORMAT = "%Y-%m-%d %H:%M:%S"

# What ``PlayerIdOverlay.status`` says (the Overlay tab words each one).
STATUS_OFF = "off"                # not running
STATUS_STARTING = "starting"      # reading the game's own words
STATUS_NO_GAME = "no_game"        # running, the game is not the window in front
STATUS_LOOKING = "looking"        # looking at the game: the last look's figures
STATUS_FAILED = "failed"          # a look raised and the loop stopped

# Room between a name and its mark, in capital heights. Wider when the mark
# window could not be left out of captures, so a mark is not read as
# something standing beside the name.
MARK_GAP = 0.6
MARK_GAP_CAPTURED = 2.0
# Windows' "leave this window out of screen captures" (Windows 10 2004 on).
_WDA_EXCLUDEFROMCAPTURE = 0x00000011

_MARK_FLAGS = (
    Qt.WindowType.Tool
    | Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.WindowStaysOnTopHint
    | Qt.WindowType.WindowTransparentForInput
    | Qt.WindowType.WindowDoesNotAcceptFocus
)


def frame_of(image: QImage) -> Frame:
    """A capture as the reader's three channels."""
    image = image.convertToFormat(QImage.Format.Format_RGB32)
    width, height = image.width(), image.height()
    if image.bytesPerLine() != width * 4:
        raise ValueError("unexpected row padding")
    return Frame.from_rgb32(width, height, image.constBits().asstring(image.sizeInBytes()))


class PlayerMarkWindow(QWidget):
    """Click-through, see-through window over the game's picture that draws
    a placeholder mark round each name: four corner brackets in the name's
    colour, with its label above them (the org a listed player is under, or
    the text that was read while the test switch is on). A listed name gets
    the thickest brackets, and a reading that is not a trusted name the
    thinnest. A location on the player's list gets a whole frame instead."""

    def __init__(self):
        super().__init__(None, _MARK_FLAGS)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._marks: list = []
        self._ratio = 1.0
        # False once Windows has refused to leave the window out of captures.
        self.hidden_from_capture: Optional[bool] = None

    def set_marks(self, marks: list, ratio: float) -> None:
        """Show *marks* (``player_id.Mark``, boxes in capture pixels).
        *ratio* is capture pixels to one of this window's own."""
        self._marks, self._ratio = list(marks), ratio or 1.0
        self.update()

    def marks(self) -> list:
        return list(self._marks)

    def showEvent(self, event):  # noqa: N802 (Qt's name)
        super().showEvent(event)
        if self.hidden_from_capture is None:
            self.hidden_from_capture = self._leave_out_of_captures()

    def _leave_out_of_captures(self) -> bool:
        if sys.platform != "win32" or QGuiApplication.platformName() != "windows":
            return False
        try:
            done = ctypes.windll.user32.SetWindowDisplayAffinity(
                ctypes.c_void_p(int(self.winId())), _WDA_EXCLUDEFROMCAPTURE)
        except (OSError, AttributeError):
            done = 0
        if done:
            logger.info("Player ID: the mark window is left out of screen captures, so the "
                        "marks show on the screen and not in a screenshot or a recording")
        else:
            logger.info("Player ID: Windows would not leave the mark window out of screen "
                        "captures, so marks are drawn further from the names")
        return bool(done)

    def paintEvent(self, _event):  # noqa: N802 (Qt's name)
        if not self._marks:
            return
        painter = QPainter(self)
        gap = MARK_GAP if self.hidden_from_capture else MARK_GAP_CAPTURED
        font = QFont(self.font())
        font.setBold(True)
        for mark in self._marks:
            x, y, w, h = (value / self._ratio for value in mark.box)
            pad = max(4.0, gap * h)
            rect = QRectF(x - pad, y - pad, w + 2 * pad, h + 2 * pad)
            color = QColor(mark.color)
            if not mark.trusted:
                color.setAlpha(190)
            pen = QPen(color)
            # Thick enough to see on a 4K picture, where a name is 17 px tall.
            share, least = (0.2, 3) if mark.listed else (0.14, 2) if mark.trusted else (0.08, 1)
            pen.setWidth(max(least, round(share * h)))
            painter.setPen(pen)
            if mark.place:
                # A location on the player's list: a whole frame, where a
                # name gets corner brackets.
                painter.drawRect(rect)
            else:
                corner = max(4.0, min(0.6 * rect.height(), 0.25 * rect.width(), 16.0))
                for cx, sx in ((rect.left(), 1), (rect.right(), -1)):
                    for cy, sy in ((rect.top(), 1), (rect.bottom(), -1)):
                        painter.drawLine(int(cx), int(cy), int(cx + sx * corner), int(cy))
                        painter.drawLine(int(cx), int(cy), int(cx), int(cy + sy * corner))
            if mark.label:
                font.setPixelSize(max(9, int(1.1 * h)))
                painter.setFont(font)
                where = QRectF(rect.left(), rect.top() - 1.9 * h - 2, max(rect.width(), 300.0),
                               1.8 * h)
                flags = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom
                painter.setPen(QColor(0, 0, 0, 200))
                painter.drawText(where.translated(1, 1), flags, mark.label)
                painter.setPen(QColor(mark.color))
                painter.drawText(where, flags, mark.label)
        painter.end()


class _WordsTask(QRunnable):
    """Reads the game's own words from the English base.ini off the GUI
    thread (the file is about 10 MB)."""

    def __init__(self, path: Path, done: pyqtSignal, token: int):
        super().__init__()
        self._path, self._done, self._token = path, done, token

    def run(self) -> None:
        try:
            words = read_game_words(self._path)
        except OSError as error:
            logger.info("Player ID: the game's words could not be read from %s (%s), so more "
                        "of the game's own text may pass for a name", self._path, error)
            words = frozenset()
        self._done.emit(self._token, words)


class _LookTask(QRunnable):
    """One look at a capture of the game's picture, off the GUI thread."""

    def __init__(self, scanner: TagScanner, image: QImage, now: float, done: pyqtSignal,
                 token: int):
        super().__init__()
        self._scanner, self._image, self._now = scanner, image, now
        self._done, self._token = done, token

    def run(self) -> None:
        try:
            readings, failed = self._scanner.scan(frame_of(self._image), self._now), False
        except Exception:
            # WARNING, not ERROR: an ERROR record opens the error box, which
            # would land over the game.
            logger.warning("Player ID: a look failed, so it has stopped", exc_info=True)
            readings, failed = [], True
        self._done.emit(self._token, readings, failed)


class PlayerIdOverlay(QObject):
    """Owns the mark window and the loop of looks."""

    # (token, the look's readings, the look raised); from the pool thread.
    _look_done = pyqtSignal(int, object, bool)
    # (token, the game's words); from the pool thread.
    _words_done = pyqtSignal(int, object)
    # A look raised and the loop stopped. Stopping and starting tries again.
    failed = pyqtSignal()
    # How it is going: one of the STATUS_ names, and for STATUS_LOOKING the
    # last look's figures (width, height, seconds, lines, skipped, read,
    # marked: skipped counts the lines left out for having no distance line).
    status = pyqtSignal(str, dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.window = PlayerMarkWindow()
        self.tracker = PlayerIdTracker()
        self._scanner: Optional[TagScanner] = None
        self._any_window = bool(os.environ.get(ANY_WINDOW_ENV))
        self._timer = QTimer(self)
        self._timer.setInterval(LOOK_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._running = False
        self._looking = False
        self._in_front = False            # the game was the window in front at the last tick
        self._token = 0
        self._words_ready = False
        self._ratio = 1.0
        self._size = None                 # the capture's size at the last look
        self._report_at = 0.0
        self._status_at = 0.0
        self._last_status = (STATUS_OFF, {})
        self._look_times: list[float] = []
        # The names read in play, kept from session to session, and this
        # session's name in that record: when it first started (``start``).
        self._past = PastPlayers()
        self._session = ""
        # Whether only text with a distance line under it is read
        # (``set_distance_filter``), for the scanner once there is one.
        self._distance_filter = False
        self._look_done.connect(self._on_look_done)
        self._words_done.connect(self._on_words_done)

    def is_running(self) -> bool:
        return self._running

    def set_marking(self, names: bool, unlisted: bool, everything: bool, places: bool) -> None:
        """The Overlay tab's switches: whether players' names are marked,
        under that whether names on no list are marked too and the test
        switch that marks every tag read at once, and whether the locations
        on the player's list are highlighted."""
        tracker = self.tracker
        before = (tracker.mark_names, tracker.mark_places, tracker.mark_unlisted, tracker.mark_all)
        tracker.mark_names, tracker.mark_places = bool(names), bool(places)
        tracker.mark_unlisted, tracker.mark_all = bool(unlisted), bool(everything)
        if before != (tracker.mark_names, tracker.mark_places, tracker.mark_unlisted,
                      tracker.mark_all):
            # A mark stays on its tag from look to look, so the marks made
            # under the old switches go: the next look makes them afresh.
            tracker.reset()

    def set_distance_filter(self, on: bool) -> None:
        """The Overlay tab's switch under both halves: read only text that
        has a distance line under it, as every marker in the game has
        (``sco_tag_scan.distance_under``). A look that is running takes it
        from its next line on."""
        self._distance_filter = bool(on)
        if self._scanner is not None:
            self._scanner.need_distance = self._distance_filter

    def reload_lists(self) -> None:
        """Take the lists, the locations and the record of past players as
        the settings hold them now (a change made on the Overlay tab).
        Nothing is read while it is not running: ``start`` reads them."""
        if not self._running:
            return
        lists = PlayerLists.from_data(AppSettings.get_player_lists())
        places = PlaceList.from_data(AppSettings.get_location_list())
        for problem in lists.problems + places.problems:
            logger.warning("Player ID lists: %s", problem)
        self.tracker.lists, self.tracker.places = lists, places
        # The marks made from the old lists go, as in ``set_marking``.
        self.tracker.reset()
        self._past = PastPlayers.from_data(AppSettings.get_player_history())

    def _keep_new_names(self) -> None:
        """Add the names the last look read for the first time to the record
        of past players and save it. They stay on this PC."""
        names = self.tracker.take_new_names()
        if not names:
            return
        changed = [self._past.saw(name, self._session) for name in names]
        if any(changed):
            AppSettings.set_player_history(self._past.to_data())

    def last_status(self) -> tuple[str, dict]:
        return self._last_status

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        if self._scanner is None:
            self._scanner = TagScanner()
        self._scanner.need_distance = self._distance_filter
        if not self._session:
            self._session = time.strftime(SESSION_FORMAT)
        self.reload_lists()
        self._words_ready = False
        self._report_at = time.monotonic() + REPORT_EVERY_S
        self._look_times = []
        base_ini = AppSettings.get_base_ini_path(AppSettings.DEFAULT_LANGUAGE)
        self._pool.start(_WordsTask(base_ini, self._words_done, self._token))
        self._timer.start()
        self._say(STATUS_STARTING)
        logger.info("Player ID: started, %s%s%s%s%s",
                    f"{len(self.tracker.lists.players)} players on the lists"
                    if self.tracker.mark_names else "names are not marked",
                    f", {len(self.tracker.places.places)} locations to highlight"
                    if self.tracker.mark_places else "",
                    ", marking everything read (the test switch)"
                    if self.tracker.mark_names and self.tracker.mark_all else "",
                    ", reading only text with a distance line under it"
                    if self._distance_filter else ", reading text with or without a distance line",
                    " (any window counts as the game)" if self._any_window else "")

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._timer.stop()
        self._token += 1
        self.tracker.reset()
        self.window.set_marks([], self._ratio)
        self.window.hide()
        self._say(STATUS_OFF)

    def wait_for_reader(self, msecs: int = -1) -> bool:
        """Block until no look is running (used on close and in tests)."""
        return self._pool.waitForDone(msecs)

    def _say(self, state: str, **figures) -> None:
        self._last_status = (state, figures)
        self._status_at = time.monotonic()
        self.status.emit(state, figures)

    def _on_words_done(self, token: int, words) -> None:
        if token != self._token:
            return
        self.tracker.words = words
        self._words_ready = True
        logger.info("Player ID: %d of the game's own words will not pass for a name", len(words))

    def _tick(self) -> None:
        if not self._running or self._looking or not self._words_ready:
            return
        area = game_window.foreground_game_area(self._any_window, (int(self.window.winId()),))
        if area is None:
            # The game is not in front: nothing to read, nothing to mark.
            self._in_front = False
            if self.window.isVisible():
                self.tracker.reset()
                self.window.set_marks([], self._ratio)
                self.window.hide()
            if self._last_status[0] != STATUS_NO_GAME:
                self._say(STATUS_NO_GAME)
            return
        captured = self._capture(area)
        if captured is None:
            return
        self._in_front = True
        image, geometry, ratio = captured
        size = (image.width(), image.height())
        if size != self._size:
            # Another window size: every remembered place is somewhere else.
            self._size = size
            self._scanner.reset()
            self.tracker.reset()
            logger.info("Player ID: looking at the game's picture, %d by %d pixels at (%d, %d) "
                        "on the screen, %.2f pixels to a point", size[0], size[1],
                        area[0], area[1], ratio)
        self._ratio = ratio
        if self.window.geometry() != geometry:
            self.window.setGeometry(geometry)
        if not self.window.isVisible():
            self.window.show()
        self._looking = True
        self._pool.start(_LookTask(self._scanner, image, time.monotonic(), self._look_done,
                                   self._token))

    def _capture(self, area):
        """The game's picture, the mark window's place over it and the
        capture pixels to one logical pixel, or None when it cannot be had."""
        centre_x, centre_y = area[0] + area[2] / 2, area[1] + area[3] / 2
        found = None
        for screen in QGuiApplication.screens():
            geometry, ratio = screen.geometry(), screen.devicePixelRatio()
            # Qt keeps a screen's top-left corner in screen pixels and scales
            # only its size.
            native = (geometry.x(), geometry.y(), round(geometry.width() * ratio),
                      round(geometry.height() * ratio))
            if found is None:
                found = (screen, native, ratio)
            if (native[0] <= centre_x < native[0] + native[2]
                    and native[1] <= centre_y < native[1] + native[3]):
                found = (screen, native, ratio)
                break
        if found is None:
            return None
        screen, native, ratio = found
        capture = screen.grabWindow(0).toImage()
        if capture.isNull():
            return None
        x, y, w, h = game_window.window_in_capture(area, native[:2],
                                                   (capture.width(), capture.height()))
        if w < game_window.SMALLEST_WINDOW[0] or h < game_window.SMALLEST_WINDOW[1]:
            return None
        if (x, y, w, h) != (0, 0, capture.width(), capture.height()):
            capture = capture.copy(x, y, w, h)
        geometry = QRect(round(native[0] + x / ratio), round(native[1] + y / ratio),
                         round(w / ratio), round(h / ratio))
        return capture, geometry, ratio

    def _on_look_done(self, token: int, readings, failed: bool) -> None:
        self._looking = False
        if token != self._token or not self._running:
            return
        if failed:
            self.stop()
            self._say(STATUS_FAILED)
            self.failed.emit()
            return
        if not self._in_front:
            return                       # the game went to the back during the look
        now = time.monotonic()
        marks = self.tracker.look(readings, now)
        self.window.set_marks(marks, self._ratio)
        self._keep_new_names()
        seconds = self._scanner.last_total_s
        self._look_times.append(seconds)
        if self._last_status[0] != STATUS_LOOKING or now - self._status_at >= STATUS_EVERY_S:
            width, height = self._size or (0, 0)
            self._say(STATUS_LOOKING, width=width, height=height, seconds=round(seconds, 2),
                      lines=self._scanner.last_lines, skipped=self._scanner.last_no_distance,
                      read=len(readings), marked=len(marks))
        if now >= self._report_at:
            times = sorted(self._look_times)
            logger.info("Player ID: %d looks in the last minute, a look took %.2f s in the "
                        "middle and %.2f s at most, %d names marked now",
                        len(times), times[len(times) // 2], times[-1], len(marks))
            self._look_times = []
            self._report_at = now + REPORT_EVERY_S
