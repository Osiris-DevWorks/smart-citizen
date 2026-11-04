"""#490: the message for a working folder Windows refuses, in every language.

An extraction whose working folder Windows refuses (a folder whose
permissions deny Smart Citizen, Controlled Folder Access) stops with one
message built from two keys: ``extract.folder_refused``, which names the
folder, then the advice. The advice is ``extract.folder_refused_fix_cache``
for a folder beside the DataForge cache, where choosing another cache folder
helps, and ``extract.folder_refused_fix`` for %TEMP%, where it may not. A
drive Windows will not write to (write-protected or failing, which Python
raises as a PermissionError too) gets ``extract.folder_unusable`` instead,
with Windows' own reason and no advice about permissions. These tests pin:

* which advice each refusal gets, with the keys recorded from real refusals
  of extract_dataforge and extract_global_ini, so a key the code stops
  using, or a new one, fails here too;
* every language: each key has a value, formats with the arguments
  pak_extractor passes and leaves no placeholder behind, and the folder
  stands on a line of its own;
* provenance (languages/TRANSLATIONS.md): English has the source text in
  ``ht``, every other language an AI text in ``at`` and an empty ``ht``.

Qt-free. conftest's ``english_ui`` keeps the active language English, and
its ``no_real_free_space`` keeps the free-space check off the real drive.
"""
from __future__ import annotations

import errno
import json
import string
from pathlib import Path

import pytest

import src.utils.pak_extractor as pe

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("english_ui")]

_LANGUAGES = Path(__file__).resolve().parent.parent / "languages"
_UI_FILES = sorted(_LANGUAGES.glob("*/ui.json"))

# Every key pak_extractor uses for a working folder Windows will not make.
_KEYS = {
    "extract.folder_refused",
    "extract.folder_refused_fix_cache",
    "extract.folder_refused_fix",
    "extract.folder_unusable",
}
_KEY_PREFIXES = ("extract.folder_refused", "extract.folder_unusable")
# Windows' own reason for a write-protected drive (WinError 19), which Python
# raises as a PermissionError although nothing was refused.
_WRITE_PROTECTED = "The media is write protected"


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


def _no_tool_may_run(*args, **kwargs):
    raise AssertionError("a tool ran, but no working folder was made")


def _refuse(parent, prefix):
    raise PermissionError(errno.EACCES, "Access is denied", str(parent))


def _write_protected(parent, prefix):
    raise OSError(None, _WRITE_PROTECTED, str(parent), 19)


def _recorded_refusals(monkeypatch, tmp_path):
    """Every extract.folder_refused* and extract.folder_unusable key
    pak_extractor passes to tr() when Windows refuses every working folder,
    with the arguments of each call, in order: extract_dataforge with its
    work beside the cache, then with a OneDrive cache whose work goes to
    %TEMP%, then extract_global_ini, which tries beside the cache and then
    %TEMP%, and last extract_dataforge beside a write-protected cache.
    Returns the calls, the folder beside the cache and %TEMP%."""
    calls: dict = {}
    real_tr = pe.tr

    def recording_tr(key, **kwargs):
        if key.startswith(_KEY_PREFIXES):
            calls.setdefault(key, []).append(kwargs)
        return real_tr(key, **kwargs)

    tools = tmp_path / "tools"
    tools.mkdir()
    for name in ("unp4k.exe", "unforge.exe", "Data.p4k"):
        (tools / name).write_bytes(b"x")
    leaf = tmp_path / "cache" / "dataforge"
    systemp = tmp_path / "systemp"
    systemp.mkdir()
    monkeypatch.setattr(pe.tempfile, "tempdir", str(systemp))
    monkeypatch.setattr(pe, "_drive_is_removable_or_network", lambda path: False)
    # Beside the cache, however long tmp_path is on the machine that runs this
    # (past the cap the work goes to %TEMP%, which takes the other advice).
    monkeypatch.setattr(pe, "_MAX_SCRATCH_CHARS", 10_000)
    monkeypatch.setattr(pe, "_run_tool", _no_tool_may_run)
    monkeypatch.setattr(pe, "_open_scratch", _refuse)
    monkeypatch.setattr(pe, "tr", recording_tr)

    for onedrive in (False, True):
        monkeypatch.setattr(pe, "is_onedrive_path", lambda path, onedrive=onedrive: onedrive)
        with pytest.raises(pe.WorkingFolderRefusedError):
            pe.extract_dataforge(tools / "Data.p4k", tools / "unp4k.exe", tools / "unforge.exe",
                                 leaf)
    monkeypatch.setattr(pe, "is_onedrive_path", lambda path: False)
    with pytest.raises(pe.WorkingFolderRefusedError):
        pe.extract_global_ini(tools / "Data.p4k", tmp_path / "data" / "base.ini",
                              tools / "unp4k.exe", scratch_near=leaf)
    monkeypatch.setattr(pe, "_open_scratch", _write_protected)
    with pytest.raises(pe.WorkingFolderRefusedError):
        pe.extract_dataforge(tools / "Data.p4k", tools / "unp4k.exe", tools / "unforge.exe", leaf)
    return calls, leaf.parent, systemp


def test_each_refusal_gets_the_advice_that_fits(monkeypatch, tmp_path):
    """The cache advice only beside the cache. DataForge's work in %TEMP%
    and the global.ini extraction's (which reports only %TEMP%) get the
    advice without another cache folder. A write-protected drive gets
    Windows' own reason and no advice."""
    calls, beside, systemp = _recorded_refusals(monkeypatch, tmp_path)
    assert set(calls) == _KEYS
    assert calls["extract.folder_refused"] == [
        {"folder": str(beside)}, {"folder": str(systemp)}, {"folder": str(systemp)}]
    assert calls["extract.folder_refused_fix_cache"] == [{}]
    assert calls["extract.folder_refused_fix"] == [{}, {}]
    assert calls["extract.folder_unusable"] == [{"folder": str(beside), "reason": _WRITE_PROTECTED}]


@pytest.mark.parametrize("ui_json", _UI_FILES, ids=lambda p: p.parent.name)
def test_every_language_formats_the_refusal_message(ui_json, tmp_path, monkeypatch):
    """A value that is missing, drops or renames a placeholder, or keeps one
    pak_extractor does not pass, fails here instead of reaching the user as
    a raw template."""
    calls, _beside, _systemp = _recorded_refusals(monkeypatch, tmp_path)
    english, strings = _load(_LANGUAGES / "english" / "ui.json"), _load(ui_json)
    for key, kwarg_sets in sorted(calls.items()):
        english_fields = _placeholders(_leaf(english, key))
        for kwargs in kwarg_sets:
            assert set(kwargs) == english_fields, key
        text = _leaf(strings, key)
        assert text, f"{ui_json.parent.name}: {key} is empty or missing"
        assert _placeholders(text) == english_fields, f"{ui_json.parent.name}: {key}"
        for kwargs in kwarg_sets:
            formatted = text.format(**kwargs)
            assert "{" not in formatted and "}" not in formatted, f"{ui_json.parent.name}: {key}"
    # A long path reads whole on a line of its own, as in English, and so
    # does Windows' reason.
    assert "\n{folder}\n\n" in _leaf(strings, "extract.folder_refused"), ui_json.parent.name
    assert "\n{folder}\n\n{reason}\n\n" in _leaf(strings, "extract.folder_unusable"), \
        ui_json.parent.name


@pytest.mark.parametrize("ui_json", _UI_FILES, ids=lambda p: p.parent.name)
def test_english_is_the_source_and_every_translation_is_an_ai_text(ui_json):
    for key in sorted(_KEYS):
        node = _node(_load(ui_json), key)
        if ui_json.parent.name == "english":
            assert node.get("ht") and node.get("at") == "", key
        else:
            assert node.get("ht") == "" and node.get("at"), f"{ui_json.parent.name}: {key}"
