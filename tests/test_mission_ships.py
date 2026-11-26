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


class TestSimple:
    """The Hostiles dropdown's Simple: a pool of more than 10 ships is its
    type, with how many and the biggest and smallest by bounding box."""

    POOL = "00000000-0000-0000-0000-0000000000e1"

    def _index(self, gen, count, simple=True):
        tags = dict(TAGS)
        tags[self.POOL] = ("Pool", FACTION)
        ships = [
            ([self.POOL, EASY], f"vehicle_Name{i:02}", f"ship{i:02}", float(i))
            for i in range(count)
        ]
        loc = {f"vehicle_Name{i:02}": f"Ship {i:02}" for i in range(count)}
        return gen.ShipSpawnIndex(tags, ships, loc, simple=simple)

    def _text(self, gen, index):
        names, label = index.pick([self.POOL, EASY], [])
        gen._set_ship_spawns(index)
        try:
            return gen._format_roster_group(
                (gen.SPAWN_HOSTILE, "Targets", (((2, names, label),),))
            )
        finally:
            gen._set_ship_spawns(None)

    def test_a_big_pool_is_its_type_biggest_and_smallest(self, gen):
        assert self._text(gen, self._index(gen, 11)) == (
            "- Targets: 2x Easy Pool ship (11 ships: Ship 10 \u2026 Ship 00)"
        )

    def test_ten_ships_are_still_listed(self, gen):
        assert self._text(gen, self._index(gen, 10)).startswith(
            "- Targets: 2x of Ship 00, Ship 01,"
        )

    def test_all_ship_details_lists_every_ship(self, gen):
        text = self._text(gen, self._index(gen, 11, simple=False))
        assert text.startswith("- Targets: 2x of Ship 00,") and "Ship 10" in text

    def test_the_summary_counts_as_one_name_for_the_one_line_rule(self, gen):
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
        assert text == (
            "- Hostile Wave: 2x Easy Pool ship (11 ships: Ship 10 \u2026 Ship 00)"
            " and 1x Ship 03"
        )

    def test_the_generation_takes_the_setting(self, gen, tmp_path):
        records, forge = _records(tmp_path)
        ctx = {
            "records": records,
            "forge_dir": forge,
            "loc": LOC,
            "tag_loc": LOC,
            "hostiles_detail": "all",
        }
        assert gen._load_ship_spawns(ctx).simple is False
        assert gen._load_ship_spawns(dict(ctx, hostiles_detail="simple")).simple is True
        del ctx["hostiles_detail"]
        assert gen._load_ship_spawns(ctx).simple is True  # the app's default


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
            ((0, 1), "None (abandon: 1 min)"),
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
        # The count line as it always was (it adds every choice's amount).
        assert "<EM4>Hostiles:</EM4> Hostile Wave x6, Targets x1" in desc
        assert "Anvil" not in desc
        assert "<EM4>Cooldown:</EM4> 1 h (abandon: 15 min)" in desc

    def test_the_fields_hide_their_lines(self, gen, tmp_path):
        records, forge = _records(tmp_path)
        desc = _generate(gen, records, forge, {"spawns": False, "cooldown": False})
        assert "Hostiles" not in desc and "Cooldown" not in desc
