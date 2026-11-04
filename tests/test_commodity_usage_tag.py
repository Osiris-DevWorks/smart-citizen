"""Craft-usage commodity tag element + journal legend (2.1).

A third commodity tag element ("usage") between CF and Collection encodes the
item categories a commodity's crafting materials feed, with its own separator.
The Mining Compendium gains a legend decoding the codes when the element is on.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.tag_builder import (  # noqa: E402
    CRAFT_USAGE_CATEGORIES,
    USAGE_INPUT_SEP,
    default_config,
    render_tag,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.fixture(scope="module")
def gen_module():
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "generate_enhancements_ini.py"
    spec = importlib.util.spec_from_file_location("gen_usage_test", script_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _commodities_cfg(*, style="long", usage_sep="pipe"):
    # default_config("commodities") ships every element disabled (#325);
    # these tests exercise usage-element rendering alongside label/collection
    # (e.g. "usage sits between CF and Collection"), so enable all three
    # explicitly regardless of that default.
    cfg = default_config("commodities")
    for e in cfg.elements:
        if e.kind in ("label", "collection"):
            e.enabled = True
        if e.kind == "usage":
            e.enabled = True
            e.style = style
    cfg.usage_separator = usage_sep
    return cfg


def _usage(*names):
    return USAGE_INPUT_SEP.join(names)


class TestUsageRender:
    def test_between_cf_and_collection(self):
        cfg = _commodities_cfg(usage_sep="pipe")
        out = render_tag(cfg, {"label": "Crafting",
                               "usage": _usage("Power Plant", "Quantum Drive"),
                               "collection": "Collection"})
        assert out == "[CF|POWR|QDRV|Collection]"

    def test_own_separator_independent_of_main(self):
        cfg = _commodities_cfg(usage_sep="dot")   # main sep stays pipe
        out = render_tag(cfg, {"label": "Crafting",
                               "usage": _usage("Power Plant", "Quantum Drive")})
        assert out == "[CF|POWR.QDRV]"

    def test_short_style(self):
        cfg = _commodities_cfg(style="short", usage_sep="dot")
        out = render_tag(cfg, {"label": "Crafting", "usage": _usage("Quantum Drive", "Shield")})
        assert out == "[CF|Q.S]"

    def test_empty_usage_drops_cleanly(self):
        cfg = _commodities_cfg()
        assert render_tag(cfg, {"label": "Crafting", "usage": ""}) == "[CF]"

    def test_usage_none_separator(self):
        cfg = _commodities_cfg(usage_sep="none")
        out = render_tag(cfg, {"label": "Crafting", "usage": _usage("Quantum Drive", "Shield")})
        assert out == "[CF|QDRVSHLD]"


class TestUsageCap:
    """#208: the name tag caps how many craft-usage codes it lists so a
    many-recipe commodity can't overflow/overlap the Fabricator item name."""

    _MANY = ["Cooler", "Power Plant", "Quantum Drive",
             "Radar", "Shield", "Tractor Beam"]

    def test_caps_at_max_with_overflow_token(self, gen_module):
        cfg = _commodities_cfg(usage_sep="pipe")
        assert gen_module.USAGE_TAG_MAX_CODES == 4
        out = gen_module._commodity_tag(
            cfg, crafting=True, collection=False, usage_keys=self._MANY
        )
        # First 4 render as codes; the remaining 2 collapse to a raw "+2".
        assert out == "<EM4>[CF|COOL|POWR|QDRV|RADR|+2]</EM4>"

    def test_at_or_below_cap_is_unchanged(self, gen_module):
        cfg = _commodities_cfg(usage_sep="pipe")
        four = self._MANY[:gen_module.USAGE_TAG_MAX_CODES]
        out = gen_module._commodity_tag(
            cfg, crafting=True, collection=False, usage_keys=four
        )
        assert "+" not in out
        assert out == "<EM4>[CF|COOL|POWR|QDRV|RADR]</EM4>"

    def test_disabled_usage_element_is_ignored(self):
        cfg = default_config("commodities")
        for e in cfg.elements:
            if e.kind == "label":
                e.enabled = True
            if e.kind == "usage":
                e.enabled = False
        out = render_tag(cfg, {"label": "Crafting", "usage": _usage("Quantum Drive")})
        assert out == "[CF]"

    def test_all_elements_off_by_default(self):
        """#325: label/usage/collection all ship disabled -- users reported
        garbled/unknown text from commodity tagging in-game, so a fresh
        install now shows plain names until the user opts in per element."""
        cfg = default_config("commodities")
        assert all(not e.enabled for e in cfg.elements)
        assert render_tag(cfg, {"label": "Crafting", "usage": _usage("Quantum Drive")}) == ""


class TestUsageClassifier:
    def test_paths_map_to_valid_category_names(self, gen_module):
        names = {n for n, *_ in CRAFT_USAGE_CATEGORIES}
        cases = {
            "crafting/vehiclegear/powerplant": "Power Plant",
            "crafting/vehiclegear/quantumdrive/size3": "Quantum Drive",
            "crafting/vehiclegear/weapons/ballistic/cannon": "Ship Weapon (Ballistic)",
            "crafting/vehiclegear/weapons/laser/repeater": "Ship Weapon (Energy)",
            "crafting/vehiclegear/weapons/distortion/cannon": "Ship Weapon (Distortion)",
            "crafting/vehiclegear/refuelling/nozzle": "Refuel Nozzle",
            "crafting/fpsgear/weapons/rifle": "FPS Weapon",
            "crafting/fpsgear/ammo/laser": "Ammo",
            "crafting/fpsgear/armour/combat/heavy": "Armor",
            "crafting/missionitems": "Mission Item",
        }
        for path, expected in cases.items():
            got = gen_module._craft_usage_key(path)
            assert got == expected, path
            assert got in names  # must be a real mapping key (else raw leaks)

    def test_templates_skipped(self, gen_module):
        assert gen_module._craft_usage_key("crafting/vehiclegear/weapons/$templates/ballistic") is None


class TestJournalLegend:
    def test_legend_present_when_usage_enabled(self, gen_module):
        legend = gen_module._build_craft_usage_legend(_commodities_cfg(style="long"))
        assert "<EM3>Crafting Tag Key</EM3>" in legend
        assert "- QDRV = Quantum Drive" in legend
        assert "<EM4>Ship Components:</EM4>" in legend
        assert "<EM4>FPS Gear:</EM4>" in legend

    def test_legend_reflects_style(self, gen_module):
        assert "- Q = Quantum Drive" in gen_module._build_craft_usage_legend(_commodities_cfg(style="short"))
        assert "- QD = Quantum Drive" in gen_module._build_craft_usage_legend(_commodities_cfg(style="med"))

    def test_legend_empty_when_usage_disabled(self, gen_module):
        cfg = default_config("commodities")
        for e in cfg.elements:
            if e.kind == "usage":
                e.enabled = False
        assert gen_module._build_craft_usage_legend(cfg) == ""
