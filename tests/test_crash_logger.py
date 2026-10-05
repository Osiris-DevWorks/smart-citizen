"""crash_logger.show_crash_dialog, the modal "Smart Citizen crashed" dialog.

tests/test_crash_handler.py stubs this function everywhere (the run keeps
one QApplication alive, so the real dialog would block). These tests run
the real one with exec() replaced. They live in their own file so a local
run that deselects test_crash_handler.py still runs them.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.regression]


class TestShowCrashDialog:
    """Its exec() is replaced so nothing blocks: a QApplication exists for the
    whole run (tests/conftest.py), so the real modal dialog would wait for a
    click nobody gives."""

    @staticmethod
    def _recording_dialog(monkeypatch):
        from PyQt6 import QtWidgets

        shown = []

        class _RecordingDialog(QtWidgets.QDialog):
            def exec(self):
                shown.append(self)
                return 0

        monkeypatch.setattr(QtWidgets, "QDialog", _RecordingDialog)
        return shown

    def test_no_qapplication_means_no_dialog(self, monkeypatch):
        """A crash before the GUI exists has no app to show a dialog on."""
        from PyQt6 import QtWidgets
        from src.utils import crash_logger

        class _NoApp:
            @staticmethod
            def instance():
                return None

        shown = self._recording_dialog(monkeypatch)
        monkeypatch.setattr(QtWidgets, "QApplication", _NoApp)

        crash_logger.show_crash_dialog(RuntimeError, RuntimeError("early"), Path("x.log"))

        assert shown == []

    def test_dialog_shows_the_error_and_copies_the_dump_path(self, monkeypatch, tmp_path):
        import pyperclip
        from PyQt6.QtWidgets import QLabel, QPushButton, QTextEdit
        from src.utils import crash_logger

        shown = self._recording_dialog(monkeypatch)
        copied = []
        monkeypatch.setattr(pyperclip, "copy", copied.append)
        dump = tmp_path / "logs" / "crash_20261005_120000.log"

        crash_logger.show_crash_dialog(ValueError, ValueError("boom"), dump)

        assert len(shown) == 1, "the dialog must be shown exactly once"
        dlg = shown[0]
        assert dlg.findChild(QTextEdit).toPlainText() == "ValueError: boom"
        assert any(str(dump) in label.text() for label in dlg.findChildren(QLabel))
        copy_btn = next(b for b in dlg.findChildren(QPushButton) if b.text() == "Copy path")
        copy_btn.click()
        assert copied == [str(dump)]

    def test_missing_dump_path_says_so(self, monkeypatch):
        from PyQt6.QtWidgets import QLabel
        from src.utils import crash_logger

        shown = self._recording_dialog(monkeypatch)

        crash_logger.show_crash_dialog(ValueError, ValueError("boom"), None)

        assert any("(could not write crash log)" in label.text()
                   for label in shown[0].findChildren(QLabel))
