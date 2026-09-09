"""Blueprint Tracker tab (#157; split into its own tab in 2.2.x, #222).

A search-filtered shuttle of every item that appears in a mission's
POTENTIAL BLUEPRINTS reward on the left, the items the user owns on the
right, and arrow buttons to move multi-selected items between them. Owned
items get an ``[Owned]`` tag wherever they show up in a mission's potential
blueprint rewards. Originally a section at the bottom of the Enhancements
tab; moved to its own tab (still hosting most of its i18n strings under the
``enhancements.blueprints_*`` namespace — unchanged on purpose, since only
the tab housing it changed, not the strings' meaning).

The available universe is fed in by MainWindow via ``set_blueprint_items``
(it is computed from the loaded mission strings, which this tab can't see).
"""
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from src.gui.enhancements_tab import _NoScrollComboBox
from src.gui.theme import get_button_color
from src.utils.i18n import tr
from src.utils.settings import AppSettings


class _NoWheelComboBox(_NoScrollComboBox):
    """A combo box that never responds to mouse wheel scroll, focused or not.

    _NoScrollComboBox (#197) only ignores the wheel while unfocused, so a
    focused wheel scroll still changes its value — intentional there, but
    wrong for a pure filter dropdown: click Mission/Type/Class/Size/Grade
    once to pick a value, it keeps focus, and later scrolling the page while
    the mouse happens to be over it silently changes the filter instead of
    scrolling (#224). Always ignoring the wheel avoids that trap; still
    inherits _NoScrollComboBox's popup-placement fix.
    """

    def wheelEvent(self, event):  # noqa: N802 (Qt override)
        event.ignore()


def _relabel_details_button(box: QMessageBox, shown_label: str, hidden_label: str) -> None:
    """Rename a QMessageBox's auto-added "Show Details.../Hide Details..."
    button to *shown_label* while collapsed and *hidden_label* while
    expanded.

    setDetailedText() gives every such button the generic Qt-default label,
    which doesn't say what the details actually are (#234 follow-up: a user
    had to click through to discover "Show Details..." meant the skipped-
    blueprint list). Qt has no direct API to set that text at creation time,
    so this finds it by its ActionRole (the role Qt assigns the details
    toggle specifically, distinct from OK/Yes/No) and relabels it after the
    box is otherwise fully configured.

    QMessageBox computes its layout size around the *original* "Show
    Details..." button before this runs, so a longer replacement label
    (confirmed live: "Show Added Blueprints" got clipped to "...w Added
    Blueprints") doesn't widen the dialog on its own. Relying purely on
    layout re-invalidation is timing-sensitive (QMessageBox isn't fully
    laid out until it's actually shown), so this also sets an explicit
    minimum width on the button itself from its own font metrics, sized for
    the longer of the two labels -- a deterministic floor that doesn't
    depend on when Qt gets around to recomputing the rest of the layout.
    Needed for every language here, not just English: several translations
    (e.g. German "Übersprungene Baupläne anzeigen") run longer still.

    Also confirmed live: Qt resets this button's text to its own "Show
    Details.../Hide Details..." on every click (it's the same button
    toggling between expanded/collapsed, and Qt's internal handler rewrites
    the label each time), so a one-time setText() here gets clobbered the
    moment the user clicks it -- and re-applying it synchronously on
    `toggled` still lost the race (confirmed live: label reverted anyway),
    meaning Qt's own reset runs after ours within the same click, not
    before. QTimer.singleShot(0, ...) defers the re-apply to the next
    event-loop iteration, strictly after all of the click's synchronous
    handling (Qt's included) has finished, so it always has the last word
    regardless of internal ordering.

    A first pass picked between the two labels via `btn.isChecked()`, which
    left the button stuck on the shown label forever (confirmed live) --
    Qt's details button is a plain QPushButton, not checkable, so
    isChecked() always returns False no matter how many times it's clicked.
    Tracking the expanded/collapsed state ourselves (a plain bool flipped
    once per click, independent of any Qt button state) fixes that, since
    each click here corresponds 1:1 with Qt's own internal visibility
    toggle.
    """
    for btn in box.buttons():
        if box.buttonRole(btn) == QMessageBox.ButtonRole.ActionRole:
            fm = btn.fontMetrics()
            needed_width = max(
                fm.horizontalAdvance(shown_label), fm.horizontalAdvance(hidden_label)
            ) + 24
            btn.setMinimumWidth(needed_width)

            state = {"expanded": False}

            def _apply_label(btn=btn, state=state, shown_label=shown_label, hidden_label=hidden_label):
                btn.setText(hidden_label if state["expanded"] else shown_label)

            def _on_clicked(_checked=False, state=state, cb=_apply_label):
                state["expanded"] = not state["expanded"]
                QTimer.singleShot(0, cb)

            btn.clicked.connect(_on_clicked)
            _apply_label()
            layout = box.layout()
            if layout is not None:
                layout.invalidate()
                layout.activate()
            box.adjustSize()


class BlueprintTrackerTab(QWidget):
    """Track owned blueprints against mission POTENTIAL BLUEPRINTS rewards."""

    # The owned-blueprint set changed. MainWindow re-weaves [Owned] tags into
    # the strings table and refreshes it.
    owned_items_changed = pyqtSignal()
    # The user clicked "Scan Logs for Owned Blueprints". MainWindow owns the
    # worker/progress-dialog lifecycle (the threading model every other
    # file-scan action in this app follows) and calls back into
    # AppSettings.set_owned_items() + _recompute_owned() on completion,
    # which re-renders this tab the same way any other Owned change does.
    scan_logs_requested = pyqtSignal()
    # The user clicked "Apply Owned Tags". MainWindow re-weaves the [Owned]
    # tag into the loaded strings' blueprint-list bullets so the current
    # Owned set is reflected on demand, without needing to move an item
    # between the two lists first.
    apply_owned_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        # name -> BlueprintItem (or None for a bare name), set by MainWindow.
        # Owned state itself lives in AppSettings (single source of truth).
        self._blueprint_meta: dict = {}
        # #372: every real item name this install knows about, wider than
        # _blueprint_meta's keys -- see set_known_item_names.
        self._known_item_names: set = set()
        # Gates the Apply Owned Tags button, same pattern as the
        # Enhancements tab's Generate Enhancements / Save Tag Changes:
        # disabled until the Owned set changes since the last apply.
        self._owned_dirty = False
        self.setup_ui()

    def setup_ui(self):
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self._title_label = QLabel(tr("blueprint_tracker.title"))
        self._title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(self._title_label)

        self._blueprints_desc_label = QLabel(tr("enhancements.blueprints_desc"))
        self._blueprints_desc_label.setProperty("role", "secondary")
        self._blueprints_desc_label.setStyleSheet("font-size: 11px;")
        self._blueprints_desc_label.setWordWrap(True)
        layout.addWidget(self._blueprints_desc_label)

        # A 4-column grid rather than two independent rows so the bottom
        # row's Export/Import buttons align exactly under Apply Owned Tags
        # (equal column stretch on all 4 columns means Export == Import ==
        # half of Apply Owned Tags each, and together they exactly span its
        # width) -- a plain QHBoxLayout can't guarantee that column
        # alignment across two separate rows the way a shared grid does.
        #
        # Row 0: Scan Logs (cols 0-1) | Apply Owned Tags (cols 2-3) -- always
        # visible regardless of the empty-state gate below, since scanning
        # logs doesn't need mission data loaded, it reads the player's own
        # earned-blueprint history straight from Star Citizen's log files.
        # Row 1: scan-behavior checkboxes (cols 0-1: which channels to cover
        # #268, whether to ignore the watermark #308, whether to run the scan
        # automatically on startup #386, and whether that auto-scan pops the
        # normal summary dialog or just a status bar message -- all four only
        # affecting "Scan Logs for Owned Blueprints") | Export/Import the Owned set
        # (#234, cols 2-3) -- secondary actions, smaller than the primary
        # scan/apply buttons above them, sharing the row since neither
        # checkbox nor export/import needs mission data loaded.
        top_grid = QGridLayout()
        for col in range(4):
            top_grid.setColumnStretch(col, 1)

        self._scan_logs_btn = QPushButton(tr("blueprint_tracker.scan_logs_btn"))
        self._scan_logs_btn.setToolTip(tr("blueprint_tracker.scan_logs_tooltip"))
        self._scan_logs_btn.clicked.connect(self.scan_logs_requested.emit)
        self._scan_logs_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        top_grid.addWidget(self._scan_logs_btn, 0, 0, 1, 2)

        self._apply_owned_btn = QPushButton(tr("blueprint_tracker.apply_owned_tag_btn"))
        self._apply_owned_btn.clicked.connect(self._on_apply_owned_clicked)
        self._apply_owned_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        top_grid.addWidget(self._apply_owned_btn, 0, 2, 1, 2)
        self._set_owned_btn_dirty(False)

        checkboxes_row = QHBoxLayout()

        # #268: also scan whichever of LIVE/HOTFIX isn't the active channel
        # when the user clicks "Scan Logs for Owned Blueprints". Enabled by
        # default; they share the same account progression, so it's cheap
        # coverage most users want. Never covers PTU/EPTU/TECH-PREVIEW: those
        # are separate test builds with their own progression, not the same
        # account history as LIVE/HOTFIX.
        self._scan_other_channels_checkbox = QCheckBox(
            tr("blueprint_tracker.scan_other_channels_checkbox")
        )
        self._scan_other_channels_checkbox.setToolTip(
            tr("blueprint_tracker.scan_other_channels_tooltip")
        )
        self._scan_other_channels_checkbox.setChecked(
            AppSettings.get_scan_other_channels_enabled()
        )
        self._scan_other_channels_checkbox.toggled.connect(
            AppSettings.set_scan_other_channels_enabled
        )
        checkboxes_row.addWidget(self._scan_other_channels_checkbox)

        # #308: force a full rescan back to the scanner's epoch floor,
        # ignoring the saved watermark -- for the rare case a user's owned
        # set drifted (e.g. an accidental unown) and a normal incremental
        # scan won't recover the missing blueprint. One-shot: MainWindow
        # unchecks it once the scan queue finishes, so it doesn't silently
        # keep forcing a full rescan (and the extra time that takes) on
        # every future click. Deliberately not persisted to AppSettings --
        # this isn't a standing preference like the checkbox above.
        self._force_rescan_checkbox = QCheckBox(
            tr("blueprint_tracker.force_rescan_checkbox")
        )
        self._force_rescan_checkbox.setToolTip(
            tr("blueprint_tracker.force_rescan_tooltip")
        )
        checkboxes_row.addWidget(self._force_rescan_checkbox)

        # #386: run "Scan Logs for Owned Blueprints" automatically on every
        # launch instead of only on a manual click. Off by default -- opt-in,
        # since it's an extra background log read on every startup. Reads
        # MainWindow's own scan pipeline (channel queue, watermark, #268
        # multi-channel coverage) unchanged; only the result feedback differs
        # (status bar, not a popup, so it doesn't interrupt every launch).
        self._auto_scan_startup_checkbox = QCheckBox(
            tr("blueprint_tracker.auto_scan_startup_checkbox")
        )
        self._auto_scan_startup_checkbox.setToolTip(
            tr("blueprint_tracker.auto_scan_startup_tooltip")
        )
        self._auto_scan_startup_checkbox.setChecked(
            AppSettings.get_auto_scan_blueprints_enabled()
        )
        self._auto_scan_startup_checkbox.toggled.connect(
            self._on_auto_scan_startup_toggled
        )
        checkboxes_row.addWidget(self._auto_scan_startup_checkbox)

        # #386 follow-up: opt back INTO the manual scan's own popup for the
        # auto-scan too, for anyone who wants the interruption. Off by
        # default, same as the auto-scan checkbox itself -- the status bar
        # message stays the default so a launch that finds something new
        # doesn't surprise everyone who didn't ask for a popup. Only affects
        # the "found new blueprints" case; a quiet run still never pops
        # anything, checkbox or not.
        self._auto_scan_popup_checkbox = QCheckBox(
            tr("blueprint_tracker.auto_scan_popup_checkbox")
        )
        self._auto_scan_popup_checkbox.setToolTip(
            tr("blueprint_tracker.auto_scan_popup_tooltip")
        )
        self._auto_scan_popup_checkbox.setChecked(
            AppSettings.get_auto_scan_show_popup_enabled()
        )
        self._auto_scan_popup_checkbox.toggled.connect(
            AppSettings.set_auto_scan_show_popup_enabled
        )
        # #386 review: this setting has no effect unless auto-scan itself is
        # on -- greyed out (not just documented in the tooltip) so that's
        # visible rather than a silently inert checkbox.
        self._auto_scan_popup_checkbox.setEnabled(
            self._auto_scan_startup_checkbox.isChecked()
        )
        checkboxes_row.addWidget(self._auto_scan_popup_checkbox)
        checkboxes_row.addStretch()
        top_grid.addLayout(checkboxes_row, 1, 0, 1, 2)

        self._export_owned_btn = QPushButton(tr("blueprint_tracker.export_owned_btn"))
        self._export_owned_btn.setToolTip(tr("blueprint_tracker.export_owned_tooltip"))
        self._export_owned_btn.clicked.connect(self._export_owned_blueprints)
        top_grid.addWidget(self._export_owned_btn, 1, 2)

        self._import_owned_btn = QPushButton(tr("blueprint_tracker.import_owned_btn"))
        self._import_owned_btn.setToolTip(tr("blueprint_tracker.import_owned_tooltip"))
        self._import_owned_btn.clicked.connect(self._import_owned_blueprints)
        top_grid.addWidget(self._import_owned_btn, 1, 3)

        layout.addLayout(top_grid)

        # Shown instead of the lists when no blueprint items exist yet (mission
        # enhancements not generated) — the same precondition the stars had.
        self._blueprints_empty_note = QLabel(tr("enhancements.blueprints_empty_note"))
        self._blueprints_empty_note.setProperty("role", "secondary")
        self._blueprints_empty_note.setStyleSheet("font-size: 11px; font-style: italic;")
        self._blueprints_empty_note.setWordWrap(True)
        layout.addWidget(self._blueprints_empty_note)

        self._blueprints_search = QLineEdit()
        self._blueprints_search.setPlaceholderText(
            tr("enhancements.blueprints_search_placeholder")
        )
        self._blueprints_search.setClearButtonEnabled(True)
        self._blueprints_search.textChanged.connect(self._refilter_blueprint_lists)
        layout.addWidget(self._blueprints_search)

        # Display-only toggle (#221): show each item's Tag Builder tag inline
        # instead of the bare name. Matching/filtering/Owned tracking always
        # use the bare name regardless — see BlueprintItem.tagged_name.
        self._blueprints_show_tags = QCheckBox(
            tr("enhancements.blueprints_show_tags_checkbox")
        )
        self._blueprints_show_tags.setChecked(AppSettings.get_blueprint_show_tags())
        self._blueprints_show_tags.toggled.connect(self._on_blueprints_show_tags_toggled)
        layout.addWidget(self._blueprints_show_tags)

        mission_row = QHBoxLayout()
        self._blueprints_mission_label = QLabel(tr("enhancements.blueprints_mission_label"))
        self._blueprints_mission_label.setProperty("role", "secondary")
        mission_row.addWidget(self._blueprints_mission_label)
        self._blueprints_mission_combo = _NoWheelComboBox()
        self._blueprints_mission_combo.addItem(tr("enhancements.blueprints_facet_any"), None)
        self._blueprints_mission_combo.currentIndexChanged.connect(
            self._refilter_blueprint_lists
        )
        mission_row.addWidget(self._blueprints_mission_combo, 1)
        layout.addLayout(mission_row)

        # Component-attribute facets. Each combo's first row is "Any" (data
        # None); the rest are enumerated from the loaded metadata. Attributes
        # exist only for ship components, so the coverage note sets expectations.
        facet_row = QHBoxLayout()
        self._blueprints_facet_combos = {}
        self._blueprints_facet_labels = {}
        for attr, label_key in (
            ("type", "enhancements.blueprints_facet_type"),
            ("cls", "enhancements.blueprints_facet_class"),
            ("size", "enhancements.blueprints_facet_size"),
            ("grade", "enhancements.blueprints_facet_grade"),
        ):
            lbl = QLabel(tr(label_key))
            lbl.setProperty("role", "secondary")
            combo = _NoWheelComboBox()
            combo.addItem(tr("enhancements.blueprints_facet_any"), None)
            combo.currentIndexChanged.connect(self._refilter_blueprint_lists)
            self._blueprints_facet_combos[attr] = combo
            self._blueprints_facet_labels[label_key] = lbl
            facet_row.addWidget(lbl)
            facet_row.addWidget(combo, 1)
        layout.addLayout(facet_row)

        self._blueprints_filter_note = QLabel(tr("enhancements.blueprints_filter_note"))
        self._blueprints_filter_note.setProperty("role", "secondary")
        self._blueprints_filter_note.setStyleSheet("font-size: 10px;")
        self._blueprints_filter_note.setWordWrap(True)
        layout.addWidget(self._blueprints_filter_note)

        lists_row = QHBoxLayout()

        avail_col = QVBoxLayout()
        self._blueprints_available_label = QLabel(
            tr("enhancements.blueprints_available_label")
        )
        avail_col.addWidget(self._blueprints_available_label)
        self._blueprints_available_list = QListWidget()
        self._blueprints_available_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._blueprints_available_list.itemDoubleClicked.connect(
            lambda _it: self._own_selected_blueprints()
        )
        avail_col.addWidget(self._blueprints_available_list)
        lists_row.addLayout(avail_col, 1)

        arrows = QVBoxLayout()
        arrows.addStretch()
        self._blueprints_add_btn = QPushButton("→")  # →
        self._blueprints_add_btn.setToolTip(tr("enhancements.blueprints_add_tooltip"))
        self._blueprints_add_btn.clicked.connect(self._own_selected_blueprints)
        arrows.addWidget(self._blueprints_add_btn)
        self._blueprints_remove_btn = QPushButton("←")  # ←
        self._blueprints_remove_btn.setToolTip(tr("enhancements.blueprints_remove_tooltip"))
        self._blueprints_remove_btn.clicked.connect(self._unown_selected_blueprints)
        arrows.addWidget(self._blueprints_remove_btn)
        arrows.addStretch()
        lists_row.addLayout(arrows)

        owned_col = QVBoxLayout()
        self._blueprints_owned_label = QLabel(
            tr("enhancements.blueprints_owned_label")
        )
        owned_col.addWidget(self._blueprints_owned_label)
        self._blueprints_owned_list = QListWidget()
        self._blueprints_owned_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._blueprints_owned_list.itemDoubleClicked.connect(
            lambda _it: self._unown_selected_blueprints()
        )
        owned_col.addWidget(self._blueprints_owned_list)
        lists_row.addLayout(owned_col, 1)

        layout.addLayout(lists_row, 1)
        layout.addStretch()

        self._render_blueprint_lists()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.viewport().setAutoFillBackground(False)
        content.setAutoFillBackground(False)
        scroll.setWidget(content)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def retranslate_ui(self) -> None:
        """Re-apply tr() to every text-bearing widget after a language switch."""
        self._title_label.setText(tr("blueprint_tracker.title"))
        self._blueprints_desc_label.setText(tr("enhancements.blueprints_desc"))
        self._scan_logs_btn.setText(tr("blueprint_tracker.scan_logs_btn"))
        # #386 review: re-derive from the button's own enabled state rather
        # than a second tracked flag, same as _set_owned_btn_dirty does for
        # _owned_dirty -- correct even if a scan happens to be running when
        # the language switches.
        self.set_scan_logs_enabled(self._scan_logs_btn.isEnabled())
        self._export_owned_btn.setText(tr("blueprint_tracker.export_owned_btn"))
        self._export_owned_btn.setToolTip(tr("blueprint_tracker.export_owned_tooltip"))
        self._import_owned_btn.setText(tr("blueprint_tracker.import_owned_btn"))
        self._import_owned_btn.setToolTip(tr("blueprint_tracker.import_owned_tooltip"))
        self._scan_other_channels_checkbox.setText(
            tr("blueprint_tracker.scan_other_channels_checkbox")
        )
        self._scan_other_channels_checkbox.setToolTip(
            tr("blueprint_tracker.scan_other_channels_tooltip")
        )
        self._force_rescan_checkbox.setText(
            tr("blueprint_tracker.force_rescan_checkbox")
        )
        self._force_rescan_checkbox.setToolTip(
            tr("blueprint_tracker.force_rescan_tooltip")
        )
        self._auto_scan_startup_checkbox.setText(
            tr("blueprint_tracker.auto_scan_startup_checkbox")
        )
        self._auto_scan_startup_checkbox.setToolTip(
            tr("blueprint_tracker.auto_scan_startup_tooltip")
        )
        self._auto_scan_popup_checkbox.setText(
            tr("blueprint_tracker.auto_scan_popup_checkbox")
        )
        self._auto_scan_popup_checkbox.setToolTip(
            tr("blueprint_tracker.auto_scan_popup_tooltip")
        )
        self._apply_owned_btn.setText(tr("blueprint_tracker.apply_owned_tag_btn"))
        self._set_owned_btn_dirty(self._owned_dirty)  # re-applies the right tooltip
        self._blueprints_empty_note.setText(tr("enhancements.blueprints_empty_note"))
        self._blueprints_search.setPlaceholderText(tr("enhancements.blueprints_search_placeholder"))
        self._blueprints_show_tags.setText(tr("enhancements.blueprints_show_tags_checkbox"))
        self._blueprints_mission_label.setText(tr("enhancements.blueprints_mission_label"))
        self._blueprints_filter_note.setText(tr("enhancements.blueprints_filter_note"))
        self._blueprints_available_label.setText(tr("enhancements.blueprints_available_label"))
        self._blueprints_owned_label.setText(tr("enhancements.blueprints_owned_label"))
        self._blueprints_add_btn.setToolTip(tr("enhancements.blueprints_add_tooltip"))
        self._blueprints_remove_btn.setToolTip(tr("enhancements.blueprints_remove_tooltip"))
        for label_key, lbl in self._blueprints_facet_labels.items():
            lbl.setText(tr(label_key))

    @staticmethod
    def _available_blueprints(all_names, owned) -> list:
        """Blueprint items not yet owned, sorted case-insensitively.

        Pure (Qt-free) so the available/owned split is unit-testable. Accepts a
        name iterable or a ``{name: meta}`` mapping (dict keys are the names).
        """
        return sorted(set(all_names) - set(owned), key=str.lower)

    def set_blueprint_items(self, meta) -> None:
        """Receive the blueprint-item metadata from MainWindow.

        *meta* is ``{name: BlueprintItem}`` (a bare name set/list is tolerated
        too — items then carry no filter attributes). Called after every load
        and every owned-set change, so the lists track the loaded strings.
        """
        if isinstance(meta, dict):
            self._blueprint_meta = dict(meta)
        else:
            self._blueprint_meta = {n: None for n in (meta or ())}
        self._populate_filter_combos()
        self._render_blueprint_lists()

    def set_known_item_names(self, names) -> None:
        """Receive the wider "every real item this install knows about" set
        (#372) -- see ``blueprint_meta.known_item_names``. Deliberately not
        the same as ``self._blueprint_meta``'s keys: that's scoped to items
        currently eligible for the Owned star, which excludes anything CIG
        has rotated out of every mission's reward pool this patch. Used only
        to let Import Owned Blueprints recover a foreign-editor-decorated
        name (#372); the narrower ``_blueprint_meta`` set still governs what
        can actually be shown/marked owned.
        """
        self._known_item_names = set(names or ())

    def _facet_value(self, name: str, attr: str):
        """The value of one facet attribute for *name*, or None if unknown."""
        item = self._blueprint_meta.get(name)
        return getattr(item, attr, None) if item is not None else None

    @staticmethod
    def _facet_sort_key(attr: str, value: str):
        """Sort facet values naturally, keeping "Other" pinned last.

        The size facet holds bare numbers ("0", "1", ..., "10") and needs a
        numeric sort — a plain string sort would put "10" before "2". "Other"
        only ever appears as a Type value, so the other facets are unaffected.
        """
        if attr == "size":
            try:
                return (False, int(value))
            except (TypeError, ValueError):
                return (False, value)
        return (value == "Other", value)

    def _populate_filter_combos(self) -> None:
        """Refill the mission and facet combos with the values present in the
        metadata, preserving each current selection where it still exists."""
        # Mission combo: the union of every item's mission names.
        missions = sorted({
            m for item in self._blueprint_meta.values()
            for m in getattr(item, "missions", ()) or ()
        }, key=str.lower)
        self._refill_combo(self._blueprints_mission_combo, missions)
        # Scalar facet combos.
        for attr, combo in self._blueprints_facet_combos.items():
            values = sorted({
                v for name in self._blueprint_meta
                if (v := self._facet_value(name, attr)) is not None
            }, key=lambda v: self._facet_sort_key(attr, v))
            self._refill_combo(combo, values)

    @staticmethod
    def _refill_combo(combo, values) -> None:
        """Rebuild *combo* as [Any, *values] preserving the prior selection."""
        prior = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(tr("enhancements.blueprints_facet_any"), None)
        for v in values:
            combo.addItem(v, v)
        idx = combo.findData(prior)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.blockSignals(False)

    def _make_blueprint_item(self, name: str) -> QListWidgetItem:
        """A list row whose display text is the name (or, with the "show
        tags" toggle on, the item's tagged item_Name value), canonical name
        in UserRole (so filters/moves never depend on display text), and a
        tooltip summarizing the item's mission(s) and component attributes."""
        meta = self._blueprint_meta.get(name)
        display = name
        if AppSettings.get_blueprint_show_tags() and meta is not None and meta.tagged_name:
            display = meta.tagged_name
        item = QListWidgetItem(display)
        item.setData(Qt.ItemDataRole.UserRole, name)
        if meta is not None:
            bits = []
            attrs = " ".join(p for p in (meta.type, meta.cls, meta.size, meta.grade) if p)
            if attrs:
                bits.append(attrs)
            if meta.missions:
                # One mission per line (#347). Comma-joined, a popular item
                # (the R97 Shotgun sits in ~37 mission bodies) rendered as a
                # single unreadable run of text; a player scanning for which
                # contract drops an item had to parse it word by word.
                #
                # The label comes from the translation with an empty
                # placeholder and is rstripped: every language's string is
                # "<Label>: {missions}", so this yields the label alone and
                # the list starts on the next line, without needing a second
                # translatable string for the header.
                label = tr("enhancements.blueprints_tooltip_missions",
                           missions="").rstrip()
                listed = "\n".join(f"  • {m}" for m in sorted(meta.missions))
                bits.append(f"{label}\n{listed}")
            if bits:
                item.setToolTip("\n".join(bits))
        return item

    def _render_blueprint_lists(self) -> None:
        """Repopulate both lists from the metadata + the persisted owned set,
        preserving the filters and not re-entering the move handlers."""
        owned = AppSettings.get_owned_items()
        available = self._available_blueprints(self._blueprint_meta, owned)
        owned_sorted = sorted(owned, key=str.lower)

        for lst, names in (
            (self._blueprints_available_list, available),
            (self._blueprints_owned_list, owned_sorted),
        ):
            lst.blockSignals(True)
            lst.clear()
            for name in names:
                lst.addItem(self._make_blueprint_item(name))
            lst.blockSignals(False)

        self._refilter_blueprint_lists()

        # Empty state: no metadata and nothing owned -> guide the user to
        # generate mission enhancements first; hide the (useless) controls.
        has_content = bool(self._blueprint_meta) or bool(owned)
        self._blueprints_empty_note.setVisible(not has_content)
        for w in (
            self._blueprints_search, self._blueprints_show_tags,
            self._blueprints_mission_label, self._blueprints_mission_combo,
            self._blueprints_filter_note,
            self._blueprints_available_list, self._blueprints_owned_list,
            self._blueprints_add_btn, self._blueprints_remove_btn,
            self._blueprints_available_label, self._blueprints_owned_label,
            *self._blueprints_facet_combos.values(),
            *self._blueprints_facet_labels.values(),
        ):
            w.setVisible(has_content)

    def _blueprint_item_visible(self, name: str) -> bool:
        """True if *name* passes the keyword, mission, and facet filters.

        An item with no value for a facet is hidden only when that facet is set
        to a specific value (not "Any") — so untyped items stay visible until a
        component facet is actually chosen.
        """
        kw = self._blueprints_search.text().strip().lower()
        if kw and kw not in name.lower():
            return False
        mission = self._blueprints_mission_combo.currentData()
        if mission is not None:
            item = self._blueprint_meta.get(name)
            missions = getattr(item, "missions", ()) if item is not None else ()
            if mission not in missions:
                return False
        for attr, combo in self._blueprints_facet_combos.items():
            sel = combo.currentData()
            if sel is not None and self._facet_value(name, attr) != sel:
                return False
        return True

    def _refilter_blueprint_lists(self, *_args) -> None:
        """Hide rows in both lists that don't pass the current filters (#374).

        Used to only touch the Available list -- the search box and Type/
        Class/Size/Grade/Mission dropdowns silently had no effect on the
        Owned list, so a player narrowing down to find one component among
        hundreds of owned items had no way to do it short of scrolling.
        _blueprint_item_visible is a pure predicate on the name alone, so
        applying it to both lists uniformly is correct: there's nothing
        list-specific about "does this item match the current filters".
        """
        for lst in (self._blueprints_available_list, self._blueprints_owned_list):
            for i in range(lst.count()):
                item = lst.item(i)
                name = item.data(Qt.ItemDataRole.UserRole)
                item.setHidden(not self._blueprint_item_visible(name))

    def _selected_names(self, lst) -> list:
        """Names of the selected rows that are actually visible (#374 review).

        Hiding a QListWidgetItem does not deselect it, and both lists allow
        ExtendedSelection, so a selection made before filtering can survive a
        search/dropdown change with some of its rows now hidden. Reading
        selectedItems() unfiltered here meant Remove could silently un-own
        items the user could no longer see -- the same class of silent
        ownership loss #372 was filed over, just reached through a filter
        instead of a foreign log name. Filtering at the point of use (rather
        than clearing the selection when the filter changes) keeps "what you
        can see is what you act on" true without discarding a selection the
        user may want back once they clear the filter.
        """
        return [it.data(Qt.ItemDataRole.UserRole)
                for it in lst.selectedItems() if not it.isHidden()]

    def _on_blueprints_show_tags_toggled(self, checked: bool) -> None:
        """Persist the show-tags display toggle and re-render (#221)."""
        AppSettings.set_blueprint_show_tags(checked)
        self._render_blueprint_lists()

    def _on_auto_scan_startup_toggled(self, checked: bool) -> None:
        """Persist the auto-scan checkbox and keep the popup checkbox's
        enabled state in sync (#386 review) -- the popup setting has no
        effect unless auto-scan itself is on, so greying it out here
        (rather than leaving it clickable but inert) makes that visible."""
        AppSettings.set_auto_scan_blueprints_enabled(checked)
        self._auto_scan_popup_checkbox.setEnabled(checked)

    def _own_selected_blueprints(self) -> None:
        """Move every selected available item into the owned set (one write)."""
        names = self._selected_names(self._blueprints_available_list)
        if not names:
            return
        owned = AppSettings.get_owned_items()
        owned.update(names)
        AppSettings.set_owned_items(owned)
        self._render_blueprint_lists()
        self.owned_items_changed.emit()
        self.mark_owned_dirty()

    def _unown_selected_blueprints(self) -> None:
        """Move every selected owned item back to available (one write)."""
        names = self._selected_names(self._blueprints_owned_list)
        if not names:
            return
        owned = AppSettings.get_owned_items()
        owned.difference_update(names)
        AppSettings.set_owned_items(owned)
        self._render_blueprint_lists()
        self.owned_items_changed.emit()
        self.mark_owned_dirty()

    def _export_owned_blueprints(self) -> None:
        """Export the Owned set to a JSON (SCMDB-shaped) or CSV file (#234).

        Format is chosen via the save dialog's own filter dropdown -- same
        pattern as Export Settings -- rather than a separate format-choice
        dialog. Falls back to whichever filter is selected if the user
        types a path with no/an unexpected extension.
        """
        from src.utils.blueprint_export import (
            export_owned_blueprints_csv,
            export_owned_blueprints_json,
        )

        owned = AppSettings.get_owned_items()
        if not owned:
            QMessageBox.information(
                self,
                tr("blueprint_tracker.export_nothing_title"),
                tr("blueprint_tracker.export_nothing_body"),
            )
            return

        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            tr("blueprint_tracker.export_dialog_title"),
            tr("blueprint_tracker.export_default_filename"),
            f"{tr('blueprint_tracker.export_json_filter')};;"
            f"{tr('blueprint_tracker.export_csv_filter')}",
        )
        if not path:
            return

        is_csv = path.lower().endswith(".csv") or (
            not path.lower().endswith(".json")
            and selected_filter == tr("blueprint_tracker.export_csv_filter")
        )
        if is_csv and not path.lower().endswith(".csv"):
            path += ".csv"
        elif not is_csv and not path.lower().endswith(".json"):
            path += ".json"

        content = (
            export_owned_blueprints_csv(owned, self._blueprint_meta)
            if is_csv
            else export_owned_blueprints_json(owned, self._blueprint_meta)
        )
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(content)
        except OSError as e:
            QMessageBox.critical(
                self,
                tr("blueprint_tracker.export_failed_title"),
                tr("blueprint_tracker.export_failed_body",
                   error_type=type(e).__name__, error=e),
            )
            return

        done_body = (
            tr("blueprint_tracker.export_done_singular", path=path) if len(owned) == 1
            else tr("blueprint_tracker.export_done_plural", count=len(owned), path=path)
        )
        QMessageBox.information(
            self,
            tr("blueprint_tracker.export_done_title"),
            done_body,
        )

    def _import_owned_blueprints(self) -> None:
        """Import owned blueprints from a JSON or CSV file (#234).

        Mirrors "Scan Logs for Owned Blueprints": no confirmation step,
        matched names are applied immediately and the [Owned] tag is
        auto-woven into the strings table the same way a log scan does, then
        one summary reports what happened. Additive -- matched items are
        unioned into the current Owned set, never replacing it, the same
        "never un-owns anything" guarantee the arrow buttons and log scan
        already give.
        """
        from src.utils.blueprint_export import (
            InvalidImportFileError,
            match_import_names,
            parse_import_names,
        )
        from src.utils.owned_items import enclosings_from_tag_configs

        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("blueprint_tracker.import_dialog_title"),
            "",
            tr("blueprint_tracker.import_file_filter"),
        )
        if not path:
            return

        enclosings = enclosings_from_tag_configs(AppSettings.get_all_tag_configs())
        try:
            imported_names = parse_import_names(path, enclosings=enclosings)
        except InvalidImportFileError as e:
            QMessageBox.critical(
                self,
                tr("blueprint_tracker.import_invalid_title"),
                tr("blueprint_tracker.import_invalid_body", error=e),
            )
            return

        matched, unmatched = match_import_names(
            imported_names, set(self._blueprint_meta),
            catalogue=self._known_item_names, enclosings=enclosings,
        )
        skipped_list = "\n".join(sorted(unmatched, key=str.lower))
        if not matched:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Information)
            box.setWindowTitle(tr("blueprint_tracker.import_dialog_title"))
            box.setText(tr("blueprint_tracker.import_nothing_matched_body", count=len(unmatched)))
            box.setDetailedText(skipped_list)
            _relabel_details_button(
                box,
                tr("blueprint_tracker.show_skipped_btn"),
                tr("blueprint_tracker.hide_skipped_btn"),
            )
            box.exec()
            return

        owned = AppSettings.get_owned_items()
        # Count only genuinely new names -- matched includes items already
        # owned, and the log-scan flow this mirrors subtracts them before
        # reporting, so a re-import of the same file says "0 added", not
        # the full file size.
        new_names = matched - owned
        if new_names:
            owned.update(new_names)
            AppSettings.set_owned_items(owned)
            self._render_blueprint_lists()
            self.owned_items_changed.emit()
            # owned_items_changed already triggers MainWindow._recompute_owned()
            # -- the same [Owned]-tag re-weave Apply Owned Tags performs -- so
            # mark clean rather than dirty. Mirrors the log-scan flow's #296
            # fix: re-dirtying after work that just happened would leave the
            # button red right after this summary told the user its tags were
            # already applied.
            self.mark_owned_clean()

        added_text = (
            tr("blueprint_tracker.owned_added_singular") if len(new_names) == 1
            else tr("blueprint_tracker.owned_added_plural", count=len(new_names))
        )
        body_parts = [added_text]
        if unmatched:
            body_parts.append(tr("blueprint_tracker.import_skipped_note", skipped=len(unmatched)))

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(tr("blueprint_tracker.import_dialog_title"))
        # Own line rather than run together in one paragraph -- the skipped
        # note is a distinct, secondary fact from the main result.
        box.setText("\n\n".join(body_parts))
        if unmatched:
            box.setDetailedText(skipped_list)
            _relabel_details_button(
                box,
                tr("blueprint_tracker.show_skipped_btn"),
                tr("blueprint_tracker.hide_skipped_btn"),
            )
        box.exec()

    # ── Apply Owned Tags dirty-tracking ──────────────────────────────────────
    # Mirrors the Enhancements tab's Generate Enhancements / Save Tag Changes
    # pattern: the button greys out once its own click clears the dirty flag,
    # and lights back up the moment the Owned set changes again — from the
    # arrow buttons above, or a channel switch (MainWindow calls
    # mark_owned_dirty() there since the reload bypasses this tab's own move
    # methods, and the owned set's items may not all be visible bullets in
    # the new channel's data yet).
    #
    # A log scan is *not* one of these cases (#296): MainWindow's scan-finish
    # handler already calls _recompute_owned() itself — the same re-weave
    # Apply Owned Tags performs — before the button is touched, so it calls
    # mark_owned_clean() instead of mark_owned_dirty(). Re-dirtying after
    # work that just happened left the button red right after the scan
    # summary had told the user its tags were applied.

    def _set_owned_btn_dirty(self, dirty: bool) -> None:
        """Single chokepoint for the button's enabled state, tooltip, and
        text color so none of the three can drift apart."""
        self._owned_dirty = dirty
        self._apply_owned_btn.setEnabled(dirty)
        self._apply_owned_btn.setToolTip(
            tr("blueprint_tracker.apply_owned_tag_tooltip") if dirty
            else tr("blueprint_tracker.apply_owned_tag_tooltip_disabled")
        )
        self._apply_owned_btn.setStyleSheet(
            f"color: {get_button_color('needs_apply')};" if dirty else ""
        )

    def mark_owned_dirty(self) -> None:
        """Public: light the Apply Owned Tags button back up. Called from
        this tab's own arrow-button moves, and by MainWindow after a channel
        switch."""
        self._set_owned_btn_dirty(True)

    def mark_owned_clean(self) -> None:
        """Public: grey the Apply Owned Tags button out. Called by
        MainWindow after a log scan's own _recompute_owned() call has
        already done the re-weave the button would otherwise prompt for
        (#296)."""
        self._set_owned_btn_dirty(False)

    def _on_apply_owned_clicked(self) -> None:
        self.apply_owned_requested.emit()
        self._set_owned_btn_dirty(False)

    def is_force_rescan_checked(self) -> bool:
        """#308: whether "Rescan all logs" is checked. Read by MainWindow
        when building a scan run, before the one-shot reset below."""
        return self._force_rescan_checkbox.isChecked()

    def reset_force_rescan_checkbox(self) -> None:
        """#308: uncheck "Rescan all logs" once a scan run has consumed it
        (called by MainWindow after the scan queue finishes), so the next
        click defaults back to a normal incremental scan."""
        self._force_rescan_checkbox.setChecked(False)

    def set_scan_logs_enabled(self, enabled: bool) -> None:
        """#386 review: gate the "Scan Logs" button while a scan is running.

        Called by MainWindow around every scan run, manual or the silent
        startup auto-scan. Without this, a click during an in-flight silent
        auto-scan (no progress dialog, easy-to-miss status bar text) hit the
        pre-existing reentrancy guard and did nothing -- no dialog, no
        disabled button, nothing telling the user a scan was already
        running. The disabled tooltip makes that visible instead of silent.
        """
        self._scan_logs_btn.setEnabled(enabled)
        self._scan_logs_btn.setToolTip(
            tr("blueprint_tracker.scan_logs_tooltip") if enabled
            else tr("blueprint_tracker.scan_logs_already_running_tooltip")
        )
