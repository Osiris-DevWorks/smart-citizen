"""Restore-backup regression (#185).

The More-menu "Restore backup" action copies a saved game ``global.ini`` back
into place and refreshes the table. A source-loading refactor changed
``load_source_files`` to take ``(sources_dict, hierarchy, ...)``, but
``MainWindow.restore_backup`` kept calling it with the old
``(path, overrides)`` signature. The string path then hit
``sources_dict.values()`` and every restore died with
``'str' object has no attribute 'values'``.

The fix routes the post-restore refresh through ``perform_merge_and_reload``
(the canonical source-backed reload used everywhere else) and never calls
``load_source_files`` from this slot. These tests drive the unbound slot on a
lightweight stub ``self`` (no full window — no pytest-qt; see tests/CLAUDE.md).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _Stub:
    """Carries only what restore_backup touches on ``self``."""

    def __init__(self):
        self.reloaded = False
        self.marked_changed = False
        self.rechecked = False
        self._session_has_unapplied_edit = False

    def _mark_game_file_changed(self):
        self.marked_changed = True

    def _refresh_apply_dirty_after_reload(self):
        self.rechecked = True

    def perform_merge_and_reload(self):
        self.reloaded = True


def _wire(monkeypatch, tmp_path, *, backup_text="key=restored\n"):
    """Stub the module-level Qt dialogs and AppSettings restore_backup reads,
    returning (stub, backup_path, target_path, dialogs) where dialogs records
    which QMessageBox calls fired."""
    import src.gui.main_window as mw

    backup = tmp_path / "global.ini.bak_20260101_000000"
    backup.write_text(backup_text, encoding="utf-8")
    target = tmp_path / "game" / "global.ini"
    target.parent.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(mw.AppSettings, "get_game_install_path",
                        staticmethod(lambda: str(tmp_path)))
    monkeypatch.setattr(mw.AppSettings, "get_backups_dir",
                        staticmethod(lambda: tmp_path))
    monkeypatch.setattr(mw.AppSettings, "get_global_ini_path",
                        staticmethod(lambda: target))
    monkeypatch.setattr(mw.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(backup), "")))

    dialogs = {"info": [], "critical": [], "warning": []}
    monkeypatch.setattr(mw.QMessageBox, "information",
                        staticmethod(lambda *a, **k: dialogs["info"].append(a)))
    monkeypatch.setattr(mw.QMessageBox, "critical",
                        staticmethod(lambda *a, **k: dialogs["critical"].append(a)))
    monkeypatch.setattr(mw.QMessageBox, "warning",
                        staticmethod(lambda *a, **k: dialogs["warning"].append(a)))

    return _Stub(), backup, target, dialogs


def test_restore_copies_backup_and_refreshes(qapp, monkeypatch, tmp_path):
    from src.gui.main_window import MainWindow

    stub, backup, target, dialogs = _wire(monkeypatch, tmp_path)
    MainWindow.restore_backup(stub)

    # Backup landed on the game's global.ini, table refreshed, success shown.
    assert target.read_text(encoding="utf-8") == "key=restored\n"
    assert stub.reloaded is True
    assert stub.marked_changed is True  # the game file changed under the Apply check
    assert dialogs["info"] and not dialogs["critical"]


def test_restore_does_not_call_load_source_files(qapp, monkeypatch, tmp_path):
    # The #185 bug was a stale direct call into load_source_files. Lock it out:
    # the refresh must go through perform_merge_and_reload, never this slot.
    import src.gui.main_window as mw
    from src.gui.main_window import MainWindow

    stub, *_ = _wire(monkeypatch, tmp_path)
    monkeypatch.setattr(
        mw, "load_source_files",
        lambda *a, **k: pytest.fail(
            "restore_backup must refresh via perform_merge_and_reload, "
            "not call load_source_files directly (#185)"
        ),
    )

    MainWindow.restore_backup(stub)
    assert stub.reloaded is True


def test_restore_no_game_path_warns_and_skips(qapp, monkeypatch, tmp_path):
    import src.gui.main_window as mw
    from src.gui.main_window import MainWindow

    stub, _backup, target, dialogs = _wire(monkeypatch, tmp_path)
    monkeypatch.setattr(mw.AppSettings, "get_game_install_path",
                        staticmethod(lambda: ""))

    MainWindow.restore_backup(stub)

    assert dialogs["warning"]            # guarded with a warning
    assert stub.reloaded is False        # nothing restored
    assert stub.marked_changed is False
    assert not target.exists()
