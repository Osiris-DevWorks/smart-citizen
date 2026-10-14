"""SCO drawer data: the Mining Compendium parse, star systems, crafting index."""
from pathlib import Path

import pytest

from src.utils.mining_catalog import (
    CRAFTING_INDEX_FILE, NYX, PYRO, STANTON, CraftingIndex, load_crafting_index,
    locations_by_system, minerals_at, ore_signature, parse_mining_compendium,
    read_compendium, star_system, write_crafting_index,
)

pytestmark = pytest.mark.unit

FIXTURE = Path(__file__).parent / "fixtures" / "kraken_global_latest.ini"


def test_compendium_from_a_real_base_ini():
    minerals = read_compendium(FIXTURE)
    assert len(minerals) >= 30
    assert minerals["Quantainium"].tier == "Legendary"
    assert "Keeger Belt" in minerals["Savrilium"].locations
    # "Found in" prose is stripped from the first location.
    assert not any(loc.lower().startswith("found in")
                   for m in minerals.values() for loc in m.locations)


def test_every_named_place_has_a_star_system():
    locations = {loc for m in read_compendium(FIXTURE).values() for loc in m.locations}
    assert {loc for loc in locations if not star_system(loc)} <= {"All Moons/Planets/Caves"}


@pytest.mark.parametrize("location, system", [
    ("HUR-L1", STANTON), ("arc-l5", STANTON), ("All Stanton Deposits", STANTON),
    ("Yela", STANTON), ("Monox", PYRO), ("All Pyro Planets", PYRO),
    ("QV Breaker Stations (Nyx)", NYX), ("Keeger Belt", NYX), ("Somewhere", ""),
])
def test_star_system(location, system):
    assert star_system(location) == system


def test_locations_grouped_in_system_order_unplaced_last():
    grouped = locations_by_system(["Somewhere", "Monox", "Yela", "Keeger Belt", "Aberdeen"])
    assert list(grouped) == [STANTON, PYRO, NYX, ""]
    assert grouped[STANTON] == ["Aberdeen", "Yela"]


def test_parse_takes_escaped_or_real_line_breaks():
    text = "Intro line\\n** Rare **\\nBeryl - Found in Aaron Halo, Monox\\nNot a mineral - x"
    for content in (text, text.replace("\\n", "\n")):
        minerals = parse_mining_compendium(content)
        assert list(minerals) == ["Beryl"]
        assert minerals["Beryl"].tier == "Rare"
        assert minerals["Beryl"].locations == ("Aaron Halo", "Monox")


def test_missing_base_ini_reads_nothing(tmp_path):
    assert read_compendium(tmp_path / "base.ini") == {}


def test_ore_signature_follows_the_compendium_spelling():
    assert ore_signature("Savrilium") == ore_signature("savrillium") is not None
    assert ore_signature("Nonsense") is None


def test_minerals_at():
    minerals = parse_mining_compendium("Beryl - Yela, Monox\\nGold - yela")
    assert minerals_at("Yela", minerals) == ["Beryl", "Gold"]


def test_crafting_index_round_trip(tmp_path):
    path = tmp_path / CRAFTING_INDEX_FILE
    write_crafting_index(path, {
        "beryl": {"names": ["Beryl (Raw)"], "items": [["Armor", "Helmet"], ["Weapons", "Pistol"]]},
        "gold": {"names": ["Gold"], "items": [["Weapons", "Pistol"]]},
    })
    index = load_crafting_index(path)
    assert index.items_using("beryl") == [("Armor", "Helmet"), ("Weapons", "Pistol")]
    assert index.materials_for("Pistol") == ["Beryl (Raw)", "Gold"]
    assert index.items() == {"Helmet": "Armor", "Pistol": "Weapons"}
    assert index.material_key_for("Beryl") == "beryl"
    assert index.material_key_for("Tin") is None


@pytest.mark.parametrize("mineral, key", [
    # CIG spells these differently in the compendium and the crafting data.
    ("Aluminium", "aluminum"),
    ("Beradon", "beradom"),
    ("Caranite", "carinite"),
    ("Ice", "pressurized_ice"),
    ("Beryl", "beryl"),
    ("Quantainium", None),
])
def test_material_key_for_bridges_cig_spellings(mineral, key):
    # Names as the LIVE 4.9 crafting_index.json holds them.
    index = CraftingIndex({
        "aluminum": {"names": ["Aluminum", "Aluminum (Ore)"], "items": []},
        "beradom": {"names": ["Beradom"], "items": []},
        "carinite": {"names": ["Carinite", "Carinite (Pure)"], "items": []},
        "pressurized_ice": {"names": ["Pressurized Ice"], "items": []},
        "beryl": {"names": ["Beryl", "Beryl (Raw)"], "items": []},
    })
    assert index.material_key_for(mineral) == key


def test_material_key_for_prefers_an_exact_name():
    # "Copper Ore" comes first, but a material named exactly "Copper" wins.
    index = CraftingIndex({
        "copper_ore": {"names": ["Copper Ore"], "items": []},
        "copper": {"names": ["Copper"], "items": []},
    })
    assert index.material_key_for("Copper") == "copper"
    assert CraftingIndex({"copper_ore": {"names": ["Copper Ore"]}}).material_key_for(
        "Copper") == "copper_ore"


@pytest.mark.parametrize("content", [None, "not json", "[1, 2]", '{"materials": 3}'])
def test_unreadable_index_is_empty(tmp_path, content):
    path = tmp_path / CRAFTING_INDEX_FILE
    if content is not None:
        path.write_text(content, encoding="utf-8")
    assert load_crafting_index(path).materials == {}
    assert isinstance(load_crafting_index(path), CraftingIndex)


@pytest.mark.parametrize("line", [
    "Journal_General_Mining_Compendium_Content,P=Beryl - Yela\n",
    "journal_general_mining_compendium_content = Beryl - Yela\r\n",
])
def test_compendium_key_read_like_the_ini_parser(tmp_path, line):
    base = tmp_path / "base.ini"
    base.write_bytes(b"\xef\xbb\xbfOther_Key=x\n" + line.encode("utf-8"))
    assert read_compendium(base)["Beryl"].locations == ("Yela",)


def test_stock_shaped_compendium_without_tier_headings():
    """The stock text has no tier headings, only paragraphs between blank
    lines; minerals still parse, each with an empty tier."""
    content = ("Mining is a profession...\\n\\n"
               "Beryl - Found in Aaron Halo, ARC-L3, Wala\\n\\n"
               "Hadanite - Aberdeen, All Moons/Planets/Caves\\n\\n"
               "Prices change with demand.")
    minerals = parse_mining_compendium(content)
    assert set(minerals) == {"Beryl", "Hadanite"}
    assert minerals["Beryl"].locations == ("Aaron Halo", "ARC-L3", "Wala")
    assert all(m.tier == "" for m in minerals.values())
