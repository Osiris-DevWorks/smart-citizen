"""Tests for the calculated-reward titles a generation collects (#413).

Some contractgen mission titles resolve to zero static XP not because
extraction failed, but because their reward is genuinely not a fixed number
anywhere in the data: ContractResult_CalculatedReward is computed dynamically
in-game. _calculated_reward_titles_in tells that case apart from a title
that simply awards no reputation at all (blueprint/item-only rewards), so the
end-of-run diagnostic in _run_gen_missions can report the two separately
instead of lumping both under one "zero XP" label.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest import mock

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def gen_module():
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "generate_enhancements_ini.py"
    spec = importlib.util.spec_from_file_location(
        "generate_enhancements_ini_calc_reward_test", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_MIXED_REWARDS_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<ContractGenerator>
  <ContractGeneratorHandler_List debugName="TestHandler">
    <Contract debugName="Dynamic" notForRelease="0">
      <ContractStringParam param="Title" value="@dynamic_reward_title" />
      <ContractStringParam param="Description" value="@dynamic_reward_desc" />
      <contractResults contractBuyInAmount="0" timeToComplete="10">
        <contractResults>
          <ContractResult_CalculatedReward>
            <missionResults>
              <Bool value="1" />
            </missionResults>
          </ContractResult_CalculatedReward>
        </contractResults>
      </contractResults>
    </Contract>
    <Contract debugName="LegacyRep" notForRelease="0">
      <ContractStringParam param="Title" value="@legacy_rep_title" />
      <ContractStringParam param="Description" value="@legacy_rep_desc" />
      <contractResults contractBuyInAmount="0" timeToComplete="10">
        <contractResults>
          <ContractResult_LegacyReputation>
            <missionResults>
              <Bool value="1" />
            </missionResults>
            <contractResultReputationAmounts reward="some-uuid" />
          </ContractResult_LegacyReputation>
        </contractResults>
      </contractResults>
    </Contract>
    <Contract debugName="BlueprintOnly" notForRelease="0">
      <ContractStringParam param="Title" value="@blueprint_only_title" />
      <ContractStringParam param="Description" value="@blueprint_only_desc" />
      <contractResults contractBuyInAmount="850000" timeToComplete="10">
        <contractResults>
          <BlueprintRewards chance="1" blueprintPool="some-pool-uuid">
            <missionResults>
              <Bool value="1" />
            </missionResults>
          </BlueprintRewards>
        </contractResults>
      </contractResults>
    </Contract>
  </ContractGeneratorHandler_List>
</ContractGenerator>
"""


@pytest.fixture
def contractgen_dir(tmp_path):
    """A contractgenerator directory pre-populated with _MIXED_REWARDS_XML,
    where a generation reads it."""
    d = tmp_path / "records" / "contracts" / "contractgenerator"
    d.mkdir(parents=True)
    (d / "test_gen.xml").write_text(_MIXED_REWARDS_XML, encoding="utf-8")
    return d


def _generation_calculated_reward_titles(gen_module, contractgen_dir, xml_path_index=None):
    """The calculated-reward titles a generation collects from
    *contractgen_dir*: _run_gen_missions over the records tree it sits in,
    with the set read off its calls to _calculated_reward_titles_in. The
    generation runs that on the contractgen parse it shares with
    scan_contract_generators (perf proposal), so there is no separate scan
    to call."""
    records = contractgen_dir.parent.parent
    loc: dict[str, str] = {}
    ctx = {"records": records, "forge_dir": records.parent / "forge", "loc": loc,
           "tag_loc": loc, "entity_names": {}, "reputation_lookup": {},
           "xml_path_index": xml_path_index}
    with mock.patch.object(gen_module, "_calculated_reward_titles_in",
                           wraps=gen_module._calculated_reward_titles_in) as titles_in:
        gen_module._run_gen_missions(ctx)
    if not titles_in.call_args_list:
        return set()
    return titles_in.call_args_list[0].args[1]


class TestCalculatedRewardTitles:
    def test_calculated_reward_title_is_flagged(self, gen_module, contractgen_dir):
        titles = _generation_calculated_reward_titles(gen_module, contractgen_dir)

        assert "dynamic_reward_title" in titles

    def test_legacy_reputation_title_is_not_flagged(self, gen_module, contractgen_dir):
        titles = _generation_calculated_reward_titles(gen_module, contractgen_dir)

        assert "legacy_rep_title" not in titles

    def test_blueprint_only_title_is_not_flagged(self, gen_module, contractgen_dir):
        titles = _generation_calculated_reward_titles(gen_module, contractgen_dir)

        assert "blueprint_only_title" not in titles

    def test_exactly_one_title_flagged(self, gen_module, contractgen_dir):
        titles = _generation_calculated_reward_titles(gen_module, contractgen_dir)

        assert titles == {"dynamic_reward_title"}

    def test_missing_dir_returns_empty_set(self, gen_module, tmp_path):
        missing_dir = tmp_path / "records" / "contracts" / "contractgenerator"

        titles = _generation_calculated_reward_titles(gen_module, missing_dir)

        assert titles == set()

    def test_flags_span_multiple_files(self, gen_module, contractgen_dir):
        second_xml = _MIXED_REWARDS_XML.replace(
            "dynamic_reward_title", "second_file_dynamic_title"
        )
        (contractgen_dir / "b.xml").write_text(second_xml, encoding="utf-8")

        titles = _generation_calculated_reward_titles(gen_module, contractgen_dir)

        assert titles == {"dynamic_reward_title", "second_file_dynamic_title"}

    def test_uses_xml_path_index_when_given(self, gen_module, tmp_path):
        """Every other test above runs without an xml_path_index, so only
        exercises the contractgen_dir.rglob("*.xml") fallback branch. Real
        generation runs always have one (main() builds it), routing
        through _index_rglob instead -- this covers that branch too."""
        records_dir = tmp_path
        contractgen_dir = records_dir / "contracts" / "contractgenerator"
        contractgen_dir.mkdir(parents=True)
        xml_file = contractgen_dir / "test_gen.xml"
        xml_file.write_text(_MIXED_REWARDS_XML, encoding="utf-8")
        xml_path_index = {"contracts/contractgenerator": [str(xml_file)]}

        titles = _generation_calculated_reward_titles(
            gen_module, contractgen_dir, xml_path_index=xml_path_index
        )

        assert titles == {"dynamic_reward_title"}
