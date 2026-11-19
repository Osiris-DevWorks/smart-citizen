"""The SCO Order tab (3.1.0): the generator's slot data in crafting_index.json
and the order maths in ``src/utils/crafting_order.py``.

The blueprint XML below follows the DataForge shape unforge writes for a
crafting blueprint (``CraftingBlueprintRecord`` -> tier -> ``mandatoryCost``
-> ``CraftingCost_Select`` slots), as documented by the public DataForge
parsers (fleetyards' ``BlueprintsParser``, scunpacked's blueprints export):
SCU amounts under ``quantity/SStandardCargoUnit@standardCargoUnits``, a
piece count as a bare ``quantity``, quality ramps under the slot's
``context``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.utils import crafting_order as co  # noqa: E402
from src.utils.mining_catalog import load_crafting_index, write_crafting_index  # noqa: E402

pytestmark = [pytest.mark.unit]

GOLD = "aaaaaaaa-0000-0000-0000-000000000001"
TUNGSTEN = "aaaaaaaa-0000-0000-0000-000000000002"
HADANITE = "aaaaaaaa-0000-0000-0000-000000000003"
COPPER = "aaaaaaaa-0000-0000-0000-000000000004"
INTEGRITY = "bbbbbbbb-0000-0000-0000-000000000001"
PIPS = "bbbbbbbb-0000-0000-0000-000000000002"
OUTPUT = "cccccccc-0000-0000-0000-000000000001"


def _resource(uuid: str, scu: float, min_quality: int = 0) -> str:
    return (
        f'<CraftingCost_Resource resource="{uuid}" minQuality="{min_quality}">'
        f'<quantity><SStandardCargoUnit standardCargoUnits="{scu}"/></quantity>'
        f"</CraftingCost_Resource>"
    )


def _slot(name: str, debug: str, cost: str, mods: str = "") -> str:
    context = ""
    if mods:
        context = (
            "<context><CraftingCostContext_ResultGameplayPropertyModifiers>"
            "<gameplayPropertyModifiers><CraftingGameplayPropertyModifiers_List>"
            f"<gameplayPropertyModifiers>{mods}</gameplayPropertyModifiers>"
            "</CraftingGameplayPropertyModifiers_List></gameplayPropertyModifiers>"
            "</CraftingCostContext_ResultGameplayPropertyModifiers></context>"
        )
    return (
        f'<CraftingCost_Select count="1"><nameInfo displayName="{name}" debugName="{debug}"/>'
        f"<options>{cost}</options>{context}</CraftingCost_Select>"
    )


def _linear(stat: str, *segments) -> str:
    ranges = "".join(
        f'<CraftingGameplayPropertyModifierValueRange_Linear startQuality="{a}" '
        f'endQuality="{b}" modifierAtStart="{x}" modifierAtEnd="{y}"/>'
        for a, b, x, y in segments
    )
    return (
        f'<CraftingGameplayPropertyModifierCommon gameplayPropertyRecord="{stat}">'
        f"<valueRanges>{ranges}</valueRanges></CraftingGameplayPropertyModifierCommon>"
    )


def _additive(stat: str, *segments) -> str:
    ranges = "".join(
        f'<CraftingGameplayPropertyModifierValueRange_LinearIntegerAdditive startQuality="{a}" '
        f'endQuality="{b}" additiveModifierAtStart="{x}" additiveModifierAtEnd="{y}"/>'
        for a, b, x, y in segments
    )
    return (
        f'<CraftingGameplayPropertyModifierCommon gameplayPropertyRecord="{stat}">'
        f"<valueRanges>{ranges}</valueRanges></CraftingGameplayPropertyModifierCommon>"
    )


def _blueprint(slots: str, count: int) -> str:
    return (
        '<CraftingBlueprintRecord.BP_CRAFT_test __type="CraftingBlueprintRecord">'
        "<blueprint><CraftingBlueprint>"
        "<processSpecificData>"
        f'<CraftingProcess_Creation entityClass="{OUTPUT}"/>'
        "</processSpecificData>"
        "<tiers><CraftingBlueprintTier><recipe><CraftingRecipe><costs><CraftingRecipeCosts>"
        f'<mandatoryCost><CraftingCost_Select count="{count}"><options>{slots}</options>'
        "</CraftingCost_Select></mandatoryCost>"
        "</CraftingRecipeCosts></costs></CraftingRecipe></recipe></CraftingBlueprintTier></tiers>"
        "</CraftingBlueprint></blueprint></CraftingBlueprintRecord.BP_CRAFT_test>"
    )


FRAME = _slot(
    "@crafting_ui_slotname_frame",
    "FRAME",
    _resource(TUNGSTEN, 0.06),
    _linear(INTEGRITY, (0, 500, 0.9, 1.0), (500, 1000, 1.0, 1.1)),
)
CABLING = _slot("@crafting_ui_slotname_cabling", "CABLING", _resource(GOLD, 0.02, 300))
GEM = _slot(
    "@missing_key",
    "POWER REGULATOR",
    f'<CraftingCost_Item entityClass="{HADANITE}" quantity="1" minQuality="0"/>',
    _additive(PIPS, (0, 399, -1, -1), (400, 899, 0, 0), (900, 1000, 1, 1)),
)


@pytest.fixture(scope="module")
def gen():
    script = Path(__file__).resolve().parent.parent / "scripts" / "generate_enhancements_ini.py"
    spec = importlib.util.spec_from_file_location("generate_enhancements_ini_order_test", script)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def records(tmp_path):
    """A records tree: two blueprints, their materials, two crafted stats."""
    bp_dir = tmp_path / "crafting" / "blueprints" / "crafting" / "fpsgear" / "weapons"
    bp_dir.mkdir(parents=True)
    (bp_dir / "bp_craft_test_rifle.xml").write_text(
        _blueprint(FRAME + CABLING + GEM, 3), encoding="utf-8"
    )
    # "Any 2 of these 3": a group of three slots, two needed.
    pick = (
        f'<CraftingCost_Select count="2"><options>'
        f'{_slot("", "PLATE A", _resource(COPPER, 0.5))}'
        f'{_slot("", "PLATE B", _resource(GOLD, 0.25))}'
        f'{_slot("", "PLATE C", _resource(TUNGSTEN, 1))}'
        f"</options></CraftingCost_Select>"
    )
    (bp_dir / "bp_craft_test_armor.xml").write_text(_blueprint(FRAME + pick, 2), encoding="utf-8")
    carry = tmp_path / "entities" / "scitem" / "carryables"
    carry.mkdir(parents=True)
    for name, uuid in (("gold", GOLD), ("tungsten", TUNGSTEN), ("copper", COPPER)):
        (carry / f"carryable_1h_commodity_metal_{name}.xml").write_text(
            f'<Entity><Reference value="{uuid}"/></Entity>', encoding="utf-8"
        )
    (carry / "harvestable_mineral_1h_hadanite.xml").write_text(
        f'<Entity __ref="{HADANITE}"/>', encoding="utf-8"
    )
    props = tmp_path / "crafting" / "craftedproperties"
    props.mkdir(parents=True)
    (props / "gpp_item_integrity.xml").write_text(
        f'<CraftingGameplayPropertyDef __ref="{INTEGRITY}" propertyName="@crafted_integrity"/>',
        encoding="utf-8",
    )
    (props / "gpp_itemresource_powergeneration.xml").write_text(
        f'<CraftingGameplayPropertyDef __ref="{PIPS}" propertyName=""/>', encoding="utf-8"
    )
    return tmp_path


def _scan(gen, records, entity_names=None, by_filename=None):
    loc = {
        "crafting_UI_SlotName_Frame,P": "Frame",
        "crafting_ui_slotname_cabling": "Cabling",
        "crafted_integrity": "Integrity",
        "items_commodities_gold": "Gold",
        "items_commodities_tungsten": "Tungsten",
        "items_commodities_copper": "Copper",
        "items_commodities_hadanite": "Hadanite",
    }
    for name in ("gold", "tungsten", "copper", "hadanite"):
        loc[f"items_commodities_{name}_desc"] = "A material."
    index, order = {}, {}
    gen.scan_crafting_blueprints(
        records / "crafting" / "blueprints" / "crafting",
        records / "entities" / "scitem" / "carryables",
        entity_names or {OUTPUT: "Test Rifle"},
        loc,
        records_dir=records,
        crafting_index=index,
        crafting_order=order,
        entity_names_by_filename=by_filename,
    )
    return index, order


class TestGeneratorSlots:
    def test_slots_amounts_units_and_names(self, gen, records):
        _index, order = _scan(gen, records, entity_names={})
        rifle = next(bp for bp in order["blueprints"] if bp["k"] == "bp_craft_test_rifle")
        assert rifle["c"]
        frame, cabling, gem = rifle["s"]
        # Slot names through the ,P-stripped, any-case loc lookup, else the
        # debug name.
        assert (frame["n"], cabling["n"], gem["n"]) == ("Frame", "Cabling", "Power regulator")
        assert (frame["mat"], frame["u"], frame["q"]) == ("tungsten", "scu", 0.06)
        assert (cabling["mat"], cabling["min"]) == ("gold", 300)
        assert (gem["mat"], gem["u"], gem["q"]) == ("hadanite", "unit", 1)
        assert rifle["p"] == []

    def test_quality_curves_and_stat_names(self, gen, records):
        _index, order = _scan(gen, records)
        rifle = next(bp for bp in order["blueprints"] if bp["k"] == "bp_craft_test_rifle")
        frame, cabling, gem = rifle["s"]
        assert cabling["m"] == []
        ((stat, ci),) = frame["m"]
        assert stat == "gpp_item_integrity" and order["stats"][stat] == "Integrity"
        assert order["curves"][ci] == {
            "s": [[0, 500, 0.9, 1.0], [500, 1000, 1.0, 1.1]],
            "add": False,
        }
        ((stat, ci),) = gem["m"]
        # No loc name: the record's file name, humanized.
        assert order["stats"][stat] == "Itemresource powergeneration"
        assert order["curves"][ci]["add"] is True
        assert order["curves"][ci]["s"][2] == [900, 1000, 1, 1]

    def test_pick_group(self, gen, records):
        _index, order = _scan(gen, records)
        armor = next(bp for bp in order["blueprints"] if bp["k"] == "bp_craft_test_armor")
        assert armor["p"] == [{"n": 3, "k": 2}]
        assert [s.get("g") for s in armor["s"]] == [None, 0, 0, 0]

    def test_a_material_no_carryable_names_keeps_the_blueprint(self, gen, records):
        """Amr's NDB-30 report: dropping such blueprints hid most of the
        catalogue, which read as an owned-only filter."""
        (
            records
            / "entities"
            / "scitem"
            / "carryables"
            / "carryable_1h_commodity_metal_copper.xml"
        ).unlink()
        _index, order = _scan(gen, records)
        assert sorted(bp["k"] for bp in order["blueprints"]) == [
            "bp_craft_test_armor",
            "bp_craft_test_rifle",
        ]
        armor = next(bp for bp in order["blueprints"] if bp["k"] == "bp_craft_test_armor")
        assert armor["s"][1]["mat"] == f"unknown:{COPPER}"
        assert order["mnames"] == {}

    def test_an_item_material_is_named_from_its_entity(self, gen, records):
        carry = records / "entities" / "scitem" / "carryables"
        (carry / "harvestable_mineral_1h_hadanite.xml").unlink()
        names = {OUTPUT: "Test Rifle", HADANITE: "Hadanite"}
        _index, order = _scan(gen, records, entity_names=names)
        rifle = next(bp for bp in order["blueprints"] if bp["k"] == "bp_craft_test_rifle")
        assert rifle["s"][2]["mat"] == f"item:{HADANITE}"
        assert order["mnames"] == {f"item:{HADANITE}": "Hadanite"}

    def test_an_unlinked_item_is_named_from_its_entity_file(self, gen, records, caplog):
        """Amr's NDB-30 report: an item whose blueprint entityClass links no
        entity (or one base.ini has no name for) is named from the entity
        file named like the blueprint, as the mission blueprint lists are,
        so the Order search finds it by its real name."""
        names = {OUTPUT: "item_NameMXOX_NeutronRepeater_S3"}  # a loc key nothing resolved
        by_file = {"test_rifle": "NDB-30 Repeater"}
        with caplog.at_level("INFO"):
            _index, order = _scan(gen, records, entity_names=names, by_filename=by_file)
        by_key = {bp["k"]: bp["n"] for bp in order["blueprints"]}
        assert by_key["bp_craft_test_rifle"] == "NDB-30 Repeater"
        # Neither found: the file name, and the log says so.
        assert by_key["bp_craft_test_armor"] == "test_armor"
        assert "1 blueprints with no item name" in caplog.text and "bp_craft_test_armor" in caplog.text

    def test_a_linked_name_wins_over_the_file_name(self, gen, records):
        _index, order = _scan(gen, records, entity_names={OUTPUT: "Test Rifle"},
                              by_filename={"test_rifle": "Other"})
        rifle = next(bp for bp in order["blueprints"] if bp["k"] == "bp_craft_test_rifle")
        assert rifle["n"] == "Test Rifle"

    def test_index_file_round_trip(self, gen, records, tmp_path):
        index, order = _scan(gen, records)
        path = tmp_path / "crafting_index.json"
        write_crafting_index(path, index, order)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["version"] == 2
        loaded = load_crafting_index(path)
        assert loaded.materials == json.loads(json.dumps(index))
        assert loaded.blueprints == order["blueprints"]
        assert loaded.curves == order["curves"] and loaded.stats == order["stats"]
        assert loaded.material_name("gold") == "Gold"

    def test_item_materials_round_trip(self, tmp_path):
        path = tmp_path / "crafting_index.json"
        write_crafting_index(path, {}, {"blueprints": [], "mnames": {"item:x": "Widget"}})
        loaded = load_crafting_index(path)
        assert loaded.item_materials == {"item:x": "Widget"}
        assert loaded.material_name("item:x") == "Widget"
        assert loaded.material_name("unknown:y") == "unknown:y"

    def test_a_version_1_index_reads_with_no_blueprints(self, tmp_path):
        path = tmp_path / "crafting_index.json"
        path.write_text(
            json.dumps({"version": 1, "materials": {"gold": {"names": ["Gold"]}}}), encoding="utf-8"
        )
        loaded = load_crafting_index(path)
        assert loaded.blueprints == [] and loaded.curves == [] and "gold" in loaded.materials

    def test_main_writes_the_order(self, gen):
        """main() threads crafting_order from the ctx to the index writer."""
        source = Path(gen.__file__).read_text(encoding="utf-8")
        assert 'crafting_order=ctx.get("crafting_order")' in source
        assert 'ctx["crafting_order"])' in source


# -- order maths -------------------------------------------------------------

BP = {
    "k": "rifle",
    "n": "Test Rifle",
    "c": "Rifles",
    "s": [
        {"n": "Frame", "mat": "tungsten", "u": "scu", "q": 0.06, "min": 0, "m": [["int", 0]]},
        {"n": "Cabling", "mat": "gold", "u": "scu", "q": 0.02, "min": 300, "m": []},
        {"n": "Regulator", "mat": "hadanite", "u": "unit", "q": 1, "min": 0, "m": [["pips", 1]]},
    ],
    "p": [],
}
PICK = {
    "k": "armor",
    "n": "Test Armor",
    "c": "Armor",
    "s": [
        {"n": "A", "mat": "copper", "u": "scu", "q": 0.5, "min": 0, "m": [], "g": 0},
        {"n": "B", "mat": "gold", "u": "scu", "q": 0.25, "min": 0, "m": [], "g": 0},
        {"n": "C", "mat": "tungsten", "u": "scu", "q": 1, "min": 0, "m": [], "g": 0},
    ],
    "p": [{"n": 3, "k": 2}],
}
CURVES = [
    {"s": [[0, 500, 0.9, 1.0], [500, 1000, 1.0, 1.1]], "add": False},
    {"s": [[0, 399, -1, -1], [400, 899, 0, 0], [900, 1000, 1, 1]], "add": True},
]
BY_KEY = co.blueprints_by_key([BP, PICK])


class TestOrderLines:
    def test_new_line_neutral_quality_and_first_picks(self):
        line = co.new_line(BP)
        assert line.q == [500, 500, 500] and line.on == [True, True, True]
        assert co.new_line(PICK).on == [True, True, False]

    def test_min_quality_clamps(self):
        bp = dict(BP, s=[dict(BP["s"][1], min=700)])
        assert co.new_line(bp).q == [700]
        assert co.clamp_quality(1200) == 1000 and co.clamp_quality(-5) == 0
        assert co.clamp_quality(100, 300) == 300

    def test_adding_the_same_item_raises_its_count(self):
        lines: list[co.OrderLine] = []
        co.add_to_order(lines, BP)
        co.add_to_order(lines, PICK)
        co.add_to_order(lines, BP, 2)
        assert [(line.key, line.count) for line in lines] == [("rifle", 3), ("armor", 1)]

    def test_count_is_capped(self):
        lines: list[co.OrderLine] = []
        co.add_to_order(lines, BP, 5000)
        assert lines[0].count == co.COUNT_MAX

    def test_toggle_pick_keeps_the_craft_valid(self):
        on = co.new_line(PICK).on
        on = co.toggle_pick_slot(PICK, on, 2)  # C on: A (the earliest) goes off
        assert on == [False, True, True]
        on = co.toggle_pick_slot(PICK, on, 1)  # B off: A takes its place
        assert on == [True, False, True]
        assert co.picks_valid(PICK, on)
        assert co.toggle_pick_slot(BP, [True] * 3, 0) == [True] * 3  # not a pick slot

    def test_load_order_fits_and_merges(self):
        raw = [
            {"key": "rifle", "count": 2, "q": [900, 100, 2000], "on": [True, True, True]},
            {"key": "gone", "count": 1},
            {"key": "armor", "count": "x", "on": [True, True, True]},  # 3 on, needs 2
            {"key": "rifle", "count": 1},
            "junk",
        ]
        lines = co.load_order(raw, BY_KEY)
        assert [(line.key, line.count) for line in lines] == [("rifle", 3), ("armor", 1)]
        assert lines[0].q == [900, 300, 1000]
        assert lines[1].on == [True, True, False]
        assert co.load_order("not a list", BY_KEY) == []

    def test_to_dict_round_trip(self):
        line = co.new_line(BP)
        line.count = 4
        assert co.load_order([line.to_dict()], BY_KEY)[0] == line


class TestTotals:
    def test_totals_by_material_and_quality(self):
        rifle = co.new_line(BP)
        rifle.count = 2
        rifle.q = [800, 500, 500]
        armor = co.new_line(PICK)  # copper + gold
        totals = co.material_totals([rifle, armor], BY_KEY)
        by_mat = {t.material: t for t in totals}
        assert by_mat["gold"].amount == pytest.approx(0.04 + 0.25)
        assert by_mat["gold"].by_quality == [(500, pytest.approx(0.29))]
        assert by_mat["tungsten"].by_quality == [(800, pytest.approx(0.12))]
        assert by_mat["gold"].items == ["Test Armor", "Test Rifle"]
        assert by_mat["hadanite"].unit == "unit" and by_mat["hadanite"].amount == 2
        # SCU first, then most needed; pieces last.
        assert [t.material for t in totals] == ["copper", "gold", "tungsten", "hadanite"]

    def test_one_line_alone(self):
        lines = [co.new_line(BP), co.new_line(PICK)]
        assert {t.material for t in co.material_totals(lines, BY_KEY, only="armor")} == {
            "copper",
            "gold",
        }

    def test_bands_split_highest_first(self):
        a, b = co.new_line(BP), co.new_line(PICK)
        b.on = [False, True, True]
        b.q = [500, 900, 500]
        gold = next(t for t in co.material_totals([a, b], BY_KEY) if t.material == "gold")
        assert gold.by_quality == [(900, 0.25), (500, 0.02)]


class TestBonuses:
    def test_curve_value(self):
        assert co.curve_value(CURVES[0], 0) == pytest.approx(0.9)
        assert co.curve_value(CURVES[0], 500) == pytest.approx(1.0)
        assert co.curve_value(CURVES[0], 750) == pytest.approx(1.05)
        assert co.curve_value(CURVES[0], 2000) == pytest.approx(1.1)
        assert co.curve_value(CURVES[1], 950) == 1

    def test_stat_modifiers(self):
        mods = co.stat_modifiers(BP, CURVES, [1000, 500, 950])
        assert mods["int"].mul == pytest.approx(1.1) and not mods["int"].pips
        assert mods["pips"].add == 1 and mods["pips"].pips
        assert set(co.stat_modifiers(BP, CURVES, [500] * 3, only=1)) == set()
        assert co.stat_modifiers(BP, CURVES, [1000] * 3, on=[False, True, True]).keys() == {"pips"}

    def test_format_and_sign(self):
        mods = co.stat_modifiers(BP, CURVES, [750, 500, 100])
        assert co.format_modifier(mods["int"]) == "+5%"
        assert co.modifier_sign(mods["int"]) == 1
        assert co.format_modifier(mods["pips"]) == "-1 pips"
        assert co.modifier_sign(mods["pips"]) == -1
        assert co.format_modifier(co.StatModifier()) == "0%"


class TestText:
    def test_amounts(self):
        assert co.format_amount(0.06, "scu", co.VOLUME_CSCU) == "6 cSCU"
        assert co.format_amount(0.06, "scu", co.VOLUME_SCU) == "0.06 SCU"
        assert co.format_amount(1.5, "scu", co.VOLUME_CSCU) == "150 cSCU"
        assert co.format_amount(3, "unit") == "3 pcs"

    def test_search(self):
        names = {"tungsten": "Tungsten", "gold": "Gold"}
        assert [bp["k"] for bp in co.search_blueprints([BP, PICK], "test", names)] == [
            "armor",
            "rifle",
        ]
        assert [bp["k"] for bp in co.search_blueprints([BP, PICK], "rifle", names)] == ["rifle"]
        assert [bp["k"] for bp in co.search_blueprints([BP, PICK], "tungsten armor", names)] == [
            "armor"
        ]
        assert co.search_blueprints([BP], "  ") == []
        keep = lambda bp: bp["k"] == "rifle"  # noqa: E731
        found = co.search_blueprints([BP, PICK], "test", names, keep=keep)
        assert [bp["k"] for bp in found] == ["rifle"]

    def test_order_text(self):
        line = co.new_line(BP)
        line.count = 2
        totals = co.material_totals([line], BY_KEY)
        text = co.order_text(totals, [line], BY_KEY, {"tungsten": "Tungsten"})
        assert text.splitlines()[0] == "Crafting order: 2 crafts"
        assert "- 2 x Test Rifle" in text
        assert "- Tungsten: 12 cSCU (12 cSCU at quality 500+)" in text


class TestSavedOrders:
    def test_names_are_made_safe_for_windows(self):
        assert co.saved_order_name("  Mining  run #2 ") == "Mining run #2"
        assert co.saved_order_name('a/b:c?"<>|*') == "abc"
        assert co.saved_order_name("trailing... ") == "trailing"
        assert co.saved_order_name("CON") == "" and co.saved_order_name("com1.txt") == ""
        assert co.saved_order_name("") == "" and co.saved_order_name("???") == ""
        assert len(co.saved_order_name("x" * 200)) == co.SAVED_ORDER_NAME_MAX

    def test_save_list_and_read(self, tmp_path):
        folder = tmp_path / "orders"
        assert co.list_saved_orders(folder) == []
        line = co.new_line(BP)
        line.count = 3
        path = co.save_order(folder, "Rifles: week 1", [line])
        assert path == folder / "Rifles week 1.json"
        co.save_order(folder, "armor", [co.new_line(PICK)])
        (folder / "notes.txt").write_text("x", encoding="utf-8")
        assert co.list_saved_orders(folder) == ["armor", "Rifles week 1"]
        raw = co.read_saved_order(folder, "Rifles week 1")
        assert [(line.key, line.count) for line in co.load_order(raw, BY_KEY)] == [("rifle", 3)]
        # Saving under the same name replaces it.
        co.save_order(folder, "Rifles week 1", [co.new_line(PICK)])
        assert [r["key"] for r in co.read_saved_order(folder, "Rifles week 1")] == ["armor"]

    def test_delete(self, tmp_path):
        co.save_order(tmp_path, "run", [co.new_line(BP)])
        co.delete_saved_order(tmp_path, "run")
        assert co.list_saved_orders(tmp_path) == []
        co.delete_saved_order(tmp_path, "run")  # already gone: no error
        co.delete_saved_order(tmp_path, "CON")  # unusable name: nothing to do

    def test_bad_input(self, tmp_path):
        with pytest.raises(ValueError):
            co.save_order(tmp_path, "CON", [])
        assert co.read_saved_order(tmp_path, "missing") == []
        (tmp_path / "broken.json").write_text("{", encoding="utf-8")
        assert co.read_saved_order(tmp_path, "broken") == []
