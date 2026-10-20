"""Tests for the Commodity Tagging feature (issue #97).

Commodities get a configurable tag with two conditional flags sharing one
<EM4>[...]</EM4> wrapper: Crafting (CF) and Collection. When an item is both,
they join with the separator ("[CF|Collection]"); single-flag items drop the
empty flag and stay "[CF]" / "[Collection]". Crafting-only output is unchanged
from the pre-1.5.0 single-label default.
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace as dc_replace
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.utils.json_settings import JsonSettings  # noqa: E402
from src.utils.settings import AppSettings  # noqa: E402
from src.utils.tag_builder import (  # noqa: E402
    DEFAULT_KIND_MAPPINGS,
    ElementSpec,
    default_config,
    render_tag,
)

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def gen_module():
    spec = importlib.util.spec_from_file_location(
        "generate_enhancements_ini_commodity_test",
        REPO / "scripts" / "generate_enhancements_ini.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ── render_tag with the default commodities config ───────────────────────────

def _enabled_commodities_config():
    """default_config("commodities") ships with every element disabled
    (#325) -- these tests exercise render_tag's join/drop logic, which is
    independent of that default, so they build their own enabled copy."""
    cfg = default_config("commodities")
    return dc_replace(
        cfg,
        elements=[dc_replace(e, enabled=True) for e in cfg.elements],
    )


class TestRender:
    def test_crafting_only(self):
        cfg = _enabled_commodities_config()
        assert render_tag(cfg, {"label": "Crafting"}) == "[CF]"

    def test_collection_only(self):
        cfg = _enabled_commodities_config()
        assert render_tag(cfg, {"collection": "Collection"}) == "[Collection]"

    def test_both_join_with_pipe(self):
        cfg = _enabled_commodities_config()
        assert render_tag(cfg, {"label": "Crafting", "collection": "Collection"}) == "[CF|Collection]"

    def test_collection_short_medium_long(self):
        assert DEFAULT_KIND_MAPPINGS["collection"]["Collection"] == ("Col", "Collect", "Collection")
        cfg = default_config("commodities")
        short = dc_replace(
            cfg,
            elements=[ElementSpec("label", True, "short"), ElementSpec("collection", True, "short")],
        )
        assert render_tag(short, {"label": "Crafting", "collection": "Collection"}) == "[CF|Col]"


# ── generator helper ─────────────────────────────────────────────────────────

class TestCommodityTagHelper:
    def test_flags(self, gen_module):
        cfg = _enabled_commodities_config()
        tag = gen_module._commodity_tag
        assert tag(cfg, crafting=True, collection=False) == "<EM4>[CF]</EM4>"
        assert tag(cfg, crafting=False, collection=True) == "<EM4>[Collection]</EM4>"
        assert tag(cfg, crafting=True, collection=True) == "<EM4>[CF|Collection]</EM4>"
        assert tag(cfg, crafting=False, collection=False) == ""


# ── membership matches the ground-truth fixture (drift guard) ────────────────

class TestMembership:
    def test_keys_match_fixture(self, gen_module):
        fixture = REPO / "tests" / "fixtures" / "collection_items_groundtruth.txt"
        keys = set()
        for line in fixture.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "|" not in line:
                continue
            keys.add(line.split("|")[0].strip())
        assert keys == set(gen_module.COLLECTION_ITEM_KEYS)
        assert len(gen_module.COLLECTION_ITEM_KEYS) == 57


# ── saved-config migration ───────────────────────────────────────────────────

class TestMigration:
    @pytest.fixture
    def json_backend(self, tmp_path):
        saved = AppSettings._backend
        AppSettings._backend = JsonSettings(tmp_path / "config.json")
        yield
        AppSettings._backend = saved

    def test_legacy_single_label_config_gains_collection_and_pipe(self, json_backend):
        # A pre-1.5.0 commodities config: only the label element, separator "none".
        legacy = (
            '{"elements":[{"kind":"label","enabled":true,"style":"short"}],'
            '"separator":"none","enclosing":"square","placement":"append",'
            '"class_mapping":{"Crafting":["CF","Craft","Crafting"]}}'
        )
        AppSettings.settings().setValue("tag_builder/commodities/config", legacy)

        cfg = AppSettings.get_tag_config("commodities")

        kinds = {e.kind for e in cfg.elements}
        assert "collection" in kinds, "collection element should be backfilled"
        assert cfg.separator == "pipe", "separator 'none' should upgrade to 'pipe'"
        # Backfilled disabled (#325: commodity elements default off), so a
        # both-flags item only renders the label the legacy config had
        # explicitly enabled -- collection needs an opt-in first.
        collection = next(e for e in cfg.elements if e.kind == "collection")
        assert collection.enabled is False
        assert render_tag(cfg, {"label": "Crafting", "collection": "Collection"}) == "[CF]"
