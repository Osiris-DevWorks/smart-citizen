"""The Config tab's Apply Preview and the Apply dialog report the same enhancements (#443).

The preview is meant to forecast what the Apply dialog will say. They used to count differently: the preview
counted per winning source (so an overridden key moved to the User row) and kept the discovered ("New") keys
that Apply drops when Include discovered items is off. Both now count with one function over the same
enhancements source, so the totals and the category lists agree.

The data set is hermetic: two stock keys that the enhancements override and two discovered keys they add,
spread over two categories. The preview runs for real through ConfigTab.preview_merge with a fake QMessageBox.
The Apply side runs what apply_to_game does with the same inputs: the snapshot of the loaded entries
(_apply_merge_inputs), the merge that strips the discovered keys (_merge_for_apply), then the count.
"""
from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from src.gui import config_tab, main_window
from src.parser import ini_parser
from src.parser.ini_parser import load_source_files, load_sources_from_settings
from src.utils.settings import AppSettings

pytestmark = pytest.mark.unit

SHIP_STOCK = "vehicle_DescANVL_Carrack"
SHIP_NEW = "vehicle_NameNEWA_Gadget"
MED_STOCK = "item_Desccrlf_consumable_adrenaline_01"
MED_NEW = "item_Desccrlf_consumable_new_01"


def _ini(path, mapping):
    path.write_text("".join(f"{key}={value}\n" for key, value in mapping.items()), encoding="utf-8")


def _set_up(tmp_path, monkeypatch, *, include_new, override):
    """Hermetic AppSettings (the approach of test_enhancements_source_injection) for the four-key data set."""
    base_ini = tmp_path / "base.ini"
    _ini(base_ini, {SHIP_STOCK: "Stock ship", MED_STOCK: "Stock pen", "status_Ready": "Ready"})
    enh_dir = tmp_path / "enhancements"
    enh_dir.mkdir()
    _ini(enh_dir / AppSettings.ENHANCEMENTS_FILES["ship_descs"],
         {SHIP_STOCK: "Enhanced ship", SHIP_NEW: "Discovered ship"})
    _ini(enh_dir / AppSettings.ENHANCEMENTS_FILES["medical_consumables"],
         {MED_STOCK: "Enhanced pen", MED_NEW: "Discovered pen"})
    user_ini = tmp_path / "user.ini"
    if override:
        _ini(user_ini, {MED_STOCK: "My own pen text"})
    paths = {AppSettings.SOURCE_GLOBAL: str(base_ini), AppSettings.SOURCE_USER: str(user_ini)}

    def patch(name, value):
        monkeypatch.setattr(AppSettings, name, staticmethod(value))

    patch("get_merge_hierarchy", lambda: [AppSettings.SOURCE_GLOBAL, AppSettings.SOURCE_USER])
    patch("get_cache_dir", lambda: tmp_path)
    patch("is_source_enabled", lambda name: True)
    patch("get_source_path", lambda name: paths.get(name, ""))
    patch("get_enabled_enhancement_categories", lambda: {"ship_descs", "medical_consumables"})
    patch("get_enhancements_dir", lambda language=None: enh_dir)
    patch("get_selected_language", lambda: "english")
    patch("get_include_new_lines", lambda: include_new)
    patch("get_owned_items", lambda: set())


def _preview(monkeypatch):
    """Run the real preview and return (enhancements total, category counts, whole text)."""
    shown = []

    class FakeBox:
        @staticmethod
        def information(parent, title, text, *args, **kwargs):
            shown.append(("information", text))

        @staticmethod
        def warning(parent, title, text, *args, **kwargs):
            shown.append(("warning", text))

        @staticmethod
        def critical(parent, title, text, *args, **kwargs):
            shown.append(("critical", text))

    monkeypatch.setattr(config_tab, "QMessageBox", FakeBox)
    config_tab.ConfigTab.preview_merge(object())
    assert [kind for kind, _ in shown] == ["information"], shown
    text = shown[0][1]
    total = int(re.search(r"Smart Citizen Enhancements \(([\d,]+) keys total\)", text).group(1).replace(",", ""))
    categories = {
        name: int(count.replace(",", ""))
        for name, count in re.findall(r"^ {7}(\S.*?): ([\d,]+)$", text, re.M)
    }
    return total, categories, text


def _apply_dialog():
    """What apply_to_game counts: the merge strips the discovered keys, then the enhancements source is counted."""
    sources, hierarchy, key_categories = load_sources_from_settings()
    entries = load_source_files(sources, hierarchy, enhancements_key_categories=key_categories)
    inputs = main_window.MainWindow._apply_merge_inputs(
        SimpleNamespace(entries=entries, _bp_header=lambda: None)
    )
    main_window._merge_for_apply(sources, hierarchy, inputs)
    counted = main_window._count_enhancement_categories(sources, key_categories)
    return sum(counted.values()), dict(counted)


# (Include discovered items, a user override on an enhancement key, expected total, expected categories)
CASES = [
    pytest.param(True, False, 4, {"Ships": 2, "Medical Consumables": 2}, id="discovered on, nothing overridden"),
    pytest.param(False, False, 2, {"Ships": 1, "Medical Consumables": 1}, id="discovered off, nothing overridden"),
    pytest.param(True, True, 4, {"Ships": 2, "Medical Consumables": 2}, id="discovered on, one key overridden"),
    pytest.param(False, True, 2, {"Ships": 1, "Medical Consumables": 1}, id="discovered off, one key overridden"),
]


@pytest.mark.parametrize("include_new, override, total, categories", CASES)
def test_preview_and_apply_dialog_report_the_same_enhancements(
    tmp_path, monkeypatch, include_new, override, total, categories
):
    _set_up(tmp_path, monkeypatch, include_new=include_new, override=override)

    preview_total, preview_categories, _ = _preview(monkeypatch)
    apply_total, apply_categories = _apply_dialog()

    assert (apply_total, apply_categories) == (total, categories)
    assert (preview_total, preview_categories) == (apply_total, apply_categories)


def test_an_overridden_key_still_shows_under_user(tmp_path, monkeypatch):
    """Counting an overridden enhancement key as an enhancement must not drop it from the User row."""
    _set_up(tmp_path, monkeypatch, include_new=True, override=True)
    _, _, text = _preview(monkeypatch)
    assert "User (1 keys)" in text


def test_only_one_copy_of_the_counter_exists():
    """The Apply dialog's name is the parser's function, not a second implementation that could drift."""
    assert main_window._count_enhancement_categories is ini_parser.count_enhancement_categories
