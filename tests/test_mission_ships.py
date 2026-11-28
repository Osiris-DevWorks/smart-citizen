"""The ships a mission spawns and its cooldown, in MISSION DETAILS.

A ship spawn option asks for ships by tags; the generator matches them
against each ship entity's own tags through the tag tree the extraction
saves (src/utils/dcb_tags.py), so the Hostiles and Friendlies lines list the
ships by name, one heading per variant where a description's contracts
differ. A choice no ship matches shows its tags' names in brackets. Without
the tag tree the lines stay the spawn counts they were. The cooldown comes
from each contract's availability, with its own overrides.

Fabricated tags, ships and contracts throughout, shaped as LIVE's are.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from lxml import etree as ET

pytestmark = pytest.mark.unit

AI = "00000000-0000-0000-0000-0000000000a1"
FACTION = "00000000-0000-0000-0000-0000000000a2"
CRIMINAL = "00000000-0000-0000-0000-0000000000a3"
VANDUUL = "00000000-0000-0000-0000-0000000000a4"
COMBAT = "00000000-0000-0000-0000-0000000000a5"
EASY = "00000000-0000-0000-0000-0000000000a6"
VERY_EASY = "00000000-0000-0000-0000-0000000000a7"
SHIP = "00000000-0000-0000-0000-0000000000b1"
MODEL = "00000000-0000-0000-0000-0000000000b2"
ARROW = "00000000-0000-0000-0000-0000000000b3"
GLADIATOR = "00000000-0000-0000-0000-0000000000b4"
NINETAILS = "00000000-0000-0000-0000-0000000000b5"
IDENTIFIER = "00000000-0000-0000-0000-0000000000c1"
DEFENDERS = "00000000-0000-0000-0000-0000000000c2"
SKILL = "00000000-0000-0000-0000-0000000000c3"
PILOT = "00000000-0000-0000-0000-0000000000c4"
SPAWNING = "00000000-0000-0000-0000-0000000000c5"
GAMEMODE = "00000000-0000-0000-0000-0000000000c6"
PU = "00000000-0000-0000-0000-0000000000c7"

TAGS = {
    AI: ("AI", None),
    FACTION: ("Faction", AI),
    CRIMINAL: ("Criminal", FACTION),
    VANDUUL: ("Vanduul", FACTION),
    NINETAILS: ("Ninetails", FACTION),
    "00000000-0000-0000-0000-0000000000a8": ("Ship", AI),
    COMBAT: ("CombatClass", "00000000-0000-0000-0000-0000000000a8"),
    EASY: ("Easy", COMBAT),
    VERY_EASY: ("VeryEasy", COMBAT),
    SHIP: ("Ship", None),
    MODEL: ("Model", SHIP),
    ARROW: ("Arrow", MODEL),
    GLADIATOR: ("Gladiator", MODEL),
    SPAWNING: ("Spawning", AI),
    IDENTIFIER: ("Identifier", SPAWNING),
    DEFENDERS: ("Defenders", IDENTIFIER),
    GAMEMODE: ("GameMode", SPAWNING),
    PU: ("PU", GAMEMODE),
    SKILL: ("SkillDefinitions", AI),
    PILOT: ("HumanPilot30", SKILL),
}

# (file stem, own tags, name loc key)
SHIPS = [
    ("anvl_arrow_pu_ai_crim", [CRIMINAL, EASY, ARROW, PU], "vehicle_NameANVL_Arrow"),
    (
        "anvl_gladiator_pu_ai_crim",
        [CRIMINAL, EASY, GLADIATOR, PU],
        "vehicle_NameANVL_Gladiator",
    ),
    ("vncl_blade_ai", [VANDUUL, EASY, PU], "vehicle_NameVNCL_Blade"),
    ("anvl_arrow", [ARROW], "vehicle_NameANVL_Arrow"),
]
TARGETS = "TargetSpawnDescriptions_BP"
NL = "\\n"
IN1 = "\u00a0" * 2
IN2 = "\u00a0" * 4
AVAILABILITY = (
    '<defaultAvailability hasPersonalCooldown="1" personalCooldownTime="15" '
    'abandonedCooldownTime="15" />'
)
LOC = {
    "vehicle_NameANVL_Arrow": "Anvil  Arrow",
    "vehicle_NameANVL_Gladiator": "Anvil Gladiator",
    "vehicle_NameVNCL_Blade": "Vanduul Blade",
    "test_title": "Ambush",
    "test_desc": "Take them out.",
    "ped_title": "Patrol",
    "ped_desc": "Walk around.",
}


@pytest.fixture(scope="module")
def gen():
    script = (
        Path(__file__).resolve().parent.parent
        / "scripts"
        / "generate_enhancements_ini.py"
    )
    spec = importlib.util.spec_from_file_location(
        "generate_enhancements_ini_ships_test", script
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def index(gen):
    facts = [(own, key) for _stem, own, key in SHIPS]
    return gen.ShipSpawnIndex(TAGS, facts, LOC)


def _ship(amount: int, tags, negative=()) -> str:
    pos = "".join(f'<Reference value="{t}" />' for t in tags)
    neg = "".join(f'<Reference value="{t}" />' for t in negative)
    return (
        f'<SpawnDescription_Ship concurrentAmount="{amount}" weight="1">'
        f"<tags><tags>{pos}</tags></tags><negativeTags><tags>{neg}</tags></negativeTags>"
        "</SpawnDescription_Ship>"
    )


def _group(name: str, *slots, wrapper: str = "HostileSpawnDescriptions_BP") -> str:
    body = "".join(
        f"<SpawnDescription_ShipOptions><options>{''.join(s)}</options>"
        "</SpawnDescription_ShipOptions>"
        for s in slots
    )
    name_attr = f' Name="{name}"' if name else ""
    return (
        f'<MissionProperty missionVariableName="{wrapper}"><value>'
        "<MissionPropertyValue_ShipSpawnDescriptions><spawnDescriptions>"
        f"<SpawnDescription_ShipGroup{name_attr}><ships>{body}</ships>"
        "</SpawnDescription_ShipGroup></spawnDescriptions>"
        "</MissionPropertyValue_ShipSpawnDescriptions></value></MissionProperty>"
    )


def _npc(name: str, count: int) -> str:
    return (
        f'<SpawnDescription_NPC_Group Name="{name}">'
        f'<autoSpawnSettings maxSpawns="{count}" /></SpawnDescription_NPC_Group>'
    )


class TestShipSpawnIndex:
    def test_a_parent_tag_matches_its_children(self, index):
        names, _label = index.pick([FACTION, EASY], [])
        assert names == ("Anvil Arrow", "Anvil Gladiator", "Vanduul Blade")

    def test_negative_tags_and_each_name_once(self, index):
        assert index.pick([CRIMINAL], [GLADIATOR])[0] == ("Anvil Arrow",)
        assert index.pick([ARROW], [])[0] == ("Anvil Arrow",)

    def test_every_pick_carries_its_type(self, index):
        # The label a Simple summary shows, also when ships match.
        assert index.pick([CRIMINAL, EASY], []) == (
            ("Anvil Arrow", "Anvil Gladiator"),
            "Easy Criminal",
        )

    def test_set_up_tags_pick_nothing(self, index):
        # A group identifier is on no ship and a pilot skill sets the pilot up.
        assert index.pick([DEFENDERS, CRIMINAL, PILOT], []) == index.pick(
            [CRIMINAL], []
        )

    def test_no_match_gives_a_label_from_the_tags(self, index):
        assert index.pick([PU, NINETAILS, VERY_EASY], []) == ((), "Very Easy Ninetails")

    def test_a_label_names_each_word_once(self, gen):
        tags = dict(TAGS, x=("Arrow", SHIP))
        empty = gen.ShipSpawnIndex(tags, [([CRIMINAL], "vehicle_NameANVL_Arrow")], LOC)
        assert empty.pick([ARROW, "x", VANDUUL], []) == ((), "Vanduul Arrow")

    def test_only_set_up_tags_give_neither(self, index):
        assert index.pick([DEFENDERS, PILOT], []) == ((), "")

    def test_false_without_tags_or_ships(self, gen):
        assert not gen.ShipSpawnIndex({}, [([ARROW], "vehicle_NameANVL_Arrow")], LOC)
        assert not gen.ShipSpawnIndex(TAGS, [([ARROW], "missing_key")], LOC)

    def test_a_name_missing_in_the_language_falls_back_to_english(self, gen):
        index = gen.ShipSpawnIndex(
            TAGS,
            [([ARROW], "vehicle_NameANVL_Arrow")],
            {},
            {"vehicle_NameANVL_Arrow": "Anvil Arrow"},
        )
        assert index.pick([ARROW], [])[0] == ("Anvil Arrow",)


class TestShipSpawnFacts:
    def test_the_roots_own_tags_and_the_name(self, gen, tmp_path):
        ships = tmp_path / "spaceships"
        ships.mkdir()
        (ships / "anvl_arrow_pu_ai_crim.xml").write_text(
            '<EntityClassDefinition.ANVL_Arrow><tags><Reference value="a" />'
            '<Reference value="b" /></tags><StaticEntityClassData><X><tags><tags>'
            '<Reference value="nested" /></tags></tags></X></StaticEntityClassData>'
            '<Components><VehicleComponentParams vehicleName="@vehicle_NameANVL_Arrow" />'
            "</Components></EntityClassDefinition.ANVL_Arrow>",
            encoding="utf-8",
        )
        (ships / "aegs_ai_template.xml").write_text(
            '<E><tags><Reference value="a" /></tags><Components>'
            '<VehicleComponentParams vehicleName="@vehicle_NameX" /></Components></E>',
            encoding="utf-8",
        )
        (ships / "no_name.xml").write_text(
            '<E><tags><Reference value="a" /></tags><Components>'
            '<VehicleComponentParams vehicleName="@LOC_UNINITIALIZED" /></Components></E>',
            encoding="utf-8",
        )
        (ships / "broken.xml").write_text("<E><tags>", encoding="utf-8")
        assert gen.build_ship_spawn_facts(ships) == [
            (["a", "b"], "vehicle_NameANVL_Arrow", "anvl_arrow_pu_ai_crim", 0.0)
        ]


class TestShipSize:
    def test_the_bounding_box_volume(self, gen, tmp_path):
        ships = tmp_path / "spaceships"
        ships.mkdir()
        (ships / "big.xml").write_text(
            '<E><tags><Reference value="a" /></tags><Components>'
            '<VehicleComponentParams vehicleName="@vehicle_NameBig">'
            '<maxBoundingBoxSize x="2" y="3" z="4" /></VehicleComponentParams>'
            "</Components></E>",
            encoding="utf-8",
        )
        assert gen.build_ship_spawn_facts(ships) == [
            (["a"], "vehicle_NameBig", "big", 24.0)
        ]


class TestRoster:
    def test_groups_slots_and_choices(self, gen, index):
        wave = _group(
            "Wave1", [_ship(2, [CRIMINAL]), _ship(3, [CRIMINAL])], [_ship(1, [ARROW])]
        )
        targets = _group(
            "", [_ship(1, [VANDUUL]), _ship(1, [GLADIATOR])], wrapper=TARGETS
        )
        xml = (
            f"<C>{wave}{targets}" f"{_npc('Soldier x 2', 2)}{_npc('Soldier B', 3)}</C>"
        )
        roster = gen._extract_spawn_roster(ET.fromstring(xml), index)
        lines = [gen._format_roster_group(g) for g in roster]
        assert lines == [
            "- Hostile Wave: 2-3x of Anvil Arrow or Anvil Gladiator and 1x Anvil Arrow",
            "- Targets: 1x of Anvil Gladiator or Vanduul Blade",
            "- Soldiers x5",
        ]

    def test_identical_groups_add_up(self, gen, index):
        xml = (
            "<C>"
            + _group("Recipient1", [_ship(1, [CRIMINAL])], wrapper="X") * 4
            + "</C>"
        )
        xml = xml.replace("Recipient1", "Recipient")
        roster = gen._extract_spawn_roster(ET.fromstring(xml), index)
        assert [gen._format_roster_group(g) for g in roster] == [
            "- Recipient: 4x of Anvil Arrow or Anvil Gladiator"
        ]

    def test_choices_at_different_amounts(self, gen, index):
        xml = f"<C>{_group('Wave1', [_ship(2, [VANDUUL]), _ship(3, [ARROW])])}</C>"
        roster = gen._extract_spawn_roster(ET.fromstring(xml), index)
        assert gen._format_roster_group(roster[0]) == (
            f"- Hostile Wave, one of:{NL}{IN2}2x Vanduul Blade{NL}{IN2}3x Anvil Arrow"
        )

    def test_a_choice_no_ship_matches_names_its_kind(self, gen, index):
        xml = f"<C>{_group('Wave1', [_ship(1, [NINETAILS, VERY_EASY]), _ship(1, [ARROW])])}</C>"
        roster = gen._extract_spawn_roster(ET.fromstring(xml), index)
        assert gen._format_roster_group(roster[0]) == (
            "- Hostile Wave: 1x of Anvil Arrow or Very Easy Ninetails ship"
        )

    def test_a_group_with_nothing_to_name_is_a_count(self, gen, index):
        xml = f"<C>{_group('Wave1', [_ship(2, [DEFENDERS])])}</C>"
        roster = gen._extract_spawn_roster(ET.fromstring(xml), index)
        assert [gen._format_roster_group(g) for g in roster] == ["- Hostile Wave x2"]

    def test_turrets_objectives_and_unknown_groups_stay_out(self, gen, index):
        xml = (
            f"<C>{_group('Turrets', [_ship(2, [ARROW])])}"
            f"{_group('Probe 1', [_ship(1, [ARROW])], wrapper='X')}"
            f"{_group('Mystery', [_ship(1, [ARROW])], wrapper='X')}</C>"
        )
        assert gen._extract_spawn_roster(ET.fromstring(xml), index) == ()


class TestListJoins:
    def test_two_names_take_no_comma_and_three_take_the_serial_comma(self, gen):
        assert gen._join_words(["A", "B"], "names") == "A or B"
        assert gen._join_words(["A", "B", "C"], "names") == "A, B, or C"
        assert gen._join_words(["A", "B", "C", "D"], "names") == "A, B, C, or D"

    def test_a_language_without_the_serial_comma_leaves_it_out(self, gen):
        from src.utils.enhancement_text import load_table

        gen._TEXT.update(load_table("german"))
        try:
            assert gen._join_words(["A", "B", "C"], "names") == "A, B oder C"
            assert gen._join_words(["A", "B"], "names") == "A oder B"
        finally:
            gen._TEXT.clear()

    def test_a_slot_of_three_names(self, gen, index):
        xml = f"<C>{_group('Wave1', [_ship(1, [FACTION, EASY])])}</C>"
        roster = gen._extract_spawn_roster(ET.fromstring(xml), index)
        assert gen._format_roster_group(roster[0]) == (
            "- Hostile Wave: 1x of Anvil Arrow, Anvil Gladiator, or Vanduul Blade"
        )


class TestLayout:
    """One choice per line where a group has choices or a long list, one line
    for a simple group, and numbered waves."""

    def test_a_long_list_breaks_the_group_into_lines(self, gen, index):
        xml = f"<C>{_group('Wave1', [_ship(2, [FACTION, EASY])], [_ship(1, [ARROW])])}</C>"
        roster = gen._extract_spawn_roster(ET.fromstring(xml), index)
        assert gen._format_roster_group(roster[0]) == (
            f"- Hostile Wave:{NL}{IN1}2x of Anvil Arrow, Anvil Gladiator, or Vanduul Blade"
            f"{NL}{IN1}and 1x Anvil Arrow"
        )

    def test_a_second_slot_with_choices_is_and_one_of(self, gen, index):
        group = _group(
            "Wave1",
            [_ship(2, [VANDUUL]), _ship(3, [ARROW])],
            [_ship(1, [GLADIATOR]), _ship(2, [VANDUUL])],
            [_ship(1, [ARROW])],
        )
        roster = gen._extract_spawn_roster(ET.fromstring(f"<C>{group}</C>"), index)
        assert gen._format_roster_group(roster[0]).split(NL) == [
            "- Hostile Wave, one of:",
            f"{IN2}2x Vanduul Blade",
            f"{IN2}3x Anvil Arrow",
            f"{IN1}and one of:",
            f"{IN2}1x Anvil Gladiator",
            f"{IN2}2x Vanduul Blade",
            f"{IN1}and 1x Anvil Arrow",
        ]

    def test_simple_parts_join_with_and(self, gen, index):
        three = _group(
            "Wave1", [_ship(2, [ARROW])], [_ship(1, [GLADIATOR])], [_ship(3, [VANDUUL])]
        )
        roster = gen._extract_spawn_roster(ET.fromstring(f"<C>{three}</C>"), index)
        assert gen._format_roster_group(roster[0]) == (
            "- Hostile Wave: 2x Anvil Arrow, 1x Anvil Gladiator, and 3x Vanduul Blade"
        )

    def test_two_or_more_waves_are_numbered_and_a_lone_wave_is_not(self, gen):
        one = (gen.SPAWN_HOSTILE, "Hostile Wave", (((1, ("Anvil Arrow",), ""),),))
        two = (gen.SPAWN_HOSTILE, "Hostile Wave", (((2, ("Vanduul Blade",), ""),),))
        target = (gen.SPAWN_HOSTILE, "Targets", 1)
        assert gen._roster_block("Hostiles", (one, target, two)) == [
            "<EM4>Hostiles:</EM4>",
            "- Wave 1: 1x Anvil Arrow",
            "- Targets x1",
            "- Wave 2: 2x Vanduul Blade",
        ]
        assert (
            gen._roster_block("Hostiles", (one,))[1] == "- Hostile Wave: 1x Anvil Arrow"
        )

    def test_a_kind_already_ending_in_ship_is_not_doubled(self, gen):
        assert gen._ship_kind("Easy Criminal Large Combat Ship") == (
            "Easy Criminal Large Combat Ship"
        )
        assert gen._ship_kind("Very Easy Ninetails") == "Very Easy Ninetails ship"

    def test_the_layout_words_follow_the_language(self, gen, index):
        from src.utils.enhancement_text import load_table

        xml = f"<C>{_group('Wave1', [_ship(2, [VANDUUL]), _ship(3, [CRIMINAL])])}</C>"
        roster = gen._extract_spawn_roster(ET.fromstring(xml), index)
        gen._TEXT.update(load_table("german"))
        try:
            text = gen._format_roster_group(roster[0], gen._t("Wave {n}", n=1))
        finally:
            gen._TEXT.clear()
        assert text.split(NL) == [
            "- Welle 1, eines von:",
            f"{IN2}2x Vanduul Blade",
            f"{IN2}3x aus Anvil Arrow oder Anvil Gladiator",
        ]


class TestShipTypes:
    """A pool of more than 3 ships is its type in the waves, and each type is
    named once under Ship types, biggest first by bounding-box volume: up to
    Ships per type (8 by default) all listed, beyond that (n - 2) / 2 at each
    end with the rest counted."""

    POOL = "00000000-0000-0000-0000-0000000000e1"

    def _index(self, gen, count, per_type=8):
        tags = dict(TAGS)
        tags[self.POOL] = ("Pool", FACTION)
        ships = [
            ([self.POOL, EASY], f"vehicle_Name{i:02}", f"ship{i:02}", float(i))
            for i in range(count)
        ]
        loc = {f"vehicle_Name{i:02}": f"Ship {i:02}" for i in range(count)}
        return gen.ShipSpawnIndex(tags, ships, loc, per_type=per_type)

    def _block(self, gen, index, *groups):
        """The Hostiles block for *groups* and the Ship types after it, as
        _variant_detail_lines writes them."""
        gen._set_ship_spawns(index)
        try:
            pools = gen._ship_pools(groups)
            lines = gen._roster_block("Hostiles", groups, pools=pools)
            return lines + gen._ship_types_block(pools)
        finally:
            gen._set_ship_spawns(None)

    def _pool(self, gen, index, amount=2, label="Targets"):
        names, kind = index.pick([self.POOL, EASY], [])
        return (gen.SPAWN_HOSTILE, label, (((amount, names, kind),),))

    def test_a_big_pool_is_its_type_named_once_under_ship_types(self, gen):
        index = self._index(gen, 4)
        assert self._block(gen, index, self._pool(gen, index)) == [
            "<EM4>Hostiles:</EM4>",
            "- Targets: 2x Easy Pool ship",
            "<EM4>Ship types:</EM4>",
            "- Easy Pool ship: Ship 03, Ship 02, Ship 01, Ship 00",
        ]

    def _types_line(self, gen, count, per_type):
        index = self._index(gen, count, per_type)
        return self._block(gen, index, self._pool(gen, index))[-1]

    def test_up_to_eight_ships_are_listed_and_nine_are_counted(self, gen):
        assert self._types_line(gen, 8, 8) == (
            "- Easy Pool ship: Ship 07, Ship 06, Ship 05, Ship 04, Ship 03,"
            " Ship 02, Ship 01, Ship 00"
        )
        assert self._types_line(gen, 9, 8) == (
            "- Easy Pool ship: Ship 08, Ship 07, Ship 06, (\u2026 3 others),"
            " Ship 02, Ship 01, Ship 00"
        )

    def test_four_keeps_one_ship_at_each_end(self, gen):
        assert self._types_line(gen, 4, 4) == (
            "- Easy Pool ship: Ship 03, Ship 02, Ship 01, Ship 00"
        )
        assert self._types_line(gen, 11, 4) == (
            "- Easy Pool ship: Ship 10, (\u2026 9 others), Ship 00"
        )

    def test_sixteen_keeps_seven_at_each_end(self, gen):
        line = self._types_line(gen, 17, 16)
        assert line.startswith("- Easy Pool ship: Ship 16, Ship 15, Ship 14,")
        assert "Ship 10, (\u2026 3 others), Ship 06," in line
        assert line.endswith("Ship 01, Ship 00")

    def test_all_lists_every_ship(self, gen):
        line = self._types_line(gen, 77, 0)
        assert "others" not in line
        assert line.count("Ship ") == 77

    def test_the_setting_is_read_as_a_number_of_ships(self, gen):
        assert gen._ships_per_type("all") == 0
        assert gen._ships_per_type("All") == 0
        assert gen._ships_per_type("16") == 16
        assert gen._ships_per_type(128) == 128
        assert gen._ships_per_type("nonsense") == 8
        assert gen._ships_per_type(2) == 8
        assert gen._ships_per_type(None) == 8

    def test_three_ships_are_still_listed(self, gen):
        index = self._index(gen, 3)
        assert self._block(gen, index, self._pool(gen, index)) == [
            "<EM4>Hostiles:</EM4>",
            "- Targets: 2x of Ship 00, Ship 01, or Ship 02",
        ]

    def test_a_type_named_in_two_groups_is_listed_once(self, gen):
        index = self._index(gen, 4)
        lines = self._block(
            gen,
            index,
            self._pool(gen, index, 2, "Hostile Wave"),
            self._pool(gen, index, 5, "Hostile Wave"),
        )
        assert lines[1:3] == ["- Wave 1: 2x Easy Pool ship", "- Wave 2: 5x Easy Pool ship"]
        assert lines.count("<EM4>Ship types:</EM4>") == 1
        assert lines[-1] == "- Easy Pool ship: Ship 03, Ship 02, Ship 01, Ship 00"

    def test_two_pools_of_one_type_with_other_ships_are_numbered(self, gen):
        # The review's ORS_ShipWaveAt_Desc: five pools whose tags differ only
        # in what they leave out all read "Criminal ship", listed as one.
        index = self._index(gen, 6)
        names, kind = index.pick([self.POOL, EASY], [])
        first = (gen.SPAWN_HOSTILE, "Targets", (((1, names[:4], kind),),))
        second = (gen.SPAWN_HOSTILE, "Targets", (((1, names[2:], kind),),))
        assert self._block(gen, index, first, second) == [
            "<EM4>Hostiles:</EM4>",
            "- Wave 1: 1x Easy Pool ship 1",
            "- Wave 2: 1x Easy Pool ship 2",
            "<EM4>Ship types:</EM4>",
            "- Easy Pool ship 1: Ship 03, Ship 02, Ship 01, Ship 00",
            "- Easy Pool ship 2: Ship 05, Ship 04, Ship 03, Ship 02",
        ]

    def test_two_pools_with_the_same_ships_are_one(self, gen):
        index = self._index(gen, 4)
        names, kind = index.pick([self.POOL, EASY], [])
        lines = self._block(
            gen, index,
            (gen.SPAWN_HOSTILE, "Hostile Wave", (((1, names, kind),),)),
            (gen.SPAWN_HOSTILE, "Targets", (((2, names, kind),),)),
        )
        assert lines[-2:] == [
            "<EM4>Ship types:</EM4>",
            "- Easy Pool ship: Ship 03, Ship 02, Ship 01, Ship 00",
        ]

    def test_a_pool_with_no_type_is_listed_and_not_a_ship_type(self, gen):
        index = self._index(gen, 4)
        names, _ = index.pick([self.POOL, EASY], [])
        group = (gen.SPAWN_HOSTILE, "Targets", (((1, names, ""),),))
        lines = self._block(gen, index, group)
        assert lines[1].startswith("- Targets:") and "Ship 03" in "\n".join(lines)
        assert "<EM4>Ship types:</EM4>" not in lines

    def test_the_type_counts_as_one_name_for_the_one_line_rule(self, gen):
        index = self._index(gen, 11)
        names, label = index.pick([self.POOL, EASY], [])
        gen._set_ship_spawns(index)
        try:
            text = gen._format_roster_group(
                (
                    gen.SPAWN_HOSTILE,
                    "Hostile Wave",
                    (((2, names, label),), ((1, ("Ship 03",), ""),)),
                )
            )
        finally:
            gen._set_ship_spawns(None)
        assert text == "- Hostile Wave: 2x Easy Pool ship and 1x Ship 03"

    def test_the_generation_takes_the_setting(self, gen, tmp_path):
        records, forge = _records(tmp_path)
        ctx = {
            "records": records,
            "forge_dir": forge,
            "loc": LOC,
            "tag_loc": LOC,
            "ships_per_type": "all",
        }
        assert gen._load_ship_spawns(ctx).per_type == 0
        assert gen._load_ship_spawns(dict(ctx, ships_per_type="16")).per_type == 16
        del ctx["ships_per_type"]
        assert gen._load_ship_spawns(ctx).per_type == 8  # the app's default

    def test_the_variant_lines_end_with_the_ship_types_after_friendlies(self, gen):
        index = self._index(gen, 4)
        friend = (gen.SPAWN_FRIENDLY, "Escorts", (((1, ("Anvil Arrow",), ""),),))
        variant = TestVariants()._variant(gen, (self._pool(gen, index), friend))
        gen._set_ship_spawns(index)
        try:
            lines, _ = gen._variant_detail_lines([variant], True, False)
        finally:
            gen._set_ship_spawns(None)
        assert lines == [
            "<EM4>Hostiles:</EM4>",
            "- Targets: 2x Easy Pool ship",
            "<EM4>Friendlies:</EM4>",
            "- Escorts: 1x Anvil Arrow",
            "<EM4>Ship types:</EM4>",
            "- Easy Pool ship: Ship 03, Ship 02, Ship 01, Ship 00",
        ]


class TestWaves:
    """Groups numbered Wave 1, Wave 2, ... in a roster block: hostile waves,
    and target groups in a block with no wave."""

    def _group(self, gen, label, name):
        return (gen.SPAWN_HOSTILE, label, (((1, (name,), ""),),))

    def test_target_groups_alone_are_numbered(self, gen):
        a = self._group(gen, "Targets", "Anvil Arrow")
        b = self._group(gen, "Targets", "Vanduul Blade")
        assert gen._roster_block("Hostiles", (a, b)) == [
            "<EM4>Hostiles:</EM4>",
            "- Wave 1: 1x Anvil Arrow",
            "- Wave 2: 1x Vanduul Blade",
        ]

    def test_a_lone_target_group_keeps_its_label(self, gen):
        a = self._group(gen, "Targets", "Anvil Arrow")
        assert gen._roster_block("Hostiles", (a,))[1] == "- Targets: 1x Anvil Arrow"

    def test_targets_beside_a_wave_are_numbered_after_their_label(self, gen):
        # They are what the wave guards, so they do not become waves, but two
        # lines with one label are told apart.
        wave = self._group(gen, "Hostile Wave", "Anvil Arrow")
        a = self._group(gen, "Targets", "Vanduul Blade")
        b = self._group(gen, "Targets", "Anvil Gladiator")
        assert gen._roster_block("Hostiles", (wave, a, b))[1:] == [
            "- Hostile Wave: 1x Anvil Arrow",
            "- Targets 1: 1x Vanduul Blade",
            "- Targets 2: 1x Anvil Gladiator",
        ]

    def test_a_lone_target_beside_a_wave_keeps_its_label(self, gen):
        wave = self._group(gen, "Hostile Wave", "Anvil Arrow")
        a = self._group(gen, "Targets", "Vanduul Blade")
        assert gen._roster_block("Hostiles", (wave, a))[1:] == [
            "- Hostile Wave: 1x Anvil Arrow",
            "- Targets: 1x Vanduul Blade",
        ]

    def test_any_other_label_that_repeats_is_numbered(self, gen):
        # The review's CleanAir_EscortShip_Easy_desc showed two
        # "- Reinforcements:" lines.
        a = self._group(gen, "Reinforcements", "Anvil Arrow")
        b = self._group(gen, "Reinforcements", "Anvil Gladiator")
        assert gen._roster_block("Hostiles", (a, b))[1:] == [
            "- Reinforcements 1: 1x Anvil Arrow",
            "- Reinforcements 2: 1x Anvil Gladiator",
        ]

    def test_a_many_line_target_group_is_numbered_too(self, gen):
        names = ("Anvil Arrow", "Anvil Gladiator", "Vanduul Blade", "Vanduul Glaive")
        a = (gen.SPAWN_HOSTILE, "Targets", (((2, names, ""),), ((1, ("Ship X",), ""),)))
        b = self._group(gen, "Targets", "Vanduul Scythe")
        lines = gen._roster_block("Hostiles", (a, b))
        assert lines[1].split(NL)[0] == "- Wave 1:"
        assert lines[-1] == "- Wave 2: 1x Vanduul Scythe"


def _prop(name: str, inner: str = "", **attrs) -> str:
    extra = "".join(f' {k}="{v}"' for k, v in attrs.items())
    return (
        f'<MissionProperty missionVariableName="{name}"{extra}>'
        f"<value>{inner}</value></MissionProperty>"
    )


def _chance(value: float) -> str:
    return (
        "<MissionPropertyValue_Float><options>"
        f'<MissionPropertyValueOption_Float weighting="1" value="{value}" />'
        "</options></MissionPropertyValue_Float>"
    )


def _switch(on: bool) -> str:
    return f'<MissionPropertyValue_Boolean value="{int(on)}" />'


class TestMergedProperties:
    """A contract runs with its template's properties, then its handler's,
    then its own, a later one of a name replacing an earlier one (review
    point 2: 174 released contracts had template groups never read)."""

    def test_template_then_handler_then_contract(self, gen):
        template = ET.fromstring(
            "<contractProperties>"
            + _prop("A", src="template") + _prop("B", src="template")
            + "</contractProperties>"
        )
        handler = ET.fromstring(
            "<ContractGeneratorHandler_Career><contractParams><propertyOverrides>"
            + _prop("B", src="handler") + _prop("C", src="handler")
            + "</propertyOverrides></contractParams>"
            "<CareerContract><paramOverrides><propertyOverrides>"
            + _prop("C", src="contract")
            + "</propertyOverrides></paramOverrides></CareerContract>"
            "</ContractGeneratorHandler_Career>"
        )
        contract = handler.find("CareerContract")
        merged = gen._merged_properties(template, handler, contract)
        assert [(p.get("missionVariableName"), p.get("src")) for p in merged] == [
            ("A", "template"), ("B", "handler"), ("C", "contract"),
        ]

    def test_two_of_one_name_in_one_place_are_both_kept(self, gen):
        contract = ET.fromstring(
            "<CareerContract><paramOverrides><propertyOverrides>"
            + _prop("A", src="1") + _prop("A", src="2")
            + "</propertyOverrides></paramOverrides></CareerContract>"
        )
        merged = gen._merged_properties(None, None, contract)
        assert [p.get("src") for p in merged] == ["1", "2"]


class TestSpawnChances:
    """A spawn property's chance, or a switch, decides whether its groups
    come (review point 1): 0 leaves them out, between 0 and 1 says so."""

    def _chances(self, gen, *props):
        root = ET.fromstring(f"<p>{''.join(props)}</p>")
        return gen._spawn_chances(root.findall("MissionProperty"))

    def test_each_rule_names_its_spawn_property(self, gen):
        assert self._chances(
            gen,
            _prop("AcePilotChance_BP", _chance(0.1)),
            _prop("AllEncounters_AcePilotChance_BP", _chance(0.25)),
            _prop("EnableAlliedReinforcements_BP", _switch(False)),
            _prop("DropoffLocation2_PercentageChanceOfEncounter_BP", _chance(30)),
            _prop("EscortShipToLandingArea_EscortReinforcementChance_BP", _chance(1)),
        ) == {
            "AcePilot_BP": 0.1,
            "AllEncounters_AcePilot_BP": 0.25,
            "AlliedSpawnDescriptions_BP": 0.0,
            "DropoffLocation2_ShipsToSpawn_BP": 0.3,
            "EscortShipToLandingArea_EscortReinforcementsWave01_BP": 1.0,
            "EscortShipToLandingArea_EscortReinforcementsWave02_BP": 1.0,
            "EscortShipToLandingArea_EscortReinforcementsWave03_BP": 1.0,
        }

    def test_weighted_options_give_their_mean(self, gen):
        options = (
            "<MissionPropertyValue_Float><options>"
            '<MissionPropertyValueOption_Float weighting="1" value="0" />'
            '<MissionPropertyValueOption_Float weighting="3" value="1" />'
            "</options></MissionPropertyValue_Float>"
        )
        assert self._chances(gen, _prop("AcePilotChance_BP", options)) == {"AcePilot_BP": 0.75}

    def test_a_chance_that_names_no_spawn_property_is_left_alone(self, gen):
        assert self._chances(
            gen,
            _prop("AmbushChance_BP", _chance(0.5)),
            _prop("InvisibleTimer_ReinforcementChance_BP", _chance(0.5)),
            _prop("XAcePilotChance_BP", _chance(0.5)),
        ) == {}

    def _contract(self, gen, chance_prop: str) -> ET.Element:
        ace = _group("AcePilotShip", [_ship(1, [ARROW])], wrapper="AcePilot_BP")
        wave = _group("Wave1", [_ship(2, [VANDUUL])])
        return ET.fromstring(f"<CareerContract>{chance_prop}{ace}{wave}</CareerContract>")

    def test_a_chance_of_0_leaves_the_group_out(self, gen, index):
        root = self._contract(gen, _prop("AcePilotChance_BP", _chance(0)))
        chances = gen._spawn_chances(root.iter("MissionProperty"))
        counts = gen._extract_spawn_counts(root, chances=chances)
        assert counts[gen.SPAWN_HOSTILE] == {"Hostile Wave": 2}
        roster = gen._extract_spawn_roster(root, index, chances=chances)
        assert [g[1] for g in roster] == ["Hostile Wave"]

    def test_a_chance_between_shows_on_its_line(self, gen, index):
        root = self._contract(gen, _prop("AcePilotChance_BP", _chance(0.1)))
        chances = gen._spawn_chances(root.iter("MissionProperty"))
        label_chances: dict = {}
        counts = gen._extract_spawn_counts(root, chances=chances, label_chances=label_chances)
        assert counts[gen.SPAWN_HOSTILE] == {"Ace Pilots": 1, "Hostile Wave": 2}
        assert label_chances == {"Ace Pilots": 0.1, "Hostile Wave": 1.0}
        ace = gen._extract_spawn_roster(root, index, chances=chances)[0]
        assert gen._format_roster_group(ace) == "- Ace Pilots (10% chance): 1x Anvil Arrow"

    def test_chance_text(self, gen):
        assert gen._chance_text(0.33) == "33%"
        assert gen._chance_text(0.004) == "<1%"

    def test_the_ace_line_and_its_wording(self, gen):
        assert gen._ace_line_text([1.0, 1.0]) == "Yes"
        assert gen._ace_line_text([0.1, 0.1]) == "10% chance"
        assert gen._ace_line_text([0.05, 0.33]) == "up to 33% chance"
        assert gen._ace_line_text([0.0, 0.2]) == "up to 20% chance"
        assert gen._ace_line_text([0.0, 0.0]) == ""


_TEMPLATE_REF = "00000000-0000-0000-0000-00000000f001"


def _scan_with_template(gen, tmp_path, contract_props: str, template_props: str):
    """One contract on a template, scanned; its variant."""
    gen_dir = tmp_path / "contracts" / "contractgenerator"
    tmpl_dir = tmp_path / "contracts" / "contracttemplates"
    gen_dir.mkdir(parents=True)
    tmpl_dir.mkdir(parents=True)
    (tmpl_dir / "t.xml").write_text(
        f'<ContractTemplate.T __ref="{_TEMPLATE_REF}"><contractProperties>'
        f"{template_props}</contractProperties></ContractTemplate.T>",
        encoding="utf-8",
    )
    (gen_dir / "g.xml").write_text(
        '<ContractGenerator><generators><ContractGeneratorHandler_Career debugName="H">'
        f'<CareerContract debugName="Patrol_Nyx_Easy" template="{_TEMPLATE_REF}">'
        "<paramOverrides><stringParamOverrides>"
        '<ContractStringParam param="Title" value="@test_title" />'
        '<ContractStringParam param="Description" value="@test_desc" />'
        f"</stringParamOverrides><propertyOverrides>{contract_props}</propertyOverrides>"
        "</paramOverrides></CareerContract></ContractGeneratorHandler_Career>"
        "</generators></ContractGenerator>",
        encoding="utf-8",
    )
    missions, _, _, _ = gen.scan_contract_generators(gen_dir)
    return missions["test_title"][0]


class TestTheContractScanReadsItsTemplate:
    ACE = _group("AcePilotShip", [_ship(1, [ARROW])], wrapper="AllEncounters_AcePilot_BP")
    WAVE = _group("Wave1", [_ship(2, [VANDUUL])])

    def test_a_template_ace_by_chance_reaches_the_variant(self, gen, tmp_path):
        v = _scan_with_template(
            gen, tmp_path, self.WAVE,
            self.ACE + _prop("AllEncounters_AcePilotChance_BP", _chance(0.1)),
        )
        assert v.spawns[gen.SPAWN_HOSTILE] == {"Ace Pilots": 1, "Hostile Wave": 2}
        assert v.ace_chance == 0.1

    def test_the_contract_overrides_the_template_chance(self, gen, tmp_path):
        v = _scan_with_template(
            gen, tmp_path,
            self.WAVE + _prop("AllEncounters_AcePilotChance_BP", _chance(0)),
            self.ACE + _prop("AllEncounters_AcePilotChance_BP", _chance(0.1)),
        )
        assert v.spawns[gen.SPAWN_HOSTILE] == {"Hostile Wave": 2}

    def test_a_switch_that_is_off_drops_the_allies(self, gen, tmp_path):
        allies = _group("Allies", [_ship(1, [ARROW])], wrapper="AlliedSpawnDescriptions_BP")
        on = _scan_with_template(
            gen, tmp_path / "on", self.WAVE + allies,
            _prop("EnableAlliedReinforcements_BP", _switch(True)),
        )
        off = _scan_with_template(
            gen, tmp_path / "off", self.WAVE + allies,
            _prop("EnableAlliedReinforcements_BP", _switch(False)),
        )

        def labels(v):
            return {label for bucket in v.spawns.values() for label in bucket}

        assert labels(on) - labels(off) and labels(off) == {"Hostile Wave"}


class TestCountsOnePerSlot:
    """Without the tag tree the count adds one option per slot, from the
    smallest to the biggest, where it used to add every option (review
    point 8: Hostile Wave x6 for a Nyx contract that spawns 3 to 4)."""

    def test_a_slot_of_choices_is_a_range(self, gen):
        root = ET.fromstring(
            "<c>" + _group("Wave1", [_ship(2, [CRIMINAL]), _ship(3, [CRIMINAL])],
                           [_ship(1, [ARROW])]) + "</c>"
        )
        counts = gen._extract_spawn_counts(root)
        assert counts[gen.SPAWN_HOSTILE] == {"Hostile Wave": (3, 4)}
        assert gen._format_spawn_lines(counts) == ["<EM4>Hostiles:</EM4> Hostile Wave x3-4"]

    def test_ranges_add_and_merge(self, gen):
        breakdown = gen._empty_spawn_breakdown()
        gen._add_spawn(breakdown, gen.SPAWN_HOSTILE, "Hostile Wave", (3, 4))
        gen._add_spawn(breakdown, gen.SPAWN_HOSTILE, "Hostile Wave", 2)
        assert breakdown[gen.SPAWN_HOSTILE] == {"Hostile Wave": (5, 6)}
        # The worst case of each end: 5 against 5-6 is 5-6.
        into = {gen.SPAWN_HOSTILE: {"Hostile Wave": 5}}
        gen._merge_spawn_breakdowns_max(into, breakdown)
        assert into[gen.SPAWN_HOSTILE] == {"Hostile Wave": (5, 6)}


class TestGroupsThatReadTheSame:
    def test_ships_that_match_with_other_tags_merge(self, gen, index):
        # The review's Headhunters_claimsweep_desc_hard showed
        # "- Prospectors: 2x MISC Prospector" twice.
        root = ET.fromstring(
            "<c>"
            + _group("", [_ship(2, [ARROW])], wrapper=TARGETS)
            + _group("", [_ship(2, [CRIMINAL, ARROW])], wrapper="TargetSpawnDescriptions2_BP")
            + "</c>"
        )
        roster = gen._extract_spawn_roster(root, index)
        assert len(roster) == 1
        assert gen._format_roster_group(roster[0]) == "- Targets: 4x Anvil Arrow"


class TestTagNameFixes:
    def test_cigs_misspellings_are_put_right(self, gen):
        assert gen._tag_words("CombatRaiting2") == "Combat Rating 2"
        assert gen._tag_words("CombatRaiting") == "Combat Rating"
        assert gen._tag_words("MainEnemys") == "Main Enemies"
        assert gen._tag_words("VeryEasy") == "Very Easy"


class TestVariantNames:
    """Variants are named by what tells them apart (review point 3): their
    star systems, else their combat rating, else a number."""

    def _v(self, gen, system, difficulty="", factions=()):
        return gen.ContractVariant(
            system_name=system, success_xp=0, failure_xp=0, desc_key="d", flags=[],
            spawns={}, difficulty=difficulty, has_bp=False, bp_chance=0.0,
            bp_variant="", rank_name="", rep_track="", hostile_factions=frozenset(factions),
        )

    def test_a_vanduul_variant_is_named_by_it(self, gen):
        # The review's CFP patrols: Nyx Easy and its _V contract, one system
        # and one combat rating, the second spawning Vanduul.
        members = [[self._v(gen, "Nyx", "Combat 3/7", {"Criminal"})],
                   [self._v(gen, "Nyx", "Combat 3/7", {"Criminal", "Vanduul"})]]
        assert gen._variant_names(members) == ["Nyx", "Nyx, Vanduul"]

    def test_vanduul_beside_other_systems(self, gen):
        # The #620 mission: Stanton and Pyro, Nyx, and Nyx's Vanduul contract.
        members = [[self._v(gen, "Stanton", "", {"Criminal"}),
                    self._v(gen, "Pyro", "", {"Criminal"})],
                   [self._v(gen, "Nyx", "", {"Criminal"})],
                   [self._v(gen, "Nyx", "", {"Vanduul"})]]
        assert gen._variant_names(members) == ["Stanton, Pyro", "Nyx", "Nyx, Vanduul"]

    def test_vanduul_leaves_the_rest_numbered(self, gen):
        members = [[self._v(gen, "Nyx", "", {"Criminal"})],
                   [self._v(gen, "Nyx", "", {"Ninetails"})],
                   [self._v(gen, "Nyx", "", {"Vanduul"})]]
        assert gen._variant_names(members) == ["Nyx #1", "Nyx #2", "Nyx, Vanduul"]
        # Every one spawning Vanduul tells none apart.
        members = [[self._v(gen, "Nyx", "", {"Vanduul"})], [self._v(gen, "Nyx", "", {"Vanduul"})]]
        assert gen._variant_names(members) == ["", ""]

    def test_the_combat_rating_comes_before_vanduul(self, gen):
        members = [[self._v(gen, "Nyx", "Combat 3/7", {"Criminal"})],
                   [self._v(gen, "Nyx", "Combat 5/7", {"Vanduul"})]]
        assert gen._variant_names(members) == ["Combat 3/7", "Combat 5/7"]

    def test_hostile_factions_come_from_the_spawn_tags(self, gen, index):
        root = ET.fromstring(
            "<c>"
            + _group("Wave1", [_ship(2, [VANDUUL, EASY])], [_ship(1, [CRIMINAL])])
            + _group("", [_ship(1, [NINETAILS])], wrapper="FriendlyShips_BP")
            + "</c>"
        )
        assert index.factions([VANDUUL, EASY]) == {"Vanduul"}
        assert gen._hostile_factions(root, index) == {"Vanduul", "Criminal"}

    def test_by_system(self, gen):
        members = [[self._v(gen, "Stanton"), self._v(gen, "Pyro")], [self._v(gen, "Nyx")]]
        assert gen._variant_names(members) == ["Stanton, Pyro", "Nyx"]

    def test_a_region_is_kept(self, gen):
        members = [[self._v(gen, "Pyro RegionA"), self._v(gen, "Pyro RegionB")],
                   [self._v(gen, "Stanton")]]
        assert gen._variant_names(members) == ["Pyro Regions A, B", "Stanton"]

    def test_one_system_for_all_names_them_by_combat(self, gen):
        members = [[self._v(gen, "Nyx", "Combat 3/7 | Risk 2/7")],
                   [self._v(gen, "Nyx", "Combat 5/7 | Risk 2/7")]]
        assert gen._variant_names(members) == ["Combat 3/7", "Combat 5/7"]

    def test_combat_where_it_tells_a_shared_system_apart(self, gen):
        members = [[self._v(gen, "Stanton", "Combat 3/7")],
                   [self._v(gen, "Nyx", "Combat 3/7")],
                   [self._v(gen, "Nyx", "Combat 5/7")]]
        assert gen._variant_names(members) == [
            "Stanton", "Nyx, Combat 3/7", "Nyx, Combat 5/7",
        ]

    def test_a_number_where_nothing_else_does(self, gen):
        # The review's #620 mission: Nyx and Nyx's Vanduul contract.
        members = [[self._v(gen, "Stanton"), self._v(gen, "Pyro")],
                   [self._v(gen, "Nyx", "Combat 4/7")],
                   [self._v(gen, "Nyx", "Combat 4/7")]]
        assert gen._variant_names(members) == ["Stanton, Pyro", "Nyx #1", "Nyx #2"]

    def test_a_handler_name_is_no_system(self, gen):
        members = [[self._v(gen, "HeadHunters_ShipAmbush")],
                   [self._v(gen, "HeadHunters_ShipAmbush")]]
        names = gen._variant_names(members)
        assert names == ["", ""]
        assert gen._variant_suffix([1, 2], names) == "variants 1, 2"

    def test_the_suffix_joins_names(self, gen):
        assert gen._variant_suffix([1, 2], ["Stanton, Pyro", "Nyx"]) == "Stanton, Pyro / Nyx"
        assert gen._variant_suffix([2], ["Nyx", ""]) == "variant 2"


LT = "00000000-0000-0000-0000-0000000000d0"     # Missions/LocationType
SYS = "00000000-0000-0000-0000-0000000000d1"    # .../System
PYRO = "00000000-0000-0000-0000-0000000000d2"   # .../System/Pyro
REGIONS = "00000000-0000-0000-0000-0000000000d3"
REG_A = "00000000-0000-0000-0000-0000000000d4"
REG_B = "00000000-0000-0000-0000-0000000000d5"
REG_C = "00000000-0000-0000-0000-0000000000d6"
PYRO1 = "00000000-0000-0000-0000-0000000000d7"
PYRO2 = "00000000-0000-0000-0000-0000000000d8"
PYRO5A = "00000000-0000-0000-0000-0000000000d9"
STATION = "00000000-0000-0000-0000-0000000000e0"
ST_PYRO = "00000000-0000-0000-0000-0000000000e2"
ST_P3 = "00000000-0000-0000-0000-0000000000e3"
ST_P3L1 = "00000000-0000-0000-0000-0000000000e4"
TEXT = "00000000-0000-0000-0000-0000000000e5"
NAME = "00000000-0000-0000-0000-0000000000e6"
MISSIONS_TAG = "00000000-0000-0000-0000-0000000000e7"
REGION_TAGS = {
    MISSIONS_TAG: ("Missions", None),
    LT: ("LocationType", MISSIONS_TAG),
    SYS: ("System", LT),
    PYRO: ("Pyro", SYS),
    REGIONS: ("Regions", PYRO),
    REG_A: ("RegionA", REGIONS),
    REG_B: ("RegionB", REGIONS),
    REG_C: ("RegionC", REGIONS),
    PYRO1: ("Pyro1", PYRO),
    PYRO2: ("Pyro2", PYRO),
    PYRO5A: ("Pyro5a", PYRO),
    STATION: ("Station", LT),
    ST_PYRO: ("Pyro", STATION),
    ST_P3: ("Pyro3", ST_PYRO),
    ST_P3L1: ("Pyro3_L1", ST_P3),
    TEXT: ("Text", MISSIONS_TAG),
    NAME: ("Name", TEXT),
}
REGION_LOC = {"Pyro1": "Pyro I", "Pyro2": "Monox", "Pyro5": "Pyro V",
              "loc_starlight": "Starlight Service Station",
              "loc_starlight_clinic": "Starlight Clinic"}
# (file stem, tags, name loc key): a cave on Pyro I in A, one on a moon of
# Pyro V in C, a station in B and one of its rooms tagged C with a stray body.
REGION_FACTS = [
    ("cave_pyro1", (REG_A, PYRO1), ()),
    ("cave_pyro5a", (REG_C, PYRO5A), ()),
    ("rr_p3_l1_starlight", (REG_B, ST_P3L1), ((NAME, "@loc_starlight"),)),
    ("rr_p3_l1_starlight_clinic", (REG_C, ST_P3L1, PYRO2), ((NAME, "@loc_starlight_clinic"),)),
]


class TestRegions:
    """Pyro's contract regions read "Pyro Region B", and a Regions block after
    the flavour text says each named region's planets and stations."""

    def test_place_names(self, gen):
        assert gen._place_names(["Stanton"]) == "Stanton"
        assert gen._place_names(["Pyro RegionB"]) == "Pyro Region B"
        assert gen._place_names(["Pyro RegionD", "Pyro RegionB", "Pyro RegionC"]) == (
            "Pyro Regions B, C, D")
        assert gen._place_names(["Stanton", "Pyro RegionA", "Pyro RegionC"]) == (
            "Stanton, Pyro Regions A, C")

    def test_planets_from_caves_and_stations_from_their_main_record(self, gen):
        places = gen._region_places(REGION_FACTS, {**TAGS, **REGION_TAGS}, REGION_LOC)
        assert places == {
            ("Pyro", "RegionA"): (["Pyro I"], []),
            # The station is B's: its room tagged C moves it nowhere, and the
            # room's stray Monox tag adds no planet.
            ("Pyro", "RegionB"): ([], ["Starlight Service Station"]),
            # A moon counts as its planet.
            ("Pyro", "RegionC"): (["Pyro V"], []),
        }

    def test_the_block_lists_known_regions_in_order(self, gen):
        gen._set_region_places({
            ("Pyro", "RegionA"): (["Pyro I", "Monox"], ["Checkmate", "Patch City"]),
            ("Pyro", "RegionB"): (["Bloom"], ["Orbituary"]),
        })
        try:
            assert gen._regions_block({("Pyro", "RegionB"), ("Pyro", "RegionA"),
                                       ("Pyro", "RegionX")}) == [
                "<EM4>Regions:</EM4>",
                "- Pyro Region A: Pyro I, Monox; Checkmate, Patch City",
                "- Pyro Region B: Bloom; Orbituary",
            ]
            assert gen._regions_block({("Pyro", "RegionX")}) == []
        finally:
            gen._set_region_places({})
        assert gen._regions_block({("Pyro", "RegionA")}) == []

    def test_facts_read_tags_and_strings(self, gen, tmp_path):
        folder = tmp_path / "missiondata" / "pu_locations" / "templates"
        folder.mkdir(parents=True)
        (folder / "Cave_Pyro1.xml").write_text(
            '<MissionLocationTemplate.Cave><locationData><generalTags><tags>'
            f'<Reference value="{REG_A}" /><Reference value="{PYRO1}" />'
            '</tags></generalTags><stringVariants><variants>'
            f'<MissionStringVariant tag="{NAME}" string="@cave_name" />'
            '</variants></stringVariants></locationData></MissionLocationTemplate.Cave>',
            encoding="utf-8",
        )
        assert gen.build_location_region_facts(tmp_path / "missiondata" / "pu_locations") == [
            ("cave_pyro1", (REG_A, PYRO1), ((NAME, "@cave_name"),)),
        ]
        assert gen.build_location_region_facts(tmp_path / "nowhere") == []

    def test_blueprint_headers_name_regions_and_report_them(self, gen):
        named: set = set()
        parts = gen._build_blueprint_body_parts({
            ("Gun A",): [("Pyro RegionA", ""), ("Pyro RegionB", "")],
            ("Gun C",): [("Pyro RegionC", "")],
        }, named_regions=named)
        assert parts == ["<EM4>[Pyro Regions A, B]</EM4>\\n- Gun A",
                         "<EM4>[Pyro Region C]</EM4>\\n- Gun C"]
        assert named == {("Pyro", "RegionA"), ("Pyro", "RegionB"), ("Pyro", "RegionC")}

    def _v(self, gen, system, roster):
        return gen.ContractVariant(
            system_name=system, success_xp=0, failure_xp=0, desc_key="d", flags=[],
            spawns={}, difficulty="", has_bp=False, bp_chance=0.0, bp_variant="",
            rank_name="", rep_track="", roster=roster, cooldown=(45, 45),
        )

    def test_the_headings_name_regions_and_report_only_those_shown(self, gen):
        a = ((gen.SPAWN_HOSTILE, "Soldiers", 3),)
        b = ((gen.SPAWN_HOSTILE, "Soldiers", 2),)
        named: set = set()
        lines, _ = gen._variant_detail_lines(
            [self._v(gen, "Pyro RegionA", a), self._v(gen, "Pyro RegionB", b),
             self._v(gen, "Pyro RegionC", b)], True, True, named)
        assert lines[0] == "<EM4>Hostiles (Pyro Region A):</EM4>"
        assert "<EM4>Hostiles (Pyro Regions B, C):</EM4>" in lines
        assert named == {("Pyro", "RegionA"), ("Pyro", "RegionB"), ("Pyro", "RegionC")}
        # One roster for all: no heading names a region, so none is reported.
        named = set()
        gen._variant_detail_lines(
            [self._v(gen, "Pyro RegionA", a), self._v(gen, "Pyro RegionB", a)], True, True, named)
        assert named == set()

    def test_the_generation_puts_the_block_after_the_flavour_text(self, gen, tmp_path):
        records, forge = _records(tmp_path)
        (forge / "tag_database.json").write_text(
            json.dumps({"version": 1, "tags": {
                g: [n, p] for g, (n, p) in {**TAGS, **REGION_TAGS}.items()}}),
            encoding="utf-8",
        )
        locations = records / "missiondata" / "pu_locations"
        locations.mkdir(parents=True)
        for stem, tags, strings in REGION_FACTS:
            refs = "".join(f'<Reference value="{t}" />' for t in tags)
            names = "".join(f'<MissionStringVariant tag="{t}" string="{s}" />' for t, s in strings)
            (locations / f"{stem}.xml").write_text(
                f"<MissionLocationTemplate.T><locationData><generalTags><tags>{refs}</tags>"
                f"</generalTags><stringVariants><variants>{names}</variants></stringVariants>"
                "</locationData></MissionLocationTemplate.T>",
                encoding="utf-8",
            )

        def contract(name, ship):
            hostiles = _group("Wave1", [_ship(1, [ship])])
            return (
                f'<CareerContract debugName="{name}">'
                "<paramOverrides><stringParamOverrides>"
                '<ContractStringParam param="Title" value="@test_title" />'
                '<ContractStringParam param="Description" value="@test_desc" />'
                f"</stringParamOverrides><propertyOverrides>{hostiles}</propertyOverrides>"
                "</paramOverrides></CareerContract>"
            )

        (records / "contracts" / "contractgenerator" / "ambush.xml").write_text(
            '<ContractGenerator><generators><ContractGeneratorHandler_Career debugName="H">'
            f"{AVAILABILITY}"
            + contract("HH_Pyro_RegionA_Ambush", ARROW)
            + contract("HH_Pyro_RegionB_Ambush", GLADIATOR)
            + "</ContractGeneratorHandler_Career></generators></ContractGenerator>",
            encoding="utf-8",
        )
        loc = {**LOC, **REGION_LOC}
        ctx = {"records": records, "forge_dir": forge, "loc": loc, "tag_loc": loc,
               "entity_names": {}, "reputation_lookup": {}, "mission_detail_fields": {}}
        desc = gen._run_gen_missions(ctx)["test_desc"]
        assert desc.startswith(
            "Take them out.\\n\\n<EM4>Regions:</EM4>\\n"
            "- Pyro Region A: Pyro I\\n"
            "- Pyro Region B: Starlight Service Station\\n\\n<EM3>MISSION DETAILS</EM3>"
        )
        assert "<EM4>Hostiles (Pyro Region A):</EM4>" in desc
        assert "<EM4>Hostiles (Pyro Region B):</EM4>" in desc
        assert gen._REGION_PLACES == {}  # set for the run only


class TestModelFallback:
    """A mission that asks for a model tag the newer AI ships do not carry
    (they carry only their series) still names the ship, through the model
    name in the entity file names."""

    HAMMER = "00000000-0000-0000-0000-0000000000d1"
    SERIES = "00000000-0000-0000-0000-0000000000d2"
    HAMMER_SERIES = "00000000-0000-0000-0000-0000000000d3"

    def _index(self, gen, stem):
        tags = dict(TAGS)
        tags[self.HAMMER] = ("Hammerhead", MODEL)
        tags[self.SERIES] = ("Series", SHIP)
        tags[self.HAMMER_SERIES] = ("Hammerhead", self.SERIES)
        ships = [([CRIMINAL, self.HAMMER_SERIES], "vehicle_NameAEGS_Hammerhead", stem)]
        loc = dict(LOC, vehicle_NameAEGS_Hammerhead="Aegis Hammerhead")
        return gen.ShipSpawnIndex(tags, ships, loc)

    def test_the_file_name_names_the_model(self, gen):
        index = self._index(gen, "aegs_hammerhead_gs_pu_ai_crim")
        assert index.pick([self.HAMMER, CRIMINAL], [])[0] == ("Aegis Hammerhead",)

    def test_the_other_tags_still_count(self, gen):
        index = self._index(gen, "aegs_hammerhead_gs_pu_ai_crim")
        assert index.pick([self.HAMMER, VANDUUL], []) == ((), "Vanduul Hammerhead")
        assert index.pick([self.HAMMER, CRIMINAL], [CRIMINAL])[0] == ()

    def test_a_name_only_inside_a_word_does_not_count(self, gen):
        index = self._index(gen, "aegs_hammerheadx_pu_ai_crim")
        assert index.pick([self.HAMMER, CRIMINAL], [])[0] == ()


class TestCooldown:
    AVAIL = AVAILABILITY

    def test_the_handlers_availability(self, gen):
        assert gen._extract_cooldown(ET.fromstring(self.AVAIL)) == (15, 15)

    def test_a_contracts_overrides_win(self, gen):
        contract = ET.fromstring(
            "<CareerContract><paramOverrides><intParamOverrides>"
            '<ContractIntParam param="PersonalCooldownTime" value="60" />'
            '<ContractIntParam param="AbandonedCooldownTime" value="5" />'
            "</intParamOverrides></paramOverrides></CareerContract>"
        )
        assert gen._extract_cooldown(ET.fromstring(self.AVAIL), contract) == (60, 5)

    def test_no_personal_cooldown(self, gen):
        contract = ET.fromstring(
            "<CareerContract><paramOverrides><boolParamOverrides>"
            '<ContractBoolParam param="HasPersonalCooldown" value="0" />'
            "</boolParamOverrides></paramOverrides></CareerContract>"
        )
        assert gen._extract_cooldown(ET.fromstring(self.AVAIL), contract) == (0, 15)
        assert gen._extract_cooldown(None) is None

    @pytest.mark.parametrize(
        "cooldown,text",
        [
            ((45, 45), "45 min"),
            ((60, 60), "1 h"),
            ((90, 0), "1 h 30 min"),
            ((2880, 2880), "2 d"),
            ((60, 15), "1 h (abandon: 15 min)"),
            ((0, 1), "None"),
            ((0, 2), "None (abandon: 2 min)"),
            ((30, 1), "30 min"),
            ((0, 0), "None"),
        ],
    )
    def test_format(self, gen, cooldown, text):
        assert gen._format_cooldown(cooldown) == text


class TestVariants:
    def _variant(self, gen, roster=(), cooldown=None):
        return gen.ContractVariant(
            system_name="Nyx",
            success_xp=0,
            failure_xp=0,
            desc_key="d",
            flags=[],
            spawns={},
            difficulty=None,
            has_bp=False,
            bp_chance=0.0,
            bp_variant="",
            rank_name="",
            rep_track="",
            roster=roster,
            cooldown=cooldown,
        )

    def test_the_same_for_every_variant_names_none(self, gen):
        group = (gen.SPAWN_HOSTILE, "Targets", (((1, ("Anvil Arrow",), ""),),))
        v = self._variant(gen, (group,), (15, 15))
        rosters, cooldown = gen._variant_detail_lines([v, v], True, True)
        assert rosters == ["<EM4>Hostiles:</EM4>", "- Targets: 1x Anvil Arrow"]
        assert cooldown == ["<EM4>Cooldown:</EM4> 15 min"]

    def test_different_variants_are_numbered_alike_in_every_line(self, gen):
        a = (gen.SPAWN_HOSTILE, "Targets", (((1, ("Anvil Arrow",), ""),),))
        b = (gen.SPAWN_HOSTILE, "Targets", (((1, ("Vanduul Blade",), ""),),))
        friend = (gen.SPAWN_FRIENDLY, "Escorts", 2)
        v1 = self._variant(gen, (a, friend), (15, 15))
        v2 = self._variant(gen, (b, friend), (60, 15))
        rosters, cooldown = gen._variant_detail_lines([v1, v2, v1], True, True)
        assert rosters == [
            "<EM4>Hostiles (variant 1):</EM4>",
            "- Targets: 1x Anvil Arrow",
            "<EM4>Hostiles (variant 2):</EM4>",
            "- Targets: 1x Vanduul Blade",
            "<EM4>Friendlies:</EM4>",
            "- Escorts x2",
        ]
        assert cooldown == [
            "<EM4>Cooldown:</EM4> variant 1: 15 min; variant 2: 1 h (abandon: 15 min)"
        ]

    def test_hidden_fields_number_nothing(self, gen):
        a = (gen.SPAWN_HOSTILE, "Targets", 1)
        v1, v2 = self._variant(gen, (a,), (15, 15)), self._variant(gen, (), (15, 15))
        assert gen._variant_detail_lines([v1, v2], False, True) == (
            [],
            ["<EM4>Cooldown:</EM4> 15 min"],
        )
        assert gen._variant_detail_lines([v1, v2], True, False) == (
            ["<EM4>Hostiles (variant 1):</EM4>", "- Targets x1"],
            [],
        )


_SHIP_XML = (
    "<EntityClassDefinition.X><tags>{tags}</tags><Components>"
    '<VehicleComponentParams vehicleName="@{key}" /></Components>'
    "</EntityClassDefinition.X>"
)


def _records(tmp_path: Path, *, with_tags: bool = True) -> tuple[Path, Path]:
    records = tmp_path / "records"
    ships = records / "entities" / "spaceships"
    ships.mkdir(parents=True)
    for stem, own, key in SHIPS:
        refs = "".join(f'<Reference value="{t}" />' for t in own)
        (ships / f"{stem}.xml").write_text(
            _SHIP_XML.format(tags=refs, key=key), encoding="utf-8"
        )
    contracts = records / "contracts" / "contractgenerator"
    contracts.mkdir(parents=True)
    wave = _group(
        "Wave1",
        [_ship(2, [CRIMINAL, PILOT]), _ship(3, [CRIMINAL])],
        [_ship(1, [ARROW])],
    )
    hostiles = wave + _group("", [_ship(1, [NINETAILS, VERY_EASY])], wrapper=TARGETS)
    (contracts / "ambush.xml").write_text(
        '<ContractGenerator><generators><ContractGeneratorHandler_Career debugName="H">'
        f"{AVAILABILITY}"
        '<CareerContract debugName="Ambush_Medium">'
        "<paramOverrides><stringParamOverrides>"
        '<ContractStringParam param="Title" value="@test_title" />'
        '<ContractStringParam param="Description" value="@test_desc" />'
        "</stringParamOverrides><intParamOverrides>"
        '<ContractIntParam param="PersonalCooldownTime" value="60" />'
        f"</intParamOverrides><propertyOverrides>{hostiles}</propertyOverrides></paramOverrides>"
        "</CareerContract></ContractGeneratorHandler_Career></generators></ContractGenerator>",
        encoding="utf-8",
    )
    forge = tmp_path / "forge"
    forge.mkdir()
    if with_tags:
        (forge / "tag_database.json").write_text(
            json.dumps(
                {"version": 1, "tags": {g: [n, p] for g, (n, p) in TAGS.items()}}
            ),
            encoding="utf-8",
        )
    return records, forge


def _generate(gen, records: Path, forge: Path, fields: dict | None = None) -> str:
    ctx = {
        "records": records,
        "forge_dir": forge,
        "loc": LOC,
        "tag_loc": LOC,
        "entity_names": {},
        "reputation_lookup": {},
        "mission_detail_fields": fields or {},
    }
    out = gen._run_gen_missions(ctx)
    return out["test_desc"]


class TestGeneration:
    def test_ships_replace_the_counts_and_the_cooldown_follows(self, gen, tmp_path):
        records, forge = _records(tmp_path)
        desc = _generate(gen, records, forge)
        assert (
            "<EM4>Hostiles:</EM4>\\n"
            "- Hostile Wave: 2-3x of Anvil Arrow or Anvil Gladiator and 1x Anvil Arrow\\n"
            "- Targets: 1x Very Easy Ninetails ship"
        ) in desc
        assert "<EM4>Cooldown:</EM4> 1 h (abandon: 15 min)" in desc
        assert "Hostile Wave x" not in desc
        assert gen._SHIP_SPAWNS is None  # set for the run only

    def test_without_the_tag_tree_the_counts_stay(self, gen, tmp_path):
        records, forge = _records(tmp_path, with_tags=False)
        desc = _generate(gen, records, forge)
        # The count line, one choice per slot: the wave's 2- and 3-ship
        # choices are 3-4 ships with the Arrow, not all of them added up (6).
        assert "<EM4>Hostiles:</EM4> Hostile Wave x3-4, Targets x1" in desc
        assert "Anvil" not in desc
        assert "<EM4>Cooldown:</EM4> 1 h (abandon: 15 min)" in desc

    def test_the_fields_hide_their_lines(self, gen, tmp_path):
        records, forge = _records(tmp_path)
        desc = _generate(gen, records, forge, {"spawns": False, "cooldown": False})
        assert "Hostiles" not in desc and "Cooldown" not in desc
