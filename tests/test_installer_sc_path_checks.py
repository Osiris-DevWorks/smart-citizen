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

The behaviour tests cut those functions, and the InitializeWizard pre-fill
block that uses them, verbatim out of installer.iss, compile them into a
throwaway setup with Inno Setup's ISCC, run it silently against a temp folder
tree and read its verdicts back. They are skipped where Inno Setup is not
installed or an Application Control policy refuses to run the unsigned probe.
GitHub's Windows runner image ships Inno Setup 6, so they run in CI as well as
on a developer machine that has Inno Setup.
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


def _run_probe(script, tmp_path, out):
    """Compile *script* with ISCC, run the resulting setup silently and return
    the lines it saved to ``out / "result.txt"``. Skips the test when an
    Application Control policy refuses to run the unsigned probe."""
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
    return (out / "result.txt").read_text(encoding="mbcs").splitlines()


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
    verdicts = _run_probe(script, tmp_path, out)
    assert len(verdicts) == len(cases)
    wrong = [
        f"{p}: IsValidSCPath={got[0]} IsValidSCRoot={got[1]}, "
        f"expected {int(want_path)}{int(want_root)}"
        for (p, want_path, want_root), got in zip(cases, verdicts)
        if got != f"{int(want_path)}{int(want_root)}"
    ]
    assert not wrong, "\n".join(wrong)


# -- The InitializeWizard pre-fill ---------------------------------------------
# Which folder the Star Citizen directory page offers, from the saved registry
# values. It uses the two checks above, and has two fixes of its own: the root
# is joined with AddBackslash (a saved root ending in a backslash used to give
# ...\StarCitizen\\LIVE), and a trailing backslash is dropped before the
# PTU/EPTU/HOTFIX/TECH-PREVIEW to LIVE swap (ExtractFileName of a path ending
# in a backslash is always '').

_PREFILL_START = re.compile(r"^  NewRegPath := .*;$", re.M)
_PREFILL_END = "    DefaultPath := ExtractFilePath(DefaultPath) + 'LIVE';"


def _prefill_block(source, tree):
    """The pre-fill block of InitializeWizard, from the registry node names to
    the channel swap, cut verbatim and pointed at fake inputs: registry reads
    go to FakeReg (so nothing touches the registry), and the hard-coded
    Program Files defaults go to folders under *tree* (so a real install on
    this machine cannot change the result)."""
    start = _PREFILL_START.search(source)
    assert start, "pre-fill block not found in installer.iss"
    end = source.index(_PREFILL_END, start.start()) + len(_PREFILL_END)
    block = source[start.start():end]
    block = block.replace("RegQueryStringValue(HKCU, ", "FakeReg(")
    block = block.replace("'C:\\Program Files (x86)\\", f"'{tree}\\PF86\\")
    block = block.replace("'C:\\Program Files\\", f"'{tree}\\PF\\")
    assert "RegQueryStringValue" not in block, "pre-fill block still reads the registry"
    assert "C:\\Program Files" not in block, "pre-fill block still reads real folders"
    assert "sc_install_root" in block
    return block


def _prefill_cases(t):
    """(name, saved registry values, expected pre-fill) against _make_tree's
    tree. A value is (node, name, data) with node "N" for the Smart Citizen
    node and "L" for the legacy SC Localization Editor node."""
    sc = f"{t}\\StarCitizen"
    stale = f"{t}\\SmartCitizen 1.4.1"
    only_ptu = f"{t}\\OnlyPTU\\StarCitizen"
    default = f"{t}\\PF\\Roberts Space Industries\\StarCitizen"
    live = sc + "\\LIVE"
    return [
        ("nothing saved", [], default),
        ("root", [("N", "sc_install_root", sc)], live),
        ("root with a trailing backslash", [("N", "sc_install_root", sc + "\\")], live),
        ("root that is a channel folder", [("N", "sc_install_root", live)], default),
        ("channel-folder root, then a good sc_directory",
         [("N", "sc_install_root", live), ("N", "sc_directory", live)], live),
        ("sc_directory LIVE", [("N", "sc_directory", live)], live),
        ("sc_directory LIVE with a trailing backslash", [("N", "sc_directory", live + "\\")], live),
        ("sc_directory PTU", [("N", "sc_directory", sc + "\\PTU")], live),
        ("sc_directory PTU with a trailing backslash", [("N", "sc_directory", sc + "\\PTU\\")], live),
        ("gone sc_directory, then game_install_path EPTU",
         [("N", "sc_directory", f"{t}\\Gone\\LIVE"), ("N", "game_install_path", sc + "\\EPTU")], live),
        ("stale root, then game_install_path",
         [("N", "sc_install_root", stale), ("N", "game_install_path", live)], live),
        ("legacy sc_directory EPTU", [("L", "sc_directory", sc + "\\EPTU")], live),
        ("legacy game_install_path LIVE with a trailing backslash",
         [("L", "game_install_path", live + "\\")], live),
        ("only a stale value", [("N", "sc_directory", stale)], default),
        ("install with only a PTU folder",
         [("N", "sc_directory", only_ptu + "\\PTU")], only_ptu + "\\LIVE"),
        ("forward slashes",
         [("N", "sc_directory", sc.replace("\\", "/") + "/PTU")], sc.replace("\\", "/") + "/LIVE"),
        ("the new node beats the legacy one",
         [("N", "sc_directory", live), ("L", "sc_directory", only_ptu + "\\PTU")], live),
    ]


@pytest.mark.skipif(_iscc() is None, reason="Inno Setup (ISCC.exe) not installed")
def test_wizard_prefill_in_compiled_installer_code(tmp_path):
    tree = tmp_path / "tree"
    out = tmp_path / "out"
    _make_tree(tree)
    cases = _prefill_cases(tree)
    source = _installer_source()

    steps = []
    for i, (_, values, _) in enumerate(cases):
        steps.append("  FakeClear();")
        steps.extend(
            f"  FakeSet({_pascal_string(node)}, {_pascal_string(name)}, {_pascal_string(data)});"
            for node, name, data in values
        )
        steps.append(f"  Lines[{i}] := Prefill();")
    script = f"""[Setup]
AppName=SC pre-fill probe
AppVersion=1.0
CreateAppDir=no
Uninstallable=no
PrivilegesRequired=lowest
OutputDir={out}
OutputBaseFilename=probe

[Code]
const
  SCRegNode = 'Probe\\Smart Citizen';
  SCLegacyRegNode = 'Probe\\SC Localization Editor';

var
  FakeNodes, FakeNames, FakeData: TArrayOfString;
  FakeCount: Integer;

{_pascal_function(source, "IsValidSCRoot")}

{_pascal_function(source, "IsValidSCPath")}

procedure FakeClear();
begin
  FakeCount := 0;
end;

procedure FakeSet(const Node, Name, Data: String);
begin
  SetArrayLength(FakeNodes, FakeCount + 1);
  SetArrayLength(FakeNames, FakeCount + 1);
  SetArrayLength(FakeData, FakeCount + 1);
  FakeNodes[FakeCount] := Node;
  FakeNames[FakeCount] := Name;
  FakeData[FakeCount] := Data;
  FakeCount := FakeCount + 1;
end;

function FakeReg(const SubKey, Name: String; var Data: String): Boolean;
var
  Node: String;
  I: Integer;
begin
  if Pos('SC Localization Editor', SubKey) > 0 then Node := 'L' else Node := 'N';
  Result := False;
  for I := 0 to FakeCount - 1 do
    if (FakeNodes[I] = Node) and (FakeNames[I] = Name) then
    begin
      Data := FakeData[I];
      Result := True;
      Exit;
    end;
end;

function Prefill(): String;
var
  NewRegPath: String;
  LegacyRegPath: String;
  DefaultPath: String;
  SavedPath: String;
  SCRoot: String;
  ActiveChannel: String;
  DefaultLeaf: String;
begin
{_prefill_block(source, tree)}
  Result := DefaultPath;
end;

function InitializeSetup(): Boolean;
var
  Lines: TArrayOfString;
begin
  SetArrayLength(Lines, {len(cases)});
{chr(10).join(steps)}
  SaveStringsToFile({_pascal_string(str(out / "result.txt"))}, Lines, False);
  Result := False;
end;
"""
    got = _run_probe(script, tmp_path, out)
    assert len(got) == len(cases)
    wrong = [
        f"{name}: got {have!r}, expected {want!r}"
        for (name, _, want), have in zip(cases, got)
        if have != want
    ]
    assert not wrong, "\n".join(wrong)
