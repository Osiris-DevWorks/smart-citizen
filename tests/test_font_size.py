"""UI font size setting (Config tab → Appearance).

Two layers:

* The AppSettings contract: default is 'medium', round-trips, and any
  unrecognized stored value coerces back to 'medium'.
* ``apply_font_size_env``: Medium leaves no ``QT_SCALE_FACTOR`` behind, so
  the default looks exactly as before; Small and Large set one; a factor
  the user set themselves is left alone; a factor we set (inherited by the
  process a restart starts) is ours to change, including back to Medium.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from PyQt6.QtCore import QSettings  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from src.utils.settings import AppSettings  # noqa: E402
from src.utils.ui_scale import (  # noqa: E402
    FONT_SCALE_FACTORS, QT_SCALE_ENV, apply_font_size_env,
)

pytestmark = [pytest.mark.unit]


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    shared = QSettings(str(tmp_path / "reg.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(AppSettings, "settings", staticmethod(lambda: shared))
    return shared


# ── Settings contract ───────────────────────────────────────────────────────

def test_default_is_medium(isolated_settings):
    assert AppSettings.get_font_size() == AppSettings.FONT_SIZE_MEDIUM


@pytest.mark.parametrize("size", AppSettings.FONT_SIZES)
def test_roundtrip(isolated_settings, size):
    AppSettings.set_font_size(size)
    assert AppSettings.get_font_size() == size


def test_unknown_stored_value_coerces_to_medium(isolated_settings):
    isolated_settings.setValue(AppSettings.FONT_SIZE, "huge")
    assert AppSettings.get_font_size() == AppSettings.FONT_SIZE_MEDIUM


def test_set_unknown_value_stores_medium(isolated_settings):
    AppSettings.set_font_size("huge")
    assert isolated_settings.value(AppSettings.FONT_SIZE) == AppSettings.FONT_SIZE_MEDIUM


def test_every_size_has_a_scale_factor():
    assert set(FONT_SCALE_FACTORS) == set(AppSettings.FONT_SIZES)
    assert FONT_SCALE_FACTORS[AppSettings.FONT_SIZE_MEDIUM] == 1.0
    assert (FONT_SCALE_FACTORS[AppSettings.FONT_SIZE_SMALL]
            < 1.0 < FONT_SCALE_FACTORS[AppSettings.FONT_SIZE_LARGE])


# ── apply_font_size_env ─────────────────────────────────────────────────────

def test_medium_sets_nothing():
    env: dict = {}
    assert apply_font_size_env(AppSettings.FONT_SIZE_MEDIUM, env) == 1.0
    assert env == {}


@pytest.mark.parametrize("size", [AppSettings.FONT_SIZE_SMALL, AppSettings.FONT_SIZE_LARGE])
def test_small_and_large_set_the_qt_scale(size):
    env: dict = {}
    factor = apply_font_size_env(size, env)
    assert factor == FONT_SCALE_FACTORS[size]
    assert float(env[QT_SCALE_ENV]) == factor


def test_users_own_scale_is_left_alone():
    env = {QT_SCALE_ENV: "1.5"}
    assert apply_font_size_env(AppSettings.FONT_SIZE_LARGE, env) is None
    assert env == {QT_SCALE_ENV: "1.5"}


def test_inherited_scale_of_ours_can_go_back_to_medium():
    # A restart hands our environment to the new process.
    env: dict = {}
    apply_font_size_env(AppSettings.FONT_SIZE_LARGE, env)
    apply_font_size_env(AppSettings.FONT_SIZE_MEDIUM, env)
    assert env == {}


def test_inherited_scale_of_ours_can_change_size():
    env: dict = {}
    apply_font_size_env(AppSettings.FONT_SIZE_LARGE, env)
    apply_font_size_env(AppSettings.FONT_SIZE_SMALL, env)
    assert float(env[QT_SCALE_ENV]) == FONT_SCALE_FACTORS[AppSettings.FONT_SIZE_SMALL]


def test_unknown_size_is_medium():
    env: dict = {}
    assert apply_font_size_env("huge", env) == 1.0
    assert env == {}
