"""Simple-mode landing page (#180).

A deliberately near-empty screen for users who just want the result: one big
**Apply Enhancements** button that runs the whole export with default
settings, plus a way back to the full **Advanced** UI. The orchestration lives
on ``MainWindow`` (`_run_simple_apply`, `_apply_ui_mode`); this widget only
emits intent.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QLabel,
)

from src.gui.theme import get_button_color, get_button_text_color
from src.utils.i18n import tr


class SimpleModeWidget(QWidget):
    """The Simple-mode page: a big generate-and-apply button and a mode switch."""

    generate_and_apply_requested = pyqtSignal()
    switch_to_advanced_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # #397: mirrors MainWindow._apply_dirty's own pre-load default --
        # starts True (red/clickable) since nothing is loaded yet to know
        # otherwise. MainWindow._set_apply_btn_dirty is the one chokepoint
        # that keeps this in sync with the Advanced-mode Apply button from
        # here on, including the #387 startup check.
        self._apply_dirty = True
        self._busy = False
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 24, 40, 24)
        layout.setSpacing(16)
        layout.addStretch(1)

        # Both buttons live in one centred, width-capped column and expand to
        # fill it, so they end up the same size. Apply Enhancements (primary)
        # sits on top; Switch to Advanced below it.
        self.generate_apply_btn = QPushButton(tr("simple_mode.generate_apply_btn"))
        self.generate_apply_btn.setMinimumHeight(44)
        self.generate_apply_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        # Tooltip/color/enabled state set below by _refresh_apply_button(),
        # once self._apply_dirty / self._busy both exist -- not hardcoded here.
        self.generate_apply_btn.clicked.connect(self.generate_and_apply_requested)

        self.advanced_btn = QPushButton(tr("simple_mode.switch_to_advanced"))
        self.advanced_btn.setToolTip(tr("simple_mode.switch_to_advanced_tip"))
        self.advanced_btn.setMinimumHeight(44)
        self.advanced_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.advanced_btn.setStyleSheet(
            f"background-color: {get_button_color('open')}; "
            f"color: {get_button_text_color()}; font-weight: bold; "
            f"font-size: 14px; padding: 10px 20px;"
        )
        self.advanced_btn.clicked.connect(self.switch_to_advanced_requested)

        btn_col = QVBoxLayout()
        btn_col.setSpacing(12)
        btn_col.addWidget(self.generate_apply_btn)   # Apply Enhancements on top
        btn_col.addWidget(self.advanced_btn)         # Switch to Advanced below
        btn_wrap = QWidget()
        btn_wrap.setLayout(btn_col)
        btn_wrap.setMaximumWidth(320)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(btn_wrap)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.hint_label = QLabel(tr("simple_mode.defaults_hint"))
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint_label.setWordWrap(True)
        self.hint_label.setProperty("role", "secondary")
        layout.addWidget(self.hint_label)

        layout.addStretch(2)

        self._refresh_apply_button()

    def set_busy(self, busy: bool) -> None:
        """Disable the action button while a run is in progress."""
        self._busy = busy
        self._refresh_apply_button()

    def set_apply_dirty(self, dirty: bool) -> None:
        """Mirror the Advanced-mode Apply button's color/enabled convention
        (#397): red/clickable when there's something to apply, green/
        disabled when the loaded state already matches what's on disk.
        Called from MainWindow._set_apply_btn_dirty, the one chokepoint
        that already keeps the toolbar button in sync -- this button was
        previously never wired to it at all, hardcoded green from
        construction regardless of actual state.
        """
        self._apply_dirty = dirty
        self._refresh_apply_button()

    def _refresh_apply_button(self) -> None:
        """Single chokepoint for this button's tooltip, enabled state, and
        color, so busy-state and dirty-state can't race and leave any of
        them wrong -- busy always wins for enabled (never clickable
        mid-run), dirty decides color and tooltip always and enabled
        whenever not busy.

        The tooltip fix is #397 follow-up: this button's tooltip was still
        the single static "here's what clicking does" string from
        construction even after set_apply_dirty started correctly driving
        color/enabled -- unlike the Advanced-mode Apply button, which
        already swaps its tooltip text between the two states. Resolved
        via tr() here (not cached) so a language switch picks it up too,
        same as retranslate_ui below already does for everything else.
        """
        color = get_button_color("needs_apply" if self._apply_dirty else "apply")
        self.generate_apply_btn.setStyleSheet(
            f"background-color: {color}; "
            f"color: {get_button_text_color()}; font-weight: bold; "
            f"font-size: 14px; padding: 10px 20px;"
        )
        self.generate_apply_btn.setToolTip(
            tr("simple_mode.generate_apply_tip") if self._apply_dirty
            else tr("simple_mode.generate_apply_tip_disabled")
        )
        self.generate_apply_btn.setEnabled(self._apply_dirty and not self._busy)

    def retranslate_ui(self) -> None:
        """Re-pull strings after a language switch."""
        self.advanced_btn.setText(tr("simple_mode.switch_to_advanced"))
        self.advanced_btn.setToolTip(tr("simple_mode.switch_to_advanced_tip"))
        self.generate_apply_btn.setText(tr("simple_mode.generate_apply_btn"))
        self.hint_label.setText(tr("simple_mode.defaults_hint"))
        self._refresh_apply_button()  # re-picks the right tooltip variant too
