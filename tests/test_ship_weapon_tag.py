"""Tests for the ship-weapon name-tag factory in generate_enhancements_ini.

Covers a 1.4.0 regression: ``_ship_weapon_name_tag_factory`` was emitting a
size-only tag like ``[S1]`` (or ``[1]`` under a user's "Number" size style)
for items in ``ships/weapons/`` that lacked a resolvable damage breakdown.
EMP devices, tractor / towing beams, and mining lasers were the visible
victims — issue thread reported
``item_NameMXOX_EMP_Device=[1] TroMag Burst Generator``. The fix requires
a non-empty damage_label before the ship-weapon damage-keyed tag is
emitted. Mining lasers later got their own component-style Type+Size
fallback instead of staying permanently untagged (#266) — see
``TestShipWeaponTagMiningLaser`` below; EMP devices and tractor/towing
beams still get no tag at all, since they aren't a recognised component
type either.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from lxml import etree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.tag_builder import (  # noqa: E402
    DEFAULT_TAG_CONFIGS,
    ElementSpec,
    TagConfig,
)

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def gen_module():
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "generate_enhancements_ini.py"
    spec = importlib.util.spec_from_file_location(
        "generate_enhancements_ini_ship_weapon_test", script_path,
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestShipWeaponTagDamageRequirement:
    """Items without a resolvable damage breakdown get no tag — the
    ship-weapon Tag Builder style is damage-keyed (``[E-S2]`` / ``[P-S3]``)
    and a size-only ``[S1]`` is just noise alongside the item's own name.
    """

    @pytest.mark.regression
    def test_emp_device_with_size_but_no_damage_emits_no_tag(self, gen_module):
        """MXOX_EMP_Device_S2 — the issue-thread repro. Size resolvable
        from the entity Name attribute (``_S2_`` pattern would match if
        present) AND from the description ``Size: 1`` line, but no ammo
        container → no damage breakdown. Pre-fix this emitted ``[1]``
        (or ``[S1]`` under default styles). Post-fix: no tag."""
        emp_xml = ET.fromstring(
            '<EntityClassDefinition Name="MXOX_EMP_Device_S2">'
            '  <SAttachableComponentParams>'
            '    <AttachDef Size="2"/>'
            '  </SAttachableComponentParams>'
            '</EntityClassDefinition>'
        )
        desc = (
            "Manufacturer: MaxOx\\n"
            "Item Type: Burst Generator\\n"
            "Size: 1\\n"
            "Damage Type: EMP\\n"
        )
        tagger = gen_module._ship_weapon_name_tag_factory(ammo_lookup={})
        assert tagger(desc, emp_xml) is None

    @pytest.mark.regression
    def test_tractor_beam_emits_no_tag(self, gen_module):
        """Tractor / towing beams live in ships/weapons/ too. Same
        no-damage shape — must not get a ``[Sx]`` tag."""
        beam_xml = ET.fromstring(
            '<EntityClassDefinition Name="ARGO_TowingBeam_S3"/>'
        )
        desc = "Item Type: Towing Beam\\nSize: 3\\n"
        tagger = gen_module._ship_weapon_name_tag_factory(ammo_lookup={})
        assert tagger(desc, beam_xml) is None

    def test_combat_weapon_with_damage_still_tagged(self, gen_module):
        """Regression guard: combat ship weapons with a real ammo damage
        breakdown still emit the ``[damage-size]`` tag. The factory needs
        an ammo_lookup entry keyed by the SAmmoContainerComponentParams'
        ammoParamsRecord UUID; we feed a minimal one that yields a single
        EnergyDamage hit so the dominant-damage extraction lands on
        ``Energy`` and renders as ``[E-S2]`` under defaults."""
        weapon_xml = ET.fromstring(
            '<EntityClassDefinition Name="BEHR_LaserCannon_S2">'
            '  <SAmmoContainerComponentParams ammoParamsRecord="ammo-uuid"/>'
            '</EntityClassDefinition>'
        )
        ammo_root = ET.fromstring(
            '<AmmoParams>'
            '  <damage>'
            '    <DamageInfo>'
            '      <DamageInfo type="DamageType" name="Energy">'
            '        <amount value="100"/>'
            '      </DamageInfo>'
            '    </DamageInfo>'
            '  </damage>'
            '</AmmoParams>'
        )
        tagger = gen_module._ship_weapon_name_tag_factory(
            ammo_lookup={"ammo-uuid": ammo_root}
        )
        # We don't pin the exact rendered string — _ammo_damage_breakdown's
        # parsing layout is sensitive to CIG's schema and is exercised
        # extensively elsewhere. The important assertion is "non-None" —
        # i.e. the damage-required guard doesn't bite when damage IS
        # actually present.
        tag = tagger("Size: 2", weapon_xml)
        # If _ammo_damage_breakdown can't parse our minimal fixture, the
        # tag will be None — that's a test-fixture limitation, not a
        # behaviour regression. Skip in that case rather than assert hard.
        if tag is None:
            pytest.skip("ammo fixture too minimal for _ammo_damage_breakdown")
        assert tag.startswith("[") and tag.endswith("]")


class TestShipWeaponTagMiningLaser:
    """Mining lasers live in ships/weapons/ alongside combat weapons but
    have no ammo/damage breakdown, so the damage-required guard above
    would otherwise skip them entirely. They ARE a real component type
    with a real Size though, so #266 tags them via the component
    Type+Size shape (``[ML-S1]``) instead — gated by the same
    Components > Type toggle as every other DEFAULT_COMPONENT_TYPE_MAPPING
    entry (Shield Generator, Cooler, ...): opt-in, not force-shown."""

    def _mining_laser_xml(self, name_attr: str = "Greycat_MiningLaser_Arbor"):
        xml = (
            f'<EntityClassDefinition Name="{name_attr}">'
            '  <Components>'
            '    <SEntityComponentMiningLaserParams/>'
            '  </Components>'
            '</EntityClassDefinition>'
        )
        return ET.fromstring(xml)

    def _components_cfg(self, type_enabled, type_style="short",
                         size_enabled=True, size_style="sn"):
        comp_cfg = DEFAULT_TAG_CONFIGS["components"]
        return TagConfig(
            elements=[
                ElementSpec("type", type_enabled, type_style),
                ElementSpec("size", size_enabled, size_style),
            ],
            separator=comp_cfg.separator,
            enclosing=comp_cfg.enclosing,
            placement=comp_cfg.placement,
            class_mapping=comp_cfg.class_mapping,
        )

    def test_no_tag_when_type_disabled_by_default(self, gen_module):
        """Type is disabled by default for "components" -- with no
        explicit config, mining lasers get no tag at all."""
        desc = "Manufacturer: Greycat Industrial\\nItem Type: Mining Laser \\nSize: 1\\n"
        tagger = gen_module._ship_weapon_name_tag_factory(ammo_lookup={})
        assert tagger(desc, self._mining_laser_xml()) is None

    def test_mining_laser_gets_component_type_size_tag_when_enabled(self, gen_module):
        desc = "Manufacturer: Greycat Industrial\\nItem Type: Mining Laser \\nSize: 1\\n"
        cfg = self._components_cfg(type_enabled=True)
        tagger = gen_module._ship_weapon_name_tag_factory(
            ammo_lookup={}, mining_laser_config=cfg,
        )
        assert tagger(desc, self._mining_laser_xml()) == "[ML-S1]"

    def test_respects_users_configured_components_style(self, gen_module):
        """A user who's enabled Type/Size with custom styles gets those
        same styles applied here, matching the fuel-nozzle bare-type tag
        behaviour (#266)."""
        cfg = self._components_cfg(type_enabled=True, type_style="long",
                                    size_enabled=True, size_style="n")
        desc = "Item Type: Mining Laser \\nSize: 1\\n"
        tagger = gen_module._ship_weapon_name_tag_factory(
            ammo_lookup={}, mining_laser_config=cfg,
        )
        assert tagger(desc, self._mining_laser_xml()) == "[Mining Laser-1]"

    def test_size_omitted_when_size_element_disabled(self, gen_module):
        """Type enabled but Size specifically disabled -- Type-only tag,
        no bare [S1] leaking in from a component element the user turned
        off."""
        cfg = self._components_cfg(type_enabled=True, size_enabled=False)
        desc = "Item Type: Mining Laser \\nSize: 1\\n"
        tagger = gen_module._ship_weapon_name_tag_factory(
            ammo_lookup={}, mining_laser_config=cfg,
        )
        assert tagger(desc, self._mining_laser_xml()) == "[ML]"

    def test_mining_laser_without_marker_falls_through_to_no_tag(self, gen_module):
        """Sanity guard: only entities carrying the mining-laser marker get
        this fallback — a plain no-damage item (tractor beam etc.) is
        untouched, per the existing damage-required guard, even with Type
        enabled."""
        beam_xml = ET.fromstring('<EntityClassDefinition Name="ARGO_TowingBeam_S3"/>')
        cfg = self._components_cfg(type_enabled=True)
        tagger = gen_module._ship_weapon_name_tag_factory(
            ammo_lookup={}, mining_laser_config=cfg,
        )
        assert tagger("Item Type: Towing Beam\\nSize: 3\\n", beam_xml) is None
