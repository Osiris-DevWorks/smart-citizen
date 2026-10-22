"""The scitem pickle is tag-free; the [CLASS-Sx-grade] name tags render in memory.

``build_scitem_lookups`` used to render ``entity_name_tags`` inside its walk of
``entities/scitem`` with the user's components TagConfig, so the pickled
``scitem_lookups`` carried that config in its key and a Tag Builder change
re-parsed all 24k scitem XMLs (11 s on an NVMe machine, the whole difference
between a normal Generate and one after a components tag edit). Now
``build_scitem_facts`` walks once and keeps the tag-free facts, ``main()``
pickles those keyed on the DataForge fingerprint alone, and
``render_scitem_name_tags`` turns them into the tags on every run.
"""
from __future__ import annotations

import importlib.util
import logging
import pickle
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lxml import etree as ET  # noqa: E402

from src.utils.tag_builder import DEFAULT_TAG_CONFIGS, TagConfig  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.fixture(scope="module")
def gen_module():
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "generate_enhancements_ini.py"
    spec = importlib.util.spec_from_file_location(
        "generate_enhancements_ini_tag_free_facts_test", script_path,
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


SHIELD_REF = "11111111-1111-1111-1111-111111111111"
LASER_REF = "22222222-2222-2222-2222-222222222222"
NOZZLE_REF = "33333333-3333-3333-3333-333333333333"

SHIELD_XML = (
    f'<EntityClassDefinition.SHLD_TEST_S01 __ref="{SHIELD_REF}" Name="SHLD_TEST_S01">'
    '<SAttachableComponentParams>'
    '<AttachDef Size="1" Grade="2" SubType="ShieldGenerator"/>'
    '<Localization Name="@item_NameSHLD_TEST" Description="@item_DescSHLD_TEST"/>'
    '</SAttachableComponentParams>'
    '<ItemComponentParams itemType="ShieldGenerator"/>'
    '</EntityClassDefinition.SHLD_TEST_S01>'
)
LASER_XML = (
    f'<EntityClassDefinition.MINL_TEST __ref="{LASER_REF}" Name="MINL_TEST_S01_laser">'
    '<SEntityComponentMiningLaserParams/>'
    '<SAttachableComponentParams>'
    '<Localization Name="@item_NameMINL_TEST" Description="@item_DescMINL_TEST"/>'
    '</SAttachableComponentParams>'
    '</EntityClassDefinition.MINL_TEST>'
)
NOZZLE_XML = (
    f'<EntityClassDefinition.nozzle __ref="{NOZZLE_REF}">'
    '<SItemComponentParams Name="@item_NameNOZZLE_TEST" Description="@item_DescNOZZLE_TEST"/>'
    '</EntityClassDefinition.nozzle>'
)
LOC = {
    "item_NameSHLD_TEST": "Test Shield",
    "item_DescSHLD_TEST": "Size: 1\\nGrade: B\\nClass: Military\\nItem Type: Shield Generator",
    "item_NameMINL_TEST": "Test Laser",
    "item_DescMINL_TEST": "A mining laser.\\nSize: 1",
    "item_NameNOZZLE_TEST": "Test Nozzle",
    "item_DescNOZZLE_TEST": "Item Type: Fuel Nozzle\\nManufacturer: Test",
}


def _components_cfg(separator="hyphen", type_enabled=False):
    base = DEFAULT_TAG_CONFIGS["components"]
    elements = [
        e if e.kind != "type" else type(e)(kind="type", enabled=type_enabled, style=e.style)
        for e in base.elements
    ]
    return TagConfig(
        elements=elements, separator=separator, enclosing=base.enclosing,
        placement=base.placement, class_mapping=base.class_mapping,
    )


@pytest.fixture
def scitem_dir(tmp_path):
    (tmp_path / "shieldgenerator").mkdir()
    (tmp_path / "shieldgenerator" / "shld_test.xml").write_text(SHIELD_XML, encoding="utf-8")
    (tmp_path / "weapons").mkdir()
    (tmp_path / "weapons" / "minl_test.xml").write_text(LASER_XML, encoding="utf-8")
    (tmp_path / "misc").mkdir()
    (tmp_path / "misc" / "nozzle_test.xml").write_text(NOZZLE_XML, encoding="utf-8")
    return tmp_path


class TestFactsAndRender:
    def test_facts_do_not_depend_on_a_tag_config_and_render_to_the_old_tags(
        self, gen_module, scitem_dir
    ):
        facts = gen_module.build_scitem_facts(scitem_dir, LOC)
        mag, names, by_file, tag_facts = facts
        assert names[SHIELD_REF] == "Test Shield"
        assert by_file["shld_test"] == "Test Shield"
        assert set(tag_facts) == {SHIELD_REF, LASER_REF, NOZZLE_REF}
        for cfg in (_components_cfg(), _components_cfg("pipe", type_enabled=True)):
            via_wrapper = gen_module.build_scitem_lookups(scitem_dir, LOC, tag_config=cfg)
            assert via_wrapper[:3] == facts[:3]
            assert via_wrapper[3] == gen_module.render_scitem_name_tags(tag_facts, LOC, cfg)

    def test_rendered_tags_follow_the_config_without_a_rewalk(self, gen_module, scitem_dir):
        _mag, _names, _by_file, tag_facts = gen_module.build_scitem_facts(scitem_dir, LOC)
        hyphen = gen_module.render_scitem_name_tags(tag_facts, LOC, _components_cfg())
        pipe = gen_module.render_scitem_name_tags(tag_facts, LOC, _components_cfg("pipe"))
        assert hyphen[SHIELD_REF] == "[MIL-S1-B]"
        assert pipe[SHIELD_REF] == "[MIL|S1|B]"
        # Type off (the default): no mining-laser or fuel-nozzle tag.
        assert LASER_REF not in hyphen and NOZZLE_REF not in hyphen
        typed = gen_module.render_scitem_name_tags(
            tag_facts, LOC, _components_cfg(type_enabled=True)
        )
        assert typed[LASER_REF].startswith("[") and "S1" in typed[LASER_REF]
        assert NOZZLE_REF in typed

    def test_a_missing_description_renders_no_tag(self, gen_module, scitem_dir):
        _mag, _names, _by_file, tag_facts = gen_module.build_scitem_facts(scitem_dir, LOC)
        loc = {k: v for k, v in LOC.items() if k != "item_DescSHLD_TEST"}
        rendered = gen_module.render_scitem_name_tags(tag_facts, loc, _components_cfg())
        assert SHIELD_REF not in rendered

    def test_facts_are_plain_builtins_that_survive_a_pickle(self, gen_module, scitem_dir):
        """The generator is loaded under several module names; a pickled
        class instance would not unpickle across them."""
        facts = gen_module.build_scitem_facts(scitem_dir, LOC)
        assert pickle.loads(pickle.dumps(facts)) == facts

        def walk(value):
            assert type(value) in (dict, tuple, list, str, bool, int, type(None)), type(value)
            if isinstance(value, dict):
                for k, v in value.items():
                    walk(k)
                    walk(v)
            elif isinstance(value, (tuple, list)):
                for v in value:
                    walk(v)

        walk(facts)


class TestInputsStandInForTheRoot:
    @pytest.mark.parametrize("desc", [
        LOC["item_DescSHLD_TEST"],
        "Grade: B\\nClass: Military",            # size from the XML
        "Class: Military",                        # size and grade from the XML
        "Item Type: Shield Generator",            # the fallback path
        "",
    ])
    def test_component_tag_is_the_same_from_inputs(self, gen_module, desc):
        root = ET.fromstring(SHIELD_XML.encode())
        inputs = gen_module._tag_inputs_from_root(root)
        for cfg in (_components_cfg(), _components_cfg("pipe", type_enabled=True)):
            assert gen_module._component_name_tag(
                desc, root, config=cfg, component_type="Shield Generator"
            ) == gen_module._component_name_tag(
                desc, config=cfg, component_type="Shield Generator", inputs=inputs
            )

    def test_component_tag_without_root_or_inputs_is_unchanged(self, gen_module):
        assert gen_module._component_name_tag(LOC["item_DescSHLD_TEST"]) == "[MIL-S1-B]"
        assert gen_module._component_name_tag("Class: Military") is None

    def test_mining_laser_tag_is_the_same_from_inputs(self, gen_module):
        root = ET.fromstring(LASER_XML.encode())
        inputs = gen_module._tag_inputs_from_root(root)
        cfg = gen_module._build_mining_laser_tag_cfg(_components_cfg(type_enabled=True))
        assert cfg is not None
        from_root = gen_module._mining_laser_component_tag(LOC["item_DescMINL_TEST"], root, cfg)
        from_inputs = gen_module._mining_laser_component_tag(
            LOC["item_DescMINL_TEST"], None, cfg, inputs=inputs
        )
        assert from_root == from_inputs and from_root is not None
        # Without inputs, a root that is not a mining laser still gives nothing.
        shield = ET.fromstring(SHIELD_XML.encode())
        assert gen_module._mining_laser_component_tag("Size: 1", shield, cfg) is None

    def test_inputs_are_seven_strings(self, gen_module):
        inputs = gen_module._tag_inputs_from_root(ET.fromstring(SHIELD_XML.encode()))
        assert len(inputs) == 7 and all(isinstance(v, str) for v in inputs)
        assert inputs[0] == "SHLD_TEST_S01" and inputs[1] == "item_NameSHLD_TEST"
        assert inputs[2:6] == ("1", "2", "ShieldGenerator", "ShieldGenerator")
        assert inputs[6] == "SHLD_TEST_S01"


class TestMainPicklesWithoutTheTagConfig:
    @pytest.fixture
    def forge_layout(self, tmp_path):
        repo_root = Path(__file__).resolve().parent.parent
        base_ini = tmp_path / "base.ini"
        shutil.copy(repo_root / "tests" / "fixtures" / "kraken_global_latest.ini", base_ini)
        # The facts keep only entities whose description resolves in the
        # English base.ini, so the fixture's loc keys are appended to it.
        with base_ini.open("a", encoding="utf-8") as f:
            f.write("".join(f"{k}={v}\n" for k, v in LOC.items()))
        forge_dir = tmp_path / "forge"
        records = forge_dir / "raw" / "libs" / "foundry" / "records"
        (records / "entities" / "scitem" / "shieldgenerator").mkdir(parents=True)
        (records / "entities" / "scitem" / "shieldgenerator" / "shld_test.xml").write_text(
            SHIELD_XML, encoding="utf-8"
        )
        (forge_dir / ".p4k_mtime").write_text("1234567890.0", encoding="utf-8")
        return base_ini, forge_dir

    def test_a_tag_change_is_a_cache_hit(self, gen_module, forge_layout, caplog):
        base_ini, forge_dir = forge_layout
        pipe_cfgs = {**DEFAULT_TAG_CONFIGS, "components": _components_cfg("pipe")}
        with caplog.at_level(logging.INFO):
            gen_module.main(base_ini, forge_dir, categories=None, max_workers=1)
            caplog.clear()
            gen_module.main(base_ini, forge_dir, categories=None, max_workers=1,
                            tag_configs=pipe_cfgs)
        assert "Lookup cache hit: scitem_lookups" in caplog.text
        assert "Lookup cache invalidated: scitem_lookups" not in caplog.text
        with (forge_dir / ".lookups" / "scitem_lookups.pkl").open("rb") as f:
            key, value = pickle.load(f)
        assert key == f"{gen_module._LOOKUP_VERSIONS['scitem_lookups']}:1234567890.0"
        assert "{" not in key                      # no TagConfig JSON in the key
        _mag, _names, _by_file, tag_facts = value
        assert SHIELD_REF in tag_facts
        assert all(not isinstance(v, str) for v in tag_facts.values())

    def test_the_pinned_version_has_moved_past_the_rendered_tag_pickles(self, gen_module):
        version = int(gen_module._LOOKUP_VERSIONS["scitem_lookups"].lstrip("v"))
        assert version >= 11
