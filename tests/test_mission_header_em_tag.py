"""Regression tests for the mission-header emphasis tag option (issue #99).

EM1/EM2 were removed in 1.5.0 because they never render in-game (only
EM3 = underline and EM4 = color do). These tests lock two things:

  * the selectable set is exactly (EM3, EM4), and
  * ``get_mission_header_em_tag`` coerces any stored legacy EM1/EM2 (or
    other junk) back to the default, so a user who previously picked a
    dead tag never has it leak into generated output.

Uses the JsonSettings backend so each test is hermetic, mirroring
test_tag_config_settings.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.json_settings import JsonSettings  # noqa: E402
from src.utils.settings import AppSettings  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.fixture
def json_backend(tmp_path):
    """Swap AppSettings._backend for a tmp JsonSettings so each test is hermetic."""
    saved = AppSettings._backend
    AppSettings._backend = JsonSettings(tmp_path / "config.json")
    yield AppSettings._backend
    AppSettings._backend = saved


def test_em1_em2_not_offered():
    assert AppSettings.MISSION_HEADER_EM_TAGS == ("EM3", "EM4")
    assert "EM1" not in AppSettings.MISSION_HEADER_EM_TAGS
    assert "EM2" not in AppSettings.MISSION_HEADER_EM_TAGS


def test_default_is_em3(json_backend):
    assert AppSettings.get_mission_header_em_tag() == "EM3"


@pytest.mark.parametrize("valid", ["EM3", "EM4"])
def test_valid_tag_passes_through(json_backend, valid):
    AppSettings.set_mission_header_em_tag(valid)
    assert AppSettings.get_mission_header_em_tag() == valid


@pytest.mark.parametrize("legacy", ["EM1", "EM2", "EM0", "nonsense", ""])
def test_legacy_or_junk_coerced_to_default(json_backend, legacy):
    AppSettings.set_mission_header_em_tag(legacy)
    assert AppSettings.get_mission_header_em_tag() == AppSettings.DEFAULT_MISSION_HEADER_EM_TAG
