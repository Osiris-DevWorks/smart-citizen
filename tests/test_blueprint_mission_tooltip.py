"""#347: the Blueprint Tracker's mission tooltip lists one mission per line.

Comma-joined, a popular item was unreadable: the R97 Shotgun appears in ~37
mission bodies, so the tooltip was a single run of text a player had to parse
word by word to find which contract drops it.

`_make_blueprint_item` needs a QApplication (it builds a QListWidgetItem) but
no window and no settings beyond the show-tags flag, so it's driven on a
lightweight stub self.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from src.gui.blueprint_tracker_tab import BlueprintTrackerTab  # noqa: E402
from src.utils.blueprint_meta import BlueprintItem  # noqa: E402
from src.utils.settings import AppSettings  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.fixture(autouse=True)
def _no_tag_display(monkeypatch):
    """Display text isn't under test; keep it the bare name."""
    monkeypatch.setattr(
        AppSettings, "get_blueprint_show_tags", staticmethod(lambda: False)
    )


class _Stub:
    """Carries only what _make_blueprint_item reads."""

    _make_blueprint_item = BlueprintTrackerTab._make_blueprint_item

    def __init__(self, meta):
        self._blueprint_meta = meta


def _item(missions, **kw):
    meta = {"Ferron": BlueprintItem(name="Ferron", missions=frozenset(missions), **kw)}
    return _Stub(meta)._make_blueprint_item("Ferron")


def test_each_mission_on_its_own_line(qapp):
    tip = _item({"Crew hasn't checked in", "Missing mining team"}).toolTip()
    lines = tip.splitlines()
    assert lines[0].rstrip(": ").endswith("Missions") or lines[0].endswith(":")
    assert "  • Crew hasn't checked in" in lines
    assert "  • Missing mining team" in lines


def test_missions_are_sorted(qapp):
    tip = _item({"Zeta run", "Alpha run", "Mid run"}).toolTip()
    listed = [ln for ln in tip.splitlines() if ln.startswith("  • ")]
    assert listed == ["  • Alpha run", "  • Mid run", "  • Zeta run"]


def test_label_is_not_duplicated_onto_the_first_mission(qapp):
    """The old format put the first mission on the label's own line. The
    label must now stand alone, with every mission below it."""
    tip = _item({"Crew hasn't checked in"}).toolTip()
    first = tip.splitlines()[0]
    assert "Crew hasn't checked in" not in first


def test_a_long_mission_list_stays_one_per_line(qapp):
    """The R97 Shotgun case: many missions must not collapse back to a run."""
    missions = {f"Mission {i:02}" for i in range(37)}
    tip = _item(missions).toolTip()
    listed = [ln for ln in tip.splitlines() if ln.startswith("  • ")]
    assert len(listed) == 37
    assert ", " not in tip


def test_attrs_still_precede_the_mission_block(qapp):
    """The type/class/size/grade summary keeps its own first line."""
    tip = _item({"Some run"}, type="Mining Laser", size="S0").toolTip()
    lines = tip.splitlines()
    assert "Mining Laser" in lines[0] and "S0" in lines[0]
    assert any(ln.startswith("  • Some run") for ln in lines)


def test_no_missions_means_no_mission_block(qapp):
    tip = _item(set(), type="Shield").toolTip()
    assert "•" not in tip
    assert tip.strip() == "Shield"
