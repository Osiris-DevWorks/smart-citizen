"""LanguageSourceDialog (Map Language File) — the #409 follow-up fixes:

- Saving a local path that resolves to the apply target for that language is
  refused with a warning instead of silently saved (double-stacking guard).
- Saving a change to the *currently selected* language's own override emits
  language_source_changed so MainWindow can repoint immediately, instead of
  waiting for the next language switch.

Drives the real QDialog headlessly (QT_QPA_PLATFORM=offscreen), same pattern
as test_mission_titles_page_dirty_signal.py — no pytest-qt.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QObject, pyqtSignal  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDialog  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from src.gui.config_tab import LanguageSourceDialog  # noqa: E402
from src.utils.json_settings import JsonSettings  # noqa: E402
from src.utils.settings import AppSettings  # noqa: E402

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Hermetic settings backend + a fake SC channel install dir."""
    saved = AppSettings._backend
    AppSettings._backend = JsonSettings(tmp_path / "config.json")
    channel_root = tmp_path / "LIVE"
    monkeypatch.setattr(AppSettings, "get_channel_install_path", staticmethod(lambda: str(channel_root)))
    monkeypatch.setattr(AppSettings, "get_selected_language", staticmethod(lambda: "korean"))
    yield channel_root
    AppSettings._backend = saved


def _korean_apply_target(channel_root: Path) -> Path:
    return channel_root / "data" / "Localization" / "korean_(south_korea)" / "global.ini"


class TestOverwriteGuard:
    def test_mapping_the_apply_target_is_refused(self, qapp, env):
        target = _korean_apply_target(env)
        dialog = LanguageSourceDialog()
        dialog._inputs["korean"].setText(str(target))

        with patch("src.gui.config_tab.QMessageBox.warning") as warn:
            dialog._save()

        warn.assert_called_once()
        assert dialog.result() != QDialog.DialogCode.Accepted
        assert AppSettings.get_language_source_override("korean") == ""

    def test_case_insensitive_match_is_also_refused(self, qapp, env):
        target = _korean_apply_target(env)
        dialog = LanguageSourceDialog()
        dialog._inputs["korean"].setText(str(target).upper())

        with patch("src.gui.config_tab.QMessageBox.warning") as warn:
            dialog._save()

        warn.assert_called_once()

    def test_a_different_languages_apply_target_does_not_block_korean(self, qapp, env):
        # French's own apply path must not false-match Korean's row.
        french_target = env / "data" / "Localization" / "french_(france)" / "global.ini"
        dialog = LanguageSourceDialog()
        dialog._inputs["korean"].setText(str(french_target))

        with patch("src.gui.config_tab.QMessageBox.warning") as warn:
            dialog._save()

        warn.assert_not_called()
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert AppSettings.get_language_source_override("korean") == str(french_target)

    def test_unrelated_local_path_saves_normally(self, qapp, env):
        other = env / "Downloads" / "global.ini"
        dialog = LanguageSourceDialog()
        dialog._inputs["korean"].setText(str(other))

        with patch("src.gui.config_tab.QMessageBox.warning") as warn:
            dialog._save()

        warn.assert_not_called()
        assert AppSettings.get_language_source_override("korean") == str(other)

    def test_url_is_never_checked_against_apply_target(self, qapp, env):
        # A URL can never equal a local apply-target path; must not be blocked.
        dialog = LanguageSourceDialog()
        dialog._inputs["korean"].setText("https://example.test/global.ini")

        with patch("src.gui.config_tab.QMessageBox.warning") as warn:
            dialog._save()

        warn.assert_not_called()


class TestLanguageSourceChangedSignal:
    def test_changing_current_languages_source_emits_signal(self, qapp, env):
        dialog = LanguageSourceDialog()
        received = []
        dialog.language_source_changed.connect(received.append)

        dialog._inputs["korean"].setText(str(env / "my_patch" / "global.ini"))
        dialog._save()

        assert received == ["korean"]

    def test_changing_a_non_current_languages_source_does_not_emit(self, qapp, env):
        # Selected language is korean; editing french's row must not fire it.
        dialog = LanguageSourceDialog()
        received = []
        dialog.language_source_changed.connect(received.append)

        dialog._inputs["french"].setText(str(env / "fr_patch" / "global.ini"))
        dialog._save()

        assert received == []

    def test_resaving_unchanged_value_does_not_emit(self, qapp, env):
        AppSettings.set_language_source_override("korean", "https://example.test/a.ini")
        dialog = LanguageSourceDialog()
        received = []
        dialog.language_source_changed.connect(received.append)

        # No edit — Save with the field exactly as loaded.
        dialog._save()

        assert received == []

    def test_dialog_closes_normally_when_nothing_is_blocked(self, qapp, env):
        dialog = LanguageSourceDialog()
        dialog._save()
        assert dialog.result() == QDialog.DialogCode.Accepted


class TestSignalForwarding:
    """ConfigTab._open_language_source_dialog relays the dialog's signal to
    its own language_source_changed via a direct signal-to-signal connect.
    Confirms that idiom actually forwards in this PyQt6 version, since it's
    the one piece here that can't be read straight off the source."""

    def test_signal_to_signal_connect_forwards_the_argument(self, qapp):
        class Inner(QObject):
            fired = pyqtSignal(str)

        class Outer(QObject):
            fired = pyqtSignal(str)

        inner, outer = Inner(), Outer()
        inner.fired.connect(outer.fired)
        received = []
        outer.fired.connect(received.append)

        inner.fired.emit("korean")

        assert received == ["korean"]
