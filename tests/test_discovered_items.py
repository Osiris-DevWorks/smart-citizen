"""Tests for XML-based item discovery when base.ini has no entry.

The enhancement generator now synthesizes descriptions from XML attributes
for items whose loc key is absent from base.ini, so they appear in the
output with status "New".
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from lxml import etree as ET

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def gen_module():
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "generate_enhancements_ini.py"
    spec = importlib.util.spec_from_file_location("generate_enhancements_ini_discovery_test", script_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ── _synthesize_description ──────────────────────────────────────────────────

class TestSynthesizeDescription:
    """Covers ``_synthesize_description`` with various XML shapes."""

    def test_from_loc_name_key(self, gen_module, tmp_path):
        """When the XML has a Name loc ref, use it as the display name."""
        xml = """<EntityClassDefinition>
          <Components>
            <Localization Name="@item_NameSHLD_TestShield" Description="@item_DescSHLD_TestShield"/>
          </Components>
        </EntityClassDefinition>"""
        xml_file = tmp_path / "test_shield.xml"
        xml_file.write_text(xml, encoding="utf-8")
        root = ET.parse(xml_file).getroot()
        result = gen_module._synthesize_description(root, xml_file, "item_DescSHLD_TestShield")
        assert "item_NameSHLD_TestShield" in result

    def test_from_file_stem(self, gen_module, tmp_path):
        """When no Name loc ref, fall back to cleaned file stem."""
        xml = """<EntityClassDefinition>
          <Components>
            <Localization Description="@item_DescSHLD_TestShield"/>
          </Components>
        </EntityClassDefinition>"""
        xml_file = tmp_path / "AEGS_Test_Shield.xml"
        xml_file.write_text(xml, encoding="utf-8")
        root = ET.parse(xml_file).getroot()
        result = gen_module._synthesize_description(root, xml_file, "item_DescSHLD_TestShield")
        assert "AEGS Test Shield" in result

    def test_from_key_fallback(self, gen_module, tmp_path):
        """When no Name ref and no Localization element, fall back to file stem."""
        xml = """<EntityClassDefinition/>"""
        xml_file = tmp_path / "unnamed_entity.xml"
        xml_file.write_text(xml, encoding="utf-8")
        root = ET.parse(xml_file).getroot()
        result = gen_module._synthesize_description(root, xml_file, "item_DescSHLD_TestShield")
        assert "unnamed entity" in result

    def test_vehicle_params_extracted(self, gen_module, tmp_path):
        """Ship XMLs get career, role, crew, length extracted."""
        xml = """<EntityClassDefinition>
          <Components>
            <VehicleComponentParams crewSize="2"
                vehicleCareer="@vehicle_career_Fighter"
                vehicleRole="@vehicle_role_HeavyFighter">
              <maxBoundingBoxSize y="32.5"/>
            </VehicleComponentParams>
            <Localization Description="@vehicle_DescAEGS_TestShip"/>
          </Components>
        </EntityClassDefinition>"""
        xml_file = tmp_path / "AEGS_Test_Ship.xml"
        xml_file.write_text(xml, encoding="utf-8")
        root = ET.parse(xml_file).getroot()
        result = gen_module._synthesize_description(root, xml_file, "vehicle_DescAEGS_TestShip")
        assert "Crew: 2" in result
        assert "32.5m" in result
        assert "vehicle_career_Fighter" in result
        assert "vehicle_role_HeavyFighter" in result

    def test_missile_tracking_extracted(self, gen_module, tmp_path):
        """Missile XMLs get tracking signal type extracted."""
        xml = """<EntityClassDefinition>
          <Components>
            <targetingParams trackingSignalType="Infrared"/>
            <Localization Description="@item_DescMISS_TestMissile"/>
          </Components>
        </EntityClassDefinition>"""
        xml_file = tmp_path / "test_missile.xml"
        xml_file.write_text(xml, encoding="utf-8")
        root = ET.parse(xml_file).getroot()
        result = gen_module._synthesize_description(root, xml_file, "item_DescMISS_TestMissile")
        assert "Tracking: Infrared" in result

    def test_item_type_extracted(self, gen_module, tmp_path):
        """Component XMLs get item type extracted."""
        xml = """<EntityClassDefinition>
          <Components>
            <ItemComponentParams itemType="ShieldGenerator"/>
            <Localization Description="@item_DescSHLD_TestComp"/>
          </Components>
        </EntityClassDefinition>"""
        xml_file = tmp_path / "test_comp.xml"
        xml_file.write_text(xml, encoding="utf-8")
        root = ET.parse(xml_file).getroot()
        result = gen_module._synthesize_description(root, xml_file, "item_DescSHLD_TestComp")
        assert "Item Type: ShieldGenerator" in result


# ── scan_entity_dir discovery ────────────────────────────────────────────────

class TestScanEntityDirDiscovery:
    """Covers ``scan_entity_dir`` discovering items missing from loc."""

    def _make_component_xml(self, tmp_path: Path, name: str, desc_key: str,
                            health: int = 500) -> Path:
        xml = f"""<EntityClassDefinition>
          <Components>
            <SHealthComponentParams Health="{health}"/>
            <ItemComponentParams itemType="ShieldGenerator"/>
            <Localization Description="@{desc_key}"/>
          </Components>
        </EntityClassDefinition>"""
        xml_file = tmp_path / f"{name}.xml"
        xml_file.write_text(xml, encoding="utf-8")
        return xml_file

    def test_discovers_item_not_in_loc(self, gen_module, tmp_path):
        """Items with a valid loc key but missing from loc dict are discovered."""
        self._make_component_xml(tmp_path, "test_shield", "item_DescSHLD_Missing")

        def dummy_enhancement_fn(root):
            return "HP: 500"

        result = gen_module.scan_entity_dir(
            tmp_path, dummy_enhancement_fn, loc={}, capture_all=False,
        )
        assert "item_DescSHLD_Missing" in result
        assert "HP: 500" in result["item_DescSHLD_Missing"]

    def test_enhances_existing_item_normally(self, gen_module, tmp_path):
        """Items present in loc still get the normal base+stats treatment."""
        self._make_component_xml(tmp_path, "test_shield", "item_DescSHLD_Existing")
        loc = {"item_DescSHLD_Existing": "A basic shield generator."}

        def dummy_enhancement_fn(root):
            return "HP: 500"

        result = gen_module.scan_entity_dir(
            tmp_path, dummy_enhancement_fn, loc=loc, capture_all=False,
        )
        assert "item_DescSHLD_Existing" in result
        assert "A basic shield generator." in result["item_DescSHLD_Existing"]
        assert "HP: 500" in result["item_DescSHLD_Existing"]

    def test_discovered_item_with_empty_enhancement(self, gen_module, tmp_path):
        """Discovered items are emitted even when enhancement_fn returns empty."""
        self._make_component_xml(tmp_path, "test_empty", "item_DescSHLD_Empty")

        def empty_enhancement_fn(root):
            return ""

        result = gen_module.scan_entity_dir(
            tmp_path, empty_enhancement_fn, loc={}, capture_all=False,
        )
        assert "item_DescSHLD_Empty" in result

    def test_discovered_counter_increments(self, gen_module, tmp_path):
        """The discovered counter tracks items found via XML but missing from loc."""
        self._make_component_xml(tmp_path, "shield1", "item_DescSHLD_A")
        self._make_component_xml(tmp_path, "shield2", "item_DescSHLD_B")
        loc = {"item_DescSHLD_B": "Existing shield."}

        def dummy_enhancement_fn(root):
            return "stats"

        result = gen_module.scan_entity_dir(
            tmp_path, dummy_enhancement_fn, loc=loc, capture_all=False,
        )
        assert "item_DescSHLD_A" in result  # discovered (not in loc)
        assert "item_DescSHLD_B" in result  # in loc, enhanced normally


# ── scan_spaceships discovery ────────────────────────────────────────────────

class TestScanSpaceshipsDiscovery:
    """Covers ``scan_spaceships`` discovering ships missing from loc."""

    def _make_ship_xml(self, tmp_path: Path, name: str, desc_key: str,
                       crew: int = 1) -> Path:
        xml = f"""<EntityClassDefinition.Spaceships.AEGS_TestShip>
          <Components>
            <VehicleComponentParams crewSize="{crew}"
                vehicleDescription="@{desc_key}"
                vehicleCareer="@vehicle_career_Fighter"
                vehicleRole="@vehicle_role_LightFighter">
              <maxBoundingBoxSize y="27.0"/>
            </VehicleComponentParams>
            <SEntityComponentDefaultLoadoutParams/>
          </Components>
        </EntityClassDefinition.Spaceships.AEGS_TestShip>"""
        xml_file = tmp_path / f"{name}.xml"
        xml_file.write_text(xml, encoding="utf-8")
        return xml_file

    def test_discovers_ship_not_in_loc(self, gen_module, tmp_path):
        """Ships with a valid loc key but missing from loc dict are discovered."""
        self._make_ship_xml(tmp_path, "AEGS_Test_Ship", "vehicle_DescAEGS_TestShip")

        result = gen_module.scan_spaceships(
            tmp_path, controller_lookup={}, loc={},
        )
        assert "vehicle_DescAEGS_TestShip" in result
        entry = result["vehicle_DescAEGS_TestShip"]
        assert "Crew: 1" in entry
        assert "27.0m" in entry

    def test_enhances_existing_ship_normally(self, gen_module, tmp_path):
        """Ships present in loc still get the normal base+stats treatment."""
        self._make_ship_xml(tmp_path, "AEGS_Test_Ship", "vehicle_DescAEGS_TestShip")
        loc = {"vehicle_DescAEGS_TestShip": "A fast light fighter."}

        result = gen_module.scan_spaceships(
            tmp_path, controller_lookup={}, loc=loc,
        )
        assert "vehicle_DescAEGS_TestShip" in result
        assert "A fast light fighter." in result["vehicle_DescAEGS_TestShip"]

    def test_skips_ship_whose_key_is_blank(self, gen_module, tmp_path):
        """#561: a key base.ini leaves blank gets no stats, since the game
        shows it elsewhere (the Carrack's interior map labels)."""
        self._make_ship_xml(tmp_path, "AEGS_Test_Ship", "vehicle_DescAEGS_TestShip")
        loc = {"vehicle_DescAEGS_TestShip": ""}

        result = gen_module.scan_spaceships(
            tmp_path, controller_lookup={}, loc=loc,
        )
        assert "vehicle_DescAEGS_TestShip" not in result

    def test_skips_ai_variants(self, gen_module, tmp_path):
        """AI variants are still skipped even with discovery enabled."""
        self._make_ship_xml(tmp_path, "AEGS_Test_pu_ai_Ship", "vehicle_DescAEGS_AI")

        result = gen_module.scan_spaceships(
            tmp_path, controller_lookup={}, loc={},
        )
        assert "vehicle_DescAEGS_AI" not in result


# ── Parser integration ──────────────────────────────────────────────────────

class TestDiscoveredItemsInParser:
    """Covers that discovered items get 'New' status through the parser."""

    def test_enhancement_only_key_gets_new_status(self, tmp_path):
        """A key only in the enhancements source gets status 'New',
        while a key in both base and enhancements gets 'Enhanced'."""
        from src.parser.ini_parser import load_source_files

        # base.ini has key A; enhancements have keys A and B
        base = {"item_DescSHLD_A": "Shield A"}
        enhancement = {
            "item_DescSHLD_A": "Shield A\n\\n\\n--- STATS ---\\nHP: 1000",
            "item_DescSHLD_B": "Discovered Shield\n\\n\\n--- STATS ---\\nHP: 500",
        }

        entries = load_source_files(
            sources_dict={"global": base, "enhancements": enhancement},
            hierarchy=["global", "enhancements"],
            user_overrides=None,
        )

        discovered_b = next(e for e in entries if e.key == "item_DescSHLD_B")
        assert discovered_b.status == "New"

        existing_a = next(e for e in entries if e.key == "item_DescSHLD_A")
        assert existing_a.status == "Enhanced"


# ── append_enhancements guard ────────────────────────────────────────────────

class TestAppendEnhancementsGuard:
    """Covers the None guard in ``append_enhancements``."""

    def test_none_existing_value(self, gen_module):
        """None existing_value is treated as empty string."""
        result = gen_module.append_enhancements(None, "HP: 500")
        assert "HP: 500" in result

    def test_empty_existing_value(self, gen_module):
        """Empty existing_value gets just the separator + block."""
        result = gen_module.append_enhancements("", "HP: 500")
        assert "HP: 500" in result

    def test_normal_existing_value(self, gen_module):
        """Normal existing_value gets separator + block appended."""
        result = gen_module.append_enhancements("Base text.", "HP: 500")
        assert "Base text." in result
        assert "HP: 500" in result
