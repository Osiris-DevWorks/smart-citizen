"""Enhancements tab for Smart Citizen."""
import logging
from dataclasses import replace as dc_replace

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QTabBar, QTabWidget, QVBoxLayout,
    QWidget,
)

from src.gui.tag_mapping_dialog import TagMappingDialog
from src.gui.theme import get_button_color
from src.utils.i18n import tr
from src.utils.settings import AppSettings
from src.utils.tag_builder import (
    CATEGORIES, ELEMENT_LABELS, ENCLOSINGS, LOCATION_DETAILS,
    MAPPED_KIND_NAMES, MISSION_TITLE_PLACEMENTS, PLACEMENTS, RANK_SEPARATORS,
    REMOVE_WORD_OPTIONS, ROUTE_ARROWS, SEPARATORS, SHORTEN_PHRASE_OPTIONS,
    SIZE_ABBREV_BY_WORD, STYLES_BY_KIND, TITLE_SEPARATORS, TagConfig,
    UNDERLINE_OPTIONS, USAGE_INPUT_SEP, abbreviate_title, apply_mission_title,
    default_config, render_route, render_tag, route_enabled,
)

# All cargo-size words, for the single "Shorten cargo sizes" master toggle.
_ALL_SIZE_WORDS: frozenset[str] = frozenset(SIZE_ABBREV_BY_WORD)

logger = logging.getLogger(__name__)


def reposition_combo_popup_below_if_it_fits(combo, popup) -> None:
    """Move *popup* to align with *combo*'s bottom-left corner, but only if
    it actually fits on-screen there.

    Qt's default popup placement flips the list above the box when it judges
    there isn't room below (common in a scroll area, even when there visually
    is room) — force it below whenever that actually fits, so the option list
    is where the user expects it. A combo near the bottom of the screen is
    the case Qt's flip logic exists for; forcing "below" there would run the
    popup off the bottom of the display, so only override when there's room.

    Shared by _NoScrollComboBox.showPopup below (initial placement) and
    blueprint_tracker_tab.py's _NoWheelComboBox.showPopup (#388, re-checked
    a second time there after forcibly shrinking an overlong popup — the
    first check ran against the original, taller height).
    """
    below_point = combo.mapToGlobal(combo.rect().bottomLeft())
    screen = combo.screen()
    fits_below = (
        screen is None
        or below_point.y() + popup.height() <= screen.availableGeometry().bottom()
    )
    if fits_below:
        popup.move(below_point)


class _NoScrollComboBox(QComboBox):
    """A combo box that ignores the mouse wheel unless it has focus (#197).

    The Enhancements tab lives in a scroll area with many dropdowns; by default
    a wheel scroll over an unfocused combo changes its selection instead of
    scrolling the page. StrongFocus stops the wheel from focusing the combo, and
    wheelEvent passes the scroll through to the page when the combo isn't focused.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event):  # noqa: N802 (Qt override)
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()

    def showPopup(self):  # noqa: N802 (Qt override)
        super().showPopup()
        reposition_combo_popup_below_if_it_fits(self, self.view().window())


class _NoScrollTabBar(QTabBar):
    """A tab bar that never switches tabs on mouse wheel scroll.

    Unlike a combo box (_NoScrollComboBox above), there's no legitimate case
    for wheel-scrolling through tabs here — a hover-scroll over the Tag
    Builder's category tabs (Components/Missiles/.../Mission Titles) should
    scroll the page, not silently jump categories. Always ignores the wheel
    event so it bubbles up to the enclosing scroll area instead.
    """

    def wheelEvent(self, event):  # noqa: N802 (Qt override)
        event.ignore()


# Sample values used by the live preview so the user can see what their
# config will produce without re-running the generator.
_PREVIEW_VALUES: dict[str, dict[str, str]] = {
    "components":   {"class": "Military", "size": "2", "grade": "A", "type": "Shield Generator"},
    "missiles":     {"ordinance": "Infrared", "size": "1"},
    "ship_weapons": {"damage": "Energy",   "size": "2"},
    "commodities":  {"label": "Crafting",
                     "usage": USAGE_INPUT_SEP.join(["Quantum Drive", "Shield"]),
                     "collection": "Collection"},
}
_PREVIEW_NAMES: dict[str, str] = {
    "components":   "FR-76",
    "missiles":     "Marksman I Missile",
    "ship_weapons": "MaxOx NN-14",
    "commodities":  "Agricium",
}
_CATEGORY_LABELS: dict[str, str] = {
    "components":   "Components",
    "missiles":     "Missiles",
    "ship_weapons": "Ship Weapons",
    "commodities":  "Commodities",
    "mission_titles": "Mission Titles",
}


class EnhancementsTab(QWidget):
    """Tab for optional enhancements: localization enhancements and ship favorites."""

    merge_requested = pyqtSignal()
    enhancements_pipeline_requested = pyqtSignal()   # extract DataForge if needed, then generate enhancements
    # (old_prefix, new_prefix) — the favourite sort prefix changed. MainWindow
    # re-prefixes in-memory favourites to match the migrated user.ini before
    # reloading, so the reload's pending-edit snapshot doesn't clobber the new
    # prefix back to the old one (#140).
    favorite_prefix_changed = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        self._loaded_prefix = AppSettings.get_favorite_prefix()
        # Dirty flags gate the Generate Enhancements / Save Tag Changes
        # buttons: disabled until something in their own section changes,
        # so a grey button tells the user "already up to date" instead of
        # inviting a redundant multi-minute regen (see _mark_*_dirty below).
        self._enhancements_dirty = False
        self._tag_dirty = False
        self._prefix_dirty = False
        self.setup_ui()

    def setup_ui(self):
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self._title_label = QLabel(tr("enhancements.title"))
        self._title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(self._title_label)

        self._desc_label = QLabel(tr("enhancements.desc"))
        self._desc_label.setProperty("role", "secondary")
        self._desc_label.setStyleSheet("font-size: 11px;")
        self._desc_label.setWordWrap(True)
        layout.addWidget(self._desc_label)

        self._enhancements_group = self._build_enhancements_group()
        layout.addWidget(self._enhancements_group)

        mid_row = QHBoxLayout()
        self._favorites_group = self._build_favorites_group()
        mid_row.addWidget(self._favorites_group)
        mid_row.addWidget(self._build_mission_labels_group(), 1)
        layout.addLayout(mid_row)

        self._tag_builder_group = self._build_tag_builder_group()
        layout.addWidget(self._tag_builder_group, 1)
        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.viewport().setAutoFillBackground(False)
        content.setAutoFillBackground(False)
        scroll.setWidget(content)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    # ── Enhancements ─────────────────────────────────────────────────────────

    def _build_enhancements_group(self) -> QGroupBox:
        group = QGroupBox(tr("enhancements.enhancements_group"))
        self._enhancements_group_box = group
        gl = QVBoxLayout(group)

        self._enhancements_desc_label = QLabel(tr("enhancements.enhancements_desc"))
        self._enhancements_desc_label.setProperty("role", "secondary")
        self._enhancements_desc_label.setStyleSheet("font-size: 11px;")
        self._enhancements_desc_label.setWordWrap(True)
        gl.addWidget(self._enhancements_desc_label)

        # Per-category checkbox + description + status dot
        _CATEGORY_DESCRIPTIONS = {
            "ships":       tr("enhancements.cat_desc_ships"),
            "ship_items":  tr("enhancements.cat_desc_ship_items"),
            "gear":        tr("enhancements.cat_desc_gear"),
            "missions":    tr("enhancements.cat_desc_missions"),
            "commodities": tr("enhancements.cat_desc_commodities"),
            "journal":     tr("enhancements.cat_desc_journal"),
            "medical_consumables": tr("enhancements.cat_desc_medical_consumables"),
        }

        self._enhancements_status_labels: dict = {}
        self._enhancements_checkboxes: dict = {}
        self._cat_desc_labels: dict = {}
        # Two-column grid: column-major fill so the first three categories
        # stack down the left column and the next three down the right —
        # reads top-to-bottom-then-right rather than left-to-right.
        categories_layout = QGridLayout()
        categories_layout.setHorizontalSpacing(12)
        categories_layout.setVerticalSpacing(4)
        column_height = 2
        for idx, (key, label) in enumerate(AppSettings.ENHANCEMENT_LABELS.items()):
            cell_row = idx % column_height
            cell_col = idx // column_height

            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            description = _CATEGORY_DESCRIPTIONS.get(key, "")

            dot = QLabel("●")
            dot.setStyleSheet("color: #999; font-size: 12px;")
            row.addWidget(dot)
            self._enhancements_status_labels[key] = dot

            cb = QCheckBox(label)
            cb.setChecked(AppSettings.get_enhancement_category_enabled(key))
            cb.setStyleSheet("font-size: 11px;")
            cb.toggled.connect(self._on_category_checkbox_changed)
            cb.toggled.connect(self._mark_enhancements_dirty)
            row.addWidget(cb)
            self._enhancements_checkboxes[key] = cb

            desc = QLabel(description)
            desc.setProperty("role", "secondary")
            desc.setStyleSheet("font-size: 10px;")
            row.addWidget(desc)
            self._cat_desc_labels[key] = desc

            cell = QWidget()
            cell.setLayout(row)
            cell.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
            categories_layout.addWidget(cell, cell_row, cell_col)

        categories_layout.setColumnStretch(0, 0)
        categories_layout.setColumnStretch(1, 0)
        categories_layout.setColumnStretch(2, 0)
        categories_layout.setColumnStretch(3, 0)
        # Pack the grid to its natural (left-hugging) width and let a
        # trailing stretch absorb the rest of the row — previously column 3
        # itself carried the stretch, which spread the categories out across
        # the full tab width and forced horizontal scrolling.
        categories_row = QHBoxLayout()
        categories_row.setContentsMargins(0, 0, 0, 0)
        categories_row.addLayout(categories_layout)
        categories_row.addStretch()
        gl.addLayout(categories_row)

        # ── Mission detail fields (#121) ───────────────────────────────────
        # Granular show/hide for each line the generator adds to a mission
        # DETAILS body. Persisted on toggle; baked at generation time, so a
        # change takes effect on the next Generate Enhancements run.
        self._mf_heading = QLabel(tr("enhancements.mission_detail_fields_heading"))
        self._mf_heading.setStyleSheet("font-size: 11px; font-weight: bold;")
        gl.addWidget(self._mf_heading)

        # Keys stored on self (not a local) so retranslate_ui can rebuild each
        # checkbox's text/tooltip after a language switch without duplicating
        # this list.
        self._mission_field_keys = [
            ("mission_type",  "enhancements.mission_field_mission_type"),
            ("difficulty",    "enhancements.mission_field_difficulty"),
            ("spawns",        "enhancements.mission_field_hostiles"),
            ("reputation",    "enhancements.mission_field_reputation"),
            ("blueprints",    "enhancements.mission_field_blueprints"),
            ("ace",           "enhancements.mission_field_ace_pilot"),
            # #331: "Resource Signatures:" breakdown block in the DETAILS
            # body for Recco Battaglia scan/mining contracts -- one line per
            # targeted ore with its full RS value progression. Independent of
            # the "Show Resource Signatures (RS) next to ore names" checkbox
            # below (which annotates the ore's own display name instead of
            # adding a body line).
            ("resource_signatures", "enhancements.mission_field_resource_signatures"),
        ]
        self._mission_field_labels = [(f, tr(k)) for f, k in self._mission_field_keys]
        # 2.2.0: the [BP]/[ACE]/rep-xp mission-TITLE markers moved to their own
        # "General Tags" section (independent of this body-fields group) —
        # see AppSettings.get_mission_title_tags(). "ace" here now controls
        # ONLY the "Ace Pilot: Yes" body line.
        self._mission_field_checkboxes: dict = {}
        _mf_saved = AppSettings.get_mission_detail_fields()
        mf_row = QHBoxLayout()
        mf_row.setContentsMargins(0, 0, 0, 0)
        for _field, _label in self._mission_field_labels:
            cb = QCheckBox(_label)
            cb.setChecked(_mf_saved.get(_field, True))
            cb.setStyleSheet("font-size: 11px;")
            cb.setToolTip(self._mission_field_tooltip(_field, _label))
            cb.toggled.connect(
                lambda checked, f=_field: self._on_mission_field_toggled(f, checked)
            )
            cb.toggled.connect(self._mark_enhancements_dirty)
            mf_row.addWidget(cb)
            self._mission_field_checkboxes[_field] = cb
        mf_row.addStretch()
        gl.addLayout(mf_row)

        self._mf_note = QLabel(tr("enhancements.mission_detail_fields_note"))
        self._mf_note.setProperty("role", "secondary")
        self._mf_note.setStyleSheet("font-size: 10px;")
        self._mf_note.setWordWrap(True)
        gl.addWidget(self._mf_note)

        # #153: place the stats block above the prose description (for ship and
        # component/weapon entries), so the useful numbers sit at the top when
        # comparing modules in the Hologlass. Baked at generation time.
        self._stats_prepend_check = QCheckBox(tr("enhancements.stats_prepend_cb"))
        self._stats_prepend_check.setChecked(AppSettings.get_stats_prepend())
        self._stats_prepend_check.setStyleSheet("font-size: 11px;")
        self._stats_prepend_check.setToolTip(tr("enhancements.stats_prepend_tooltip"))
        self._stats_prepend_check.toggled.connect(
            lambda checked: AppSettings.set_stats_prepend(checked)
        )
        self._stats_prepend_check.toggled.connect(self._mark_enhancements_dirty)
        gl.addWidget(self._stats_prepend_check)

        self._standardize_ship_names_check = QCheckBox(tr("enhancements.standardize_ship_names_cb"))
        self._standardize_ship_names_check.setChecked(
            AppSettings.get_standardize_earnable_ship_names()
        )
        self._standardize_ship_names_check.setStyleSheet("font-size: 11px;")
        self._standardize_ship_names_check.setToolTip(tr("enhancements.standardize_ship_names_tooltip"))
        self._standardize_ship_names_check.toggled.connect(
            lambda checked: AppSettings.set_standardize_earnable_ship_names(checked)
        )
        self._standardize_ship_names_check.toggled.connect(self._mark_enhancements_dirty)
        gl.addWidget(self._standardize_ship_names_check)

        # #331: annotates every mineable ore's own display name with its base
        # Resource Signature ("Aluminium (RS 4285)"), so the value shows up
        # everywhere the game renders that name -- including the top-right
        # mission tracker, which is the case users specifically asked for.
        # Independent of "Resource Signatures" under Mission Detail Fields
        # above (the DETAILS-body breakdown): that one adds a line to the
        # mission body, this one patches the ore's own name at its source.
        # Default on -- see AppSettings.RS_ORE_NAME_ANNOTATIONS for why.
        self._rs_ore_name_annotations_check = QCheckBox(tr("enhancements.rs_ore_name_annotations_cb"))
        self._rs_ore_name_annotations_check.setChecked(
            AppSettings.get_rs_ore_name_annotations()
        )
        self._rs_ore_name_annotations_check.setStyleSheet("font-size: 11px;")
        self._rs_ore_name_annotations_check.setToolTip(tr("enhancements.rs_ore_name_annotations_tooltip"))
        self._rs_ore_name_annotations_check.toggled.connect(
            lambda checked: AppSettings.set_rs_ore_name_annotations(checked)
        )
        self._rs_ore_name_annotations_check.toggled.connect(self._mark_enhancements_dirty)
        gl.addWidget(self._rs_ore_name_annotations_check)

        btn_row = QHBoxLayout()

        self._apply_categories_btn = QPushButton(tr("enhancements.apply_btn"))
        self._apply_categories_btn.setMaximumWidth(100)
        self._apply_categories_btn.setEnabled(False)
        self._apply_categories_btn.setToolTip(tr("enhancements.apply_categories_tooltip"))
        self._apply_categories_btn.clicked.connect(self._apply_category_changes)
        btn_row.addWidget(self._apply_categories_btn)

        self._generate_enhancements_btn = QPushButton(tr("enhancements.generate_btn"))
        self._generate_enhancements_btn.setMaximumWidth(160)
        self._generate_enhancements_btn.clicked.connect(self._on_generate_enhancements_clicked)
        btn_row.addWidget(self._generate_enhancements_btn)

        btn_row.addStretch()
        gl.addLayout(btn_row)

        self._forge_status_label = QLabel()
        self._forge_status_label.setProperty("role", "secondary")
        self._forge_status_label.setStyleSheet("font-size: 10px;")
        gl.addWidget(self._forge_status_label)

        self.refresh_enhancements_status()
        # Start dirty (button clickable) when there's nothing generated yet
        # or the DataForge cache is stale — otherwise start clean, since the
        # loaded checkbox/field state matches what's already on disk.
        self._set_generate_btn_dirty(self._compute_initial_enhancements_dirty())
        return group

    @staticmethod
    def _mission_field_tooltip(field: str, label: str) -> str:
        """Tooltip for one mission-detail-field checkbox. "ace" gets a
        dedicated string (it shares its settings key with the unrelated
        [ACE] title tag under General Tags, so the distinction needs
        spelling out); every other field gets the generic template. Shared
        by setup_ui() and retranslate_ui() so the two can't drift apart."""
        if field == "ace":
            return tr("enhancements.mission_field_ace_tooltip")
        return tr("enhancements.mission_field_default_tooltip", label=label)

    def _set_generate_btn_dirty(self, dirty: bool) -> None:
        """Single chokepoint for the button's enabled state, tooltip, and
        text color so none of the three can drift apart. Red text signals
        "click me — something changed"; clean/disabled reverts to Qt's
        default look. The two tooltip variants are resolved via tr() here
        (not cached class constants) so they always reflect the active
        language — the disabled-state text is what a user hovering a
        gone-grey button most wants to know: "why can't I click this?" """
        self._enhancements_dirty = dirty
        self._generate_enhancements_btn.setEnabled(dirty)
        self._generate_enhancements_btn.setToolTip(
            tr("enhancements.generate_enabled_tooltip") if dirty
            else tr("enhancements.generate_disabled_tooltip")
        )
        self._generate_enhancements_btn.setStyleSheet(
            f"color: {get_button_color('needs_apply')};" if dirty else ""
        )

    def _compute_initial_enhancements_dirty(self) -> bool:
        """True if Generate Enhancements has work to do right now: the
        DataForge cache was never extracted or is stale vs. Data.p4k, or an
        enabled category's output file doesn't exist yet.

        Looks in get_enhancements_dir(), not get_cache_dir(). Those are the
        same path for English, but every other language keeps its generated
        INIs in cache/lang/{language} (get_enhancements_dir), which is where
        the generator writes them (workers.py, enh_dir). Checking the channel
        root instead answered for English no matter which language was
        selected, so a language with nothing generated could report "nothing
        to do" purely because English had been generated earlier. #363 made
        that reachable on every language switch, which is what surfaced it.
        """
        from src.utils.pak_extractor import P4K_MTIME_STAMP, dataforge_cache_is_fresh
        forge_dir = AppSettings.get_dataforge_cache_dir()
        p4k_path = AppSettings.get_p4k_path()
        if not (forge_dir / P4K_MTIME_STAMP).exists():
            return True
        if p4k_path.exists() and not dataforge_cache_is_fresh(p4k_path, forge_dir):
            return True
        enh_dir = AppSettings.get_enhancements_dir()
        for key, cb in self._enhancements_checkboxes.items():
            if cb.isChecked() and any(
                not (enh_dir / fn).exists() for fn in self._files_for_category(key)
            ):
                return True
        return False

    def _mark_enhancements_dirty(self, *_args):
        """A setting that feeds Generate Enhancements changed since the last
        run — light the button back up."""
        self._set_generate_btn_dirty(True)

    def mark_enhancements_dirty(self) -> None:
        """Public entrypoint for external callers (MainWindow) to flag that
        something outside this tab affects Generate Enhancements — e.g. a
        fresh base.ini extraction. A pure loc-string change (CIG renaming or
        adding flavor text to an item) doesn't touch the DataForge XML cache
        the freshness check above looks at, so without this a stale cached
        enhancement entry for that item could sit indefinitely with the
        button never lighting up to prompt a re-run."""
        self._mark_enhancements_dirty()

    def mark_enhancements_clean(self) -> None:
        """Public entrypoint for external callers (MainWindow) to flag that
        a Generate Enhancements run is starting, regardless of how it was
        triggered — manual click, Tag Builder apply, or the automated
        freshness check (#292). Call at the point a run is launched, not on
        completion: set_operation_idle() only re-enables the button on
        success, it doesn't force it clean, so if a run is triggered while
        already dirty this needs to have cleared the flag first or the
        button stays red after a successful generation."""
        self._set_generate_btn_dirty(False)

    def refresh_enhancements_dirty_state(self) -> None:
        """Public entrypoint for external callers (MainWindow) to re-derive
        the Generate Enhancements button's enabled state from the current
        channel's real disk state (#273).

        _enhancements_dirty is otherwise only ever set once, at tab
        construction, then nudged True/False by discrete UI events
        (a checkbox toggle, clicking Generate itself). Switching the active
        channel changes what "the current channel's real disk state" even
        means — the flag needs recomputing from scratch, not left at
        whatever it held for the previous channel. Without this, switching
        to a channel that genuinely needs (re)generation left the button
        disabled (still reflecting the previous channel's now-clean state),
        so clicking it silently did nothing until the user happened to
        retoggle some checkbox that forces the flag back on."""
        self._set_generate_btn_dirty(self._compute_initial_enhancements_dirty())

    def _live_tag_config_fingerprint(self) -> str:
        """Fingerprint the Tag Builder config as it stands in the pages right
        now — INCLUDING unsaved in-session edits — so a freshness check reflects
        what the user actually sees, not just what's been persisted. Falls back
        to the persisted config when the Tag Builder group hasn't been built
        yet (same getattr guard as _persist_tag_builder_state).

        Using the live page state (not AppSettings.get_current_tag_config_
        fingerprint()) is deliberate: comparing persisted-only config against a
        channel's stamp could clear the button while unsaved edits still sit in
        the pages, silently dropping the "you have unsaved changes" signal. In
        the no-edit steady state the pages equal the persisted config, so this
        still matches the stamp the generator wrote from those same values."""
        from src.utils.tag_builder import tag_config_fingerprint
        pages = getattr(self, "_tag_builder_pages", None)
        annotate_cb = getattr(self, "_annotate_mission_descs_cb", None)
        if not pages or annotate_cb is None:
            return AppSettings.get_current_tag_config_fingerprint()
        configs = {cat: page.config for cat, page in pages.items()}
        return tag_config_fingerprint(configs, annotate_cb.isChecked())

    def refresh_tag_builder_dirty_state(self) -> None:
        """Public entrypoint for external callers (MainWindow) to re-derive the
        Save Tag Changes button's state after a channel switch (#273 follow-up).

        Tag Builder configs are global, but the generated enhancement INIs they
        feed are per-channel. Generation now stamps each channel's enhancement
        dir with a fingerprint of the tag config it was built from (see
        workers.py / AppSettings.get/set_tag_config_stamp), so we can do a real
        freshness check here — matching Generate Enhancements' own
        refresh_enhancements_dirty_state — instead of always lighting the
        button. Light it only when the new channel's stamp is missing or
        differs from the config currently shown in the pages (so its INIs
        genuinely lack those tags); leave it grey when they already match. A
        missing stamp (channels generated before this feature, or never
        generated) reads as dirty, so the button stays clickable exactly as it
        did before until the next generation records a stamp.

        #363 made this the single definition of "the generated INIs don't match
        the tag config", called from every point that can invalidate them
        (launch, an import, a finished run) rather than only a channel switch,
        so it also gained the gate below: being stale requires there to be
        something that *can* be stale. With no enhancement output on disk there
        is nothing to be out of date, and Generate Enhancements is already
        lit for the missing files, so lighting this one too would just put a
        second red button in front of a new user who has done nothing wrong.
        """
        if getattr(self, "_apply_tag_btn", None) is None:
            return
        if not self._enhancements_output_exists():
            self._set_tag_btn_dirty(False)
            return
        stamp = AppSettings.get_tag_config_stamp()
        current = self._live_tag_config_fingerprint()
        self._set_tag_btn_dirty(not stamp or stamp != current)

    def _enhancements_output_exists(self) -> bool:
        """True if any enabled category has at least one generated INI on disk.

        Deliberately "any", not "all": a partially generated set is still
        output that a tag-config change can invalidate, and the missing half is
        Generate Enhancements' business (_compute_initial_enhancements_dirty
        lights it for exactly that). Guarded with getattr so it stays a safe
        no-op if the enhancements group hasn't been built — setup_ui builds it
        before the Tag Builder group, so in practice it always has.

        Uses get_enhancements_dir() so it agrees with the stamp it gates: the
        stamp lives in that same per-language dir, and for anything but
        English it is cache/lang/{language}, not the channel root. Reading the
        root here would have suppressed the whole freshness check for a
        non-English user who had never generated English enhancements — no
        files found, so "nothing can be stale", so the stamp never read.
        """
        checkboxes = getattr(self, "_enhancements_checkboxes", None)
        if not checkboxes:
            return False
        enh_dir = AppSettings.get_enhancements_dir()
        return any(
            (enh_dir / fn).exists()
            for key, cb in checkboxes.items() if cb.isChecked()
            for fn in self._files_for_category(key)
        )

    def _on_category_checkbox_changed(self):
        """Enable Apply button if any checkbox differs from saved settings."""
        has_changes = any(
            cb.isChecked() != AppSettings.get_enhancement_category_enabled(key)
            for key, cb in self._enhancements_checkboxes.items()
        )
        self._apply_categories_btn.setEnabled(has_changes)

    def _apply_category_changes(self):
        """Save checkbox states, disable/restore enhancement files, and trigger reload."""
        for key, cb in self._enhancements_checkboxes.items():
            now_enabled = cb.isChecked()
            AppSettings.set_enhancement_category_enabled(key, now_enabled)

            # Per-language, like every other enhancement-file path (#363).
            # This one MUTATES files, so reading the channel root here did
            # more than answer the wrong question: a user on a non-English
            # language toggling a category renamed the ENGLISH INIs to
            # .disabled and back, while their own language's files, the ones
            # the checkbox appears to control, were never touched. The toggle
            # silently did nothing for them and quietly vandalised English.
            enh_dir = AppSettings.get_enhancements_dir()
            # Apply to all files mapped to this checkbox key
            for filename in self._files_for_category(key):
                active_file = enh_dir / filename
                disabled_file = enh_dir / (filename + ".disabled")

                if not now_enabled and active_file.exists():
                    try:
                        # Windows rename() fails when the target exists, and a
                        # stale .disabled is reachable: anyone who hit the bug
                        # above has an orphaned English .disabled, and
                        # regenerating recreates the active file beside it.
                        # Without this the next disable raises, gets logged,
                        # and the toggle appears to do nothing.
                        disabled_file.unlink(missing_ok=True)
                        active_file.rename(disabled_file)
                        logger.info(f"Disabled enhancement file: {filename}")
                    except OSError as e:
                        logger.warning(f"Failed to disable {filename}: {e}")

                elif now_enabled and not active_file.exists() and disabled_file.exists():
                    try:
                        disabled_file.rename(active_file)
                        logger.info(f"Restored enhancement file: {filename}")
                    except OSError as e:
                        logger.warning(f"Failed to restore {filename}: {e}")

        self._apply_categories_btn.setEnabled(False)
        self.refresh_enhancements_status()
        self.merge_requested.emit()

    @staticmethod
    def _files_for_category(key: str) -> list[str]:
        """Return the enhancement filenames controlled by a checkbox key."""
        file_keys = AppSettings.ENHANCEMENT_CATEGORY_FILES.get(key, [key])
        return [AppSettings.ENHANCEMENTS_FILES[fk] for fk in file_keys]

    def revert_category_checkboxes(self):
        """Reset checkboxes to match the saved settings (called when leaving tab without applying)."""
        for key, cb in self._enhancements_checkboxes.items():
            cb.blockSignals(True)
            cb.setChecked(AppSettings.get_enhancement_category_enabled(key))
            cb.blockSignals(False)
        self._apply_categories_btn.setEnabled(False)

    def _on_mission_field_toggled(self, field: str, checked: bool) -> None:
        """Persist a mission-detail field toggle (#121). Baked at generation
        time, so the change shows up after the next Generate Enhancements."""
        AppSettings.set_mission_detail_field(field, checked)

    # ── Favorites ─────────────────────────────────────────────────────────────

    def _build_favorites_group(self) -> QGroupBox:
        group = QGroupBox(tr("enhancements.favorites_group"))
        self._favorites_group_box = group
        gl = QVBoxLayout(group)

        self._favorites_desc_label = QLabel(tr("enhancements.favorites_desc"))
        self._favorites_desc_label.setProperty("role", "secondary")
        self._favorites_desc_label.setStyleSheet("font-size: 11px;")
        self._favorites_desc_label.setWordWrap(True)
        gl.addWidget(self._favorites_desc_label)


        prefix_row = QHBoxLayout()
        self._sort_prefix_label = QLabel(tr("enhancements.sort_prefix_label"))
        prefix_row.addWidget(self._sort_prefix_label)

        self.favorite_prefix_combo = _NoScrollComboBox()
        self.favorite_prefix_combo.setToolTip(tr("enhancements.favorite_prefix_tooltip"))
        self.favorite_prefix_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents
        )
        self.favorite_prefix_combo.addItem("  (space)", userData=" ")
        for code in range(33, 65):
            self.favorite_prefix_combo.addItem(chr(code), userData=chr(code))

        for i in range(self.favorite_prefix_combo.count()):
            if self.favorite_prefix_combo.itemData(i) == self._loaded_prefix:
                self.favorite_prefix_combo.setCurrentIndex(i)
                break
        self.favorite_prefix_combo.currentIndexChanged.connect(self._mark_prefix_dirty)

        self.favorite_prefix_combo.view().setMinimumWidth(
            self.favorite_prefix_combo.sizeHint().width() + 20
        )
        prefix_row.addWidget(self.favorite_prefix_combo)

        self._apply_prefix_btn = QPushButton(tr("enhancements.apply_btn"))
        self._apply_prefix_btn.clicked.connect(self._apply_favorite_prefix)
        prefix_row.addWidget(self._apply_prefix_btn)
        self._set_prefix_btn_dirty(False)

        prefix_row.addStretch()
        gl.addLayout(prefix_row)
        return group

    # ── Mission Labels ──────────────────────────────────────────────────────

    def _build_mission_labels_group(self) -> QGroupBox:
        from PyQt6.QtWidgets import QLineEdit
        self.mission_labels_group = QGroupBox(tr("enhancements.mission_labels_group"))
        group = self.mission_labels_group
        gl = QVBoxLayout(group)

        headers = AppSettings.get_mission_headers()
        self._header_inputs: dict[str, QLineEdit] = {}

        # 6 fields in a 3-col × 2-row grid
        d = AppSettings.MISSION_HEADER_DEFAULTS
        fields = [
            ("details",        "enhancements.mission_label_details",        headers.get("details", d["details"])),
            ("blueprints",     "enhancements.mission_label_blueprints",     headers.get("blueprints", d["blueprints"])),
            ("items",          "enhancements.mission_label_item_rewards",   headers.get("items", d["items"])),
            ("blueprint_data", "enhancements.mission_label_blueprint_data", headers.get("blueprint_data", d["blueprint_data"])),
        ]

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(4)
        col_height = 2
        self._mission_label_widgets: list[tuple[QLabel, str]] = []
        for idx, (key, label_key, value) in enumerate(fields):
            row = idx % col_height
            col = (idx // col_height) * 2
            lbl_widget = QLabel(tr(label_key))
            grid.addWidget(lbl_widget, row, col)
            self._mission_label_widgets.append((lbl_widget, label_key))
            inp = QLineEdit()
            inp.setText(value)
            inp.editingFinished.connect(lambda k=key: self._save_mission_header(k))
            self._header_inputs[key] = inp
            grid.addWidget(inp, row, col + 1)

        # XP label and header tag in the third column pair
        self._xp_label_widget = QLabel(tr("enhancements.mission_label_xp"))
        grid.addWidget(self._xp_label_widget, 0, 4)
        self._rep_xp_label_input = QLineEdit()
        self._rep_xp_label_input.setText(AppSettings.get_rep_xp_label())
        self._rep_xp_label_input.setMaximumWidth(100)
        self._rep_xp_label_input.setToolTip(tr("enhancements.rep_xp_label_tooltip"))
        self._rep_xp_label_input.editingFinished.connect(self._save_rep_xp_label)
        grid.addWidget(self._rep_xp_label_input, 0, 5)

        self._header_style_label_widget = QLabel(tr("enhancements.mission_label_header_style"))
        grid.addWidget(self._header_style_label_widget, 1, 4)
        self._header_em_combo = _NoScrollComboBox()
        # #164: show what the tags actually do in-game (EM3 underlines, EM4
        # renders blue) instead of the opaque EM3/EM4 names. The stored value
        # stays the EM tag, so the generator output is unchanged.
        for tag in AppSettings.MISSION_HEADER_EM_TAGS:
            self._header_em_combo.addItem(self._em_label(tag), userData=tag)
        current_em = AppSettings.get_mission_header_em_tag()
        for i in range(self._header_em_combo.count()):
            if self._header_em_combo.itemData(i) == current_em:
                self._header_em_combo.setCurrentIndex(i)
                break
        self._header_em_combo.setToolTip(tr("enhancements.header_em_tooltip"))
        self._header_em_combo.currentIndexChanged.connect(self._save_header_em_tag)
        grid.addWidget(self._header_em_combo, 1, 5)

        gl.addLayout(grid)
        return group

    def _save_rep_xp_label(self):
        label = self._rep_xp_label_input.text().strip()
        if not label:
            label = AppSettings.DEFAULT_REP_XP_LABEL
            self._rep_xp_label_input.setText(label)
        AppSettings.set_rep_xp_label(label)
        self._mark_enhancements_dirty()

    def _save_mission_header(self, key: str):
        inp = self._header_inputs.get(key)
        if inp:
            val = inp.text().strip()
            if val:
                AppSettings.set_mission_header(key, val)
                self._mark_enhancements_dirty()

    def _save_header_em_tag(self):
        tag = self._header_em_combo.currentData()
        if tag:
            AppSettings.set_mission_header_em_tag(tag)
            self._mark_enhancements_dirty()

    @staticmethod
    def _em_label(tag: str) -> str:
        """Friendly combo-item text for a header EM tag ("EM3" -> "Underline").

        Shared by construction and retranslate_ui() so the two can't drift apart.
        """
        return {
            "EM3": tr("enhancements.em_label_underline"),
            "EM4": tr("enhancements.em_label_blue_text"),
        }.get(tag, tag)

    def _set_prefix_btn_dirty(self, dirty: bool) -> None:
        """Single chokepoint for the button's enabled state, tooltip, and
        text color so none of the three can drift apart. Same enabled/
        disabled tooltip + red-text pattern as the other dirty-tracked
        buttons on this tab; resolved via tr() here (not cached class
        constants) so they always reflect the active language."""
        self._prefix_dirty = dirty
        self._apply_prefix_btn.setEnabled(dirty)
        self._apply_prefix_btn.setToolTip(
            tr("enhancements.prefix_enabled_tooltip") if dirty
            else tr("enhancements.prefix_disabled_tooltip")
        )
        self._apply_prefix_btn.setStyleSheet(
            f"color: {get_button_color('needs_apply')};" if dirty else ""
        )

    def _mark_prefix_dirty(self, *_args) -> None:
        """Recompute dirty state whenever the prefix combo selection
        changes — dirty only when it actually differs from what's saved."""
        self._set_prefix_btn_dirty(self.favorite_prefix_combo.currentData() != self._loaded_prefix)

    def _apply_favorite_prefix(self):
        new_prefix = self.favorite_prefix_combo.currentData()
        if not new_prefix:
            return

        old_prefix = self._loaded_prefix

        if new_prefix != old_prefix:
            overrides_path = AppSettings.get_user_ini_path()
            if overrides_path.exists():
                try:
                    lines = overrides_path.read_text(encoding="utf-8").splitlines()
                    updated = []
                    migrated = 0
                    for line in lines:
                        if "=" in line:
                            key, _, value = line.partition("=")
                            if value.startswith(old_prefix):
                                value = new_prefix + value[len(old_prefix):]
                                migrated += 1
                            updated.append(f"{key}={value}")
                        else:
                            updated.append(line)
                    overrides_path.write_text("\n".join(updated), encoding="utf-8")
                    logger.info(f"Migrated {migrated} favorites from '{old_prefix}' to '{new_prefix}'")
                except Exception as e:
                    logger.exception(f"Failed to migrate favorites: {e}")
                    QMessageBox.critical(self, tr("dialogs.error_title"), f"Failed to update favorites: {e}")
                    return

        AppSettings.set_favorite_prefix(new_prefix)
        self._loaded_prefix = new_prefix
        self._set_prefix_btn_dirty(False)
        # Hand the old/new prefix to MainWindow so it can re-prefix in-memory
        # favourites before the reload (see signal doc). Emitting merge_requested
        # alone would let the pending-edit snapshot restore the old prefix.
        self.favorite_prefix_changed.emit(old_prefix, new_prefix)

    # ── Operation state ───────────────────────────────────────────────────────

    def set_operation_running(self, message: str):
        self._generate_enhancements_btn.setEnabled(False)
        self._generate_enhancements_btn.setToolTip(message)

    def set_operation_idle(self, success: bool = True):
        """Re-enable after a background run. A successful run means
        mark_enhancements_clean() already cleared the dirty flag when the
        run was launched (#292), so leave it grey unless something changed
        mid-run; a failed run re-enables unconditionally so the user has a
        way to retry without first having to touch an unrelated setting."""
        if not success:
            self._enhancements_dirty = True
        self._set_generate_btn_dirty(self._enhancements_dirty)

    # ── Status refresh ────────────────────────────────────────────────────────

    def refresh_enhancements_status(self):
        """Update enhancement file status indicators and DataForge cache status.

        Reads get_enhancements_dir() for the same reason
        _compute_initial_enhancements_dirty does: the generator writes each
        language's INIs to cache/lang/{language}, and only English collapses
        onto the channel root. These dots sit directly beside the Generate
        Enhancements button, so leaving them on get_cache_dir() while that
        button reads the per-language dir let the two contradict each other
        outright -- a German user with English enhancements generated saw
        every category green AND the button lit, at the same time.
        """
        enh_dir = AppSettings.get_enhancements_dir()
        for key, dot in self._enhancements_status_labels.items():
            # Check all files controlled by this checkbox
            filenames = self._files_for_category(key)
            all_present = all((enh_dir / fn).exists() for fn in filenames)
            dot.setStyleSheet(f"color: {'#4caf50' if all_present else '#f44336'}; font-size: 12px;")
        self.refresh_forge_status()

    def refresh_forge_status(self):
        """Update the DataForge cache status label."""
        from src.utils.pak_extractor import P4K_MTIME_STAMP, dataforge_cache_is_fresh
        forge_dir = AppSettings.get_dataforge_cache_dir()
        p4k_path = AppSettings.get_p4k_path()
        if not (forge_dir / P4K_MTIME_STAMP).exists():
            self._forge_status_label.setText(tr("enhancements.forge_status_not_extracted"))
            self._forge_status_label.setStyleSheet("font-size: 10px; color: #f44336;")
        elif p4k_path.exists() and not dataforge_cache_is_fresh(p4k_path, forge_dir):
            self._forge_status_label.setText(tr("enhancements.forge_status_outdated"))
            self._forge_status_label.setStyleSheet("font-size: 10px; color: #ff9800;")
        else:
            self._forge_status_label.setText(tr("enhancements.forge_status_up_to_date"))
            self._forge_status_label.setStyleSheet("font-size: 10px; color: #4caf50;")

    # ── Tag Builder (issue #31) ──────────────────────────────────────────────

    def _build_tag_builder_group(self) -> QGroupBox:
        """Construct the Tag Builder QGroupBox shown below Favorites.

        Each supported category (components, missiles, ship_weapons) gets a
        tab page with an element list (reorderable via the ▲/▼ buttons),
        per-element style dropdowns, separator/enclosing/placement
        dropdowns, and a live preview. The "Apply Tag Builder" button at
        the bottom persists every page's config and re-runs the enhancement
        generator so the new tags take effect immediately."""
        group = QGroupBox(tr("enhancements.tag_builder_group"))
        self._tag_builder_group_box = group
        gl = QVBoxLayout(group)

        self._tag_builder_desc_label = QLabel(tr("enhancements.tag_builder_desc"))
        self._tag_builder_desc_label.setProperty("role", "secondary")
        self._tag_builder_desc_label.setStyleSheet("font-size: 11px;")
        self._tag_builder_desc_label.setWordWrap(True)
        gl.addWidget(self._tag_builder_desc_label)

        self._tag_builder_tabs = QTabWidget()
        self._tag_builder_tabs.setTabBar(_NoScrollTabBar())
        self._tag_builder_pages: dict[str, _TagBuilderPage] = {}
        for cat in CATEGORIES:
            cfg = AppSettings.get_tag_config(cat)
            page = _TagBuilderPage(cat, cfg)
            page.config_changed.connect(self._mark_tag_dirty)
            self._tag_builder_pages[cat] = page
            self._tag_builder_tabs.addTab(page, _CATEGORY_LABELS[cat])
        gl.addWidget(self._tag_builder_tabs)

        # Issue #31 follow-up: cross-surface toggle for the inline
        # component annotation inside mission POTENTIAL BLUEPRINTS lists.
        # Default ON preserves v1.4.0 behavior. When off, mission bodies
        # render bare names ("Norfield") even though the same component
        # on the strings tab still shows the configured tag. The toggle
        # is persisted alongside the per-category configs and applied
        # by the same "Save Tag Changes" button below — no separate
        # save action so the user can't end up with the toggle and the
        # configs out of sync on disk.
        self._annotate_mission_descs_cb = QCheckBox(
            tr("enhancements.annotate_mission_descs_cb")
        )
        self._annotate_mission_descs_cb.setChecked(
            AppSettings.get_tag_annotate_mission_descs()
        )
        self._annotate_mission_descs_cb.toggled.connect(self._mark_tag_dirty)
        self._annotate_mission_descs_cb.setToolTip(tr("enhancements.annotate_mission_descs_tooltip"))
        gl.addWidget(self._annotate_mission_descs_cb)

        btn_row = QHBoxLayout()
        self._apply_tag_btn = QPushButton(tr("enhancements.apply_tag_changes_btn"))
        self._apply_tag_btn.clicked.connect(self._apply_tag_builder)
        btn_row.addWidget(self._apply_tag_btn)
        # #363: derive the starting state rather than asserting clean. This
        # was an unconditional _set_tag_btn_dirty(False), which made launch
        # the one moment the freshness check never ran — it was wired only to
        # the channel switch — so INIs that didn't match the tag config were
        # invisible on startup behind two grey buttons. See the module
        # docstring of tests/test_tag_config_staleness_startup.py for the
        # reported symptom and why cycling the checkbox appeared to fix it.
        # Safe here: the pages, the annotate checkbox and _apply_tag_btn are
        # all built above, so the fingerprint comes from the live pages.
        self.refresh_tag_builder_dirty_state()

        self._reset_tag_btn = QPushButton(tr("enhancements.reset_defaults_btn"))
        self._reset_tag_btn.setToolTip(tr("enhancements.reset_tag_tooltip"))
        self._reset_tag_btn.clicked.connect(self._reset_all_tag_builder_pages)
        btn_row.addWidget(self._reset_tag_btn)

        btn_row.addStretch()
        gl.addLayout(btn_row)
        return group

    # ── Retranslation ─────────────────────────────────────────────────────────

    def retranslate_ui(self) -> None:
        """Re-apply tr() to every text-bearing widget after a language switch."""
        self._title_label.setText(tr("enhancements.title"))
        self._desc_label.setText(tr("enhancements.desc"))
        self._enhancements_group_box.setTitle(tr("enhancements.enhancements_group"))
        self._enhancements_desc_label.setText(tr("enhancements.enhancements_desc"))
        self._apply_categories_btn.setText(tr("enhancements.apply_btn"))
        self._apply_categories_btn.setToolTip(tr("enhancements.apply_categories_tooltip"))
        self._generate_enhancements_btn.setText(tr("enhancements.generate_btn"))
        self._set_generate_btn_dirty(self._enhancements_dirty)
        _CAT_KEYS = {
            "ships":       "enhancements.cat_desc_ships",
            "ship_items":  "enhancements.cat_desc_ship_items",
            "gear":        "enhancements.cat_desc_gear",
            "missions":    "enhancements.cat_desc_missions",
            "commodities": "enhancements.cat_desc_commodities",
            "journal":     "enhancements.cat_desc_journal",
            "medical_consumables": "enhancements.cat_desc_medical_consumables",
        }
        for key, lbl in self._cat_desc_labels.items():
            if key in _CAT_KEYS:
                lbl.setText(tr(_CAT_KEYS[key]))
        self._mf_heading.setText(tr("enhancements.mission_detail_fields_heading"))
        self._mission_field_labels = [(f, tr(k)) for f, k in self._mission_field_keys]
        _mf_label_by_field = dict(self._mission_field_labels)
        for field, cb in self._mission_field_checkboxes.items():
            label = _mf_label_by_field.get(field, field)
            cb.setText(label)
            cb.setToolTip(self._mission_field_tooltip(field, label))
        self._mf_note.setText(tr("enhancements.mission_detail_fields_note"))
        self._stats_prepend_check.setText(tr("enhancements.stats_prepend_cb"))
        self._stats_prepend_check.setToolTip(tr("enhancements.stats_prepend_tooltip"))
        self._standardize_ship_names_check.setText(tr("enhancements.standardize_ship_names_cb"))
        self._standardize_ship_names_check.setToolTip(tr("enhancements.standardize_ship_names_tooltip"))
        self._rs_ore_name_annotations_check.setText(tr("enhancements.rs_ore_name_annotations_cb"))
        self._rs_ore_name_annotations_check.setToolTip(tr("enhancements.rs_ore_name_annotations_tooltip"))
        self._favorites_group_box.setTitle(tr("enhancements.favorites_group"))
        self._favorites_desc_label.setText(tr("enhancements.favorites_desc"))
        self._sort_prefix_label.setText(tr("enhancements.sort_prefix_label"))
        self.favorite_prefix_combo.setToolTip(tr("enhancements.favorite_prefix_tooltip"))
        self._apply_prefix_btn.setText(tr("enhancements.apply_btn"))
        self._set_prefix_btn_dirty(self._prefix_dirty)

        # Mission Labels group
        self.mission_labels_group.setTitle(tr("enhancements.mission_labels_group"))
        for lbl_widget, lbl_key in self._mission_label_widgets:
            lbl_widget.setText(tr(lbl_key))
        self._xp_label_widget.setText(tr("enhancements.mission_label_xp"))
        self._header_style_label_widget.setText(tr("enhancements.mission_label_header_style"))
        self._rep_xp_label_input.setToolTip(tr("enhancements.rep_xp_label_tooltip"))
        self._header_em_combo.setToolTip(tr("enhancements.header_em_tooltip"))
        self._header_em_combo.blockSignals(True)
        try:
            for i in range(self._header_em_combo.count()):
                self._header_em_combo.setItemText(i, self._em_label(self._header_em_combo.itemData(i)))
        finally:
            self._header_em_combo.blockSignals(False)

        # Tag Builder pages (element rows, Mission Titles page, etc.)
        for page in getattr(self, "_tag_builder_pages", {}).values():
            page.retranslate_ui()
        self.refresh_forge_status()

        self._tag_builder_group_box.setTitle(tr("enhancements.tag_builder_group"))
        self._tag_builder_desc_label.setText(tr("enhancements.tag_builder_desc"))
        self._annotate_mission_descs_cb.setText(tr("enhancements.annotate_mission_descs_cb"))
        self._annotate_mission_descs_cb.setToolTip(tr("enhancements.annotate_mission_descs_tooltip"))
        self._apply_tag_btn.setText(tr("enhancements.apply_tag_changes_btn"))
        self._set_tag_btn_dirty(self._tag_dirty)
        self._reset_tag_btn.setText(tr("enhancements.reset_defaults_btn"))
        self._reset_tag_btn.setToolTip(tr("enhancements.reset_tag_tooltip"))

    def _persist_tag_builder_state(self) -> None:
        """Save every Tag Builder page's TagConfig plus the annotate-descs
        toggle to settings.

        Shared by the dedicated *Save Tag Changes* button and the *Generate
        Enhancements* button (#215): whichever the user clicks, the on-screen
        Tag Builder state is what gets generated, so a toggled-off label (e.g.
        the commodity CF flag) can't linger just because the config wasn't
        saved first. Guarded with getattr so it's a safe no-op if the Tag
        Builder group hasn't been built."""
        pages = getattr(self, "_tag_builder_pages", None)
        if not pages:
            return
        for cat, page in pages.items():
            AppSettings.set_tag_config(cat, page.config)
        annotate_cb = getattr(self, "_annotate_mission_descs_cb", None)
        if annotate_cb is not None:
            AppSettings.set_tag_annotate_mission_descs(annotate_cb.isChecked())
        logger.info("Tag Builder: saved configs for %s", ", ".join(pages))

    def reload_tag_builder_from_settings(self) -> None:
        """Re-read every Tag Builder page from settings, discarding UI state.

        Import Settings rewrites the ``tag_builder/*`` keys underneath a tab
        that was built at launch, so the on-screen pages still hold the
        *pre-import* config. That stale state is not just cosmetic: the next
        ``_persist_tag_builder_state()`` — reachable from Save Tag Changes,
        Generate Enhancements, *and* Export Settings — would write it back
        over everything the import just restored. Refreshing here keeps the
        widgets and settings in agreement, so none of those paths can
        resurrect the old config (and a user who picks "Restart Later" sees
        their imported tags immediately).

        Same shape as :meth:`revert_category_checkboxes`, which MainWindow
        already calls to resync the category checkboxes from settings.
        """
        pages = getattr(self, "_tag_builder_pages", None)
        if not pages:
            return
        for cat, page in pages.items():
            page.apply_config(AppSettings.get_tag_config(cat))
        annotate_cb = getattr(self, "_annotate_mission_descs_cb", None)
        if annotate_cb is not None:
            annotate_cb.blockSignals(True)
            annotate_cb.setChecked(AppSettings.get_tag_annotate_mission_descs())
            annotate_cb.blockSignals(False)
        # apply_config emits config_changed per page, which lights the Save
        # button — but nothing is actually *unsaved* here, so drop that
        # signal. #363: re-derive rather than clearing outright, though. An
        # import that changes the tag config leaves the generated INIs built
        # from the pre-import one, and clearing unconditionally hid that the
        # same way launch did: grey button, stale output, no way to tell.
        # The pages now equal the persisted config, so this reports only
        # genuine staleness and never the unsaved edits it's here to drop.
        self.refresh_tag_builder_dirty_state()
        logger.info("Tag Builder: reloaded configs from settings for %s", ", ".join(pages))

    def flush_pending_tag_edits(self) -> None:
        """Persist on-screen Tag Builder edits *without* regenerating.

        Same "what you see is what you save" contract as Generate
        Enhancements (#215), for callers that need settings to match the UI
        but must not kick off the pipeline. Export Settings uses this so a
        backup captures the Tag Builder state the user is looking at, not
        whatever was last committed via Save Tag Changes.
        """
        self._persist_tag_builder_state()
        # #363: persisting is not regenerating. Clearing the button outright
        # here threw away a correct "you still need to regenerate" signal the
        # user had already been shown: edit the Tag Builder, click Export
        # Settings, and the edits landed in settings while the INIs kept the
        # old config — stale output behind a grey button, the same end state
        # as the launch and import cases. Re-deriving keeps it lit for exactly
        # as long as the output really is behind.
        self.refresh_tag_builder_dirty_state()

    def _set_tag_btn_dirty(self, dirty: bool) -> None:
        """Single chokepoint for the button's enabled state, tooltip, and
        text color so none of the three can drift apart. Same enabled/
        disabled tooltip pattern as Generate Enhancements; resolved via
        tr() here (not cached class constants) so they always reflect
        the active language."""
        self._tag_dirty = dirty
        self._apply_tag_btn.setEnabled(dirty)
        self._apply_tag_btn.setToolTip(
            tr("enhancements.tag_enabled_tooltip") if dirty
            else tr("enhancements.tag_disabled_tooltip")
        )
        self._apply_tag_btn.setStyleSheet(
            f"color: {get_button_color('needs_apply')};" if dirty else ""
        )

    def _mark_tag_dirty(self, *_args):
        """A Tag Builder config changed since the last save — light the
        Save Tag Changes button back up."""
        self._set_tag_btn_dirty(True)

    def _apply_tag_builder(self):
        """Persist every page's TagConfig and kick off enhancement regen."""
        self._persist_tag_builder_state()
        # Re-run the generator so the new tags show up in the output INIs;
        # MainWindow handles the worker lifecycle + progress UI.
        self.enhancements_pipeline_requested.emit()
        self._set_tag_btn_dirty(False)

    def _on_generate_enhancements_clicked(self):
        """Generate Enhancements entry point.

        Persists the current Tag Builder edits first (#215) so "what you see is
        what you generate" — previously only the separate *Save Tag Changes*
        button saved them, so a user who disabled a tag and clicked Generate
        still got the old tag in the output.
        """
        self._persist_tag_builder_state()
        # enhancements_pipeline_requested is a direct connection, so by the
        # time emit() returns MainWindow._run_enhancements_pipeline has
        # already called mark_enhancements_clean() for us (#292) — no need
        # to clear the dirty flag here too.
        self.enhancements_pipeline_requested.emit()
        # Generate also persists Tag Builder edits (see docstring above), so
        # it satisfies Save Tag Changes too — otherwise that button would
        # stay lit for a save that already happened.
        self._set_tag_btn_dirty(False)

    def _reset_all_tag_builder_pages(self):
        """Reset every category's tag config back to its built-in default.

        Resets in-memory only — the user still has to click Apply Tag
        Changes to persist + regenerate. That matches the per-page Edit
        mapping… flow where edits are tentative until Apply.
        """
        for page in self._tag_builder_pages.values():
            page._reset_to_defaults()


# ── Tag Builder helpers ──────────────────────────────────────────────────────
# Row + page widgets live alongside the tab so the live-preview wiring stays
# local. The mapping editor (TagMappingDialog) is in its own module because
# it's a modal dialog and gets reused by all three pages.


class _ElementRow(QWidget):
    """One element row inside a category's reorderable container.

    Holds the live ``ElementSpec`` from the parent's ``TagConfig`` so toggle
    + style-change events mutate the config in place. The page listens to
    ``changed`` to refresh its preview, to ``edit_mapping_requested`` to
    open the ``TagMappingDialog``, and to ``move_up`` / ``move_down`` to
    swap rows in the element list.
    """

    changed = pyqtSignal()
    edit_mapping_requested = pyqtSignal()
    move_up = pyqtSignal()
    move_down = pyqtSignal()

    # Sample raw value used to build dynamic style-dropdown labels for
    # mapped kinds. Picked to match the values in _PREVIEW_VALUES so the
    # dropdown's parenthetical hint matches what the user sees in the
    # preview row below. Unmapped kinds (size, grade) ignore this and use
    # the static STYLES_BY_KIND labels.
    _SAMPLE_MAPPED_RAW: dict[str, str] = {
        "class":      "Military",
        "ordinance":  "Infrared",
        "damage":     "Energy",
        "type":       "Shield Generator",
        "label":      "Crafting",
        "collection": "Collection",
    }

    def __init__(self, spec, mapping: dict | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.spec = spec  # ElementSpec from src.utils.tag_builder
        self._mapping = mapping or {}
        # Lock vertical size so the page's QVBoxLayout can't stretch a
        # single row to fill the tab — that's the symptom that produced
        # the overlapping-text bug.
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        row = QHBoxLayout(self)
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(8)

        # Up/down reorder buttons, leading the row so users can't miss them.
        # QPushButton (not QToolButton) so they have visible chrome under
        # every theme; explicit width to keep them stacked tightly.
        self.up_btn = QPushButton("▲")
        self.up_btn.setToolTip(tr("enhancements.tag_move_up_tooltip"))
        self.up_btn.setFixedSize(28, 26)
        self.up_btn.clicked.connect(self.move_up.emit)
        row.addWidget(self.up_btn)

        self.down_btn = QPushButton("▼")
        self.down_btn.setToolTip(tr("enhancements.tag_move_down_tooltip"))
        self.down_btn.setFixedSize(28, 26)
        self.down_btn.clicked.connect(self.move_down.emit)
        row.addWidget(self.down_btn)

        self.enable_cb = QCheckBox()
        self.enable_cb.setChecked(spec.enabled)
        self.enable_cb.setToolTip(tr("enhancements.tag_untick_exclude_tooltip"))
        self.enable_cb.toggled.connect(self._on_enabled_toggled)
        row.addWidget(self.enable_cb)

        self.label = QLabel(ELEMENT_LABELS.get(spec.kind, spec.kind))
        self.label.setMinimumWidth(90)
        row.addWidget(self.label)

        self.style_combo = _NoScrollComboBox()
        for style_key, style_label in STYLES_BY_KIND.get(spec.kind, ()):
            self.style_combo.addItem(
                self._build_style_label(spec.kind, style_key, style_label),
                userData=style_key,
            )
        target_idx = 0
        for i in range(self.style_combo.count()):
            if self.style_combo.itemData(i) == spec.style:
                target_idx = i
                break
        self.style_combo.setCurrentIndex(target_idx)
        if self.style_combo.currentData() is not None:
            self.spec.style = self.style_combo.currentData()
        self.style_combo.currentIndexChanged.connect(self._on_style_changed)
        row.addWidget(self.style_combo)

        # Only kinds backed by the per-category variant mapping get the
        # mapping-edit button — size and grade are derived from raw values
        # and have nothing user-editable beyond style.
        self.edit_btn = None
        if spec.kind in MAPPED_KIND_NAMES:
            self.edit_btn = QPushButton(tr("enhancements.tag_edit_mapping_row_btn"))
            self.edit_btn.setToolTip(tr(self._mapping_tooltip_key(spec.kind)))
            self.edit_btn.clicked.connect(self.edit_mapping_requested.emit)
            row.addWidget(self.edit_btn)

        row.addStretch()

    @staticmethod
    def _mapping_tooltip_key(kind: str) -> str:
        return {
            "ordinance": "enhancements.tag_mapping_tooltip_ordinance",
            "damage": "enhancements.tag_mapping_tooltip_damage",
            "type": "enhancements.tag_mapping_tooltip_type",
            "label": "enhancements.tag_mapping_tooltip_label",
            "collection": "enhancements.tag_mapping_tooltip_collection",
        }.get(kind, "enhancements.tag_mapping_tooltip_default")

    def retranslate_ui(self) -> None:
        """Re-apply tr() to this row's static chrome after a language switch."""
        self.up_btn.setToolTip(tr("enhancements.tag_move_up_tooltip"))
        self.down_btn.setToolTip(tr("enhancements.tag_move_down_tooltip"))
        self.enable_cb.setToolTip(tr("enhancements.tag_untick_exclude_tooltip"))
        if self.edit_btn is not None:
            self.edit_btn.setText(tr("enhancements.tag_edit_mapping_row_btn"))
            self.edit_btn.setToolTip(tr(self._mapping_tooltip_key(self.spec.kind)))

    def _on_enabled_toggled(self, checked: bool):
        self.spec.enabled = bool(checked)
        # Dim the row so disabled state is visually obvious.
        self.label.setEnabled(checked)
        self.style_combo.setEnabled(checked)
        self.changed.emit()

    def _on_style_changed(self, _idx: int):
        data = self.style_combo.currentData()
        if data is not None:
            self.spec.style = data
            self.changed.emit()

    def set_move_enabled(self, can_up: bool, can_down: bool) -> None:
        self.up_btn.setEnabled(can_up)
        self.down_btn.setEnabled(can_down)

    def _build_style_label(self, kind: str, style_key: str, fallback: str) -> str:
        """Return the dropdown label for a style.

        For mapped kinds (class/ordinance/damage), build the label from the
        current user mapping so an edit like Military Short → "ML" shows up
        as "Short (ML)" instead of the baked-in "Short (M)". For unmapped
        kinds (size/grade) the static STYLES_BY_KIND label is the natural
        thing to show.
        """
        sample = self._SAMPLE_MAPPED_RAW.get(kind)
        if sample is None:
            return fallback
        variants = self._mapping.get(sample)
        if not variants:
            return fallback
        idx_by_style = {"short": 0, "med": 1, "long": 2}
        idx = idx_by_style.get(style_key, 1)
        try:
            variant_text = variants[idx]
        except IndexError:
            return fallback
        # Strip the parenthetical sample from the fallback label
        # ("Short (M)" → "Short") and re-attach with the live mapping value.
        base = fallback.split(" (")[0]
        return f"{base} ({variant_text})"


class _TagBuilderPage(QWidget):
    """One category's Tag Builder page (element list + separator/enclosing
    dropdowns + live preview + Reset button)."""

    # Fired on every user-driven config mutation (never during construction)
    # so the tab can light up its Save Tag Changes button.
    config_changed = pyqtSignal()

    def __init__(self, category: str, config: TagConfig, parent: QWidget | None = None):
        super().__init__(parent)
        self.category = category
        self.config = config
        self._rows: list[_ElementRow] = []
        self.usage_sep_combo = None

        # Mission Titles is a purpose-built page (route controls, not element
        # rows + variant mappings), so it has its own layout branch.
        if category == "mission_titles":
            self._build_mission_titles_page()
            return

        # Rows + separator/preview/reset go directly into the page's own
        # QVBoxLayout. An earlier iteration wrapped this in a QScrollArea
        # to avoid forcing a hard minimum height up the widget tree (which
        # was squeezing the main window's footer), but the scroll area
        # introduced its own dark "Base" palette background and made the
        # Apply Tag Builder button render against the group-box border.
        # With the Localization Enhancements section now using a two-column
        # grid (freeing ~84px of vertical space), the natural layout
        # comfortably fits without needing scroll/min-height tricks.
        top = QHBoxLayout(self)
        top.setContentsMargins(8, 4, 8, 4)
        top.setSpacing(12)

        # ── Left: element rows ────────────────────────────────────────
        self._rows_column = QVBoxLayout()
        self._rows_column.setSpacing(2)
        self._page_layout = self._rows_column
        self._rows_insert_at = 0
        self._repopulate_list()
        self._rows_column.addStretch()
        top.addLayout(self._rows_column, 0)

        # ── Right: controls + preview ─────────────────────────────────
        right = QVBoxLayout()
        right.setSpacing(4)

        ctrl_grid = QGridLayout()
        ctrl_grid.setVerticalSpacing(4)
        ctrl_grid.setHorizontalSpacing(6)

        self._sep_label = QLabel(tr("enhancements.tag_separator_label"))
        ctrl_grid.addWidget(self._sep_label, 0, 0)
        self.sep_combo = _NoScrollComboBox()
        for key, label, _ in SEPARATORS:
            # "None" is offered for every category, commodities included: a
            # deliberate no-separator commodity tag renders "[CFCollection]".
            # A legacy leftover "none" is upgraded once to "pipe" by
            # AppSettings.get_tag_config so existing users don't regress (#97).
            self.sep_combo.addItem(label, userData=key)
        self._select_combo(self.sep_combo, config.separator)
        self.sep_combo.currentIndexChanged.connect(self._on_sep_changed)
        ctrl_grid.addWidget(self.sep_combo, 0, 1)

        self._enc_label = QLabel(tr("enhancements.tag_enclosing_label"))
        ctrl_grid.addWidget(self._enc_label, 1, 0)
        self.enc_combo = _NoScrollComboBox()
        for key, label, _open, _close in ENCLOSINGS:
            self.enc_combo.addItem(label, userData=key)
        self._select_combo(self.enc_combo, config.enclosing)
        self.enc_combo.currentIndexChanged.connect(self._on_enc_changed)
        ctrl_grid.addWidget(self.enc_combo, 1, 1)

        self._placement_label = QLabel(tr("enhancements.tag_placement_label"))
        ctrl_grid.addWidget(self._placement_label, 2, 0)
        self.placement_combo = _NoScrollComboBox()
        for key, label in PLACEMENTS:
            self.placement_combo.addItem(label, userData=key)
        self._select_combo(self.placement_combo, config.placement)
        self.placement_combo.currentIndexChanged.connect(self._on_placement_changed)
        ctrl_grid.addWidget(self.placement_combo, 2, 1)

        # Commodities get a second separator: the one used INSIDE the multi-value
        # "Used To Craft" element, independent of the element separator above.
        self.usage_sep_combo = None
        self._usage_sep_label = None
        if self.category == "commodities":
            self._usage_sep_label = QLabel(tr("enhancements.tag_craft_usage_separator_label"))
            ctrl_grid.addWidget(self._usage_sep_label, 3, 0)
            self.usage_sep_combo = _NoScrollComboBox()
            for key, label, _ in SEPARATORS:
                self.usage_sep_combo.addItem(label, userData=key)
            self._select_combo(self.usage_sep_combo, config.usage_separator)
            self.usage_sep_combo.currentIndexChanged.connect(self._on_usage_sep_changed)
            ctrl_grid.addWidget(self.usage_sep_combo, 3, 1)

        right.addLayout(ctrl_grid)

        self.preview_label = QLabel()
        self.preview_label.setMinimumHeight(28)
        self.preview_label.setStyleSheet(
            "font-family: Consolas, 'Courier New', monospace; "
            "font-size: 12px; padding: 4px; "
            "background: rgba(0, 0, 0, 30); border-radius: 3px;"
        )
        right.addWidget(self.preview_label)
        right.addStretch()
        top.addLayout(right, 0)
        top.addStretch(1)

        self._refresh_preview()

    # ── Row population + reorder ─────────────────────────────────────────

    # Fixed pixel height for each row widget; pinned on the row itself
    # (setFixedHeight below) so the page's QVBoxLayout can't stretch it
    # on first show.
    _ROW_H = 32

    def _repopulate_list(self) -> None:
        """Rebuild the row widgets from ``self.config.elements`` in order.

        Rows live directly in ``self._page_layout`` between the hint label
        and the separator/enclosing/placement row — no nested container.
        Insertion index is tracked in ``self._rows_insert_at`` and stays
        valid because we remove every existing row before adding new ones.
        """
        # Remove every existing row from the layout + delete the widget.
        for row in self._rows:
            self._page_layout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()

        insert_at = self._rows_insert_at
        for idx, spec in enumerate(self.config.elements):
            row_widget = _ElementRow(spec, mapping=self.config.class_mapping)
            row_widget.setFixedHeight(self._ROW_H)
            row_widget.changed.connect(self._refresh_preview)
            row_widget.changed.connect(self.config_changed.emit)
            row_widget.edit_mapping_requested.connect(
                lambda _checked=False, k=spec.kind: self._open_mapping_dialog(k)
            )
            row_widget.move_up.connect(lambda i=idx: self._move_row(i, -1))
            row_widget.move_down.connect(lambda i=idx: self._move_row(i, +1))
            # Initial enabled-state visual sync — the row constructor sets
            # checkbox state but doesn't fire toggled, so dim styling is
            # applied here.
            row_widget.label.setEnabled(spec.enabled)
            row_widget.style_combo.setEnabled(spec.enabled)
            self._page_layout.insertWidget(insert_at + idx, row_widget)
            self._rows.append(row_widget)

        # Disable the up-arrow on the first row and down-arrow on the
        # last, so users can't move rows off the ends.
        n = max(len(self._rows), 1)
        for i, r in enumerate(self._rows):
            r.set_move_enabled(can_up=(i > 0), can_down=(i < n - 1))

        # Equalize style-combo and label widths across all rows so columns
        # line up visually.
        if self._rows:
            max_combo = max(r.style_combo.sizeHint().width() for r in self._rows)
            max_label = max(r.label.sizeHint().width() for r in self._rows)
            for r in self._rows:
                r.style_combo.setMinimumWidth(max_combo)
                r.label.setMinimumWidth(max_label)

    def _move_row(self, index: int, delta: int) -> None:
        """Swap ``self.config.elements[index]`` with its neighbor at
        ``index + delta`` (delta is -1 or +1) and rebuild the row list."""
        target = index + delta
        if target < 0 or target >= len(self.config.elements):
            return
        elems = self.config.elements
        elems[index], elems[target] = elems[target], elems[index]
        self._repopulate_list()
        self._refresh_preview()
        self.config_changed.emit()

    # ── Separator/Enclosing change handlers ──────────────────────────────

    def _on_sep_changed(self, _idx: int):
        data = self.sep_combo.currentData()
        if data is not None:
            self.config.separator = data
            self._refresh_preview()
            self.config_changed.emit()

    def _on_enc_changed(self, _idx: int):
        data = self.enc_combo.currentData()
        if data is not None:
            self.config.enclosing = data
            self._refresh_preview()
            self.config_changed.emit()

    def _on_placement_changed(self, _idx: int):
        data = self.placement_combo.currentData()
        if data is not None:
            self.config.placement = data
            self._refresh_preview()
            self.config_changed.emit()

    def _on_usage_sep_changed(self, _idx: int):
        data = self.usage_sep_combo.currentData()
        if data is not None:
            self.config.usage_separator = data
            self._refresh_preview()
            self.config_changed.emit()

    # ── Mapping editor ───────────────────────────────────────────────────

    def _open_mapping_dialog(self, kind: str | None = None):
        """Open the variant-mapping editor for a specific element kind.

        Filters the shared class_mapping to only the keys belonging to
        *kind* so the user sees Class entries OR Type entries, not both.
        On accept, merges the edited subset back into the full mapping."""
        from src.utils.tag_builder import CATEGORY_ELEMENT_KINDS, DEFAULT_KIND_MAPPINGS
        kind_defaults = DEFAULT_KIND_MAPPINGS.get(kind, {})
        # Keys that belong to OTHER kinds *in this category* — exclude them from
        # this dialog. Scoped to the category (not all kinds globally) because
        # some keys collide across categories: component "type" and commodity
        # "usage" both map "Power Plant" / "Cooler" / "Quantum Drive" / "Radar"
        # with different codes, so a global exclusion would hide those rows when
        # editing commodity usage.
        category_kinds = set(CATEGORY_ELEMENT_KINDS.get(self.category, ()))
        other_keys = set()
        for other_kind in category_kinds:
            if other_kind != kind:
                other_keys.update(DEFAULT_KIND_MAPPINGS.get(other_kind, {}).keys())
        kind_mapping = {k: v for k, v in self.config.class_mapping.items() if k not in other_keys}

        kind_label = ELEMENT_LABELS.get(kind, kind or self.category)
        title = f"Edit {kind_label} variants"
        dialog = TagMappingDialog(
            kind_mapping, kind_defaults, title, parent=self,
        )
        if dialog.exec():
            result = dialog.result_mapping()
            for k in list(self.config.class_mapping):
                if k not in other_keys:
                    del self.config.class_mapping[k]
            self.config.class_mapping.update(result)
            self._repopulate_list()
            self._refresh_preview()
            self.config_changed.emit()

    # ── Mission Titles page (route controls) ─────────────────────────────

    def _build_mission_titles_page(self) -> None:
        """Purpose-built page for the mission-title route: an enable toggle plus
        placement / arrow / separator / location-detail combos and a preview."""
        # Hauling missions get their own titled box rather than filling the
        # whole page, so future mission types (bounty, delivery, etc.) can
        # sit as sibling boxes in the empty space to the right without a
        # layout rework later.
        page = QHBoxLayout(self)
        page.setContentsMargins(10, 6, 10, 6)
        page.setSpacing(12)

        self._mt_group = QGroupBox(tr("enhancements.mt_hauling_group"))
        col = QVBoxLayout(self._mt_group)
        col.setContentsMargins(10, 10, 10, 10)
        col.setSpacing(6)
        page.addWidget(self._mt_group)

        top_row = QHBoxLayout()
        self._mt_enable = QCheckBox(tr("enhancements.mt_enable_route_cb"))
        route_el = next((e for e in self.config.elements if e.kind == "route"), None)
        self._mt_enable.setChecked(bool(route_el and route_el.enabled))
        self._mt_enable.toggled.connect(self._on_mt_enable)
        top_row.addWidget(self._mt_enable)

        self._mt_standardize = QCheckBox(tr("enhancements.mt_standardize_cb"))
        self._mt_standardize.setChecked(
            getattr(self.config, "standardize_hauling_names", False)
        )
        self._mt_standardize.toggled.connect(self._on_mt_standardize_toggle)
        top_row.addWidget(self._mt_standardize)
        top_row.addStretch()
        col.addLayout(top_row)

        self._mt_hint = QLabel(tr("enhancements.mt_route_hint"))
        self._mt_hint.setProperty("role", "secondary")
        self._mt_hint.setStyleSheet("font-size: 11px;")
        self._mt_hint.setWordWrap(True)
        col.addWidget(self._mt_hint)

        def _combo(items) -> QComboBox:
            c = _NoScrollComboBox()
            for entry in items:
                c.addItem(entry[1], userData=entry[0])
            # AdjustToContents (rather than the default
            # AdjustToContentsOnFirstShow) so sizeHint() below reflects every
            # item's width immediately, before the widget is ever shown.
            c.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
            return c

        enabled_phrases = set(getattr(self.config, "abbreviated_phrases", frozenset()))
        shortened_sizes = set(getattr(self.config, "shortened_sizes", frozenset()))
        _shorten_phrase_keys = frozenset(k for k, *_ in SHORTEN_PHRASE_OPTIONS)

        # #200 follow-up, generalized: one grid pairs each dropdown with a
        # checkbox on the same row (label | combo | gap | checkbox), so the
        # page reads as 5 aligned rows instead of separate blocks. Column 2
        # is a deliberately empty spacer — tight label-to-combo spacing plus
        # one wider gap before the checkboxes, rather than uniform spacing
        # everywhere. Rank separator moved in here (after Title separator)
        # instead of its own row. Each checkbox's example lives in
        # parentheses in its own label (one line) instead of a separate
        # description widget. "Underline Direct" doesn't pair with a
        # dropdown, so it sits as its own row below the grid.
        self._mt_placement = _combo(MISSION_TITLE_PLACEMENTS)
        self._mt_arrow = _combo(ROUTE_ARROWS)
        self._mt_sep = _combo(TITLE_SEPARATORS)
        self._mt_rank_sep = _combo(RANK_SEPARATORS)
        self._mt_detail = _combo(LOCATION_DETAILS)
        self._select_combo(self._mt_placement, self.config.placement)
        self._select_combo(self._mt_arrow, self.config.route_arrow)
        self._select_combo(self._mt_sep, self.config.title_separator)
        self._select_combo(self._mt_rank_sep, self.config.rank_separator)
        self._select_combo(self._mt_detail, self.config.location_detail)
        for combo in (self._mt_placement, self._mt_arrow, self._mt_sep, self._mt_detail):
            combo.currentIndexChanged.connect(self._on_mt_changed)
        self._mt_rank_sep.currentIndexChanged.connect(self._on_mt_rank_sep_changed)

        self._mt_shorten_titles = QCheckBox(tr("enhancements.mt_shorten_titles_cb"))
        self._mt_shorten_titles.setChecked(_shorten_phrase_keys <= enabled_phrases)
        self._mt_shorten_titles.toggled.connect(self._on_mt_shorten_titles_toggle)

        self._mt_shorten_sizes = QCheckBox(tr("enhancements.mt_shorten_sizes_cb"))
        self._mt_shorten_sizes.setChecked(_ALL_SIZE_WORDS <= shortened_sizes)
        self._mt_shorten_sizes.toggled.connect(self._on_mt_shorten_sizes_toggle)

        self._mt_abbrev_boxes: dict[str, QCheckBox] = {}
        for key, label, *_rest in REMOVE_WORD_OPTIONS:
            box = QCheckBox(label)
            box.setChecked(key in enabled_phrases)
            box.toggled.connect(lambda checked, k=key: self._on_mt_abbrev_toggle(k, checked))
            self._mt_abbrev_boxes[key] = box

        # Explicit fixed widths instead of leaving it to Qt's auto-sizing —
        # sharing a plain grid column let one combo's natural sizeHint (e.g.
        # Route arrow's "Route shape ( ->- / ->= / =>- / =>= )") inflate
        # every other row too, pushing dropdowns much further right than
        # their own label needed. Uniform width here instead sized to
        # whichever of the 5 combos actually needs the most room, via Qt's
        # own sizeHint (accounts for the widest item's text plus the
        # dropdown arrow and frame padding) — so the longest option always
        # displays in full, in whichever combo it belongs to.
        _LABEL_WIDTH = 110
        _mt_combos = (self._mt_placement, self._mt_arrow, self._mt_sep,
                      self._mt_rank_sep, self._mt_detail)
        _COMBO_WIDTH = max(c.sizeHint().width() for c in _mt_combos) + 10  # small safety margin
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)
        grid.setColumnMinimumWidth(2, 24)  # gap between dropdowns and checkboxes
        grid_rows = [
            ("enhancements.tag_placement_label", self._mt_placement, self._mt_shorten_titles),
            ("enhancements.mt_route_arrow_label", self._mt_arrow, self._mt_shorten_sizes),
            ("enhancements.mt_title_separator_label", self._mt_sep, self._mt_abbrev_boxes["cargo"]),
            ("enhancements.mt_rank_separator_label", self._mt_rank_sep, self._mt_abbrev_boxes["haul"]),
            ("enhancements.mt_location_detail_label", self._mt_detail, self._mt_abbrev_boxes["rank"]),
        ]
        self._mt_grid_labels: list[tuple[QLabel, str]] = []
        for r, (lbl_key, combo, box) in enumerate(grid_rows):
            lbl_widget = QLabel(tr(lbl_key))
            lbl_widget.setFixedWidth(_LABEL_WIDTH)
            combo.setFixedWidth(_COMBO_WIDTH)
            grid.addWidget(lbl_widget, r, 0)
            grid.addWidget(combo, r, 1)
            grid.addWidget(box, r, 3)
            self._mt_grid_labels.append((lbl_widget, lbl_key))
        col.addLayout(grid)

        underline_row = QHBoxLayout()
        self._mt_underline_direct = QCheckBox(tr("enhancements.mt_underline_direct_cb"))
        self._mt_underline_direct.setChecked("underline_direct" in enabled_phrases)
        self._mt_underline_direct.toggled.connect(
            lambda checked: self._on_mt_abbrev_toggle("underline_direct", checked)
        )
        self._mt_abbrev_boxes["underline_direct"] = self._mt_underline_direct
        underline_row.addWidget(self._mt_underline_direct)
        underline_row.addStretch()
        col.addLayout(underline_row)

        self.preview_label = QLabel()
        self.preview_label.setMinimumHeight(28)
        self.preview_label.setWordWrap(True)
        self.preview_label.setTextFormat(Qt.TextFormat.RichText)
        self.preview_label.setStyleSheet(
            "font-family: Consolas, 'Courier New', monospace; "
            "font-size: 12px; padding: 4px; "
            "background: rgba(0, 0, 0, 30); border-radius: 3px;"
        )
        col.addWidget(self.preview_label)
        col.addStretch()
        self._set_mt_controls_enabled(self._mt_enable.isChecked())
        self._refresh_preview()

        # "General Tags" (2.2.0): show/hide the [REP]/[BP]/[ACE] markers on
        # the mission TITLE only, across every mission type — independent of
        # the "Mission detail fields" body toggles above (which is per-
        # category, per-#121) and independent of the Hauling Missions
        # TagConfig to its left. Persisted directly via AppSettings, same
        # pattern as the mission-detail-field checkboxes.
        self._mt_tags_group = QGroupBox(tr("enhancements.mt_general_tags_group"))
        tags_col = QVBoxLayout(self._mt_tags_group)
        tags_col.setContentsMargins(10, 10, 10, 10)
        tags_col.setSpacing(6)
        self._mt_tags_hint = QLabel(tr("enhancements.mt_general_tags_hint"))
        self._mt_tags_hint.setProperty("role", "secondary")
        self._mt_tags_hint.setStyleSheet("font-size: 11px;")
        self._mt_tags_hint.setWordWrap(True)
        tags_col.addWidget(self._mt_tags_hint)

        _TITLE_TAG_KEYS = [
            ("rep",       "enhancements.mt_tag_rep_cb"),
            ("blueprint", "enhancements.mt_tag_blueprint_cb"),
            ("ace",       "enhancements.mt_tag_ace_cb"),
            ("rep_track", "enhancements.mt_tag_rep_track_cb"),
        ]
        self._title_tag_checkboxes: dict = {}
        self._title_tag_keys: dict = dict(_TITLE_TAG_KEYS)
        _tt_saved = AppSettings.get_mission_title_tags()
        for _field, _key in _TITLE_TAG_KEYS:
            cb = QCheckBox(tr(_key))
            cb.setChecked(_tt_saved.get(_field, True))
            cb.toggled.connect(
                lambda checked, f=_field: AppSettings.set_mission_title_tag(f, checked)
            )
            cb.toggled.connect(self.config_changed.emit)
            tags_col.addWidget(cb)
            self._title_tag_checkboxes[_field] = cb
        tags_col.addStretch()
        page.addWidget(self._mt_tags_group)

        # "Scanning/Mining Missions" (4.9+): its own box next to General Tags
        # rather than folded into it, since it's specific to one mission
        # family (Recco Battaglia's Scan/Mining contracts) rather than a
        # tag shown across every mission type. Same immediate-persist
        # pattern as the General Tags checkboxes above (shares
        # self._title_tag_checkboxes so Reset-to-defaults picks it up too).
        self._mt_scanning_group = QGroupBox(tr("enhancements.mt_scanning_group"))
        scanning_col = QVBoxLayout(self._mt_scanning_group)
        scanning_col.setContentsMargins(10, 10, 10, 10)
        scanning_col.setSpacing(6)
        self._mt_scanning_hint = QLabel(tr("enhancements.mt_scanning_hint"))
        self._mt_scanning_hint.setProperty("role", "secondary")
        self._mt_scanning_hint.setStyleSheet("font-size: 11px;")
        self._mt_scanning_hint.setWordWrap(True)
        scanning_col.addWidget(self._mt_scanning_hint)

        _rs_cb = QCheckBox(tr("enhancements.mt_tag_rs_cb"))
        _rs_cb.setChecked(_tt_saved.get("rs", True))
        _rs_cb.toggled.connect(
            lambda checked: AppSettings.set_mission_title_tag("rs", checked)
        )
        _rs_cb.toggled.connect(self.config_changed.emit)
        scanning_col.addWidget(_rs_cb)
        self._title_tag_checkboxes["rs"] = _rs_cb
        self._title_tag_keys["rs"] = "enhancements.mt_tag_rs_cb"
        scanning_col.addStretch()
        page.addWidget(self._mt_scanning_group)

        page.addStretch()

    def _set_mt_controls_enabled(self, on: bool) -> None:
        for c in (self._mt_placement, self._mt_arrow, self._mt_sep, self._mt_detail):
            c.setEnabled(on)

    def _on_mt_enable(self, checked: bool) -> None:
        for e in self.config.elements:
            if e.kind == "route":
                e.enabled = checked
        self._set_mt_controls_enabled(checked)
        self._refresh_preview()
        self.config_changed.emit()

    def _on_mt_standardize_toggle(self, checked: bool) -> None:
        self.config.standardize_hauling_names = checked
        self._refresh_preview()
        self.config_changed.emit()

    def _on_mt_abbrev_toggle(self, key: str, checked: bool) -> None:
        phrases = set(getattr(self.config, "abbreviated_phrases", frozenset()))
        if checked:
            phrases.add(key)
        else:
            phrases.discard(key)
        self.config.abbreviated_phrases = frozenset(phrases)
        self._refresh_preview()
        self.config_changed.emit()

    def _on_mt_shorten_titles_toggle(self, checked: bool) -> None:
        phrases = set(getattr(self.config, "abbreviated_phrases", frozenset()))
        keys = {k for k, *_ in SHORTEN_PHRASE_OPTIONS}
        phrases = (phrases | keys) if checked else (phrases - keys)
        self.config.abbreviated_phrases = frozenset(phrases)
        self._refresh_preview()
        self.config_changed.emit()

    def _on_mt_shorten_sizes_toggle(self, checked: bool) -> None:
        self.config.shortened_sizes = frozenset(_ALL_SIZE_WORDS) if checked else frozenset()
        self._refresh_preview()
        self.config_changed.emit()

    def _on_mt_rank_sep_changed(self, _idx: int) -> None:
        self.config.rank_separator = self._mt_rank_sep.currentData() or self.config.rank_separator
        self._refresh_preview()
        self.config_changed.emit()

    def _on_mt_changed(self, _idx: int) -> None:
        self.config.placement = self._mt_placement.currentData() or self.config.placement
        self.config.route_arrow = self._mt_arrow.currentData() or self.config.route_arrow
        self.config.title_separator = self._mt_sep.currentData() or self.config.title_separator
        self.config.location_detail = self._mt_detail.currentData() or self.config.location_detail
        self._refresh_preview()
        self.config_changed.emit()

    # In-game emphasis tag written to the real generated INI — must stay
    # exactly this for _EM3_DISPLAY_MARKUP below to find and swap it.
    _EM3_DIRECT = "<EM3>DIRECT</EM3>"

    def _refresh_mt_preview(self) -> None:
        sample_title = "Master Rank - Direct Medium Cargo Haul"
        enabled_phrases = getattr(self.config, "abbreviated_phrases", frozenset())
        # Always applied — the Rank separator is an independent, always-on
        # feature and doesn't need any checkbox ticked; the word/phrase
        # toggles inside abbreviate_title stay individually gated. This is
        # the SAME function the generator calls, so when "underline_direct"
        # is on, sample_title genuinely contains the real <EM3>DIRECT</EM3>
        # in-game emphasis tag — swapped for a visual underline only when
        # displayed below, never in the data itself.
        sample_title = abbreviate_title(
            sample_title, enabled_phrases, self.config.rank_separator,
            getattr(self.config, "standardize_hauling_names", False)
        )
        # In-game the size comes from the CargoGradeToken loc keys the
        # generator overrides; mirror that on the literal sample here, per
        # size, independent of the word/phrase removal checkboxes above.
        for word in getattr(self.config, "shortened_sizes", frozenset()):
            short = SIZE_ABBREV_BY_WORD.get(word)
            if short:
                sample_title = sample_title.replace(word, short)
        if not route_enabled(self.config):
            display = sample_title.replace(self._EM3_DIRECT, "<u>DIRECT</u>")
            self.preview_label.setText(tr("enhancements.mt_preview_route_off", display=display))
            return
        if self.config.location_detail == "address":
            frm, to = "Area18, Crusader", "Lorville, Hurston"
        else:
            frm, to = "Area18", "Lorville"
        route = render_route(frm, to, self.config.route_arrow)
        title = apply_mission_title(sample_title, route, self.config)
        display = title.replace(self._EM3_DIRECT, "<u>DIRECT</u>")
        self.preview_label.setText(tr("enhancements.mt_preview_route_on", display=display))

    # ── Preview ──────────────────────────────────────────────────────────

    def _refresh_preview(self):
        if self.category == "mission_titles":
            self._refresh_mt_preview()
            return
        tag = render_tag(self.config, _PREVIEW_VALUES.get(self.category, {}))
        name = _PREVIEW_NAMES.get(self.category, "Sample")
        if tag:
            if self.config.placement == "append":
                self.preview_label.setText(tr("enhancements.tag_preview", content=f"{name} {tag}"))
            else:
                self.preview_label.setText(tr("enhancements.tag_preview", content=f"{tag} {name}"))
        else:
            self.preview_label.setText(tr("enhancements.tag_preview_no_tag", name=name))

    def retranslate_ui(self) -> None:
        """Re-apply tr() to every static widget on this page after a language
        switch. Element rows and combo-box item text supplied by
        src.utils.tag_builder's option tables are out of scope here — that
        module doesn't route through tr() (a separate, larger conversion)."""
        if self.category == "mission_titles":
            self._mt_group.setTitle(tr("enhancements.mt_hauling_group"))
            self._mt_enable.setText(tr("enhancements.mt_enable_route_cb"))
            self._mt_standardize.setText(tr("enhancements.mt_standardize_cb"))
            self._mt_hint.setText(tr("enhancements.mt_route_hint"))
            for lbl_widget, lbl_key in self._mt_grid_labels:
                lbl_widget.setText(tr(lbl_key))
            self._mt_shorten_titles.setText(tr("enhancements.mt_shorten_titles_cb"))
            self._mt_shorten_sizes.setText(tr("enhancements.mt_shorten_sizes_cb"))
            self._mt_underline_direct.setText(tr("enhancements.mt_underline_direct_cb"))
            self._mt_tags_group.setTitle(tr("enhancements.mt_general_tags_group"))
            self._mt_tags_hint.setText(tr("enhancements.mt_general_tags_hint"))
            for field, cb in self._title_tag_checkboxes.items():
                key = self._title_tag_keys.get(field)
                if key:
                    cb.setText(tr(key))
            self._mt_scanning_group.setTitle(tr("enhancements.mt_scanning_group"))
            self._mt_scanning_hint.setText(tr("enhancements.mt_scanning_hint"))
        else:
            self._sep_label.setText(tr("enhancements.tag_separator_label"))
            self._enc_label.setText(tr("enhancements.tag_enclosing_label"))
            self._placement_label.setText(tr("enhancements.tag_placement_label"))
            if self._usage_sep_label is not None:
                self._usage_sep_label.setText(tr("enhancements.tag_craft_usage_separator_label"))
            for row in self._rows:
                row.retranslate_ui()
        self._refresh_preview()

    # ── Reset ────────────────────────────────────────────────────────────

    def _reset_to_defaults(self):
        """Reset-to-defaults button: swap in a fresh default config.

        Thin wrapper over :meth:`apply_config` — ``reset_title_tags=True``
        keeps the historical behaviour of *persisting* each General Tags
        default (see the long comment in ``apply_config``).
        """
        self.apply_config(default_config(self.category), reset_title_tags=True)

    def apply_config(self, cfg: TagConfig, *, reset_title_tags: bool = False):
        """Adopt *cfg* as this page's config and resync every widget to it.

        Two callers, two intents:

        - **Reset to defaults** passes a fresh default config with
          ``reset_title_tags=True``: General Tags are written back to their
          per-field defaults *and persisted*, since Reset is an explicit
          user action on that immediately-saved settings domain.
        - **Import Settings** passes the freshly-imported saved config with
          ``reset_title_tags=False``: the checkboxes are re-read from the
          (already imported) settings and nothing is written back. Without
          this refresh the page keeps the pre-import config in memory, and
          the next Save Tag Changes / Generate / Export would write that
          stale state straight over the imported one.
        """
        # Replace this page's config, rebuild the row list, resync
        # separator/enclosing/placement combos + preview.
        fresh = cfg
        self.config = fresh
        if self.category == "mission_titles":
            route_el = next((e for e in fresh.elements if e.kind == "route"), None)
            self._mt_enable.setChecked(bool(route_el and route_el.enabled))
            self._mt_standardize.setChecked(fresh.standardize_hauling_names)
            _shorten_phrase_keys = frozenset(k for k, *_ in SHORTEN_PHRASE_OPTIONS)
            self._mt_shorten_titles.setChecked(_shorten_phrase_keys <= fresh.abbreviated_phrases)
            self._mt_shorten_sizes.setChecked(_ALL_SIZE_WORDS <= fresh.shortened_sizes)
            for key, box in self._mt_abbrev_boxes.items():
                box.setChecked(key in fresh.abbreviated_phrases)
            self._select_combo(self._mt_rank_sep, fresh.rank_separator)
            self._select_combo(self._mt_placement, fresh.placement)
            self._select_combo(self._mt_arrow, fresh.route_arrow)
            self._select_combo(self._mt_sep, fresh.title_separator)
            self._select_combo(self._mt_detail, fresh.location_detail)
            # General Tags (Rep/BP/ACE/Rep Track) aren't part of TagConfig —
            # they're their own settings domain
            # (AppSettings.set_mission_title_tag), persisted immediately on
            # toggle rather than staged until Apply Tag Changes like the rest
            # of this page. Reset explicitly persists each field's own
            # default (get_mission_title_tag_default — all on except Rep
            # Track, which defaults off) to match that immediate-save
            # behavior, rather than relying solely on setChecked's toggled
            # signal (a checkbox already at its default wouldn't fire it,
            # leaving a stale saved value if one had somehow drifted out of
            # sync).
            _tt_saved = AppSettings.get_mission_title_tags()
            for field, box in self._title_tag_checkboxes.items():
                if reset_title_tags:
                    value = AppSettings.get_mission_title_tag_default(field)
                else:
                    # Import path: settings already hold the imported values;
                    # just mirror them. Writing here would be a no-op at best
                    # and could clobber at worst.
                    value = _tt_saved.get(field, True)
                box.blockSignals(True)
                box.setChecked(value)
                box.blockSignals(False)
                if reset_title_tags:
                    AppSettings.set_mission_title_tag(field, value)
            self._set_mt_controls_enabled(self._mt_enable.isChecked())
            self._refresh_preview()
            self.config_changed.emit()
            return
        self._select_combo(self.sep_combo, fresh.separator)
        self._select_combo(self.enc_combo, fresh.enclosing)
        self._select_combo(self.placement_combo, fresh.placement)
        if self.usage_sep_combo is not None:
            self._select_combo(self.usage_sep_combo, fresh.usage_separator)
        self._repopulate_list()
        self._refresh_preview()
        self.config_changed.emit()

    @staticmethod
    def _select_combo(combo: QComboBox, key: str) -> None:
        for i in range(combo.count()):
            if combo.itemData(i) == key:
                combo.setCurrentIndex(i)
                return
