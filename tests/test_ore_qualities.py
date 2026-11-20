"""The ore quality tiers the SCO Order tab's sliders snap to (Amr, 3.1.0)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils import crafting_order as co  # noqa: E402
from src.utils import ore_qualities as oq  # noqa: E402

pytestmark = [pytest.mark.unit]


def test_every_row_of_the_table_is_read():
    assert len(oq.QUALITY_TIERS) == 36
    assert oq.QUALITY_TIERS["gold"] == tuple(
        zip(oq.TIER_NAMES, (359, 553, 644, 786, 864, 916, 959, 1000))
    )
    for tiers in oq.QUALITY_TIERS.values():
        values = [v for _t, v in tiers]
        assert values == sorted(values) and values[-1] == 1000
        assert tiers[-1][0] == "Perfect"


def test_a_short_row_is_missing_its_lowest_tiers():
    """Carinite has no F tier: its seven numbers start at E."""
    carinite = oq.QUALITY_TIERS["carinite"]
    assert [t for t, _v in carinite] == ["E", "D", "C", "B", "A", "S", "Perfect"]
    assert carinite[0] == ("E", 554)


def test_a_pasted_table_is_parsed_the_same_way():
    tiers = oq.parse_quality_table("Ore F Tier E Tier\nNew Ore 100 200 300 400 500 600 700 1000\n")
    assert list(tiers) == ["newore"] and tiers["newore"][0] == ("F", 100)


@pytest.mark.parametrize(
    "names, expected",
    [
        (["pressurized_ice"], "pressurizedice"),
        (["ice"], "pressurizedice"),
        (["aluminium"], "aluminum"),
        (["savrillium"], "savrilium"),
        (["item:abc", "Hadanite"], "hadanite"),
        (["oro", "Gold"], "gold"),
    ],
)
def test_names_and_spellings_are_matched(names, expected):
    assert oq.quality_tiers(names) == oq.QUALITY_TIERS[expected]


def test_an_unknown_material_has_no_tiers():
    assert oq.quality_tiers(["unknown:abc", "Widget"]) is None
    assert oq.tier_of(None, 500) == ""
    assert oq.tier_of(oq.QUALITY_TIERS["gold"], 786) == "C"


class TestClampQuality:
    STEPS = (359, 553, 644, 786, 864, 916, 959, 1000)

    def test_without_steps_any_quality_in_range(self):
        assert co.clamp_quality(612) == 612
        assert co.clamp_quality(-5) == 0 and co.clamp_quality(2000) == 1000
        assert co.clamp_quality(100, 300) == 300

    def test_snaps_to_the_nearest_step(self):
        assert co.clamp_quality(500, 0, self.STEPS) == 553
        assert co.clamp_quality(0, 0, self.STEPS) == 359
        assert co.clamp_quality(2000, 0, self.STEPS) == 1000

    def test_a_tie_takes_the_higher_step(self):
        assert co.clamp_quality(603, 0, (553, 653)) == 653

    def test_never_under_the_slot_minimum(self):
        assert co.clamp_quality(560, 600, self.STEPS) == 644
        # No step that high but Perfect: Perfect.
        assert co.clamp_quality(0, 990, self.STEPS) == 1000

    def test_a_move_that_snaps_back_takes_the_next_step(self):
        assert co.clamp_quality(600, 0, self.STEPS, current=553) == 644
        assert co.clamp_quality(500, 0, self.STEPS, current=553) == 359
        assert co.clamp_quality(553, 0, self.STEPS, current=553) == 553
        assert co.clamp_quality(1000, 0, self.STEPS, current=1000) == 1000

    def test_new_and_loaded_lines_snap(self):
        bp = {"k": "x", "s": [{"mat": "gold", "min": 0}], "p": []}
        co.attach_quality_tiers([bp], lambda key: [key])
        assert co.slot_steps(bp["s"][0]) == self.STEPS
        assert co.new_line(bp).q == [553]
        lines = co.load_order([{"key": "x", "count": 1, "q": [900]}], {"x": bp})
        assert lines[0].q == [916]

    def test_attach_leaves_unknown_materials_free(self):
        bp = {"k": "x", "s": [{"mat": "unknown:1", "min": 0, "tiers": "stale"}], "p": []}
        co.attach_quality_tiers([bp], lambda key: [key])
        assert "tiers" not in bp["s"][0] and co.slot_steps(bp["s"][0]) == ()
