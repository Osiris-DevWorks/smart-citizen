"""Rotating user.ini backups + restore (#172).

user.ini holds every hand-entered edit but historically had no backup (only
the applied game global.ini did), so a truncation or a OneDrive sync emptying
the file was unrecoverable. These tests lock the safety net: a content-changing
save snapshots the prior file first, snapshots rotate to keep 5, and a restore
is itself reversible.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.models.string_model import StringEntry  # noqa: E402
from src.utils import user_ini_manager as uim  # noqa: E402

pytestmark = pytest.mark.unit


def _entry(key, original, custom, status="Modified"):
    return StringEntry(
        key=key, source_file="global", category="Ships",
        original_value=original, custom_value=custom, status=status,
    )


def _user_ini(tmp_path: Path) -> Path:
    # Mirror the real layout: {root}/{channel}/user.ini, backups sibling.
    channel = tmp_path / "LIVE"
    channel.mkdir()
    return channel / "user.ini"


# ── backup_user_ini ──────────────────────────────────────────────────────────

class TestBackupUserIni:
    def test_missing_file_returns_none(self, tmp_path):
        assert uim.backup_user_ini(_user_ini(tmp_path)) is None

    def test_empty_file_returns_none(self, tmp_path):
        p = _user_ini(tmp_path)
        p.write_text("", encoding="utf-8")
        assert uim.backup_user_ini(p) is None

    def test_creates_backup_with_matching_content(self, tmp_path):
        p = _user_ini(tmp_path)
        p.write_text("k=*Avenger\n", encoding="utf-8")
        b = uim.backup_user_ini(p)
        assert b is not None and b.exists()
        assert b.parent == p.parent / "backups"
        assert b.name.startswith(uim.USER_INI_BACKUP_PREFIX)
        assert b.read_text(encoding="utf-8") == "k=*Avenger\n"

    def test_rotation_keeps_at_most_five(self, tmp_path):
        p = _user_ini(tmp_path)
        for i in range(8):
            p.write_text(f"k=v{i}\n", encoding="utf-8")
            uim.backup_user_ini(p)
        backups = uim.list_user_ini_backups(p)
        assert len(backups) == uim.MAX_USER_INI_BACKUPS
        # The newest backup holds the most recent content.
        assert backups[0].read_text(encoding="utf-8") == "k=v7\n"

    def test_same_second_collision_gets_suffix(self, tmp_path, monkeypatch):
        # Freeze the timestamp so two backups would target the same name.
        import src.utils.user_ini_manager as m

        class _FixedDT:
            @staticmethod
            def now():
                import datetime as _d
                return _d.datetime(2026, 6, 20, 12, 0, 0)

        monkeypatch.setattr(m, "datetime", _FixedDT)
        p = _user_ini(tmp_path)
        p.write_text("a=1\n", encoding="utf-8")
        b1 = uim.backup_user_ini(p)
        p.write_text("a=2\n", encoding="utf-8")
        b2 = uim.backup_user_ini(p)
        assert b1 != b2 and b1.exists() and b2.exists()


# ── list / restore ───────────────────────────────────────────────────────────

class TestListAndRestore:
    def test_list_newest_first(self, tmp_path):
        p = _user_ini(tmp_path)
        names = []
        for i in range(3):
            p.write_text(f"k=v{i}\n", encoding="utf-8")
            names.append(uim.backup_user_ini(p).name)
        listed = [b.name for b in uim.list_user_ini_backups(p)]
        assert listed == list(reversed(names))

    def test_restore_overwrites_and_snapshots_current(self, tmp_path):
        p = _user_ini(tmp_path)
        p.write_text("original=*Avenger\n", encoding="utf-8")
        snap = uim.backup_user_ini(p)            # snapshot of the good state
        p.write_text("", encoding="utf-8")        # simulate truncation
        uim.restore_user_ini_backup(snap, p)
        assert p.read_text(encoding="utf-8") == "original=*Avenger\n"

    def test_restore_is_reversible(self, tmp_path):
        # Restoring snapshots the pre-restore file first, so it can be undone.
        p = _user_ini(tmp_path)
        p.write_text("good=*Avenger\n", encoding="utf-8")
        snap = uim.backup_user_ini(p)
        p.write_text("bad=*Wrong\n", encoding="utf-8")
        before = len(uim.list_user_ini_backups(p))
        uim.restore_user_ini_backup(snap, p)
        after = uim.list_user_ini_backups(p)
        assert len(after) == before + 1
        assert any(b.read_text(encoding="utf-8") == "bad=*Wrong\n" for b in after)

    def test_restoring_the_oldest_of_a_full_set(self, tmp_path):
        """The pre-restore snapshot rotates out the oldest of a full set,
        which is the one picked here. It was deleted before it was read, so
        the restore failed and the snapshot was gone (#531)."""
        p = _user_ini(tmp_path)
        for i in range(uim.MAX_USER_INI_BACKUPS):
            p.write_text(f"k=v{i}\n", encoding="utf-8")
            uim.backup_user_ini(p)
        p.write_text("k=current\n", encoding="utf-8")
        oldest = uim.list_user_ini_backups(p)[-1]
        assert oldest.read_text(encoding="utf-8") == "k=v0\n"

        uim.restore_user_ini_backup(oldest, p)

        assert p.read_text(encoding="utf-8") == "k=v0\n"
        assert any(b.read_text(encoding="utf-8") == "k=current\n"
                   for b in uim.list_user_ini_backups(p))


# ── integration with save_user_ini ───────────────────────────────────────────

class TestSaveBacksUp:
    def test_no_backup_on_first_save(self, tmp_path):
        p = _user_ini(tmp_path)
        uim.save_user_ini([_entry("k", "Avenger", "*Avenger")], p)
        assert uim.list_user_ini_backups(p) == []  # nothing existed to snapshot

    def test_backup_made_when_content_changes(self, tmp_path):
        p = _user_ini(tmp_path)
        uim.save_user_ini([_entry("k", "Avenger", "*Avenger")], p)
        uim.save_user_ini([_entry("k", "Avenger", "*Avenger Titan")], p)
        backups = uim.list_user_ini_backups(p)
        assert len(backups) == 1
        assert backups[0].read_text(encoding="utf-8") == "k=*Avenger\n"

    def test_no_backup_when_content_unchanged(self, tmp_path):
        p = _user_ini(tmp_path)
        e = [_entry("k", "Avenger", "*Avenger")]
        uim.save_user_ini(e, p)
        uim.save_user_ini(e, p)  # identical write
        assert uim.list_user_ini_backups(p) == []

    def test_truncating_save_snapshots_populated_file(self, tmp_path):
        # The exact disaster: a populated user.ini is overwritten with empty
        # edits. The prior 36-favorite state must be snapshotted first.
        p = _user_ini(tmp_path)
        populated = [_entry(f"k{i}", f"S{i}", f"*S{i}") for i in range(36)]
        uim.save_user_ini(populated, p)
        assert uim.list_user_ini_backups(p) == []  # first save, nothing prior

        # Now an empty save (load mismatch / clear-all) truncates the file...
        uim.save_user_ini([], p)
        assert p.read_text(encoding="utf-8") == ""  # truncated on disk
        backups = uim.list_user_ini_backups(p)
        assert len(backups) == 1
        recovered = backups[0].read_text(encoding="utf-8")
        assert recovered.count("\n") == 36 and "k0=*S0" in recovered
