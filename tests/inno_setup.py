"""Inno Setup's compiler, for the tests that compile installer.iss or a probe.

Four test files compile with ISCC.exe (``test_installer_auto_update_relaunch``,
``test_installer_onedrive_check``, ``test_installer_sc_path_checks`` and
``test_installer_wipe_safety``). They used to carry a copy each of a lookup
that only knew ``Inno Setup 6`` folders, so a machine or runner with Inno
Setup 7 skipped them without a word.

``find_iscc`` looks on PATH first, then in every ``Inno Setup *`` folder under
Program Files (x86), Program Files and the per-user ``%LOCALAPPDATA%\\Programs``
(where a per-user install lands), newest version first.

``require_iscc`` is what a test calls before it compiles. It skips the test where
Inno Setup is not installed, as before, except under CI, where it fails: a runner
image that dropped Inno Setup (or moved it) must turn these compile checks red,
not into skips nobody reads. GitHub Actions sets ``CI=true``.

``run_probe`` and ``pascal_string`` are the rest of what the probe tests
share: compiling a throwaway setup, running it silently and reading back the
lines it saved, and quoting a value for the Pascal source they generate.
"""

import glob
import os
import re
import shutil
import subprocess

import pytest


def _install_roots():
    """The folders Inno Setup installs under, in the order a tie is broken."""
    local = os.environ.get("LOCALAPPDATA")
    roots = [
        os.environ.get("ProgramFiles(x86)"),
        os.environ.get("ProgramFiles"),
        os.path.join(local, "Programs") if local else None,
    ]
    return [root for root in roots if root]


def _version(folder):
    """Sort key for an ``Inno Setup 6`` folder name: the numbers in it, so a
    folder for version 10 sorts after one for version 9."""
    return tuple(int(number) for number in re.findall(r"\d+", os.path.basename(folder)))


def find_iscc():
    """The path of ``ISCC.exe``, or ``None``. PATH wins, then the newest
    ``Inno Setup *`` folder (an older one only when the newer has no ISCC)."""
    on_path = shutil.which("ISCC")
    if on_path:
        return on_path
    found = []
    for root in _install_roots():
        for folder in glob.glob(os.path.join(glob.escape(root), "Inno Setup *")):
            iscc = os.path.join(folder, "ISCC.exe")
            if os.path.isfile(iscc):
                found.append((_version(folder), iscc))
    # Stable, so two folders of one version keep the order of _install_roots().
    found.sort(key=lambda item: item[0], reverse=True)
    return found[0][1] if found else None


def require_iscc():
    """The path of ``ISCC.exe``. Without Inno Setup this skips the calling test,
    or fails it when the ``CI`` environment variable is set."""
    iscc = find_iscc()
    if iscc:
        return iscc
    reason = "Inno Setup (ISCC.exe) not installed"
    if os.environ.get("CI"):
        pytest.fail(
            f"{reason}. CI does not skip the installer compile tests: install Inno Setup 6.6.0 "
            "or newer on the runner, or put ISCC.exe on PATH.",
            pytrace=False,
        )
    pytest.skip(reason)


def pascal_string(value):
    """*value* as a Pascal string literal, with every quote doubled."""
    return "'" + value.replace("'", "''") + "'"


def run_probe(script, tmp_path, out):
    """Compile *script* with ISCC, run the resulting setup silently and return
    the lines it saved to ``out / "result.txt"``. Skips the test where Inno
    Setup is not installed (``require_iscc`` fails it under CI instead) or when
    an Application Control policy refuses to run the unsigned probe. The probe's
    InitializeSetup returns False, so it exits without installing anything."""
    iscc = require_iscc()
    probe = tmp_path / "probe.iss"
    probe.write_text(script, encoding="utf-8-sig")
    compiled = subprocess.run([iscc, "/Q", str(probe)], capture_output=True, text=True, timeout=120)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    try:
        subprocess.run([str(out / "probe.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES"], timeout=120)
    except OSError as exc:
        # ERROR_SYSTEM_INTEGRITY_POLICY_VIOLATION: an Application Control
        # policy (e.g. a sandboxed shell) refused to run the unsigned probe.
        if getattr(exc, "winerror", None) == 4551:
            pytest.skip(f"probe setup blocked by Application Control: {exc}")
        raise
    return (out / "result.txt").read_text(encoding="mbcs").splitlines()
