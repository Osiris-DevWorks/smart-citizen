"""#494: the messages for a DataForge cache folder that cannot be made, in
every language.

Two places report it, each in one box built from the keys below. The Config
tab, when the cache folder of the folder the user picked or reset to cannot
be made: ``config.cache_folder_refused`` with #490's
``extract.folder_refused_fix`` (not the advice to choose another cache
folder, which the user is doing right then), ``config.cache_folder_unreachable``
for a drive that is gone, ``config.cache_folder_unusable`` with Windows' own
reason for any other error (a name Windows does not take), and
``config.cache_folder_is_file``. And ``MainWindow._run_dataforge_extraction``,
when the cache folder cannot be made as an extraction starts:
``extract.cache_folder_refused`` with ``extract.folder_refused_fix_cache``,
``extract.cache_folder_unreachable``, and ``extract.cache_folder_unusable``
with Windows' own reason. Both pick the message with
``settings.cache_folder_failure``. These tests pin:

* which kind of message each Windows error gets: a drive that is not ready
  (WinError 21, which Python raises as a PermissionError) could not be
  reached, like a FileNotFoundError, a real PermissionError was refused,
  and anything else could not be used, with ``strerror`` as the reason, or
  the whole error when it has none. A path Windows cannot parse or one too
  long for it (WinError 161 and 206) could not be used either, though
  Python raises both as a FileNotFoundError;
* that both places show each Windows code in ``_WINERRORS`` as the
  classifier reads it, raised while the cache folder is made, so neither
  can read one of those codes its own way;
* which keys each case uses, with which arguments, recorded from real cases
  (a folder whose permissions deny new folders, a drive that is not there, a
  name Windows does not take, a file where the cache folder should be, a
  file picked as the cache folder). Every key under the ``config.cache_folder_``,
  ``extract.cache_folder_`` and ``extract.folder_refused`` prefixes is
  recorded, so a key the code stops using, or a new one, fails here too;
* every language: each key has a value, formats with the recorded arguments
  and leaves no placeholder behind, and the folder, and Windows' reason
  where there is one, each stand on a line of their own;
* provenance (languages/TRANSLATIONS.md): English has the source text in
  ``ht``, every other language an AI text in ``at`` and an empty ``ht``.

The Config tab is the real one, offscreen (``qapp``), the window a stub, and
the settings in ``tmp_profile``. conftest's ``english_ui`` keeps the active
language English while the keys are recorded.
"""
from __future__ import annotations

import json
import os
import re
import string
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import src.gui.config_tab as config_tab
import src.gui.main_window as main_window
from src.gui.config_tab import ConfigTab
from src.gui.main_window import MainWindow
from src.utils.pak_extractor import windows_reason
from src.utils.settings import (
    AppSettings,
    CACHE_FOLDER_REFUSED,
    CACHE_FOLDER_UNREACHABLE,
    CACHE_FOLDER_UNUSABLE,
    cache_folder_failure,
)
from tests.unusable_folder import missing_drive_folder, new_folders_denied

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("qapp", "english_ui")]

_LANGUAGES = Path(__file__).resolve().parent.parent / "languages"
_UI_FILES = sorted(_LANGUAGES.glob("*/ui.json"))

# The keys #494 added.
_KEYS = {
    "config.cache_folder_refused",
    "config.cache_folder_unreachable",
    "config.cache_folder_unusable",
    "config.cache_folder_is_file",
    "extract.cache_folder_refused",
    "extract.cache_folder_unreachable",
    "extract.cache_folder_unusable",
}
# Every tr() call under these is recorded: #494's keys, and #490's advice,
# to pin which one each refusal gets. A key added under one of them is
# recorded too, so the exact expectations below catch it.
_RECORDED = ("config.cache_folder_", "extract.cache_folder_", "extract.folder_refused")

# Placeholders that stand on a line of their own: after a line break, and
# followed by a blank line or nothing.
_OWN_LINE_FIELDS = ("folder", "reason")


def _on_its_own_line(text: str, field: str) -> bool:
    return re.search(r"\n\{" + field + r"\}(\n\n|$)", text) is not None


def _node(strings: dict, key: str) -> dict:
    """A key's ``{ht, at}`` entry in one ui.json, or {} when it is missing."""
    node = strings
    for part in key.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    return node if isinstance(node, dict) else {}


def _leaf(strings: dict, key: str) -> str:
    """A key's value in one ui.json: ``ht``, else ``at``, as tr() reads it."""
    node = _node(strings, key)
    return node.get("ht") or node.get("at") or ""


def _placeholders(text: str) -> set[str]:
    return {field for _lit, field, _spec, _conv in string.Formatter().parse(text) if field}


def _load(ui_json: Path) -> dict:
    return json.loads(ui_json.read_text(encoding="utf-8"))


def _type(tab, folder) -> None:
    """Type *folder* in the Config tab's cache folder field and press Enter.
    The tab saves only a folder the user typed (the field's modified flag,
    which typing sets and setText clears), so the flag is set here too."""
    tab.cache_dir_input.setText(str(folder))
    tab.cache_dir_input.setModified(True)
    tab.cache_dir_input.editingFinished.emit()


def _start_extraction() -> None:
    """The real start of a DataForge extraction, on a stub window."""
    me = MagicMock()
    me._close_committed = False
    me._forge_worker = None
    me._job_running.return_value = False
    assert MainWindow._run_dataforge_extraction(me) is False


def _reason_for(folder: Path) -> str:
    """Windows' own reason for refusing to make *folder*, as the app makes
    it, read here so the test holds in any Windows language."""
    with pytest.raises(OSError) as raised:
        folder.mkdir(parents=True, exist_ok=True)
    assert not isinstance(raised.value, (PermissionError, FileNotFoundError)), raised.value
    return windows_reason(raised.value)


def _recorded_cases(monkeypatch, profile: Path) -> tuple[dict, dict, dict]:
    """Every tr() call under _RECORDED, with its arguments, in order, for
    each case: the Config tab given a folder that denies new folders, one on
    a drive that is not there, a name Windows does not take and a file, and
    an extraction started with its cache folder denying new folders, on a
    drive that is not there, and with a file where it should be. Returns the
    calls by case, the folder each case names, as the boxes name it, and
    Windows' reason for each case that gives one."""
    calls: list = []
    for module in (config_tab, main_window):
        def recording_tr(key, _real=module.tr, **kwargs):
            if key.startswith(_RECORDED):
                calls.append((key, kwargs))
            return _real(key, **kwargs)

        monkeypatch.setattr(module, "tr", recording_tr)
        monkeypatch.setattr(module, "QMessageBox", MagicMock())
    for name in ("DataForgeExtractWorker", "AnimatedProgressDialog"):
        monkeypatch.setattr(main_window, name,
                            MagicMock(side_effect=AssertionError(f"{name} was built")))

    refused = profile / "refused"
    refused.mkdir()
    missing = missing_drive_folder()
    bad_name = profile / "SC|Cache"
    a_file = profile / "cache.txt"
    a_file.write_text("not a folder", encoding="utf-8")
    reasons = {"bad name": _reason_for(bad_name),
               "file in the way": _reason_for(a_file / "LIVE" / "cache" / "dataforge")}
    tab = ConfigTab()
    cases: dict = {}

    def record(case, action):
        calls.clear()
        action()
        cases[case] = list(calls)

    with new_folders_denied(refused):
        record("config refused", lambda: _type(tab, refused))
        AppSettings.set_cache_dir(refused)
        record("extraction refused", _start_extraction)
    record("config unreachable", lambda: _type(tab, missing))
    record("config unusable", lambda: _type(tab, bad_name))
    record("config file", lambda: _type(tab, a_file))
    AppSettings.set_cache_dir(missing)
    record("extraction unreachable", _start_extraction)
    AppSettings.set_cache_dir(a_file)
    record("extraction unusable", _start_extraction)
    folders = {name: os.path.normpath(str(path.resolve()))
               for name, path in (("refused", refused), ("missing", missing),
                                  ("bad name", bad_name), ("file", a_file))}
    return cases, folders, reasons


# Windows' codes for a folder that cannot be made, and the kind of message
# each gets.
_WINERRORS = [
    (2, CACHE_FOLDER_UNREACHABLE),   # ERROR_FILE_NOT_FOUND
    (3, CACHE_FOLDER_UNREACHABLE),   # ERROR_PATH_NOT_FOUND: a drive letter not assigned
    (15, CACHE_FOLDER_UNREACHABLE),  # ERROR_INVALID_DRIVE
    (21, CACHE_FOLDER_UNREACHABLE),  # ERROR_NOT_READY: a drive with no media in it
    (53, CACHE_FOLDER_UNREACHABLE),  # ERROR_BAD_NETPATH
    (67, CACHE_FOLDER_UNREACHABLE),  # ERROR_BAD_NET_NAME
    (5, CACHE_FOLDER_REFUSED),       # ERROR_ACCESS_DENIED: permissions, Controlled folder access
    (65, CACHE_FOLDER_REFUSED),      # ERROR_NETWORK_ACCESS_DENIED: a share
    # The rest of the range Python raises as PermissionError is not a refusal.
    (19, CACHE_FOLDER_UNUSABLE),     # ERROR_WRITE_PROTECT
    (23, CACHE_FOLDER_UNUSABLE),     # ERROR_CRC: a failing drive
    (32, CACHE_FOLDER_UNUSABLE),     # ERROR_SHARING_VIOLATION: a file another program holds
    (112, CACHE_FOLDER_UNUSABLE),    # ERROR_DISK_FULL
    (123, CACHE_FOLDER_UNUSABLE),    # ERROR_INVALID_NAME: a name Windows does not take
    (161, CACHE_FOLDER_UNUSABLE),    # ERROR_BAD_PATHNAME: a path Windows cannot parse
    (183, CACHE_FOLDER_UNUSABLE),    # ERROR_ALREADY_EXISTS: a file in the way
    (206, CACHE_FOLDER_UNUSABLE),    # ERROR_FILENAME_EXCED_RANGE: a path too long for Windows
]


def _windows_error(winerror: int) -> OSError:
    """Built the way Python builds the error from Windows' code, so a
    not-ready drive arrives as a PermissionError, and a path Windows cannot
    parse or one too long for it as a FileNotFoundError, as they do for real."""
    return OSError(None, "Windows' reason", "E:\\SC Cache\\LIVE", winerror)


@pytest.mark.parametrize("winerror, failure", _WINERRORS)
def test_each_windows_error_gets_its_kind_of_message(winerror, failure):
    error = _windows_error(winerror)
    if winerror == 21:
        assert isinstance(error, PermissionError)
    if winerror in (161, 206):
        assert isinstance(error, FileNotFoundError)
    assert cache_folder_failure(error) == failure, type(error).__name__


@pytest.mark.parametrize("winerror", [winerror for winerror, _failure in _WINERRORS])
def test_both_places_read_each_error_as_the_classifier_does(winerror, monkeypatch, tmp_profile):
    """Each code in ``_WINERRORS`` raised while the cache folder is made, in
    the Config tab (a typed folder that is there) and at the start of an
    extraction: each shows the message for the kind ``cache_folder_failure``
    gives, so neither can read one of these codes its own way. A code that
    is not in the table is not checked here."""
    error = _windows_error(winerror)
    kind = cache_folder_failure(error)
    keys = []
    for module in (config_tab, main_window):
        def recording_tr(key, _real=module.tr, **kwargs):
            if key.startswith(("config.cache_folder_", "extract.cache_folder_")):
                keys.append(key)
            return _real(key, **kwargs)

        monkeypatch.setattr(module, "tr", recording_tr)
        monkeypatch.setattr(module, "QMessageBox", MagicMock())
    for name in ("DataForgeExtractWorker", "AnimatedProgressDialog"):
        monkeypatch.setattr(main_window, name,
                            MagicMock(side_effect=AssertionError(f"{name} was built")))

    def raise_it():
        raise error

    monkeypatch.setattr(AppSettings, "get_dataforge_cache_dir", staticmethod(raise_it))
    (tmp_profile / "new").mkdir()

    _type(ConfigTab(), tmp_profile / "new")
    _start_extraction()

    assert keys == [f"config.cache_folder_{kind}", f"extract.cache_folder_{kind}"]


def test_the_reason_is_windows_own_or_the_whole_error():
    assert windows_reason(OSError(None, "The device is not ready", "E:\\", 21)) == (
        "The device is not ready")
    error = OSError("the cache folder could not be made")
    assert windows_reason(error) == str(error) == "the cache folder could not be made"


def test_each_case_gets_its_own_message_and_advice(monkeypatch, tmp_profile):
    """The cache advice (choose another cache folder) only for an
    extraction; the Config tab's refusal gets the advice without it. Any
    other error gets Windows' own reason."""
    cases, folders, reasons = _recorded_cases(monkeypatch, tmp_profile)
    refused, missing = {"folder": folders["refused"]}, {"folder": folders["missing"]}
    assert cases == {
        "config refused": [("config.cache_folder_refused", refused),
                           ("extract.folder_refused_fix", {})],
        "config unreachable": [("config.cache_folder_unreachable", missing)],
        "config unusable": [("config.cache_folder_unusable",
                             {"folder": folders["bad name"], "reason": reasons["bad name"]})],
        "config file": [("config.cache_folder_is_file", {"folder": folders["file"]})],
        "extraction refused": [("extract.cache_folder_refused", refused),
                               ("extract.folder_refused_fix_cache", {})],
        "extraction unreachable": [("extract.cache_folder_unreachable", missing)],
        "extraction unusable": [("extract.cache_folder_unusable",
                                 {"folder": folders["file"],
                                  "reason": reasons["file in the way"]})],
    }


@pytest.mark.parametrize("ui_json", _UI_FILES, ids=lambda p: p.parent.name)
def test_every_language_formats_the_messages(ui_json, tmp_profile, monkeypatch):
    """A value that is missing, drops or renames a placeholder, or keeps one
    the code does not pass, fails here instead of reaching the user as a raw
    template. A long path, and Windows' reason, each read whole on a line of
    their own, as in English."""
    cases, _folders, _reasons = _recorded_cases(monkeypatch, tmp_profile)
    english, strings = _load(_LANGUAGES / "english" / "ui.json"), _load(ui_json)
    language = ui_json.parent.name
    for key, kwargs in (call for calls in cases.values() for call in calls):
        english_fields = _placeholders(_leaf(english, key))
        assert set(kwargs) == english_fields, key
        text = _leaf(strings, key)
        assert text, f"{language}: {key} is empty or missing"
        assert _placeholders(text) == english_fields, f"{language}: {key}"
        formatted = text.format(**kwargs)
        assert "{" not in formatted and "}" not in formatted, f"{language}: {key}"
        for field in _OWN_LINE_FIELDS:
            if field in kwargs:
                assert _on_its_own_line(text, field), f"{language}: {key} {{{field}}}"


@pytest.mark.parametrize("ui_json", _UI_FILES, ids=lambda p: p.parent.name)
def test_english_is_the_source_and_every_translation_is_an_ai_text(ui_json):
    for key in sorted(_KEYS):
        node = _node(_load(ui_json), key)
        if ui_json.parent.name == "english":
            assert node.get("ht") and node.get("at") == "", key
        else:
            assert node.get("ht") == "" and node.get("at"), f"{ui_json.parent.name}: {key}"
