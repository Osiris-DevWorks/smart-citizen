"""Configuration tab for Smart Citizen."""
import logging
import os
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLineEdit,
    QPushButton, QLabel, QFileDialog, QMessageBox, QComboBox,
    QCheckBox, QScrollArea, QFrame, QDialog, QDialogButtonBox, QGridLayout,
)
from PyQt6.QtCore import pyqtSignal, QTimer

from src.gui.theme import AVAILABLE_THEMES, THEME_LIGHT, THEME_DARK, THEME_SCLE, THEME_ODW, get_button_color
from src.utils.i18n import tr
from src.utils.settings import AppSettings
from src.utils.user_ini_manager import migrate_user_data_dir

logger = logging.getLogger(__name__)


class ConfigTab(QWidget):
    """Configuration tab — game path, P4K extraction, and import tools."""

    merge_requested = pyqtSignal()
    p4k_extract_requested = pyqtSignal()
    import_ini_requested = pyqtSignal()
    # Emitted when the user clicks the "Reset user.ini" Tools button.
    # MainWindow runs the confirmation dialog and the actual file work so
    # this tab stays decoupled from filesystem state + reload orchestration.
    reset_user_ini_requested = pyqtSignal()
    # Emitted when the user clicks "Restore user.ini" — MainWindow lists the
    # rotating snapshots and lets the user pick one to restore (#172).
    restore_user_ini_requested = pyqtSignal()
    # Emitted after the user picks a new channel in the combo AND the choice
    # has already been persisted via AppSettings.set_active_channel(). Main
    # window listens and triggers a reload against the new channel's data.
    channel_changed = pyqtSignal(str)
    # Emitted when the user clicks the "Check for Updates" button in Tools.
    # MainWindow owns the update-check worker and writes results back via
    # set_update_status() so this tab stays decoupled from the network path.
    check_updates_requested = pyqtSignal()
    # Emitted after the Smart Citizen data folder override has been saved.
    # MainWindow re-syncs source paths and reloads against the new location.
    data_dir_changed = pyqtSignal(str)
    # Emitted after the DataForge cache folder override has been saved AND
    # the user confirmed (in the re-extraction dialog) that the cache should
    # be rebuilt against the new location. MainWindow listens and triggers
    # P4K extraction. If the user picked "delete old cache after re-extract",
    # the old path is also stashed in AppSettings.PENDING_CACHE_CLEANUP for
    # the post-extract cleanup step.
    cache_dir_changed = pyqtSignal(str)
    # Emitted when the user picks a different language. MainWindow listens and
    # triggers a merge+reload so the table reflects the new language strings.
    language_changed = pyqtSignal(str)
    # Emitted by the Settings Backup buttons. MainWindow owns the file
    # dialogs, the zip I/O (src/utils/settings_profile.py), and the
    # post-import restart flow so this tab stays presentation-only.
    export_settings_requested = pyqtSignal()
    import_settings_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setup_ui()

    def setup_ui(self):
        # Build into an inner content widget that a QScrollArea hosts, so the
        # tab degrades gracefully on short viewports (e.g. a 4K TV with
        # Windows display scaling, which gives the app a small logical height
        # and previously squished the Config tab — #98). The wrap is added at
        # the end of this method.
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self._title_label = QLabel(tr("config.title"))
        self._title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(self._title_label)

        self._instructions_label = QLabel(tr("config.instructions"))
        self._instructions_label.setProperty("role", "secondary")
        self._instructions_label.setStyleSheet("font-size: 11px;")
        self._instructions_label.setWordWrap(True)
        layout.addWidget(self._instructions_label)

        # ── Tools ────────────────────────────────────────────────────────────
        self._tools_group = QGroupBox(tr("config.tools_group"))
        tools_layout = QVBoxLayout(self._tools_group)

        self._tools_desc_label = QLabel(tr("config.tools_desc"))
        self._tools_desc_label.setProperty("role", "secondary")
        self._tools_desc_label.setStyleSheet("font-size: 11px;")
        self._tools_desc_label.setWordWrap(True)
        tools_layout.addWidget(self._tools_desc_label)

        self.include_new_cb = QCheckBox(tr("config.include_new_cb"))
        self.include_new_cb.setToolTip(tr("config.include_new_tooltip"))
        self.include_new_cb.setChecked(AppSettings.get_include_new_lines())
        self.include_new_cb.toggled.connect(self._on_include_new_toggled)
        tools_layout.addWidget(self.include_new_cb)

        button_layout = QHBoxLayout()

        self._import_btn = QPushButton(tr("config.import_ini_btn"))
        self._import_btn.setMaximumWidth(150)
        self._import_btn.setToolTip(tr("config.import_ini_tooltip"))
        self._import_btn.clicked.connect(self.import_ini_requested.emit)
        button_layout.addWidget(self._import_btn)

        self._reset_user_ini_btn = QPushButton(tr("config.reset_user_ini_btn"))
        self._reset_user_ini_btn.setMaximumWidth(150)
        self._reset_user_ini_btn.setToolTip(tr("config.reset_user_ini_tooltip"))
        self._reset_user_ini_btn.clicked.connect(self.reset_user_ini_requested.emit)
        button_layout.addWidget(self._reset_user_ini_btn)

        self._restore_user_ini_btn = QPushButton(tr("config.restore_user_ini_btn"))
        self._restore_user_ini_btn.setMaximumWidth(150)
        self._restore_user_ini_btn.setToolTip(tr("config.restore_user_ini_tooltip"))
        self._restore_user_ini_btn.clicked.connect(self.restore_user_ini_requested.emit)
        button_layout.addWidget(self._restore_user_ini_btn)

        self._preview_btn = QPushButton(tr("config.preview_apply_btn"))
        self._preview_btn.setMaximumWidth(150)
        self._preview_btn.setToolTip(tr("config.preview_apply_tooltip"))
        self._preview_btn.clicked.connect(self.preview_merge)
        button_layout.addWidget(self._preview_btn)

        self._check_updates_btn = QPushButton(tr("config.check_updates_btn"))
        self._check_updates_btn.setMaximumWidth(170)
        self._check_updates_btn.setToolTip(tr("config.check_updates_tooltip"))
        self._check_updates_btn.clicked.connect(self.check_updates_requested.emit)
        button_layout.addWidget(self._check_updates_btn)

        self._update_status_label = QLabel("")
        self._update_status_label.setProperty("role", "secondary")
        self._update_status_label.setStyleSheet("font-size: 11px;")
        button_layout.addWidget(self._update_status_label)

        button_layout.addStretch()
        tools_layout.addLayout(button_layout)
        # _tools_group is added to the layout last (see the bottom of this
        # method) so Tools stays at the bottom of the Config tab, where it sat
        # before the scroll-area wrap reordered it to the top.

        # ── Appearance ───────────────────────────────────────────────────────
        self._appearance_group = QGroupBox(tr("config.appearance_group"))
        appearance_layout = QHBoxLayout(self._appearance_group)

        self._theme_label = QLabel(tr("config.theme_label"))
        appearance_layout.addWidget(self._theme_label)

        self.theme_combo = QComboBox()
        self.theme_combo.setToolTip(tr("config.theme_tooltip"))
        self.theme_combo.addItem(tr("config.theme_default"), THEME_SCLE)
        self.theme_combo.addItem(tr("config.theme_light"), THEME_LIGHT)
        self.theme_combo.addItem(tr("config.theme_dark"), THEME_DARK)
        self.theme_combo.addItem(tr("config.theme_odw"), THEME_ODW)
        current = AppSettings.get_theme()
        idx = self.theme_combo.findData(current)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        self.theme_combo.setMaximumWidth(150)
        appearance_layout.addWidget(self.theme_combo)

        appearance_layout.addSpacing(20)
        self.disable_tutorial_cb = QCheckBox(tr("config.disable_tutorial_cb"))
        self.disable_tutorial_cb.setToolTip(tr("config.disable_tutorial_tooltip"))
        self.disable_tutorial_cb.setChecked(AppSettings.get_tutorial_disabled())
        self.disable_tutorial_cb.toggled.connect(AppSettings.set_tutorial_disabled)
        appearance_layout.addWidget(self.disable_tutorial_cb)

        appearance_layout.addStretch()
        layout.addWidget(self._appearance_group)

        # ── Star Citizen Installation (path, channel, language) ────────────
        self._loc_group = QGroupBox(tr("config.star_citizen_group"))
        loc_outer = QHBoxLayout(self._loc_group)

        # Game install path, channel, language
        game_layout = QVBoxLayout()

        self._install_label = QLabel(tr("config.installation_label"))
        self._install_label.setStyleSheet("font-weight: bold; font-size: 11px;")
        game_layout.addWidget(self._install_label)

        self._game_desc_label = QLabel(tr("config.installation_desc"))
        self._game_desc_label.setProperty("role", "secondary")
        self._game_desc_label.setStyleSheet("font-size: 11px; margin-bottom: 5px;")
        self._game_desc_label.setWordWrap(True)
        game_layout.addWidget(self._game_desc_label)

        game_input_layout = QHBoxLayout()
        self.game_path_input = QLineEdit()
        _initial_game_root = AppSettings.get_sc_install_root()
        self.game_path_input.setText(os.path.normpath(_initial_game_root) if _initial_game_root else "")
        self.game_path_input.setPlaceholderText(tr("config.game_path_placeholder"))
        self.game_path_input.setToolTip(tr("config.game_path_tooltip"))
        self.game_path_input.editingFinished.connect(self._save_game_path)
        game_input_layout.addWidget(self.game_path_input)

        self._game_browse_btn = QPushButton(tr("config.browse_btn"))
        self._game_browse_btn.setMaximumWidth(100)
        self._game_browse_btn.setToolTip(tr("config.browse_game_tooltip"))
        self._game_browse_btn.clicked.connect(self._browse_game_path)
        game_input_layout.addWidget(self._game_browse_btn)
        game_layout.addLayout(game_input_layout)

        # ── Channel selector (LIVE / PTU / EPTU / HOTFIX / TECH-PREVIEW) ───
        channel_row = QHBoxLayout()
        self._channel_label = QLabel(tr("config.channel_label"))
        self._channel_label.setStyleSheet("font-size: 11px;")
        channel_row.addWidget(self._channel_label)

        self.channel_combo = QComboBox()
        self.channel_combo.setMaximumWidth(180)
        self.channel_combo.setToolTip(tr("config.channel_tooltip"))
        channel_row.addWidget(self.channel_combo)

        self._channel_hint_label = QLabel()
        self._channel_hint_label.setProperty("role", "secondary")
        self._channel_hint_label.setStyleSheet("font-size: 10px;")
        channel_row.addWidget(self._channel_hint_label)
        channel_row.addStretch()

        # ── Install-location check (2.4, #385) ─────────────────────────────
        # Rides the right end of the channel row rather than taking a row of
        # its own: a dedicated row left a dead gap down the left-hand side
        # and pushed Channel/Language a row lower, while sharing the path row
        # ate the QLineEdit's width. The channel row already ends in dead
        # space, so this costs no vertical room and moves nothing.
        #
        # It answers the question the path field above raises -- "is this the
        # install I actually play?" -- because a second install the RSI
        # Launcher drives instead makes every apply a silent no-op, and
        # nothing else in the app can surface that.
        self._dupe_check_btn = QPushButton(tr("config.dupe_check_btn"))
        self._dupe_check_btn.setMaximumWidth(220)
        self._dupe_check_btn.setToolTip(tr("config.dupe_check_tooltip"))
        # Lambda, not a bare connect: clicked(bool) would land its `checked`
        # argument in the `deep` parameter.
        self._dupe_check_btn.clicked.connect(lambda: self._check_other_installs(deep=False))
        channel_row.addWidget(self._dupe_check_btn)
        game_layout.addLayout(channel_row)

        self._populate_channel_combo()
        # Wire AFTER populate so the initial setCurrentIndex inside
        # _populate_channel_combo doesn't emit a phantom change signal.
        self.channel_combo.currentIndexChanged.connect(self._on_channel_changed)

        # ── Language selector ────────────────────────────────────────────────
        language_row = QHBoxLayout()
        self._language_label = QLabel(tr("config.language_label"))
        self._language_label.setStyleSheet("font-size: 11px;")
        language_row.addWidget(self._language_label)

        self.language_combo = QComboBox()
        self.language_combo.setMaximumWidth(180)
        self.language_combo.setToolTip(tr("config.language_tooltip"))
        language_row.addWidget(self.language_combo)

        self._map_lang_btn = QPushButton(tr("config.map_language_btn"))
        self._map_lang_btn.setMaximumWidth(160)
        self._map_lang_btn.setToolTip(tr("config.map_language_tooltip"))
        self._map_lang_btn.clicked.connect(self._open_language_source_dialog)
        language_row.addWidget(self._map_lang_btn)

        language_row.addStretch()
        game_layout.addLayout(language_row)

        self._populate_language_combo()
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)

        game_layout.addStretch()
        loc_outer.addLayout(game_layout)

        # Base localization / P4K extraction lives in its own standalone
        # group below (self._p4k_group), not here — this group is just the
        # install path, channel, and language.
        layout.addWidget(self._loc_group)

        # ── Smart Citizen Data ───────────────────────────────────────────────
        self._data_group = QGroupBox(tr("config.data_group"))
        data_layout = QVBoxLayout(self._data_group)

        self._data_desc_label = QLabel(tr("config.data_desc"))
        self._data_desc_label.setProperty("role", "secondary")
        self._data_desc_label.setStyleSheet("font-size: 11px; margin-bottom: 5px;")
        self._data_desc_label.setWordWrap(True)
        data_layout.addWidget(self._data_desc_label)

        # Sub-label for the user-data row.
        self._app_data_label = QLabel(tr("config.app_data_label"))
        self._app_data_label.setStyleSheet("font-size: 11px;")
        data_layout.addWidget(self._app_data_label)

        data_input_layout = QHBoxLayout()
        self.data_dir_input = QLineEdit()
        self.data_dir_input.setText(os.path.normpath(str(AppSettings.get_user_data_dir())))
        self.data_dir_input.setToolTip(tr("config.data_dir_tooltip"))
        self.data_dir_input.editingFinished.connect(self._save_data_dir)
        data_input_layout.addWidget(self.data_dir_input)

        self._data_browse_btn = QPushButton(tr("config.browse_btn"))
        self._data_browse_btn.setMaximumWidth(100)
        self._data_browse_btn.setToolTip(tr("config.browse_data_tooltip"))
        self._data_browse_btn.clicked.connect(self._browse_data_dir)
        data_input_layout.addWidget(self._data_browse_btn)

        self._data_reset_btn = QPushButton(tr("config.reset_btn"))
        self._data_reset_btn.setMaximumWidth(80)
        self._data_reset_btn.setToolTip(tr("config.reset_data_tooltip"))
        self._data_reset_btn.clicked.connect(self._reset_data_dir)
        data_input_layout.addWidget(self._data_reset_btn)

        data_layout.addLayout(data_input_layout)

        # ── DataForge cache row ──────────────────────────────────────────
        # Independent from the app-data folder above so users can route the
        # ~1.4 GB / ~28k-file DataForge tree to a fast local SSD while
        # keeping their tiny user.ini / sources where they like. Default
        # base is %LOCALAPPDATA% (registry) or <exe-dir>/data/cache/
        # (portable) — both never OneDrive-synced.
        self._cache_label = QLabel(tr("config.dataforge_cache_label"))
        self._cache_label.setStyleSheet("font-size: 11px; margin-top: 8px;")
        data_layout.addWidget(self._cache_label)

        cache_input_layout = QHBoxLayout()
        self.cache_dir_input = QLineEdit()
        self.cache_dir_input.setText(
            os.path.normpath(str(AppSettings.get_dataforge_cache_base()))
        )
        self.cache_dir_input.setToolTip(tr("config.cache_dir_tooltip"))
        self.cache_dir_input.editingFinished.connect(self._save_cache_dir)
        cache_input_layout.addWidget(self.cache_dir_input)

        self._cache_browse_btn = QPushButton(tr("config.browse_btn"))
        self._cache_browse_btn.setMaximumWidth(100)
        self._cache_browse_btn.setToolTip(tr("config.browse_cache_tooltip"))
        self._cache_browse_btn.clicked.connect(self._browse_cache_dir)
        cache_input_layout.addWidget(self._cache_browse_btn)

        self._cache_reset_btn = QPushButton(tr("config.reset_btn"))
        self._cache_reset_btn.setMaximumWidth(80)
        self._cache_reset_btn.setToolTip(tr("config.reset_cache_tooltip"))
        self._cache_reset_btn.clicked.connect(self._reset_cache_dir)
        cache_input_layout.addWidget(self._cache_reset_btn)

        data_layout.addLayout(cache_input_layout)
        layout.addWidget(self._data_group)

        # ── P4K Extraction ───────────────────────────────────────────────────
        self._p4k_group = QGroupBox(tr("config.p4k_group"))
        p4k_layout = QVBoxLayout(self._p4k_group)

        self._p4k_desc_label = QLabel(tr("config.p4k_desc"))
        self._p4k_desc_label.setProperty("role", "secondary")
        self._p4k_desc_label.setStyleSheet("font-size: 11px;")
        self._p4k_desc_label.setWordWrap(True)
        p4k_layout.addWidget(self._p4k_desc_label)

        p4k_status_row = QHBoxLayout()
        self._p4k_status_dot = QLabel("●")
        self._p4k_status_dot.setStyleSheet("font-size: 14px;")
        p4k_status_row.addWidget(self._p4k_status_dot)

        self._p4k_status_label = QLabel()
        self._p4k_status_label.setProperty("role", "secondary")
        self._p4k_status_label.setStyleSheet("font-size: 11px;")
        p4k_status_row.addWidget(self._p4k_status_label)
        p4k_status_row.addStretch()

        self._extract_btn = QPushButton(tr("config.extract_btn"))
        self._extract_btn.setMaximumWidth(180)
        self._extract_btn.setToolTip(tr("config.extract_tooltip"))
        self._extract_btn.clicked.connect(self.p4k_extract_requested.emit)
        p4k_status_row.addWidget(self._extract_btn)

        p4k_layout.addLayout(p4k_status_row)
        layout.addWidget(self._p4k_group)

        self._refresh_p4k_status()

        # Tools last, so it sits at the bottom of the Config tab.
        layout.addWidget(self._tools_group)

        # ── Settings Backup (Export / Import Settings) ───────────────────────
        self._backup_group = QGroupBox(tr("config.backup_group"))
        backup_layout = QVBoxLayout(self._backup_group)

        self._backup_desc_label = QLabel(tr("config.backup_desc"))
        self._backup_desc_label.setProperty("role", "secondary")
        self._backup_desc_label.setStyleSheet("font-size: 11px;")
        self._backup_desc_label.setWordWrap(True)
        backup_layout.addWidget(self._backup_desc_label)

        backup_btn_layout = QHBoxLayout()

        self._export_settings_btn = QPushButton(tr("config.export_settings_btn"))
        self._export_settings_btn.setMaximumWidth(150)
        self._export_settings_btn.setToolTip(tr("config.export_settings_tooltip"))
        self._export_settings_btn.clicked.connect(self.export_settings_requested.emit)
        backup_btn_layout.addWidget(self._export_settings_btn)

        self._import_settings_btn = QPushButton(tr("config.import_settings_btn"))
        self._import_settings_btn.setMaximumWidth(150)
        self._import_settings_btn.setToolTip(tr("config.import_settings_tooltip"))
        self._import_settings_btn.clicked.connect(self.import_settings_requested.emit)
        backup_btn_layout.addWidget(self._import_settings_btn)

        backup_btn_layout.addStretch()
        backup_layout.addLayout(backup_btn_layout)
        layout.addWidget(self._backup_group)

        layout.addStretch()

        # Host the content in a scroll area. MainWindow adds the tab widget
        # with stretch=1, so the scroll area fills the tab and this does NOT
        # reintroduce the tab-switch resize that got the 1.4.x Enhancements
        # scroll-area attempt reverted (#65). Keep the frame and viewport
        # background clear so the themed background shows through rather than
        # the scroll area painting its own Base colour.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.viewport().setAutoFillBackground(False)
        content.setAutoFillBackground(False)
        scroll.setWidget(content)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    # ── Retranslation ─────────────────────────────────────────────────────────

    def retranslate_ui(self) -> None:
        """Re-apply tr() to every text-bearing widget after a language switch."""
        self._title_label.setText(tr("config.title"))
        self._instructions_label.setText(tr("config.instructions"))
        self._tools_group.setTitle(tr("config.tools_group"))
        self._tools_desc_label.setText(tr("config.tools_desc"))
        self.include_new_cb.setText(tr("config.include_new_cb"))
        self.include_new_cb.setToolTip(tr("config.include_new_tooltip"))
        self._import_btn.setText(tr("config.import_ini_btn"))
        self._import_btn.setToolTip(tr("config.import_ini_tooltip"))
        self._reset_user_ini_btn.setText(tr("config.reset_user_ini_btn"))
        self._reset_user_ini_btn.setToolTip(tr("config.reset_user_ini_tooltip"))
        self._restore_user_ini_btn.setText(tr("config.restore_user_ini_btn"))
        self._restore_user_ini_btn.setToolTip(tr("config.restore_user_ini_tooltip"))
        self._preview_btn.setText(tr("config.preview_apply_btn"))
        self._preview_btn.setToolTip(tr("config.preview_apply_tooltip"))
        self._check_updates_btn.setText(tr("config.check_updates_btn"))
        self._check_updates_btn.setToolTip(tr("config.check_updates_tooltip"))
        self._backup_group.setTitle(tr("config.backup_group"))
        self._backup_desc_label.setText(tr("config.backup_desc"))
        self._export_settings_btn.setText(tr("config.export_settings_btn"))
        self._export_settings_btn.setToolTip(tr("config.export_settings_tooltip"))
        self._import_settings_btn.setText(tr("config.import_settings_btn"))
        self._import_settings_btn.setToolTip(tr("config.import_settings_tooltip"))
        self._appearance_group.setTitle(tr("config.appearance_group"))
        self._theme_label.setText(tr("config.theme_label"))
        self.theme_combo.setToolTip(tr("config.theme_tooltip"))
        self.theme_combo.blockSignals(True)
        try:
            self.theme_combo.setItemText(0, tr("config.theme_default"))
            self.theme_combo.setItemText(1, tr("config.theme_light"))
            self.theme_combo.setItemText(2, tr("config.theme_dark"))
            self.theme_combo.setItemText(3, tr("config.theme_odw"))
        finally:
            self.theme_combo.blockSignals(False)
        self.disable_tutorial_cb.setText(tr("config.disable_tutorial_cb"))
        self.disable_tutorial_cb.setToolTip(tr("config.disable_tutorial_tooltip"))
        self._loc_group.setTitle(tr("config.star_citizen_group"))
        self._install_label.setText(tr("config.installation_label"))
        self._game_desc_label.setText(tr("config.installation_desc"))
        self.game_path_input.setPlaceholderText(tr("config.game_path_placeholder"))
        self.game_path_input.setToolTip(tr("config.game_path_tooltip"))
        self._game_browse_btn.setText(tr("config.browse_btn"))
        self._game_browse_btn.setToolTip(tr("config.browse_game_tooltip"))
        self._dupe_check_btn.setText(tr("config.dupe_check_btn"))
        self._dupe_check_btn.setToolTip(tr("config.dupe_check_tooltip"))
        self._channel_label.setText(tr("config.channel_label"))
        self.channel_combo.setToolTip(tr("config.channel_tooltip"))
        self._language_label.setText(tr("config.language_label"))
        self.language_combo.setToolTip(tr("config.language_tooltip"))
        self._map_lang_btn.setText(tr("config.map_language_btn"))
        self._map_lang_btn.setToolTip(tr("config.map_language_tooltip"))
        self._extract_btn.setText(tr("config.extract_btn"))
        self._extract_btn.setToolTip(tr("config.extract_tooltip"))
        self._data_group.setTitle(tr("config.data_group"))
        self._data_desc_label.setText(tr("config.data_desc"))
        self._app_data_label.setText(tr("config.app_data_label"))
        self.data_dir_input.setToolTip(tr("config.data_dir_tooltip"))
        self._data_browse_btn.setText(tr("config.browse_btn"))
        self._data_browse_btn.setToolTip(tr("config.browse_data_tooltip"))
        self._data_reset_btn.setText(tr("config.reset_btn"))
        self._data_reset_btn.setToolTip(tr("config.reset_data_tooltip"))
        self._cache_label.setText(tr("config.dataforge_cache_label"))
        self.cache_dir_input.setToolTip(tr("config.cache_dir_tooltip"))
        self._cache_browse_btn.setText(tr("config.browse_btn"))
        self._cache_browse_btn.setToolTip(tr("config.browse_cache_tooltip"))
        self._cache_reset_btn.setText(tr("config.reset_btn"))
        self._cache_reset_btn.setToolTip(tr("config.reset_cache_tooltip"))
        self._p4k_group.setTitle(tr("config.p4k_group"))
        self._p4k_desc_label.setText(tr("config.p4k_desc"))

    # ── Theme ────────────────────────────────────────────────────────────────

    def _on_theme_changed(self, _index: int):
        """Defer the actual swap to the next event-loop tick. Running
        app.setPalette() directly from a QComboBox.currentIndexChanged slot
        crashes Qt 6 because the combo's event chain hasn't finished unwinding.
        """
        theme = self.theme_combo.currentData()
        if theme not in AVAILABLE_THEMES:
            return
        QTimer.singleShot(0, lambda: self._apply_theme_change(theme))

    def _apply_theme_change(self, theme: str):
        """Persist and apply the theme. Runs via QTimer.singleShot so we're
        outside the combo's event handling — required for setPalette safety."""
        from PyQt6.QtWidgets import QApplication
        from src.gui.theme import apply_theme
        AppSettings.set_theme(theme)
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, theme)
        mw = self.window()
        if hasattr(mw, "refresh_action_buttons"):
            mw.refresh_action_buttons()

    def _on_include_new_toggled(self, checked: bool):
        AppSettings.set_include_new_lines(checked)

    # ── Game path ────────────────────────────────────────────────────────────

    def _save_game_path(self) -> bool:
        """Save the SC install root when editing finishes, and refresh the
        channel combo so per-channel enable/disable reflects the new root.

        Returns whether the value was actually applied. An empty field is a
        deliberate clear and counts as applied; a non-empty path that fails
        the exists() check does not. Most callers (manual typing, Browse) are
        fine ignoring this -- the field itself still shows what was rejected.
        ``_use_install_root`` is the one caller that needs to know, since it
        would otherwise close its results dialog as if a picked install had
        been applied when it silently was not (#385 review).
        """
        game_path = self.game_path_input.text().strip()
        if game_path:
            # Normalize to native separators (backslashes on Windows). Qt's
            # QFileDialog returns POSIX-style forward slashes and Path.resolve()
            # also yields forward slashes in some flows; without this the field
            # toggles between styles depending on how the path arrived.
            game_path = os.path.normpath(game_path)
            self.game_path_input.setText(game_path)
        if game_path and not Path(game_path).exists():
            logger.warning(f"SC install root does not exist: {game_path}")
            return False
        AppSettings.set_sc_install_root(game_path)  # also syncs legacy GAME_INSTALL_PATH
        self._populate_channel_combo()
        self._refresh_p4k_status()
        return True

    def _browse_game_path(self):
        start_dir = self.game_path_input.text().strip() or str(AppSettings.get_sc_install_root())
        path = QFileDialog.getExistingDirectory(
            self, tr("config.select_sc_root"), start_dir
        )
        if path:
            self.game_path_input.setText(path)
            self._save_game_path()

    # ── Duplicate-install check (2.4) ────────────────────────────────────────

    def _check_other_installs(self, deep: bool = False):
        """Scan for every Star Citizen install and show the results dialog.

        Runs in :class:`InstallScanWorker` even for the quick scan: reading
        each install's applied global.ini for the apply watermark is cheap
        warm but measured at 26 s cold, which would freeze the window.

        Re-entry guard (#385 review): the dialog's own "Scan all drives"
        button stays enabled for the whole deep scan (`set_report` only
        touches it once a report arrives), and the deep walk is slow by
        design -- exactly the window a second click needs. Without this, a
        second call reassigns `self._dupe_worker`/`self._dupe_progress` to
        the new scan, and the first worker's `finished` handler hits the
        (correct, already-tested) stale-worker identity check and returns
        before ever closing its own progress dialog -- an orphaned progress
        window left on screen for the life of the app.
        """
        if getattr(self, "_dupe_worker", None) is not None:
            return

        from src.gui.workers import AnimatedProgressDialog, InstallScanWorker

        self._dupe_check_btn.setEnabled(False)
        # Parent to the results dialog when one is already open (a deep scan
        # launched from inside it) so the progress window stacks above that
        # modal instead of behind it.
        open_dialog = getattr(self, "_dupe_dialog", None)
        progress_parent = open_dialog if (open_dialog and open_dialog.isVisible()) else self
        # A quick scan has nothing meaningful to cancel and finishes in a
        # blink; only the drive walk gets a working Cancel button (passing
        # real button text here, not just wiring .canceled below, is what
        # actually makes Qt create one — #385 review).
        cancel_text = tr("config.dupe_deep_scan_cancel_btn") if deep else None
        self._dupe_progress = AnimatedProgressDialog(
            tr("config.dupe_scanning"), progress_parent, title=tr("config.dupe_title"),
            cancel_text=cancel_text,
        )
        # Hard backstop on top of the label eliding in InstallScanWorker:
        # QProgressDialog grows to fit its label and never shrinks, so without
        # a cap one long path stretches it across the screen for the rest of
        # the scan. 560 comfortably fits an elided path at this font size.
        self._dupe_progress.setMaximumWidth(560)
        if deep:
            self._dupe_progress.canceled.connect(self._cancel_install_scan)

        self._dupe_worker = InstallScanWorker(deep=deep, parent=self)
        self._dupe_worker.progress_pct.connect(self._dupe_progress.set_progress)
        self._dupe_worker.error.connect(self._on_install_scan_error)
        # w=self._dupe_worker binds at connect time, not call time -- this is
        # how _on_install_scan_finished tells "the worker that just finished"
        # apart from "whatever self._dupe_worker points at right now", which
        # can already be a newer scan by the time a cancelled one's finished
        # signal actually arrives (#385 review).
        self._dupe_worker.finished.connect(
            lambda report, w=self._dupe_worker: self._on_install_scan_finished(report, w)
        )
        self._dupe_worker.start()

    def _cancel_install_scan(self):
        worker = getattr(self, "_dupe_worker", None)
        if worker is not None:
            worker.cancel()

    def _on_install_scan_error(self, message: str):
        QMessageBox.warning(
            self,
            tr("config.dupe_scan_failed_title"),
            tr("config.dupe_scan_failed_body", error=message),
        )

    def _on_install_scan_finished(self, report, worker):
        """Tear the worker down, then show or refresh the results dialog.

        Cancel-then-act (re-scan, or close the dialog) leaves a scan whose
        `finished` can arrive after something newer already replaced what it
        was going to touch. Two cases (#385 review):

        * Re-scanning before the cancelled worker's own `finished` arrives
          reassigns `self._dupe_worker` to the new one. Without the identity
          check below, this handler would call `.wait()` on that NEW, still-
          running worker instead of the one that actually just finished --
          and a custom-`run()` QThread ignores `.quit()`, so `.wait()` blocks
          the GUI thread for the whole new scan.
        * Cancel, then close the results dialog, still leaves the cancelled
          worker running. Without the `report.cancelled` check below, its
          late `finished` would build and `.exec()` a brand new modal
          dialog the user already explicitly dismissed.

        `worker` is the specific instance this call's connection was bound
        to (see the `lambda report, w=...` at the connect site), not
        whatever `self._dupe_worker` happens to hold when this runs -- that
        is the whole fix, so testing it needs both to be able to disagree.
        """
        worker.quit()
        worker.wait()  # the worker that just emitted finished() has, by
                        # definition, already returned from run() -- this is
                        # never the wait-on-a-live-thread case above.
        if worker is not self._dupe_worker:
            return

        self._dupe_worker = None
        progress = getattr(self, "_dupe_progress", None)
        if progress is not None:
            progress.close()
            self._dupe_progress = None

        self._dupe_check_btn.setEnabled(True)
        if report is None:
            return  # the error slot already told the user

        dialog = getattr(self, "_dupe_dialog", None)
        if dialog is not None and dialog.isVisible():
            # A deep scan launched from inside the dialog: refresh in place
            # rather than stacking a second window on top of the first.
            dialog.set_report(report)
            return
        if report.cancelled:
            # No dialog open to refresh, and the scan that just finished was
            # explicitly cancelled -- the user asked to stop, so don't pop a
            # fresh results window open after they've already moved on.
            return

        from src.gui.duplicate_install_dialog import DuplicateInstallDialog
        dialog = DuplicateInstallDialog(report, self)
        dialog.install_selected.connect(self._use_install_root)
        dialog.deep_scan_requested.connect(lambda: self._check_other_installs(deep=True))
        self._dupe_dialog = dialog
        dialog.exec()
        self._dupe_dialog = None

    def _use_install_root(self, root: str):
        """Repoint Smart Citizen at *root*, picked from the results dialog.

        Goes through the same field-then-``_save_game_path`` path a manual
        Browse does, so channel-combo refresh, P4K status, and the legacy
        GAME_INSTALL_PATH sync all happen exactly once and in one place.
        """
        logger.info(f"Switching SC install root to {root!r} from the install check")
        self.game_path_input.setText(os.path.normpath(root))
        if not self._save_game_path():
            # The install picked from the scan results vanished between scan
            # time and click time (unplugged removable drive, dropped share).
            # Closing the dialog anyway would look identical to a successful
            # switch -- exactly the silent no-op this feature exists to catch
            # (#385 review).
            QMessageBox.warning(
                self,
                tr("config.dupe_use_failed_title"),
                tr("config.dupe_use_failed_body", path=root),
            )
            return
        dialog = getattr(self, "_dupe_dialog", None)
        if dialog is not None:
            dialog.accept()

    # ── Smart Citizen data folder ────────────────────────────────────────────

    def _save_data_dir(self):
        """Persist the Smart Citizen data folder override."""
        current_dir = AppSettings.get_user_data_dir()
        raw_path = self.data_dir_input.text().strip()
        if raw_path:
            raw_path = os.path.normpath(raw_path)

        try:
            if raw_path:
                target = Path(os.path.expandvars(raw_path)).expanduser().resolve()
                if target.exists() and not target.is_dir():
                    QMessageBox.warning(
                        self,
                        tr("config.invalid_data_folder_title"),
                        tr("config.invalid_data_folder_body", path=target),
                    )
                    self.data_dir_input.setText(str(current_dir))
                    return
                # Warn before committing a OneDrive-managed folder: OneDrive can
                # sync and empty these files, which has caused lost edits (#172).
                from src.utils.onedrive import is_onedrive_path
                if is_onedrive_path(target):
                    proceed = QMessageBox.warning(
                        self,
                        tr("config.onedrive_folder_title"),
                        tr("config.onedrive_folder_body", path=target),
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    if proceed != QMessageBox.StandardButton.Yes:
                        self.data_dir_input.setText(str(current_dir))
                        return
                target.mkdir(parents=True, exist_ok=True)
                AppSettings.set_user_data_dir(target)
            else:
                AppSettings.set_user_data_dir(None)

            new_dir = AppSettings.get_user_data_dir()
        except OSError as e:
            logger.warning(f"Could not use Smart Citizen data folder {raw_path!r}: {e}")
            QMessageBox.warning(
                self,
                tr("config.invalid_data_folder_title"),
                f"Smart Citizen could not use that data folder:\n{e}",
            )
            self.data_dir_input.setText(str(current_dir))
            return

        self.data_dir_input.setText(os.path.normpath(str(new_dir)))
        if new_dir != current_dir:
            logger.info(f"Smart Citizen data folder changed: {current_dir} → {new_dir}")
            self._maybe_migrate_data(current_dir, new_dir)
            self._refresh_p4k_status()
            self.data_dir_changed.emit(str(new_dir))

    def _maybe_migrate_data(self, old_dir, new_dir) -> None:
        """Offer to copy existing data (overrides, backups, cached strings)
        from the previous data folder into the new one, so favourites and
        edits follow the move instead of being left behind (issue #103).
        Copies (never overwrites), so the originals remain as a safety net."""
        try:
            old_path = Path(old_dir)
            if not old_path.exists() or not any(old_path.iterdir()):
                return
        except OSError:
            return
        reply = QMessageBox.question(
            self,
            tr("config.migrate_data_title"),
            tr("config.migrate_data_body", old_dir=old_dir, new_dir=new_dir),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            count = migrate_user_data_dir(old_dir, new_dir, move=True)
            QMessageBox.information(
                self, tr("config.migrate_data_done_title"),
                tr("config.migrate_data_done_body", count=count),
            )
        except Exception as e:  # pragma: no cover - defensive UI guard
            logger.exception(f"Data migration failed: {e}")
            QMessageBox.warning(
                self, tr("config.migrate_data_failed_title"),
                tr("config.migrate_data_failed_body", error=e),
            )

    def change_data_dir_to(self, path: str) -> None:
        """Set the data folder programmatically through the same validated
        save + migrate + reload flow as the text input. Used by the startup
        OneDrive warning's "move to a local folder" action (#172)."""
        self.data_dir_input.setText(os.path.normpath(str(path)))
        self._save_data_dir()

    def _browse_data_dir(self):
        start_dir = self.data_dir_input.text().strip() or str(AppSettings.get_user_data_dir())
        path = QFileDialog.getExistingDirectory(
            self, tr("config.select_data_folder"), start_dir
        )
        if path:
            self.data_dir_input.setText(path)
            self._save_data_dir()

    def _reset_data_dir(self):
        current_dir = AppSettings.get_user_data_dir()
        AppSettings.set_user_data_dir(None)
        new_dir = AppSettings.get_user_data_dir()
        self.data_dir_input.setText(os.path.normpath(str(new_dir)))
        if new_dir != current_dir:
            logger.info(f"Smart Citizen data folder reset to default: {new_dir}")
            self._maybe_migrate_data(current_dir, new_dir)
            self._refresh_p4k_status()
            self.data_dir_changed.emit(str(new_dir))

    # ── DataForge cache folder ───────────────────────────────────────────────
    # The cache path is independent of the app-data path so users can target
    # a fast local SSD for the 1.4 GB DataForge tree without disturbing their
    # user.ini / sources. Changing the path requires a re-extraction (the
    # old cache contents aren't migrated — moving 28k tiny files is slower
    # than letting unforge rebuild from Data.p4k), so the user gets a
    # 3-button prompt: Re-extract + delete old / Re-extract + keep old /
    # Cancel. Cancel reverts the input to the previous value.

    def _maybe_apply_cache_change(self, new_override: "str | None") -> bool:
        """Common path for set/browse/reset.

        Returns ``True`` when the new override was accepted (the caller
        should refresh the input field) and ``False`` when the user
        cancelled the migration dialog (caller should revert the input).
        """
        old_base = AppSettings.get_dataforge_cache_base()
        old_leaf = AppSettings.get_dataforge_cache_dir()
        # Stash + temporarily apply the prospective override so the resolved
        # base picks up env-var expansion + resolve() in the same code path
        # production uses. Revert if the user cancels.
        prev_override = AppSettings.get_cache_dir_override()
        AppSettings.set_cache_dir(new_override)
        new_base = AppSettings.get_dataforge_cache_base()
        new_leaf = AppSettings.get_dataforge_cache_dir()

        if new_base == old_base:
            # No-op change (e.g. user typed the same path they had). The
            # mkdir inside get_dataforge_cache_dir is harmless.
            return True

        # Only prompt when the old cache actually has extracted content.
        # The ``.p4k_mtime`` stamp is written by pak_extractor.py once an
        # extraction succeeds, so its presence is the cheapest "is this a
        # populated cache" probe (avoids walking 28k files).
        from src.utils.pak_extractor import P4K_MTIME_STAMP
        old_has_content = (old_leaf / P4K_MTIME_STAMP).exists()
        if not old_has_content:
            logger.info(
                f"DataForge cache base changed: {old_base} → {new_base} "
                f"(old leaf empty; no migration prompt)"
            )
            self.cache_dir_changed.emit(str(new_leaf))
            return True

        # The shipped behavior is: never silently move ~1.4 GB. We ask the
        # user up-front whether to also clean up the orphan, and only the
        # cleanup is deferred (after re-extraction completes). The
        # re-extraction itself is triggered immediately via the signal so
        # the user can fire it off and walk away.
        prompt = QMessageBox(self)
        prompt.setWindowTitle(tr("config.dataforge_cache_changed_title"))
        prompt.setIcon(QMessageBox.Icon.Question)
        prompt.setText(tr("config.dataforge_cache_changed_body"))
        prompt.setInformativeText(tr("config.dataforge_cache_old_new", old=old_leaf, new=new_leaf))
        delete_btn = prompt.addButton(tr("config.re_extract_delete_old"), QMessageBox.ButtonRole.AcceptRole)
        keep_btn = prompt.addButton(tr("config.re_extract_keep_old"), QMessageBox.ButtonRole.AcceptRole)
        cancel_btn = prompt.addButton(QMessageBox.StandardButton.Cancel)
        prompt.setDefaultButton(keep_btn)
        prompt.exec()
        clicked = prompt.clickedButton()

        if clicked is cancel_btn:
            AppSettings.set_cache_dir(prev_override or None)
            return False

        if clicked is delete_btn:
            # MainWindow drains this after the next successful re-extract.
            AppSettings.set_pending_cache_cleanup(old_leaf)
            logger.info(
                f"DataForge cache path changed; queued old cache for cleanup "
                f"after re-extraction: {old_leaf}"
            )
        else:
            # Re-extract + keep old: don't queue cleanup. The orphan stays
            # until the user removes it manually.
            AppSettings.set_pending_cache_cleanup(None)
            logger.info(
                f"DataForge cache path changed; old cache retained at {old_leaf}"
            )

        self.cache_dir_changed.emit(str(new_leaf))
        return True

    def _save_cache_dir(self):
        raw_path = self.cache_dir_input.text().strip()
        if raw_path:
            raw_path = os.path.normpath(raw_path)

        try:
            if raw_path:
                target = Path(os.path.expandvars(raw_path)).expanduser().resolve()
                if target.exists() and not target.is_dir():
                    QMessageBox.warning(
                        self,
                        tr("config.invalid_cache_folder_title"),
                        f"The selected cache folder is a file, not a directory:\n{target}",
                    )
                    self.cache_dir_input.setText(
                        os.path.normpath(str(AppSettings.get_dataforge_cache_base()))
                    )
                    return
                target.mkdir(parents=True, exist_ok=True)
                accepted = self._maybe_apply_cache_change(str(target))
            else:
                accepted = self._maybe_apply_cache_change(None)
        except OSError as e:
            logger.warning(f"Could not use DataForge cache folder {raw_path!r}: {e}")
            QMessageBox.warning(
                self,
                tr("config.invalid_cache_folder_title"),
                f"Smart Citizen could not use that cache folder:\n{e}",
            )
            self.cache_dir_input.setText(
                os.path.normpath(str(AppSettings.get_dataforge_cache_base()))
            )
            return

        # Always re-read AppSettings on exit — the user may have cancelled,
        # in which case the override is restored to its previous value.
        self.cache_dir_input.setText(
            os.path.normpath(str(AppSettings.get_dataforge_cache_base()))
        )
        if accepted:
            self._refresh_p4k_status()

    def _browse_cache_dir(self):
        start_dir = (
            self.cache_dir_input.text().strip()
            or str(AppSettings.get_dataforge_cache_base())
        )
        path = QFileDialog.getExistingDirectory(
            self, tr("config.select_cache_folder"), start_dir
        )
        if path:
            self.cache_dir_input.setText(path)
            self._save_cache_dir()

    def _reset_cache_dir(self):
        accepted = self._maybe_apply_cache_change(None)
        self.cache_dir_input.setText(
            os.path.normpath(str(AppSettings.get_dataforge_cache_base()))
        )
        if accepted:
            self._refresh_p4k_status()

    # ── Channel selector ─────────────────────────────────────────────────────

    def _populate_channel_combo(self):
        """Rebuild the channel combo, marking channels without a Data.p4k
        under the configured root as disabled.

        Signals are blocked while we mutate so an index change triggered by
        ``setCurrentIndex`` doesn't fire our ``currentIndexChanged`` slot,
        which would double-fire the channel-change reload logic.
        """
        if not hasattr(self, "channel_combo"):
            return
        blocker = self.channel_combo.blockSignals(True)
        try:
            self.channel_combo.clear()
            root = AppSettings.get_sc_install_root()
            active = AppSettings.get_active_channel()
            available_lookup = set(AppSettings.get_available_channels()) if root else set()
            active_index = 0
            for i, channel in enumerate(AppSettings.AVAILABLE_CHANNELS):
                self.channel_combo.addItem(channel, userData=channel)
                is_available = channel in available_lookup
                # Qt combo-item disable: set Qt.ItemFlag.NoItemFlags on the
                # item via the model, then a tooltip explains why.
                item = self.channel_combo.model().item(i)
                if item is not None and not is_available and root:
                    from PyQt6.QtCore import Qt
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                    item.setToolTip(tr(
                        "config.channel_not_installed_tooltip",
                        channel=channel, path=str(Path(root) / channel / "Data.p4k"),
                    ))
                if channel == active:
                    active_index = i
            self.channel_combo.setCurrentIndex(active_index)

            # If the stored active channel is unavailable, surface that with
            # a hint label so the user knows why things might not work.
            if root and active not in available_lookup:
                self._channel_hint_label.setText(
                    tr("config.channel_not_installed_hint", channel=active)
                )
                self._channel_hint_label.setStyleSheet("font-size: 10px; color: #ff9800;")
            else:
                self._channel_hint_label.setText("")
        finally:
            self.channel_combo.blockSignals(blocker)

    def _on_channel_changed(self, index: int):
        """Persist the new active channel and notify the main window."""
        if index < 0:
            return
        channel = self.channel_combo.itemData(index)
        if not channel or channel == AppSettings.get_active_channel():
            return
        # Reject selection of disabled (not-installed) items defensively —
        # Qt normally prevents this, but some desktop environments can
        # still produce a currentIndexChanged here if the model's item
        # flags were bypassed.
        item = self.channel_combo.model().item(index)
        if item is not None:
            from PyQt6.QtCore import Qt
            if not (item.flags() & Qt.ItemFlag.ItemIsEnabled):
                QMessageBox.warning(
                    self, tr("config.channel_not_installed_title"),
                    tr("config.channel_not_installed_body", channel=channel),
                )
                # Revert the combo to the active channel.
                self._populate_channel_combo()
                return
        logger.info(f"Active channel switching: {AppSettings.get_active_channel()} → {channel}")
        AppSettings.set_active_channel(channel)  # also syncs legacy GAME_INSTALL_PATH
        self._refresh_p4k_status()
        self.channel_changed.emit(channel)

    # ── Language selector ────────────────────────────────────────────────────

    def _populate_language_combo(self):
        """Rebuild the language combo from the bundled languages/ directory."""
        if not hasattr(self, "language_combo"):
            return
        blocker = self.language_combo.blockSignals(True)
        try:
            self.language_combo.clear()
            for lang in AppSettings.get_available_languages():
                self.language_combo.addItem(lang.replace("_", " ").title(), userData=lang)
            current = AppSettings.get_selected_language()
            idx = self.language_combo.findData(current)
            if idx < 0:
                # The persisted language is no longer offered (e.g. an
                # untranslated stub that is now hidden). Fall back to the
                # default so the combo and the stored setting stay in sync.
                AppSettings.set_selected_language(AppSettings.DEFAULT_LANGUAGE)
                idx = self.language_combo.findData(AppSettings.DEFAULT_LANGUAGE)
            if idx >= 0:
                self.language_combo.setCurrentIndex(idx)
        finally:
            self.language_combo.blockSignals(blocker)

    def _on_language_changed(self, index: int):
        """Persist the new language and notify the main window."""
        if index < 0:
            return
        language = self.language_combo.itemData(index)
        if not language or language == AppSettings.get_selected_language():
            return
        AppSettings.set_selected_language(language)
        logger.info(f"Language changed to: {language}")
        self.language_changed.emit(language)

    def _open_language_source_dialog(self):
        """Open the Map Language File dialog to edit per-language base.ini URLs."""
        LanguageSourceDialog(self).exec()

    # ── P4K status ───────────────────────────────────────────────────────────

    def _refresh_p4k_status(self):
        p4k_path = AppSettings.get_p4k_path()
        base_ini = AppSettings.get_cache_dir() / 'base.ini'
        needs_update = False

        if p4k_path.exists():
            self._p4k_status_dot.setStyleSheet("color: #4caf50; font-size: 14px;")
            if base_ini.exists():
                try:
                    last_str = datetime.fromtimestamp(
                        base_ini.stat().st_mtime
                    ).strftime("%Y-%m-%d %H:%M")
                except Exception:
                    last_str = "unknown"
                self._p4k_status_label.setText(
                    tr("config.p4k_status_found_with_base", date=last_str)
                )
                needs_update = p4k_path.stat().st_mtime > base_ini.stat().st_mtime
            else:
                self._p4k_status_label.setText(tr("config.p4k_status_found_no_base"))
                needs_update = True
        else:
            self._p4k_status_dot.setStyleSheet("color: #f44336; font-size: 14px;")
            if AppSettings.get_game_install_path():
                self._p4k_status_label.setText(tr("config.p4k_status_not_found", path=p4k_path))
            else:
                self._p4k_status_label.setText(tr("config.p4k_status_no_path"))

        self._set_extract_btn_needs_update(needs_update)

    def _set_extract_btn_needs_update(self, needs_update: bool) -> None:
        """Red button text when base.ini has never been extracted or Data.p4k
        is newer than the cached copy — a nudge, not a gate. Unlike Generate
        Enhancements/Apply Enhancements, this button is never disabled: users
        may legitimately want to re-extract even when nothing looks stale
        (e.g. after manually clearing part of the cache)."""
        self._extract_btn.setStyleSheet(
            f"color: {get_button_color('needs_apply')};" if needs_update else ""
        )

    # ── Updates ──────────────────────────────────────────────────────────────

    def set_update_status(self, text: str) -> None:
        """Write a short status string next to the 'Check for Updates' button.

        MainWindow calls this from its app-update signal handlers so the
        result ("Up to date", "v0.9.4 available", "Check failed") sits
        inline with the button without this tab needing to know about
        the worker.
        """
        self._update_status_label.setText(text)

    def set_check_updates_enabled(self, enabled: bool) -> None:
        """Toggle the 'Check for Updates' button — disable while a check runs."""
        self._check_updates_btn.setEnabled(enabled)

    # ── Preview ──────────────────────────────────────────────────────────────

    def preview_merge(self):
        """Show a dry-run summary of what Apply Enhancements would write.

        Mirrors the post-Apply success dialog so the preview reads as
        a "what will I get" forecast: per-source key counts, with the
        Smart Citizen Enhancements row broken down by category, plus
        a status (Modified / Enhanced / Unmodified / New) tally.
        """
        try:
            from collections import Counter
            from src.parser.ini_parser import load_sources_from_settings, load_source_files

            sources_dict, hierarchy, _enhancements_cats = load_sources_from_settings()

            if not sources_dict:
                QMessageBox.warning(self, tr("dialogs.warning_title"), tr("config.no_sources_warning"))
                return

            entries = load_source_files(sources_dict, hierarchy)

            # Count contributions per source. The merge engine overlays later
            # sources on top of earlier ones, with user.ini always winning —
            # so a key the user has overridden is contributed by the user
            # source, even though entry.source_file still records its
            # original baseline source. Without this, the User row in the
            # preview always reads 0 unless the user added a brand-new key.
            from src.utils.settings import AppSettings as _AS
            source_counts: dict[str, int] = {}
            # Per-category counter for the enhancements source so we can
            # mirror the Apply-to-game dialog's breakdown. Other sources
            # don't get the category split — they're either "Global" (the
            # whole base) or "User" (always small enough to read at a
            # glance).
            enhancement_categories: Counter[str] = Counter()
            ENHANCEMENTS_SRC = "enhancements"
            for entry in entries:
                contributing = _AS.SOURCE_USER if entry.custom_value else entry.source_file
                source_counts[contributing] = source_counts.get(contributing, 0) + 1
                if contributing == ENHANCEMENTS_SRC:
                    enhancement_categories[entry.category] += 1

            # Filter out zero-key entries before displaying — leftover
            # `contracts` / `components` / `commodities` / `gear` source
            # entries from pre-0.7.0 registry state can linger in the
            # hierarchy even after `migrate_remove_retired_url_sources`
            # ran, because that migrator only prunes URL-backed paths.
            # Their content has been folded into the general
            # enhancements pipeline, so showing them as "X (0 keys)"
            # is just visual noise. Renumber remaining entries so the
            # list reads 1, 2, 3, ... without gaps.
            text = tr("config.preview_header")
            visible_index = 0
            for name in hierarchy:
                count = source_counts.get(name, 0)
                if count == 0:
                    continue
                visible_index += 1
                if name == ENHANCEMENTS_SRC:
                    text += f"  {visible_index}. Smart Citizen Enhancements ({count:,} keys total):\n"
                    if enhancement_categories:
                        for cat, ccount in enhancement_categories.most_common():
                            text += f"       {cat}: {ccount:,}\n"
                else:
                    text += f"  {visible_index}. {name.capitalize()} ({count:,} keys)\n"

            text += tr("config.preview_total", count=len(entries))
            status_counts: dict[str, int] = {}
            for entry in entries:
                status_counts[entry.status] = status_counts.get(entry.status, 0) + 1
            # Sort descending by count so the largest bucket leads —
            # consistent with the Apply dialog's most_common() ordering.
            for status, count in sorted(status_counts.items(), key=lambda kv: -kv[1]):
                text += f"  {status}: {count:,}\n"

            QMessageBox.information(self, tr("config.preview_title"), text)

        except Exception as e:
            logger.exception(f"Error previewing merge: {e}")
            QMessageBox.critical(self, tr("dialogs.error_title"), tr("config.preview_merge_failed", error=e))


class LanguageSourceDialog(QDialog):
    """Edit per-language override URLs for the base.ini (global.ini) download.

    One row per non-English language Smart Citizen knows about (the bundled
    languages/sources.json keys, plus any language that already has an
    override). The URL a user enters here wins over the bundled map; switching
    to that language downloads it and uses it as the base strings (issue #30).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("config.map_language_title"))
        self.setMinimumWidth(560)
        from src.utils.settings import _bundled_language_sources

        layout = QVBoxLayout(self)
        info = QLabel(tr("config.map_language_desc"))
        info.setWordWrap(True)
        info.setProperty("role", "secondary")
        layout.addWidget(info)

        # Only languages the user can actually switch to — the same filter the
        # language selector uses (excludes untranslated stubs like Spanish).
        # Mapping a base.ini URL for a language you can't select is pointless.
        bundled = _bundled_language_sources()
        langs = [
            lang for lang in AppSettings.get_available_languages()
            if lang != AppSettings.DEFAULT_LANGUAGE
        ]

        self._inputs: dict[str, QLineEdit] = {}
        grid = QGridLayout()
        for row, lang in enumerate(sorted(langs)):
            label = QLabel(lang.replace("_", " ").title())
            edit = QLineEdit(AppSettings.get_language_source_override(lang))
            edit.setPlaceholderText(
                bundled.get(lang, "") or tr("config.language_source_placeholder")
            )
            grid.addWidget(label, row, 0)
            grid.addWidget(edit, row, 1)
            self._inputs[lang] = edit
        layout.addLayout(grid)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self):
        for lang, edit in self._inputs.items():
            AppSettings.set_language_source_override(lang, edit.text().strip())
        logger.info("Saved language base.ini URL overrides")
        self.accept()
