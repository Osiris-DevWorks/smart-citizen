"""installer.iss OneDrive checks behind the data-folder pre-fill (#432).

``IsDocsOnOneDrive`` used to look for the literal text ``\\OneDrive\\`` in the
shell Documents path. A work or school OneDrive names its folder
``OneDrive - Contoso`` (the app's own check, ``onedrive.is_onedrive_path``,
accepts that too), so on those machines the data-folder page offered the
OneDrive path as its default instead of the local one. Only the Next-click
warning caught it. It now asks ``IsPathOnOneDrive``, the same check that
warning uses, so the pre-fill, the warning and the app agree.
``IsPathOnOneDrive`` also takes ``/`` as a separator now, since the old check
matched ``\\OneDrive/`` and a path typed into the data-folder box can use
forward slashes.

Recognising those machines would have let a silent update (the in-app
updater, which never shows the page) move an existing install's data folder to
the local path and leave ``user.ini`` behind. So the pre-fill only suggests the
local folder when ``Documents\\Smart Citizen`` does not exist yet.

The behaviour test cuts the OneDrive functions and the pre-fill ladder
verbatim out of installer.iss, points their registry and environment reads at
fakes, compiles them into a throwaway setup with Inno Setup's ISCC, runs it
silently and reads its verdicts back. It is skipped where Inno Setup is not
installed or an Application Control policy refuses to run the unsigned probe.
GitHub's Windows runner image ships Inno Setup 6, so it runs in CI as well as
on a developer machine that has Inno Setup. The two text checks run everywhere.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

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


def _needed_functions(source, text, needed=None):
    """The installer.iss functions that *text* calls, directly or through each
    other, as ``{name: source}`` with every callee ahead of its callers (Pascal
    Script needs a function declared before it is used). Following the calls
    keeps the probe working when a helper is added to or renamed in the code
    it cuts out."""
    needed = {} if needed is None else needed
    for name in re.findall(r"\b([A-Za-z_]\w*)\(", re.sub(r"\{.*?\}", "", text, flags=re.S)):
        match = (
            None
            if name in needed
            else re.search(rf"^function {name}\(.*?^end;$", source, re.S | re.M)
        )
        if match:
            needed[name] = None  # in place first, so a call cycle ends
            _needed_functions(source, match.group(0), needed)
            del needed[name]
            needed[name] = match.group(0)
    return needed


def _pascal_string(value):
    return "'" + value.replace("'", "''") + "'"


# -- Text checks, which need no Inno Setup ---------------------------------------


def test_docs_check_asks_the_shared_path_check():
    docs = _pascal_function(_installer_source(), "IsDocsOnOneDrive")
    assert "IsPathOnOneDrive(" in docs
    assert "Pos(" not in docs, "IsDocsOnOneDrive matches OneDrive paths by hand again"


def test_path_check_is_declared_before_the_docs_check():
    # Pascal Script needs a function declared before it is used, and CI does
    # not compile installer.iss (release.yml does), so a wrong order would only
    # show up when a release is built.
    source = _installer_source()
    assert source.index("function IsPathOnOneDrive(") < source.index("function IsDocsOnOneDrive(")


# -- Behaviour, in the compiled installer code -----------------------------------

_NO_ROOTS = ("", "", "")

# (name, Documents path or None for "no registry value", (%OneDrive%,
# %OneDriveConsumer%, %OneDriveCommercial%), whether it counts as OneDrive).
# IsDocsOnOneDrive() and IsPathOnOneDrive(<that path>) must both give the answer.
_CASES = [
    ("personal OneDrive", r"C:\Users\Sam\OneDrive\Documents", _NO_ROOTS, True),
    ("work OneDrive", r"C:\Users\Sam\OneDrive - Contoso\Documents", _NO_ROOTS, True),
    ("work OneDrive without spaces", r"C:\Users\Sam\OneDrive-Contoso\Documents", _NO_ROOTS, True),
    (
        "work OneDrive named with a comma",
        r"C:\Users\Sam\OneDrive - Smith, Jones & Co\Documents",
        _NO_ROOTS,
        True,
    ),
    ("work OneDrive in capitals", r"C:\USERS\SAM\ONEDRIVE - CONTOSO\DOCUMENTS", _NO_ROOTS, True),
    ("slash after the OneDrive folder", "C:\\Users\\Sam\\OneDrive/Documents", _NO_ROOTS, True),
    ("slashes all through", "C:/Users/Sam/OneDrive - Contoso/Documents", _NO_ROOTS, True),
    ("root from %OneDriveCommercial%", r"D:\Work\Sync\Documents", ("", "", r"D:\Work\Sync"), True),
    ("root from %OneDriveConsumer%", r"E:\Sync\Documents", ("", r"E:\Sync", ""), True),
    (
        "root from %OneDrive% with a trailing backslash",
        r"D:\Work\Sync\Documents",
        ("D:\\Work\\Sync\\", "", ""),
        True,
    ),
    (
        "root from the environment, slashes",
        "D:/Work/Sync/Documents",
        ("", "", r"D:\Work\Sync"),
        True,
    ),
    ("sibling of a root", r"D:\Work\SyncOld\Documents", ("", "", r"D:\Work\Sync"), False),
    (
        "OneDrive set, Documents elsewhere",
        r"C:\Users\Sam\Documents",
        (r"C:\Users\Sam\OneDrive", "", ""),
        False,
    ),
    ("look-alike OneDriveBackups", r"C:\Users\Sam\OneDriveBackups\Documents", _NO_ROOTS, False),
    ("look-alike with a space", r"C:\Users\Sam\OneDrive Stuff\Documents", _NO_ROOTS, False),
    ("plain Documents", r"C:\Users\Sam\Documents", _NO_ROOTS, False),
    ("Documents on another drive", r"D:\Documents", _NO_ROOTS, False),
    ("empty Documents path", "", _NO_ROOTS, False),
    ("no registry value", None, _NO_ROOTS, False),
]

# The data-folder pre-fill in InitializeWizard: one if/else chain, from the saved
# override to the Documents default.
_PREFILL_START = re.compile(
    r"^  if RegQueryStringValue\(HKCU, NewRegPath, 'user_data_dir', SavedDataDir\) and$", re.M
)
_PREFILL_NODE = "Probe\\Smart Citizen"


def _prefill_cases(tree):
    """(name, (folder Documents sits in, saved user_data_dir or None, whether
    ``Documents\\Smart Citizen`` already exists, expected pre-fill)), for folders
    made under *tree*. The expected pre-fill is ``"default"``
    (Documents\\Smart Citizen), ``"local"`` (the %USERPROFILE% folder) or the
    saved override's own path."""
    onedrive_work = "OneDrive - Contoso"
    saved = str(tree / "Data" / "Mine")
    versioned = str(tree / "Data" / "Smart Citizen 1.4.1")
    gone = str(tree / "Data" / "Gone")
    return [
        ("work OneDrive, nothing there yet", (onedrive_work, None, False, "local")),
        ("work OneDrive, data already there", (onedrive_work, None, True, "default")),
        ("personal OneDrive, nothing there yet", ("OneDrive", None, False, "local")),
        ("personal OneDrive, data already there", ("OneDrive", None, True, "default")),
        ("plain Documents, nothing there yet", ("Plain", None, False, "default")),
        ("plain Documents, data already there", ("Plain", None, True, "default")),
        ("saved override beats the suggestion", (onedrive_work, saved, False, saved)),
        ("saved override, data already there", (onedrive_work, saved, True, saved)),
        ("gone override, nothing there yet", (onedrive_work, gone, False, "local")),
        ("gone override, data already there", (onedrive_work, gone, True, "default")),
        ("versioned leftover override", (onedrive_work, versioned, False, "local")),
        ("empty override", (onedrive_work, "", False, "local")),
    ]


def _make_prefill_tree(tree, cases):
    """Create what the cases rely on and return ``(name, docs, override,
    expected)`` with every path spelled out."""
    (tree / "Data" / "Mine").mkdir(parents=True)
    (tree / "Data" / "Smart Citizen 1.4.1").mkdir(parents=True)
    local = os.environ["USERPROFILE"] + "\\Documents\\Smart Citizen"
    resolved = []
    for i, (name, (folder, override, existing, expected)) in enumerate(cases):
        docs = tree / f"case{i}" / "Users" / "Sam" / folder / "Documents"
        docs.mkdir(parents=True)
        if existing:
            (docs / "Smart Citizen").mkdir()
        want = {"default": f"{docs}\\Smart Citizen", "local": local}.get(expected, expected)
        resolved.append((name, str(docs), override, want))
    return resolved


# What the cut-out code reads from the machine, as fakes. FakeReg answers only
# the two values the code reads, so a changed registry read fails the test
# instead of reading this machine's registry. Folder checks (DirExists) use the
# real folders made under the test's tmp_path.
_FAKES = f"""var
  FakeDocs, FakeOverride: String;
  FakeHasDocs, FakeHasOverride: Boolean;
  FakeRoot0, FakeRoot1, FakeRoot2: String;

function FakeReg(const SubKey, Name: String; var Data: String): Boolean;
begin
  Result := False;
  if (Name = 'Personal') and (Pos('Shell Folders', SubKey) > 0) then
  begin
    Result := FakeHasDocs;
    if Result then
      Data := FakeDocs;
  end
  else if (Name = 'user_data_dir') and (SubKey = {_pascal_string(_PREFILL_NODE)}) then
  begin
    Result := FakeHasOverride;
    if Result then
      Data := FakeOverride;
  end;
end;

function FakeEnv(const Name: String): String;
begin
  Result := '';
  if Name = 'OneDrive' then
    Result := FakeRoot0
  else if Name = 'OneDriveConsumer' then
    Result := FakeRoot1
  else if Name = 'OneDriveCommercial' then
    Result := FakeRoot2;
end;

function B(const V: Boolean): String;
begin
  if V then Result := '1' else Result := '0';
end;
"""


def _fake_reads(text):
    """Point the registry and environment reads in *text* at the fakes."""
    text = re.sub(r"RegQueryStringValue\(HKCU,\s*", "FakeReg(", text)
    text = text.replace("GetEnv(", "FakeEnv(")
    assert "RegQueryStringValue" not in text, "cut-out code still reads the registry"
    assert "GetEnv(" not in text, "cut-out code still reads the environment"
    return text


def _prefill_block(source):
    """The pre-fill ladder from InitializeWizard, verbatim, assigning to
    ``Result`` instead of the data-folder page."""
    start = _PREFILL_START.search(source)
    assert start, "data-folder pre-fill not found in installer.iss"
    begin = start.start()
    end = source.index(";", begin) + 1  # the whole if/else chain is one statement
    return source[begin:end].replace("DataDirPage.Values[0]", "Result")


def _cut_functions(source, block):
    """The OneDrive checks, and every function the pre-fill *block* calls, cut
    verbatim out of *source* with their registry and environment reads pointed
    at the fakes."""
    needed = _needed_functions(source, block + "\nIsDocsOnOneDrive(); IsPathOnOneDrive('');")
    assert "IsDocsOnOneDrive" in needed and "IsPathOnOneDrive" in needed
    return _fake_reads("\n\n".join(needed.values()))


def _prefill_function(block):
    """*block* wrapped in a function that returns the value InitializeWizard
    would put on the data-folder page."""
    return f"""function DataDirPrefill(): String;
var
  NewRegPath: String;
  SavedDataDir: String;
begin
  NewRegPath := {_pascal_string(_PREFILL_NODE)};
{_fake_reads(block)}
end;
"""


def _probe_script(source, cases, prefill_cases, out):
    block = _prefill_block(source)
    steps = []
    for i, (_, docs, roots, _) in enumerate(cases):
        steps.append(
            f"  FakeHasDocs := {'False' if docs is None else 'True'}; "
            f"FakeDocs := {_pascal_string(docs or '')};"
        )
        steps.append(
            "  FakeRoot0 := {}; FakeRoot1 := {}; FakeRoot2 := {};".format(
                *(_pascal_string(r) for r in roots)
            )
        )
        steps.append(f"  Lines[{i}] := B(IsDocsOnOneDrive()) + B(IsPathOnOneDrive(FakeDocs));")
    for j, (_, docs, override, _) in enumerate(prefill_cases, start=len(cases)):
        steps.append(
            f"  FakeHasDocs := True; FakeDocs := {_pascal_string(docs)}; "
            f"FakeHasOverride := {'False' if override is None else 'True'}; "
            f"FakeOverride := {_pascal_string(override or '')};"
        )
        steps.append("  FakeRoot0 := ''; FakeRoot1 := ''; FakeRoot2 := '';")
        steps.append(f"  Lines[{j}] := DataDirPrefill();")
    return f"""[Setup]
AppName=OneDrive check probe
AppVersion=1.0
CreateAppDir=no
Uninstallable=no
PrivilegesRequired=lowest
OutputDir={out}
OutputBaseFilename=probe

[Code]
{_FAKES}
{_cut_functions(source, block)}

{_prefill_function(block)}
function InitializeSetup(): Boolean;
var
  Lines: TArrayOfString;
begin
  SetArrayLength(Lines, {len(cases) + len(prefill_cases)});
{chr(10).join(steps)}
  SaveStringsToFile({_pascal_string(str(out / "result.txt"))}, Lines, False);
  Result := False;
end;
"""


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
        subprocess.run([str(out / "probe.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES"], timeout=120)
    except OSError as exc:
        # ERROR_SYSTEM_INTEGRITY_POLICY_VIOLATION: an Application Control
        # policy (e.g. a sandboxed shell) refused to run the unsigned probe.
        if getattr(exc, "winerror", None) == 4551:
            pytest.skip(f"probe setup blocked by Application Control: {exc}")
        raise
    return (out / "result.txt").read_text(encoding="mbcs").splitlines()


@pytest.mark.skipif(_iscc() is None, reason="Inno Setup (ISCC.exe) not installed")
def test_onedrive_checks_in_compiled_installer_code(tmp_path):
    tree = tmp_path / "tree"
    out = tmp_path / "out"
    prefill_cases = _make_prefill_tree(tree, _prefill_cases(tree))
    script = _probe_script(_installer_source(), _CASES, prefill_cases, out)
    verdicts = _run_probe(script, tmp_path, out)
    first_prefill = len(_CASES)
    assert len(verdicts) == first_prefill + len(prefill_cases)
    wrong = [
        f"{name}: {docs!r}: IsDocsOnOneDrive={got[0]} IsPathOnOneDrive={got[1]}, "
        f"expected {int(want)} for both"
        for (name, docs, _, want), got in zip(_CASES, verdicts)
        if got != f"{int(want)}{int(want)}"
    ]
    wrong += [
        f"pre-fill, {name}: got {got!r}, expected {want!r}"
        for (name, _, _, want), got in zip(prefill_cases, verdicts[first_prefill:])
        if got != want
    ]
    assert not wrong, "\n".join(wrong)
