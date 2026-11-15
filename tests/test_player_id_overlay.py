"""The player ID test's overlay (``src/gui/player_id_overlay.py``), headless.

``QT_QPA_PLATFORM=offscreen``, the pattern of test_sco_overlay.py. The game's
window, the screen capture and the tag scanner are stand-ins: what is tested
is the loop round them (one look at a time on the pool thread, the marks
reaching the mark window on the GUI thread, a stop dropping a late look, a
look that raises stopping the loop quietly), the lists being taken from the
settings, the names read being kept there from session to session, the
locations to highlight, the switches, the status it reports, the mark
window's drawing, and the overlay's switches. Settings are redirected: no
test reads or writes this PC's own settings or the real base.ini.
"""
from __future__ import annotations

import logging
import threading
import time
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QImage

from src.gui import player_id_overlay as module
from src.gui.player_id_overlay import PlayerIdOverlay, PlayerMarkWindow, frame_of
from src.utils.json_settings import JsonSettings
from src.utils.player_id import NOT_A_NAME_COLOR, UNLISTED_DEFAULT, UNTRUSTED_COLOR, Mark
from src.utils.sco_tag_scan import TagReading
from src.utils.settings import AppSettings
from tests.event_loop import pump_until

AREA = (0, 0, 1280, 720)
BOX = (400, 300, 120, 12)
OTHER_BOX = (700, 200, 90, 12)
THIRD_BOX = (200, 500, 110, 12)


def names_kept() -> list:
    """The names the settings hold as read in play, newest first."""
    return [name for name, _session in AppSettings.get_player_history().get("names", [])]


class FakeScanner:
    """Stands in for TagScanner: gives the readings it is told to."""

    def __init__(self, readings=()):
        self.readings = list(readings)
        self.last_total_s = 0.01
        self.last_lines = 4
        self.last_no_distance = 3
        self.need_distance = None        # set by the overlay when it starts
        self.threads = []
        self.resets = 0
        self.hold = threading.Event()
        self.hold.set()
        self.error = None

    def scan(self, frame, now):
        self.threads.append(threading.current_thread())
        self.hold.wait(10)
        if self.error is not None:
            raise self.error
        return list(self.readings)

    def reset(self):
        self.resets += 1


class SavedLists(dict):
    """The lists a test's settings hold (a test may change them), and one
    entry in ``reads`` for each time they were asked for."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.reads = []


@pytest.fixture
def saved_lists(tmp_path, monkeypatch):
    """Redirected settings: the lists a test sets and an English base.ini in
    tmp_path. Everything else the overlay reads or saves (the locations to
    highlight, the names it has read) goes to a settings file in tmp_path,
    never to this PC's own settings."""
    saved = SavedLists(orgs=[["WOLVES", "green"]], players=[["FRIEND_ONE", "WOLVES", ""]],
                       unlisted="grey")

    def get_player_lists():
        saved.reads.append(True)
        return dict(saved)

    base_ini = tmp_path / "base.ini"
    base_ini.write_text("ui_controls=Controls\n", encoding="utf-8")
    monkeypatch.setattr(AppSettings, "_backend", JsonSettings(tmp_path / "config.json"))
    monkeypatch.setattr(AppSettings, "get_player_lists", staticmethod(get_player_lists))
    monkeypatch.setattr(AppSettings, "get_base_ini_path",
                        staticmethod(lambda language=None: base_ini))
    return saved


@pytest.fixture
def overlay(qapp, saved_lists, monkeypatch):
    """A PlayerIdOverlay over a stand-in game window, with a fake scanner."""
    front = {"area": AREA}
    monkeypatch.setattr(module.game_window, "foreground_game_area",
                        lambda any_window=False, own_windows=(): front["area"])
    image = QImage(AREA[2], AREA[3], QImage.Format.Format_RGB32)
    image.fill(QColor(0, 0, 0))
    monkeypatch.setattr(PlayerIdOverlay, "_capture",
                        lambda self, area: (image, QRect(*AREA), 1.0))
    made = PlayerIdOverlay()
    made._scanner = FakeScanner([TagReading("FRIEND_ONE", BOX, 0.95, 0, True, 1)])
    made.front = front
    made.states = []
    made.status.connect(lambda state, figures: made.states.append((state, dict(figures))))
    yield made
    made._scanner.hold.set()
    made.stop()
    assert made.wait_for_reader(5000)


def test_a_capture_becomes_the_readers_three_channels(qapp):
    image = QImage(3, 2, QImage.Format.Format_RGB32)
    image.fill(QColor(10, 20, 30))
    image.setPixelColor(2, 1, QColor(200, 150, 100))
    frame = frame_of(image)
    assert (frame.width, frame.height) == (3, 2)
    assert frame.red == bytes([10, 10, 10, 10, 10, 200])
    assert frame.green == bytes([20, 20, 20, 20, 20, 150])
    assert frame.blue == bytes([30, 30, 30, 30, 30, 100])


def test_a_look_runs_on_the_pool_thread_and_its_marks_reach_the_window(overlay):
    overlay.start()
    assert pump_until(lambda: overlay.window.marks())
    marks = overlay.window.marks()
    assert [(m.name, m.color, m.label, m.listed, m.box) for m in marks] == [
        ("FRIEND_ONE", "#40C057", "WOLVES", True, BOX)]
    assert overlay.window.isVisible() and overlay.window.geometry() == QRect(*AREA)
    assert overlay._scanner.threads and all(
        thread is not threading.main_thread() for thread in overlay._scanner.threads)


def test_no_look_runs_before_the_games_words_are_read(overlay, monkeypatch):
    # With no wait between votes, two looks would make any other word a name.
    monkeypatch.setattr("src.utils.player_id.VOTE_GAP_S", 0.0)
    overlay._scanner.readings = [TagReading("CONTROLS", BOX, 0.95, 0, True, 1)]
    overlay.start()
    assert not overlay._words_ready
    overlay._tick()
    assert overlay._scanner.threads == []
    assert pump_until(lambda: len(overlay._scanner.threads) >= 3)
    # CONTROLS is one of the game's words in the redirected base.ini, so two
    # looks apart never make it a name.
    assert overlay.tracker.words and overlay.window.marks() == []


def test_one_look_at_a_time(overlay):
    overlay._scanner.hold.clear()                  # the first look stays with the scanner
    overlay.start()
    assert pump_until(lambda: len(overlay._scanner.threads) == 1)
    for _tick in range(5):
        overlay._tick()
    assert len(overlay._scanner.threads) == 1
    overlay._scanner.hold.set()
    assert pump_until(lambda: len(overlay._scanner.threads) >= 2)


def test_a_look_that_ends_after_a_stop_is_dropped(overlay):
    overlay._scanner.hold.clear()
    overlay.start()
    assert pump_until(lambda: len(overlay._scanner.threads) == 1)
    overlay.stop()
    overlay._scanner.hold.set()
    assert overlay.wait_for_reader(5000)
    pump_until(lambda: False, 0.2)
    assert overlay.window.marks() == [] and not overlay.window.isVisible()
    assert not overlay.is_running()


def test_the_game_going_to_the_back_hides_the_marks(overlay):
    overlay.start()
    assert pump_until(lambda: overlay.window.marks())
    overlay.front["area"] = None
    assert pump_until(lambda: not overlay.window.isVisible())
    assert overlay.window.marks() == []
    looks = len(overlay._scanner.threads)
    pump_until(lambda: False, 0.4)
    assert len(overlay._scanner.threads) <= looks + 1      # at most the look already running
    overlay.front["area"] = AREA
    assert pump_until(lambda: overlay.window.marks())


def test_a_look_that_raises_stops_the_loop_quietly(overlay, caplog):
    failed = []
    overlay.failed.connect(lambda: failed.append(True))
    overlay._scanner.error = RuntimeError("boom")
    with caplog.at_level(logging.DEBUG):
        overlay.start()
        assert pump_until(lambda: failed)
    assert not overlay.is_running() and not overlay.window.isVisible()
    worst = max(record.levelno for record in caplog.records)
    assert worst == logging.WARNING                # an ERROR would open the error box
    assert overlay.last_status() == (module.STATUS_FAILED, {})


def test_a_new_window_size_forgets_the_remembered_places(overlay, monkeypatch):
    overlay.start()
    assert pump_until(lambda: overlay.window.marks())
    resets = overlay._scanner.resets
    bigger = QImage(1920, 1080, QImage.Format.Format_RGB32)
    bigger.fill(QColor(0, 0, 0))
    monkeypatch.setattr(PlayerIdOverlay, "_capture",
                        lambda self, area: (bigger, QRect(0, 0, 1920, 1080), 1.0))
    assert pump_until(lambda: overlay._scanner.resets > resets)
    assert pump_until(lambda: overlay.window.geometry() == QRect(0, 0, 1920, 1080))


class TestTheListsComeFromTheSettings:
    def test_a_start_takes_the_saved_lists(self, overlay, saved_lists):
        assert saved_lists.reads == []             # nothing is read before it runs
        overlay.start()
        assert saved_lists.reads and overlay.tracker.lists.find("FRIEND_ONE").label == "WOLVES"

    def test_nothing_is_read_while_it_is_not_running(self, overlay, saved_lists):
        overlay.reload_lists()
        assert saved_lists.reads == [] and not overlay.tracker.lists.players

    def test_changed_lists_show_once_it_is_told(self, overlay, saved_lists):
        overlay.start()
        assert pump_until(lambda: overlay.window.marks())
        saved_lists["orgs"] = []
        saved_lists["players"] = [["FRIEND_ONE", "", "#112233"]]
        overlay.reload_lists()
        assert pump_until(lambda: [m.color for m in overlay.window.marks()] == ["#112233"])

    def test_an_entry_that_cannot_be_used_is_logged_and_the_rest_is_kept(self, overlay,
                                                                         saved_lists, caplog):
        saved_lists["players"] = [["FRIEND_ONE", "WOLVES", ""], ["TWO WORDS", "", "red"]]
        with caplog.at_level(logging.WARNING):
            overlay.start()
        assert sorted(overlay.tracker.lists.players) == ["FRIEND_ONE"]
        assert [r.getMessage() for r in caplog.records if "Player ID lists" in r.getMessage()] == [
            "Player ID lists: player 'TWO WORDS': cannot be a name tag"]

    def test_with_no_lists_a_name_is_marked_grey_once_two_looks_agree(self, overlay,
                                                                      saved_lists):
        saved_lists.clear()
        overlay.start()
        assert pump_until(lambda: overlay.window.marks(), 15)
        mark = overlay.window.marks()[0]
        assert (mark.name, mark.color, mark.listed, mark.label) == (
            "FRIEND_ONE", UNLISTED_DEFAULT, False, "")
        assert names_kept() == ["FRIEND_ONE"]


class TestTheNamesReadAreKept:
    """The names read in play go into the settings, so the lists editor has
    the last session's names and everyone read before. They are kept on this
    PC only (``test_overlay_tab.py`` has the backup side)."""

    @pytest.fixture
    def writes(self, saved_lists, monkeypatch):
        """Each time the record of past players was saved."""
        saved, real = [], AppSettings.set_player_history

        def set_player_history(data):
            saved.append(data)
            real(data)

        monkeypatch.setattr(AppSettings, "set_player_history", staticmethod(set_player_history))
        return saved

    def test_a_listed_name_and_a_trusted_one_are_kept_once(self, overlay, writes, monkeypatch):
        monkeypatch.setattr("src.utils.player_id.VOTE_GAP_S", 0.0)
        overlay._scanner.readings = [TagReading("FRIEND_ONE", BOX, 0.95, 0, True, 1),
                                     TagReading("STRANGER", OTHER_BOX, 0.95, 0, True, 2),
                                     TagReading("UNKNOWN", THIRD_BOX, 0.95, 0, True, 3)]
        overlay.start()
        assert pump_until(lambda: len(names_kept()) == 2)
        assert sorted(names_kept()) == ["FRIEND_ONE", "STRANGER"]   # never a tag that is no name
        history = AppSettings.get_player_history()
        assert history["session"] == overlay._session
        assert {session for _name, session in history["names"]} == {overlay._session}
        # Looks go on, and a name already kept this session is not saved again.
        looks = len(overlay._scanner.threads)
        assert pump_until(lambda: len(overlay._scanner.threads) >= looks + 4)
        assert len(writes) == 2 and names_kept().count("STRANGER") == 1

    def test_a_name_read_once_is_not_kept(self, overlay, writes, saved_lists, monkeypatch):
        monkeypatch.setattr("src.utils.player_id.VOTE_GAP_S", 1000.0)   # never two looks
        saved_lists.clear()
        overlay._scanner.readings = [TagReading("STRANGER", BOX, 0.95, 0, True, 1)]
        overlay.start()
        assert pump_until(lambda: len(overlay._scanner.threads) >= 4)
        assert writes == [] and names_kept() == []

    def test_a_session_is_named_when_it_first_starts_and_keeps_its_name(self, overlay, writes,
                                                                        monkeypatch):
        # The overlay's own clock only: logging formats its times with the
        # real one.
        times = iter(["2026-11-15 14:02:10", "2026-11-15 15:00:00"])
        monkeypatch.setattr(module, "time", SimpleNamespace(
            strftime=lambda form: next(times), monotonic=time.monotonic))
        assert overlay._session == ""
        overlay.start()
        overlay.stop()
        overlay.start()                                        # still the same session
        assert overlay._session == "2026-11-15 14:02:10"
        assert pump_until(lambda: names_kept() == ["FRIEND_ONE"])
        assert AppSettings.get_player_history() == {
            "session": "2026-11-15 14:02:10", "names": [["FRIEND_ONE", "2026-11-15 14:02:10"]]}

    def test_names_of_earlier_sessions_stay_and_a_name_read_again_moves_up(self, overlay, writes):
        AppSettings.set_player_history({
            "session": "2026-11-01 09:00:00",
            "names": [["OLD_HAND", "2026-11-01 09:00:00"], ["FRIEND_ONE", "2026-10-20 20:00:00"]]})
        writes.clear()
        overlay.start()
        assert pump_until(lambda: writes)
        history = AppSettings.get_player_history()
        assert history["session"] == overlay._session
        assert history["names"] == [["FRIEND_ONE", overlay._session],
                                    ["OLD_HAND", "2026-11-01 09:00:00"]]

    def test_a_record_cleared_in_the_editor_stays_cleared(self, overlay, writes, monkeypatch):
        monkeypatch.setattr("src.utils.player_id.VOTE_GAP_S", 0.0)
        overlay.start()
        assert pump_until(lambda: names_kept() == ["FRIEND_ONE"])
        AppSettings.set_player_history({})                     # what the editor's Clear leads to
        overlay.reload_lists()                                 # and the tab's options_changed
        overlay._scanner.readings = [TagReading("FRIEND_ONE", BOX, 0.95, 0, True, 1),
                                     TagReading("STRANGER", OTHER_BOX, 0.95, 0, True, 2)]
        assert pump_until(lambda: names_kept() == ["STRANGER"])   # the old names do not come back


class TestHighlightedLocations:
    """A marker whose text is on the player's list of locations gets a mark
    of its own kind in its colour, whether or not names are marked."""

    def test_a_listed_location_is_marked_at_once(self, overlay):
        AppSettings.set_location_list([["new babbage", "#010203"]])
        overlay._scanner.readings = [TagReading("NEW BABBAGE", OTHER_BOX, 0.95, 0, True, 2),
                                     TagReading("FRIEND_ONE", BOX, 0.95, 0, True, 1)]
        overlay.set_marking(True, True, False, True)
        overlay.start()
        assert pump_until(lambda: len(overlay.window.marks()) == 2)
        assert sorted((m.name, m.color, m.place, m.box) for m in overlay.window.marks()) == [
            ("FRIEND_ONE", "#40C057", False, BOX), ("NEW BABBAGE", "#010203", True, OTHER_BOX)]
        assert names_kept() == ["FRIEND_ONE"]                  # a location is nobody's name

    def test_it_needs_its_switch(self, overlay):
        AppSettings.set_location_list([["NEW BABBAGE", "red"]])
        overlay._scanner.readings = [TagReading("NEW BABBAGE", OTHER_BOX, 0.95, 0, True, 2)]
        overlay.start()                                        # names only, the default
        assert pump_until(lambda: len(overlay._scanner.threads) >= 4)
        assert overlay.window.marks() == []

    def test_switching_it_off_takes_its_mark_away_at_the_next_look(self, overlay):
        """A mark stays on its tag from look to look, so a switch that
        changes has to drop the marks made under the old one."""
        AppSettings.set_location_list([["NEW BABBAGE", "red"]])
        overlay._scanner.readings = [TagReading("NEW BABBAGE", OTHER_BOX, 0.95, 0, True, 2)]
        overlay.set_marking(True, True, False, True)
        overlay.start()
        assert pump_until(lambda: len(overlay.window.marks()) == 1)
        overlay.set_marking(True, True, False, False)
        assert pump_until(lambda: overlay.window.marks() == [])
        # And a location taken off the list loses its mark the same way.
        overlay.set_marking(True, True, False, True)
        assert pump_until(lambda: len(overlay.window.marks()) == 1)
        AppSettings.set_location_list([])
        overlay.reload_lists()
        assert pump_until(lambda: overlay.window.marks() == [])

    def test_with_names_off_only_locations_are_marked(self, overlay):
        AppSettings.set_location_list([["NEW BABBAGE", "red"]])
        overlay._scanner.readings = [TagReading("NEW BABBAGE", OTHER_BOX, 0.95, 0, True, 2),
                                     TagReading("FRIEND_ONE", BOX, 0.95, 0, True, 1)]
        overlay.set_marking(False, True, True, True)
        overlay.start()
        assert pump_until(lambda: overlay.window.marks())
        assert pump_until(lambda: len(overlay._scanner.threads) >= 4)
        assert [(m.name, m.place) for m in overlay.window.marks()] == [("NEW BABBAGE", True)]
        assert names_kept() == []                              # and no name is kept

    def test_a_changed_list_shows_once_it_is_told(self, overlay, caplog):
        overlay._scanner.readings = [TagReading("PORT TRESSLER", OTHER_BOX, 0.95, 0, True, 2)]
        overlay.set_marking(False, True, False, True)
        overlay.start()
        assert pump_until(lambda: len(overlay._scanner.threads) >= 3)
        assert overlay.window.marks() == []
        AppSettings.set_location_list([["PORT TRESSLER", "blue"], ["no", "red"]])
        with caplog.at_level(logging.WARNING):
            overlay.reload_lists()
        assert pump_until(lambda: [m.color for m in overlay.window.marks()] == ["#4DABF7"])
        assert [r.getMessage() for r in caplog.records if "Player ID lists" in r.getMessage()] == [
            "Player ID lists: location 'NO': cannot be read off a marker"]


class TestTheDistanceSwitch:
    """The switch under both halves: the scanner reads only text with a
    distance line under it (``test_sco_tag_scan.py`` has what that means)."""

    def test_it_is_off_until_it_is_set_and_reaches_the_scanner_at_the_start(self, overlay):
        assert overlay._scanner.need_distance is None           # the stand-in's own start
        overlay.start()
        assert overlay._scanner.need_distance is False

    def test_set_before_the_start_it_is_handed_over_at_the_start(self, overlay):
        overlay.set_distance_filter(True)
        overlay.start()
        assert overlay._scanner.need_distance is True

    def test_a_running_scanner_takes_a_change_at_once(self, overlay):
        overlay.start()
        overlay.set_distance_filter(True)
        assert overlay._scanner.need_distance is True
        overlay.set_distance_filter(False)
        assert overlay._scanner.need_distance is False

    def test_with_no_scanner_yet_it_is_kept_for_the_first_start(self, qapp, saved_lists,
                                                                monkeypatch):
        monkeypatch.setattr(module.game_window, "foreground_game_area",
                            lambda any_window=False, own_windows=(): None)
        made = PlayerIdOverlay()
        made.set_distance_filter(True)                          # no scanner before a start
        assert made._scanner is None
        made.start()
        try:
            assert made._scanner.need_distance is True
        finally:
            made.stop()
            assert made.wait_for_reader(5000)

    def test_the_start_says_in_the_log_which_way_it_is_set(self, overlay, caplog):
        overlay.set_distance_filter(True)
        with caplog.at_level(logging.INFO):
            overlay.start()
        started = [r.getMessage() for r in caplog.records if "Player ID: started" in r.getMessage()]
        assert len(started) == 1 and "only text with a distance line under it" in started[0]


class TestTheSwitches:
    def test_they_reach_the_tracker(self, overlay):
        tracker = overlay.tracker
        assert (tracker.mark_names, tracker.mark_unlisted, tracker.mark_all,
                tracker.mark_places) == (True, True, False, False)
        overlay.set_marking(False, False, True, True)
        assert (tracker.mark_names, tracker.mark_unlisted, tracker.mark_all,
                tracker.mark_places) == (False, False, True, True)

    def test_names_on_no_list_can_be_left_out(self, overlay, saved_lists, monkeypatch):
        monkeypatch.setattr("src.utils.player_id.VOTE_GAP_S", 0.0)
        overlay._scanner.readings = [TagReading("FRIEND_ONE", BOX, 0.95, 0, True, 1),
                                     TagReading("STRANGER", OTHER_BOX, 0.95, 0, True, 2)]
        overlay.set_marking(True, False, False, False)
        overlay.start()
        # The name is still read and kept for the editor, only not marked.
        assert pump_until(lambda: "STRANGER" in names_kept())
        assert pump_until(lambda: len(overlay._scanner.threads) >= 4)
        assert [m.name for m in overlay.window.marks()] == ["FRIEND_ONE"]

    def test_switching_names_on_no_list_off_takes_their_marks_away(self, overlay, monkeypatch):
        monkeypatch.setattr("src.utils.player_id.VOTE_GAP_S", 0.0)
        overlay._scanner.readings = [TagReading("FRIEND_ONE", BOX, 0.95, 0, True, 1),
                                     TagReading("STRANGER", OTHER_BOX, 0.95, 0, True, 2)]
        overlay.start()
        assert pump_until(lambda: len(overlay.window.marks()) == 2)
        overlay.set_marking(True, False, False, False)
        assert pump_until(lambda: [m.name for m in overlay.window.marks()] == ["FRIEND_ONE"])
        # Names off altogether: the listed one goes too.
        overlay.set_marking(False, False, False, False)
        assert pump_until(lambda: overlay.window.marks() == [])

    def test_the_test_switch_marks_every_reading_at_once_with_its_text(self, overlay,
                                                                       saved_lists, monkeypatch):
        # Votes that never come to two: nothing here is ever trusted.
        monkeypatch.setattr("src.utils.player_id.VOTE_GAP_S", 1000.0)
        saved_lists.clear()
        overlay._scanner.readings = [TagReading("UNKNOWN", BOX, 0.95, 0, True, 1),
                                     TagReading("STRANGER", OTHER_BOX, 0.95, 0, True, 2)]
        overlay.set_marking(True, True, True, False)
        overlay.start()
        assert pump_until(lambda: len(overlay.window.marks()) == 2)
        assert sorted((m.name, m.label, m.color, m.trusted) for m in overlay.window.marks()) == [
            ("STRANGER", "STRANGER", UNTRUSTED_COLOR, False),
            ("UNKNOWN", "UNKNOWN", NOT_A_NAME_COLOR, False)]
        # Without the switch neither is marked: the next looks take them away.
        overlay.set_marking(True, True, False, False)
        assert pump_until(lambda: overlay.window.marks() == [])


class TestTheStatus:
    def test_it_says_how_the_looks_are_going(self, overlay):
        assert overlay.last_status() == (module.STATUS_OFF, {})
        overlay.start()
        assert overlay.states == [(module.STATUS_STARTING, {})]
        assert pump_until(lambda: overlay.last_status()[0] == module.STATUS_LOOKING)
        state, figures = overlay.last_status()
        assert figures == {"width": 1280, "height": 720, "seconds": 0.01, "lines": 4,
                           "skipped": 3, "read": 1, "marked": 1}
        overlay.front["area"] = None
        assert pump_until(lambda: overlay.last_status() == (module.STATUS_NO_GAME, {}))
        waiting = len(overlay.states)
        pump_until(lambda: False, 0.4)
        assert len(overlay.states) == waiting      # said once while it waits
        overlay.stop()
        assert overlay.states[-1] == (module.STATUS_OFF, {})

    def test_it_is_not_sent_for_every_look(self, overlay, monkeypatch):
        monkeypatch.setattr(module, "STATUS_EVERY_S", 1000.0)
        overlay.start()
        assert pump_until(lambda: len(overlay._scanner.threads) >= 5)
        assert [state for state, _figures in overlay.states] == [
            module.STATUS_STARTING, module.STATUS_LOOKING]


class TestTheMarkWindow:
    @staticmethod
    def drawn(marks) -> QImage:
        window = PlayerMarkWindow()
        window.hidden_from_capture = True
        window.resize(640, 360)
        window.set_marks(marks, 1.0)
        image = QImage(640, 360, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        window.render(image)
        return image

    @staticmethod
    def corner(height: float = 10) -> tuple:
        """The top-left corner of a mark round a name at (200, 150): a
        little outside the name's box."""
        pad = max(4.0, module.MARK_GAP * height)
        return int(200 - pad), int(150 - pad)

    def test_it_draws_corner_brackets_in_the_names_color(self, qapp):
        image = self.drawn([Mark("FRIEND_ONE", (200, 150, 100, 10), "#FF00FF", "", True)])
        corner = self.corner()
        magenta = QColor("#FF00FF").rgb()
        assert image.pixel(*corner) == magenta
        assert image.pixel(corner[0] + 3, corner[1]) == magenta        # along the top
        assert image.pixel(corner[0], corner[1] + 3) == magenta        # down the side
        # Nothing is drawn over the name itself.
        assert image.pixelColor(250, 155).alpha() == 0

    def test_a_listed_name_gets_the_thickest_brackets(self, qapp):
        def thickness(mark) -> int:
            image = self.drawn([mark])
            x, y = self.corner()
            return sum(image.pixelColor(x + 6, row).alpha() > 0 for row in range(y - 6, y + 7))

        box = (200, 150, 100, 10)
        listed = thickness(Mark("A_NAME", box, "#FF00FF", "", True))
        unlisted = thickness(Mark("A_NAME", box, "#FF00FF", "", False))
        untrusted = thickness(Mark("A_NAME", box, "#FF00FF", "", False, trusted=False))
        assert (listed, unlisted, untrusted) == (3, 2, 1)

    def test_brackets_are_thicker_round_a_taller_name(self, qapp):
        image = self.drawn([Mark("A_NAME", (200, 150, 170, 17), "#FF00FF", "", False)])
        x, y = self.corner(17)
        assert sum(image.pixelColor(x + 8, row).alpha() > 0 for row in range(y - 6, y + 7)) == 2
        image = self.drawn([Mark("A_NAME", (200, 150, 170, 30), "#FF00FF", "", True)])
        x, y = self.corner(30)
        assert sum(image.pixelColor(x + 8, row).alpha() > 0 for row in range(y - 8, y + 9)) == 6

    def test_a_location_gets_a_whole_frame(self, qapp):
        """A name's mark is four corners. A location's is a frame all the
        way round, so the two can be told apart at a glance."""
        def inked_on_top_edge(mark) -> bool:
            image = self.drawn([mark])
            x, y = self.corner()
            return image.pixelColor(250, y).alpha() > 0    # half way along the top

        box = (200, 150, 100, 10)
        assert inked_on_top_edge(Mark("NEW BABBAGE", box, "#FF00FF", "", True, place=True))
        assert not inked_on_top_edge(Mark("A_NAME", box, "#FF00FF", "", True))
        image = self.drawn([Mark("NEW BABBAGE", box, "#FF00FF", "", True, place=True)])
        assert image.pixel(*self.corner()) == QColor("#FF00FF").rgb()
        assert image.pixelColor(250, 155).alpha() == 0     # nothing over the text itself

    def test_a_label_is_drawn_above_the_mark(self, qapp):
        def inked_above(label: str) -> int:
            image = self.drawn([Mark("A_NAME", (200, 150, 100, 10), "#FF00FF", label, True)])
            x, y = self.corner()
            return sum(image.pixelColor(column, row).alpha() > 0
                       for row in range(y - 24, y - 2) for column in range(x, x + 120))

        assert inked_above("") == 0
        assert inked_above("WOLVES") > 20

    def test_it_lets_clicks_through_and_takes_no_focus(self, qapp):
        flags = PlayerMarkWindow().windowFlags()
        assert flags & Qt.WindowType.WindowTransparentForInput
        assert flags & Qt.WindowType.WindowDoesNotAcceptFocus
        assert flags & Qt.WindowType.WindowStaysOnTopHint


class TestTheOverlaysSwitch:
    """ScoOverlay runs the player ID loop only while it runs with the switch
    on, and hands it the two switches under it and the saved lists."""

    @pytest.fixture
    def sco(self, qapp, saved_lists, monkeypatch, tmp_path):
        from src.gui import sco_overlay
        from src.gui.sco_overlay import DEFAULT_OVERLAY_COLORS, OverlayColors, ScoOverlay

        monkeypatch.setattr(OverlayColors, "from_theme",
                            classmethod(lambda cls: DEFAULT_OVERLAY_COLORS))
        monkeypatch.setattr(sco_overlay.AppSettings, "get_sco_samples_dir",
                            staticmethod(lambda: tmp_path / "samples"))
        monkeypatch.setattr(module.game_window, "foreground_game_area",
                            lambda any_window=False, own_windows=(): None)
        made = ScoOverlay()
        made.set_reader(None)                      # no screen capture in a test
        yield made
        made.stop()
        assert made.wait_for_reader(5000)

    @staticmethod
    def options(player_id: bool, **others) -> dict:
        options = {name: False for name in AppSettings.SCO_OPTION_SETTING}
        options[AppSettings.SCO_PLAYER_ID] = player_id
        options.update(others)
        return options

    def test_it_is_off_until_switched_on(self, sco):
        sco.start()
        assert not sco.player_id.is_running()
        sco.set_options(self.options(True))
        assert sco.player_id.is_running()
        sco.set_options(self.options(False))
        assert not sco.player_id.is_running()

    def test_a_switch_set_before_the_start_takes_effect_at_the_start(self, sco):
        sco.set_options(self.options(True))
        assert not sco.player_id.is_running()
        sco.start()
        assert sco.player_id.is_running()

    def test_stopping_the_overlay_stops_it(self, sco):
        sco.start()
        sco.set_options(self.options(True))
        sco.stop()
        assert not sco.player_id.is_running()
        assert not sco.player_id.window.isVisible()

    def test_the_switches_under_it_reach_the_tracker(self, sco):
        tracker = sco.player_id.tracker
        sco.set_options(self.options(True, player_id_unlisted=True, player_id_all=True))
        assert (tracker.mark_unlisted, tracker.mark_all) == (True, True)
        assert (tracker.mark_names, tracker.mark_places) == (True, False)
        sco.set_options(self.options(True, player_id_unlisted=False, player_id_all=False))
        assert (tracker.mark_unlisted, tracker.mark_all) == (False, False)
        # A switch that is left out takes its default.
        sco.set_options({})
        assert (tracker.mark_unlisted, tracker.mark_all) == (True, False)
        assert (tracker.mark_names, tracker.mark_places) == (False, False)

    def test_the_locations_switch_runs_the_looks_on_its_own(self, sco):
        """Names and locations are read by the same looks, so either switch
        runs them, and each tells the tracker what to mark."""
        tracker = sco.player_id.tracker
        sco.start()
        sco.set_options(self.options(False, highlight_locations=True))
        assert sco.player_id.is_running()
        assert (tracker.mark_names, tracker.mark_places) == (False, True)
        sco.set_options(self.options(True, highlight_locations=True))
        assert sco.player_id.is_running()
        assert (tracker.mark_names, tracker.mark_places) == (True, True)
        sco.set_options(self.options(False))
        assert not sco.player_id.is_running()

    def test_the_distance_switch_reaches_the_scanner(self, sco):
        sco.start()
        sco.set_options(self.options(True, player_id_distance=True))
        assert sco.player_id._scanner.need_distance is True
        sco.set_options(self.options(True, player_id_distance=False))
        assert sco.player_id._scanner.need_distance is False
        # Left out, it takes its default, which is on.
        sco.set_options({AppSettings.SCO_PLAYER_ID: True})
        assert sco.player_id._scanner.need_distance is True

    def test_new_options_hand_a_running_one_the_saved_locations(self, sco):
        sco.start()
        sco.set_options(self.options(False, highlight_locations=True))
        assert sco.player_id.tracker.places.find("GRIM HEX") is None
        AppSettings.set_location_list([["GRIM HEX", "red"]])
        sco.set_options(self.options(False, highlight_locations=True))
        assert sco.player_id.tracker.places.find("GRIM HEX") == ("GRIM HEX", "#FA5252")

    def test_new_options_hand_a_running_one_the_saved_lists(self, sco, saved_lists):
        sco.start()
        sco.set_options(self.options(True))
        assert sco.player_id.tracker.lists.find("NEW_ONE") is None
        saved_lists["players"] = [["NEW_ONE", "", "red"]]
        sco.set_options(self.options(True))        # what the Overlay tab's editor leads to
        assert sco.player_id.tracker.lists.find("NEW_ONE").color == "#FA5252"

    def test_the_defaults(self):
        defaults = {name: AppSettings.SCO_OPTION_SETTING[name][1]
                    for name in (AppSettings.SCO_PLAYER_ID, AppSettings.SCO_PLAYER_ID_UNLISTED,
                                 AppSettings.SCO_PLAYER_ID_ALL,
                                 AppSettings.SCO_HIGHLIGHT_LOCATIONS,
                                 AppSettings.SCO_PLAYER_ID_DISTANCE)}
        assert defaults == {"player_id": False, "player_id_unlisted": True,
                            "player_id_all": False, "highlight_locations": False,
                            "player_id_distance": True}
