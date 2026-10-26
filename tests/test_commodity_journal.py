"""Regression tests for ``scan_crafting_blueprints`` return shape.

Pre-1.4.1, the function's early-return when the crafting blueprints
directory was missing returned a single empty dict, while the happy path
returned a ``(commodity_out, journal_out)`` 2-tuple. The dispatcher in
``main()`` unpacks the result into ``out_commodities, out_journal`` —
so any user whose DataForge cache happened to lack the crafting tree
crashed the enhancements pipeline with::

    ValueError: not enough values to unpack (expected 2, got 0)

This test locks both halves of the contract: returns a 2-tuple of dicts
on the missing-directory path AND on the present-but-empty path.
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace as dc_replace
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.utils.tag_builder import default_config  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.fixture(scope="module")
def gen_module():
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "generate_enhancements_ini.py"
    spec = importlib.util.spec_from_file_location(
        "generate_enhancements_ini_commodity_test", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _enabled_commodities_config():
    """default_config("commodities") ships with every element disabled
    (#325) -- these tests exercise the crafting-cost scanner's [CF] tagging
    logic, which is independent of that default, so they build their own
    enabled copy."""
    cfg = default_config("commodities")
    return dc_replace(
        cfg,
        elements=[dc_replace(e, enabled=True) for e in cfg.elements],
    )


class TestCraftingCostItemPickup:
    """Regression: ``CraftingCost_Item entityClass=...`` references must be
    counted as crafting material references alongside ``CraftingCost_Resource
    resource=...``.

    Pre-1.4.1 the scanner only collected the Resource path, which silently
    excluded every blueprint slot that referenced a carryable directly by its
    entity-class UUID. Concretely: the Omnisky III laser cannon spec spawns
    Hadanite (Emitter) and Dolivine (Aperture Iris) via CraftingCost_Item,
    so neither gem was getting the ``[CF]`` tag or the Mining Compendium
    augmentation despite being in active crafting recipes.

    Also locks the filename regex extension covering the
    ``harvestable_mineral_1h_<gem>`` entity files where hand-mineable gems
    actually live (the existing ``commodity_(metal|mineral|...)_<name>``
    pattern matched bulk carryables only).
    """

    def test_blueprint_material_uids_collect_item_entityclass_uuids(self, gen_module, tmp_path):
        bp_file = tmp_path / "bp_test.xml"
        bp_file.write_text(
            '<CraftingBlueprintRecord __type="CraftingBlueprintRecord">'
            '<options>'
            '<CraftingCost_Resource resource="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"/>'
            '<CraftingCost_Item entityClass="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb" quantity="3"/>'
            '<CraftingCost_Item entityClass="00000000-0000-0000-0000-000000000000"/>'
            '</options>'
            '</CraftingBlueprintRecord>',
            encoding="utf-8",
        )
        # The UUIDs scan_crafting_blueprints' blueprint pass hands to the
        # carryable resolver (perf proposal: it collects them as it reads
        # each blueprint, so there is no separate UUID scan to call).
        with mock.patch.object(gen_module, "_build_uuid_to_commodity",
                               return_value={}) as resolve:
            gen_module.scan_crafting_blueprints(tmp_path, tmp_path / "carryables", {}, {})
        uuids = resolve.call_args.args[0]
        assert "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa" in uuids, (
            "CraftingCost_Resource UUID must still be collected"
        )
        assert "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb" in uuids, (
            "CraftingCost_Item entityClass UUID must be collected"
        )
        assert "00000000-0000-0000-0000-000000000000" not in uuids, (
            "Zero-UUID sentinel must be filtered"
        )

    def test_filename_regex_matches_harvestable_handheld(self, gen_module, tmp_path):
        """An ``harvestable_mineral_1h_<gem>.xml`` carryable referenced by a
        blueprint via CraftingCost_Item must resolve to its gem commodity."""
        gem_uuid = "1234abcd-1234-abcd-1234-1234abcd1234"

        # Carryable file with the handheld filename schema.
        carryables = tmp_path / "carryables"
        carryables.mkdir()
        (carryables / "harvestable_mineral_1h_hadanite.xml").write_text(
            f'<Entity __ref="{gem_uuid}"/>', encoding="utf-8"
        )

        # Blueprint references the gem via CraftingCost_Item.
        bp_dir = tmp_path / "bp"
        bp_dir.mkdir()
        (bp_dir / "bp_craft_test_weapon.xml").write_text(
            f'<CraftingBlueprintRecord>'
            f'<CraftingProcess_Creation entityClass="ffff0000-0000-0000-0000-000000000000"/>'
            f'<CraftingCost_Item entityClass="{gem_uuid}" quantity="7"/>'
            f'</CraftingBlueprintRecord>',
            encoding="utf-8",
        )

        loc = {
            "items_commodities_hadanite": "Hadanite",
            "items_commodities_hadanite_desc": "A crystal oscillator.",
        }
        commodities, _journal = gen_module.scan_crafting_blueprints(
            bp_dir=bp_dir,
            carryables_dir=carryables,
            entity_names={},
            loc=loc,
            tag_config=_enabled_commodities_config(),
        )
        assert "items_commodities_hadanite" in commodities
        assert "[CF]" in commodities["items_commodities_hadanite"]
        assert "items_commodities_hadanite_desc" in commodities
        assert "BLUEPRINT DATA" in commodities["items_commodities_hadanite_desc"]

    def test_resource_and_item_paths_unify(self, gen_module, tmp_path):
        """When a single blueprint uses both element types, BOTH commodities
        get attributed to that blueprint."""
        agricium_uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        hadanite_uuid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

        carryables = tmp_path / "carryables"
        carryables.mkdir()
        # Bulk-schema carryable referencing the abstract resource UUID.
        (carryables / "carryable_tbo_fl_1scu_commodity_metal_agricium.xml").write_text(
            f'<Entity><Reference value="{agricium_uuid}"/></Entity>',
            encoding="utf-8",
        )
        # Handheld-schema carryable with its own __ref as the entity UUID.
        (carryables / "harvestable_mineral_1h_hadanite.xml").write_text(
            f'<Entity __ref="{hadanite_uuid}"/>', encoding="utf-8"
        )

        bp_dir = tmp_path / "bp"
        bp_dir.mkdir()
        (bp_dir / "bp_craft_omnisky_like.xml").write_text(
            f'<CraftingBlueprintRecord>'
            f'<CraftingProcess_Creation entityClass="ffff0000-0000-0000-0000-000000000000"/>'
            f'<CraftingCost_Resource resource="{agricium_uuid}"/>'
            f'<CraftingCost_Item entityClass="{hadanite_uuid}" quantity="7"/>'
            f'</CraftingBlueprintRecord>',
            encoding="utf-8",
        )

        loc = {
            "items_commodities_agricium": "Agricium",
            "items_commodities_agricium_desc": "Industrial mineral.",
            "items_commodities_hadanite": "Hadanite",
            "items_commodities_hadanite_desc": "A crystal oscillator.",
        }
        commodities, _journal = gen_module.scan_crafting_blueprints(
            bp_dir=bp_dir,
            carryables_dir=carryables,
            entity_names={},
            loc=loc,
            tag_config=_enabled_commodities_config(),
        )
        assert "[CF]" in commodities.get("items_commodities_agricium", "")
        assert "[CF]" in commodities.get("items_commodities_hadanite", "")

    def test_fills_the_sco_crafting_index(self, gen_module, tmp_path):
        """Given a dict, the scan records each material's display names and
        the (category, item) pairs it goes into, for the SCO drawer."""
        hadanite_uuid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        item_uuid = "ffff0000-0000-0000-0000-000000000000"
        carryables = tmp_path / "carryables"
        carryables.mkdir()
        (carryables / "harvestable_mineral_1h_hadanite.xml").write_text(
            f'<Entity __ref="{hadanite_uuid}"/>', encoding="utf-8"
        )
        bp_dir = tmp_path / "bp"
        (bp_dir / "armour").mkdir(parents=True)
        (bp_dir / "armour" / "bp_craft_test_helmet.xml").write_text(
            f'<CraftingBlueprintRecord>'
            f'<CraftingProcess_Creation entityClass="{item_uuid}"/>'
            f'<CraftingCost_Item entityClass="{hadanite_uuid}" quantity="7"/>'
            f'</CraftingBlueprintRecord>',
            encoding="utf-8",
        )
        index = {}
        gen_module.scan_crafting_blueprints(
            bp_dir=bp_dir,
            carryables_dir=carryables,
            entity_names={item_uuid: "Test Helmet"},
            loc={"items_commodities_hadanite": "Hadanite",
                 "items_commodities_hadanite_desc": "A crystal oscillator."},
            tag_config=_enabled_commodities_config(),
            crafting_index=index,
        )
        assert index["hadanite"]["names"] == ["Hadanite"]
        assert [item for _cat, item in index["hadanite"]["items"]] == ["Test Helmet"]

    def test_the_crafting_index_order_does_not_change_between_runs(self, gen_module, tmp_path):
        """The materials of one blueprint were read from a set, so their
        order in crafting_index.json, the order they were first met in,
        changed with every run's string hashing (found in the perf proposal's
        review). Now each blueprint's materials are met in name order, so
        the index keeps them in the order they are first met, blueprint by
        blueprint, each blueprint's by name. All eight here are in one
        blueprint, which makes any other order fail."""
        gems = ["saldynium", "hadanite", "glacosite", "aphorite",
                "janalite", "dolivine", "feynmaline", "beradom"]
        carryables = tmp_path / "carryables"
        carryables.mkdir()
        costs, loc = [], {}
        for n, gem in enumerate(gems):
            uuid = f"{n + 1:08x}-0000-0000-0000-000000000000"   # the all-zero one is skipped
            (carryables / f"harvestable_mineral_1h_{gem}.xml").write_text(
                f'<Entity __ref="{uuid}"/>', encoding="utf-8")
            costs.append(f'<CraftingCost_Item entityClass="{uuid}" quantity="1"/>')
            loc[f"items_commodities_{gem}"] = gem.title()
        item_uuid = "ffff0000-0000-0000-0000-000000000000"
        bp_dir = tmp_path / "bp"
        (bp_dir / "armour").mkdir(parents=True)
        (bp_dir / "armour" / "bp_craft_test_helmet.xml").write_text(
            f'<CraftingBlueprintRecord>'
            f'<CraftingProcess_Creation entityClass="{item_uuid}"/>'
            + "".join(costs) + '</CraftingBlueprintRecord>',
            encoding="utf-8",
        )
        index = {}
        gen_module.scan_crafting_blueprints(
            bp_dir=bp_dir,
            carryables_dir=carryables,
            entity_names={item_uuid: "Test Helmet"},
            loc=loc,
            tag_config=_enabled_commodities_config(),
            crafting_index=index,
        )
        assert list(index) == sorted(gems)

    def test_crafting_index_names_follow_the_selected_language(self, gen_module, tmp_path):
        """The SCO index keeps the selected language's material names (ctx
        "loc"), not the English annotation loc ("tag_loc"): a German player
        sees German names in the drawer's Crafting search, and a mineral
        still finds them through the English key."""
        hadanite_uuid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        item_uuid = "ffff0000-0000-0000-0000-000000000000"
        records = tmp_path / "records"
        scitem_dir = records / "entities" / "scitem"
        (scitem_dir / "carryables").mkdir(parents=True)
        (scitem_dir / "carryables" / "harvestable_mineral_1h_hadanite.xml").write_text(
            f'<Entity __ref="{hadanite_uuid}"/>', encoding="utf-8")
        bp_dir = records / "crafting" / "blueprints" / "crafting" / "armour"
        bp_dir.mkdir(parents=True)
        (bp_dir / "bp_craft_test_helmet.xml").write_text(
            f'<CraftingBlueprintRecord>'
            f'<CraftingProcess_Creation entityClass="{item_uuid}"/>'
            f'<CraftingCost_Item entityClass="{hadanite_uuid}" quantity="7"/>'
            f'</CraftingBlueprintRecord>',
            encoding="utf-8")
        ctx = {
            "records": records,
            "scitem_dir": scitem_dir,
            "entity_names": {item_uuid: "Test Helmet"},
            "loc": {"items_commodities_hadanite": "Hadanit",
                    "items_commodities_hadanite_desc": "Ein Kristalloszillator."},
            "tag_loc": {"items_commodities_hadanite": "Hadanite",
                        "items_commodities_hadanite_desc": "A crystal oscillator."},
            "tag_configs": {"commodities": _enabled_commodities_config()},
            "crafting_index": {},
        }
        gen_module._run_gen_commodity_journal(ctx)
        assert ctx["crafting_index"]["hadanite"]["names"] == ["Hadanit"]


class TestScanCraftingBlueprintsReturnShape:
    def test_missing_directory_returns_two_empty_dicts(self, gen_module, tmp_path):
        """The early-return path (no crafting blueprints dir) must produce a
        2-tuple to match the happy-path shape — otherwise the dispatcher in
        ``main()`` fails to unpack the result."""
        nonexistent = tmp_path / "does_not_exist"
        carryables = tmp_path / "carryables_also_missing"

        result = gen_module.scan_crafting_blueprints(
            bp_dir=nonexistent,
            carryables_dir=carryables,
            entity_names={},
            loc={},
        )

        assert isinstance(result, tuple), (
            "scan_crafting_blueprints must return a 2-tuple even when bp_dir "
            "is missing — the main() dispatcher unpacks the result into "
            "(out_commodities, out_journal) unconditionally."
        )
        assert len(result) == 2
        commodities, journal = result
        assert commodities == {}
        assert journal == {}

    def test_dispatcher_unpack_against_missing_dir(self, gen_module, tmp_path):
        """End-to-end shape guard: a fresh ``(out_commodities, out_journal) =
        scan_crafting_blueprints(...)`` unpack must not raise even when the
        directory is missing. This is the exact line that crashed in 1.3.1."""
        out_commodities, out_journal = gen_module.scan_crafting_blueprints(
            bp_dir=tmp_path / "missing",
            carryables_dir=tmp_path / "missing_too",
            entity_names={},
            loc={},
        )
        assert out_commodities == {}
        assert out_journal == {}


class TestCraftItemCondensing:
    """Humanized category labels + consolidated quantum-drive buckets in the
    journal / commodity BLUEPRINT DATA craft list (2.1 journal redesign)."""

    def test_humanize_category(self, gen_module):
        h = gen_module._humanize_craft_category
        assert h("crafting/vehiclegear/powerplant") == "Power Plants"
        assert h("crafting/vehiclegear/cooler") == "Coolers"
        assert h("crafting/vehiclegear/refuelling/nozzle") == "Refuel Nozzles"
        # Unknown category falls back to a title-cased last segment.
        assert h("crafting/vehiclegear/somethingnew") == "Somethingnew"

    def test_qd_size_range(self, gen_module):
        r = gen_module._qd_size_range
        assert r([3]) == "S3"
        assert r([1, 2, 3]) == "S1-S3"
        assert r([2, 4]) == "S2, S4"

    def test_condense_humanizes_and_consolidates_qd(self, gen_module):
        items = [
            ("weapons/rifle", "Karna Rifle"),
            ("crafting/vehiclegear/powerplant", "a"),
            ("crafting/vehiclegear/quantumdrive/size1", "b"),
            ("crafting/vehiclegear/quantumdrive/size2", "c"),
            ("crafting/vehiclegear/quantumdrive/size3", "d"),
        ]
        out = gen_module._condense_crafted_items(items)
        # Alphabetized, humanized, QD sizes consolidated into one line.
        assert out == [
            "Karna Rifle",
            "Power Plants: 1 items",
            "Quantum Drives: 3 items (S1-S3)",
        ]


class TestCompendiumLocations:
    """Shared Compendium location parsing feeding both the journal and the
    individual commodity descriptions (2.1 commodity-desc revamp)."""

    # INI values use the literal two-character sequence backslash-n as the
    # line separator, so the test content must too (\\n in source == \n on disk).
    _CONTENT = (
        "Intro prose with no dash-entry shape here.\\n\\n"
        "Agricium - ARC-L3, Cellin, CRU-L5, Daymar\\n\\n"
        "Aluminium - Aaron Halo, ARC-L1"
    )

    def test_parse_skips_prose_and_sorts(self, gen_module):
        locs = gen_module._parse_compendium_locations(self._CONTENT)
        assert set(locs) == {"agricium", "aluminium"}
        assert locs["agricium"] == ["ARC-L3", "Cellin", "CRU-L5", "Daymar"]

    def test_lookup_by_display_first_word_and_internal(self, gen_module):
        locs = gen_module._parse_compendium_locations(self._CONTENT)
        assert gen_module._lookup_commodity_locations(locs, "Agricium", "agricium")[0] == "ARC-L3"
        # First-word match: "Aluminium (Ore)" -> aluminium.
        assert gen_module._lookup_commodity_locations(locs, "Aluminium (Ore)", "aluminum_ore") is not None
        # Miss.
        assert gen_module._lookup_commodity_locations(locs, "Gold", "gold") is None

    def test_empty_content_is_empty(self, gen_module):
        assert gen_module._parse_compendium_locations("") == {}


class TestMiningCompendiumRSTagging:
    """Base Resource Signature line added to each ore's block in the
    "Mining Fundamentals #2: Where to Mine" journal entry (from
    MINEABLE_RS_VALUES) when a confirmed value exists; silently omitted
    otherwise. Community reference: starminersdepot.com's Alpha 4.8 scanner
    table, cross-checked against the pre-existing Battaglia RS values."""

    def test_known_ore_gets_rs_line(self, gen_module, tmp_path):
        content = "Aluminium - Aaron Halo, ARC-L1"
        bp_dir = tmp_path / "bp"
        bp_dir.mkdir()
        _commodities, journal = gen_module.scan_crafting_blueprints(
            bp_dir=bp_dir,
            carryables_dir=tmp_path / "carryables",
            entity_names={},
            loc={
                "Journal_General_Mining_Compendium_Title": "Mining Fundamentals #2: Where to Mine",
                "Journal_General_Mining_Compendium_Content": content,
            },
        )
        result = journal["Journal_General_Mining_Compendium_Content"]
        assert "Base Resource Signature: <EM4>4285</EM4>" in result
        assert "<EM4>Locations:</EM4>" in result

    def test_unknown_ore_has_no_rs_line(self, gen_module, tmp_path):
        content = "Aphorite - All Moons/Planets/Caves"
        bp_dir = tmp_path / "bp"
        bp_dir.mkdir()
        _commodities, journal = gen_module.scan_crafting_blueprints(
            bp_dir=bp_dir,
            carryables_dir=tmp_path / "carryables",
            entity_names={},
            loc={
                "Journal_General_Mining_Compendium_Title": "Mining Fundamentals #2: Where to Mine",
                "Journal_General_Mining_Compendium_Content": content,
            },
        )
        result = journal["Journal_General_Mining_Compendium_Content"]
        assert "Base Resource Signature" not in result

    def test_savrilium_typo_spelling_still_matches(self, gen_module, tmp_path):
        """The journal's own prose spells it "Savrilium" (single L), but the
        DataForge loc key and MINEABLE_RS_VALUES both use "savrillium" —
        _MINING_COMPENDIUM_ORE_ALIASES must bridge the two."""
        content = "Savrilium - Glaciem Ring, Keeger Belt"
        bp_dir = tmp_path / "bp"
        bp_dir.mkdir()
        _commodities, journal = gen_module.scan_crafting_blueprints(
            bp_dir=bp_dir,
            carryables_dir=tmp_path / "carryables",
            entity_names={},
            loc={
                "Journal_General_Mining_Compendium_Title": "Mining Fundamentals #2: Where to Mine",
                "Journal_General_Mining_Compendium_Content": content,
            },
        )
        result = journal["Journal_General_Mining_Compendium_Content"]
        assert "Base Resource Signature: <EM4>3200</EM4>" in result
