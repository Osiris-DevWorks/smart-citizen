"""Regression test for issue #101.

The component Type element (Shield / Cooler / Power Plant / Quantum Drive /
Radar) rendered on standalone component names but was missing from the
component entries inside mission blueprint lists. Those list tags come from
``entity_name_tags`` built in ``build_scitem_lookups``, which called
``_component_name_tag`` WITHOUT ``component_type``. The fix derives the type
from the entity's scitem subdir and passes it, so the Type element appears in
both places when enabled.
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
        "generate_enhancements_ini_type_tag_test", script_path,
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _type_enabled_config():
    from src.utils.tag_builder import (
        DEFAULT_COMPONENT_CLASS_MAPPING,
        DEFAULT_COMPONENT_TYPE_MAPPING,
        ElementSpec,
        TagConfig,
    )
    return TagConfig(
        elements=[
            ElementSpec("class", True, "med"),     # MIL
            ElementSpec("size", True, "sn"),        # S1
            ElementSpec("grade", True, "letter"),   # A
            ElementSpec("type", True, "short"),     # SH  (enabled, unlike default)
        ],
        separator="hyphen",
        enclosing="square",
        class_mapping={**DEFAULT_COMPONENT_CLASS_MAPPING, **DEFAULT_COMPONENT_TYPE_MAPPING},
    )


def _write_shield(tmp_path: Path, ref: str) -> Path:
    subdir = tmp_path / "shieldgenerator"
    subdir.mkdir(parents=True, exist_ok=True)
    (subdir / "shield_test.xml").write_text(
        f'<EntityClassDefinition.shield __ref="{ref}">'
        '<SItemComponentParams Name="@nm_shield" Description="@ds_shield"/>'
        '</EntityClassDefinition.shield>',
        encoding="utf-8",
    )
    return tmp_path


def test_blueprint_list_tag_carries_type_when_enabled(gen_module, tmp_path):
    ref = "11111111-1111-1111-1111-111111111111"
    _write_shield(tmp_path, ref)
    loc = {"nm_shield": "Test Shield", "ds_shield": "Size: 1 Grade: A Class: Military"}

    _mag, _names, _by_file, entity_name_tags = gen_module.build_scitem_lookups(
        tmp_path, loc=loc, tag_config=_type_enabled_config()
    )

    assert ref in entity_name_tags, "shield component should produce a name tag"
    tag = entity_name_tags[ref]
    # The Type element (Shield Generator -> short "SH") is only present if
    # build_scitem_lookups derived and passed component_type (the #101 fix).
    assert "SH" in tag, f"type element missing from blueprint-list tag: {tag!r}"
    # Sanity: the rest of the trio is there too.
    assert "MIL" in tag and "S1" in tag and "A" in tag


def test_no_type_when_not_in_type_subdir(gen_module, tmp_path):
    """Negative control: an identical component placed OUTSIDE a type subdir
    gets no Type element (comp_type stays ""), proving the Type token comes
    specifically from the subdir derivation added in #101 — not from the
    config or something else. The rest of the trip (MIL-S1-A) still renders."""
    ref = "22222222-2222-2222-2222-222222222222"
    subdir = tmp_path / "miscgear"  # deliberately NOT one of the 5 type subdirs
    subdir.mkdir(parents=True, exist_ok=True)
    (subdir / "thing.xml").write_text(
        f'<EntityClassDefinition.shield __ref="{ref}">'
        '<SItemComponentParams Name="@nm" Description="@ds"/>'
        '</EntityClassDefinition.shield>',
        encoding="utf-8",
    )
    loc = {"nm": "Test Thing", "ds": "Size: 1 Grade: A Class: Military"}

    _mag, _names, _by_file, entity_name_tags = gen_module.build_scitem_lookups(
        tmp_path, loc=loc, tag_config=_type_enabled_config()
    )

    assert ref in entity_name_tags
    tag = entity_name_tags[ref]
    assert "SH" not in tag, f"type element should be absent outside a type subdir: {tag!r}"
    assert "MIL" in tag and "S1" in tag and "A" in tag
