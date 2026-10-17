"""Tests for migrate_user_data_dir (issue #103).

When the user moves the Smart Citizen data folder, their existing overrides /
backups / cached strings should follow the move instead of being left behind.
The helper copies (merge, never overwrite) so data already in the new location
wins and the originals survive as a safety net.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from src.utils.user_ini_manager import migrate_user_data_dir  # noqa: E402

pytestmark = pytest.mark.unit


def _seed(root: Path) -> None:
    (root / "LIVE").mkdir(parents=True)
    (root / "LIVE" / "user.ini").write_text("vehicle_NameX= My Ship\n", encoding="utf-8")
    (root / "LIVE" / "backups").mkdir()
    (root / "LIVE" / "backups" / "global.ini.bak").write_text("backup", encoding="utf-8")


def test_copies_all_files_to_new_location(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    _seed(old)

    copied = migrate_user_data_dir(old, new)

    assert copied == 2
    assert (new / "LIVE" / "user.ini").read_text(encoding="utf-8") == "vehicle_NameX= My Ship\n"
    assert (new / "LIVE" / "backups" / "global.ini.bak").exists()
    # originals are left in place (copy, not move)
    assert (old / "LIVE" / "user.ini").exists()


def test_never_overwrites_existing_destination_files(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    _seed(old)
    # Pre-existing data in the new location must win.
    (new / "LIVE").mkdir(parents=True)
    (new / "LIVE" / "user.ini").write_text("KEEP ME", encoding="utf-8")

    copied = migrate_user_data_dir(old, new)

    assert (new / "LIVE" / "user.ini").read_text(encoding="utf-8") == "KEEP ME"
    assert (new / "LIVE" / "backups" / "global.ini.bak").exists()  # non-conflicting file still copied
    assert copied == 1


def test_noop_when_same_dir(tmp_path):
    old = tmp_path / "d"
    _seed(old)
    assert migrate_user_data_dir(old, old) == 0


def test_noop_when_old_missing(tmp_path):
    assert migrate_user_data_dir(tmp_path / "does_not_exist", tmp_path / "new") == 0


def test_moves_all_files_to_new_location(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    _seed(old)

    moved = migrate_user_data_dir(old, new, move=True)

    assert moved == 2
    assert (new / "LIVE" / "user.ini").read_text(encoding="utf-8") == "vehicle_NameX= My Ship\n"
    assert (new / "LIVE" / "backups" / "global.ini.bak").exists()
    # originals removed after move
    assert not (old / "LIVE" / "user.ini").exists()
    assert not (old / "LIVE" / "backups" / "global.ini.bak").exists()


def test_move_prunes_empty_source_dirs(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    _seed(old)

    migrate_user_data_dir(old, new, move=True)

    # All source files gone → entire old tree should be removed.
    assert not old.exists()


def test_move_leaves_conflicting_files_in_place(tmp_path):
    """A file skipped because the destination already exists must NOT be deleted."""
    old = tmp_path / "old"
    new = tmp_path / "new"
    _seed(old)
    (new / "LIVE").mkdir(parents=True)
    (new / "LIVE" / "user.ini").write_text("KEEP ME", encoding="utf-8")

    moved = migrate_user_data_dir(old, new, move=True)

    assert moved == 1  # only the backup was moved
    # The conflicting source file must survive because we couldn't place it.
    assert (old / "LIVE" / "user.ini").exists()
    # The backup was moved.
    assert not (old / "LIVE" / "backups" / "global.ini.bak").exists()


def test_new_nested_inside_old_terminates_without_recursion(tmp_path):
    """If the new folder is a subdirectory of the old one, the migration must
    copy the old data once and not recursively re-copy into ever-deeper
    nesting (the lazy-walk trap)."""
    old = tmp_path / "old"
    _seed(old)                 # old/LIVE/user.ini + old/LIVE/backups/global.ini.bak
    new = old / "moved"        # new is INSIDE old

    copied = migrate_user_data_dir(old, new)

    # The two seeded files land under new exactly once.
    assert copied == 2
    assert (new / "LIVE" / "user.ini").exists()
    assert (new / "LIVE" / "backups" / "global.ini.bak").exists()
    # No pathological deeper nesting (new/moved/… must not exist).
    assert not (new / "moved").exists()


def test_exclude_leaves_a_file_where_it_is_and_uncounted(tmp_path):
    # #455 leaves the DataForge cache trees behind this way. The predicate is
    # asked with each file's path relative to the old root.
    old = tmp_path / "old"
    new = tmp_path / "new"
    _seed(old)
    seen = []

    def exclude(rel: Path) -> bool:
        seen.append(rel.as_posix())
        return rel.parts[1] == "backups"

    moved = migrate_user_data_dir(old, new, move=True, exclude=exclude)

    assert moved == 1
    assert (new / "LIVE" / "user.ini").exists()
    assert not (new / "LIVE" / "backups").exists()
    assert (old / "LIVE" / "backups" / "global.ini.bak").read_text(encoding="utf-8") == "backup"
    assert sorted(seen) == ["LIVE/backups/global.ini.bak", "LIVE/user.ini"]
