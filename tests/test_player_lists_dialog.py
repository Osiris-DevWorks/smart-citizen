"""The player ID test's editors (``src/gui/player_lists_dialog.py``),
headless: the lists editor and the editor of the locations to highlight.

The dialogs are built and driven without being shown, except where a cell is
typed into. Their three ways out of the app are stand-ins, so no test opens
a browser, a colour picker or a message box: ``QDesktopServices.openUrl``,
``QColorDialog.getColor`` and ``QMessageBox.warning``.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QEvent, QItemSelectionModel, Qt
from PyQt6.QtGui import QColor, QKeyEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QLineEdit

from src.gui import player_lists_dialog as module
from src.gui.player_lists_dialog import (
    LOCATION_COLOR_COLUMN, NAME_COLUMN, NEW_COLORS, ORG_COLOR_COLUMN, PLAYER_COLOR_COLUMN,
    PLAYER_ORG_COLUMN, ColorButton, LocationListDialog, PlayerListsDialog,
)
from src.utils.i18n import tr
from src.utils.player_id import UNLISTED_DEFAULT, PlaceList, PlayerLists

# Saved as an older build left them, in any case: the editor shows capitals.
SAVED = {"orgs": [["Wolves", "green"], ["PIRATES", "#ff0000"]],
         "players": [["friend_one", "wolves", ""], ["BAD_GUY", "Pirates", "#123456"],
                     ["LONER", "", "#112233"]],
         "unlisted": "#abcdef"}
# The names read in play, newest first: three in the last session (one of
# them listed), and two in earlier ones (one of them listed).
PAST = {"session": "2026-11-15 14:02:10",
        "names": [["NEWCOMER", "2026-11-15 14:02:10"], ["STRANGER", "2026-11-15 14:02:10"],
                  ["FRIEND_ONE", "2026-11-15 14:02:10"], ["OLD_HAND", "2026-11-01 09:00:00"],
                  ["LONER", "2026-10-20 20:00:00"]]}
PLACES = [["new babbage", "green"], ["OM-3", "#ff0000"]]
SELECT = QItemSelectionModel.SelectionFlag


@pytest.fixture
def opened(monkeypatch):
    """What the dialog handed to the user's browser and to a message box."""
    record = {"urls": [], "warnings": []}
    monkeypatch.setattr(module, "QDesktopServices", SimpleNamespace(
        openUrl=lambda url: record["urls"].append(url.toString())))
    monkeypatch.setattr(module, "QMessageBox", SimpleNamespace(
        warning=lambda parent, title, text: record["warnings"].append(text)))
    return record


def org_name(dialog, row: int):
    """The cell that holds an org's name."""
    return dialog.orgs.item(row, NAME_COLUMN)


def org_color(dialog, row: int):
    return dialog.orgs.cellWidget(row, ORG_COLOR_COLUMN)


def player_name(dialog, row: int):
    """The cell that holds a player's name."""
    return dialog.players.item(row, NAME_COLUMN)


def player_org(dialog, row: int):
    """A player's org picker."""
    return dialog.players.cellWidget(row, PLAYER_ORG_COLUMN)


def player_color(dialog, row: int):
    return dialog.players.cellWidget(row, PLAYER_COLOR_COLUMN)


def player_rows(dialog) -> list:
    """Each player row as (name, the org picked, whether its own colour can be set)."""
    return [(player_name(dialog, row).text(), player_org(dialog, row).currentData(),
             player_color(dialog, row).isEnabled())
            for row in range(dialog.players.rowCount())]


def texts(names) -> list:
    """What a list of names read in play shows, row by row."""
    return [names.item(row).text() for row in range(names.count())]


def select_rows(table, *rows: int) -> None:
    """Select whole rows, as clicks on them do. Done on the selection model
    itself: ``selectRow`` asks which keys are held, and a key event another
    test module sent can leave Ctrl held for the rest of the run, which adds
    the row to the selection instead."""
    table.clearSelection()
    for row in rows:
        table.selectionModel().select(table.model().index(row, NAME_COLUMN),
                                      SELECT.Select | SELECT.Rows)


def type_into(table, row: int, keys: str) -> QLineEdit:
    """Open a name cell's editor, as a double click does, and type *keys*
    into it. Gives back the editor, still open."""
    table.editItem(table.item(row, NAME_COLUMN))
    editor = table.findChild(QLineEdit)
    assert editor is not None, "the cell has no editor"
    editor.clear()
    QTest.keyClicks(editor, keys)
    return editor


def test_it_shows_the_saved_lists_and_gives_them_back(qapp, opened):
    dialog = PlayerListsDialog(SAVED, {})
    assert dialog.lists() == {
        # Names are in capitals, an org's too, however they were saved.
        "orgs": [["WOLVES", "#40C057"], ["PIRATES", "#FF0000"]],
        # A player under an org keeps a colour of their own for later: the
        # one that was saved, or the one a new player starts with.
        "players": [["FRIEND_ONE", "WOLVES", NEW_COLORS[1]], ["BAD_GUY", "PIRATES", "#123456"],
                    ["LONER", "", "#112233"]],
        "unlisted": "#ABCDEF"}
    assert [org_name(dialog, row).text() for row in range(2)] == ["WOLVES", "PIRATES"]
    # A player under an org takes the org's colour, so their own is greyed.
    assert player_rows(dialog) == [("FRIEND_ONE", "WOLVES", False), ("BAD_GUY", "PIRATES", False),
                                   ("LONER", "", True)]
    # What it gives back is what the reader takes.
    lists = PlayerLists.from_data(dialog.lists())
    assert lists.problems == () and lists.unlisted == "#ABCDEF"
    assert [(p.name, p.color, p.label) for p in lists.players.values()] == [
        ("FRIEND_ONE", "#40C057", "WOLVES"), ("BAD_GUY", "#FF0000", "PIRATES"),
        ("LONER", "#112233", "")]


@pytest.mark.parametrize("data", [None, {}, "text", [], {"orgs": 5, "players": "x"},
                                  {"orgs": [["one field"], "row"], "players": [[1, 2]]}])
def test_nothing_saved_or_a_damaged_value_opens_empty(qapp, opened, data):
    assert PlayerListsDialog(data, None).lists() == {"orgs": [], "players": [],
                                                     "unlisted": UNLISTED_DEFAULT}


def test_a_player_whose_org_is_gone_opens_with_a_color_of_their_own(qapp, opened):
    dialog = PlayerListsDialog({"players": [["ORPHAN", "GONE", "#112233"]]}, {})
    assert player_rows(dialog) == [("ORPHAN", "", True)]
    assert dialog.lists()["players"] == [["ORPHAN", "", "#112233"]]


def test_new_rows_and_removed_rows(qapp, opened):
    dialog = PlayerListsDialog({}, {})
    dialog.add_org("Pirates", "red")
    dialog.add_player("bad_guy", "Pirates")
    dialog.add_player("solo", "", "blue")
    assert dialog.lists() == {"orgs": [["PIRATES", "#FA5252"]],
                              "players": [["BAD_GUY", "PIRATES", NEW_COLORS[1]],
                                          ["SOLO", "", "#4DABF7"]],
                              "unlisted": UNLISTED_DEFAULT}
    # A row added with its button starts empty and is left out until named.
    dialog.add_org_btn.click()
    dialog.add_player_btn.click()
    assert (dialog.orgs.rowCount(), dialog.players.rowCount()) == (2, 3)
    assert len(dialog.lists()["orgs"]) == 1 and len(dialog.lists()["players"]) == 2
    org_name(dialog, 1).setText("Wolves")
    picker = player_org(dialog, 2)
    assert [picker.itemData(i) for i in range(picker.count())] == ["", "PIRATES", "WOLVES"]
    # Removing an org puts its players back on a colour of their own.
    select_rows(dialog.orgs, 0)
    dialog.remove_org_btn.click()
    assert dialog.lists()["orgs"] == [["WOLVES", NEW_COLORS[1]]]
    assert player_rows(dialog)[0] == ("BAD_GUY", "", True)
    select_rows(dialog.players, 1)
    dialog.remove_player_btn.click()
    assert [name for name, _org, _own in player_rows(dialog)] == ["BAD_GUY", ""]


def test_remove_takes_every_selected_row_or_the_current_one(qapp, opened):
    dialog = PlayerListsDialog({"players": [[name, "", "red"] for name in
                                            ("ONE", "TWO", "THREE", "FOUR")]}, {})
    select_rows(dialog.players, 0, 2)
    dialog.remove_player_btn.click()
    assert [name for name, _org, _own in player_rows(dialog)] == ["TWO", "FOUR"]
    # With nothing selected, the row the user is on goes.
    dialog.players.clearSelection()
    dialog.players.selectionModel().setCurrentIndex(
        dialog.players.model().index(1, NAME_COLUMN), SELECT.NoUpdate)
    dialog.remove_player_btn.click()
    assert [name for name, _org, _own in player_rows(dialog)] == ["TWO"]


def test_a_player_stays_under_an_org_that_is_renamed(qapp, opened):
    dialog = PlayerListsDialog(SAVED, {})
    org_name(dialog, 0).setText("Wolfpack")
    assert player_rows(dialog)[0] == ("FRIEND_ONE", "WOLFPACK", False)
    org_name(dialog, 0).setText("wolfpack")                 # the same name, set in small letters
    assert player_rows(dialog)[0] == ("FRIEND_ONE", "WOLFPACK", False)
    assert player_rows(dialog)[1] == ("BAD_GUY", "PIRATES", False)       # the others stay
    # An org whose name is emptied is gone: its players are on their own.
    org_name(dialog, 0).setText("  ")
    assert player_rows(dialog)[0] == ("FRIEND_ONE", "", True)
    assert dialog.lists()["orgs"] == [["PIRATES", "#FF0000"]]


def test_picking_an_org_greys_the_players_own_color(qapp, opened):
    dialog = PlayerListsDialog(SAVED, {})
    picker = player_org(dialog, 2)                          # LONER
    picker.setCurrentIndex(picker.findData("PIRATES"))
    assert player_rows(dialog)[2] == ("LONER", "PIRATES", False)
    picker.setCurrentIndex(0)
    assert player_rows(dialog)[2] == ("LONER", "", True)


def test_a_player_under_an_org_shows_the_orgs_color(qapp, opened, monkeypatch):
    dialog = PlayerListsDialog(SAVED, {})
    friend, loner = player_color(dialog, 0), player_color(dialog, 2)
    # The org's colour is shown, and the player's own is kept for later.
    assert (friend.shown_color(), friend.color()) == ("#40C057", NEW_COLORS[1])
    hint = tr("overlay.player_lists_org_color_hint")
    assert friend.toolTip() == hint and hint != "overlay.player_lists_org_color_hint"
    assert loner.shown_color() == loner.color() == "#112233" and loner.toolTip() == "#112233"
    # A new colour for the org shows on its players at once.
    monkeypatch.setattr(module, "QColorDialog",
                        SimpleNamespace(getColor=lambda start, parent: QColor("#010203")))
    org_color(dialog, 0).click()
    assert friend.shown_color() == "#010203"
    assert dialog.lists()["orgs"][0] == ["WOLVES", "#010203"]
    # Under another org, that org's colour. Out of every org, their own again.
    picker = player_org(dialog, 0)
    picker.setCurrentIndex(picker.findData("PIRATES"))
    assert friend.shown_color() == "#FF0000" and not friend.isEnabled()
    picker.setCurrentIndex(0)
    assert friend.shown_color() == NEW_COLORS[1] and friend.isEnabled()
    assert dialog.lists()["players"][0] == ["FRIEND_ONE", "", NEW_COLORS[1]]


def test_a_name_is_kept_in_capitals_however_it_is_set(qapp, opened):
    """The game shows every name in capitals, so the lists do too: a
    player's name and an org's."""
    dialog = PlayerListsDialog({}, {})
    dialog.add_player("solo")
    assert player_name(dialog, 0).text() == "SOLO"
    player_name(dialog, 0).setText(" bad_guy ")             # as a paste could leave it
    assert player_name(dialog, 0).text() == "BAD_GUY"
    dialog.add_org("Wolves")
    assert org_name(dialog, 0).text() == "WOLVES"
    org_name(dialog, 0).setText(" wolf pack ")
    assert org_name(dialog, 0).text() == "WOLF PACK"
    assert dialog.lists()["orgs"] == [["WOLF PACK", NEW_COLORS[0]]]


def test_a_name_shows_in_capitals_as_it_is_typed(qapp, opened):
    """Typed into its cell, a name is in capitals from the first letter,
    for an org and for a player. Enter ends the edit and leaves the editor
    open."""
    dialog = PlayerListsDialog({}, {})
    closed = []
    dialog.finished.connect(closed.append)
    dialog.show()
    qapp.processEvents()
    try:
        dialog.add_org("x")
        editor = type_into(dialog.orgs, 0, "wolf pack")
        assert editor.text() == "WOLF PACK"                 # while it is still being typed
        QTest.keyClick(editor, Qt.Key.Key_Return)
        qapp.processEvents()
        assert org_name(dialog, 0).text() == "WOLF PACK"
        dialog.add_player("x", "WOLF PACK")
        editor = type_into(dialog.players, 0, "friend_one")
        assert editor.text() == "FRIEND_ONE"
        editor.insert("_two")                               # a paste goes the same way
        assert editor.text() == "FRIEND_ONE_TWO"
        QTest.keyClick(editor, Qt.Key.Key_Return)
        qapp.processEvents()
        assert player_name(dialog, 0).text() == "FRIEND_ONE_TWO"
        assert closed == [] and dialog.isVisible()
        assert dialog.lists()["players"] == [["FRIEND_ONE_TWO", "WOLF PACK", NEW_COLORS[1]]]
    finally:
        dialog.hide()


def test_a_name_is_listed_once(qapp, opened):
    dialog = PlayerListsDialog({"orgs": [["Wolves", "green"], ["WOLVES", "red"]],
                                "players": [["TWIN", "", "red"], ["twin", "", "blue"]]}, {})
    assert dialog.lists()["orgs"] == [["WOLVES", "#40C057"]]
    assert dialog.lists()["players"] == [["TWIN", "", "#FA5252"]]


def test_the_names_read_in_play_are_offered(qapp, opened):
    """The last session's names on one side and everyone read in any
    session on the other, each without the names already listed."""
    dialog = PlayerListsDialog(SAVED, PAST)
    assert dialog.seen_label.text() == ("Last session (2026-11-15 14:02): names read that are "
                                        "on no list")
    assert texts(dialog.seen) == ["NEWCOMER", "STRANGER"]   # not FRIEND_ONE, who is listed
    # Everyone, newest first, with the day each was last read.
    assert texts(dialog.past) == ["NEWCOMER    2026-11-15", "STRANGER    2026-11-15",
                                  "OLD_HAND    2026-11-01"]
    assert dialog.past.toolTip().startswith("Each name with the day it was last read.")
    assert not dialog.past_cleared()


@pytest.mark.parametrize("past", [None, {}, [], "text", {"names": 5}, {"session": 3},
                                  {"names": [["a b", "x"], "row", ["ONLY_ONE_FIELD"]]}])
def test_no_names_read_or_a_damaged_record_offers_nothing(qapp, opened, past):
    dialog = PlayerListsDialog(SAVED, past)
    assert texts(dialog.seen) == [] and texts(dialog.past) == []
    assert dialog.seen_label.text() == "Last session: no names read yet"


def test_a_name_read_in_play_is_added_from_either_list(qapp, opened):
    dialog = PlayerListsDialog(SAVED, PAST)
    dialog.past.item(2).setSelected(True)                   # OLD_HAND, from an earlier session
    dialog.add_seen_btn.click()
    assert player_rows(dialog)[-1] == ("OLD_HAND", "", True)
    assert texts(dialog.past) == ["NEWCOMER    2026-11-15", "STRANGER    2026-11-15"]
    # One from the last session leaves both lists, since it is in both.
    dialog.seen.item(0).setSelected(True)                   # NEWCOMER
    dialog.add_seen_btn.click()
    assert texts(dialog.seen) == ["STRANGER"] and texts(dialog.past) == ["STRANGER    2026-11-15"]
    assert [row[0] for row in player_rows(dialog)][-2:] == ["OLD_HAND", "NEWCOMER"]
    assert dialog.lists()["players"][-1] == ["NEWCOMER", "", NEW_COLORS[1]]
    # A name picked in both lists is added once.
    dialog.seen.item(0).setSelected(True)
    dialog.past.item(0).setSelected(True)
    dialog.add_seen_btn.click()
    assert [row[0] for row in player_rows(dialog)].count("STRANGER") == 1
    assert texts(dialog.seen) == [] and texts(dialog.past) == []
    assert opened["urls"] == []                             # adding a name opens nothing
    assert not dialog.past_cleared()                        # and clears nothing


def test_clear_past_players_empties_both_lists_and_says_so(qapp, opened):
    dialog = PlayerListsDialog(SAVED, PAST)
    assert dialog.clear_past_btn.text() == "Clear past players"
    dialog.clear_past_btn.click()
    assert texts(dialog.seen) == [] and texts(dialog.past) == []
    assert dialog.seen_label.text() == "Last session: no names read yet"
    assert dialog.past_cleared()
    # The orgs and players stay.
    assert len(dialog.lists()["players"]) == 3 and len(dialog.lists()["orgs"]) == 2


def test_open_rsi_page_hands_the_address_to_the_users_browser(qapp, opened):
    dialog = PlayerListsDialog(SAVED, PAST)
    assert opened["urls"] == []                             # nothing opens by itself
    dialog.open_seen_btn.click()
    dialog.open_player_btn.click()
    assert opened["urls"] == []                             # nor with nothing picked
    dialog.past.item(2).setSelected(True)                   # OLD_HAND
    dialog.open_seen_btn.click()
    assert opened["urls"] == ["https://robertsspaceindustries.com/citizens/OLD_HAND"]
    dialog.seen.item(1).setSelected(True)                   # STRANGER: the last session's first
    dialog.open_seen_btn.click()
    assert opened["urls"][1:] == ["https://robertsspaceindustries.com/citizens/STRANGER"]
    dialog.players.setCurrentCell(2, NAME_COLUMN)
    dialog.open_player_btn.click()
    assert opened["urls"][2:] == ["https://robertsspaceindustries.com/citizens/LONER"]
    # Text that cannot be a name is never put into an address.
    player_name(dialog, 2).setText("NOT A NAME/../x")
    dialog.open_player_btn.click()
    assert len(opened["urls"]) == 3


def test_a_name_that_cannot_be_a_tag_is_refused_on_ok(qapp, opened):
    dialog = PlayerListsDialog(SAVED, {})
    closed = []
    dialog.finished.connect(closed.append)
    dialog.add_player("two words")
    dialog.add_player("ab")
    assert dialog.bad_names() == ["TWO WORDS", "AB"]
    dialog.accept()
    assert closed == [] and len(opened["warnings"]) == 1
    assert "TWO WORDS, AB" in opened["warnings"][0]
    # Until they are put right they are left out of what would be saved.
    assert [name for name, _org, _color in dialog.lists()["players"]] == [
        "FRIEND_ONE", "BAD_GUY", "LONER"]
    player_name(dialog, 3).setText("TWO_WORDS")
    player_name(dialog, 4).setText("ABC")
    dialog.accept()
    assert closed == [QDialog.DialogCode.Accepted.value] and len(opened["warnings"]) == 1
    assert [name for name, _org, _color in dialog.lists()["players"]][3:] == ["TWO_WORDS", "ABC"]


@pytest.mark.parametrize("make", [lambda: PlayerListsDialog(SAVED, {}),
                                  lambda: LocationListDialog(PLACES)])
def test_enter_does_not_close_it(qapp, opened, make):
    """Enter ends a cell's edit. Passed on to the dialog it would press OK,
    the default button once the dialog is on screen."""
    dialog = make()
    closed = []
    dialog.finished.connect(closed.append)
    dialog.show()
    qapp.processEvents()
    try:
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            QApplication.sendEvent(dialog, QKeyEvent(QEvent.Type.KeyPress, key,
                                                     Qt.KeyboardModifier.NoModifier))
        assert closed == [] and dialog.isVisible()
        QApplication.sendEvent(dialog, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape,
                                                 Qt.KeyboardModifier.NoModifier))
        assert closed == [QDialog.DialogCode.Rejected.value]
    finally:
        dialog.hide()


class TestTheLocationsEditor:
    @staticmethod
    def rows(dialog) -> list:
        return [(dialog.table.item(row, NAME_COLUMN).text(),
                 dialog.table.cellWidget(row, LOCATION_COLOR_COLUMN).color())
                for row in range(dialog.table.rowCount())]

    def test_it_shows_the_saved_list_and_gives_it_back(self, qapp, opened):
        dialog = LocationListDialog(PLACES)
        assert dialog.windowTitle() == "Locations to highlight (test)"
        assert self.rows(dialog) == [("NEW BABBAGE", "#40C057"), ("OM-3", "#FF0000")]
        assert dialog.locations() == [["NEW BABBAGE", "#40C057"], ["OM-3", "#FF0000"]]
        # What it gives back is what the reader takes.
        places = PlaceList.from_data(dialog.locations())
        assert places.problems == () and places.find("NEW BABBAGE") == ("NEW BABBAGE", "#40C057")

    @pytest.mark.parametrize("data", [None, {}, "text", 5, [["one field"], "row", [1, 2, 3]]])
    def test_nothing_saved_or_a_damaged_value_opens_empty(self, qapp, opened, data):
        assert LocationListDialog(data).locations() == []

    def test_new_rows_and_removed_rows(self, qapp, opened):
        dialog = LocationListDialog([])
        dialog.add_location("Port Tressler", "red")
        dialog.add_location("grim hex")
        assert dialog.locations() == [["PORT TRESSLER", "#FA5252"], ["GRIM HEX", NEW_COLORS[1]]]
        # A row added with its button starts empty and is left out until named.
        assert dialog.add_btn.text() == "Add location"
        dialog.add_btn.click()
        assert dialog.table.rowCount() == 3 and len(dialog.locations()) == 2
        dialog.table.item(2, NAME_COLUMN).setText("area18")
        assert dialog.locations()[2] == ["AREA18", NEW_COLORS[2]]
        select_rows(dialog.table, 0, 1)
        dialog.remove_btn.click()
        assert dialog.locations() == [["AREA18", NEW_COLORS[2]]]

    def test_a_location_is_kept_in_capitals_with_single_spaces(self, qapp, opened):
        dialog = LocationListDialog([])
        dialog.add_location("  new   babbage ")
        assert self.rows(dialog)[0][0] == "NEW BABBAGE"
        dialog.table.item(0, NAME_COLUMN).setText(" port  tressler")
        assert self.rows(dialog)[0][0] == "PORT TRESSLER"

    def test_a_location_shows_in_capitals_as_it_is_typed(self, qapp, opened):
        dialog = LocationListDialog([])
        dialog.show()
        qapp.processEvents()
        try:
            dialog.add_location("x")
            editor = type_into(dialog.table, 0, "new babbage")
            assert editor.text() == "NEW BABBAGE"
            QTest.keyClick(editor, Qt.Key.Key_Return)
            qapp.processEvents()
            assert dialog.locations() == [["NEW BABBAGE", NEW_COLORS[0]]] and dialog.isVisible()
        finally:
            dialog.hide()

    def test_a_location_is_listed_once(self, qapp, opened):
        dialog = LocationListDialog([["Lorville", "green"], ["LORVILLE", "red"],
                                     ["lor  ville", "blue"]])
        assert dialog.locations() == [["LORVILLE", "#40C057"], ["LOR VILLE", "#4DABF7"]]

    def test_a_color_is_picked_with_its_button(self, qapp, opened, monkeypatch):
        dialog = LocationListDialog(PLACES)
        monkeypatch.setattr(module, "QColorDialog",
                            SimpleNamespace(getColor=lambda start, parent: QColor("#010203")))
        dialog.table.cellWidget(1, LOCATION_COLOR_COLUMN).click()
        assert dialog.locations()[1] == ["OM-3", "#010203"]

    def test_a_text_that_cannot_be_read_off_a_marker_is_refused_on_ok(self, qapp, opened):
        dialog = LocationListDialog(PLACES)
        closed = []
        dialog.finished.connect(closed.append)
        dialog.add_location("ab")
        dialog.add_location("what?")
        dialog.add_location("x" * 41)
        assert dialog.bad_names() == ["AB", "WHAT?", "X" * 41]
        dialog.accept()
        assert closed == [] and len(opened["warnings"]) == 1
        assert "AB, WHAT?" in opened["warnings"][0]
        assert opened["warnings"][0].startswith("These cannot be read off a marker.")
        # Until they are put right they are left out of what would be saved.
        assert [text for text, _color in dialog.locations()] == ["NEW BABBAGE", "OM-3"]
        dialog.table.item(2, NAME_COLUMN).setText("ABC")
        dialog.table.item(3, NAME_COLUMN).setText("WHAT")
        dialog.table.item(4, NAME_COLUMN).setText("X" * 40)
        dialog.accept()
        assert closed == [QDialog.DialogCode.Accepted.value] and len(opened["warnings"]) == 1
        assert [text for text, _color in dialog.locations()][2:] == ["ABC", "WHAT", "X" * 40]


class TestColorButton:
    def test_it_takes_a_name_or_a_hex_color(self, qapp):
        button = ColorButton("red")
        assert button.color() == "#FA5252" and button.toolTip() == "#FA5252"
        button.set_color("#a1b2c3")
        assert button.color() == "#A1B2C3" and "#A1B2C3" in button.styleSheet()
        button.set_color("sparkly")
        assert button.color() == UNLISTED_DEFAULT

    def test_a_click_asks_for_a_color_and_keeps_it(self, qapp, monkeypatch):
        asked = []

        def get_color(start, parent):
            asked.append(start.name().upper())
            return QColor("#123456")

        monkeypatch.setattr(module, "QColorDialog", SimpleNamespace(getColor=get_color))
        button = ColorButton("red")
        changed = []
        button.changed.connect(lambda: changed.append(True))
        button.click()
        assert asked == ["#FA5252"] and button.color() == "#123456" and changed == [True]
        # A picker closed without a pick changes nothing.
        monkeypatch.setattr(module, "QColorDialog",
                            SimpleNamespace(getColor=lambda start, parent: QColor()))
        button.click()
        assert button.color() == "#123456" and changed == [True]

    def test_it_can_show_another_color_and_keep_its_own(self, qapp):
        button = ColorButton("red")
        button.show_instead("green", "why it shows this")
        assert (button.color(), button.shown_color()) == ("#FA5252", "#40C057")
        assert button.toolTip() == "why it shows this"
        assert "#40C057" in button.styleSheet() and "dashed" in button.styleSheet()
        button.set_color("blue")                            # its own changes underneath
        assert (button.color(), button.shown_color()) == ("#4DABF7", "#40C057")
        button.show_instead(None)
        assert button.shown_color() == "#4DABF7" and button.toolTip() == "#4DABF7"
        assert "dashed" not in button.styleSheet()
