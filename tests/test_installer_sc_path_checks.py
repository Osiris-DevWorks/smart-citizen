"""installer.iss path checks behind the Star Citizen directory pre-fill (#422).

``IsValidSCPath`` used to read the last path component with
``ExtractFileName(RemoveBackslash(Path) + '\\')``, which is always ``''``, so
its "path is itself a channel folder" branch could never match and every
saved ``...\\LIVE`` path was rejected as stale (dead since #119 added the
check). The fix reads the component without the trailing backslash, requires
a channel folder to exist (so a path left behind by a moved install falls
through to auto-detect), and splits out ``IsValidSCRoot`` for the
``sc_install_root`` value, which gets ``LIVE`` appended and so must never be
a channel path itself (``...\\LIVE\\LIVE``).

The behaviour test cuts both functions verbatim out of installer.iss,
compiles them into a throwaway setup with Inno Setup's ISCC, runs it silently
against a temp folder tree and reads its verdicts back. It is skipped where
Inno Setup is not installed (CI's pytest step runs before any Inno install),
so the text check is the part that guards CI.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

# The app's channel list, so a channel added there but not to the installer's
# checks fails here.
from src.utils.install_scanner import SC_CHANNELS as CHANNELS

INSTALLER = Path(__file__).resolve().parent.parent / "installer.iss"


def _iscc():
    candidates = [
        shutil.which("ISCC"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"),
    ]
    return next((c for c in candidates if c and os.path.isfile(c)), None)


def _installer_source():
    return INSTALLER.read_text(encoding="utf-8-sig")


def _pascal_function(source, name):
    """Return ``function <name>(...)`` through its closing ``end;``."""
    match = re.search(rf"^function {name}\(.*?^end;$", source, re.S | re.M)
    assert match, f"function {name} not found in installer.iss"
    return match.group(0)


def test_install_root_check_is_root_only():
    """sc_install_root gets LIVE appended, so only a real root may pass."""
    line = next(
        (
            line
            for line in _installer_source().splitlines()
            if "'sc_install_root', SCRoot)" in line
        ),
        None,
    )
    assert line, "sc_install_root read not found in installer.iss"
    assert "IsValidSCRoot(SCRoot)" in line
    assert "IsValidSCPath" not in line


def _cases(t):
    """(path, IsValidSCPath, IsValidSCRoot) against the tree _make_tree builds."""
    sc = f"{t}\\StarCitizen"
    gone = f"{t}\\Gone\\StarCitizen"
    return [
        (sc, True, True),
        (sc + "\\", True, True),
        *[(f"{sc}\\{channel}", True, False) for channel in CHANNELS],
        (sc + "\\LIVE\\", True, False),
        (sc + "\\live", True, False),
        (sc.replace("\\", "/") + "/LIVE", True, False),
        *[(f"{t}\\Only{channel}\\StarCitizen", True, True) for channel in CHANNELS],
        (f"{t}\\SmartCitizen 1.4.1", False, False),
        (f"{t}\\LIVE-backup", False, False),
        (sc + "\\LIVE\\data", False, False),
        (gone + "\\LIVE", False, False),
        (gone + "\\PTU\\", False, False),
        (f"{t}\\OnlyPTU\\StarCitizen\\LIVE", False, False),
    ]


def _make_tree(t):
    for channel in CHANNELS:
        (t / "StarCitizen" / channel).mkdir(parents=True)
        (t / f"Only{channel}" / "StarCitizen" / channel).mkdir(parents=True)
    (t / "SmartCitizen 1.4.1" / "bin").mkdir(parents=True)
    (t / "LIVE-backup" / "data").mkdir(parents=True)


def _pascal_string(value):
    return "'" + value.replace("'", "''") + "'"


@pytest.mark.skipif(_iscc() is None, reason="Inno Setup (ISCC.exe) not installed")
def test_path_checks_in_compiled_installer_code(tmp_path):
    tree = tmp_path / "tree"
    out = tmp_path / "out"
    _make_tree(tree)
    cases = _cases(tree)
    source = _installer_source()

    checks = "\n".join(
        f"  Lines[{i}] := B(IsValidSCPath({_pascal_string(p)})) + "
        f"B(IsValidSCRoot({_pascal_string(p)}));"
        for i, (p, _, _) in enumerate(cases)
    )
    script = f"""[Setup]
AppName=SC path check probe
AppVersion=1.0
CreateAppDir=no
Uninstallable=no
PrivilegesRequired=lowest
OutputDir={out}
OutputBaseFilename=probe

[Code]
{_pascal_function(source, "IsValidSCRoot")}

{_pascal_function(source, "IsValidSCPath")}

function B(const V: Boolean): String;
begin
  if V then Result := '1' else Result := '0';
end;

function InitializeSetup(): Boolean;
var
  Lines: TArrayOfString;
begin
  SetArrayLength(Lines, {len(cases)});
{checks}
  SaveStringsToFile({_pascal_string(str(out / "result.txt"))}, Lines, False);
  Result := False;
end;
"""
    probe = tmp_path / "probe.iss"
    probe.write_text(script, encoding="utf-8-sig")
    compiled = subprocess.run(
        [_iscc(), "/Q", str(probe)], capture_output=True, text=True, timeout=120
    )
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    # InitializeSetup returns False, so the setup exits without installing.
    try:
        subprocess.run(
            [str(out / "probe.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES"], timeout=120
        )
    except OSError as exc:
        # ERROR_SYSTEM_INTEGRITY_POLICY_VIOLATION: an Application Control
        # policy (e.g. a sandboxed shell) refused to run the unsigned probe.
        if getattr(exc, "winerror", None) == 4551:
            pytest.skip(f"probe setup blocked by Application Control: {exc}")
        raise

    verdicts = (out / "result.txt").read_text().split()
    assert len(verdicts) == len(cases)
    wrong = [
        f"{p}: IsValidSCPath={got[0]} IsValidSCRoot={got[1]}, "
        f"expected {int(want_path)}{int(want_root)}"
        for (p, want_path, want_root), got in zip(cases, verdicts)
        if got != f"{int(want_path)}{int(want_root)}"
    ]
    assert not wrong, "\n".join(wrong)
