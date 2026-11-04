"""Tests for :func:`src.utils.user_ini_manager.reset_user_ini`.

Locks the contract used by the Config tab's "Reset user.ini" button:
  * Returns the backup path on success and leaves the original gone.
  * Returns ``None`` when the source file doesn't exist (caller treats
    that as a no-op).
  * ``backup=False`` deletes outright and still returns ``None``.
  * ``backup=True`` also saves a rotating snapshot, which Restore user.ini
    lists, so a reset can be undone there (#531).
  * Backup naming guards against same-second double invocations — the
    second call must NOT silently overwrite the first backup, even if
    both calls land inside the same wall-clock second (which produces
    the same ``YYYYMMDD-HHMMSS`` stamp).
"""
from __future__ import annotations

from pathlib import Path

from src.utils.user_ini_manager import list_user_ini_backups, reset_user_ini


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestResetUserIni:
    def test_returns_none_when_source_absent(self, tmp_path: Path):
        missing = tmp_path / "user.ini"
        assert reset_user_ini(missing, backup=True) is None
        assert not missing.exists()

    def test_backup_true_renames_to_timestamped_sibling(self, tmp_path: Path):
        src = tmp_path / "user.ini"
        _write(src, "some_key=Custom Value\nother_key=Another\n")

        backup = reset_user_ini(src, backup=True)

        assert backup is not None
        assert backup.exists()
        assert backup.parent == src.parent
        assert backup.name.startswith("user.ini.bak-")
        # Backup must preserve content byte-for-byte.
        assert backup.read_text(encoding="utf-8") == \
            "some_key=Custom Value\nother_key=Another\n"
        # Original must be gone.
        assert not src.exists()

    def test_backup_false_deletes_outright(self, tmp_path: Path):
        src = tmp_path / "user.ini"
        _write(src, "key=value\n")

        result = reset_user_ini(src, backup=False)

        assert result is None
        assert not src.exists()
        # No sibling backup file was created, and no snapshot either.
        assert list(tmp_path.iterdir()) == []

    def test_backup_true_also_saves_a_snapshot_restore_lists(self, tmp_path: Path):
        """Restore user.ini lists only the rotating snapshots, and it had
        none to offer straight after a reset (found in testing, #531)."""
        src = tmp_path / "LIVE" / "user.ini"
        _write(src, "some_key=Custom Value\n")

        reset_user_ini(src, backup=True)

        [snapshot] = list_user_ini_backups(src)
        assert snapshot.read_text(encoding="utf-8") == "some_key=Custom Value\n"

    def test_double_call_same_second_does_not_clobber_first_backup(
        self, tmp_path: Path, monkeypatch
    ):
        """Two resets producing the same YYYYMMDD-HHMMSS stamp must coexist.

        Real-world trigger: user double-clicks the button, restores from
        backup, hits reset again — and a fast machine can land both
        invocations inside one wall-clock second. The function must add
        a numeric suffix instead of overwriting the first backup.

        We monkey-patch :func:`datetime.now` inside the module so both
        calls observe the same timestamp deterministically (the real
        clock would race the test).
        """
        from datetime import datetime
        import src.utils.user_ini_manager as mod

        class _FrozenClock:
            @classmethod
            def now(cls):
                return datetime(2026, 5, 17, 12, 34, 56)

        monkeypatch.setattr(mod, "datetime", _FrozenClock)

        first_src = tmp_path / "user.ini"
        _write(first_src, "first=alpha\n")
        first_backup = reset_user_ini(first_src, backup=True)

        # Recreate user.ini for the second invocation (simulates the user
        # re-introducing overrides between the two resets).
        _write(first_src, "second=beta\n")
        second_backup = reset_user_ini(first_src, backup=True)

        assert first_backup is not None and second_backup is not None
        assert first_backup != second_backup
        assert first_backup.exists() and second_backup.exists()
        # Distinct contents — second call did not overwrite the first.
        assert first_backup.read_text(encoding="utf-8") == "first=alpha\n"
        assert second_backup.read_text(encoding="utf-8") == "second=beta\n"
        # Naming: first is the bare timestamp, second carries a suffix.
        assert first_backup.name == "user.ini.bak-20260517-123456"
        assert second_backup.name == "user.ini.bak-20260517-123456-2"
