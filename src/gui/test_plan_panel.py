"""The side-docked Test Plan panel for testers (#144).

An interactive checklist of what changed in the release. Testers check items
off as they verify them and can write a short note under each one; progress
and notes persist across launches, and the run can be
copied to the clipboard or posted to a Discord webhook. Modelled on the Help
dock (right-side `QDockWidget`); the plan content and report formatting live in
the Qt-free `src/utils/test_plan.py`.
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.utils import test_plan
from src.utils.i18n import tr
from src.utils.settings import AppSettings
from src.utils.version import get_version

logger = logging.getLogger(__name__)

# A note is a short line, not a bug report: long feedback goes in the
# free-text box at the bottom. Keeps a report's per-item line readable and
# well inside one Discord message.
NOTE_MAX_LENGTH = 200


class _ClickableLabel(QLabel):
    """A word-wrapping label that emits ``clicked`` when pressed.

    Paired with a text-less QCheckBox so a long checklist item wraps to the
    panel width (QCheckBox can't wrap its own label) while clicking the text
    still toggles the box.
    """

    clicked = pyqtSignal()

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)


class TestPlanPanel(QWidget):
    """Checklist widget shown inside the Test Plan dock."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._checked = AppSettings.get_test_plan_checks()
        self._item_notes = AppSettings.get_test_plan_item_notes()
        self._checkboxes: dict[str, QCheckBox] = {}
        self._note_edits: dict[str, QLineEdit] = {}
        self._submit_worker = None
        self._build_ui()
        self._refresh_progress()

    # ── construction ─────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self._intro_label = QLabel(tr("test_plan.intro"))
        self._intro_label.setWordWrap(True)
        layout.addWidget(self._intro_label)

        # Tester name (persisted; used to label the submitted report).
        name_row = QHBoxLayout()
        self._tester_label = QLabel(tr("test_plan.tester_label"))
        name_row.addWidget(self._tester_label)
        self.tester_edit = QLineEdit(AppSettings.get_tester_name())
        self.tester_edit.setPlaceholderText(tr("test_plan.tester_placeholder"))
        self.tester_edit.editingFinished.connect(
            lambda: AppSettings.set_tester_name(self.tester_edit.text())
        )
        name_row.addWidget(self.tester_edit, stretch=1)
        layout.addLayout(name_row)

        # Progress.
        prog_row = QHBoxLayout()
        self.progress_label = QLabel()
        prog_row.addWidget(self.progress_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, max(1, test_plan.total_items()))
        prog_row.addWidget(self.progress_bar, stretch=1)
        layout.addLayout(prog_row)

        # Checklist, in a scroll area so a long plan never squishes the buttons.
        # Items word-wrap to the panel width; the horizontal scrollbar is off so
        # long text never forces sideways scrolling.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        container = QWidget()
        clist = QVBoxLayout(container)
        for s, section in enumerate(test_plan.TEST_SECTIONS):
            group = QGroupBox(section["title"])
            gbox = QVBoxLayout(group)
            for i, text in enumerate(section["items"]):
                key = test_plan.item_key(s, i)
                gbox.addWidget(self._make_check_row(key, text))
            clist.addWidget(group)
        clist.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll, stretch=1)

        # Actions.
        btn_row = QHBoxLayout()
        self.submit_btn = QPushButton(tr("test_plan.submit_btn"))
        self.submit_btn.clicked.connect(self._submit)
        webhook = AppSettings.get_test_webhook_url()
        if not webhook:
            self.submit_btn.setEnabled(False)
            self.submit_btn.setToolTip(
                tr("test_plan.no_webhook_tooltip", env_var=AppSettings.TEST_WEBHOOK_ENV)
            )
        btn_row.addWidget(self.submit_btn)

        self.copy_btn = QPushButton(tr("test_plan.copy_report_btn"))
        self.copy_btn.clicked.connect(self._copy_report)
        btn_row.addWidget(self.copy_btn)

        self.reset_btn = QPushButton(tr("test_plan.reset_btn"))
        self.reset_btn.clicked.connect(self._reset)
        btn_row.addWidget(self.reset_btn)

        # Free-text feedback, included in the report (clipboard and Discord).
        self._notes_label = QLabel(tr("test_plan.notes_label"))
        layout.addWidget(self._notes_label)
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setPlaceholderText(tr("test_plan.notes_placeholder"))
        self.notes_edit.setMaximumHeight(110)
        layout.addWidget(self.notes_edit)

        layout.addLayout(btn_row)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

    def retranslate_ui(self) -> None:
        """Re-apply tr() to every static widget after a language switch.

        Checklist item text and section titles come from src.utils.test_plan's
        TEST_SECTIONS table, a separate data layer that doesn't route through
        tr() (out of scope here — a bigger, distinct conversion)."""
        self._intro_label.setText(tr("test_plan.intro"))
        self._tester_label.setText(tr("test_plan.tester_label"))
        self.tester_edit.setPlaceholderText(tr("test_plan.tester_placeholder"))
        self.submit_btn.setText(tr("test_plan.submit_btn"))
        if not AppSettings.get_test_webhook_url():
            self.submit_btn.setToolTip(
                tr("test_plan.no_webhook_tooltip", env_var=AppSettings.TEST_WEBHOOK_ENV)
            )
        self.copy_btn.setText(tr("test_plan.copy_report_btn"))
        self.reset_btn.setText(tr("test_plan.reset_btn"))
        self._notes_label.setText(tr("test_plan.notes_label"))
        self.notes_edit.setPlaceholderText(tr("test_plan.notes_placeholder"))
        for edit in self._note_edits.values():
            edit.setPlaceholderText(tr("test_plan.item_notes_placeholder"))

    def _make_check_row(self, key: str, text: str) -> QWidget:
        """A checklist row: a text-less checkbox, a word-wrapping label and,
        under the label, a one-line notes box for that item.

        QCheckBox can't wrap its own label, so the wrapping text lives in a
        sibling label; clicking either the box or the text toggles the item.
        The note is saved when the box loses focus and goes into the report
        under the item's line.
        """
        row = QWidget()
        hb = QHBoxLayout(row)
        hb.setContentsMargins(0, 0, 0, 0)
        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        cb = QCheckBox()
        cb.setChecked(key in self._checked)
        cb.toggled.connect(lambda checked, k=key: self._on_toggle(k, checked))
        label = _ClickableLabel(text)
        label.clicked.connect(cb.toggle)
        note = QLineEdit(self._item_notes.get(key, ""))
        note.setPlaceholderText(tr("test_plan.item_notes_placeholder"))
        note.setMaxLength(NOTE_MAX_LENGTH)
        note.setClearButtonEnabled(True)
        note.editingFinished.connect(self._save_item_notes)
        text_col.addWidget(label)
        text_col.addWidget(note)
        hb.addWidget(cb, 0, Qt.AlignmentFlag.AlignTop)
        hb.addLayout(text_col, 1)
        self._checkboxes[key] = cb
        self._note_edits[key] = note
        return row

    # ── state ─────────────────────────────────────────────────────────────────
    def _on_toggle(self, key: str, checked: bool) -> None:
        if checked:
            self._checked.add(key)
        else:
            self._checked.discard(key)
        AppSettings.set_test_plan_checks(self._checked)
        self._refresh_progress()

    def _current_item_notes(self) -> dict[str, str]:
        """Each item's note as typed now, blank ones left out."""
        return {
            key: edit.text().strip()
            for key, edit in self._note_edits.items()
            if edit.text().strip()
        }

    def _save_item_notes(self) -> None:
        notes = self._current_item_notes()
        if notes != self._item_notes:
            self._item_notes = notes
            AppSettings.set_test_plan_item_notes(notes)

    def _refresh_progress(self) -> None:
        done, total, pct = test_plan.progress(self._checked)
        self.progress_label.setText(f"{done}/{total} ({pct}%)")
        self.progress_bar.setMaximum(max(1, total))
        self.progress_bar.setValue(done)

    def _build_report(self) -> str:
        return test_plan.build_report(
            self._checked,
            self.tester_edit.text(),
            get_version(),
            notes=self.notes_edit.toPlainText(),
            item_notes=self._current_item_notes(),
        )

    # ── actions ─────────────────────────────────────────────────────────────
    def _copy_report(self) -> None:
        self._save_item_notes()
        report = self._build_report()
        try:
            import pyperclip

            pyperclip.copy(report)
            self.status_label.setText(tr("test_plan.copied_status"))
        except Exception as e:
            logger.error("Could not copy test-plan report: %s", e)
            self.status_label.setText(tr("test_plan.copy_failed_status"))

    def _reset(self) -> None:
        self._checked = set()
        AppSettings.set_test_plan_checks(self._checked)
        for cb in self._checkboxes.values():
            cb.blockSignals(True)
            cb.setChecked(False)
            cb.blockSignals(False)
        for edit in self._note_edits.values():
            edit.blockSignals(True)
            edit.clear()
            edit.blockSignals(False)
        self._item_notes = {}
        AppSettings.set_test_plan_item_notes({})
        self._refresh_progress()
        self.status_label.setText(tr("test_plan.reset_status"))

    def _submit(self) -> None:
        self._save_item_notes()
        webhook = AppSettings.get_test_webhook_url()
        if not webhook:
            self.status_label.setText(tr("test_plan.no_webhook_status"))
            return
        from src.gui.workers import TestPlanSubmitWorker

        chunks = test_plan.discord_chunks(self._build_report())
        self.submit_btn.setEnabled(False)
        self.status_label.setText(tr("test_plan.sending_status"))
        self._submit_worker = TestPlanSubmitWorker(webhook, chunks, self)
        self._submit_worker.finished.connect(self._on_submit_finished)
        self._submit_worker.start()

    def _on_submit_finished(self, ok: bool, message: str) -> None:
        self.status_label.setText(message)
        self.submit_btn.setEnabled(bool(AppSettings.get_test_webhook_url()))
        if self._submit_worker is not None:
            self._submit_worker.quit()
            self._submit_worker.wait()
            self._submit_worker = None
