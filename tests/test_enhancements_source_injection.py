"""Enhancements source injection in load_sources_from_settings
(src/parser/ini_parser.py).

When an enhancement category is enabled, its generated INI is loaded as the
synthetic ``enhancements`` source (AppSettings.SOURCE_ENHANCEMENTS), inserted
into the merge hierarchy just before ``user`` (or appended when there is no
user entry), and every key it carries is mapped to that category's label for
the table's category column. Also driven through load_source_files, so the
source name, the Enhanced status and the map category are checked end to end.
"""
from __future__ import annotations

import pytest

from src.parser.ini_parser import load_source_files, load_sources_from_settings
from src.utils.settings import AppSettings

pytestmark = pytest.mark.unit

KEY = "item_Desccrlf_consumable_adrenaline_01"
LABEL = "medical_consumables"


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Hermetic AppSettings: a base.ini holding KEY, an enhancements dir whose
    medical-consumables file overrides it, global+user sources, English."""
    base_ini = tmp_path / "base.ini"
    base_ini.write_text(f"{KEY}=Stock text\nstatus_Ready=Ready\n", encoding="utf-8")
    enh_dir = tmp_path / "enhancements"
    enh_dir.mkdir()
    (enh_dir / AppSettings.ENHANCEMENTS_FILES[LABEL]).write_text(
        f"{KEY}=Enhanced text\n", encoding="utf-8"
    )
    paths = {
        AppSettings.SOURCE_GLOBAL: str(base_ini),
        AppSettings.SOURCE_USER: str(tmp_path / "user.ini"),  # absent: first run
    }
    monkeypatch.setattr(
        AppSettings, "get_merge_hierarchy",
        staticmethod(lambda: [AppSettings.SOURCE_GLOBAL, AppSettings.SOURCE_USER]),
    )
    monkeypatch.setattr(AppSettings, "get_cache_dir", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(
        AppSettings, "is_source_enabled", staticmethod(lambda name: True)
    )
    monkeypatch.setattr(
        AppSettings, "get_source_path", staticmethod(lambda name: paths.get(name, ""))
    )
    monkeypatch.setattr(
        AppSettings, "get_enabled_enhancement_categories", staticmethod(lambda: {LABEL})
    )
    monkeypatch.setattr(
        AppSettings, "get_enhancements_dir", staticmethod(lambda language=None: enh_dir)
    )
    monkeypatch.setattr(
        AppSettings, "get_selected_language", staticmethod(lambda: "english")
    )
    return monkeypatch


def test_source_is_injected_with_the_generated_keys(env):
    sources, _, _ = load_sources_from_settings()
    assert sources[AppSettings.SOURCE_ENHANCEMENTS] == {KEY: "Enhanced text"}


def test_inserted_just_before_user(env):
    _, hierarchy, _ = load_sources_from_settings()
    assert hierarchy == [
        AppSettings.SOURCE_GLOBAL,
        AppSettings.SOURCE_ENHANCEMENTS,
        AppSettings.SOURCE_USER,
    ]


def test_appended_when_there_is_no_user_source(env):
    env.setattr(
        AppSettings, "get_merge_hierarchy",
        staticmethod(lambda: [AppSettings.SOURCE_GLOBAL]),
    )
    _, hierarchy, _ = load_sources_from_settings()
    assert hierarchy == [AppSettings.SOURCE_GLOBAL, AppSettings.SOURCE_ENHANCEMENTS]


def test_keys_map_to_the_category_label(env):
    _, _, key_categories = load_sources_from_settings()
    assert key_categories == {KEY: "Medical Consumables"}


def test_no_enabled_category_means_no_enhancements_source(env):
    env.setattr(
        AppSettings, "get_enabled_enhancement_categories", staticmethod(lambda: set())
    )
    sources, hierarchy, key_categories = load_sources_from_settings()
    assert AppSettings.SOURCE_ENHANCEMENTS not in sources
    assert AppSettings.SOURCE_ENHANCEMENTS not in hierarchy
    assert key_categories == {}


def test_overridden_key_is_enhanced_and_categorised_from_the_map(env):
    sources, hierarchy, key_categories = load_sources_from_settings()
    entries = load_source_files(
        sources, hierarchy, enhancements_key_categories=key_categories
    )
    entry = next(e for e in entries if e.key == KEY)
    assert entry.source_file == AppSettings.SOURCE_ENHANCEMENTS
    assert entry.status == "Enhanced"
    assert entry.category == "Medical Consumables"
    assert entry.original_value == "Enhanced text"


def test_config_preview_buckets_keys_by_the_map_category(env):
    """ConfigTab.preview_merge mirrors the Apply dialog, so it must bucket
    enhancement keys by the generator's map too: a medical consumable is
    "Medical Consumables", not "Gear" by key prefix."""
    from src.gui import config_tab

    calls = []

    class FakeBox:
        @staticmethod
        def information(parent, title, text, *args, **kwargs):
            calls.append(("information", text))

        @staticmethod
        def warning(parent, title, text, *args, **kwargs):
            calls.append(("warning", text))

        @staticmethod
        def critical(parent, title, text, *args, **kwargs):
            calls.append(("critical", text))

    env.setattr(config_tab, "QMessageBox", FakeBox)
    config_tab.ConfigTab.preview_merge(object())

    assert [kind for kind, _ in calls] == ["information"], calls
    text = calls[0][1]
    assert "Medical Consumables: 1" in text
    assert "Gear" not in text
