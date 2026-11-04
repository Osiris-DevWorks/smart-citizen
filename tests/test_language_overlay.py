"""Language overlay in load_sources_from_settings (src/parser/ini_parser.py, 2.0 #30).

When a non-English language is selected, the bundled ``languages/<lang>/
global.ini`` is loaded as a synthetic ``language`` source and inserted into
the merge hierarchy just before ``user`` (or appended when there is no user
entry), so translated keys override English while user edits still win and
keys missing from the translation fall back to the English base.

Degradation paths are locked too: a missing overlay file or one that parses
empty must leave the hierarchy untouched (English-only), never raise, and
English itself must never gain an overlay source.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.parser.ini_parser import load_sources_from_settings  # noqa: E402
from src.utils.settings import AppSettings  # noqa: E402

pytestmark = pytest.mark.unit


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Hermetic AppSettings for load_sources_from_settings: a real base.ini
    on disk, global+user sources, no enhancements, French selected."""
    base_ini = tmp_path / "base.ini"
    base_ini.write_text(
        "vehicle_NameHunter=Drake Cutlass Black\nstatus_Ready=Ready\n",
        encoding="utf-8",
    )
    cache = tmp_path / "cache"
    cache.mkdir()

    paths = {
        AppSettings.SOURCE_GLOBAL: str(base_ini),
        AppSettings.SOURCE_USER: str(tmp_path / "user.ini"),  # absent: first run
    }
    monkeypatch.setattr(
        AppSettings, "get_merge_hierarchy",
        staticmethod(lambda: [AppSettings.SOURCE_GLOBAL, AppSettings.SOURCE_USER]),
    )
    monkeypatch.setattr(AppSettings, "get_cache_dir", staticmethod(lambda: cache))
    monkeypatch.setattr(AppSettings, "is_source_enabled", staticmethod(lambda name: True))
    monkeypatch.setattr(
        AppSettings, "get_source_path", staticmethod(lambda name: paths.get(name, ""))
    )
    monkeypatch.setattr(
        AppSettings, "get_enabled_enhancement_categories", staticmethod(lambda: set())
    )
    monkeypatch.setattr(
        AppSettings, "get_selected_language", staticmethod(lambda: "french")
    )

    overlay = tmp_path / "languages" / "french" / "global.ini"
    overlay.parent.mkdir(parents=True)
    overlay.write_text("vehicle_NameHunter=Drake Cutlass Noir\n", encoding="utf-8")
    monkeypatch.setattr(
        AppSettings,
        "get_language_global_ini_path",
        staticmethod(lambda lang=None: overlay if overlay.exists() else None),
    )
    return {"overlay": overlay, "tmp": tmp_path, "monkeypatch": monkeypatch}


def test_overlay_loads_as_language_source(env):
    sources, hierarchy, _ = load_sources_from_settings()
    assert sources["language"] == {"vehicle_NameHunter": "Drake Cutlass Noir"}


def test_overlay_inserted_just_before_user(env):
    _, hierarchy, _ = load_sources_from_settings()
    assert hierarchy == ["global", "language", "user"]


def test_overlay_appended_when_no_user_in_hierarchy(env):
    env["monkeypatch"].setattr(
        AppSettings, "get_merge_hierarchy",
        staticmethod(lambda: [AppSettings.SOURCE_GLOBAL]),
    )
    _, hierarchy, _ = load_sources_from_settings()
    assert hierarchy == ["global", "language"]


def test_missing_overlay_file_degrades_to_english_only(env):
    env["overlay"].unlink()  # fixture's path helper now returns None
    sources, hierarchy, _ = load_sources_from_settings()
    assert "language" not in sources
    assert hierarchy == ["global", "user"]


def test_empty_overlay_parse_degrades_to_english_only(env):
    env["overlay"].write_text("", encoding="utf-8")
    sources, hierarchy, _ = load_sources_from_settings()
    assert "language" not in sources
    assert hierarchy == ["global", "user"]


def test_english_never_gains_an_overlay(env):
    env["monkeypatch"].setattr(
        AppSettings, "get_selected_language", staticmethod(lambda: "english")
    )
    sources, hierarchy, _ = load_sources_from_settings()
    assert "language" not in sources
    assert hierarchy == ["global", "user"]


def test_english_base_still_loaded_alongside_overlay(env):
    sources, _, _ = load_sources_from_settings()
    assert sources["global"]["status_Ready"] == "Ready"
