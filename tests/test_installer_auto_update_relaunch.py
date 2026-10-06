"""installer.iss relaunches Smart Citizen after it has written its settings (#434).

The in-app updater (#211) runs the installer with ``/SILENT /AUTOUPDATE=1`` and
expects the app to start again afterwards. That relaunch was a ``[Run]`` entry.
Inno Setup processes ``[Run]`` entries that are not ``postinstall`` right after
the files are installed and BEFORE it signals ``ssPostInstall`` (``TMainForm.
Install`` in Inno's ``Setup.MainForm.pas``: ``PerformInstall``, then
``ProcessRunEntries``, then ``SetStep(ssPostInstall)``). The installer writes
its wizard choices to the registry in ``CurStepChanged(ssPostInstall)``, so the
app started first and the settings landed second.

The relaunch now runs inside that step, with ``ExecAsOriginalUser``, right
after ``WriteInstallerChoicesToRegistry`` and ahead of the missing-uninstaller
check (#420 keeps that box from ever delaying the relaunch).

These checks read installer.iss as text, so they run everywhere. The last one
also compiles the whole script with Inno Setup's ISCC when it is installed
(GitHub's Windows runner image ships Inno Setup 6, so CI runs it), because CI
does not otherwise compile installer.iss and a mistake in a ``[Code]`` call
would only show up when a release is built. It never runs the compiled setup.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.inno_setup import require_iscc  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
INSTALLER = ROOT / "installer.iss"


def _installer_source():
    return INSTALLER.read_text(encoding="utf-8-sig")


def _run_entries(source):
    """``(line, flags)`` for every entry of the ``[Run]`` section."""
    section = re.search(r"^\[Run\]\s*$(.*?)(?=^\[\w+\]\s*$|\Z)", source, re.S | re.M)
    assert section, "[Run] section not found in installer.iss"
    entries = []
    for line in section.group(1).splitlines():
        line = line.strip()
        if line.startswith("Filename:"):
            flags = re.search(r"Flags:\s*([^;]*)", line)
            entries.append((line, set(flags.group(1).split()) if flags else set()))
    return entries


def _post_install_block(source):
    """The ``ssPostInstall`` part of ``CurStepChanged``."""
    step = re.search(r"^procedure CurStepChanged\(.*?^end;$", source, re.S | re.M)
    assert step, "procedure CurStepChanged not found in installer.iss"
    block = step.group(0)
    start = re.search(r"\(CurStep\s*=\s*ssPostInstall\)", block)
    assert start, "no ssPostInstall branch in CurStepChanged"
    begin = start.start()
    return block[begin:]


def test_no_run_entry_starts_the_app_before_ssPostInstall():
    # A [Run] entry without "postinstall" runs before ssPostInstall, ahead of
    # the registry writes. Only the finish-page launch (postinstall) may start
    # the app from this section.
    entries = [
        (line, flags)
        for line, flags in _run_entries(_installer_source())
        if "SmartCitizen.exe" in line
    ]
    assert entries, "the finish-page launch entry is gone from [Run]"
    early = [line for line, flags in entries if "postinstall" not in flags]
    assert not early, "a [Run] entry starts the app before ssPostInstall:\n" + "\n".join(early)


def test_relaunch_follows_the_registry_writes_and_precedes_the_uninstaller_check():
    block = _post_install_block(_installer_source())
    write = re.search(r"^\s*WriteInstallerChoicesToRegistry\(\);", block, re.M)
    relaunch = re.search(r"ExecAsOriginalUser\(", block)
    # #454: the uninstaller Setup really wrote. In a shared install folder another
    # program's unins000 files can stay, and Setup then names ours unins001.
    check = re.search(
        r"UninstallExe := ExpandConstant\('\{uninstallexe\}'\);\s*"
        r"if not FileExists\(UninstallExe\)",
        block,
    )
    assert (
        write and relaunch and check
    ), "the relaunch, the registry writes or the uninstaller check is gone"
    assert not re.search(
        r"\{app\}\\unins\d", block
    ), "the uninstaller check must ask for {uninstallexe}"
    assert write.start() < relaunch.start() < check.start()
    # Only an auto-update relaunches, and it launches the app.
    first, last = relaunch.start(), check.start()
    assert "SmartCitizen.exe" in block[first:last]
    assert "IsAutoUpdate()" in block[write.end() : first]


def test_whole_installer_compiles(tmp_path):
    iscc = require_iscc()
    # The files installer.iss reads at compile time. Add any new one here.
    (tmp_path / "assets").mkdir()
    shutil.copyfile(ROOT / "assets" / "logo.ico", tmp_path / "assets" / "logo.ico")
    shutil.copyfile(ROOT / "VERSION.TXT", tmp_path / "VERSION.TXT")
    shutil.copyfile(INSTALLER, tmp_path / "installer.iss")
    (tmp_path / "dist" / "SmartCitizen").mkdir(parents=True)
    (tmp_path / "dist" / "SmartCitizen" / "stub.txt").write_text("stub", encoding="utf-8")
    out = tmp_path / "out"
    compiled = subprocess.run(
        [iscc, "/Q", f"/O{out}", str(tmp_path / "installer.iss")],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=tmp_path,
    )
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
