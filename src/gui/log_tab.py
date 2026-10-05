"""Log tab — in-app log viewer with export capability."""
import logging
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QPlainTextEdit, QFileDialog, QCheckBox, QLabel, QComboBox
)
from PyQt6.QtCore import pyqtSignal, QObject
from PyQt6.QtGui import QTextCharFormat, QColor, QFont, QTextCursor

from src.utils.i18n import tr

# Maximum lines kept in the viewer before oldest lines are dropped
_MAX_LINES = 2000

# Colours per level
_LEVEL_COLORS = {
    logging.DEBUG:    "#888888",
    logging.INFO:     "#cccccc",
    logging.WARNING:  "#ff9800",
    logging.ERROR:    "#f44336",
    logging.CRITICAL: "#f44336",
}

_LEVEL_NAMES = {
    logging.DEBUG:    "DEBUG",
    logging.INFO:     "INFO",
    logging.WARNING:  "WARNING",
    logging.ERROR:    "ERROR",
    logging.CRITICAL: "CRITICAL",
}


class _LogEmitter(QObject):
    """Bridge between the stdlib logging system and Qt signals.

    Lives on the main thread; the handler posts records to it via a signal
    so Qt's event loop delivers them safely regardless of which thread logs.
    """
    record_emitted = pyqtSignal(str, int)   # formatted message, levelno


class _QtLogHandler(logging.Handler):
    """logging.Handler that forwards records to a _LogEmitter signal."""

    def __init__(self, emitter: _LogEmitter):
        super().__init__()
        self._emitter = emitter

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            self._emitter.record_emitted.emit(msg, record.levelno)
        except Exception:
            self.handleError(record)


class LogTab(QWidget):
    """Tab showing a live stream of application log output."""

    def __init__(self):
        super().__init__()
        self._line_count = 0
        self._emitter = _LogEmitter()
        self._handler = _QtLogHandler(self._emitter)
        self._handler.setFormatter(
            logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
                              datefmt="%H:%M:%S")
        )
        self._emitter.record_emitted.connect(self._append_record)
        self.setup_ui()
        self._install_handler()

    # ── UI ────────────────────────────────────────────────────────────────────

    def setup_ui(self):
        layout = QVBoxLayout(self)
        # Zero margins so the viewer's horizontal scrollbar lands flush at the
        # tab's bottom edge, in the same pixel row as every other tab's bar.
        # NoWrap below means this view always has a horizontal bar with real
        # log content, so its placement is the most visible of the lot. The
        # 8px inset is re-applied to the toolbar and status rows instead.
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Toolbar row
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(8, 8, 8, 0)

        self._min_level_label = QLabel(tr("log.min_level_label"))
        toolbar.addWidget(self._min_level_label)
        self._level_combo = QComboBox()
        self._level_combo.setToolTip(tr("log.min_level_tooltip"))
        for level, name in [
            (logging.DEBUG,   "DEBUG"),
            (logging.INFO,    "INFO"),
            (logging.WARNING, "WARNING"),
            (logging.ERROR,   "ERROR"),
        ]:
            self._level_combo.addItem(name, userData=level)
        self._level_combo.setCurrentIndex(1)   # default: INFO
        self._level_combo.currentIndexChanged.connect(self._on_level_changed)
        toolbar.addWidget(self._level_combo)

        toolbar.addSpacing(16)

        self._autoscroll_cb = QCheckBox(tr("log.auto_scroll_check"))
        self._autoscroll_cb.setToolTip(tr("log.auto_scroll_tooltip"))
        self._autoscroll_cb.setChecked(True)
        toolbar.addWidget(self._autoscroll_cb)

        toolbar.addStretch()

        self._clear_btn = QPushButton(tr("log.clear_btn"))
        self._clear_btn.setMaximumWidth(70)
        self._clear_btn.setToolTip(tr("log.clear_tooltip"))
        self._clear_btn.clicked.connect(self._clear)
        toolbar.addWidget(self._clear_btn)

        self._export_btn = QPushButton(tr("log.export_btn"))
        self._export_btn.setMaximumWidth(130)
        self._export_btn.setToolTip(tr("log.export_tooltip"))
        self._export_btn.clicked.connect(self._export)
        toolbar.addWidget(self._export_btn)

        layout.addLayout(toolbar)

        # Log viewer
        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setMaximumBlockCount(_MAX_LINES)
        self._view.setFont(QFont("Consolas", 9))
        self._view.setStyleSheet(
            "QPlainTextEdit { background: #1e1e1e; color: #cccccc; border: none; }"
        )
        # Disable the default word-wrap so long lines scroll horizontally
        self._view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        # Status bar sits ABOVE the viewer: a widget below it would stop its
        # horizontal scrollbar reaching the tab's bottom edge, which is what
        # left this tab's bar out of line with the others.
        self._status_label = QLabel(tr("log.lines_label", count=0))
        self._status_label.setProperty("role", "secondary")
        self._status_label.setStyleSheet("font-size: 10px;")
        self._status_label.setContentsMargins(8, 0, 8, 2)
        layout.addWidget(self._status_label)

        layout.addWidget(self._view)

    # ── Retranslation ─────────────────────────────────────────────────────────

    def retranslate_ui(self) -> None:
        """Re-apply tr() to every text-bearing widget after a language switch."""
        self._min_level_label.setText(tr("log.min_level_label"))
        self._level_combo.setToolTip(tr("log.min_level_tooltip"))
        self._autoscroll_cb.setText(tr("log.auto_scroll_check"))
        self._autoscroll_cb.setToolTip(tr("log.auto_scroll_tooltip"))
        self._clear_btn.setText(tr("log.clear_btn"))
        self._clear_btn.setToolTip(tr("log.clear_tooltip"))
        self._export_btn.setText(tr("log.export_btn"))
        self._export_btn.setToolTip(tr("log.export_tooltip"))

    # ── Handler lifecycle ─────────────────────────────────────────────────────

    def _install_handler(self):
        root = logging.getLogger()
        self._on_level_changed()   # sync handler level with combo
        root.addHandler(self._handler)

    def remove_handler(self):
        """Call on app close to avoid logging to a destroyed widget."""
        logging.getLogger().removeHandler(self._handler)

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_level_changed(self):
        level = self._level_combo.currentData()
        if level is not None:
            self._handler.setLevel(level)

    def _append_record(self, msg: str, levelno: int):
        color = _LEVEL_COLORS.get(levelno, "#cccccc")
        bold = levelno >= logging.ERROR

        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        if bold:
            fmt.setFontWeight(QFont.Weight.Bold)

        cursor = self._view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(msg + "\n", fmt)

        self._line_count = self._view.document().blockCount()
        self._status_label.setText(tr("log.lines_label", count=self._line_count))

        if self._autoscroll_cb.isChecked():
            self._view.setTextCursor(cursor)
            self._view.ensureCursorVisible()

    def _clear(self):
        self._view.clear()
        self._line_count = 0
        self._status_label.setText(tr("log.lines_label", count=0))

    def _export(self):
        # Default to the canonical logs/ directory under user data so manual
        # exports land alongside any auto-written crash dumps. The dialog
        # still lets the user redirect elsewhere; passing a full path as the
        # default ``dir`` argument opens the dialog there instead of in the
        # OS-default / last-used location.
        from src.utils.settings import AppSettings
        default_name = f"smart_citizen_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        default_path = str(AppSettings.get_logs_dir() / default_name)
        path, _ = QFileDialog.getSaveFileName(
            self, tr("log.export_title"), default_path,
            "Log files (*.log);;Text files (*.txt);;All files (*)"
        )
        if not path:
            return
        try:
            Path(path).write_text(self._view.toPlainText(), encoding="utf-8")
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, tr("log.export_failed_title"), str(e))
