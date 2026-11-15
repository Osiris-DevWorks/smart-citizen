"""The player ID test's text logic (``src/utils/player_id.py``), Qt-free.

Which readings may be a name, the game's own words, the two-look vote, the
lists as the settings keep them, the marks a look gives, with and without
the test switch, the record of past players, and the locations to highlight.
Readings are made up here: reading tags off a picture is
``test_sco_tag_scan.py``'s.
"""
import ast
from pathlib import Path

import pytest

from src.utils.player_id import (
    HOLD_S, NOT_A_NAME_COLOR, UNLISTED_DEFAULT, UNTRUSTED_COLOR, NameVotes, PastPlayers,
    PlaceList, PlayerIdTracker, PlayerLists, clean_place, could_be_handle, could_be_name, folded,
    game_words, near_unknown, parse_color,
)
from src.utils.sco_tag_scan import TagReading

BOX = (100, 200, 80, 17)
OTHER_BOX = (600, 500, 90, 17)


def reading(text, score=0.95, crowded=0, fresh=True, box=BOX, place=1):
    return TagReading(text, box, score, crowded, fresh, place)


def lists(orgs=(), players=(), unlisted="grey"):
    return PlayerLists.from_data({"orgs": [list(o) for o in orgs],
                                  "players": [list(p) for p in players],
                                  "unlisted": unlisted})


class TestWhatMayBeAName:
    @pytest.mark.parametrize("text", ["ABC", "PILOT_ONE", "X-RAY7", "A1B2C3"])
    def test_a_handle_shaped_word_may(self, text):
        assert could_be_handle(text)
        assert could_be_name(text, 0.9, 0)

    @pytest.mark.parametrize("text", ["AB", "TWO WORDS", "lower", "DOT.TED", "UNKNOWN",
                                      "LV-5121-VA", ""])
    def test_other_shapes_may_not(self, text):
        assert not could_be_handle(text)

    def test_a_poor_match_or_something_beside_it_may_not(self):
        assert could_be_name("PILOT_ONE", 0.80, 0)
        assert not could_be_name("PILOT_ONE", 0.79, 0)
        assert not could_be_name("PILOT_ONE", 0.95, 1)

    def test_digits_alone_may_not(self):
        assert not could_be_name("210", 0.95, 0)
        assert could_be_name("2TEN", 0.95, 0)

    @pytest.mark.parametrize("text", ["UNKNDWN", "UNKNOWI", "NKNOWN", "UNK", "UNKNO", "KNOWN",
                                      "OWN", "UNKN0WN"])
    def test_anything_like_unknown_may_not(self, text):
        assert near_unknown(text)
        assert not could_be_name(text, 0.95, 0)

    @pytest.mark.parametrize("text", ["UNKEMPT", "KNIGHT", "NOWHERE1", "PILOT_ONE"])
    def test_other_words_are_not_like_unknown(self, text):
        assert not near_unknown(text)


class TestGameWords:
    TEXT = ("ui_controls=Controls\n"
            "ui_keys=Key Bindings\n"
            "ui_status=System <EM4>Online</EM4> ~mission(Name)\n"
            "item_Name_x=Aphorite [Craft]\n"
            "hud_vsi,P=VSI\n"
            "not a line\n")

    def test_every_word_of_the_text_is_one(self):
        words = game_words(self.TEXT)
        for word in ("CONTROLS", "KEY", "BINDINGS", "SYSTEM", "ONLINE", "APHORITE", "VSI"):
            assert folded(word) in words, word

    def test_a_short_label_also_counts_run_together(self):
        assert folded("KEYBINDINGS") in game_words(self.TEXT)

    def test_mark_up_is_not_a_word(self):
        words = game_words(self.TEXT)
        assert folded("EM4") not in words and folded("MISSION") not in words
        assert folded("CRAFT") not in words

    def test_a_word_read_with_a_look_alike_is_still_the_word(self):
        words = game_words(self.TEXT)
        assert not could_be_name("ONL1NE", 0.95, 0, words)
        assert not could_be_name("VS1", 0.95, 0, words)
        assert not could_be_name("CONTR0LS", 0.95, 0, words)
        assert could_be_name("PILOT_ONE", 0.95, 0, words)


class TestNameVotes:
    def test_one_look_is_not_enough(self):
        votes = NameVotes()
        votes.add_look(["PILOT_ONE"], 0.0)
        assert votes.spelling("PILOT_ONE") is None

    def test_two_looks_apart_are(self):
        votes = NameVotes()
        votes.add_look(["PILOT_ONE"], 0.0)
        votes.add_look(["PILOT_ONE"], 1.0)
        assert votes.spelling("PILOT_ONE") == "PILOT_ONE"

    def test_two_looks_at_the_same_moment_count_once(self):
        votes = NameVotes()
        votes.add_look(["PILOT_ONE"], 0.0)
        votes.add_look(["PILOT_ONE"], 0.3)
        assert votes.spelling("PILOT_ONE") is None
        votes.add_look(["PILOT_ONE"], 1.0)
        assert votes.spelling("PILOT_ONE") == "PILOT_ONE"

    def test_look_alike_spellings_are_one_name_and_the_most_read_wins(self):
        votes = NameVotes()
        for second, text in enumerate(["GOOD_DOG", "GOOD_DOG", "GOOD_D0G", "GOOD_DOG"]):
            votes.add_look([text], float(second))
        assert votes.spelling("GOOD_D0G") == "GOOD_DOG"
        assert votes.spelling("G00D_DOG") == "GOOD_DOG"

    def test_a_tie_between_spellings_trusts_neither(self):
        votes = NameVotes()
        for second, text in enumerate(["GOOD_DOG", "GOOD_D0G", "GOOD_DOG", "GOOD_D0G"]):
            votes.add_look([text], float(second))
        assert votes.spelling("GOOD_DOG") is None

    def test_a_piece_of_a_longer_reading_is_never_trusted(self):
        votes = NameVotes()
        for second in range(3):
            votes.add_look(["PILOT_ONE", "PILOT_O"], float(second))
        assert votes.spelling("PILOT_ONE") == "PILOT_ONE"
        assert votes.spelling("PILOT_O") is None


class TestPlayerLists:
    def test_players_take_their_org_or_their_own_color(self):
        made = lists(orgs=[("Wolves", "green"), ("PIRATES", "#ff0000")],
                     players=[("friend_one", "wolves", ""), ("BAD_GUY", "Pirates", "#123456"),
                              ("LONER", "", "yellow")],
                     unlisted="#abcdef")
        assert made.problems == ()
        friend = made.find("FRIEND_ONE")
        # An org's name is in capitals too, however it was saved: the label
        # over a mark reads like the tag under it.
        assert (friend.name, friend.color, friend.label) == ("FRIEND_ONE", "#40C057", "WOLVES")
        # Under an org, the org's color counts, not the player's own.
        assert made.find("BAD_GUY").color == "#FF0000"
        loner = made.find("LONER")
        assert (loner.color, loner.label) == ("#FCC419", "")
        assert made.find("STRANGER") is None
        assert made.unlisted == "#ABCDEF"

    def test_a_look_alike_reading_finds_the_listed_player(self):
        made = lists(players=[("GOOD_DOG", "", "red")])
        assert made.find("G00D_D0G").name == "GOOD_DOG"
        assert made.find("GOOD_DQG").name == "GOOD_DOG"
        assert made.find("GOOD_CAT") is None

    def test_two_listed_names_that_look_alike_need_the_exact_spelling(self):
        made = lists(players=[("BOB", "", "red"), ("B0B", "", "blue")])
        assert made.find("BOB").color != made.find("B0B").color
        assert made.find("8OB") is None

    def test_an_entry_that_cannot_be_used_is_named_and_left_out(self):
        made = PlayerLists.from_data({
            "orgs": [["WOLVES", "sparkly"], ["", "red"], ["three", "fields", "here"],
                     ["OK", "blue"]],
            "players": [["TWO WORDS", "", "red"], ["SOLO", "", "nothing"], ["LOST", "GONE", "red"],
                        ["ORPHAN", "GONE", ""], ["KEPT", "ok", ""], "not a row"],
            "unlisted": "sparkly",
        })
        # A player whose org is gone falls back to their own color when they
        # have one, and is left out when they have none.
        assert sorted(made.players) == ["KEPT", "LOST"]
        assert made.find("KEPT").color == "#4DABF7" and made.find("LOST").label == ""
        assert len(made.problems) == 8
        assert made.unlisted == UNLISTED_DEFAULT

    @pytest.mark.parametrize("data", [None, {}, [], "text", {"orgs": "x", "players": 5}])
    def test_nothing_saved_or_a_damaged_value_gives_empty_lists(self, data):
        made = PlayerLists.from_data(data)
        assert not made.players and made.unlisted == UNLISTED_DEFAULT

    def test_colors(self):
        assert parse_color(" Red ") == "#FA5252"
        assert parse_color("#a1b2c3") == "#A1B2C3"
        assert parse_color("#abc") is None and parse_color("mauve") is None
        assert parse_color("grey") == parse_color("gray")


class TestTheMarksOfALook:
    def test_a_listed_name_is_marked_at_once_in_its_color(self):
        tracker = PlayerIdTracker()
        tracker.lists = lists(orgs=[("WOLVES", "green")], players=[("FRIEND_ONE", "WOLVES", "")])
        marks = tracker.look([reading("FRIEND_ONE")], 0.0)
        assert [(m.name, m.color, m.label, m.listed, m.trusted, m.box) for m in marks] == [
            ("FRIEND_ONE", "#40C057", "WOLVES", True, True, BOX)]

    def test_a_listed_name_is_marked_with_something_beside_it_and_a_fair_match(self):
        tracker = PlayerIdTracker()
        tracker.lists = lists(players=[("FRIEND_ONE", "", "green")])
        assert tracker.look([reading("FRIEND_ONE", score=0.72, crowded=2)], 0.0)
        assert not tracker.look([reading("FRIEND_ONE", score=0.6, place=2)], 5.0)

    def test_an_unlisted_name_is_marked_once_two_looks_agree(self):
        tracker = PlayerIdTracker()
        assert tracker.look([reading("STRANGER")], 0.0) == []
        marks = tracker.look([reading("STRANGER")], 1.0)
        assert [(m.name, m.color, m.label, m.listed) for m in marks] == [
            ("STRANGER", UNLISTED_DEFAULT, "", False)]

    def test_a_carried_reading_is_not_a_second_look(self):
        tracker = PlayerIdTracker()
        tracker.look([reading("STRANGER")], 0.0)
        assert tracker.look([reading("STRANGER", fresh=False)], 1.0) == []
        assert tracker.look([reading("STRANGER", fresh=False)], 2.0) == []
        marks = tracker.look([reading("STRANGER")], 3.0)
        assert [m.name for m in marks] == ["STRANGER"]
        # Once trusted, a carried reading keeps the mark where the tag is now.
        moved = (300, 400, 80, 17)
        marks = tracker.look([reading("STRANGER", fresh=False, box=moved)], 3.5)
        assert [m.box for m in marks] == [moved]

    def test_unlisted_names_are_left_out_when_switched_off(self):
        tracker = PlayerIdTracker()
        tracker.mark_unlisted = False
        tracker.lists = lists(players=[("FRIEND_ONE", "", "green")])
        tracker.look([reading("STRANGER"), reading("FRIEND_ONE", box=OTHER_BOX, place=2)], 0.0)
        marks = tracker.look([reading("STRANGER"), reading("FRIEND_ONE", box=OTHER_BOX, place=2)],
                             1.0)
        assert [m.name for m in marks] == ["FRIEND_ONE"]

    def test_the_games_own_words_are_never_marked(self):
        tracker = PlayerIdTracker()
        tracker.words = game_words("ui_controls=Controls\n")
        tracker.look([reading("CONTROLS")], 0.0)
        assert tracker.look([reading("CONTROLS")], 1.0) == []

    def test_each_tag_has_its_own_mark(self):
        tracker = PlayerIdTracker()
        tracker.lists = lists(players=[("TWIN", "", "green")])
        marks = tracker.look([reading("TWIN", place=1),
                              reading("TWIN", box=OTHER_BOX, place=2)], 0.0)
        assert sorted(m.box for m in marks) == sorted([BOX, OTHER_BOX])

    def test_a_mark_stays_on_its_tag_when_it_is_misread_a_little(self):
        tracker = PlayerIdTracker()
        tracker.lists = lists(players=[("FRIEND_ONE", "", "green")])
        tracker.look([reading("FRIEND_ONE")], 0.0)
        moved = (120, 210, 80, 17)
        # One letter wrong (not a look-alike), read with something beside it.
        marks = tracker.look([reading("FRIEND_XNE", crowded=1, box=moved)], 0.4)
        assert [(m.name, m.color, m.box) for m in marks] == [("FRIEND_ONE", "#40C057", moved)]
        # The place now reads something else altogether: the mark goes.
        assert tracker.look([reading("CONTROLS_PANEL", box=moved)], 0.8) == []

    def test_a_mark_outlives_one_missed_look_and_then_goes(self):
        tracker = PlayerIdTracker()
        tracker.lists = lists(players=[("FRIEND_ONE", "", "green")])
        tracker.look([reading("FRIEND_ONE")], 0.0)
        assert [m.name for m in tracker.look([], HOLD_S - 0.1)] == ["FRIEND_ONE"]
        assert tracker.look([], HOLD_S + 0.1) == []

    def test_reset_drops_the_marks_and_keeps_the_votes(self):
        tracker = PlayerIdTracker()
        tracker.look([reading("STRANGER")], 0.0)
        tracker.look([reading("STRANGER")], 1.0)
        tracker.reset()
        assert tracker.look([], 1.1) == []
        marks = tracker.look([reading("STRANGER", fresh=False)], 1.2)
        assert [m.name for m in marks] == ["STRANGER"]


class TestTheTestSwitch:
    """``mark_all``: every tag read is marked at once, with the text that was
    read above it."""

    def test_a_single_reading_is_marked_at_once_as_not_trusted_yet(self):
        tracker = PlayerIdTracker()
        tracker.mark_all = True
        marks = tracker.look([reading("STRANGER")], 0.0)
        assert [(m.name, m.color, m.label, m.listed, m.trusted) for m in marks] == [
            ("STRANGER", UNTRUSTED_COLOR, "STRANGER", False, False)]

    def test_it_turns_to_the_unlisted_color_once_two_looks_agree(self):
        tracker = PlayerIdTracker()
        tracker.mark_all = True
        tracker.look([reading("STRANGER")], 0.0)
        marks = tracker.look([reading("STRANGER")], 1.0)
        assert [(m.name, m.color, m.label, m.trusted) for m in marks] == [
            ("STRANGER", UNLISTED_DEFAULT, "STRANGER", True)]

    def test_it_marks_what_the_rule_holds_back(self):
        tracker = PlayerIdTracker()
        tracker.mark_all = True
        tracker.words = game_words("ui_controls=Controls\n")
        held_back = [reading("CONTROLS", place=1),               # one of the game's words
                     reading("HALF_NAM", crowded=2, place=2),     # something beside it
                     reading("FAINT_ONE", score=0.5, place=3),    # a poor match
                     reading("210", place=4)]                     # digits only
        marks = tracker.look(held_back, 0.0)
        assert sorted(m.name for m in marks) == ["210", "CONTROLS", "FAINT_ONE", "HALF_NAM"]
        assert not any(m.trusted for m in marks)

    NOT_NAMES = ("UNKNOWN", "LV-5121-VA", "TWO WORDS")

    def test_a_tag_that_cannot_be_a_name_is_marked_in_a_color_of_its_own(self):
        tracker = PlayerIdTracker()
        tracker.mark_all = True
        marks = tracker.look([reading(text, place=place)
                              for place, text in enumerate(self.NOT_NAMES, 1)], 0.0)
        assert sorted((m.name, m.label, m.color, m.listed, m.trusted) for m in marks) == [
            (text, text, NOT_A_NAME_COLOR, False, False) for text in sorted(self.NOT_NAMES)]

    def test_without_it_such_a_tag_is_never_marked(self):
        tracker = PlayerIdTracker()
        for now in (0.0, 1.0, 2.0):
            marks = tracker.look([reading(text, place=place)
                                  for place, text in enumerate(self.NOT_NAMES, 1)], now)
        assert marks == []

    def test_switching_it_off_takes_its_marks_away_at_the_next_look(self):
        tracker = PlayerIdTracker()
        tracker.mark_all = True
        assert len(tracker.look([reading("UNKNOWN", place=1), reading("READ_ONCE", place=2)],
                                0.0)) == 2
        tracker.mark_all = False
        assert tracker.look([reading("UNKNOWN", fresh=False, place=1),
                             reading("READ_ONCE", fresh=False, place=2)], 0.3) == []

    def test_a_trusted_mark_stays_when_its_tag_is_misread_a_little(self):
        tracker = PlayerIdTracker()
        tracker.mark_all = True
        tracker.lists = lists(players=[("FRIEND_ONE", "", "green")])
        tracker.look([reading("FRIEND_ONE")], 0.0)
        marks = tracker.look([reading("FRIEND_XNE", crowded=1)], 0.4)
        assert [(m.name, m.color, m.trusted) for m in marks] == [("FRIEND_ONE", "#40C057", True)]
        # Another tag at that place is marked as what it reads.
        marks = tracker.look([reading("CARGO_DECK")], 0.8)
        assert [(m.name, m.trusted) for m in marks] == [("CARGO_DECK", False)]

    def test_it_marks_unlisted_names_even_with_that_switch_off(self):
        tracker = PlayerIdTracker()
        tracker.mark_all, tracker.mark_unlisted = True, False
        tracker.look([reading("STRANGER")], 0.0)
        assert [m.name for m in tracker.look([reading("STRANGER")], 1.0)] == ["STRANGER"]

    def test_a_listed_name_shows_its_org_or_its_name(self):
        tracker = PlayerIdTracker()
        tracker.mark_all = True
        tracker.lists = lists(orgs=[("WOLVES", "green")],
                              players=[("FRIEND_ONE", "WOLVES", ""), ("LONER", "", "red")])
        marks = tracker.look([reading("FRIEND_ONE", place=1),
                              reading("LONER", box=OTHER_BOX, place=2)], 0.0)
        assert sorted((m.name, m.label) for m in marks) == [
            ("FRIEND_ONE", "WOLVES"), ("LONER", "LONER")]


def network_imports(source: str) -> list:
    """The imports in *source* that could reach the network."""
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return sorted(name for name in names
                  if name.split(".")[0] in NETWORK_MODULES
                  or any(part in name for part in QT_NETWORK_PARTS))


NETWORK_MODULES = {"urllib", "urllib3", "http", "requests", "socket", "ssl", "ftplib", "smtplib",
                   "aiohttp", "httpx", "websocket", "websockets", "webbrowser"}
QT_NETWORK_PARTS = ("QtNetwork", "QtWebSockets", "QtWebEngine")


class TestNothingIsLookedUp:
    """The player ID test sends nothing anywhere. RSI's terms forbid a
    program asking its site about a player, so no module of the test may
    import anything that could. The one way out is the lists editor's
    "Open RSI page" button, which hands an address to the user's own browser
    (``test_player_lists_dialog.py``)."""

    MODULES = ("src/utils/player_id.py", "src/utils/sco_tag_scan.py",
               "src/utils/sco_tag_reader.py", "src/utils/sco_tag_glyphs.py",
               "src/utils/game_window.py", "src/gui/player_id_overlay.py",
               "src/gui/player_lists_dialog.py")

    @pytest.mark.parametrize("relative", MODULES)
    def test_no_module_imports_anything_that_reaches_the_network(self, relative):
        source = (Path(__file__).parent.parent / relative).read_text(encoding="utf-8")
        assert network_imports(source) == []

    @pytest.mark.parametrize("source, found", [
        ("import urllib.request", ["urllib.request"]),
        ("from urllib import request", ["urllib", "urllib.request"]),
        ("import requests as r", ["requests"]),
        ("import socket", ["socket"]),
        ("def f():\n    import http.client", ["http.client"]),
        ("from PyQt6 import QtNetwork", ["PyQt6.QtNetwork"]),
        ("from PyQt6.QtNetwork import QNetworkAccessManager",
         ["PyQt6.QtNetwork", "PyQt6.QtNetwork.QNetworkAccessManager"]),
        ("from PyQt6.QtCore import QUrl\nimport ctypes\nfrom src.utils import game_window", []),
    ])
    def test_the_check_sees_each_way_of_importing(self, source, found):
        assert network_imports(source) == found


class TestTheNamesReadAreToldOnce:
    """``take_new_names`` feeds the record of past players: each name once."""

    def test_a_listed_name_at_once_and_another_once_two_looks_agree(self):
        tracker = PlayerIdTracker()
        tracker.lists = lists(players=[("FRIEND_ONE", "", "green")])
        looked_at = [reading("OLD_ONE", place=1), reading("FRIEND_ONE", place=2)]
        tracker.look(looked_at, 0.0)
        assert tracker.take_new_names() == ["FRIEND_ONE"]
        tracker.look(looked_at, 1.0)
        assert tracker.take_new_names() == ["OLD_ONE"]
        tracker.look(looked_at, 2.0)
        assert tracker.take_new_names() == []               # nobody twice

    def test_a_name_read_once_is_not_told(self):
        tracker = PlayerIdTracker()
        tracker.mark_all = True
        tracker.look([reading("READ_ONCE")], 0.0)
        assert tracker.take_new_names() == []

    def test_a_name_is_told_even_when_unlisted_names_are_not_marked(self):
        tracker = PlayerIdTracker()
        tracker.mark_unlisted = False
        tracker.look([reading("STRANGER")], 0.0)
        assert tracker.look([reading("STRANGER")], 1.0) == []
        assert tracker.take_new_names() == ["STRANGER"]

    def test_a_tag_that_is_no_name_is_never_told(self):
        tracker = PlayerIdTracker()
        tracker.mark_all = True
        tracker.words = game_words("ui_controls=Controls\n")
        tracker.places = PlaceList.from_data([["NEW BABBAGE", "red"]])
        tracker.mark_places = True
        for now in (0.0, 1.0, 2.0):
            tracker.look([reading("UNKNOWN", place=1), reading("AB-1234-CD", place=2),
                          reading("CONTROLS", place=3), reading("NEW BABBAGE", place=4)], now)
        assert tracker.take_new_names() == []

    def test_a_reset_does_not_tell_a_name_again(self):
        tracker = PlayerIdTracker()
        for now in (0.0, 1.0):
            tracker.look([reading("STRANGER")], now)
        assert tracker.take_new_names() == ["STRANGER"]
        tracker.reset()                                     # the game went to the back
        tracker.look([reading("STRANGER")], 5.0)
        assert tracker.take_new_names() == []


SESSION_ONE, SESSION_TWO = "2026-11-01 09:00:00", "2026-11-15 14:02:10"


class TestPastPlayers:
    def test_a_name_is_news_once_a_session(self):
        past = PastPlayers()
        assert past.session == "" and past.everyone() == [] and past.last_session() == []
        assert past.saw("STRANGER", SESSION_ONE) is True
        assert past.saw("STRANGER", SESSION_ONE) is False
        assert past.saw("OTHER_ONE", SESSION_ONE) is True
        assert past.session == SESSION_ONE
        assert past.last_session() == ["OTHER_ONE", "STRANGER"]          # newest first
        assert past.everyone() == [("OTHER_ONE", SESSION_ONE), ("STRANGER", SESSION_ONE)]

    def test_a_new_session_keeps_the_old_names_and_moves_up_a_name_read_again(self):
        past = PastPlayers()
        for name in ("AAA", "BBB"):
            past.saw(name, SESSION_ONE)
        assert past.saw("BBB", SESSION_TWO) is True         # news: last read a session ago
        past.saw("CCC", SESSION_TWO)
        assert past.session == SESSION_TWO
        assert past.last_session() == ["CCC", "BBB"]
        assert past.everyone() == [("CCC", SESSION_TWO), ("BBB", SESSION_TWO), ("AAA", SESSION_ONE)]

    def test_it_goes_into_the_settings_and_comes_back_the_same(self):
        past = PastPlayers()
        past.saw("AAA", SESSION_ONE)
        past.saw("BBB", SESSION_TWO)
        data = past.to_data()
        assert data == {"session": SESSION_TWO,
                        "names": [["BBB", SESSION_TWO], ["AAA", SESSION_ONE]]}
        again = PastPlayers.from_data(data)
        assert again.to_data() == data and again.last_session() == ["BBB"]
        assert again.saw("BBB", SESSION_TWO) is False       # known, as before it was saved

    def test_the_oldest_names_go_when_it_is_full(self, monkeypatch):
        monkeypatch.setattr("src.utils.player_id.MAX_PAST_NAMES", 3)
        past = PastPlayers()
        for name in ("AAA", "BBB", "CCC", "DDD"):
            past.saw(name, SESSION_ONE)
        assert [name for name, _session in past.everyone()] == ["DDD", "CCC", "BBB"]

    @pytest.mark.parametrize("data", [None, {}, [], "text", 5, {"names": "x", "session": 7}])
    def test_nothing_saved_or_a_damaged_value_gives_an_empty_record(self, data):
        past = PastPlayers.from_data(data)
        assert past.to_data() == {"session": "", "names": []}

    def test_an_entry_that_cannot_be_a_name_is_left_out(self):
        past = PastPlayers.from_data({"session": SESSION_ONE, "names": [
            ["two words", SESSION_ONE], ["ok_name", SESSION_ONE], "row", ["ONE_FIELD"],
            ["OK_NAME", "2026-01-01 00:00:00"], ["ab", SESSION_ONE]]})
        # In capitals, each name once (the first, which is the newest).
        assert past.everyone() == [("OK_NAME", SESSION_ONE)]


class TestTheLocationsList:
    def test_a_listed_text_is_found_with_its_color(self):
        places = PlaceList.from_data([["new  babbage", "green"], ["OM-3", "#ff0000"]])
        assert places.problems == () and sorted(places.places) == ["NEW BABBAGE", "OM-3"]
        assert places.find("NEW BABBAGE") == ("NEW BABBAGE", "#40C057")
        assert places.find("OM-3") == ("OM-3", "#FF0000")
        assert places.find("PORT TRESSLER") is None

    @pytest.mark.parametrize("read", ["NEWBABBAGE", "NEW BAB BAGE", "NEW BA8BAGE", "NEW BABBA6E",
                                      "N3W BABBAGE", "NEW BABBAGF"])
    def test_a_gap_a_look_alike_or_one_character_off_still_counts(self, read):
        places = PlaceList.from_data([["NEW BABBAGE", "green"]])
        assert places.find(read) == ("NEW BABBAGE", "#40C057")

    @pytest.mark.parametrize("read", ["NEW BXBBXGE", "NEW BABB", "OLD BABBAGE", ""])
    def test_more_than_that_does_not(self, read):
        assert PlaceList.from_data([["NEW BABBAGE", "green"]]).find(read) is None

    def test_a_gap_is_not_a_character_off(self):
        """The spaces are left out before anything is compared, so a missed
        gap costs nothing: not the one character a long text may be off,
        and not at all for a short text, which may not be off by any."""
        places = PlaceList.from_data([["OM 12", "red"], ["PORT OF CALL", "blue"]])
        assert places.find("OM12") == ("OM 12", "#FA5252")
        assert places.find("PORTOFCALL") == ("PORT OF CALL", "#4DABF7")      # two gaps missed
        assert places.find("PORTOFCALI") == ("PORT OF CALL", "#4DABF7")      # and a look-alike
        assert places.find("PORTOFCAXL") == ("PORT OF CALL", "#4DABF7")      # and one character

    def test_a_short_text_must_be_read_exactly(self):
        places = PlaceList.from_data([["OM-3", "red"], ["LEVSKI", "blue"]])
        assert places.find("OM-4") is None and places.find("OM-3") is not None
        assert places.find("LEVSKY") == ("LEVSKI", "#4DABF7")           # six characters: one off

    def test_a_reading_as_near_two_listed_texts_is_neither(self):
        places = PlaceList.from_data([["AREA18", "red"], ["AREA19", "blue"]])
        assert places.find("AREA18")[1] == "#FA5252" and places.find("AREA19")[1] == "#4DABF7"
        assert places.find("AREA1X") is None

    def test_two_listed_texts_that_look_alike_need_the_exact_text(self):
        places = PlaceList.from_data([["BOB STATION", "red"], ["B0B STATION", "blue"]])
        assert places.find("BOB STATION")[1] != places.find("B0B STATION")[1]
        assert places.find("8OB STATION") is None

    def test_an_entry_that_cannot_be_used_is_named_and_left_out(self):
        places = PlaceList.from_data([
            ["ab", "red"], ["OK PLACE", "nothing"], ["what?", "red"], "not a row",
            ["GOOD ONE", "blue"], ["good  one", "red"], ["x" * 41, "red"]])
        assert places.places == {"GOOD ONE": "#4DABF7"}     # listed once, the first time
        assert len(places.problems) == 5

    @pytest.mark.parametrize("data", [None, {}, "text", 5, {"a": 1}])
    def test_nothing_saved_or_a_damaged_value_gives_an_empty_list(self, data):
        places = PlaceList.from_data(data)
        assert places.places == {} and places.find("NEW BABBAGE") is None

    def test_a_location_is_kept_in_capitals_with_single_spaces(self):
        assert clean_place("  new   babbage ") == "NEW BABBAGE"


class TestHighlightedLocations:
    @staticmethod
    def tracker() -> PlayerIdTracker:
        made = PlayerIdTracker()
        made.places = PlaceList.from_data([["NEW BABBAGE", "red"], ["LORVILLE", "blue"]])
        made.mark_places = True
        return made

    def test_a_listed_location_is_marked_at_once_as_a_place(self):
        marks = self.tracker().look([reading("NEW BABBAGE")], 0.0)
        assert [(m.name, m.color, m.label, m.listed, m.trusted, m.place, m.box) for m in marks] == [
            ("NEW BABBAGE", "#FA5252", "", True, True, True, BOX)]

    def test_it_needs_its_switch_and_a_fair_match(self):
        tracker = self.tracker()
        assert tracker.look([reading("NEW BABBAGE", score=0.6)], 0.0) == []
        tracker.mark_places = False
        assert tracker.look([reading("NEW BABBAGE", place=2)], 5.0) == []
        assert PlayerIdTracker().mark_places is False        # off unless switched on

    def test_with_names_off_only_locations_are_marked(self):
        tracker = self.tracker()
        tracker.lists = lists(players=[("FRIEND_ONE", "", "green")])
        tracker.mark_names, tracker.mark_all = False, True   # the test switch hangs under names
        for now in (0.0, 1.0):
            marks = tracker.look([reading("FRIEND_ONE", place=1), reading("STRANGER", place=2),
                                  reading("NEW BABBAGE", place=3)], now)
        assert [(m.name, m.place) for m in marks] == [("NEW BABBAGE", True)]

    def test_names_are_marked_as_before_beside_it(self):
        tracker = self.tracker()
        tracker.lists = lists(players=[("FRIEND_ONE", "", "green")])
        marks = tracker.look([reading("FRIEND_ONE", place=1), reading("NEW BABBAGE", place=2)], 0.0)
        assert sorted((m.name, m.place, m.listed) for m in marks) == [
            ("FRIEND_ONE", False, True), ("NEW BABBAGE", True, True)]

    def test_a_one_word_location_is_marked_though_it_is_one_of_the_games_words(self):
        tracker = self.tracker()
        tracker.words = game_words("ui_place=Lorville\n")
        marks = tracker.look([reading("LORVILLE")], 0.0)
        assert [(m.name, m.color, m.place) for m in marks] == [("LORVILLE", "#4DABF7", True)]

    def test_with_the_test_switch_it_keeps_its_own_mark(self):
        tracker = self.tracker()
        tracker.mark_all = True
        marks = tracker.look([reading("NEW BABBAGE")], 0.0)
        assert [(m.color, m.place, m.trusted) for m in marks] == [("#FA5252", True, True)]

    def test_its_mark_stays_when_it_is_misread_a_little(self):
        tracker = self.tracker()
        tracker.look([reading("NEW BABBAGE")], 0.0)
        marks = tracker.look([reading("NEW BXBBXGE", box=OTHER_BOX)], 0.5)
        assert [(m.name, m.place, m.box) for m in marks] == [("NEW BABBAGE", True, OTHER_BOX)]
