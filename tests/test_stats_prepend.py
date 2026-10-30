"""Stats-above-description toggle (#153).

Covers the AppSettings round-trip and the append_enhancements prepend mode
(stats block leads, plain divider, then the prose blurb).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from PyQt6.QtCore import QSettings

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.settings import AppSettings  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.fixture(scope="module")
def gen_module():
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "generate_enhancements_ini.py"
    spec = importlib.util.spec_from_file_location(
        "generate_enhancements_ini_prepend_test", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    shared = QSettings(str(tmp_path / "reg.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(AppSettings, "settings", staticmethod(lambda: shared))


def test_stats_prepend_defaults_off(isolated_settings):
    assert AppSettings.get_stats_prepend() is False


def test_stats_prepend_roundtrip(isolated_settings):
    AppSettings.set_stats_prepend(True)
    assert AppSettings.get_stats_prepend() is True
    AppSettings.set_stats_prepend(False)
    assert AppSettings.get_stats_prepend() is False


def test_append_mode_puts_stats_below(gen_module):
    out = gen_module.append_enhancements("Prose blurb", "Crew: 1")
    assert out.startswith("Prose blurb")
    assert "--- STATS ---" in out
    assert out.index("Prose blurb") < out.index("Crew: 1")


def test_prepend_mode_puts_stats_above(gen_module):
    out = gen_module.append_enhancements("Prose blurb", "Crew: 1", prepend=True)
    assert out.startswith("Crew: 1")
    assert "--- STATS ---" not in out          # no header when stats lead
    assert out.index("Crew: 1") < out.index("Prose blurb")


def test_prepend_empty_block_returns_base_unchanged(gen_module):
    assert gen_module.append_enhancements("Prose blurb", "", prepend=True) == "Prose blurb"
