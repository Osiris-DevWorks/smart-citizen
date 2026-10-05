"""Per-field mission-detail toggles (issue #121).

Two layers are covered:

* The AppSettings contract: every field defaults to on (so an unconfigured
  user gets the full mission body exactly as before), set/get round-trips,
  and unknown keys are ignored.
* The generator's show/hide gating. ``_run_gen_missions`` isn't callable
  without a large synthetic ctx, so (as with ``TestCargoBpTitleDemotion`` in
  test_blueprint_pools.py) these tests drive a replica of the exact
  ``if _show(field): details_lines.append(...)`` structure. The replica is
  kept line-for-line faithful to the generator block it mirrors.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PyQt6.QtCore import QSettings

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from utils.settings import AppSettings  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    """Back AppSettings with one shared file-scoped QSettings instance (a single
    instance so set-then-get is consistent; see #123)."""
    shared = QSettings(str(tmp_path / "reg.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(AppSettings, "settings", staticmethod(lambda: shared))


# ── Settings contract ──────────────────────────────────────────────────────

def test_defaults_all_on(isolated_settings):
    fields = AppSettings.get_mission_detail_fields()
    assert set(fields) == set(AppSettings.MISSION_FIELD_KEYS)
    assert all(fields.values()), "every mission-detail field must default to on"


def test_set_get_roundtrip(isolated_settings):
    AppSettings.set_mission_detail_field("blueprints", False)
    AppSettings.set_mission_detail_field("spawns", False)
    fields = AppSettings.get_mission_detail_fields()
    assert fields["blueprints"] is False
    assert fields["spawns"] is False
    # Untouched fields stay on.
    assert fields["mission_type"] is True
    assert fields["difficulty"] is True
    assert fields["reputation"] is True


def test_unknown_key_ignored(isolated_settings):
    AppSettings.set_mission_detail_field("not_a_field", False)
    fields = AppSettings.get_mission_detail_fields()
    assert "not_a_field" not in fields
    assert all(fields.values())


# ── Generator gating (replica of the _run_gen_missions DETAILS block) ───────

def _render(fields: dict, *, difficulty=True, spawns=("Spawn: 3",),
            tiers=1, has_bp=True, rs_lines=()) -> tuple[list[str], bool]:
    """Replica of the generator's per-field gating for the mission DETAILS
    body. Returns (detail_lines, blueprint_section_shown). `fields` maps
    field -> bool; missing defaults to on, exactly like ``_show`` in
    _run_gen_missions.

    2.2.0: the mission-TITLE [BP]/[ACE]/rep-xp tags moved to their own
    independent settings group (AppSettings.get_mission_title_tags(), gated
    by ``_show_title_tag`` in the generator) — see test_mission_title_tags.py.
    This replica now covers ONLY the body fields ``_show`` still gates,
    including the standalone "resource_signatures" field that gates the
    Battaglia "Resource Signatures:" breakdown (independent of the
    mission-TITLE "rs" tag); see test_battaglia_mineable_rs.py for the
    desc-keyed ore-list dict and _format_rs_details_lines in the real
    generator that together produce ``rs_lines`` here."""
    def _show(f):
        return bool(fields.get(f, True))

    lines: list[str] = []
    if _show("mission_type"):
        lines.append("Mission Type: Combat")
    if _show("difficulty") and difficulty:
        lines.append("Difficulty (1-7): 4")
    if _show("resource_signatures") and rs_lines:
        lines.extend(rs_lines)
    if _show("spawns"):
        lines.extend(spawns)
    if _show("reputation"):
        if tiers == 1:
            lines.append("Rep: +500")
        elif tiers > 1:
            lines.append("Neutral: +500 Rep")
            lines.append("Friendly: +900 Rep")
    bp_shown = has_bp and _show("blueprints")
    if bp_shown:
        lines.append("Blueprint Reward: Guaranteed")
    return lines, bp_shown


def test_all_on_emits_every_field():
    lines, bp = _render({})  # empty config -> all default on
    assert any("Mission Type" in s for s in lines)
    assert any("Difficulty" in s for s in lines)
    assert any("Spawn" in s for s in lines)
    assert any("Rep" in s for s in lines)
    assert bp is True


@pytest.mark.parametrize("field,needle", [
    ("mission_type", "Mission Type"),
    ("difficulty", "Difficulty"),
    ("spawns", "Spawn"),
    ("reputation", "Rep"),
])
def test_each_field_off_omits_its_line(field, needle):
    lines, _ = _render({field: False})
    assert not any(needle in s for s in lines), f"{field} off should omit its line"


def test_reputation_off_omits_both_tier_branches():
    lines, _ = _render({"reputation": False}, tiers=3)
    assert not any("Rep" in s for s in lines)


def test_blueprints_off_omits_blueprint_section():
    lines, bp = _render({"blueprints": False})
    assert bp is False
    assert not any("Blueprint" in s for s in lines)


# ── Battaglia "Resource Signatures" breakdown in the DETAILS body ───────────

def test_rs_breakdown_included_when_present():
    lines, _ = _render({}, rs_lines=[
        "Resource Signatures:", "<EM4>Savrilium</EM4>: 3200 - 6400", "<EM4>Ice</EM4>: 4300 - 8600",
    ])
    assert "Resource Signatures:" in lines
    assert "<EM4>Savrilium</EM4>: 3200 - 6400" in lines
    assert "<EM4>Ice</EM4>: 4300 - 8600" in lines


def test_rs_breakdown_omitted_when_no_match_for_this_mission():
    # Most missions aren't Battaglia scan/mining contracts, so an empty
    # rs_lines (no desc-key match) means nothing gets appended.
    lines, _ = _render({}, rs_lines=[])
    assert not any("Resource" in s for s in lines)


def test_rs_breakdown_omitted_when_field_off():
    # The "resource_signatures" mission-detail field is independent of the
    # mission-TITLE "rs" General Tags toggle (test_mission_title_tags.py).
    lines, _ = _render({"resource_signatures": False}, rs_lines=[
        "Resource Signatures:", "<EM4>Ice</EM4>: 4300 - 8600",
    ])
    assert not any("Resource" in s for s in lines)
