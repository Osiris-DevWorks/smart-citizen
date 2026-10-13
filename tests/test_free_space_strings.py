"""#482: the not-enough-space messages, in every language.

An extraction that would not fit is refused with a message built from several
keys: an intro, one line per short drive with its free and needed sizes, and
the advice for each drive. The sizes are formatted by each language's own
``extract.size_gb`` / ``extract.size_mb`` templates, which own the decimal
mark and the unit. These tests pin:

* the rounding: free rounds down and the need rounds up, so a short drive
  never reads as having what it needs;
* every language: each key the refusals use has a value, formats with the
  arguments pak_extractor passes and leaves no placeholder behind, with the
  keys recorded from real refusals, so each extraction's own intro is used;
* the Config tab's cache folder tooltip and the data folder text state the
  figures the check uses, in every language, except a translator's data
  folder text, which stays on TRANSLATIONS.md's re-review list instead.

Qt-free. The English asserts run under conftest's ``english_ui``.
"""
from __future__ import annotations

import json
import math
import re
import string
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.utils.pak_extractor as pe

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("english_ui")]

_LANGUAGES = Path(__file__).resolve().parent.parent / "languages"
_UI_FILES = sorted(_LANGUAGES.glob("*/ui.json"))
_GIB, _MIB = 1 << 30, 1 << 20

# Every key pak_extractor uses for a refusal or a drive that filled.
_NEW_KEYS = {
    "extract.no_space_dataforge",
    "extract.no_space_global_ini",
    "extract.no_space_drive",
    "extract.no_space_fix_cache",
    "extract.no_space_fix_temp",
    "extract.no_space_fix",
    "extract.no_space_cache_incomplete",
    "extract.size_gb",
    "extract.size_mb",
}


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


def _one_drive(monkeypatch, free: int, label: str = "C:") -> None:
    """Every folder is on one volume, *label*, with *free* bytes free."""
    monkeypatch.setattr(pe, "_measure_volume", lambda folder: pe._Volume(1, label, 4096, None))
    monkeypatch.setattr(pe.shutil, "disk_usage", lambda path: SimpleNamespace(free=free))


def _part_needing(folder: Path, need: int) -> "pe._SpaceNeed":
    """A part whose need at 4096-byte clusters is exactly *need* bytes."""
    logical = -(-need * 100 // pe._SPACE_GROWTH_PERCENT)
    credit = pe._space_for(logical, 0, 4096) - need
    return pe._SpaceNeed(folder, logical, 0, credit=credit, fix="cache")


@pytest.mark.parametrize("free, need, free_text, need_text", [
    (int(3.05 * _GIB), int(3.06 * _GIB), "3.0 GB", "3.1 GB"),
    (900 * _MIB, 3 * _GIB, "900 MB", "3.0 GB"),
    (3 * _GIB - 1, 3 * _GIB, "2.9 GB", "3.0 GB"),
    (40 * _MIB + 1, 49 * _MIB - 1, "40 MB", "49 MB"),
])
def test_the_message_names_each_short_drive_and_rounds_safely(
    tmp_path, monkeypatch, free, need, free_text, need_text
):
    for key in sorted(_NEW_KEYS):
        assert pe.tr(key) != key, f"{key} is missing from languages/english/ui.json"
    _one_drive(monkeypatch, free)
    with pytest.raises(pe.NotEnoughSpaceError) as raised:
        pe._require_free_space([_part_needing(tmp_path, need)], pe.tr("extract.no_space_dataforge"))
    assert raised.value.shortages[0][2:] == (free, need)
    message = str(raised.value)
    assert "{" not in message and "}" not in message
    assert message.startswith(pe.tr("extract.no_space_dataforge"))
    assert pe.tr("extract.no_space_drive", drive="C:", free=free_text, needed=need_text) in message
    assert pe.tr("extract.no_space_fix_cache", drive="C:") in message


@pytest.mark.parametrize("unit", [_MIB, _GIB // 10])
def test_a_drive_one_byte_short_never_reads_as_having_enough(unit):
    """Free rounds down and the need rounds up, so the two figures differ
    even at the edge of each rounding step, in MB and in tenths of a GB."""
    for steps in range(1, 40):
        need = steps * unit + (_GIB if unit != _MIB else 0)
        for delta in (-1, 0, 1):
            n = need + delta
            assert pe._size_text(n - 1, round_up=False) != pe._size_text(n, round_up=True), n


def _no_tool_may_run(*args, **kwargs):
    raise AssertionError("a tool ran, but the free-space check refuses before any does")


def _recorded_refusals(monkeypatch, tmp_path) -> dict:
    """Every key pak_extractor passes to tr() in a refusal of each kind, with
    the arguments of each call. The refusals come from the real entry
    points, so each extraction picks its own intro and advice:
    extract_dataforge with its work beside the cache (the cache advice) and
    with a OneDrive cache whose work goes to %TEMP% (the temp advice),
    extract_global_ini with no cache folder, so in %TEMP% (the plain
    advice), each refused before any tool runs, and a drive that filled
    while the new cache was saved. %TEMP% is on C: and everything else on
    D:. The free figure is in MB and the needs in GB, so both size keys are
    used."""
    calls: dict = {}
    real_tr = pe.tr

    def recording_tr(key, **kwargs):
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
    monkeypatch.setattr(pe, "_run_tool", _no_tool_may_run)
    monkeypatch.setattr(pe, "tr", recording_tr)
    monkeypatch.setattr(pe, "_measure_volume", lambda folder: pe._Volume(
        *((1, "C:") if pe.win_plain_path(folder).startswith(str(systemp)) else (2, "D:")),
        4096, None))
    monkeypatch.setattr(pe.shutil, "disk_usage", lambda path: SimpleNamespace(free=5 * _MIB))

    for onedrive in (False, True):
        monkeypatch.setattr(pe, "is_onedrive_path", lambda path, onedrive=onedrive: onedrive)
        with pytest.raises(pe.NotEnoughSpaceError) as raised:
            pe.extract_dataforge(tools / "Data.p4k", tools / "unp4k.exe", tools / "unforge.exe",
                                 leaf)
        assert str(raised.value).startswith(real_tr("extract.no_space_dataforge"))
    with pytest.raises(pe.NotEnoughSpaceError) as raised:
        pe.extract_global_ini(tools / "Data.p4k", tmp_path / "data" / "base.ini",
                              tools / "unp4k.exe")
    assert str(raised.value).startswith(real_tr("extract.no_space_global_ini"))
    pe._cache_incomplete_error(leaf, OSError(28, "No space left on device"))
    return calls


@pytest.mark.parametrize("ui_json", _UI_FILES, ids=lambda p: p.parent.name)
def test_every_language_formats_the_free_space_messages(ui_json, tmp_path, monkeypatch):
    """The only check of these placeholders some languages get. A value that
    is missing, drops or renames a placeholder, or keeps one pak_extractor
    does not pass, fails here instead of reaching the user as a raw
    template."""
    calls = _recorded_refusals(monkeypatch, tmp_path)
    assert set(calls) == _NEW_KEYS
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


def _first_run_need_4k() -> int:
    """What a first run asks for on one NTFS drive: the working folder and the
    new cache, at 4096-byte clusters."""
    return (pe._space_for(pe._DATAFORGE_WORK_BYTES, pe._DATAFORGE_WORK_FILES, 4096)
            + pe._space_for(pe._DATAFORGE_CACHE_BYTES, pe._DATAFORGE_CACHE_FILES, 4096))


def _tooltip_figures() -> tuple[str, str]:
    """The cache folder tooltip's two figures, as "4.5" and "1.2": the 4 KiB
    first-run need rounded up to the next half GB, and the cache constant."""
    return (f"{math.ceil(_first_run_need_4k() / (_GIB / 2)) / 2:.1f}",
            f"{pe._DATAFORGE_CACHE_BYTES / _GIB:.1f}")


def test_the_cache_tooltip_states_what_the_check_asks_for():
    """English gives both figures in GB, so changing the constants without
    the text fails here."""
    up_to, cache = _tooltip_figures()
    tooltip = pe.tr("config.cache_dir_tooltip")
    assert f"{up_to} GB" in tooltip and f"{cache} GB" in tooltip


@pytest.mark.parametrize("ui_json", _UI_FILES, ids=lambda p: p.parent.name)
def test_every_cache_tooltip_gives_the_figures_and_not_the_old_one(ui_json):
    """Every language gives both figures, with its own decimal mark and unit,
    the old ~1.4 GB is gone, and the only placeholders are {base} and
    {channel}. config_tab calls tr() on it without arguments, so any other
    placeholder would show raw."""
    tooltip = _leaf(_load(ui_json), "config.cache_dir_tooltip")
    assert tooltip
    for figure in _tooltip_figures():
        assert _gives_figure(tooltip, figure), (ui_json.parent.name, figure)
    assert not _gives_figure(tooltip, "1.4")
    assert _placeholders(tooltip) == {"base", "channel"}


# config.data_desc has a translator's ht in these three, which AI never edits
# (decision 5), so it keeps the old figure until a translator updates it.
_HUMAN_DATA_DESC = {"french", "portuguese_br", "spanish"}


def _re_review_languages(key: str) -> set[str]:
    """The languages the entry for *key* under "Needs human re-review" in
    languages/TRANSLATIONS.md says it affects ("Affects french,
    portuguese_br and spanish, whose ..."), or none when it has no entry."""
    text = (_LANGUAGES / "TRANSLATIONS.md").read_text(encoding="utf-8")
    section = text.split("\n## Needs human re-review\n", 1)[1].split("\n## ", 1)[0]
    for entry in re.split(r"\n(?=- )", section):
        if entry.startswith(f"- `{key}`"):
            affects = re.search(r"\bAffects (.+?)(?:, whose\b| \(|\.)", " ".join(entry.split()))
            return set(re.split(r",\s*|\s+and\s+", affects.group(1))) if affects else set()
    return set()


def _gives_figure(text: str, figure: str) -> bool:
    """True when *text* gives *figure* ("1.2"), with either decimal mark."""
    whole, tenth = figure.split(".")
    return re.search(rf"(?<!\d){whole}[.,]{tenth}(?!\d)", text) is not None


@pytest.mark.parametrize("ui_json", _UI_FILES, ids=lambda p: p.parent.name)
def test_the_data_folder_text_gives_the_cache_size(ui_json):
    """config.data_desc says how big the DataForge cache is (#482, decision
    5). English and the seven languages with only an AI text there say
    1.2 GB, with their own decimal mark. french, portuguese_br and spanish
    keep their translator's ht, which still says 1,4, so while it does they
    must be on TRANSLATIONS.md's re-review entry for the key."""
    language = ui_json.parent.name
    node = _node(_load(ui_json), "config.data_desc")
    shown = node.get("ht") or node.get("at") or ""
    cache = f"{pe._DATAFORGE_CACHE_BYTES / _GIB:.1f}"
    if language in _HUMAN_DATA_DESC:
        assert node.get("ht"), f"{language}: the translator's text is gone"
        if not _gives_figure(shown, cache):
            assert language in _re_review_languages("config.data_desc"), language
    else:
        assert _gives_figure(shown, cache), language
        assert not _gives_figure(shown, "1.4"), language
