"""tests/unusable_folder.py makes a folder Windows refuses, and names one on a
drive that is not there.

Several test files make a folder refuse new subfolders through
``new_folders_denied`` and name a cache folder on a missing drive through
``missing_drive_folder``. These cover what the two do: a real deny that
refuses a new subfolder while it is held (in a folder named with letters
outside the OEM code page too), lets files and the folders already there
alone, and is gone afterwards, also when the block raises; a deny icacls
cannot set skips the test and leaves nothing denied, a deny that cannot be
removed fails the test, and a folder that is not there is a mistake, not a
skip. The missing drive is one no letter in use has, and none left skips.
"""

import ctypes
import sys

import pytest

import tests.unusable_folder as unusable_folder
from tests.unusable_folder import missing_drive_folder, new_folders_denied

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(sys.platform != "win32", reason="Windows access control lists"),
]

ERROR_ACCESS_DENIED = 5
ERROR_PATH_NOT_FOUND = 3


def _refuses_new_folders(folder) -> bool:
    try:
        (folder / "probe").mkdir()
    except PermissionError as error:
        assert error.winerror == ERROR_ACCESS_DENIED
        return True
    (folder / "probe").rmdir()
    return False


def _skip_reason(block):
    """Runs *block* and returns the skip message, or None when it ran. A skip
    is caught, so a helper that skips where it should not fails the test
    instead of being skipped."""
    try:
        block()
    except pytest.skip.Exception as skipped:
        return skipped.msg
    return None


@pytest.mark.parametrize("name", ["plain", "Ωmega Āpex ü"])
def test_a_deny_refuses_new_folders_only_while_it_is_held(tmp_path, name):
    folder = tmp_path / name
    (folder / "already there").mkdir(parents=True)
    with new_folders_denied(folder):
        assert _refuses_new_folders(folder)
        (folder / "file.txt").write_text("x", encoding="utf-8")
        assert not _refuses_new_folders(folder / "already there")
    assert not _refuses_new_folders(folder)
    assert (folder / "file.txt").read_text(encoding="utf-8") == "x"


def test_several_folders_are_each_denied_and_all_released(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    with new_folders_denied(first, second):
        assert _refuses_new_folders(first) and _refuses_new_folders(second)
    assert not _refuses_new_folders(first) and not _refuses_new_folders(second)


def test_the_deny_is_removed_when_the_block_raises(tmp_path):
    with pytest.raises(RuntimeError, match="inside"):
        with new_folders_denied(tmp_path):
            raise RuntimeError("inside")
    assert not _refuses_new_folders(tmp_path)


def test_a_deny_icacls_cannot_set_skips_and_leaves_nothing_denied(tmp_path, monkeypatch):
    """The first folder is really denied, then icacls fails on the second:
    the test is skipped and the first folder's deny is removed."""
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    real = unusable_folder.icacls

    def icacls(*args):
        if args[0] == str(second) and args[1] == "/deny":
            return real(str(tmp_path / "not there"), *args[1:])   # a real failure
        return real(*args)

    monkeypatch.setattr(unusable_folder, "icacls", icacls)

    def block():
        with new_folders_denied(first, second):
            pytest.fail("the block must not run without every deny in place")

    reason = _skip_reason(block)
    assert reason is not None and reason.startswith("icacls could not deny new folders here: ")
    assert not _refuses_new_folders(first)


def test_a_deny_that_cannot_be_removed_fails_the_test(tmp_path, monkeypatch):
    calls = []

    def icacls(*args):
        calls.append(args[1])
        return unusable_folder.subprocess.CompletedProcess(
            args, 0 if args[1] == "/deny" else 1, "", "cannot remove it")

    monkeypatch.setattr(unusable_folder, "icacls", icacls)
    with pytest.raises(AssertionError, match="cannot remove it"):
        with new_folders_denied(tmp_path):
            pass
    assert calls == ["/deny", "/remove:d"]


def test_a_folder_that_is_not_there_is_a_mistake_not_a_skip(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(unusable_folder, "icacls", lambda *args: calls.append(args))
    with pytest.raises(AssertionError, match="no folder to deny new folders in"):
        with new_folders_denied(tmp_path / "missing"):
            pass
    assert calls == []


def test_the_missing_drive_is_not_there(tmp_path):
    folder = missing_drive_folder()
    assert folder.parent == folder.parent.parent    # the top of its drive
    assert not folder.exists()
    with pytest.raises(FileNotFoundError) as raised:
        folder.mkdir(parents=True)
    assert raised.value.winerror == ERROR_PATH_NOT_FOUND


def test_a_letter_in_use_is_passed_over(monkeypatch):
    """Z: is reported in use as well as this machine's own drives, so the
    folder is on a letter none of them has."""
    real_letters = ctypes.windll.kernel32.GetLogicalDrives()
    monkeypatch.setattr(ctypes.windll.kernel32, "GetLogicalDrives",
                        lambda: real_letters | (1 << 25))
    folder = missing_drive_folder("cache")
    letter = folder.drive[0]
    assert letter != "Z"
    assert not real_letters & (1 << (ord(letter) - ord("A")))
    assert folder == unusable_folder.Path(f"{letter}:\\cache")


def test_no_letter_left_skips(monkeypatch):
    monkeypatch.setattr(ctypes.windll.kernel32, "GetLogicalDrives", lambda: (1 << 26) - 1)
    reason = _skip_reason(missing_drive_folder)
    assert reason == "every drive letter is in use, so none can stand for a missing drive"
