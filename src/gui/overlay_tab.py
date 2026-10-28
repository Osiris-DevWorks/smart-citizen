"""Overlay tab: start/stop and options for the Smart Citizen Overlay (SCO).

The switches persist through ``AppSettings.get_/set_sco_option``, and the
drawer position, the scan text size and the drawer hotkey through their own
getters and setters; this tab only edits them and says so. ``MainWindow``
owns the overlay itself and keeps the toolbar's Overlay button and this
tab's start button in step.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QEvent, QKeyCombination, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QKeySequence
from PyQt6.QtWidgets import (
    QCheckBox, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from src.gui.combo_box import NoScrollComboBox
from src.gui.global_hotkey import HOTKEY_UNSUPPORTED, hotkey_text, windows_hotkey
from src.gui.theme import get_button_color, get_button_text_color
from src.utils.i18n import tr
from src.utils.settings import AppSettings

logger = logging.getLogger(__name__)


DRAWER_SECTION_PREFIX = AppSettings.SCO_DRAWER_SECTION_PREFIX
ALERT_PREFIX = AppSettings.SCO_ALERT_PREFIX
# How far what hangs under a switch sits in, in its box: the scan decoder's
# text size and alerts, the drawer's sections, position and hotkey.
DRAWER_SECTION_INDENT = 22
# The hotkey box's width: room for a long combination such as Ctrl+Alt+Shift+F12.
HOTKEY_EDIT_WIDTH = 170
# A checkbox's indicator plus its gap: a switch's hint lines up with the
# checkbox text above it, not its box.
CHECK_TEXT_INDENT = 22


def hotkey_problem_text(problem: str) -> str:
    """The text for a ``global_hotkey`` problem (``HOTKEY_TAKEN``, ``HOTKEY_UNSUPPORTED``)."""
    return tr(f"overlay.hotkey_{problem}")


def _shown(sequence: str) -> str:
    """Portable text ("Ctrl+Alt+O") as the user's system names it."""
    return QKeySequence.fromString(sequence, QKeySequence.SequenceFormat.PortableText).toString(
        QKeySequence.SequenceFormat.NativeText)


_HELD = (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
         | Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.MetaModifier)
# Each modifier key and the modifier it holds (AltGr is Ctrl+Alt on Windows).
_MODIFIER_KEYS = {
    Qt.Key.Key_Control: Qt.KeyboardModifier.ControlModifier,
    Qt.Key.Key_Alt: Qt.KeyboardModifier.AltModifier,
    Qt.Key.Key_Shift: Qt.KeyboardModifier.ShiftModifier,
    Qt.Key.Key_Meta: Qt.KeyboardModifier.MetaModifier,
    Qt.Key.Key_AltGr: Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier,
}


class HotkeyEdit(QLineEdit):
    """Records one key combination: click it, then press the keys together.

    The key is the Windows virtual key the press reports, not the character
    the keyboard layout makes of it (``global_hotkey.hotkey_text``), so
    Ctrl+Alt+O works where Ctrl+Alt is AltGr and makes "ó", and Ctrl+Shift+1
    where Shift+1 makes "!" (#523). While only modifiers are held it shows
    them ("Ctrl+Alt+"). Every key comes here, Tab and app shortcuts too,
    and nothing can be typed or pasted, so the Overlay tab's Clear button
    beside it empties it (``clear_hotkey``).
    ``recorded`` carries the new combination as portable text ("" when
    cleared), ``refused`` one ``windows_hotkey`` does not take: a key
    Windows has no hotkey code for (Esc, Enter), a dead key, a symbol
    another key also types, or a key other than an F key or Pause without
    Ctrl, Alt or Win (``global_hotkey.MODIFIERS_NEEDED``).
    """

    recorded = pyqtSignal(str)
    refused = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sequence = ""
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.setAcceptDrops(False)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, False)

    def sequence(self) -> str:
        return self._sequence

    def set_sequence(self, sequence: str) -> None:
        """Show *sequence* (portable text) without announcing it."""
        self._sequence = sequence or ""
        self._show(_shown(self._sequence))

    def _show(self, text: str) -> None:
        self.blockSignals(True)
        self.setText(text)
        self.blockSignals(False)

    def event(self, event):
        if event.type() == QEvent.Type.ShortcutOverride:
            # The box takes every key, so no app shortcut fires instead.
            event.accept()
            return True
        if event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Tab,
                                                                    Qt.Key.Key_Backtab):
            self.keyPressEvent(event)                 # a key, not a focus move
            return True
        return super().event(event)

    def keyPressEvent(self, event):  # noqa: N802 (Qt's name)
        own = _MODIFIER_KEYS.get(event.key())
        if own is not None:
            # Qt leaves a modifier key's own modifier out of its press, so
            # it is added back: what is held now, the key included.
            self._show_held((event.modifiers() | own) & _HELD)
            return
        virtual_key = event.nativeVirtualKey() or self._virtual_key_of(event)
        text = hotkey_text(event.modifiers(), virtual_key) if virtual_key else None
        if text is None:
            self.set_sequence(self._sequence)
            self.refused.emit()
            return
        self.set_sequence(text)
        self.recorded.emit(text)

    def keyReleaseEvent(self, event):  # noqa: N802 (Qt's name)
        own = _MODIFIER_KEYS.get(event.key())
        if own is not None:
            self._show_held(event.modifiers() & ~own & _HELD)   # that key is up now

    def _show_held(self, held: Qt.KeyboardModifier) -> None:
        """Modifiers held with no key yet ("Ctrl+Alt+"), or, when none is
        held any more, the saved combination again."""
        if not held:
            self.set_sequence(self._sequence)
            return
        self._show(QKeySequence(QKeyCombination(held, Qt.Key.Key_A)).toString(
            QKeySequence.SequenceFormat.NativeText)[:-1])

    @staticmethod
    def _virtual_key_of(event) -> int:
        """The virtual key for a press that carries none (another platform,
        or a press sent by code), worked out from Qt's key."""
        try:
            key = Qt.Key(event.key())
        except ValueError:
            return 0
        text = QKeySequence(QKeyCombination(event.modifiers(), key)).toString(
            QKeySequence.SequenceFormat.PortableText)
        keys = windows_hotkey(text)
        return keys[1] if keys else 0

    def clear_hotkey(self) -> None:
        """No hotkey: empty the box and say so with ``recorded("")``."""
        if not self._sequence:
            return
        self.set_sequence("")
        self.recorded.emit("")


class OverlayTab(QWidget):
    """Start/stop button plus one checkbox per SCO option, in a titled box
    per part: scan decoder, drawer, blueprints from Game.log, scan samples."""

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

        # One titled box per part, as on the Config and Enhancements tabs
        # (#523): each part's switch first, what hangs under it indented.
        self._groups: dict[str, QGroupBox] = {}
        scan = self._group(layout, "scan_group")
        self._add_switch(scan, AppSettings.SCO_SCAN_DECODER)
        under = self._indented(scan)
        self._size_label, self._size_combo, row = self._picker_row(
            AppSettings.SCO_LABEL_SIZES, AppSettings.get_sco_label_size(),
            AppSettings.set_sco_label_size)
        under.addLayout(row)
        self._alerts_title = QLabel()
        under.addWidget(self._alerts_title)
        under.addLayout(self._switch_row(ALERT_PREFIX))

        drawer = self._group(layout, "drawer_group")
        self._add_switch(drawer, AppSettings.SCO_DRAWER)
        under = self._indented(drawer)
        under.addLayout(self._switch_row(DRAWER_SECTION_PREFIX))
        self._position_label, self._position_combo, row = self._picker_row(
            AppSettings.SCO_DRAWER_POSITIONS, AppSettings.get_sco_drawer_position(),
            AppSettings.set_sco_drawer_position)
        under.addLayout(row)
        under.addLayout(self._hotkey_row())
        under.addWidget(self._hotkey_hint)
        under.addWidget(self._hotkey_problem)

        self._add_switch(self._group(layout, "blueprint_watch_group"),
                         AppSettings.SCO_LIVE_BLUEPRINT_WATCH)

        samples = self._group(layout, "samples_group")
        self._open_samples_btn = QPushButton()
        self._open_samples_btn.clicked.connect(self._open_samples_folder)
        self._add_switch(samples, AppSettings.SCO_SAVE_SAMPLES, beside=self._open_samples_btn)
        layout.addStretch()

        for name in (AppSettings.SCO_SCAN_DECODER, AppSettings.SCO_DRAWER):
            self._checks[name].toggled.connect(self._sync_enabled)
        self._sync_enabled()

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
        for name, box in self._groups.items():
            box.setTitle(tr(f"overlay.{name}"))
        for name, check in self._checks.items():
            check.setText(tr(f"overlay.{name}"))
            hint = tr(f"overlay.{name}_hint")
            if name in self._hints:
                self._hints[name].setText(hint)
            else:
                check.setToolTip(hint)                # a switch in a row: no room under it
        self._open_samples_btn.setText(tr("overlay.open_samples_btn"))
        for label, combo, title, item_prefix in (
                (self._position_label, self._position_combo, "overlay.drawer_position",
                 "overlay.position_"),
                (self._size_label, self._size_combo, "overlay.label_size", "overlay.size_")):
            label.setText(tr(title))
            for i in range(combo.count()):
                combo.setItemText(i, tr(f"{item_prefix}{combo.itemData(i)}"))
        self._alerts_title.setText(tr("overlay.alerts_title"))
        self._hotkey_label.setText(tr("overlay.drawer_hotkey"))
        self._hotkey_clear.setText(tr("overlay.drawer_hotkey_clear"))
        self._hotkey_hint.setText(tr("overlay.drawer_hotkey_hint"))
        self._show_hotkey_problem()

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

    def _group(self, layout: QVBoxLayout, name: str) -> QVBoxLayout:
        """A titled box (``overlay.<name>``) added to *layout*; returns its layout."""
        box = QGroupBox()
        self._groups[name] = box
        layout.addWidget(box)
        return QVBoxLayout(box)

    @staticmethod
    def _indented(box: QVBoxLayout) -> QVBoxLayout:
        """A layout in *box* for what hangs under its switch, set in."""
        under = QVBoxLayout()
        under.setContentsMargins(DRAWER_SECTION_INDENT, 0, 0, 0)
        box.addLayout(under)
        return under

    def _new_switch(self, name: str) -> QCheckBox:
        check = QCheckBox()
        check.setChecked(AppSettings.get_sco_option(name))
        check.toggled.connect(lambda on, n=name: self._on_option_toggled(n, on))
        self._checks[name] = check
        return check

    def _add_switch(self, box: QVBoxLayout, name: str, beside: Optional[QWidget] = None) -> None:
        """A switch with its hint under it, and *beside* it on the same line."""
        row = QHBoxLayout()
        row.addWidget(self._new_switch(name))
        if beside is not None:
            row.addSpacing(12)
            row.addWidget(beside)
        row.addStretch()
        box.addLayout(row)
        hint = QLabel()
        hint.setProperty("role", "secondary")
        hint.setStyleSheet(f"font-size: 11px; margin-left: {CHECK_TEXT_INDENT}px;")
        hint.setWordWrap(True)
        box.addWidget(hint)
        self._hints[name] = hint

    def _switch_row(self, prefix: str) -> QHBoxLayout:
        """The switches named *prefix*..., side by side, in the settings' order
        (their hints become tooltips)."""
        row = QHBoxLayout()
        for name in AppSettings.SCO_OPTION_SETTING:
            if name.startswith(prefix):
                row.addWidget(self._new_switch(name))
                row.addSpacing(8)
        row.addStretch()
        return row

    def _picker_row(self, choices: tuple, current: str,
                    save) -> tuple[QLabel, NoScrollComboBox, QHBoxLayout]:
        """A label and a drop-down of *choices* (setting values; their texts
        come from ``retranslate_ui``). A pick is saved with *save* and
        announced with ``options_changed``."""
        label, combo = QLabel(), NoScrollComboBox()
        for choice in choices:
            combo.addItem("", choice)
        combo.setCurrentIndex(choices.index(current))
        combo.currentIndexChanged.connect(lambda index: self._on_pick(save, combo.itemData(index)))
        row = QHBoxLayout()
        row.addWidget(label)
        row.addWidget(combo)
        row.addStretch()
        return label, combo, row

    def _on_pick(self, save, value: str) -> None:
        save(value)
        self.options_changed.emit()

    def _hotkey_row(self) -> QHBoxLayout:
        """Drawer hotkey box (one key combination: a key with Ctrl, Alt or
        Win, and Shift if wanted, or an F key or Pause alone), with its hint
        and, when it cannot be used, why."""
        self._hotkey_label = QLabel()
        self._hotkey_edit = HotkeyEdit()
        self._hotkey_edit.setFixedWidth(HOTKEY_EDIT_WIDTH)
        self._hotkey_edit.set_sequence(AppSettings.get_sco_drawer_hotkey())
        self._hotkey_edit.recorded.connect(self._on_hotkey_recorded)
        self._hotkey_edit.refused.connect(lambda: self.set_hotkey_problem(HOTKEY_UNSUPPORTED))
        self._hotkey_hint = QLabel()
        self._hotkey_hint.setProperty("role", "secondary")
        self._hotkey_hint.setStyleSheet("font-size: 11px;")
        self._hotkey_hint.setWordWrap(True)
        self._hotkey_problem = QLabel()
        self._hotkey_problem.setStyleSheet("color: #ff9800; font-size: 11px;")
        self._hotkey_problem.setWordWrap(True)
        self._hotkey_problem.hide()
        self._problem = ""
        # The box takes every key as the hotkey, so this is how it is emptied.
        self._hotkey_clear = QPushButton()
        self._hotkey_clear.clicked.connect(self._hotkey_edit.clear_hotkey)
        row = QHBoxLayout()
        row.addWidget(self._hotkey_label)
        row.addWidget(self._hotkey_edit)
        row.addWidget(self._hotkey_clear)
        row.addStretch()
        return row

    def _on_hotkey_recorded(self, sequence: str) -> None:
        AppSettings.set_sco_drawer_hotkey(sequence)
        self.set_hotkey_problem("")
        self._sync_enabled()
        self.options_changed.emit()

    def set_hotkey_problem(self, problem: str) -> None:
        """Why the drawer hotkey is not in use (``global_hotkey.HOTKEY_TAKEN`` or
        ``HOTKEY_UNSUPPORTED``, each naming an ``overlay.hotkey_*`` text), or ""."""
        self._problem = problem
        self._show_hotkey_problem()

    def _show_hotkey_problem(self) -> None:
        if self._problem:
            self._hotkey_problem.setText(hotkey_problem_text(self._problem))
        self._hotkey_problem.setVisible(bool(self._problem))

    def _sync_enabled(self) -> None:
        """Grey out what hangs under a switch that is off (kept, not changed)."""
        decoder_on = self._checks[AppSettings.SCO_SCAN_DECODER].isChecked()
        drawer_on = self._checks[AppSettings.SCO_DRAWER].isChecked()
        for name, check in self._checks.items():
            for prefix, on in ((DRAWER_SECTION_PREFIX, drawer_on), (ALERT_PREFIX, decoder_on)):
                if name.startswith(prefix):
                    check.setEnabled(on)
        for widget in (self._size_label, self._size_combo, self._alerts_title):
            widget.setEnabled(decoder_on)
        for widget in (self._position_label, self._position_combo, self._hotkey_label,
                       self._hotkey_edit, self._hotkey_hint):
            widget.setEnabled(drawer_on)
        self._hotkey_clear.setEnabled(drawer_on and bool(self._hotkey_edit.sequence()))

    def _open_samples_folder(self) -> None:
        samples_dir = self._samples_dir or AppSettings.get_sco_samples_dir()
        try:
            samples_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.warning("SCO: could not create the samples folder %s", samples_dir)
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(samples_dir)))
