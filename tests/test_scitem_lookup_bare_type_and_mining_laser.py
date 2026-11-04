"""Regression tests for build_scitem_lookups' mission-bullet tagging of
Fuel Nozzle / Scraper Module / ship Mining Laser entities (#266 follow-up).

Before this fix, entity_name_tags (which feeds the POTENTIAL BLUEPRINTS
bullet list a player reads in-game, via build_blueprint_pool_lookup) never
got an entry for these three item types: Fuel Nozzle/Scraper Module have no
Size:/Grade:/Class: so _component_name_tag always returned None for them,
and Mining Laser lives under a "weapons" parent dir that's unconditionally
excluded (guard added for #220's combat-weapon false positives). The item's
OWN name still got tagged correctly (via enhancements_bare_type_tags /
_ship_weapon_name_tag_factory), so the tag showed up in the String Editor
and in a ship's loadout screen -- but never inside a mission's blueprint
list, which is what a player actually reads before accepting a contract.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.fixture(scope="module")
def gen_module():
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "generate_enhancements_ini.py"
    spec = importlib.util.spec_from_file_location(
        "generate_enhancements_ini_scitem_bare_type_test", script_path,
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _components_cfg(gen_module, type_enabled=True, type_style="med",
                     size_enabled=True, size_style="sn"):
    from src.utils.tag_builder import DEFAULT_TAG_CONFIGS
    comp_cfg = DEFAULT_TAG_CONFIGS["components"]
    return gen_module.TagConfig(
        elements=[
            gen_module.ElementSpec("type", type_enabled, type_style),
            gen_module.ElementSpec("size", size_enabled, size_style),
        ],
        separator=comp_cfg.separator,
        enclosing=comp_cfg.enclosing,
        placement=comp_cfg.placement,
        class_mapping=comp_cfg.class_mapping,
    )


class TestBareTypeEntityTag:
    """Fuel Nozzle / Scraper Module: no Size:/Grade:/Class:, tagged via
    the _bare_type_tag_from_desc fallback when _component_name_tag can't
    classify them."""

    def _write_fuel_nozzle(self, tmp_path: Path, ref: str) -> Path:
        subdir = tmp_path / "misc"
        subdir.mkdir(parents=True, exist_ok=True)
        (subdir / "nozzle_test.xml").write_text(
            f'<EntityClassDefinition.nozzle __ref="{ref}">'
            '<SItemComponentParams Name="@nm_nozzle" Description="@ds_nozzle"/>'
            '</EntityClassDefinition.nozzle>',
            encoding="utf-8",
        )
        return tmp_path

    def test_fuel_nozzle_gets_bullet_tag_when_type_enabled(self, gen_module, tmp_path):
        ref = "33333333-3333-3333-3333-333333333333"
        self._write_fuel_nozzle(tmp_path, ref)
        loc = {
            "nm_nozzle": "RN-7s",
            "ds_nozzle": "Manufacturer: MISC\\nItem Type: Fuel Nozzle\\nHydrogen Flow Speed: 1.65 SCU/s\\n",
        }
        _mag, _names, _by_file, entity_name_tags = gen_module.build_scitem_lookups(
            tmp_path, loc=loc, tag_config=_components_cfg(gen_module),
        )
        assert ref in entity_name_tags
        assert entity_name_tags[ref] == "[FNoz]"

    def test_fuel_nozzle_gets_no_bullet_tag_when_type_disabled(self, gen_module, tmp_path):
        ref = "44444444-4444-4444-4444-444444444444"
        self._write_fuel_nozzle(tmp_path, ref)
        loc = {
            "nm_nozzle": "RN-7s",
            "ds_nozzle": "Manufacturer: MISC\\nItem Type: Fuel Nozzle\\n",
        }
        cfg = _components_cfg(gen_module, type_enabled=False)
        _mag, _names, _by_file, entity_name_tags = gen_module.build_scitem_lookups(
            tmp_path, loc=loc, tag_config=cfg,
        )
        assert ref not in entity_name_tags


class TestMiningLaserEntityTag:
    """Ship-mounted Mining Laser: lives under a "weapons" parent dir
    (normally excluded outright) but IS a real component type with a
    real Size, so it gets a carve-out."""

    def _write_mining_laser(self, tmp_path: Path, ref: str) -> Path:
        subdir = tmp_path / "weapons"
        subdir.mkdir(parents=True, exist_ok=True)
        (subdir / "mininglaser_test.xml").write_text(
            f'<EntityClassDefinition.miningLaser __ref="{ref}">'
            '<SItemComponentParams Name="@nm_ml" Description="@ds_ml"/>'
            '<SEntityComponentMiningLaserParams/>'
            '</EntityClassDefinition.miningLaser>',
            encoding="utf-8",
        )
        return tmp_path

    def test_mining_laser_gets_bullet_type_size_tag_when_enabled(self, gen_module, tmp_path):
        ref = "55555555-5555-5555-5555-555555555555"
        self._write_mining_laser(tmp_path, ref)
        loc = {
            "nm_ml": "Helix I Mining Laser",
            "ds_ml": "Manufacturer: Thermyte Concern\\nItem Type: Mining Laser \\nSize: 1\\n",
        }
        _mag, _names, _by_file, entity_name_tags = gen_module.build_scitem_lookups(
            tmp_path, loc=loc, tag_config=_components_cfg(gen_module),
        )
        assert ref in entity_name_tags
        assert entity_name_tags[ref] == "[MineL-S1]"

    def test_mining_laser_gets_no_bullet_tag_when_type_disabled(self, gen_module, tmp_path):
        ref = "66666666-6666-6666-6666-666666666666"
        self._write_mining_laser(tmp_path, ref)
        loc = {
            "nm_ml": "Helix I Mining Laser",
            "ds_ml": "Manufacturer: Thermyte Concern\\nItem Type: Mining Laser \\nSize: 1\\n",
        }
        cfg = _components_cfg(gen_module, type_enabled=False)
        _mag, _names, _by_file, entity_name_tags = gen_module.build_scitem_lookups(
            tmp_path, loc=loc, tag_config=cfg,
        )
        assert ref not in entity_name_tags

    def test_combat_weapon_in_weapons_dir_still_excluded(self, gen_module, tmp_path):
        """Regression guard for #220: a combat weapon (no mining-laser
        marker) under weapons/ must still get no tag at all, even with
        Size:/Grade:/Class: text present in its description."""
        ref = "77777777-7777-7777-7777-777777777777"
        subdir = tmp_path / "weapons"
        subdir.mkdir(parents=True, exist_ok=True)
        (subdir / "cannon_test.xml").write_text(
            f'<EntityClassDefinition.weapon __ref="{ref}">'
            '<SItemComponentParams Name="@nm_gun" Description="@ds_gun"/>'
            '</EntityClassDefinition.weapon>',
            encoding="utf-8",
        )
        loc = {
            "nm_gun": "Test Cannon",
            "ds_gun": "Size: 2 Grade: A Class: Military",
        }
        _mag, _names, _by_file, entity_name_tags = gen_module.build_scitem_lookups(
            tmp_path, loc=loc, tag_config=_components_cfg(gen_module),
        )
        assert ref not in entity_name_tags

    def test_s_prefixed_size_line_still_yields_a_size(self, gen_module, tmp_path):
        """#345: the four Mining Head lasers write CIG's S-prefixed size
        form ("Size: S0") instead of the bare digit every other component
        uses. The tagger's size regex only accepted digits, so Helix,
        Hofstede, and Lawson rendered as a size-less "[MineL]" while their
        S1/S2 siblings got "[MineL-S1]"."""
        ref = "88888888-8888-8888-8888-888888888888"
        self._write_mining_laser(tmp_path, ref)
        loc = {
            "nm_ml": "S00 Hofstede",
            "ds_ml": "Manufacturer: Shubin Interstellar\\nItem Type: Mining Laser\\nSize: S0\\nGrade: B\\n",
        }
        _mag, _names, _by_file, entity_name_tags = gen_module.build_scitem_lookups(
            tmp_path, loc=loc, tag_config=_components_cfg(gen_module),
        )
        assert entity_name_tags[ref] == "[MineL-S0]"


class TestSizeLineRegex:
    """#345: one shared _SIZE_LINE_RE across every tagger that reads a size
    off description text. _component_name_tag already tolerated the
    S-prefixed form; the missile, mining-laser, and ship-weapon taggers each
    kept a bare-digit copy, so S-prefixed items (mining heads, bomb racks,
    scopes, the NOVA gatling) silently lost their size."""

    def test_accepts_both_cig_size_forms(self, gen_module):
        rx = gen_module._SIZE_LINE_RE
        assert rx.search("Size: 1").group(1) == "1"      # ship components
        assert rx.search("Size: S0").group(1) == "0"     # mining heads
        assert rx.search("Size: S10").group(1) == "10"   # bomb racks
        assert rx.search("Size: 0").group(1) == "0"

    def test_ignores_non_numeric_size(self, gen_module):
        """"Size: SV" (the variable-size mining heads) has no numeric size;
        it must stay unmatched rather than resolving to a bogus number."""
        assert gen_module._SIZE_LINE_RE.search("Size: SV") is None

    def test_every_desc_size_read_uses_the_shared_pattern(self):
        """Drift guard: the bug was four copies of one regex. Any new
        bare-digit `Size:` literal in the generator means a tagger has
        forked its own copy again."""
        import re as _re
        from pathlib import Path
        src = Path(__file__).resolve().parent.parent / "scripts" / "generate_enhancements_ini.py"
        text = src.read_text(encoding="utf-8")
        stray = _re.findall(r'r"Size:\\s\*\(\\d\+\)"', text)
        assert not stray, f"tagger forked its own size regex: {stray}"
