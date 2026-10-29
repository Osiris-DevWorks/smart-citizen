"""QAbstractTableModel for the localization strings table.

Replaces the old QTableWidget populate_table() approach. The model provides data
on-demand for visible rows only, making table population effectively instant
regardless of entry count. Sorting is done entirely in Python (via sort()
override) to avoid the massive overhead of Qt's per-comparison lessThan()
virtual method calls across the Python/C++ boundary.
"""

import re as _re
from typing import Optional

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, pyqtSlot
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication

from src.models.string_model import StringEntry, is_favoritable_ship
from src.parser.ini_parser import status_without_override
from src.utils.i18n import tr
from src.utils.owned_items import normalize_item_name
from src.utils.ship_sort_prefix import get_order, set_order

_OWNED_GOLD = QColor("#FFD700")
_OWNED_GREY = QColor("#666666")

# ---------------------------------------------------------------------------
# Column constants
# ---------------------------------------------------------------------------
COL_CATEGORY = 0
COL_KEY = 1
COL_DEFAULT = 2
COL_CURRENT = 3
COL_STAR = 4
COL_ORDER = 5
COL_CUSTOM = 6
COL_STATUS = 7
COL_OWNED = 8   # #157: "owned blueprint" star, shown on craftable-blueprint item rows
NUM_COLUMNS = 9

_HEADER_KEYS = [
    "strings_tab.col_category",
    "strings_tab.col_key",
    "strings_tab.col_default_value",
    "strings_tab.col_current_value",
    "strings_tab.col_star",
    "strings_tab.col_order",
    "strings_tab.col_custom_value",
    "strings_tab.col_status",
    "strings_tab.col_owned",
]

# ---------------------------------------------------------------------------
# Status colours
# ---------------------------------------------------------------------------
_STATUS_COLORS = {
    "Modified": QColor("#4CAF50"),    # green — user-customized
    "Enhanced": QColor("#2196F3"),    # blue — Smart Citizen enhancement pipeline
    "Unmodified": QColor("#999999"),  # grey — stock value, unchanged
    "New": QColor("#FF9800"),          # orange — discovered from XML, not in base.ini
}
_DEFAULT_STATUS_COLOR = QColor("black")

_FAV_GOLD = QColor("#FFD700")
_FAV_GREY = QColor("#666666")
_FAV_BG_DARK = QColor("#3a3000")   # deep gold-brown for dark theme
_FAV_BG_LIGHT = QColor("#FFF4C4")  # soft pale gold for light theme


def _compute_fav_bg() -> QColor:
    from src.utils.settings import AppSettings
    from src.gui.theme import THEME_LIGHT
    return _FAV_BG_LIGHT if AppSettings.get_theme() == THEME_LIGHT else _FAV_BG_DARK


def status_color(status: str) -> QColor:
    return _STATUS_COLORS.get(status, _DEFAULT_STATUS_COLOR)


# ---------------------------------------------------------------------------
# Grouped-sort helpers (moved from main_window.py)
# ---------------------------------------------------------------------------
_ITEM_PREFIX_RE = _re.compile(r'^(item_)(Name|Desc|name|desc)(.*)', _re.IGNORECASE)
_VEHICLE_PREFIX_RE = _re.compile(r'^(vehicle_)(Name|Desc)(.*)', _re.IGNORECASE)
_MISSION_SUFFIX_RE = _re.compile(
    r'^(.*?)_(title|desc|content)(_.+)?$',
    _re.IGNORECASE,
)
# Commodity keys: items_commodities_X (name) / items_commodities_X_desc or _des (description)
_COMMODITY_RE = _re.compile(
    r'^(items_commodities_\w+?)(?:_(desc?|description))?$',
    _re.IGNORECASE,
)


def _group_sort_key(key: str) -> tuple[str, int]:
    """Return (group_key, sub_order) for grouped sorting."""
    m = _ITEM_PREFIX_RE.match(key)
    if m:
        marker = m.group(2).lower()
        content = m.group(3)
        sub = 0 if marker == "name" else 1
        return (f"item_{content}".lower(), sub)

    m = _VEHICLE_PREFIX_RE.match(key)
    if m:
        marker = m.group(2).lower()
        content = m.group(3)
        sub = 0 if marker == "name" else 1
        return (f"vehicle_{content}".lower(), sub)

    m = _COMMODITY_RE.match(key)
    if m:
        group = m.group(1).lower()
        sub = 1 if m.group(2) else 0  # desc/des suffix → 1, name (no suffix) → 0
        return (group, sub)

    m = _MISSION_SUFFIX_RE.match(key)
    if m:
        prefix = m.group(1)
        marker = m.group(2).lower()
        suffix = m.group(3) or ""
        sub = 0 if marker == "title" else 1
        return (f"{prefix}{suffix}".lower(), sub)

    return (key.lower(), 0)


# ---------------------------------------------------------------------------
# Column key-function factories for sort()
# ---------------------------------------------------------------------------
def _make_sort_key(entries, default_values, sort_keys, col, grouped, favorite_prefix,
                   owned_items=None, bp_item_names=None, enclosings=None):
    """Return a key function for sorted() given the column and grouped-sort state."""
    owned_items = owned_items or set()
    bp_item_names = bp_item_names or set()
    if col == COL_KEY and grouped:
        return lambda idx: sort_keys[idx]
    if col == COL_CATEGORY:
        return lambda idx: entries[idx].category.lower()
    if col == COL_KEY:
        return lambda idx: entries[idx].key.lower()
    if col == COL_DEFAULT:
        return lambda idx: default_values.get(entries[idx].key, "").lower()
    if col == COL_CURRENT:
        return lambda idx: entries[idx].original_value.lower()
    if col == COL_CUSTOM:
        return lambda idx: entries[idx].custom_value.lower()
    if col == COL_STATUS:
        return lambda idx: entries[idx].status.lower()
    if col == COL_OWNED:
        # Owned = a blueprint item the user has marked owned (the gold ★).
        # Primary key 0 for owned, 1 otherwise → ascending floats owned rows to
        # the top, like favorites; the header arrow flips it. Tie-break by key
        # so ordering within each group is stable. (#189)
        def owned_key(idx):
            e = entries[idx]
            stock = default_values.get(e.key) or None
            name = normalize_item_name(e.custom_value or e.original_value, enclosings, stock)
            is_owned = name in bp_item_names and name in owned_items
            return (0 if is_owned else 1, e.key.lower())
        return owned_key
    if col == COL_STAR:
        # Favorite = Ship with the configured prefix on its custom_value.
        # Primary key 0 for favorites, 1 for non-favorites → ascending puts
        # favorites at top. Tie-break by entry key so ordering within each
        # group is stable.
        def fav_key(idx):
            e = entries[idx]
            is_fav = is_favoritable_ship(e) and e.custom_value.startswith(
                favorite_prefix
            )
            return (0 if is_fav else 1, e.key.lower())
        return fav_key
    if col == COL_ORDER:
        # Sort order = the two-digit token on a Ship's custom_value. Assigned
        # ships first (ascending by number), unassigned/non-ships after;
        # tie-break by key so ordering within each group is stable.
        def order_key(idx):
            e = entries[idx]
            order = (
                get_order(e.custom_value, favorite_prefix)
                if is_favoritable_ship(e) else ""
            )
            return (0 if order else 1, order, e.key.lower())
        return order_key
    # unknown — fall back to key
    return lambda idx: entries[idx].key.lower()


# ---------------------------------------------------------------------------
# Source model
# ---------------------------------------------------------------------------
class StringTableModel(QAbstractTableModel):
    """Model backing the localization strings QTableView.

    Holds a reference to the full entries list and an index array of which
    entries are currently visible (after filtering). The view only asks for
    data for rows that are on screen, so even 100k entries are ~instant.

    Sorting is handled by overriding sort() to use Python's sorted(), which
    is dramatically faster than Qt's per-comparison lessThan() virtual calls.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: list[StringEntry] = []
        self._default_values: dict[str, str] = {}
        self._filtered_indices: list[int] = []
        self._reverse_index: dict[int, int] = {}  # entry_idx → model row
        self._favorite_prefix: str = "*"
        self._sort_keys: list[tuple[str, int]] = []  # pre-computed per entry
        self._grouped_sort: bool = False
        self._sort_column: int = COL_KEY
        self._sort_order: Qt.SortOrder = Qt.SortOrder.AscendingOrder
        # #157: item names appearing in any POTENTIAL BLUEPRINTS list (the rows
        # that get an Owned star), and the user's owned set. Both normalized.
        self._bp_item_names: set[str] = set()
        self._owned_items: set[str] = set()
        # #352: the Tag Builder enclosing pair(s) currently configured, so the
        # Owned-star matching (_owned_name) strips the right style. None until
        # set_owned_state() runs at least once; normalize_item_name treats
        # None as its own Square-only default.
        self._enclosings = None
        # Cached values recomputed only on theme/language change, not per-paint.
        self._header_labels: list[str] = [tr(k) for k in _HEADER_KEYS]
        self._fav_bg: QColor = _compute_fav_bg()
        app = QApplication.instance()
        if app is not None:
            app.paletteChanged.connect(self._on_palette_changed)

    # -- bulk setters -------------------------------------------------------

    def set_data_source(
        self,
        entries: list[StringEntry],
        default_values: dict[str, str],
        favorite_prefix: str,
        sort_keys: list[tuple[str, int]] | None = None,
    ) -> None:
        """Replace the entire dataset (called after file loading).

        Args:
            sort_keys: Pre-computed group sort keys (one per entry). If None,
                       computed here on the main thread as a fallback.
        """
        self.beginResetModel()
        self._entries = entries
        self._default_values = default_values
        self._favorite_prefix = favorite_prefix
        self._filtered_indices = list(range(len(entries)))
        self._sort_keys = sort_keys if sort_keys is not None else [_group_sort_key(e.key) for e in entries]
        self._rebuild_reverse_index()
        self.endResetModel()

    def set_filtered_indices(self, indices: list[int]) -> None:
        """Apply a new filter result, re-sorting to maintain current sort order."""
        self.layoutAboutToBeChanged.emit()
        try:
            self._filtered_indices = indices
            self._apply_sort()
            self._rebuild_reverse_index()
        finally:
            self.layoutChanged.emit()

    def refresh_favorite_prefix(self, prefix: str) -> None:
        self.beginResetModel()
        self._favorite_prefix = prefix
        self.endResetModel()

    def set_grouped_sort(self, enabled: bool) -> None:
        self._grouped_sort = enabled

    def set_owned_state(self, bp_item_names: set, owned_items: set, enclosings=None) -> None:
        """#157: set which item names are blueprint items (eligible for the
        Owned star) and which are currently owned. Triggers a full refresh.

        ``enclosings`` is the set of (open, close) Tag Builder delimiter
        pairs currently configured (#352) -- see
        ``owned_items.enclosings_from_tag_configs``. Defaults to None
        (Square only), matching this method's original behavior."""
        self.beginResetModel()
        self._bp_item_names = bp_item_names or set()
        self._owned_items = owned_items or set()
        self._enclosings = enclosings
        self.endResetModel()

    def _owned_name(self, entry: StringEntry) -> str:
        """Normalized display name used to match an entry against blueprint
        bullet names (the row's effective value, tag-stripped).

        Passes the entry's stock (pre-Tag-Builder) value, when known, so a
        "None (space only)" enclosing tag resolves authoritatively via diff
        rather than a guess (#352) -- see normalize_item_name's docstring.
        """
        stock = self._default_values.get(entry.key) or None
        return normalize_item_name(
            entry.custom_value or entry.original_value, self._enclosings, stock
        )

    def _is_bp_item(self, entry: StringEntry) -> bool:
        """True if this row names an item that appears in a blueprint list."""
        return bool(self._bp_item_names) and self._owned_name(entry) in self._bp_item_names

    # -- entry access helpers -----------------------------------------------

    def entry_index_for_row(self, row: int) -> int:
        """Map a model row to an index into self._entries."""
        return self._filtered_indices[row]

    def entry_for_row(self, row: int) -> Optional[StringEntry]:
        """Return the entry for a model row, or None if the row is out of
        range. The view can briefly query stale rows after a failed/empty
        load (first run before extraction, when the loader raises "No
        sources configured"); an unguarded index there crashed with
        IndexError (issue #110)."""
        if 0 <= row < len(self._filtered_indices):
            return self._entries[self._filtered_indices[row]]
        return None

    def source_row_for_entry_index(self, entry_idx: int) -> Optional[int]:
        """Reverse lookup: entry index -> model row. O(1) via dict."""
        return self._reverse_index.get(entry_idx)

    def _rebuild_reverse_index(self) -> None:
        self._reverse_index = {idx: row for row, idx in enumerate(self._filtered_indices)}

    # -- QAbstractTableModel interface --------------------------------------

    def rowCount(self, parent=QModelIndex()):
        return len(self._filtered_indices)

    def columnCount(self, parent=QModelIndex()):
        return NUM_COLUMNS

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if 0 <= section < len(self._header_labels):
                return self._header_labels[section]
        return None

    def retranslate(self) -> None:
        """Recompute cached header labels and notify the view."""
        self._header_labels = [tr(k) for k in _HEADER_KEYS]
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, NUM_COLUMNS - 1)

    @pyqtSlot()
    def _on_palette_changed(self) -> None:
        """Recompute fav-row background when the app theme changes."""
        self._fav_bg = _compute_fav_bg()

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        col = index.column()
        if col == COL_CUSTOM:
            return base | Qt.ItemFlag.ItemIsEditable
        if col == COL_STAR:
            entry = self.entry_for_row(index.row())
            if entry is not None and not is_favoritable_ship(entry):
                return Qt.ItemFlag.ItemIsEnabled  # not selectable
        if col == COL_ORDER:
            entry = self.entry_for_row(index.row())
            if entry is not None and is_favoritable_ship(entry):
                return base | Qt.ItemFlag.ItemIsEditable
            return Qt.ItemFlag.ItemIsEnabled  # non-name rows: shown, not editable
        if col == COL_OWNED:
            # Read-only indicator: ownership is managed by the Blueprints
            # shuttle on the Enhancements tab, so the cell is never selectable
            # or editable (blueprint rows show the star, others are blank).
            return Qt.ItemFlag.ItemIsEnabled
        return base

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        row = index.row()
        col = index.column()
        entry = self.entry_for_row(row)
        if entry is None:
            return None
        prefix = self._favorite_prefix

        # -- display text ---------------------------------------------------
        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_CATEGORY:
                return entry.category
            if col == COL_KEY:
                return entry.key
            if col == COL_DEFAULT:
                return self._default_values.get(entry.key, "")
            if col == COL_CURRENT:
                return entry.original_value
            if col == COL_STAR:
                if not is_favoritable_ship(entry):
                    return ""
                return "\u2605" if entry.custom_value.startswith(prefix) else "\u2606"
            if col == COL_ORDER:
                if not is_favoritable_ship(entry):
                    return ""
                return get_order(entry.custom_value, prefix)
            if col == COL_CUSTOM:
                return entry.custom_value
            if col == COL_STATUS:
                return entry.status
            if col == COL_OWNED:
                if not self._is_bp_item(entry):
                    return ""
                return "★" if self._owned_name(entry) in self._owned_items else "☆"
            return None

        # -- edit text (populates the inline editor on double-click) --------
        if role == Qt.ItemDataRole.EditRole:
            if col == COL_CUSTOM:
                return entry.custom_value
            if col == COL_ORDER:
                return get_order(entry.custom_value, prefix)
            return None

        # -- entry index (replaces old UserRole on col-0 trick) -------------
        if role == Qt.ItemDataRole.UserRole:
            return self._filtered_indices[row]

        # -- tooltips -------------------------------------------------------
        if role == Qt.ItemDataRole.ToolTipRole:
            if col == COL_STAR:
                if is_favoritable_ship(entry):
                    if entry.custom_value.startswith(prefix):
                        return "Favorite \u2014 click to remove"
                    return "Click to mark as favorite"
                return None
            if col == COL_ORDER:
                if is_favoritable_ship(entry):
                    return "Sort order: click to pick a number for ASOP ordering"
                return None
            if col == COL_OWNED:
                if self._is_bp_item(entry):
                    if self._owned_name(entry) in self._owned_items:
                        return "Owned blueprint — manage ownership in the Enhancements tab's Blueprints list"
                    return "Ownable blueprint — mark it owned in the Enhancements tab's Blueprints list"
                return None
            return self.data(index, Qt.ItemDataRole.DisplayRole)

        # -- foreground colour ----------------------------------------------
        if role == Qt.ItemDataRole.ForegroundRole:
            if col == COL_STAR and is_favoritable_ship(entry):
                return _FAV_GOLD if entry.custom_value.startswith(prefix) else _FAV_GREY
            if col == COL_OWNED and self._is_bp_item(entry):
                return _OWNED_GOLD if self._owned_name(entry) in self._owned_items else _OWNED_GREY
            if col == COL_STATUS:
                return status_color(entry.status)
            return None

        # -- background colour (favorite rows) ------------------------------
        if role == Qt.ItemDataRole.BackgroundRole:
            if is_favoritable_ship(entry) and entry.custom_value.startswith(prefix):
                return self._fav_bg
            return None

        # -- alignment ------------------------------------------------------
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (COL_STAR, COL_ORDER, COL_OWNED):
                return int(Qt.AlignmentFlag.AlignCenter)
            return None

        return None

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole) -> bool:
        """Handle inline editing of the Custom Value and Sort Order columns."""
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        col = index.column()
        if col not in (COL_CUSTOM, COL_ORDER):
            return False

        entry = self.entry_for_row(index.row())
        if entry is None:
            return False

        if col == COL_CUSTOM:
            new_text = str(value)
            if new_text == entry.custom_value:
                return False
            entry.custom_value = new_text
            if not new_text:
                # An emptied cell clears the override: the row reads as a
                # load would show it (#531).
                entry.status = status_without_override(entry, self._default_values)
            else:
                entry.status = "Modified" if new_text != entry.original_value else "Unmodified"
        else:  # COL_ORDER: only ship name rows are editable here (enforced by flags()).
            if not is_favoritable_ship(entry):
                return False
            new_custom = set_order(
                entry.custom_value,
                entry.original_value,
                self._favorite_prefix,
                str(value),
            )
            if new_custom == entry.custom_value:
                return False
            entry.custom_value = new_custom
            # set_order collapses to "" when nothing distinguishes it from
            # stock, so a non-empty value always means Modified.
            entry.status = ("Modified" if entry.custom_value
                            else status_without_override(entry, self._default_values))

        # Notify view that star, order, custom value, and status columns changed
        left = self.index(index.row(), COL_STAR)
        right = self.index(index.row(), COL_STATUS)
        self.dataChanged.emit(left, right)
        return True

    # -- sorting (entirely in Python) ---------------------------------------

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        """Sort by column using Python sorted() — avoids Qt lessThan() overhead.

        Header clicks go through this path and disable grouped sort.
        The Group Sort button calls set_grouped_sort(True) before calling sort().
        """
        self._sort_column = column
        self._sort_order = order
        self.layoutAboutToBeChanged.emit()
        try:
            self._apply_sort()
            self._rebuild_reverse_index()
        finally:
            self.layoutChanged.emit()
        # Reset after applying so subsequent header clicks use normal sort
        self._grouped_sort = False

    def _apply_sort(self) -> None:
        """Sort _filtered_indices in place using current sort column/order."""
        if not self._filtered_indices:
            return
        key_fn = _make_sort_key(
            self._entries, self._default_values, self._sort_keys,
            self._sort_column, self._grouped_sort, self._favorite_prefix,
            self._owned_items, self._bp_item_names, self._enclosings,
        )
        reverse = self._sort_order == Qt.SortOrder.DescendingOrder
        self._filtered_indices.sort(key=key_fn, reverse=reverse)

    # -- targeted refresh ---------------------------------------------------

    def notify_entry_changed(self, entry_idx: int) -> None:
        """Emit dataChanged for the row displaying *entry_idx* (if visible)."""
        source_row = self.source_row_for_entry_index(entry_idx)
        if source_row is not None:
            left = self.index(source_row, 0)
            right = self.index(source_row, NUM_COLUMNS - 1)
            self.dataChanged.emit(left, right)
