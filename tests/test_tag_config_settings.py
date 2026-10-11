"""AppSettings persistence tests for the dynamic tag builder.

Uses the JsonSettings backend (same shim portable-mode builds use) so we
exercise the slash-key path tested by ``test_json_settings.py``. The key
layout is ``tag_builder/{category}/config`` with the entire TagConfig
serialized as a single JSON string per category — keeps the keyspace
flat enough to round-trip cleanly through both backends.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from src.utils.json_settings import JsonSettings  # noqa: E402
from src.utils.settings import AppSettings  # noqa: E402
from src.utils.tag_builder import (  # noqa: E402
    TagConfig,
    default_config,
    render_tag,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def json_backend(tmp_path, monkeypatch):
    """Swap AppSettings._backend for a tmp JsonSettings so each test is hermetic."""
    saved = AppSettings._backend
    AppSettings._backend = JsonSettings(tmp_path / "config.json")
    yield AppSettings._backend
    AppSettings._backend = saved


class TestDefaults:
    def test_absent_returns_default_for_each_category(self, json_backend):
        for cat in ("components", "missiles", "ship_weapons"):
            cfg = AppSettings.get_tag_config(cat)
            # to_json is deterministic via sort_keys=True so equality on the
            # serialized form is a tight check.
            assert cfg.to_json() == default_config(cat).to_json()

    def test_default_components_still_produces_old_tag(self, json_backend):
        cfg = AppSettings.get_tag_config("components")
        assert render_tag(cfg, {"class": "Military", "size": "2", "grade": "A"}) == "[MIL-S2-A]"


class TestRoundtrip:
    def test_set_then_get_components(self, json_backend):
        cfg = default_config("components")
        cfg.separator = "underscore"
        cfg.enclosing = "round"
        for el in cfg.elements:
            if el.kind == "class":
                el.style = "short"
        AppSettings.set_tag_config("components", cfg)
        revived = AppSettings.get_tag_config("components")
        assert revived.to_json() == cfg.to_json()
        assert render_tag(revived, {"class": "Military", "size": "2", "grade": "A"}) == "(M_S2_A)"

    def test_user_mapping_edit_persists(self, json_backend):
        cfg = default_config("components")
        cfg.class_mapping["Military"] = ("X", "XMIL", "X-Military")
        AppSettings.set_tag_config("components", cfg)
        revived = AppSettings.get_tag_config("components")
        assert revived.class_mapping["Military"] == ("X", "XMIL", "X-Military")


class TestCorruption:
    def test_invalid_json_falls_back_to_default(self, json_backend):
        json_backend.setValue("tag_builder/components/config", "{this is not json")
        cfg = AppSettings.get_tag_config("components")
        # No exception, falls through to defaults.
        assert cfg.to_json() == default_config("components").to_json()

    def test_empty_string_falls_back_to_default(self, json_backend):
        json_backend.setValue("tag_builder/components/config", "")
        cfg = AppSettings.get_tag_config("components")
        assert cfg.to_json() == default_config("components").to_json()


class TestGetAll:
    def test_get_all_returns_one_config_per_category(self, json_backend):
        all_cfgs = AppSettings.get_all_tag_configs()
        assert set(all_cfgs.keys()) == {
            "components", "missiles", "ship_weapons", "commodities", "mission_titles"}
        assert all(isinstance(v, TagConfig) for v in all_cfgs.values())


class TestShipWeaponMappingMigration:
    """Old ship-weapon configs stored damage entries under the compact
    generator labels ("Phys", "Distort", "Bio"). Loading should rewrite
    those into the user-friendly full names without losing the user's
    custom variant text."""

    def _save_legacy_blob(self, backend, mapping):
        import json
        blob = json.dumps({
            "elements": [
                {"kind": "damage", "enabled": True, "style": "short"},
                {"kind": "size",   "enabled": True, "style": "sn"},
            ],
            "separator": "hyphen",
            "enclosing": "square",
            "placement": "prepend",
            "class_mapping": {k: list(v) for k, v in mapping.items()},
        })
        backend.setValue("tag_builder/ship_weapons/config", blob)

    def test_old_short_keys_get_renamed(self, json_backend):
        self._save_legacy_blob(json_backend, {
            "Energy":  ("E", "EN", "Energy"),
            "Phys":    ("X", "XPHY", "Custom-Physical"),
            "Distort": ("Y", "YDIS", "Custom-Distortion"),
            "Bio":     ("Z", "ZBIO", "Custom-Bio"),
        })
        cfg = AppSettings.get_tag_config("ship_weapons")
        keys = set(cfg.class_mapping.keys())
        assert "Phys" not in keys and "Physical" in keys
        assert "Distort" not in keys and "Distortion" in keys
        assert "Bio" not in keys and "Biochemical" in keys
        # User edits survive the rename.
        assert cfg.class_mapping["Physical"] == ("X", "XPHY", "Custom-Physical")

    def test_orphan_old_key_drops_when_new_key_already_present(self, json_backend):
        # Both forms in the same save (an artifact of a brief earlier shape).
        self._save_legacy_blob(json_backend, {
            "Energy":      ("E", "EN", "Energy"),
            "Phys":        ("P", "PHY", "Physical"),
            "Physical":    ("X", "XPHY", "Custom-Physical"),
        })
        cfg = AppSettings.get_tag_config("ship_weapons")
        # Drop the orphan "Phys"; keep the user-friendly "Physical" row.
        assert "Phys" not in cfg.class_mapping
        assert cfg.class_mapping["Physical"] == ("X", "XPHY", "Custom-Physical")


class TestCommoditySeparatorNone:
    """#97 follow-up: 'None' is a real, persistent separator choice for
    commodities, but a legacy leftover 'none' is upgraded once to 'pipe' so
    existing users don't regress to a mashed '[CFCollection]'."""

    _MARKER = "tag_builder/commodities/sep_migrated"

    def _commodity_cfg(self, separator: str) -> TagConfig:
        cfg = default_config("commodities")
        cfg.separator = separator
        return cfg

    def test_legacy_none_upgraded_to_pipe_once(self, json_backend):
        # Stored 'none' with no migration marker -> upgraded to pipe on read,
        # the upgrade is persisted, and the marker is set.
        AppSettings.set_tag_config("commodities", self._commodity_cfg("none"))
        cfg = AppSettings.get_tag_config("commodities")
        assert cfg.separator == "pipe"
        assert json_backend.value(self._MARKER, False, type=bool) is True
        # Persisted, so a second read stays pipe.
        assert AppSettings.get_tag_config("commodities").separator == "pipe"

    def test_deliberate_none_persists_after_migration(self, json_backend):
        # After the one-time upgrade has run, a fresh 'none' choice sticks.
        json_backend.setValue(self._MARKER, True)
        cfg = self._commodity_cfg("none")
        # default_config("commodities") ships every element disabled (#325);
        # enable label + collection explicitly to exercise the mashed-output
        # render this test is actually about.
        for el in cfg.elements:
            if el.kind in ("label", "collection"):
                el.enabled = True
        AppSettings.set_tag_config("commodities", cfg)
        cfg = AppSettings.get_tag_config("commodities")
        assert cfg.separator == "none"
        assert render_tag(cfg, {"label": "CF", "collection": "Collection"}) == "[CFCollection]"

    def test_pipe_config_untouched_and_marks_migrated(self, json_backend):
        AppSettings.set_tag_config("commodities", self._commodity_cfg("pipe"))
        cfg = AppSettings.get_tag_config("commodities")
        assert cfg.separator == "pipe"
        # The one-time pass runs (marker set) even when nothing needed upgrading,
        # so a later 'none' choice is honored.
        assert json_backend.value(self._MARKER, False, type=bool) is True
        AppSettings.set_tag_config("commodities", self._commodity_cfg("none"))
        assert AppSettings.get_tag_config("commodities").separator == "none"
