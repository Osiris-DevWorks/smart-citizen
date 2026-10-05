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

The behaviour test cuts the real routines verbatim out of installer.iss, points
their registry reads, ``{app}`` and log at fakes, compiles them into a throwaway
setup with Inno Setup's ISCC, runs it silently against folders it deletes in
under ``tmp_path``, and checks which files are left. Nothing outside that tree
is deleted in: the only outside paths, a drive and network paths, go to the
delete check on its own, which reads them as text. It is skipped where Inno
Setup is not installed (under CI it fails instead, see ``tests/inno_setup.py``)
or an Application Control policy refuses to run the unsigned probe. GitHub's Windows
runner image ships Inno Setup 6, so it runs in CI as well as on a developer
machine that has Inno Setup. The text checks run everywhere. They are structural
tripwires on the shape of each guard (see the note above them), and the compiled
test is the semantic check.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import pytest

# The app's channel list, so a channel added there but not to the installer's
# checks fails here.
from src.utils.install_scanner import SC_CHANNELS as CHANNELS
from tests.inno_setup import pascal_string, run_probe

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


# The delete entries outside [Code]. They name only what a previous install put in
# the app folder (the exe and PyInstaller's _internal), never a wildcard over the
# whole folder, which emptied any existing folder the user picked (#454).
_INSTALL_DELETE = [
    'Type: filesandordirs; Name: "{app}\\_internal"',
    'Type: files; Name: "{app}\\SmartCitizen.exe"',
    'Type: files; Name: "{app}\\SmartCitizen-v*.exe"',
]


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


# -- Behaviour, in the compiled installer code ------------------------------------


@dataclass
class Case:
    """One folder tree and what a routine must leave of it. *entries* are made
    under the case's own folder (a trailing ``/`` makes a folder, otherwise a
    file), *gone* are the ones that must be deleted (a folder takes what is in
    it, the rest must still be there)."""

    name: str
    kind: str  # cache, clean, channels, wipe, wipe-cache-root or reason
    entries: list
    target: str  # the folder under test, relative to the case's folder
    gone: list = field(default_factory=list)
    override: bool = False  # the user_data_dir registry value is *target*
    sc_root: str = ""  # relative path saved as sc_install_root
    app: str = "App"  # the fake {app}
    docs: str = "Docs"  # the fake shell Documents folder
    expect: str = ""  # cache: "1" or "0", reason: the reason, "" for none
    outside: str = ""  # reason: a path outside the tree, which the check only reads as text
    notes: str = ""  # wipe: "" for no summary, else text it must hold
    log: object = None  # text the log must hold, "" for an empty log, None for either
    base: Path = None


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
"""

_ROOTS = (
    "CleanCachedData",
    "CleanPerChannelCaches",
    "DeleteOwnedSubpaths",
    "LooksLikeScCache",
    "UnsafeDeleteRootReason",
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
    for name in ("SCRegNode", "SCLegacyRegNode", "ScChannelCount", "ScMarkerCount"):
        match = re.search(rf"^  {name} = [^\n]*;$", source, re.M)
        assert match, f"const {name} not found in installer.iss"
        lines.append(match.group(0))
    return "const\n" + "\n".join(lines)


def _steps(cases, tree):
    """The Pascal that runs each case and puts its result line in ``Lines``.
    Every path it names is inside *tree*, apart from the reason cases' outside
    paths, which the check only reads as text."""

    def p(relative, case):
        path = case.base / relative
        assert str(path).startswith(str(tree)), f"{path} is outside the test tree"
        return pascal_string(str(path))

    steps = []
    for i, case in enumerate(cases):
        # Only the delete check on its own may see an outside path. A cleaner or
        # the wipe pointed at one would delete for real outside the tree.
        assert not case.outside or case.kind == "reason", (
            f"{case.name}: only a reason case may name a path outside the tree"
        )
        target = pascal_string(case.outside) if case.outside else p(case.target, case)
        docs, app = p(case.docs, case), p(case.app, case)
        sc = p(case.sc_root, case) if case.sc_root else "''"
        override = target if case.override else "''"
        call = {
            "cache": f"CaseCache({target})",
            "clean": f"CaseClean({docs}, {override}, {sc}, {app})",
            "channels": f"CaseChannels({docs}, {override}, {sc}, {app}, {target})",
            "wipe": f"CaseWipe({docs}, {sc}, {app}, {target}, False)",
            "wipe-cache-root": f"CaseWipe({docs}, {sc}, {app}, {target}, True)",
            "reason": f"CaseReason({docs}, {app}, {target})",
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
        notes, _, log = line.partition("\t")
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


@pytest.mark.parametrize("kind", ["cache", "clean", "channels", "wipe", "wipe-cache-root"])
def test_only_a_reason_case_may_name_a_path_outside_the_tree(tmp_path, kind):
    case = Case("outside", kind, [], "", outside="Z:\\")
    case.base = tmp_path / "case00"
    with pytest.raises(AssertionError, match="only a reason case"):
        _steps([case], tmp_path)


def test_cache_cleaning_and_the_wipe_in_compiled_installer_code(tmp_path):
    tree = tmp_path / "tree"
    out = tmp_path / "out"
    cases = _cases(tree)
    _make_trees(cases)
    script = _probe_script(_installer_source(), cases, tree, out)
    lines = run_probe(script, tmp_path, out)
    problems = _problems(cases, lines)
    assert not problems, "\n".join(problems)
