"""The player ID test's editors (placeholders until they have real ones).

``PlayerListsDialog`` edits what ``AppSettings.get_/set_player_lists`` hold:
orgs with a colour, players with an org or a colour of their own, and the
colour of names on no list. It also offers the names read in play that are
on no list yet (``player_id.PastPlayers``), the last session's and everyone
read in any session, to add with a click, and opens a name's RSI page in the
user's own browser. Nothing is looked up by the app: the page is for the
user to read, and what they learn they type in.

``LocationListDialog`` edits the locations to highlight
(``AppSettings.get_/set_location_list``): the text a marker shows and a
colour for it.

The game shows every name in capitals, so a name's cell shows what is typed
in capitals as it is typed, and an org's name is kept that way too.

The dialogs only edit: the Overlay tab saves what they leave when they are
accepted.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QValidator
from PyQt6.QtWidgets import (
    QColorDialog, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QStyledItemDelegate,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from src.utils.i18n import tr
from src.utils.player_id import (
    HANDLE, MAX_PAST_NAMES, PLACE, UNLISTED_DEFAULT, PastPlayers, clean_name, clean_place,
    parse_color,
)

# A citizen's page, for the "Open RSI page" button.
RSI_CITIZEN_URL = "https://robertsspaceindustries.com/citizens/{name}"
# The colours new entries start with, in turn.
NEW_COLORS = ("#40C057", "#FA5252", "#4DABF7", "#FCC419", "#FF922B", "#B197FC", "#F783AC",
              "#3BC9DB")
# The tables' columns: a name first in all of them, then an org's or a
# location's colour, or a player's org and colour.
NAME_COLUMN = 0
ORG_COLOR_COLUMN = 1
PLAYER_ORG_COLUMN, PLAYER_COLOR_COLUMN = 1, 2
LOCATION_COLOR_COLUMN = 1
# How wide a player's org picker is, in pixels.
ORG_PICKER_WIDTH = 140
# Where an org's row keeps the name it had before an edit, so its players
# can follow a rename.
_NAME_BEFORE = Qt.ItemDataRole.UserRole
# Where a row of the names read in play keeps its name (its text may also
# say when the name was last read).
_READ_NAME = Qt.ItemDataRole.UserRole
# How much of a session's name the editor shows: its day, and its day and
# time to the minute ("2026-11-15 14:02:10").
_DAY, _MINUTE = 10, 16


class _CapitalsValidator(QValidator):
    """Turns what is typed into capitals, as the game shows a name."""

    def validate(self, text: str, position: int):  # noqa: D102 (Qt's)
        return QValidator.State.Acceptable, text.upper(), position


class _CapitalsDelegate(QStyledItemDelegate):
    """A name cell's editor: what is typed shows in capitals as it is typed."""

    def createEditor(self, parent, option, index):  # noqa: N802 (Qt's name)
        editor = super().createEditor(parent, option, index)
        if isinstance(editor, QLineEdit):
            editor.setValidator(_CapitalsValidator(editor))
        return editor


def _tidy(table: QTableWidget) -> None:
    """The look and the name column's capitals the editors' tables share."""
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(NAME_COLUMN, QHeaderView.ResizeMode.Stretch)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setItemDelegateForColumn(NAME_COLUMN, _CapitalsDelegate(table))


def _remove_selected_rows(table: QTableWidget) -> None:
    """Remove every selected row, or the row the user is on."""
    rows = sorted({index.row() for index in table.selectedIndexes()}, reverse=True)
    if not rows and table.currentRow() >= 0:
        rows = [table.currentRow()]
    for row in rows:
        table.removeRow(row)


class ColorButton(QPushButton):
    """A button that shows a colour and lets the user pick another. It can
    show another colour in place of its own (a player under an org shows the
    org's), which it keeps for later."""

    # The user picked another colour.
    changed = pyqtSignal()

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._color = UNLISTED_DEFAULT
        self._instead: Optional[str] = None
        self._instead_hint = ""
        self.set_color(color)
        self.clicked.connect(self._pick)

    def color(self) -> str:
        """Its own colour, also while it shows another."""
        return self._color

    def shown_color(self) -> str:
        return self._instead or self._color

    def set_color(self, color: str) -> None:
        self._color = parse_color(color) or UNLISTED_DEFAULT
        self._restyle()

    def show_instead(self, color: Optional[str], hint: str = "") -> None:
        """Show *color* in place of its own, with *hint* as the tooltip.
        None shows its own again."""
        self._instead = parse_color(color) if color else None
        self._instead_hint = hint
        self._restyle()

    def _restyle(self) -> None:
        border = "1px dashed #AAAAAA" if self._instead else "1px solid #555555"
        self.setStyleSheet(f"background-color: {self.shown_color()}; border: {border}; "
                           f"min-width: 44px; min-height: 16px;")
        self.setToolTip(self._instead_hint if self._instead else self._color)

    def _pick(self) -> None:
        picked = QColorDialog.getColor(QColor(self._color), self)
        if picked.isValid():
            self.set_color(picked.name())
            self.changed.emit()


class _EditorDialog(QDialog):
    """What the two editors share: Enter ends a cell's edit, and must not
    also close the dialog."""

    def keyPressEvent(self, event):  # noqa: N802 (Qt's name)
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            return
        super().keyPressEvent(event)


class PlayerListsDialog(_EditorDialog):
    """Edits the lists. ``lists()`` is what to save once it is accepted, and
    ``past_cleared()`` says whether the record of past players is to be
    emptied. *past* is that record as the settings hold it."""

    def __init__(self, data: dict, past, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("overlay.player_lists_title"))
        self.resize(820, 620)
        data = data if isinstance(data, dict) else {}
        layout = QVBoxLayout(self)
        intro = QLabel(tr("overlay.player_lists_intro"))
        intro.setWordWrap(True)
        layout.addWidget(intro)

        tables = QHBoxLayout()
        layout.addLayout(tables, 1)

        orgs_box = QVBoxLayout()
        tables.addLayout(orgs_box, 2)
        orgs_box.addWidget(QLabel(tr("overlay.player_lists_orgs")))
        self.orgs = QTableWidget(0, 2)
        self.orgs.setHorizontalHeaderLabels([tr("overlay.player_lists_org"),
                                             tr("overlay.player_lists_color")])
        _tidy(self.orgs)
        self.orgs.itemChanged.connect(self._orgs_changed)
        orgs_box.addWidget(self.orgs)
        row = QHBoxLayout()
        self.add_org_btn = QPushButton(tr("overlay.player_lists_add_org"))
        self.add_org_btn.clicked.connect(lambda: self.add_org())
        self.remove_org_btn = QPushButton(tr("overlay.player_lists_remove"))
        self.remove_org_btn.clicked.connect(lambda: self._remove_selected(self.orgs))
        row.addWidget(self.add_org_btn)
        row.addWidget(self.remove_org_btn)
        row.addStretch()
        orgs_box.addLayout(row)

        players_box = QVBoxLayout()
        tables.addLayout(players_box, 3)
        players_box.addWidget(QLabel(tr("overlay.player_lists_players")))
        self.players = QTableWidget(0, 3)
        self.players.setHorizontalHeaderLabels([tr("overlay.player_lists_player"),
                                                tr("overlay.player_lists_org"),
                                                tr("overlay.player_lists_color")])
        _tidy(self.players)
        # Room for "(own color)" and an org's name beside the picker's arrow.
        self.players.setColumnWidth(PLAYER_ORG_COLUMN, ORG_PICKER_WIDTH)
        self.players.itemChanged.connect(self._player_named)
        players_box.addWidget(self.players)
        row = QHBoxLayout()
        self.add_player_btn = QPushButton(tr("overlay.player_lists_add_player"))
        self.add_player_btn.clicked.connect(lambda: self.add_player())
        self.remove_player_btn = QPushButton(tr("overlay.player_lists_remove"))
        self.remove_player_btn.clicked.connect(lambda: self._remove_selected(self.players))
        self.open_player_btn = QPushButton(tr("overlay.player_lists_open_rsi"))
        self.open_player_btn.setToolTip(tr("overlay.player_lists_open_rsi_hint"))
        self.open_player_btn.clicked.connect(self._open_selected_player)
        row.addWidget(self.add_player_btn)
        row.addWidget(self.remove_player_btn)
        row.addWidget(self.open_player_btn)
        row.addStretch()
        players_box.addLayout(row)

        # The names read in play: the last session's on the left, everyone
        # read in any session on the right.
        read = QHBoxLayout()
        layout.addLayout(read)
        seen_box = QVBoxLayout()
        read.addLayout(seen_box, 1)
        # Both headings wrap, so two long ones side by side do not force the
        # editor wide.
        self.seen_label = QLabel()
        self.seen_label.setWordWrap(True)
        seen_box.addWidget(self.seen_label)
        self.seen = self._read_list()
        seen_box.addWidget(self.seen)
        past_box = QVBoxLayout()
        read.addLayout(past_box, 1)
        past_label = QLabel(tr("overlay.player_lists_past"))
        past_label.setWordWrap(True)
        past_box.addWidget(past_label)
        self.past = self._read_list()
        self.past.setToolTip(tr("overlay.player_lists_past_hint", count=MAX_PAST_NAMES))
        past_box.addWidget(self.past)
        row = QHBoxLayout()
        self.add_seen_btn = QPushButton(tr("overlay.player_lists_add_seen"))
        self.add_seen_btn.clicked.connect(self._add_seen)
        self.open_seen_btn = QPushButton(tr("overlay.player_lists_open_rsi"))
        self.open_seen_btn.setToolTip(tr("overlay.player_lists_open_rsi_hint"))
        self.open_seen_btn.clicked.connect(self._open_selected_seen)
        self.clear_past_btn = QPushButton(tr("overlay.player_lists_clear_past"))
        self.clear_past_btn.setToolTip(tr("overlay.player_lists_clear_past_hint"))
        self.clear_past_btn.clicked.connect(self._clear_past)
        row.addWidget(self.add_seen_btn)
        row.addWidget(self.open_seen_btn)
        row.addStretch()
        row.addWidget(self.clear_past_btn)
        layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel(tr("overlay.player_lists_unlisted")))
        self.unlisted = ColorButton(str(data.get("unlisted", "")))
        row.addWidget(self.unlisted)
        row.addStretch()
        layout.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        for entry in data.get("orgs") if isinstance(data.get("orgs"), list) else []:
            if isinstance(entry, (list, tuple)) and len(entry) == 2:
                self.add_org(str(entry[0]), str(entry[1]))
        for entry in data.get("players") if isinstance(data.get("players"), list) else []:
            if isinstance(entry, (list, tuple)) and len(entry) == 3:
                self.add_player(str(entry[0]), str(entry[1]), str(entry[2]))
        self._past_cleared = False
        self._show_read_names(PastPlayers.from_data(past))

    @staticmethod
    def _read_list() -> QListWidget:
        names = QListWidget()
        names.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        names.setMaximumHeight(140)
        return names

    # -- orgs -----------------------------------------------------------

    def add_org(self, name: str = "", color: str = "") -> None:
        name = clean_name(name)
        row = self.orgs.rowCount()
        item = QTableWidgetItem(name)
        item.setData(_NAME_BEFORE, name)
        self.orgs.blockSignals(True)
        self.orgs.insertRow(row)
        self.orgs.setItem(row, NAME_COLUMN, item)
        self.orgs.blockSignals(False)
        button = ColorButton(color or NEW_COLORS[row % len(NEW_COLORS)])
        button.changed.connect(self._orgs_changed)
        self.orgs.setCellWidget(row, ORG_COLOR_COLUMN, button)
        self._orgs_changed()
        if not name:
            self.orgs.setCurrentCell(row, NAME_COLUMN)
            self.orgs.editItem(item)

    def _org_rows(self) -> list:
        """(name, colour) of each org with a name, each name once."""
        rows, taken = [], set()
        for row in range(self.orgs.rowCount()):
            item = self.orgs.item(row, NAME_COLUMN)
            name = clean_name(item.text()) if item is not None else ""
            if name and name not in taken:
                taken.add(name)
                rows.append((name, self.orgs.cellWidget(row, ORG_COLOR_COLUMN).color()))
        return rows

    def _orgs_changed(self, item=None) -> None:
        """An org was added, renamed, recoloured or removed: every player's
        org picker gets the new names, and a player under an org shows its
        colour. A player stays under an org through its rename, and goes
        back to a colour of their own when their org is removed. An org's
        name is kept in capitals, however it was set."""
        renamed = {}
        if item is not None and item.column() == NAME_COLUMN:
            before, now = str(item.data(_NAME_BEFORE) or ""), clean_name(item.text())
            if before and now:
                renamed[before] = now
            self.orgs.blockSignals(True)
            if item.text() != now:
                item.setText(now)
            item.setData(_NAME_BEFORE, now)
            self.orgs.blockSignals(False)
        names = [name for name, _color in self._org_rows()]
        for row in range(self.players.rowCount()):
            picker = self.players.cellWidget(row, PLAYER_ORG_COLUMN)
            if picker is None:
                continue
            pick = picker.currentData() or ""
            self._fill_org_picker(picker, names, renamed.get(pick, pick))
            self._sync_player_color(row)

    # -- players --------------------------------------------------------

    def add_player(self, name: str = "", org: str = "", color: str = "") -> None:
        row = self.players.rowCount()
        self.players.insertRow(row)
        item = QTableWidgetItem(clean_name(name))
        self.players.setItem(row, NAME_COLUMN, item)
        picker = QComboBox()
        self._fill_org_picker(picker, [n for n, _color in self._org_rows()], org)
        picker.currentIndexChanged.connect(lambda _index, p=picker: self._picker_changed(p))
        self.players.setCellWidget(row, PLAYER_ORG_COLUMN, picker)
        self.players.setCellWidget(row, PLAYER_COLOR_COLUMN,
                                   ColorButton(color or NEW_COLORS[1]))
        self._sync_player_color(row)
        if not name:
            self.players.setCurrentCell(row, NAME_COLUMN)
            self.players.editItem(item)

    @staticmethod
    def _fill_org_picker(picker: QComboBox, names: list, pick: str = None) -> None:
        if pick is None:
            pick = picker.currentData() or ""
        pick = clean_name(pick)
        picker.blockSignals(True)
        picker.clear()
        picker.addItem(tr("overlay.player_lists_own_color"), "")
        chosen = 0
        for name in names:
            picker.addItem(name, name)
            if name == pick:
                chosen = picker.count() - 1
        picker.setCurrentIndex(chosen)
        picker.blockSignals(False)

    def _picker_changed(self, picker: QComboBox) -> None:
        for row in range(self.players.rowCount()):
            if self.players.cellWidget(row, PLAYER_ORG_COLUMN) is picker:
                self._sync_player_color(row)

    def _sync_player_color(self, row: int) -> None:
        """A player under an org takes the org's colour: their colour button
        shows it and is only live while they have no org."""
        picker = self.players.cellWidget(row, PLAYER_ORG_COLUMN)
        button = self.players.cellWidget(row, PLAYER_COLOR_COLUMN)
        if picker is None or button is None:
            return
        org = picker.currentData() or ""
        colors = dict(self._org_rows())
        button.setEnabled(not org)
        button.show_instead(colors.get(org) if org else None,
                            tr("overlay.player_lists_org_color_hint"))

    def _player_named(self, item) -> None:
        """A name is matched as its tag shows it, in capitals, so that is how
        the list keeps it, however it was set."""
        if item.column() == NAME_COLUMN and item.text() != clean_name(item.text()):
            self.players.blockSignals(True)
            item.setText(clean_name(item.text()))
            self.players.blockSignals(False)

    def _player_rows(self) -> list:
        """(name, org, colour) of each player row with a name, each name once."""
        rows, taken = [], set()
        for row in range(self.players.rowCount()):
            item = self.players.item(row, NAME_COLUMN)
            name = clean_name(item.text()) if item is not None else ""
            if name and name not in taken:
                taken.add(name)
                org = self.players.cellWidget(row, PLAYER_ORG_COLUMN).currentData() or ""
                rows.append((name, org,
                             self.players.cellWidget(row, PLAYER_COLOR_COLUMN).color()))
        return rows

    # -- names read in play ------------------------------------------------

    def _show_read_names(self, past: PastPlayers) -> None:
        """Fill the two lists of names read in play with the ones that are
        on no list: the last session's, and everyone, each with the day it
        was last read."""
        listed = {name for name, _org, _color in self._player_rows()}
        self.seen.clear()
        self.past.clear()
        for name in past.last_session():
            if name not in listed:
                self._add_read_name(self.seen, name, name)
        for name, session in past.everyone():
            if name not in listed:
                self._add_read_name(self.past, name, f"{name}    {session[:_DAY]}".rstrip())
        self.seen_label.setText(tr("overlay.player_lists_seen", when=past.session[:_MINUTE])
                                if past.session else tr("overlay.player_lists_seen_none"))

    @staticmethod
    def _add_read_name(names: QListWidget, name: str, text: str) -> None:
        item = QListWidgetItem(text)
        item.setData(_READ_NAME, name)
        names.addItem(item)

    def _selected_read_names(self) -> list:
        """The names picked in the two lists, the last session's first, each once."""
        picked = []
        for names in (self.seen, self.past):
            for item in names.selectedItems():
                if item.data(_READ_NAME) not in picked:
                    picked.append(item.data(_READ_NAME))
        return picked

    def _add_seen(self) -> None:
        """Put the picked names on the players list. A name that is listed
        leaves both lists of names read."""
        for name in self._selected_read_names():
            self.add_player(name)
            for names in (self.seen, self.past):
                for row in reversed(range(names.count())):
                    if names.item(row).data(_READ_NAME) == name:
                        names.takeItem(row)

    def _open_selected_seen(self) -> None:
        for name in self._selected_read_names()[:1]:
            self._open_rsi_page(name)

    def _clear_past(self) -> None:
        """Empty both lists of names read. The record itself goes when the
        dialog is accepted (``past_cleared``)."""
        self._past_cleared = True
        self._show_read_names(PastPlayers())

    def past_cleared(self) -> bool:
        """Whether the record of past players is to be emptied."""
        return self._past_cleared

    def _open_selected_player(self) -> None:
        row = self.players.currentRow()
        item = self.players.item(row, NAME_COLUMN) if row >= 0 else None
        if item is not None and clean_name(item.text()):
            self._open_rsi_page(clean_name(item.text()))

    def _open_rsi_page(self, name: str) -> None:
        """Open a name's RSI page in the user's own browser."""
        if HANDLE.match(name):
            QDesktopServices.openUrl(QUrl(RSI_CITIZEN_URL.format(name=name)))

    # -- result ----------------------------------------------------------

    def _remove_selected(self, table: QTableWidget) -> None:
        _remove_selected_rows(table)
        if table is self.orgs:
            self._orgs_changed()

    def bad_names(self) -> list:
        """Player names that cannot be a name tag (a space, a symbol)."""
        return [name for name, _org, _color in self._player_rows() if not HANDLE.match(name)]

    def lists(self) -> dict:
        """The lists as edited, in the shape the settings keep."""
        return {
            "orgs": [[name, color] for name, color in self._org_rows()],
            "players": [[name, org, color] for name, org, color in self._player_rows()
                        if HANDLE.match(name)],
            "unlisted": self.unlisted.color(),
        }

    def accept(self) -> None:  # noqa: D102 (Qt's)
        bad = self.bad_names()
        if bad:
            QMessageBox.warning(self, tr("overlay.player_lists_title"),
                                tr("overlay.player_lists_bad_names", names=", ".join(bad)))
            return
        super().accept()


class LocationListDialog(_EditorDialog):
    """Edits the locations to highlight: the text a marker shows, in
    capitals, and a colour. ``locations()`` is what to save once it is
    accepted. *data* is the list as the settings hold it."""

    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("overlay.locations_title"))
        self.resize(480, 460)
        layout = QVBoxLayout(self)
        intro = QLabel(tr("overlay.locations_intro"))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([tr("overlay.locations_location"),
                                              tr("overlay.player_lists_color")])
        _tidy(self.table)
        self.table.itemChanged.connect(self._named)
        layout.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.add_btn = QPushButton(tr("overlay.locations_add"))
        self.add_btn.clicked.connect(lambda: self.add_location())
        self.remove_btn = QPushButton(tr("overlay.player_lists_remove"))
        self.remove_btn.clicked.connect(lambda: _remove_selected_rows(self.table))
        row.addWidget(self.add_btn)
        row.addWidget(self.remove_btn)
        row.addStretch()
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        for entry in data if isinstance(data, list) else []:
            if isinstance(entry, (list, tuple)) and len(entry) == 2:
                self.add_location(str(entry[0]), str(entry[1]))

    def add_location(self, text: str = "", color: str = "") -> None:
        row = self.table.rowCount()
        item = QTableWidgetItem(clean_place(text))
        self.table.blockSignals(True)
        self.table.insertRow(row)
        self.table.setItem(row, NAME_COLUMN, item)
        self.table.blockSignals(False)
        self.table.setCellWidget(row, LOCATION_COLOR_COLUMN,
                                 ColorButton(color or NEW_COLORS[row % len(NEW_COLORS)]))
        if not text:
            self.table.setCurrentCell(row, NAME_COLUMN)
            self.table.editItem(item)

    def _named(self, item) -> None:
        """A location is matched as its marker shows it: capitals, one
        space between words. That is how the list keeps it."""
        if item.column() == NAME_COLUMN and item.text() != clean_place(item.text()):
            self.table.blockSignals(True)
            item.setText(clean_place(item.text()))
            self.table.blockSignals(False)

    def _rows(self) -> list:
        """(text, colour) of each row with a text, each text once."""
        rows, taken = [], set()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, NAME_COLUMN)
            text = clean_place(item.text()) if item is not None else ""
            if text and text not in taken:
                taken.add(text)
                rows.append((text, self.table.cellWidget(row, LOCATION_COLOR_COLUMN).color()))
        return rows

    def bad_names(self) -> list:
        """Texts that cannot be read off a marker (too short, a symbol)."""
        return [text for text, _color in self._rows() if not PLACE.match(text)]

    def locations(self) -> list:
        """The list as edited, in the shape the settings keep."""
        return [[text, color] for text, color in self._rows() if PLACE.match(text)]

    def accept(self) -> None:  # noqa: D102 (Qt's)
        bad = self.bad_names()
        if bad:
            QMessageBox.warning(self, tr("overlay.locations_title"),
                                tr("overlay.locations_bad_names", names=", ".join(bad)))
            return
        super().accept()
