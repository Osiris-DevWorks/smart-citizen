"""Unit tests for AppSettings._backfill_new_elements.

Covers the upgrade path where a saved tag config from an older version is
missing element kinds added in a newer release (e.g. ``type`` added to
components in 1.4.2, ``label`` added to commodities). The backfill appends
those elements disabled so existing output is unchanged, and also injects
default mapping entries for the new kind.
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
    DEFAULT_COMPONENT_TYPE_MAPPING,
    DEFAULT_COMMODITY_LABEL_MAPPING,
    DEFAULT_TAG_CONFIGS,
    ElementSpec,
    TagConfig,
    default_config,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def json_backend(tmp_path, monkeypatch):
    """Swap AppSettings._backend for a tmp JsonSettings so each test is hermetic."""
    saved = AppSettings._backend
    AppSettings._backend = JsonSettings(tmp_path / "config.json")
    yield AppSettings._backend
    AppSettings._backend = saved


def _save_config(backend, category: str, cfg: TagConfig) -> None:
    """Persist *cfg* under the tag_builder key so get_tag_config will load it."""
    backend.setValue(f"tag_builder/{category}/config", cfg.to_json())


class TestBackfillComponentsType:
    """A saved components config from pre-1.4.2 has [class, size, grade]
    but no ``type`` element. After backfill, ``type`` appears disabled."""

    def test_type_element_appended_disabled(self, json_backend):
        old_cfg = TagConfig(
            elements=[
                ElementSpec("class", True, "med"),
                ElementSpec("size", True, "sn"),
                ElementSpec("grade", True, "letter"),
            ],
            separator="hyphen",
            enclosing="square",
            class_mapping=dict(DEFAULT_TAG_CONFIGS["components"].class_mapping),
        )
        # Remove any type mapping entries that the full default config has
        for key in list(DEFAULT_COMPONENT_TYPE_MAPPING):
            old_cfg.class_mapping.pop(key, None)

        _save_config(json_backend, "components", old_cfg)
        loaded = AppSettings.get_tag_config("components")

        kinds = [e.kind for e in loaded.elements]
        assert "type" in kinds, "type element should be appended by backfill"

        type_spec = next(e for e in loaded.elements if e.kind == "type")
        assert type_spec.enabled is False, "backfilled type element should be disabled"
        assert type_spec.style == "short", "backfilled type element should use the default style"

    def test_type_mapping_entries_added(self, json_backend):
        old_cfg = TagConfig(
            elements=[
                ElementSpec("class", True, "med"),
                ElementSpec("size", True, "sn"),
                ElementSpec("grade", True, "letter"),
            ],
            separator="hyphen",
            enclosing="square",
            class_mapping=dict(DEFAULT_TAG_CONFIGS["components"].class_mapping),
        )
        # Strip type mapping entries
        for key in list(DEFAULT_COMPONENT_TYPE_MAPPING):
            old_cfg.class_mapping.pop(key, None)

        _save_config(json_backend, "components", old_cfg)
        loaded = AppSettings.get_tag_config("components")

        for key, val in DEFAULT_COMPONENT_TYPE_MAPPING.items():
            assert key in loaded.class_mapping, f"mapping key {key!r} should be backfilled"
            assert loaded.class_mapping[key] == val

    def test_specific_type_mappings_present(self, json_backend):
        """Shield Generator, Cooler, etc. get added to class_mapping."""
        old_cfg = TagConfig(
            elements=[
                ElementSpec("class", True, "med"),
                ElementSpec("size", True, "sn"),
                ElementSpec("grade", True, "letter"),
            ],
            separator="hyphen",
            enclosing="square",
            class_mapping=dict(DEFAULT_TAG_CONFIGS["components"].class_mapping),
        )
        for key in list(DEFAULT_COMPONENT_TYPE_MAPPING):
            old_cfg.class_mapping.pop(key, None)

        _save_config(json_backend, "components", old_cfg)
        loaded = AppSettings.get_tag_config("components")

        assert loaded.class_mapping["Shield Generator"] == ("SH", "SHLD", "Shield")
        assert loaded.class_mapping["Cooler"] == ("CL", "COOL", "Cooler")
        assert loaded.class_mapping["Power Plant"] == ("PW", "POWR", "Power")
        assert loaded.class_mapping["Quantum Drive"] == ("QD", "QDRV", "Quantum")
        assert loaded.class_mapping["Radar"] == ("RD", "RADR", "Radar")


class TestBackfillNoOp:
    """A config that already has all elements is unchanged after backfill."""

    def test_full_components_config_elements_unchanged(self, json_backend):
        full_cfg = default_config("components")
        _save_config(json_backend, "components", full_cfg)
        loaded = AppSettings.get_tag_config("components")

        original_kinds = [e.kind for e in full_cfg.elements]
        loaded_kinds = [e.kind for e in loaded.elements]
        assert loaded_kinds == original_kinds

    def test_full_components_config_mapping_unchanged(self, json_backend):
        full_cfg = default_config("components")
        _save_config(json_backend, "components", full_cfg)
        loaded = AppSettings.get_tag_config("components")

        assert loaded.class_mapping == full_cfg.class_mapping

    def test_existing_user_mapping_not_overwritten(self, json_backend):
        """User-customized mapping entries survive the backfill."""
        cfg = default_config("components")
        cfg.class_mapping["Shield Generator"] = ("X", "XSHLD", "X-Shield")
        _save_config(json_backend, "components", cfg)
        loaded = AppSettings.get_tag_config("components")

        assert loaded.class_mapping["Shield Generator"] == ("X", "XSHLD", "X-Shield")


class TestBackfillCommoditiesLabel:
    """Commodities config gets ``label`` element if missing."""

    def test_label_element_appended_when_missing(self, json_backend):
        old_cfg = TagConfig(
            elements=[],
            separator="none",
            enclosing="square",
            class_mapping={},
        )
        _save_config(json_backend, "commodities", old_cfg)
        loaded = AppSettings.get_tag_config("commodities")

        kinds = [e.kind for e in loaded.elements]
        assert "label" in kinds

    def test_label_mapping_entries_added(self, json_backend):
        old_cfg = TagConfig(
            elements=[],
            separator="none",
            enclosing="square",
            class_mapping={},
        )
        _save_config(json_backend, "commodities", old_cfg)
        loaded = AppSettings.get_tag_config("commodities")

        for key, val in DEFAULT_COMMODITY_LABEL_MAPPING.items():
            assert key in loaded.class_mapping
            assert loaded.class_mapping[key] == val


class TestBackfillCommoditiesUsageMidInsert:
    """2.1 (#166 follow-up): the commodities ``usage`` element was added
    *between* the existing ``label`` and ``collection`` kinds. A saved pre-2.1
    config has ``[label, collection]``; backfill must insert ``usage`` in the
    middle (canonical order ``label, usage, collection``), not append it at the
    end — otherwise upgraded users' tags render the usage element out of place.
    """

    def _legacy_label_collection_cfg(self) -> TagConfig:
        """A pre-2.1 commodities config: the full default minus ``usage``."""
        cfg = default_config("commodities")
        cfg.elements = [e for e in cfg.elements if e.kind != "usage"]
        return cfg

    def test_usage_inserted_between_label_and_collection(self, json_backend):
        # Sanity: the simulated legacy config really is [label, collection].
        legacy = self._legacy_label_collection_cfg()
        assert [e.kind for e in legacy.elements] == ["label", "collection"]

        _save_config(json_backend, "commodities", legacy)
        loaded = AppSettings.get_tag_config("commodities")

        kinds = [e.kind for e in loaded.elements]
        assert kinds == ["label", "usage", "collection"], (
            "usage must land between label and collection, not appended"
        )

    def test_backfilled_usage_matches_current_default(self, json_backend):
        _save_config(json_backend, "commodities", self._legacy_label_collection_cfg())
        loaded = AppSettings.get_tag_config("commodities")

        usage = next(e for e in loaded.elements if e.kind == "usage")
        assert usage.enabled is False, (
            "backfill inherits DEFAULT_TAG_CONFIGS' enabled state (#325: all "
            "three commodity elements default off, so upgraded users don't "
            "pick up a newly-added element enabled without opting in)"
        )
