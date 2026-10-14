"""Overlay tab: start/stop and options for the Smart Citizen Overlay (SCO).

The switches persist through ``AppSettings.get_/set_sco_option``; this tab
only edits them and says so. ``MainWindow`` owns the overlay itself and
keeps the toolbar's Overlay button and this tab's start button in step.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from src.gui.combo_box import NoScrollComboBox
from src.gui.theme import get_button_color, get_button_text_color
from src.utils.i18n import tr
from src.utils.settings import AppSettings

logger = logging.getLogger(__name__)


DRAWER_SECTION_PREFIX = AppSettings.SCO_DRAWER_SECTION_PREFIX
# How far the drawer's section switches and position picker sit in under
# the drawer switch.
DRAWER_SECTION_INDENT = 22
# A checkbox's indicator plus its gap: hints and the samples button line up
# with the checkbox text above them, not its box.
CHECK_TEXT_INDENT = 22


class OverlayTab(QWidget):
    """Start/stop button plus one checkbox per SCO option."""

    overlay_toggled = pyqtSignal(bool)
    options_changed = pyqtSignal()

    def __init__(self, samples_dir: Optional[Path] = None, parent=None):
        super().__init__(parent)
        # None: AppSettings.get_sco_samples_dir() when opened, so a data-folder
        # move is followed.
        self._samples_dir = samples_dir
        self._checks: dict[str, QCheckBox] = {}
        self._hints: dict[str, QLabel] = {}
        self.setup_ui()

    def setup_ui(self):
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self._title_label = QLabel()
        self._title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(self._title_label)

        self._desc_label = QLabel()
        self._desc_label.setProperty("role", "secondary")
        self._desc_label.setStyleSheet("font-size: 11px;")
        self._desc_label.setWordWrap(True)
        layout.addWidget(self._desc_label)

        self._start_btn = QPushButton()
        self._start_btn.setCheckable(True)
        self.refresh_styles()
        self._start_btn.toggled.connect(self._on_start_toggled)
        start_row = QHBoxLayout()
        start_row.addWidget(self._start_btn)
        start_row.addStretch()
        layout.addLayout(start_row)

        for name in AppSettings.SCO_OPTION_SETTING:
            # The drawer's sections sit indented under the drawer switch.
            indent = DRAWER_SECTION_INDENT if name.startswith(DRAWER_SECTION_PREFIX) else 0
            check = QCheckBox()
            check.setChecked(AppSettings.get_sco_option(name))
            check.toggled.connect(lambda on, n=name: self._on_option_toggled(n, on))
            check.setStyleSheet(f"margin-left: {indent}px;")
            hint = QLabel()
            hint.setProperty("role", "secondary")
            hint.setStyleSheet(f"font-size: 11px; margin-left: {indent + CHECK_TEXT_INDENT}px;")
            hint.setWordWrap(True)
            layout.addWidget(check)
            layout.addWidget(hint)
            self._checks[name] = check
            self._hints[name] = hint
            if name == AppSettings.SCO_DRAWER:
                layout.addLayout(self._position_row())
        drawer = self._checks[AppSettings.SCO_DRAWER]
        drawer.toggled.connect(self._sync_section_enabled)
        self._sync_section_enabled(drawer.isChecked())

        self._open_samples_btn = QPushButton()
        self._open_samples_btn.clicked.connect(self._open_samples_folder)
        samples_row = QHBoxLayout()
        samples_row.setContentsMargins(CHECK_TEXT_INDENT, 0, 0, 0)
        samples_row.addWidget(self._open_samples_btn)
        samples_row.addStretch()
        layout.addLayout(samples_row)
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

        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        """Re-apply tr() to every text-bearing widget after a language switch."""
        self._title_label.setText(tr("overlay.title"))
        self._desc_label.setText(tr("overlay.desc"))
        self._sync_start_text()
        for name, check in self._checks.items():
            check.setText(tr(f"overlay.{name}"))
            self._hints[name].setText(tr(f"overlay.{name}_hint"))
        self._open_samples_btn.setText(tr("overlay.open_samples_btn"))
        self._position_label.setText(tr("overlay.drawer_position"))
        for i, position in enumerate(AppSettings.SCO_DRAWER_POSITIONS):
            self._position_combo.setItemText(i, tr(f"overlay.position_{position}"))

    def refresh_styles(self) -> None:
        """Re-apply the theme's button colours (MainWindow calls this after a
        live theme swap, with its toolbar buttons)."""
        self._start_btn.setStyleSheet(
            f"background-color: {get_button_color('open')}; "
            f"color: {get_button_text_color()}; font-weight: bold; padding: 6px;")

    def set_running(self, running: bool) -> None:
        """Mirror the overlay's state without asking for a change."""
        self._start_btn.blockSignals(True)
        self._start_btn.setChecked(running)
        self._start_btn.blockSignals(False)
        self._sync_start_text()

    def set_option(self, name: str, on: bool) -> None:
        """Mirror a switch changed elsewhere (the SCO drawer) without
        re-saving it or emitting ``options_changed``."""
        check = self._checks[name]
        check.blockSignals(True)
        check.setChecked(on)
        check.blockSignals(False)

    def _sync_start_text(self) -> None:
        key = "overlay.stop_btn" if self._start_btn.isChecked() else "overlay.start_btn"
        self._start_btn.setText(tr(key))

    def _on_start_toggled(self, on: bool) -> None:
        self._sync_start_text()
        self.overlay_toggled.emit(on)

    def _on_option_toggled(self, name: str, on: bool) -> None:
        AppSettings.set_sco_option(name, on)
        self.options_changed.emit()

    def _position_row(self) -> QHBoxLayout:
        """Drawer position picker, indented under the drawer switch."""
        self._position_label = QLabel()
        self._position_combo = NoScrollComboBox()
        for position in AppSettings.SCO_DRAWER_POSITIONS:
            self._position_combo.addItem("", position)
        self._position_combo.setCurrentIndex(
            AppSettings.SCO_DRAWER_POSITIONS.index(AppSettings.get_sco_drawer_position()))
        self._position_combo.currentIndexChanged.connect(self._on_position_changed)
        row = QHBoxLayout()
        row.setContentsMargins(DRAWER_SECTION_INDENT, 0, 0, 0)
        row.addWidget(self._position_label)
        row.addWidget(self._position_combo)
        row.addStretch()
        return row

    def _on_position_changed(self, index: int) -> None:
        AppSettings.set_sco_drawer_position(self._position_combo.itemData(index))
        self.options_changed.emit()

    def _sync_section_enabled(self, drawer_on: bool) -> None:
        for name, check in self._checks.items():
            if name.startswith(DRAWER_SECTION_PREFIX):
                check.setEnabled(drawer_on)
                self._hints[name].setEnabled(drawer_on)
        self._position_label.setEnabled(drawer_on)
        self._position_combo.setEnabled(drawer_on)

    def _open_samples_folder(self) -> None:
        samples_dir = self._samples_dir or AppSettings.get_sco_samples_dir()
        try:
            samples_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.warning("SCO: could not create the samples folder %s", samples_dir)
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(samples_dir)))
