"""Recco Battaglia's Scan/Mining contracts (4.9+): the "[RS ####]" mission-title
tag, gated by the "rs" General Tags checkbox (AppSettings.MISSION_TITLE_TAG_KEYS).

Each ``Battaglia_RPT_Scan_*`` / ``Battaglia_RPT_ScanMine_*`` contract targets 1-3
mineable ores via sibling ``MissionProperty`` overrides with
``extendedTextToken="ResourceType"``/``"ResourceType2"``/``"ResourceType3"``
pointing at a ``mineabletype_primary_<ore>`` loc key. CIG doesn't expose a
per-ore RS number anywhere in DataForge (confirmed against the full PTU 4.9
cache), so ``MINEABLE_RS_VALUES`` is a curated table covering just the 8 ores
this mission family uses.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest import mock

import pytest
from lxml import etree as ET

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def gen_module():
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "generate_enhancements_ini.py"
    spec = importlib.util.spec_from_file_location(
        "generate_enhancements_ini_battaglia_rs_test", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _resource_type_property(token: str, ore: str) -> str:
    return (
        f'<MissionProperty extendedTextToken="{token}">'
        '<value><MissionPropertyValue_StringHash><options>'
        f'<MissionPropertyValueOption_StringHash textId="@mineabletype_primary_{ore}" '
        'weighting="1" DEBUG_forceChooseThisOption="0" />'
        '</options></MissionPropertyValue_StringHash></value>'
        '</MissionProperty>'
    )


def _contract(
    title_key: str,
    *ore_tokens: tuple[str, str],
    tag: str = "CareerContract",
    desc_key: str = "",
    template: str = "",
) -> str:
    props = "".join(_resource_type_property(token, ore) for token, ore in ore_tokens)
    desc_param = (
        f'<ContractStringParam param="Description" value="@{desc_key}" />' if desc_key else ""
    )
    tmpl_attr = f' template="{template}"' if template else ""
    return (
        f'<{tag} debugName="X"{tmpl_attr}>'
        '<paramOverrides><stringParamOverrides>'
        f'<ContractStringParam param="Title" value="@{title_key}" />'
        f'{desc_param}'
        '</stringParamOverrides><propertyOverrides>'
        f'{props}'
        '</propertyOverrides></paramOverrides>'
        f'</{tag}>'
    )


def _template_xml(ref: str, *, title_key: str = "", desc_key: str = "") -> str:
    """A contracttemplates XML matching _build_template_lookup's expected
    shape: root ``__ref`` plus ``LocID`` elements whose value carries
    "_title"/"_desc" in the key."""
    locs = ""
    if title_key:
        locs += f'<LocID value="@{title_key}" />'
    if desc_key:
        locs += f'<LocID value="@{desc_key}" />'
    return f'<ContractTemplate __ref="{ref}">{locs}</ContractTemplate>'


def _contractgen_dir(tmp_path: Path) -> Path:
    """A contractgenerator folder where a generation reads it,
    ``records/contracts/contractgenerator``, with its contracttemplates
    folder beside it."""
    contractgen_dir = tmp_path / "records" / "contracts" / "contractgenerator"
    contractgen_dir.mkdir(parents=True)
    return contractgen_dir


def _generation_rs_tags(gen_module, contractgen_dir: Path):
    """The ``(title_tags, desc_ores)`` a generation collects from
    *contractgen_dir*: _run_gen_missions over the records tree it sits in,
    with both dicts read off its calls to _battaglia_mineable_rs_in. The
    generation runs that on the contractgen parse it shares with
    scan_contract_generators (perf proposal), so there is no separate scan
    to call."""
    records = contractgen_dir.parent.parent
    loc: dict[str, str] = {}
    ctx = {"records": records, "forge_dir": records.parent / "forge", "loc": loc,
           "tag_loc": loc, "entity_names": {}, "reputation_lookup": {}}
    with mock.patch.object(gen_module, "_battaglia_mineable_rs_in",
                           wraps=gen_module._battaglia_mineable_rs_in) as rs_in:
        gen_module._run_gen_missions(ctx)
    if not rs_in.call_args_list:
        return {}, {}
    _root, _template_lookup, title_tags, desc_ores = rs_in.call_args_list[0].args
    return title_tags, desc_ores


class TestBattagliaContractMineableOres:
    def test_single_ore_resource_type(self, gen_module):
        root = ET.fromstring(_contract("Battaglia_RPT_Scan_01_title", ("ResourceType", "aluminium")))
        assert gen_module._battaglia_contract_mineable_ores(root) == ["aluminium"]

    def test_multi_ore_preserves_order(self, gen_module):
        root = ET.fromstring(_contract(
            "Battaglia_RPT_ScanMine_04_title",
            ("ResourceType", "bexalite"), ("ResourceType2", "ice"), ("ResourceType3", "torite"),
        ))
        assert gen_module._battaglia_contract_mineable_ores(root) == ["bexalite", "ice", "torite"]

    def test_dedups_repeated_ore(self, gen_module):
        root = ET.fromstring(_contract(
            "Battaglia_RPT_Scan_01_title",
            ("ResourceType", "iron"), ("ResourceType2", "iron"),
        ))
        assert gen_module._battaglia_contract_mineable_ores(root) == ["iron"]

    def test_ignores_unrelated_mineabletype_tokens(self, gen_module):
        """``MineableType`` (deposit form, e.g. shipasteroid) is a different
        token family from ``ResourceType`` (the ore itself) and must not be
        picked up as an ore."""
        body = (
            '<CareerContract debugName="X">'
            '<paramOverrides><stringParamOverrides>'
            '<ContractStringParam param="Title" value="@Battaglia_RPT_Scan_01_title" />'
            '</stringParamOverrides><propertyOverrides>'
            + _resource_type_property("ResourceType", "aluminium") +
            '<MissionProperty extendedTextToken="MineableType">'
            '<value><MissionPropertyValue_StringHash><options>'
            '<MissionPropertyValueOption_StringHash textId="@mineabletype_type_shipasteroid" '
            'weighting="1" DEBUG_forceChooseThisOption="0" />'
            '</options></MissionPropertyValue_StringHash></value>'
            '</MissionProperty>'
            '</propertyOverrides></paramOverrides>'
            '</CareerContract>'
        )
        root = ET.fromstring(body)
        assert gen_module._battaglia_contract_mineable_ores(root) == ["aluminium"]

    def test_no_resource_type_yields_empty(self, gen_module):
        root = ET.fromstring('<CareerContract debugName="X"></CareerContract>')
        assert gen_module._battaglia_contract_mineable_ores(root) == []


class TestFormatRsTag:
    def test_single_ore(self, gen_module):
        assert gen_module._format_rs_tag(["aluminium"]) == "[RS 4285]"

    def test_multiple_ores_slash_joined_in_order(self, gen_module):
        assert gen_module._format_rs_tag(["bexalite", "ice", "torite"]) == "[RS 3600/4300/3900]"

    def test_unknown_ore_skipped_not_erroring(self, gen_module):
        """A future ore this table doesn't cover yet is silently dropped
        rather than crashing the whole tag."""
        assert gen_module._format_rs_tag(["aluminium", "unobtainium"]) == "[RS 4285]"

    def test_all_unknown_yields_empty_string(self, gen_module):
        assert gen_module._format_rs_tag(["unobtainium"]) == ""

    def test_empty_list_yields_empty_string(self, gen_module):
        assert gen_module._format_rs_tag([]) == ""


class TestRsValueSteps:
    def test_curated_progression_ore(self, gen_module):
        assert gen_module._rs_value_steps("ice") == (4300, 8600, 12900, 17200, 21500, 25800)
        assert gen_module._rs_value_steps("savrillium") == (3200, 6400)

    def test_hand_curated_progressions_still_match(self, gen_module):
        # The seven progressions curated by hand before the steps were
        # built from ORE_SIGNATURES' caps; the derived table must keep them.
        assert gen_module._rs_value_steps("lindinium") == (3400, 6800, 10200)
        assert gen_module._rs_value_steps("bexalite") == (3600, 7200, 10800, 14400)
        assert gen_module._rs_value_steps("torite") == (3900, 7800, 11700, 15600, 19500)
        assert gen_module._rs_value_steps("iron") == (4270, 8540, 12810, 17080, 21350, 25620)
        assert gen_module._rs_value_steps("aluminium") == (
            4285, 8570, 12855, 17140, 21425, 25710)

    def test_every_rs_ore_has_a_progression(self, gen_module):
        # Every ore with a base RS gets a full progression, starting at that
        # base and ending at the largest cluster the scan decoder accepts.
        from src.utils.mining_signatures import ORE_SIGNATURES
        for ore, (base, max_count) in ORE_SIGNATURES.items():
            steps = gen_module._rs_value_steps(ore)
            assert steps[0] == gen_module.MINEABLE_RS_VALUES[ore] == base
            assert len(steps) == max_count
        assert gen_module._rs_value_steps("agricium") == (3885, 7770, 11655, 15540, 19425)

    def test_unknown_ore_yields_empty_tuple(self, gen_module):
        assert gen_module._rs_value_steps("unobtainium") == ()


class TestFormatRsDetailsLines:
    def test_single_ore_breakdown(self, gen_module):
        loc = {"mineabletype_primary_ice": "Ice"}
        lines = gen_module._format_rs_details_lines(["ice"], loc)
        assert lines == [
            "<EM4>Resource Signatures:</EM4>",
            "<EM4>Ice</EM4>: 4300 - 8600 - 12900 - 17200 - 21500 - 25800",
        ]

    def test_multi_ore_breakdown_preserves_order(self, gen_module):
        loc = {
            "mineabletype_primary_savrillium": "Savrillium",
            "mineabletype_primary_ice": "Ice",
        }
        lines = gen_module._format_rs_details_lines(["savrillium", "ice"], loc)
        assert lines == [
            "<EM4>Resource Signatures:</EM4>",
            "<EM4>Savrillium</EM4>: 3200 - 6400",
            "<EM4>Ice</EM4>: 4300 - 8600 - 12900 - 17200 - 21500 - 25800",
        ]

    def test_falls_back_to_titlecase_when_loc_key_missing(self, gen_module):
        lines = gen_module._format_rs_details_lines(["ice"], {})
        assert lines[1].startswith("<EM4>Ice</EM4>:")

    def test_unknown_ore_dropped_not_erroring(self, gen_module):
        loc = {"mineabletype_primary_ice": "Ice"}
        lines = gen_module._format_rs_details_lines(["ice", "unobtainium"], loc)
        assert lines == [
            "<EM4>Resource Signatures:</EM4>",
            "<EM4>Ice</EM4>: 4300 - 8600 - 12900 - 17200 - 21500 - 25800",
        ]

    def test_all_unknown_yields_empty_list(self, gen_module):
        assert gen_module._format_rs_details_lines(["unobtainium"], {}) == []

    def test_empty_ore_list_yields_empty_list(self, gen_module):
        assert gen_module._format_rs_details_lines([], {}) == []


class TestBuildMineableRsNameOverrides:
    """CIG's Battaglia Work Brief prose and the Primary Objectives HUD panel
    both render an ore's name via a runtime ``~mission(MineableType)`` token
    that resolves straight through ``mineabletype_primary_<ore>``, so the
    literal ore name never appears as static desc text (real generated data
    confirmed the desc string is literally
    ``"...locate ~mission(Resources) ~mission(MineableType)..."``, so a
    prior find-and-replace-the-literal-name approach could never match
    anything). Overriding the name loc key itself is what actually makes RS
    values show up in both places."""

    def test_overrides_every_ore_with_a_known_value(self, gen_module):
        loc = {
            "mineabletype_primary_aluminium": "Aluminium",
            "mineabletype_primary_ice": "Ice",
        }
        overrides = gen_module._build_mineable_rs_name_overrides(loc)
        assert overrides == {
            "mineabletype_primary_aluminium": "Aluminium (RS 4285)",
            "mineabletype_primary_ice": "Ice (RS 4300)",
        }

    def test_ore_missing_from_loc_is_skipped(self, gen_module):
        # loc doesn't have this ore's own display-name key at all (e.g. a
        # base.ini variant missing it); nothing to override, no crash.
        overrides = gen_module._build_mineable_rs_name_overrides({})
        assert overrides == {}

    def test_unrelated_loc_keys_left_out(self, gen_module):
        loc = {
            "mineabletype_primary_ice": "Ice",
            "some_other_key": "Unrelated",
        }
        overrides = gen_module._build_mineable_rs_name_overrides(loc)
        assert "some_other_key" not in overrides
        assert overrides == {"mineabletype_primary_ice": "Ice (RS 4300)"}

    def test_covers_all_curated_ores(self, gen_module):
        loc = {
            f"mineabletype_primary_{ore}": ore.title()
            for ore in gen_module.MINEABLE_RS_VALUES
        }
        overrides = gen_module._build_mineable_rs_name_overrides(loc)
        assert len(overrides) == len(gen_module.MINEABLE_RS_VALUES)
        assert overrides["mineabletype_primary_savrillium"] == "Savrillium (RS 3200)"


class TestBattagliaMineableRsTags:
    """A generation collects a ``(title_tags, desc_ores)`` pair
    (``_generation_rs_tags``). ``desc_ores`` is keyed by
    desc_key -> raw ore list (order-preserved), which is what lets the real
    generator build the mission's own DETAILS "Resource Signatures" via
    ``_format_rs_details_lines``, not just the flattened title tag."""

    def test_builds_tag_for_scan_and_scanmine_titles(self, gen_module, tmp_path):
        contractgen_dir = _contractgen_dir(tmp_path)
        (contractgen_dir / "battaglia_generator.xml").write_text(
            '<ContractGeneratorHandler_Career><contracts>'
            + _contract("Battaglia_RPT_Scan_04_title",
                        ("ResourceType", "bexalite"), ("ResourceType2", "ice"), ("ResourceType3", "torite"))
            + _contract("Battaglia_RPT_ScanMine_01_title",
                        ("ResourceType", "aluminium"), ("ResourceType2", "iron"))
            + '</contracts></ContractGeneratorHandler_Career>',
            encoding="utf-8",
        )
        title_tags, desc_ores = _generation_rs_tags(gen_module, contractgen_dir)
        assert title_tags == {
            "Battaglia_RPT_Scan_04_title": "[RS 3600/4300/3900]",
            "Battaglia_RPT_ScanMine_01_title": "[RS 4285/4270]",
        }
        assert desc_ores == {}

    def test_builds_desc_ores_alongside_title_tag(self, gen_module, tmp_path):
        contractgen_dir = _contractgen_dir(tmp_path)
        (contractgen_dir / "battaglia_generator.xml").write_text(
            '<ContractGeneratorHandler_Career><contracts>'
            + _contract("Battaglia_RPT_Scan_04_title",
                        ("ResourceType", "bexalite"), ("ResourceType2", "ice"), ("ResourceType3", "torite"),
                        desc_key="Battaglia_RPT_Scan_04_desc")
            + '</contracts></ContractGeneratorHandler_Career>',
            encoding="utf-8",
        )
        title_tags, desc_ores = _generation_rs_tags(gen_module, contractgen_dir)
        assert title_tags == {"Battaglia_RPT_Scan_04_title": "[RS 3600/4300/3900]"}
        assert desc_ores == {"Battaglia_RPT_Scan_04_desc": ["bexalite", "ice", "torite"]}

    def test_no_desc_param_yields_empty_desc_ores(self, gen_module, tmp_path):
        """A contract variant with no Description param (desc_key="") must
        not show up in desc_ores under a bogus empty-string key."""
        contractgen_dir = _contractgen_dir(tmp_path)
        (contractgen_dir / "battaglia_generator.xml").write_text(
            '<ContractGeneratorHandler_Career><contracts>'
            + _contract("Battaglia_RPT_Scan_01_title", ("ResourceType", "aluminium"))
            + '</contracts></ContractGeneratorHandler_Career>',
            encoding="utf-8",
        )
        _title_tags, desc_ores = _generation_rs_tags(gen_module, contractgen_dir)
        assert desc_ores == {}

    def test_first_variant_wins_for_desc_key_shared_across_files(self, gen_module, tmp_path):
        contractgen_dir = _contractgen_dir(tmp_path)
        (contractgen_dir / "a_stanton.xml").write_text(
            '<ContractGeneratorHandler_Career><contracts>'
            + _contract("Battaglia_RPT_Scan_06_title",
                        ("ResourceType", "lindinium"), ("ResourceType2", "savrillium"),
                        desc_key="Battaglia_RPT_Scan_06_desc")
            + '</contracts></ContractGeneratorHandler_Career>',
            encoding="utf-8",
        )
        (contractgen_dir / "b_pyro.xml").write_text(
            '<ContractGeneratorHandler_Career><contracts>'
            + _contract("Battaglia_RPT_Scan_06_title",
                        ("ResourceType", "lindinium"), ("ResourceType2", "savrillium"),
                        desc_key="Battaglia_RPT_Scan_06_desc")
            + '</contracts></ContractGeneratorHandler_Career>',
            encoding="utf-8",
        )
        _title_tags, desc_ores = _generation_rs_tags(gen_module, contractgen_dir)
        assert desc_ores == {"Battaglia_RPT_Scan_06_desc": ["lindinium", "savrillium"]}

    def test_ignores_non_battaglia_scan_titles(self, gen_module, tmp_path):
        """A mining-flavoured title from an unrelated contractor (or one of
        Battaglia's own non-scan mission types, e.g. Salvage) must not pick
        up an RS tag even if it happens to reference a mineabletype key."""
        contractgen_dir = _contractgen_dir(tmp_path)
        (contractgen_dir / "other.xml").write_text(
            '<ContractGeneratorHandler_Career><contracts>'
            + _contract("Battaglia_RPT_Salvage_E_01_title", ("ResourceType", "aluminium"))
            + _contract("Shubin_ResourceGathering_title", ("ResourceType", "iron"))
            + '</contracts></ContractGeneratorHandler_Career>',
            encoding="utf-8",
        )
        title_tags, desc_ores = _generation_rs_tags(gen_module, contractgen_dir)
        assert title_tags == {}
        assert desc_ores == {}

    def test_intro_contract_wrapper_also_covered(self, gen_module, tmp_path):
        """Battaglia wraps its intro mission in a plain <Contract> tag under
        introContracts, not <CareerContract> — must still be picked up."""
        contractgen_dir = _contractgen_dir(tmp_path)
        (contractgen_dir / "battaglia_generator.xml").write_text(
            '<ContractGeneratorHandler_Career><introContracts>'
            + _contract("Battaglia_RPT_Scan_01_title", ("ResourceType", "aluminium"), tag="Contract")
            + '</introContracts></ContractGeneratorHandler_Career>',
            encoding="utf-8",
        )
        title_tags, desc_ores = _generation_rs_tags(gen_module, contractgen_dir)
        assert title_tags == {"Battaglia_RPT_Scan_01_title": "[RS 4285]"}
        assert desc_ores == {}

    def test_first_variant_wins_when_title_shared_across_files(self, gen_module, tmp_path):
        contractgen_dir = _contractgen_dir(tmp_path)
        (contractgen_dir / "a_stanton.xml").write_text(
            '<ContractGeneratorHandler_Career><contracts>'
            + _contract("Battaglia_RPT_Scan_06_title", ("ResourceType", "lindinium"), ("ResourceType2", "savrillium"))
            + '</contracts></ContractGeneratorHandler_Career>',
            encoding="utf-8",
        )
        (contractgen_dir / "b_pyro.xml").write_text(
            '<ContractGeneratorHandler_Career><contracts>'
            + _contract("Battaglia_RPT_Scan_06_title", ("ResourceType", "lindinium"), ("ResourceType2", "savrillium"))
            + '</contracts></ContractGeneratorHandler_Career>',
            encoding="utf-8",
        )
        title_tags, desc_ores = _generation_rs_tags(gen_module, contractgen_dir)
        assert title_tags == {"Battaglia_RPT_Scan_06_title": "[RS 3400/3200]"}
        assert desc_ores == {}

    def test_missing_dir_returns_empty(self, gen_module, tmp_path):
        title_tags, desc_ores = _generation_rs_tags(
            gen_module, tmp_path / "records" / "contracts" / "contractgenerator")
        assert title_tags == {}
        assert desc_ores == {}

    def test_desc_key_resolved_via_template_when_no_inline_desc_param(self, gen_module, tmp_path):
        """Regression: some Battaglia scan/mining contracts carry no inline
        Description ContractStringParam and inherit it from a shared body
        template via the contract's "template" UUID (mirrors
        scan_contract_generators' own fallback). Missing this meant desc_ores
        stayed empty for every such contract even though its title_key
        resolved fine, silently dropping both the DETAILS "Resource
        Signatures:" block and the inline "(RS ####)" annotation."""
        contractgen_dir = _contractgen_dir(tmp_path)
        (contractgen_dir / "battaglia_generator.xml").write_text(
            '<ContractGeneratorHandler_Career><contracts>'
            + _contract("Battaglia_RPT_Scan_04_title",
                        ("ResourceType", "bexalite"), ("ResourceType2", "ice"),
                        template="tpl-uuid-1")
            + '</contracts></ContractGeneratorHandler_Career>',
            encoding="utf-8",
        )
        templates_dir = contractgen_dir.parent / "contracttemplates"
        templates_dir.mkdir()
        (templates_dir / "templates.xml").write_text(
            # _build_template_lookup only registers a template ref when it
            # resolves a title_key (see its `if title_key:` gate); the
            # template's own title_key is otherwise unused here since the
            # contract already has an inline Title param.
            _template_xml("tpl-uuid-1", title_key="Battaglia_RPT_Scan_04_tmpl_title",
                          desc_key="Battaglia_RPT_Scan_04_desc"),
            encoding="utf-8",
        )
        _title_tags, desc_ores = _generation_rs_tags(gen_module, contractgen_dir)
        assert desc_ores == {"Battaglia_RPT_Scan_04_desc": ["bexalite", "ice"]}

    def test_inline_desc_param_wins_over_template(self, gen_module, tmp_path):
        """An inline Description param, when present, is authoritative; the
        template fallback only kicks in when the contract has none."""
        contractgen_dir = _contractgen_dir(tmp_path)
        (contractgen_dir / "battaglia_generator.xml").write_text(
            '<ContractGeneratorHandler_Career><contracts>'
            + _contract("Battaglia_RPT_Scan_04_title",
                        ("ResourceType", "ice"),
                        desc_key="Battaglia_RPT_Scan_04_inline_desc",
                        template="tpl-uuid-1")
            + '</contracts></ContractGeneratorHandler_Career>',
            encoding="utf-8",
        )
        templates_dir = contractgen_dir.parent / "contracttemplates"
        templates_dir.mkdir()
        (templates_dir / "templates.xml").write_text(
            _template_xml("tpl-uuid-1", title_key="Battaglia_RPT_Scan_04_tmpl_title",
                          desc_key="Battaglia_RPT_Scan_04_template_desc"),
            encoding="utf-8",
        )
        _title_tags, desc_ores = _generation_rs_tags(gen_module, contractgen_dir)
        assert desc_ores == {"Battaglia_RPT_Scan_04_inline_desc": ["ice"]}

    def test_no_template_and_no_inline_desc_yields_empty_desc_ores(self, gen_module, tmp_path):
        contractgen_dir = _contractgen_dir(tmp_path)
        (contractgen_dir / "battaglia_generator.xml").write_text(
            '<ContractGeneratorHandler_Career><contracts>'
            + _contract("Battaglia_RPT_Scan_01_title", ("ResourceType", "aluminium"))
            + '</contracts></ContractGeneratorHandler_Career>',
            encoding="utf-8",
        )
        _title_tags, desc_ores = _generation_rs_tags(gen_module, contractgen_dir)
        assert desc_ores == {}
