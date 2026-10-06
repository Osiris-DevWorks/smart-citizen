"""installer.iss deletes only Smart Citizen's own folders (the #419 review follow-ups).

Two gaps were found in the code that deletes folders, both about a data folder
the user picked (the Config tab allows any folder, a whole drive included):

* The opt-in wipe (#357) deleted ``<data folder>\\cache`` whole. ``cache`` is a
  generic name, so with a data folder such as ``D:\\Data`` another program's
  ``cache`` folder went too. The wipe now deletes it only when it holds a Smart
  Citizen cache (``LooksLikeScCache``: a ``base.ini``, a ``dataforge`` folder, or
  a ``<channel>\\cache`` folder).
* ``CleanCachedData`` and ``CleanPerChannelCaches`` run on every install,
  upgrade, auto-update and uninstall, and used to delete inside the data folder
  with no check at all: with a data folder of ``D:\\`` the next update deleted
  ``D:\\cache``. They now ask ``UnsafeDeleteRootReason`` first (the same refusals
  as the wipe) and do nothing, with the reason in the log and never a dialog,
  in a folder it refuses. The flat ``cache`` folder they clear is held to the
  same ``LooksLikeScCache`` rule.

#454 found a third, about the install folder:

* ``[InstallDelete]`` emptied whatever install folder was chosen (#454), and
  every later upgrade emptied it again. It now empties the folder only when
  nothing but Smart Citizen's own files are in it (``WholeInstallDirReason``),
  and elsewhere deletes only Smart Citizen's own files, by their exact names.
  The install folder page gives an install its own ``Smart Citizen`` folder
  inside one that holds other files, unless it is the previous install's
  folder. The probe runs those checks and the real ``[InstallDelete]`` entries
  over install folders under ``tmp_path``.

The behaviour test cuts the real routines verbatim out of installer.iss, points
their registry reads, ``{app}`` and log at fakes, compiles them into a throwaway
setup with Inno Setup's ISCC, runs it silently against folders it deletes in
under ``tmp_path``, and checks which files are left. Nothing outside that tree
is deleted in. The only outside paths go to checks that read them as text and
delete nothing: a drive and network paths to the delete check on its own, and
relative install folders to the install folder checks on their own (the
``reason`` and ``install-reason`` cases). It is skipped where Inno
Setup is not installed (under CI it fails instead, see ``tests/inno_setup.py``)
or an Application Control policy refuses to run the unsigned probe. GitHub's Windows
runner image ships Inno Setup 6, so it runs in CI as well as on a developer
machine that has Inno Setup. The text checks run everywhere. They are structural
tripwires on the shape of each guard (see the note above them), and the compiled
test is the semantic check.
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import pytest

# The app's channel list, so a channel added there but not to the installer's
# checks fails here.
from src.utils.install_scanner import SC_CHANNELS as CHANNELS
from tests.inno_setup import pascal_string, require_iscc, run_probe

INSTALLER = Path(__file__).resolve().parent.parent / "installer.iss"


def _installer_source():
    return INSTALLER.read_text(encoding="utf-8-sig")


# Strings, { } comments and // comments: what is not code.
_NOT_CODE = re.compile(r"'(?:[^']|'')*'|\{[^}]*\}|//[^\n]*")
# A forward declaration is not the routine: its ``.*?^end;$`` would run on into
# the next routine.
_FORWARD = re.compile(r"^(?:function|procedure) (\w+)\([^\n]*\bforward;$", re.M)


def _definitions(source):
    """``{name: text}`` of every function and procedure *source* defines."""
    plain = _FORWARD.sub("", source)
    return {
        m.group(1): m.group(0)
        for m in re.finditer(r"^(?:function|procedure) (\w+)\(.*?^end;$", plain, re.S | re.M)
    }


def _pascal_routine(source, name):
    """The routine *name* through its closing ``end;``."""
    definitions = _definitions(source)
    assert name in definitions, f"{name} not found in installer.iss"
    return definitions[name]


# -- Text checks, which need no Inno Setup ----------------------------------------
# These read installer.iss as text, so they run on every machine. They are
# STRUCTURAL TRIPWIRES: each pins the shape of a guard (the call, its condition,
# the Exit, the check round each delete) so a guard that is deleted, inverted or
# aimed at the wrong folder fails here. They cannot show that a guard works. The
# compiled test further down is the semantic check, and it skips where Inno
# Setup is not installed.


def _code(text, strings=False):
    """*text* as code only: comments blanked, string literals blanked to ``''``
    (kept when *strings* is true) and white space collapsed to single spaces, so
    a pattern does not care about line breaks and a word in a comment or a log
    line is never mistaken for a call."""

    def blank(match):
        if not match.group(0).startswith("'"):
            return " "
        return match.group(0) if strings else "''"

    return re.sub(r"\s+", " ", _NOT_CODE.sub(blank, text)).strip()


def _routine_code(source, name, strings=False):
    return _code(_pascal_routine(source, name), strings)


def _code_by_routine(source, strings=False):
    """``[(routine name, its code)]`` for every routine."""
    return [(name, _code(text, strings)) for name, text in _definitions(source).items()]


def _section(source, name):
    """The entries of the ``[name]`` section (lines that are not blank or
    comments), or None when the section is not there. A section may appear more
    than once in a script, so every one is read."""
    sections = list(
        re.finditer(rf"^\[{name}\]\s*$(.*?)(?=^\[\w+\]\s*$|\Z)", source, re.S | re.M | re.I)
    )
    if not sections:
        return None
    lines = (line.strip() for match in sections for line in match.group(1).splitlines())
    return [line for line in lines if line and not line.startswith(";")]


def test_delete_safety_checks_are_declared_before_the_cache_cleaners():
    # Pascal Script needs a routine declared before it is used. The cleaners sit
    # far above UnsafeDeleteRootReason, so it is forward-declared.
    # test_whole_installer_compiles (test_installer_auto_update_relaunch.py)
    # compiles the whole file where Inno Setup is installed, and this check runs
    # everywhere.
    source = _installer_source()
    forward = "function UnsafeDeleteRootReason(const RawRoot: String): String; forward;"
    assert source.count(forward) == 1
    start = {
        m.group(1): m.start() for m in re.finditer(r"^(?:function|procedure) (\w+)\(", source, re.M)
    }
    for early in ("CleanPerChannelCaches", "CleanCachedData"):
        assert source.index(forward) < start[early]
    for user in ("CleanCachedData", "DeleteOwnedSubpaths"):
        assert start["LooksLikeScCache"] < start[user]


def test_cache_check_takes_its_channels_from_the_channel_list():
    # ScChannelName is the one list the wipe and the app's channel list are
    # checked against (test_install_scanner.py), so the check must not keep a
    # copy of the names.
    body = _routine_code(_installer_source(), "LooksLikeScCache", strings=True)
    assert "ScChannelName(" in body and "ScChannelCount" in body
    literals = re.findall(r"'(?:[^']|'')*'", body)
    assert not [s for s in literals if any(channel in s for channel in CHANNELS)]


def test_cache_check_has_its_three_marks_and_starts_from_false():
    # A predicate forced to True, or one that lost a mark, would let the wipe and
    # the cleaners delete a folder that is not ours (or skip one that is).
    code = _routine_code(_installer_source(), "LooksLikeScCache", strings=True)
    assert code.count("Result :=") == 3, (
        "LooksLikeScCache may set its answer only three times: the False it starts "
        f"from, the base.ini/dataforge line and the channel loop. Found: {code}"
    )
    assert (
        "begin Result := False; if not DirExists(Dir) then Exit;" in code
    ), "LooksLikeScCache must start from Result := False and give up on a missing folder"
    marks = {
        "a base.ini file or a dataforge folder": (
            "Result := FileExists(Dir + '\\base.ini') or DirExists(Dir + '\\dataforge');"
        ),
        "a <channel>\\cache folder for every channel": (
            "for i := 0 to ScChannelCount - 1 do if not Result then "
            "Result := DirExists(Dir + '\\' + ScChannelName(i) + '\\cache');"
        ),
    }
    for what, statement in marks.items():
        assert statement in code, f"LooksLikeScCache no longer recognises {what}: {statement}"


# The guard each cleaner starts with: ask about a folder, refuse on any reason,
# and Exit. The folder asked about is captured, to compare with the folder the
# DelTree deletes in.
_GUARD = re.compile(
    r"Reason := UnsafeDeleteRootReason\((?P<asked>\w+)\); "
    r"if Reason <> '' then begin (?:(?!\bend\b).)*?\bExit; end;"
)
# The flat cache is deleted only inside "if LooksLikeScCache(<that folder>)", whose
# else branch only logs.
_FLAT_CACHE_GATE = re.compile(
    r"if LooksLikeScCache\((?P<folder>\w+)\) then begin "
    r"(?:(?!\bend\b).)*?DelTree\((?P=folder), True, True, True\); end else Log\("
)
# The wipe's <root>\cache, the same way.
_WIPE_CACHE_GATE = (
    r"Item := Root \+ '\\cache'; if DirExists\(Item\) then begin "
    r"if LooksLikeScCache\(Item\) then Result := Result \+ DeleteOwnedItem\(Item, True\) "
    r"else Log\("
)


@pytest.mark.parametrize("name", ["CleanPerChannelCaches", "CleanCachedData"])
def test_each_cleaner_asks_about_the_folder_it_cleans_before_it_deletes(name):
    code = _routine_code(_installer_source(), name)
    assert code.count("DelTree(") == 1, (
        f"{name} must hold exactly one DelTree, behind its guard. Another one needs "
        "the same review, and a line here saying why it is safe."
    )
    guard = _GUARD.search(code)
    assert guard, (
        f"{name} must ask UnsafeDeleteRootReason about its data folder and give up when "
        "it names a reason: Reason := UnsafeDeleteRootReason(<folder>); "
        "if Reason <> '' then begin <log>; Exit; end;"
    )
    assert guard.end() <= code.index("DelTree("), f"{name}: the guard must come before the DelTree"
    deleted = re.search(r"DelTree\((\w+),", code)
    assert deleted, f"{name}: DelTree must delete a folder held in a variable it built"
    deleted = deleted.group(1)
    built = re.search(rf"\b{deleted} := (\w+) \+", code)
    assert built and built.group(1) == guard.group("asked"), (
        f"{name} asks about {guard.group('asked')} but deletes in {deleted}, which is built "
        f"from {built.group(1) if built else 'something else'}: the guard must ask about "
        "the data folder it is about to clean"
    )


def test_the_flat_cache_and_the_wipes_cache_are_deleted_only_behind_the_cache_check():
    source = _installer_source()
    flat = _routine_code(source, "CleanCachedData")
    assert _FLAT_CACHE_GATE.search(flat), (
        "CleanCachedData must delete the flat cache only inside "
        "'if LooksLikeScCache(<that folder>) then begin ... DelTree(<that folder>, ...); "
        "end else Log(...)'"
    )
    wipe = _routine_code(source, "DeleteOwnedSubpaths", strings=True)
    assert re.search(_WIPE_CACHE_GATE, wipe), (
        "DeleteOwnedSubpaths must delete <root>\\cache only inside "
        "'if LooksLikeScCache(Item) then Result := Result + DeleteOwnedItem(Item, True) "
        "else Log(...)'"
    )


# Every routine that deletes, and why it can only reach Smart Citizen's folders.
_DELETERS = {
    "DelTree": {
        "DeleteOwnedItem": "the wipe's one delete; every caller checks its root first",
        "CleanPerChannelCaches": "asks UnsafeDeleteRootReason first",
        "CleanCachedData": "asks UnsafeDeleteRootReason, and LooksLikeScCache for the flat cache",
    },
    "RemoveDir": {
        "RemoveEmptyIfSafe": "asks UnsafeDeleteRootReason, and removes only an empty folder"
    },
    "DeleteFile": {},
}


def test_every_delete_is_in_a_routine_that_checks_its_folder_first():
    # Pascal Script is case-insensitive and allows a space before the bracket, so
    # match both.
    found = {}
    for name, code in _code_by_routine(_installer_source()):
        for call in _DELETERS:
            if re.search(rf"(?<![A-Za-z0-9_]){call}\s*\(", code, re.I):
                found.setdefault(call, set()).add(name)
    unknown = {
        call: sorted(names - set(_DELETERS[call]))
        for call, names in found.items()
        if names - set(_DELETERS[call])
    }
    assert not unknown, (
        f"installer.iss deletes in a routine this test does not list: {unknown}. A delete "
        "there has to be reviewed first. Guard it the way CleanCachedData is (ask "
        "UnsafeDeleteRootReason before deleting, and keep to what only Smart Citizen "
        "writes), then add the routine to _DELETERS with the reason it is safe."
    )
    for call, routines in _DELETERS.items():
        gone = sorted(set(routines) - found.get(call, set()))
        assert not gone, f"{call} is gone from {gone}: take them out of _DELETERS too"


# Routines that start a program, and what for. A program can delete folders too
# (cmd /c rd /s /q ...), so a new one is a new delete.
_LAUNCHERS = {
    "UnInstallOldVersion": "runs the previous version's uninstaller",
    "InitializeSetup": "runs the previous version's uninstaller (uninstall only)",
    "CurStepChanged": "starts Smart Citizen again after an auto-update",
}
_LAUNCH_CALL = re.compile(r"(?<![A-Za-z0-9_])(?:Shell)?Exec\w*\s*\(", re.I)
_SHELL_WORDS = re.compile(
    r"\b(?:rd|rmdir|del|erase|remove-item|cmd|cmd\.exe|powershell|pwsh)\b", re.I
)


def test_no_program_is_started_to_delete_folders():
    source = _installer_source()
    starts = {name for name, code in _code_by_routine(source) if _LAUNCH_CALL.search(code)}
    assert starts == set(_LAUNCHERS), (
        f"The routines that start a program changed: {sorted(starts)}. A program can delete "
        "folders (cmd /c rd /s /q), so review the new one, then list it in _LAUNCHERS with "
        "what it runs."
    )
    # Anything that names a shell or a delete command, in a string or in a [Run] or
    # [UninstallRun] entry.
    code_start = source.index("\n[Code]")
    literals = re.findall(r"'(?:[^']|'')*'", _code(source[code_start:], strings=True))
    entries = (_section(source, "Run") or []) + (_section(source, "UninstallRun") or [])
    shellish = [text for text in literals + entries if _SHELL_WORDS.search(text)]
    assert (
        not shellish
    ), f"installer.iss names a shell or a delete command: {shellish}. Review it as a new delete."


# The delete entries outside [Code] (#454). The first empties the install folder,
# as before, but only behind InstallDirMayBeEmptied (WholeInstallDirReason). The
# rest delete only Smart Citizen's own files, by the exact names its releases
# installed, in any folder. A new or changed entry has to be reviewed before it
# is added here.
_INSTALL_DELETE = [
    'Type: filesandordirs; Name: "{app}\\*"; Check: InstallDirMayBeEmptied',
    'Type: files; Name: "{app}\\SmartCitizen.exe"',
    'Type: filesandordirs; Name: "{app}\\_internal"',
    'Type: files; Name: "{app}\\SmartCitizen-v?.?.?.exe"',
    'Type: files; Name: "{app}\\SCLocalizationEditor.exe"',
    'Type: files; Name: "{app}\\SCLocalizationEditor-v?.?.?.exe"',
]
_INSTALL_DELETE_ENTRY = re.compile(
    r'^Type: (?P<type>files|filesandordirs); Name: "\{app\}\\(?P<name>[^"]+)"'
    r"(?:; Check: (?P<check>\w+))?$"
)
# A program entry: an exact name, or a name ending in -v and a version of three
# one-digit parts (each ? is one character). A * or a longer version would also
# take a download that starts the same way, such as an old -Setup.exe.
_PROGRAM_ENTRY = re.compile(r"(?P<fixed>[A-Za-z]+(?:-v)?)(?P<version>\?\.\?\.\?)?\.exe")


def test_install_and_uninstall_delete_entries_are_pinned():
    source = _installer_source()
    assert _section(source, "InstallDelete") == _INSTALL_DELETE, (
        "[InstallDelete] changed. A new delete entry has to be reviewed (what can it reach, "
        "and has the folder been checked?) before it is added to _INSTALL_DELETE."
    )
    assert not _section(source, "UninstallDelete"), (
        "installer.iss has an [UninstallDelete] entry. A new delete entry has to be "
        "reviewed first, then pinned here."
    )


def test_install_folder_deletes_name_only_smart_citizens_files():
    # #454: the install folder can be any folder, so only the entry that empties
    # it whole has a Check, and every other entry names only Smart Citizen's own
    # files, the same ones the checks in [Code] count as Smart Citizen's.
    source = _installer_source()
    entries = _section(source, "InstallDelete")
    matches = [_INSTALL_DELETE_ENTRY.match(entry) for entry in entries]
    assert all(matches), f"an [InstallDelete] entry has an unexpected shape: {entries}"
    whole = [m for m in matches if m["name"] == "*"]
    assert len(whole) == 1 and whole[0]["check"] == "InstallDirMayBeEmptied", (
        "only one entry may empty the install folder, and only behind "
        "Check: InstallDirMayBeEmptied"
    )
    program = _routine_code(source, "IsOwnProgramFile", strings=True)
    scan = _routine_code(source, "ScanInstallDir", strings=True)
    # What IsOwnProgramFile must name, one string for each program entry, and
    # nothing more: it counts as Smart Citizen's exactly what these entries delete.
    expected = set()
    for m in matches:
        name = m["name"]
        if name == "*":
            continue
        assert m["check"] is None, f"{name}: Smart Citizen's own files go in any folder"
        if name == "_internal":
            assert m["type"] == "filesandordirs" and "'_internal'" in scan, (
                "_internal goes as a folder, and ScanInstallDir counts it as ours"
            )
            continue
        shape = _PROGRAM_ENTRY.fullmatch(name)
        assert shape and m["type"] == "files", (
            f"{name}: a program entry is a 'files' entry with an exact name or a name "
            "ending in -v?.?.?.exe. A wider wildcard also deletes downloads such as an old "
            "-Setup.exe."
        )
        fixed = shape["fixed"].lower()
        if shape["version"]:
            # Windows matches a wildcard against 8.3 short names as well, so a short
            # fixed part could match another program's file through its short name.
            assert len(fixed) > 8, f"{name}: a wildcard needs more than 8 fixed characters"
            call = f"IsVersionedProgramName(Low, '{fixed}')"
        else:
            fixed = name.lower()
            call = f"(Low = '{fixed}')"
        assert call in program, f"{name} is deleted in any folder, but IsOwnProgramFile lacks it"
        expected.add(f"'{fixed}'")
    named = set(re.findall(r"'(?:[^']|'')*'", program))
    assert named == expected, (
        f"IsOwnProgramFile names {sorted(named)}, but the program entries of "
        f"[InstallDelete] delete {sorted(expected)}: keep the two in step"
    )
    # IsVersionedProgramName takes a digit for each ? and nothing more.
    versioned = _routine_code(source, "IsVersionedProgramName", strings=True)
    for part in ("Length(Low) = Length(Prefix) + 9", "'0123456789'", "'.exe'", "= '.'"):
        assert part in versioned, f"IsVersionedProgramName lost {part}"
    # The program the shortcuts start is deleted too, or a renamed exe would pile up
    # in a shared folder.
    started = re.findall(
        r'Filename: "\{app\}\\([^"\\]+\.exe)"',
        "\n".join((_section(source, "Icons") or []) + (_section(source, "Run") or [])),
    )
    assert started and set(started) <= {m["name"] for m in matches}


# Where a folder of its own would make the path too long, Setup does not install
# there: a person is asked for another folder and stays on the page, and a silent
# run logs why and stops (False ends a silent Setup without installing, and the
# in-app updater never gets here, because the previous install's folder is never
# moved). Strings are blanked, so the arguments hold no semicolon.
_TOO_LONG_STOP = re.compile(
    r"if TooLong then begin if WizardSilent\(\) then Log\([^;]*\bOwn\b[^;]*\) "
    r"else SuppressibleMsgBox\([^;]*\bOwn\b[^;]*, MB_OK, IDOK\); Result := False; Exit; end;"
)


def test_the_folder_page_gives_a_shared_folder_its_own_folder():
    source = _installer_source()
    click = _routine_code(source, "NextButtonClick")
    # Straight into the data folder page's exit, so nothing can change the guard's
    # answer on the way out.
    hook = (
        "Result := True; if CurPageID = wpSelectDir then Result := GiveInstallItsOwnFolder(); "
        "if (DataDirPage = nil) or (CurPageID <> DataDirPage.ID) then Exit;"
    )
    assert hook in click, (
        "NextButtonClick must hand the install folder page to GiveInstallItsOwnFolder "
        f"and go straight on to its exit for every page but the data folder's: {hook}"
    )
    give = _routine_code(source, "GiveInstallItsOwnFolder")
    for statement in (
        "Chosen := WizardDirValue();",
        "Own := NewInstallDir(Chosen, ExtractFileDir(RemoveQuotes(GetUninstallString())), "
        "TooLong);",
        # Without it, every Next shows the box and returns False, so a person can
        # never leave the page.
        "if Own = Chosen then Exit;",
        "WizardForm.DirEdit.Text := Own;",
        "if WizardSilent() then Exit;",
    ):
        assert statement in give, f"GiveInstallItsOwnFolder lost: {statement}"
    too_long = _TOO_LONG_STOP.search(give)
    assert too_long, (
        "GiveInstallItsOwnFolder must keep Setup out of a folder where a folder of its own "
        "would be too long: if TooLong then begin if WizardSilent() then Log(...Own...) "
        "else SuppressibleMsgBox(...Own...); Result := False; Exit; end;"
    )
    # A silent Setup that gets False on this page ends without installing. That is
    # wanted only where the path is too long, which the in-app updater never reaches,
    # so the move's False comes after its silent exit.
    assert give.count("Result := False;") == 2 and give.count("SuppressibleMsgBox(") == 2
    order = [
        "Result := True;",
        "Own := NewInstallDir(",
        # Before the early exit, because a too-long folder is kept as chosen.
        too_long.group(0),
        "if Own = Chosen then Exit;",
        "WizardForm.DirEdit.Text := Own;",
        "if WizardSilent() then Exit;",
    ]
    places = [give.index(statement) for statement in order]
    places += [give.rindex("SuppressibleMsgBox("), give.rindex("Result := False;")]
    assert places == sorted(places), (
        f"GiveInstallItsOwnFolder must run in this order: {order}, then the move's box and "
        "Result := False;"
    )


def test_install_folder_checks_take_their_folder_as_a_parameter():
    # The probe runs these with folders under tmp_path, so they must not read the
    # wizard or the install folder constant themselves.
    source = _installer_source()
    for name in (
        "IsVersionedProgramName",
        "IsOwnProgramFile",
        "ScanInstallDir",
        "WholeInstallDirReason",
        "NewInstallDir",
    ):
        code = _routine_code(source, name)
        for outside in (
            "WizardForm",
            "WizardDirValue",
            "WizardSilent",
            "DataDirPage",
            "CacheDirPage",
            "GetUninstallString",
            "ExpandConstant",
        ):
            assert outside not in code, f"{name} reads {outside}: pass the folder in instead"
    # Asked afresh each time, never cached: the answer just before the delete counts.
    # This pins only InstallDirMayBeEmptied. The probe's install-refill case is the
    # semantic check, and it also sees a cache in the routines this one calls.
    check = _routine_code(source, "InstallDirMayBeEmptied", strings=True)
    assert (
        "Dir := ExpandConstant('{app}'); Reason := WholeInstallDirReason(Dir); "
        "Result := (Reason = '');" in check
    )
    assert check.count("Result :=") == 1
    scan = _routine_code(source, "ScanInstallDir", strings=True)
    assert scan.count("FindFirst(") == 1 and "FindFirst(LongPath(Root) + '\\*', FR)" in scan
    for name in ("'unins000.exe'", "'unins000.dat'", "'unins000.msg'"):
        assert name in scan


def test_install_folder_name_matches_setup():
    # The folder the install folder page adds is the one Browse adds, the last
    # part of DefaultDirName.
    source = _installer_source()
    default = [e for e in _section(source, "Setup") if e.startswith("DefaultDirName=")]
    assert len(default) == 1
    name = re.search(r"^  AppFolderName = '(.*)';$", source, re.M)
    assert name and default[0].split("\\")[-1] == name.group(1) == _OWN
    assert "Result := AddBackslash(Result) + AppFolderName;" in _routine_code(
        source, "NewInstallDir"
    )


def test_the_guard_stops_only_where_it_must():
    # NewInstallDir keeps a folder that is only Smart Citizen's or the previous
    # install's. A Smart Citizen program in a shared folder is no reason (a loose
    # old portable copy has the same name), and the narrow delete would then take
    # the folder's _internal. It also stops before a path Setup would refuse on its
    # folder page (ValidateCustomDirEdit), which a silent run does not check again,
    # and says so in TooLong, which GiveInstallItsOwnFolder turns into a box.
    source = _installer_source()
    guard = _routine_code(source, "NewInstallDir")
    keep = "if OnlyOwn or SameDir(Result, PreviousDir) then Exit;"
    too_long = "if Length(AddBackslash(Result) + AppFolderName) > MaxInstallDirLength then begin"
    for statement in (
        "begin TooLong := False; Result := Chosen; for i := 1 to 3 do begin",
        keep,
        too_long,
        "TooLong := True; Exit; end;",
    ):
        assert statement in guard, f"NewInstallDir lost: {statement}"
    # Kept before the length is looked at, so an upgrade in a long folder is never
    # asked for another one.
    assert guard.index(keep) < guard.index(too_long), f"NewInstallDir must ask {keep} first"
    assert guard.count("TooLong :=") == 2
    assert re.search(rf"^  MaxInstallDirLength = {_MAX_DIR};$", source, re.M)


# -- Behaviour, in the compiled installer code ------------------------------------


@dataclass
class Case:
    """One folder tree and what a routine must leave of it. *entries* are made
    under the case's own folder (a trailing ``/`` makes a folder, otherwise a
    file), *gone* are the ones that must be deleted (a folder takes what is in
    it, the rest must still be there)."""

    name: str
    # cache, clean, channels, wipe, wipe-cache-root, reason, install, install-refill
    # or install-reason
    kind: str
    entries: list
    target: str  # the folder under test, relative to the case's folder
    gone: list = field(default_factory=list)
    override: bool = False  # the user_data_dir registry value is *target*
    sc_root: str = ""  # relative path saved as sc_install_root
    app: str = "App"  # the fake {app}
    docs: str = "Docs"  # the fake shell Documents folder
    # cache: "1" or "0", reason: the reason ("" for none), install: "whole" or "narrow",
    # install-refill: the first Check's answer, install-reason:
    # "<WholeInstallDirReason> > <NewInstallDir> > too long|not too long"
    expect: str = ""
    # reason and install-reason: a path outside the tree, which the checks only read as text
    outside: str = ""
    notes: str = ""  # wipe: "" for no summary, else text it must hold
    log: object = None  # text the log must hold, "" for an empty log, None for either
    # install and install-reason: the previous install's folder, "" for none (read as
    # text only, like *outside*, in an install-reason case)
    previous: str = ""
    moved: str = ""  # install: the folder the guard must pick, "" for *target* itself
    # (link, target) pairs, made as junctions; an entry behind a link is made at its target
    links: list = field(default_factory=list)
    base: Path = None


# What InstallDirMayBeEmptied logs for each answer (#454).
_INSTALL_LOG = {
    "whole": "is Smart Citizen's own folder, so it is emptied",
    "narrow": (
        "only Smart Citizen's own files there are deleted, "
        "because it holds files Smart Citizen did not install"
    ),
}
# The data file an install-refill case puts in its install folder between the two
# Checks, relative to that folder.
_REFILL_DATA = "LIVE/user.ini"
# The kinds whose checks read a folder as text and delete nothing, the only ones
# that may name a path outside the tree.
_TEXT_ONLY_KINDS = ("reason", "install-reason")
# installer.iss's AppFolderName and MaxInstallDirLength, the folder the guard adds
# and Setup's own length limit, pinned to the installer by
# test_install_folder_name_matches_setup and test_the_guard_stops_only_where_it_must.
_OWN = "Smart Citizen"
_MAX_DIR = 240


def _channel_caches(root):
    return [f"{root}/{channel}/cache" for channel in CHANNELS]


def _sc_files(root):
    """What Smart Citizen keeps in a data folder, every channel's cache and the
    things that must survive a cache clean."""
    entries = []
    for channel in CHANNELS:
        entries += [
            f"{root}/{channel}/cache/base.ini",
            f"{root}/{channel}/cache/lang/german/base.ini",
            f"{root}/{channel}/user.ini",
            f"{root}/{channel}/backups/global.ini.bak_1",
        ]
    return entries


def _cases(t):
    """The cases, in the order the probe runs them, for a tree rooted at *t*.
    Makes nothing on disk."""
    cases = []

    def add(*args, **kwargs):
        cases.append(Case(*args, **kwargs))

    # LooksLikeScCache: one folder called cache.
    add(
        "flat cache with a base.ini",
        "cache",
        ["cache/base.ini", "cache/ships_desc_enhancements.ini"],
        "cache",
        expect="1",
    )
    add(
        "flat cache with only a dataforge folder",
        "cache",
        ["cache/dataforge/a.xml"],
        "cache",
        expect="1",
    )
    for channel in CHANNELS:
        add(
            f"cache folder holding {channel}\\cache",
            "cache",
            [f"cache/{channel}/cache/dataforge/a.xml"],
            "cache",
            expect="1",
        )
    add(
        "unrelated files only", "cache", ["cache/thing.dat", "cache/sub/x.bin"], "cache", expect="0"
    )
    add("empty folder", "cache", ["cache/"], "cache", expect="0")
    add("missing folder", "cache", [], "cache", expect="0")
    add(
        "a channel folder with no cache folder in it",
        "cache",
        ["cache/LIVE/other.txt"],
        "cache",
        expect="0",
    )
    add("a file named like a channel", "cache", ["cache/LIVE"], "cache", expect="0")
    add("a folder called base.ini", "cache", ["cache/base.ini/x.txt"], "cache", expect="0")
    add("a file called dataforge", "cache", ["cache/dataforge"], "cache", expect="0")
    add(
        "look-alike names",
        "cache",
        ["cache/base.ini.bak", "cache/dataforge2/a", "cache/LIVE2/cache/b"],
        "cache",
        expect="0",
    )

    # CleanCachedData in an ordinary data folder.
    flat = [
        "{r}/cache/base.ini",
        "{r}/cache/ships_desc_enhancements.ini",
        "{r}/cache/dataforge/a.xml",
    ]
    keep = [
        "{r}/logs/crash_1.log",
        "{r}/overrides.ini",
        "{r}/LIVE/keepme.txt",
        "{r}/Misc/cache/keep.txt",
    ]
    for name, root, override in (
        ("default data folder", "Docs/Smart Citizen", False),
        ("data folder from the registry", "MyData", True),
    ):
        add(
            name + ": caches go, the rest stays",
            "clean",
            _sc_files(root) + [e.format(r=root) for e in flat + keep],
            root,
            gone=_channel_caches(root) + [f"{root}/cache"],
            override=override,
            log="Cleaning cached data from:",
        )
    add(
        "another program's cache folder stays",
        "clean",
        [
            "MyData/LIVE/cache/base.ini",
            "MyData/LIVE/user.ini",
            "MyData/cache/thing.dat",
            "MyData/cache/sub/x.bin",
        ],
        "MyData",
        gone=["MyData/LIVE/cache"],
        override=True,
        log="Leaving",
    )
    add(
        "flat cache with only a dataforge folder goes",
        "clean",
        ["MyData/cache/dataforge/a.xml"],
        "MyData",
        gone=["MyData/cache"],
        override=True,
    )
    add(
        "flat cache holding channel caches goes",
        "clean",
        ["MyData/cache/LIVE/cache/dataforge/a.xml", "MyData/cache/PTU/cache/dataforge/b.xml"],
        "MyData",
        gone=["MyData/cache"],
        override=True,
    )
    add(
        "an empty cache folder stays",
        "clean",
        ["MyData/cache/"],
        "MyData",
        override=True,
        log="Leaving",
    )
    add(
        "a data folder that is not there is skipped without a word",
        "clean",
        [],
        "Gone",
        override=True,
        log="",
    )

    # CleanCachedData where the data folder is not safe to delete in.
    refused = ["{r}/cache/base.ini", "{r}/LIVE/cache/base.ini", "{r}/LIVE/user.ini"]
    add(
        "data folder is Documents",
        "clean",
        [e.format(r="Docs") for e in refused],
        "Docs",
        override=True,
        log="Not cleaning cached data under",
    )
    add(
        "data folder holds Star Citizen game files",
        "clean",
        ["SCRoot/LIVE/Data.p4k"] + [e.format(r="SCRoot") for e in refused],
        "SCRoot",
        override=True,
        log="it holds Star Citizen game files",
    )
    add(
        "data folder is the registered Star Citizen install",
        "clean",
        [e.format(r="Games") for e in refused],
        "Games",
        override=True,
        sc_root="Games",
        log="it is the Star Citizen install folder",
    )
    add(
        "data folder contains the registered Star Citizen install",
        "clean",
        ["Games/StarCitizen/"] + [e.format(r="Games") for e in refused],
        "Games",
        override=True,
        sc_root="Games/StarCitizen",
        log="it contains the Star Citizen install",
    )
    add(
        "data folder is the folder Smart Citizen is installed in",
        "clean",
        [e.format(r="App") for e in refused],
        "App",
        override=True,
        log="it is the folder Smart Citizen is installed in",
    )

    # CleanPerChannelCaches on its own.
    add(
        "per-channel caches, and only those",
        "channels",
        _sc_files("MyData")
        + ["MyData/Other/cache/x.txt", "MyData/PTU2/cache/x.txt", "MyData/cache/base.ini"],
        "MyData",
        gone=_channel_caches("MyData"),
    )
    add(
        "per-channel caches in Documents",
        "channels",
        ["Docs/LIVE/cache/base.ini", "Docs/PTU/cache/base.ini"],
        "Docs",
        log="Not cleaning per-channel caches under",
    )

    # The wipe, DeleteOwnedSubpaths.
    owned = (
        _sc_files("{r}")
        + [
            "{r}/cache/base.ini",
            "{r}/cache/dataforge/a.xml",
            "{r}/user.ini",
            "{r}/overrides.ini",
            "{r}/base.ini",
        ]
        + ["{r}/logs/crash_1.log", "{r}/logs/smart_citizen_1.log"]
    )
    add(
        "wipe: what Smart Citizen made goes, the rest stays",
        "wipe",
        [e.format(r="MyData") for e in owned]
        + ["MyData/logs/other.log", "MyData/Notes/readme.txt"],
        "MyData",
        gone=[f"MyData/{p}" for p in (*CHANNELS, "cache", "user.ini", "overrides.ini", "base.ini")]
        + ["MyData/logs/crash_1.log", "MyData/logs/smart_citizen_1.log"],
    )
    add(
        "wipe: another program's cache folder stays, and so does the data folder",
        "wipe",
        [
            "MyData/LIVE/user.ini",
            "MyData/user.ini",
            "MyData/cache/thing.dat",
            "MyData/cache/sub/x.bin",
        ],
        "MyData",
        gone=["MyData/LIVE", "MyData/user.ini"],
        log="Leaving",
    )
    add(
        "wipe: only another program's cache folder, nothing goes",
        "wipe",
        ["MyData/cache/thing.dat"],
        "MyData",
    )
    add("wipe: an empty cache folder stays", "wipe", ["MyData/cache/"], "MyData", log="Leaving")
    add(
        "wipe: a flat cache that was all there was takes its folder too",
        "wipe",
        ["MyData/cache/base.ini"],
        "MyData",
        gone=["MyData/cache", "MyData"],
    )
    add(
        "wipe: a flat cache with only a dataforge folder goes",
        "wipe",
        ["MyData/cache/dataforge/a.xml"],
        "MyData",
        gone=["MyData/cache", "MyData"],
    )
    add(
        "wipe: a flat cache holding channel caches goes",
        "wipe",
        ["MyData/cache/LIVE/cache/dataforge/a.xml"],
        "MyData",
        gone=["MyData/cache", "MyData"],
    )
    add(
        "wipe: Documents is refused",
        "wipe",
        ["Docs/LIVE/user.ini", "Docs/cache/base.ini"],
        "Docs",
        notes="not cleaned because it is the Documents folder",
    )
    add(
        "wipe of a cache folder: only the channel folders go",
        "wipe-cache-root",
        ["CacheDir/LIVE/cache/dataforge/a.xml", "CacheDir/cache/thing.dat", "CacheDir/other.txt"],
        "CacheDir",
        gone=["CacheDir/LIVE"],
    )

    # UnsafeDeleteRootReason on its own, for the folders no tree under tmp_path
    # can be: the issue's own example, a whole drive, and network paths. The
    # check reads each of them as text and returns before any disk or network
    # access, and nothing deletes in them.
    for name, outside, reason in (
        ("a drive root", "Z:\\", "it is a whole drive"),
        ("a drive", "Z:", "it is a whole drive"),
        ("the top of a network share", r"\\server\share", "it is the top of a network share"),
        (
            "Documents through an admin share",
            r"\\localhost\C$\Users\Someone\Documents",
            "it is a whole drive shared over the network",
        ),
        ("a device path", r"\\?\C:\Data", "it is a special device path"),
    ):
        add(f"reason: {name}", "reason", [], "", outside=outside, expect=reason)
    add("reason: an ordinary folder", "reason", ["Data/"], "Data", expect="")

    # The install folder (#454): the guard (NewInstallDir) on the folder the case
    # names, then the real [InstallDelete] entries, each behind its real Check, in
    # the folder the guard picked, as in Setup. "whole" empties that folder,
    # "narrow" deletes only Smart Citizen's own names there. A narrow case that
    # stands for an upgrade names its folder as the previous install's, which the
    # guard never moves.
    internal = ["_internal/base_library.zip", "_internal/PyQt6/Qt6/bin/Qt6Core.dll"]
    uninstaller = ["unins000.exe", "unins000.dat"]

    def under(root, items):
        return [f"{root}/{item}" for item in items]

    def top(root, items):
        """What emptying *root* deletes: its top-level items."""
        return sorted({f"{root}/{item.split('/')[0]}" for item in items})

    def moved_away(name, entries):
        # Inst is not an install, so the guard gives it a folder of its own, which
        # is missing: it is emptied whole, and nothing in Inst is deleted.
        install(name, entries, "whole", moved=f"Inst/{_OWN}")

    def install(name, entries, expect, target="Inst", **kwargs):
        log = _INSTALL_LOG[expect]
        add(f"install: {name}", "install", entries, target, expect=expect, log=log, **kwargs)

    # Every layout a release has installed is emptied, and so is a folder with
    # nothing in it yet.
    install("a missing folder is emptied", [], "whole")
    install("an empty folder is emptied", ["Inst/"], "whole")
    for name, items in (
        ("2.x", ["SmartCitizen.exe", *internal, *uninstaller]),
        ("1.x", ["SmartCitizen-v1.4.2.exe", *internal, *uninstaller]),
        (
            "0.1.1 to 0.6, flat",
            ["SCLocalizationEditor-v0.1.0.exe", "SCLocalizationEditor-v0.6.0.exe", *uninstaller],
        ),
        (
            "0.7 to 0.8, with a flat program left",
            ["SCLocalizationEditor-v0.6.0.exe", "SCLocalizationEditor-v0.8.2.exe", *internal]
            + uninstaller,
        ),
        ("0.1.0", ["SCLocalizationEditor.exe", *internal]),
        ("leftovers with no program", [*internal, *uninstaller]),
        ("any case", ["SMARTCITIZEN.EXE", "_INTERNAL/x.pyd", "UNINS000.DAT"]),
    ):
        install(f"{name} is emptied", under("Inst", items), "whole", gone=top("Inst", items))
    install(
        "an _internal link is removed, not entered",
        ["Inst/SmartCitizen.exe", "Elsewhere/keep.txt"],
        "whole",
        gone=["Inst/SmartCitizen.exe", "Inst/_internal"],
        links=[("Inst/_internal", "Elsewhere")],
    )

    # Anything else in the previous install's folder: only Smart Citizen's own
    # names go.
    own = ["SmartCitizen.exe", "_internal"]
    install(
        "a shared folder keeps everything that is not Smart Citizen's",
        under("Inst", ["SmartCitizen.exe", *internal, *uninstaller, "Game/game.exe"])
        + under("Inst", ["Game/data.pak", "notes.txt", "Other.exe"])
        + under("Inst", ["unins001.exe", "unins001.dat"]),
        "narrow",
        gone=under("Inst", own),
        previous="Inst",
    )
    programs = [
        "SmartCitizen.exe",
        "SmartCitizen-v1.4.2.exe",
        "SCLocalizationEditor.exe",
        "SCLocalizationEditor-v0.6.0.exe",
    ]
    install(
        "every version's program goes, in any folder",
        under("Inst", [*programs, "Game/game.exe"]),
        "narrow",
        gone=under("Inst", programs),
        previous="Inst",
    )
    install(
        "an old install among other programs keeps its uninstaller",
        under("Inst", ["SmartCitizen-v1.4.2.exe", *internal, *uninstaller, "Game/x.exe"]),
        "narrow",
        gone=under("Inst", ["SmartCitizen-v1.4.2.exe", "_internal"]),
        previous="Inst",
    )
    data = "Docs/Smart Citizen"
    install(
        "the data folder used as the install folder keeps the data",
        under(data, ["SmartCitizen.exe", *internal, "LIVE/user.ini"])
        + under(data, ["LIVE/backups/global.ini.bak_1", "logs/crash_1.log"]),
        "narrow",
        target=data,
        gone=under(data, own),
        previous=data,
    )
    install(
        "the data folder with only loose files keeps them",
        under(data, ["SmartCitizen.exe", "notes.txt"]),
        "narrow",
        target=data,
        gone=[f"{data}/SmartCitizen.exe"],
        previous=data,
    )
    named = _OWN
    install(
        "a folder named Smart Citizen keeps loose files Smart Citizen did not install",
        under(named, ["SmartCitizen.exe", *internal, *uninstaller, "notes.txt", "desktop.ini"]),
        "narrow",
        target=named,
        gone=under(named, own),
        previous=named,
    )
    legacy = "SC Localization Editor"
    install(
        "a folder named SC Localization Editor keeps loose files",
        under(legacy, ["SCLocalizationEditor-v0.8.2.exe", *internal, "old.log"]),
        "narrow",
        target=legacy,
        gone=under(legacy, ["SCLocalizationEditor-v0.8.2.exe", "_internal"]),
        previous=legacy,
    )
    install(
        "a folder named Smart Citizen keeps another program's folder",
        under(named, ["SmartCitizen.exe", *internal, "Mods/m.pak"]),
        "narrow",
        target=named,
        gone=under(named, own),
        previous=named,
    )
    install(
        "a folder named Smart Citizen keeps a link and what it points at",
        under(named, ["SmartCitizen.exe", *internal]) + ["Saves/save.dat"],
        "narrow",
        target=named,
        gone=under(named, own),
        links=[(f"{named}/Saves", "Saves")],
        previous=named,
    )
    install(
        "the previous install's folder is not moved, and keeps loose files",
        under(named, [*internal, "notes.txt"]),
        "narrow",
        target=named,
        gone=[f"{named}/_internal"],
        previous=named,
    )
    # No case has an install folder that is itself a link. A Setup built with
    # Inno Setup 6.7.0 or newer turns on Windows' RedirectionGuard where the
    # system has it (Windows 11, Windows 10 22H2), which stops it following a
    # junction a normal user made, so such a folder cannot be listed and nothing
    # is deleted through it. With an older compiler, or on older Windows, the
    # folder reads like any other. The result depends on both, and neither way
    # deletes anything Smart Citizen did not install.
    install(
        "a link in the install folder stays, and so does what it points at",
        ["Inst/SmartCitizen.exe", "Lib/book.txt"],
        "narrow",
        gone=["Inst/SmartCitizen.exe"],
        links=[("Inst/Library", "Lib")],
        previous="Inst",
    )
    install(
        "a portable copy beside the install stays, with its data",
        under("Inst", ["SmartCitizen.exe", *internal])
        + under("Inst", ["SmartCitizen-Portable-v2.3.1.exe", "data/config.json"]),
        "narrow",
        gone=under("Inst", own),
        previous="Inst",
    )
    # Another program's leftover uninstaller is not Smart Citizen's: the guard
    # moves away from it, and the folder is not emptied even as the previous
    # install's.
    leftovers = under("Inst", uninstaller)
    moved_away("another program's leftover uninstaller is not an install", leftovers)
    install(
        "another program's leftover uninstaller is not emptied",
        leftovers,
        "narrow",
        previous="Inst",
    )

    # The guard: a folder that holds files Smart Citizen did not install gets a
    # Smart Citizen folder of its own, unless it is the previous install's. A new
    # folder is missing, so it is emptied whole, which deletes nothing.
    moved_away(
        "a folder of other files gets its own folder", ["Inst/Game/game.exe", "Inst/readme.txt"]
    )
    install(
        "the previous install's folder is never moved",
        ["Inst/readme.txt"],
        "narrow",
        previous="Inst",
    )
    moved_away(
        "a loose old program among another app's files does not keep Setup there",
        under("Inst", ["SCLocalizationEditor-v0.7.0.exe", "OtherApp.exe", "_internal/x.pyd"]),
    )
    install(
        "a Smart Citizen folder of other files gets one too",
        ["D2/other.txt", f"D2/{_OWN}/LIVE/user.ini"],
        "whole",
        target="D2",
        moved=f"D2/{_OWN}/{_OWN}",
    )
    install(
        "an install in the folder it would add is found, and emptied",
        ["G/game.exe", f"G/{_OWN}/SmartCitizen.exe"],
        "whole",
        target="G",
        moved=f"G/{_OWN}",
        gone=[f"G/{_OWN}/SmartCitizen.exe"],
    )
    nested = ["X"]
    while len(nested) < 4:
        nested.append(f"{nested[-1]}/{_OWN}")
    install(
        "the guard adds its folder at most three times",
        [f"{folder}/a.txt" for folder in nested],
        "narrow",
        target="X",
        moved=nested[-1],
    )

    # Look-alike names: none of them is Smart Citizen's, beside an install (the
    # narrow entries leave it) or on its own (the guard moves away from it). The
    # last five have exactly a versioned program name's length (the prefix, five
    # characters, .exe), so only IsVersionedProgramName's own checks turn them
    # away: Viewer and vXYZab fail the digit and the dot tests, 1-4-2 and 0-8-2
    # only the dot test, and OtherProgram-v1.2.3.exe only the prefix.
    # SmartCitizen-v1.4.2.exe.bak passes all but the length test, and
    # SCLocalizationEditor-v0.6.0.txt all but the .exe test.
    for name in (
        "SmartCitizenVault.exe",
        "SmartCitizen-Vault.exe",
        "SmartCitizen.exe.bak",
        "SmartCitizen-v1.4.2.exe.bak",
        "SmartCitizen-Portable-v2.3.1.exe",
        "SmartCitizen-0.9.4-Setup.exe",
        "SCLocalizationEditor-0.8.2-Setup.exe",
        "SCLocalizationEditor-v0.1.1-Setup.exe",
        "SCLocalizationEditor-0.1.0-installer.exe",
        "SCLocalizationEditor-v0.6.0.txt",
        "unins001.exe",
        "unins000.txt",
        "uninstall notes.txt",
        "internal/x",
        "_internal.old/x",
        "SmartCitizen-v1.4.2.exe/x",
        "SmartCitizen-Viewer.exe",
        "SCLocalizationEditor-vXYZab.exe",
        "SmartCitizen-v1-4-2.exe",
        "SCLocalizationEditor-v0-8-2.exe",
        "OtherProgram-v1.2.3.exe",
    ):
        install(
            f"{name} stays beside an install",
            ["Inst/SmartCitizen.exe", f"Inst/{name}"],
            "narrow",
            gone=["Inst/SmartCitizen.exe"],
            previous="Inst",
        )
        moved_away(f"{name} on its own is not an install", [f"Inst/{name}"])
    # Dots in their places and a letter for a digit: only the digit test turns
    # these away. The ?.?.? entries delete them beside an install (Windows lets a
    # ? match any character), so only the guard shows the test: on its own, such
    # a file must be moved away from.
    for name in ("SmartCitizen-v1.4.x.exe", "SCLocalizationEditor-v0.8.x.exe"):
        moved_away(f"{name} on its own is not an install", [f"Inst/{name}"])
    # ScanInstallDir must not count a folder of that name as the program.
    moved_away("a folder named SmartCitizen.exe is not an install", ["Inst/SmartCitizen.exe/x"])

    # Setup asks the delete Check on the Preparing page and again just before the
    # delete, and in between MigrateUserDocsFolder can rename the old data folder
    # into an install folder that was still missing. A missing folder is emptied
    # whole, so an answer kept from the first ask (a cache at any level) would
    # delete the data moved in. The case asks on a missing folder, puts a data
    # file in it, then runs the deletes: the file must stay, and the second ask
    # must log the narrow answer.
    add(
        "install refill: data moved in after the first Check is kept",
        "install-refill",
        [],
        "Docs/Smart Citizen",
        expect="whole",
    )

    # The install folder checks on their own, for folders no tree under tmp_path
    # can be. Each is read as text only (a folder that is not a full path is
    # never listed), and nothing deletes in it.
    not_full = "it is not a full folder path or Setup could not list what is in it"
    add(
        "install reason: a relative folder is never Smart Citizen's own",
        "install-reason",
        [],
        "",
        outside="Inst",
        expect=f"{not_full} > Inst\\{_OWN}\\{_OWN}\\{_OWN} > not too long",
    )
    # One Smart Citizen folder brings it to exactly Setup's 240 characters, and a
    # second would pass them, so the guard stops there and says it stopped for
    # length (an interactive Setup then asks for another folder).
    long_folder = "L" * (_MAX_DIR - len("\\" + _OWN))
    add(
        "install reason: the guard stops at Setup's 240 characters",
        "install-reason",
        [],
        "",
        outside=long_folder,
        expect=f"{not_full} > {long_folder}\\{_OWN} > too long",
    )
    # One character more and not even one fits: the folder is kept as chosen.
    longer = long_folder + "L"
    add(
        "install reason: a folder too long for a folder of its own is kept, too long",
        "install-reason",
        [],
        "",
        outside=longer,
        expect=f"{not_full} > {longer} > too long",
    )
    # The previous install's folder is kept before its length is looked at, so an
    # upgrade there is never asked for another folder.
    add(
        "install reason: the previous install's folder is kept, however long",
        "install-reason",
        [],
        "",
        outside=longer,
        previous=longer,
        expect=f"{not_full} > {longer} > not too long",
    )

    for i, case in enumerate(cases):
        case.base = t / f"case{i:02d}"
    return cases


def _make_trees(cases):
    """Make the folders and files of every case."""
    for case in cases:
        for folder in (case.docs, case.app):
            (case.base / folder).mkdir(parents=True, exist_ok=True)
        for entry in case.entries:
            path = case.base / entry.rstrip("/")
            if entry.endswith("/"):
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("x", encoding="utf-8")
        for link, target in case.links:
            import _winapi  # Windows only, like the probe itself

            (case.base / target).mkdir(parents=True, exist_ok=True)
            (case.base / link).parent.mkdir(parents=True, exist_ok=True)
            _winapi.CreateJunction(str(case.base / target), str(case.base / link))


# What the cut-out code reads from the machine, as fakes. FakeReg answers only
# the values the code reads, so a changed registry read fails the test instead
# of reading this machine's registry, and Personal always answers (with a folder
# under the test's tmp_path), so no default data folder can resolve to the real
# Documents. The log goes into a string the case's result line carries back.
_FAKES = """var
  FakePersonal, FakeOverride, FakeScRoot, FakeAppDir, FakeLogText: String;

function FakeReg(const SubKey, Name: String; var Data: String): Boolean;
begin
  Result := False;
  if (Name = 'Personal') and (Pos('Shell Folders', SubKey) > 0) then
  begin
    Data := FakePersonal;
    Result := True;
  end
  else if (Name = 'user_data_dir') and (FakeOverride <> '') then
  begin
    Data := FakeOverride;
    Result := True;
  end
  else if (Name = 'sc_install_root') and (FakeScRoot <> '') and
          (Pos('SC Localization Editor', SubKey) = 0) then
  begin
    Data := FakeScRoot;
    Result := True;
  end;
end;

function FakeApp(): String;
begin
  Result := FakeAppDir;
end;

procedure FakeLog(const S: String);
begin
  FakeLogText := FakeLogText + S + ' | ';
end;

procedure FakeSet(const Docs, DataOverride, ScRoot, App: String);
begin
  FakePersonal := Docs;
  FakeOverride := DataOverride;
  FakeScRoot := ScRoot;
  FakeAppDir := App;
  FakeLogText := '';
end;

function FakeReport(const Notes: String): String;
var
  N: String;
begin
  N := Notes;
  StringChangeEx(N, #13#10, ' / ', True);
  Result := N + #9 + FakeLogText;
end;
"""

# One function per kind of case, each taking every input, so a case is one line.
_CASE_FUNCTIONS = """function CaseCache(const Dir: String): String;
begin
  if LooksLikeScCache(Dir) then
    Result := '1'
  else
    Result := '0';
end;

function CaseClean(const Docs, DataOverride, ScRoot, App: String): String;
begin
  FakeSet(Docs, DataOverride, ScRoot, App);
  CleanCachedData();
  Result := FakeReport('');
end;

function CaseChannels(const Docs, DataOverride, ScRoot, App, Root: String): String;
begin
  FakeSet(Docs, DataOverride, ScRoot, App);
  CleanPerChannelCaches(Root);
  Result := FakeReport('');
end;

function CaseWipe(const Docs, ScRoot, App, Root: String; const IsCacheRoot: Boolean): String;
begin
  FakeSet(Docs, '', ScRoot, App);
  Result := FakeReport(DeleteOwnedSubpaths(Root, IsCacheRoot));
end;

function CaseReason(const Docs, App, Dir: String): String;
begin
  FakeSet(Docs, '', '', App);
  Result := UnsafeDeleteRootReason(Dir);
end;

function CaseInstall(const Docs, Dir, Previous: String): String;
var
  Mode, Own: String;
  TooLong: Boolean;
begin
  { The folder page's guard, then the Check and the deletes in the folder it
    picked, which Setup then installs in. }
  FakeSet(Docs, '', '', Dir);
  Own := NewInstallDir(Dir, Previous, TooLong);
  FakeAppDir := Own;
  if InstallDirMayBeEmptied() then
    Mode := 'whole'
  else
    Mode := 'narrow';
  RunInstallDelete();
  Result := FakeReport(Mode + ' > ' + Own);
end;

function CaseInstallRefill(const Docs, Dir, Data: String): String;
var
  First: String;
begin
  { The Check on the Preparing page, then Data put in the install folder Dir
    (as MigrateUserDocsFolder can at ssInstall), then the deletes, which ask
    the Check again. }
  FakeSet(Docs, '', '', Dir);
  if InstallDirMayBeEmptied() then
    First := 'whole'
  else
    First := 'narrow';
  ForceDirectories(ExtractFileDir(Data));
  SaveStringToFile(Data, 'x', False);
  RunInstallDelete();
  if FileExists(Data) then
    Result := FakeReport(First + ' > kept')
  else
    Result := FakeReport(First + ' > deleted');
end;

function CaseInstallReason(const Dir, Previous: String): String;
var
  TooLong: Boolean;
begin
  Result := WholeInstallDirReason(Dir) + ' > ' + NewInstallDir(Dir, Previous, TooLong);
  if TooLong then
    Result := Result + ' > too long'
  else
    Result := Result + ' > not too long';
end;
"""

_ROOTS = (
    "CleanCachedData",
    "CleanPerChannelCaches",
    "DeleteOwnedSubpaths",
    "LooksLikeScCache",
    "UnsafeDeleteRootReason",
    "InstallDirMayBeEmptied",
    "NewInstallDir",
)


def _cut_routines(source):
    """The routines the cases call, and everything they call in turn, verbatim
    out of *source* in file order (with the forward declaration of any that has
    one), their registry reads, ``{app}`` and log pointed at the fakes."""
    definitions = _definitions(source)
    needed, todo = set(), list(_ROOTS)
    while todo:
        name = todo.pop()
        if name not in needed:
            needed.add(name)
            code = _NOT_CODE.sub(" ", definitions[name])
            todo += [n for n in re.findall(r"\b(\w+)\(", code) if n in definitions]
    pieces = [(source.index(definitions[n]), definitions[n]) for n in needed]
    for match in _FORWARD.finditer(source):
        if match.group(1) in needed:
            pieces.append((match.start(), match.group(0)))
    text = "\n\n".join(piece for _, piece in sorted(pieces))
    text = re.sub(r"RegQueryStringValue\(HKCU,\s*", "FakeReg(", text)
    text = text.replace("ExpandConstant('{app}')", "FakeApp()")
    text = re.sub(r"(?<![A-Za-z])Log\(", "FakeLog(", text)
    code = _NOT_CODE.sub(" ", text)
    assert "RegQueryStringValue" not in code, "cut-out code still reads the registry"
    assert "{app}" not in text.replace("FakeApp()", ""), "cut-out code still expands {app}"
    assert not re.search(r"(?<![A-Za-z])Log\(", code), "cut-out code still writes the Setup log"
    return text


def _constants(source):
    lines = []
    names = (
        "SCRegNode",
        "SCLegacyRegNode",
        "ScChannelCount",
        "ScMarkerCount",
        "AppFolderName",
        "MaxInstallDirLength",
    )
    for name in names:
        match = re.search(rf"^  {name} = [^\n]*;$", source, re.M)
        assert match, f"const {name} not found in installer.iss"
        lines.append(match.group(0))
    return "const\n" + "\n".join(lines)


def _install_delete_procedure(source):
    """``RunInstallDelete``: installer.iss's own ``[InstallDelete]`` entries, in
    their order, each behind its Check, as the call Setup makes for them, in the
    fake install folder. So the probe and the pin cannot drift apart."""
    calls = []
    for entry in _section(source, "InstallDelete"):
        match = _INSTALL_DELETE_ENTRY.match(entry)
        assert match, f"the probe cannot run this [InstallDelete] entry: {entry}"
        path = pascal_string("\\" + match["name"])
        subdirs = "True" if match["type"] == "filesandordirs" else "False"
        # The call Setup's ProcessInstallDeleteEntries makes (IsDir False,
        # DeleteFiles True); script DelTree strips read-only and does not
        # enter reparse points, like it (checked in is-6_6_0 and main).
        call = f"DelTree(FakeApp() + {path}, False, True, {subdirs});"
        calls.append(f"  if {match['check']}() then {call}" if match["check"] else f"  {call}")
    return "procedure RunInstallDelete();\nbegin\n" + "\n".join(calls) + "\nend;\n"


def _steps(cases, tree):
    """The Pascal that runs each case and puts its result line in ``Lines``.
    Every path it names is inside *tree*, apart from the paths of the reason and
    install-reason cases (*outside*, and *previous* in an install-reason case),
    which the checks only read as text."""

    def p(relative, case):
        path = case.base / relative
        assert str(path).startswith(str(tree)), f"{path} is outside the test tree"
        return pascal_string(str(path))

    steps = []
    for i, case in enumerate(cases):
        # Only the checks on their own, which read a folder as text, may see an
        # outside path. A cleaner, the wipe or an install case pointed at one would
        # delete for real outside the tree.
        assert not case.outside or case.kind in _TEXT_ONLY_KINDS, (
            f"{case.name}: only a reason or install-reason case may name a path outside the tree"
        )
        target = pascal_string(case.outside) if case.outside else p(case.target, case)
        docs, app = p(case.docs, case), p(case.app, case)
        sc = p(case.sc_root, case) if case.sc_root else "''"
        override = target if case.override else "''"
        if not case.previous:
            previous = "''"
        elif case.kind in _TEXT_ONLY_KINDS:
            previous = pascal_string(case.previous)
        else:
            previous = p(case.previous, case)
        data = p(f"{case.target}/{_REFILL_DATA}", case) if case.kind == "install-refill" else ""
        call = {
            "cache": f"CaseCache({target})",
            "clean": f"CaseClean({docs}, {override}, {sc}, {app})",
            "channels": f"CaseChannels({docs}, {override}, {sc}, {app}, {target})",
            "wipe": f"CaseWipe({docs}, {sc}, {app}, {target}, False)",
            "wipe-cache-root": f"CaseWipe({docs}, {sc}, {app}, {target}, True)",
            "reason": f"CaseReason({docs}, {app}, {target})",
            # The folder chosen on the install folder page. The deletes run in the
            # folder the guard picks from it.
            "install": f"CaseInstall({docs}, {target}, {previous})",
            "install-refill": f"CaseInstallRefill({docs}, {target}, {data})",
            "install-reason": f"CaseInstallReason({target}, {previous})",
        }[case.kind]
        steps.append(f"  Lines[{i}] := {call};")
    return "\n".join(steps)


def _probe_script(source, cases, tree, out):
    return f"""[Setup]
AppName=Installer wipe safety probe
AppVersion=1.0
CreateAppDir=no
Uninstallable=no
PrivilegesRequired=lowest
OutputDir={out}
OutputBaseFilename=probe

[Code]
{_constants(source)}

{_FAKES}
{{ routines: begin }}
{_cut_routines(source)}

{_install_delete_procedure(source)}
{_CASE_FUNCTIONS}
{{ routines: end }}

function InitializeSetup(): Boolean;
var
  Lines: TArrayOfString;
begin
  SetArrayLength(Lines, {len(cases)});
  FakeSet({pascal_string(str(tree / "NoDocs"))}, '', '', {pascal_string(str(tree / "NoApp"))});
{{ steps: begin }}
{_steps(cases, tree)}
{{ steps: end }}
  SaveStringsToFile({pascal_string(str(out / "result.txt"))}, Lines, False);
  Result := False;
end;
"""


def _problems(cases, lines):
    """What is wrong with the probe's result *lines*, as one sentence each."""
    if len(lines) != len(cases):
        return [f"the probe saved {len(lines)} result lines for {len(cases)} cases"]
    problems = []
    for case, line in zip(cases, lines):
        if case.kind == "cache":
            if line != case.expect:
                problems.append(
                    f"{case.name}: LooksLikeScCache said {line!r}, expected {case.expect!r}"
                )
            continue
        if case.kind == "reason":
            if line != case.expect:
                problems.append(
                    f"{case.name}: UnsafeDeleteRootReason said {line!r}, expected {case.expect!r}"
                )
            continue
        if case.kind == "install-reason":
            if line != case.expect:
                problems.append(
                    f"{case.name}: the install folder checks said {line!r}, "
                    f"expected {case.expect!r}"
                )
            continue
        notes, _, log = line.partition("\t")
        if case.kind == "install-refill":
            first, _, data = notes.partition(" > ")
            if first != case.expect:
                problems.append(
                    f"{case.name}: the first Check said {first!r}, expected {case.expect!r}"
                )
            if data != "kept" or not (case.base / case.target / _REFILL_DATA).exists():
                problems.append(
                    f"{case.name}: the data put in after the first Check was deleted, so the "
                    "Check just before the delete was not asked afresh"
                )
            whole = log.find(_INSTALL_LOG["whole"])
            narrow = log.find(_INSTALL_LOG["narrow"])
            if not 0 <= whole < narrow:
                problems.append(
                    f"{case.name}: the log was {log!r}, expected the whole answer, "
                    "then the narrow one"
                )
        if case.kind == "install":
            mode, _, own = notes.partition(" > ")
            if mode != case.expect:
                problems.append(
                    f"{case.name}: the install folder was {mode!r}, expected {case.expect!r}"
                )
            want = case.base / (case.moved or case.target)
            if os.path.normcase(own) != os.path.normcase(str(want)):
                problems.append(f"{case.name}: the guard picked {own!r}, expected {str(want)!r}")
            for link, _target in case.links:
                if os.path.lexists(case.base / link) == (link in case.gone):
                    state = "is still there" if link in case.gone else "was deleted"
                    problems.append(f"{case.name}: the link {link} {state}")
        gone = [case.base / g for g in case.gone]
        for entry in case.entries:
            path = case.base / entry.rstrip("/")
            should_go = any(path == g or g in path.parents for g in gone)
            if path.exists() == should_go:
                problems.append(
                    f"{case.name}: {entry} {'is still there' if should_go else 'was deleted'}"
                )
        problems += [
            f"{case.name}: {g} is still there" for g in case.gone if (case.base / g).exists()
        ]
        if case.kind.startswith("wipe"):
            if (case.notes == "" and notes != "") or case.notes not in notes:
                problems.append(
                    f"{case.name}: the summary was {notes!r}, expected {case.notes or 'nothing'!r}"
                )
        if case.log is not None and (log != "" if case.log == "" else case.log not in log):
            problems.append(f"{case.name}: the log was {log!r}, expected {case.log or 'nothing'!r}")
    return problems


_KINDS = (
    "cache",
    "clean",
    "channels",
    "wipe",
    "wipe-cache-root",
    "reason",
    "install",
    "install-refill",
    "install-reason",
)


@pytest.mark.parametrize("kind", _KINDS)
def test_only_the_text_checks_may_name_a_path_outside_the_tree(tmp_path, kind):
    # Every kind the cases use is listed here, so a new one is checked too.
    assert {case.kind for case in _cases(tmp_path)} <= set(_KINDS)
    # Pinned here, not read from _steps: a kind added to _TEXT_ONLY_KINDS could
    # name a folder outside the tree, so it has to be reviewed and added here.
    assert _TEXT_ONLY_KINDS == ("reason", "install-reason")
    case = Case("outside", kind, [], "", outside="Z:\\")
    case.base = tmp_path / "case00"
    if kind in _TEXT_ONLY_KINDS:
        # Read as text by a check that deletes nothing.
        assert pascal_string("Z:\\") in _steps([case], tmp_path)
        return
    with pytest.raises(AssertionError, match="may name a path outside the tree"):
        _steps([case], tmp_path)


def test_folder_deletes_in_compiled_installer_code(tmp_path):
    # Before the trees, which make junctions: where Inno Setup is missing the test
    # skips (or fails under CI) without touching the file system.
    require_iscc()
    tree = tmp_path / "tree"
    out = tmp_path / "out"
    cases = _cases(tree)
    _make_trees(cases)
    script = _probe_script(_installer_source(), cases, tree, out)
    lines = run_probe(script, tmp_path, out)
    problems = _problems(cases, lines)
    assert not problems, "\n".join(problems)
