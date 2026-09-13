"""Unit tests for _titles_with_calculated_reward (#413).

Some contractgen mission titles resolve to zero static XP not because
extraction failed, but because their reward is genuinely not a fixed number
anywhere in the data: ContractResult_CalculatedReward is computed dynamically
in-game. _titles_with_calculated_reward tells that case apart from a title
that simply awards no reputation at all (blueprint/item-only rewards), so the
end-of-run diagnostic in _run_gen_missions can report the two separately
instead of lumping both under one "zero XP" label.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

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
    """A contractgenerator directory pre-populated with _MIXED_REWARDS_XML."""
    d = tmp_path / "contractgenerators"
    d.mkdir()
    (d / "test_gen.xml").write_text(_MIXED_REWARDS_XML, encoding="utf-8")
    return d


class TestTitlesWithCalculatedReward:
    def test_calculated_reward_title_is_flagged(self, gen_module, contractgen_dir):
        titles = gen_module._titles_with_calculated_reward(contractgen_dir)

        assert "dynamic_reward_title" in titles

    def test_legacy_reputation_title_is_not_flagged(self, gen_module, contractgen_dir):
        titles = gen_module._titles_with_calculated_reward(contractgen_dir)

        assert "legacy_rep_title" not in titles

    def test_blueprint_only_title_is_not_flagged(self, gen_module, contractgen_dir):
        titles = gen_module._titles_with_calculated_reward(contractgen_dir)

        assert "blueprint_only_title" not in titles

    def test_exactly_one_title_flagged(self, gen_module, contractgen_dir):
        titles = gen_module._titles_with_calculated_reward(contractgen_dir)

        assert titles == {"dynamic_reward_title"}

    def test_missing_dir_returns_empty_set(self, gen_module, tmp_path):
        missing_dir = tmp_path / "does_not_exist"

        titles = gen_module._titles_with_calculated_reward(missing_dir)

        assert titles == set()

    def test_flags_span_multiple_files(self, gen_module, contractgen_dir):
        second_xml = _MIXED_REWARDS_XML.replace(
            "dynamic_reward_title", "second_file_dynamic_title"
        )
        (contractgen_dir / "b.xml").write_text(second_xml, encoding="utf-8")

        titles = gen_module._titles_with_calculated_reward(contractgen_dir)

        assert titles == {"dynamic_reward_title", "second_file_dynamic_title"}

    def test_uses_xml_path_index_when_given(self, gen_module, tmp_path):
        """Every other test above omits xml_path_index/records_dir, so only
        exercises the contractgen_dir.rglob("*.xml") fallback branch. Real
        generation runs always pass both (see _run_gen_missions), routing
        through _index_rglob instead -- this covers that branch too."""
        records_dir = tmp_path
        contractgen_dir = records_dir / "contracts" / "contractgenerator"
        contractgen_dir.mkdir(parents=True)
        xml_file = contractgen_dir / "test_gen.xml"
        xml_file.write_text(_MIXED_REWARDS_XML, encoding="utf-8")
        xml_path_index = {"contracts/contractgenerator": [str(xml_file)]}

        titles = gen_module._titles_with_calculated_reward(
            contractgen_dir, xml_path_index=xml_path_index, records_dir=records_dir
        )

        assert titles == {"dynamic_reward_title"}
