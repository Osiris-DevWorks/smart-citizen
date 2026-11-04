"""Folders Windows refuses or cannot reach, for the tests that need one.

A DataForge cache folder can be unusable in two ways a test can set up for
real: its permissions deny new subfolders (what Controlled folder access or a
locked-down folder does to Smart Citizen), or it is on a drive that is not
there (an external drive unplugged before the app starts). The extraction
tests (``test_extraction_working_folder``) and the #494 cache folder tests
(``test_cache_dir``, ``test_cache_folder_strings``,
``test_config_tab_cache_folder``, ``test_enhancements_tab_refused_cache``,
``test_extraction_stop``, ``test_generator_refused_cache``,
``test_refused_cache_window_paths`` and ``test_startup_refused_cache``) make
theirs here. The deny used to live in
``test_extraction_working_folder`` alone.

``new_folders_denied`` denies Everyone the right to add a subfolder (``AD``)
with Windows' own icacls and removes the deny in a ``finally``. It skips the
test only when icacls cannot set the deny, so it runs under CI too (GitHub's
Windows runner can set it). ``missing_drive_folder`` names a folder on a
drive letter nothing is assigned to, picked when the test runs.
"""

import contextlib
import os
import string
import subprocess
from pathlib import Path

import pytest

# The well-known SID of Everyone. The account name is translated on
# non-English Windows, the SID never is.
EVERYONE_SID = "*S-1-1-0"


def icacls(*args: str) -> subprocess.CompletedProcess:
    """Run Windows' own icacls (from System32, never from PATH). It writes to
    a pipe in the OEM code page, not the ANSI one ``text=True`` would read,
    so a folder name or a translated message with a letter only the OEM page
    has would fail to decode."""
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    exe = Path(system_root) / "System32" / "icacls.exe"
    return subprocess.run([str(exe), *args], capture_output=True, encoding="oem",
                          errors="replace", timeout=30)


@contextlib.contextmanager
def new_folders_denied(*folders: Path):
    """Deny Everyone the right to add a subfolder (AD) in each of *folders*
    for the block: what Windows answers when a folder's permissions refuse
    Smart Citizen. Files can still be written there, and folders already
    there still open. Each folder must exist (a missing one is a mistake in
    the test, not a reason to skip). The deny is removed in a finally, so
    pytest can clean up, and the test is skipped when icacls cannot set it."""
    for folder in folders:
        assert Path(folder).is_dir(), f"no folder to deny new folders in: {folder}"
    denied = []
    try:
        for folder in folders:
            result = icacls(str(folder), "/deny", f"{EVERYONE_SID}:(AD)")
            if result.returncode != 0:
                pytest.skip(f"icacls could not deny new folders here: "
                            f"{result.stdout}{result.stderr}")
            denied.append(folder)
        yield
    finally:
        failed = [(folder, result.stdout + result.stderr) for folder, result in
                  ((folder, icacls(str(folder), "/remove:d", EVERYONE_SID)) for folder in denied)
                  if result.returncode != 0]
    assert failed == [], failed


def missing_drive_folder(name: str = "Smart Citizen Cache") -> Path:
    """A folder called *name* at the top of a drive letter nothing is
    assigned to, picked from Z: down when the test runs, so it is a drive
    that is not there on this machine. Skips the test when every letter is
    taken."""
    import ctypes  # Windows only, like every test that calls this

    in_use = ctypes.windll.kernel32.GetLogicalDrives()
    for index in reversed(range(len(string.ascii_uppercase))):
        letter = string.ascii_uppercase[index]
        if in_use & (1 << index) or os.path.exists(f"{letter}:\\"):
            continue
        return Path(f"{letter}:\\") / name
    pytest.skip("every drive letter is in use, so none can stand for a missing drive")
