"""Regression guard for the contract mission-variant tuple shape.

Contract generators store one ``ContractVariant`` per mission variant under
``contractgen_missions[title_key]``. The 1.4.2 rep-tier-names change grew
the tuple from 10 → 11 elements (adding ``rank_name`` at position 10). The
2.2.0 reputation-track change (issue #161) grew it again, 11 → 12 (adding
``rep_track`` at position 11) so a mission's body/title can show which
reputation track (e.g. "Security" vs the generic Contractor/Standing track)
its XP feeds. ``_run_gen_missions`` reads a variant by field name since #240,
and ``scan_contract_generators`` builds it by keyword, a sub-contract's from its
contract's with ``_replace``. These tests lock the real ``ContractVariant`` and
both of those variants, so the next refactor can't slip a similar drift through.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.fixture(scope="module")
def gen_module():
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "generate_enhancements_ini.py"
    spec = importlib.util.spec_from_file_location(
        "generate_enhancements_ini_tuple_test", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# Canonical mission-variant tuple — same shape as the ``ContractVariant`` that
# ``scan_contract_generators`` appends (``missions[title_key].append(...)``).
# Keeping this aligned with ``ContractVariant`` is the entire point: when that
# shape moves, this helper must move too.
def _make_variant(
    system_name: str,
    success_xp: int,
    failure_xp: int,
    desc_key: str,
    contract_flags: list[str],
    spawns: dict,
    contract_difficulty: str | None,
    contract_has_bp: bool,
    contract_bp_chance: float,
    contract_bp_variant: str,
    rank_name: str,
    rep_track: str,
) -> tuple:
    return (
        system_name,
        success_xp,
        failure_xp,
        desc_key,
        contract_flags,
        spawns,
        contract_difficulty,
        contract_has_bp,
        contract_bp_chance,
        contract_bp_variant,
        rank_name,
        rep_track,
    )


class TestMissionVariantTupleShape:
    """``_make_variant`` holds the real ``ContractVariant``'s fields, in order."""

    def test_helper_holds_each_field_at_its_position(self, gen_module):
        """A field added to, dropped from, renamed in or moved within
        ``ContractVariant`` fails here until ``_make_variant`` and the expected
        dict below agree with it. Every value differs from the others, so a
        field that moved cannot pass."""
        values = _make_variant(
            system_name="Pyro",
            success_xp=500,
            failure_xp=-250,
            desc_key="my_desc",
            contract_flags=["Starter"],
            spawns={"hostile": {"Pirates": 4}},
            contract_difficulty="2",
            contract_has_bp=True,
            contract_bp_chance=0.25,
            contract_bp_variant="hard",
            rank_name="Rookie",
            rep_track="Security",
        )
        fields = gen_module.ContractVariant._fields
        assert len(values) == len(fields), (
            f"ContractVariant has {len(fields)} fields, _make_variant gives {len(values)}. "
            "Change both, and the keywords of the ContractVariant(...) call in "
            "scan_contract_generators."
        )
        assert gen_module.ContractVariant(*values)._asdict() == {
            "system_name": "Pyro",
            "success_xp": 500,
            "failure_xp": -250,
            "desc_key": "my_desc",
            "flags": ["Starter"],
            "spawns": {"hostile": {"Pirates": 4}},
            "difficulty": "2",
            "has_bp": True,
            "bp_chance": 0.25,
            "bp_variant": "hard",
            "rank_name": "Rookie",
            "rep_track": "Security",
        }


# One contract with two sub-contracts, the second with no description of its own.
# Each field of their variants gets a value of its own, so a value that lands in
# another field cannot pass.
_CONTRACT_GEN_XML = """\
<ContractGenerator>
  <ContractGeneratorHandler_Career debugName="Test_Handler">
    <CareerContract debugName="Pyro_Intro_Test" minStanding="standing">
      <ContractStringParam param="Title" value="@my_title" />
      <ContractStringParam param="Description" value="@my_desc" />
      <BlueprintRewards blueprintPool="pool" chance="0.25" />
      <ContractResult_LegacyReputation>
        <contractResultReputationAmounts reward="gain" />
      </ContractResult_LegacyReputation>
      <ContractResult_LegacyReputation>
        <contractResultReputationAmounts reward="loss" />
      </ContractResult_LegacyReputation>
      <ContractDifficulty mechanicalSkill="Hard_action_5" />
      <SpawnDescription_ShipGroup Name="Pirates">
        <SpawnDescription_Ship concurrentAmount="4" />
      </SpawnDescription_ShipGroup>
      <subContracts>
        <SubContract>
          <ContractStringParam param="Title" value="@sub_title" />
          <ContractStringParam param="Description" value="@sub_desc" />
        </SubContract>
        <SubContract>
          <ContractStringParam param="Title" value="@sub_no_desc_title" />
        </SubContract>
      </subContracts>
    </CareerContract>
  </ContractGeneratorHandler_Career>
</ContractGenerator>
"""


class TestScanContractGeneratorsFillsEachField:
    """``scan_contract_generators`` builds a contract's variant by keyword and a
    sub-contract's from it with ``_replace``. Two values swapped in that call raise
    nothing. A missing keyword raises a ``TypeError`` for each contract, and the
    scan then fails the run (see ``test_contract_scan.py``)."""

    def test_each_value_lands_in_its_field(self, gen_module, tmp_path):
        contractgen_dir = tmp_path / "contractgenerators"
        contractgen_dir.mkdir()
        (contractgen_dir / "contracts.xml").write_text(_CONTRACT_GEN_XML, encoding="utf-8")

        missions, _, _, _ = gen_module.scan_contract_generators(
            contractgen_dir,
            reputation_lookup={"gain": 500, "loss": -250},
            blueprint_pools={"pool": ["Some Armor"]},
            standings_lookup={"standing": "Rookie"},
            standing_track_lookup={"standing": "Security"},
        )

        shared = dict(
            system_name="Pyro",
            success_xp=500,
            failure_xp=-250,
            contract_flags=["Starter"],
            spawns={
                **gen_module._empty_spawn_breakdown(),
                gen_module.SPAWN_HOSTILE: {"Pirates": 4},
            },
            contract_difficulty="Combat 5/7",
            contract_has_bp=True,
            contract_bp_chance=0.25,
            contract_bp_variant="Pyro_Intro_Test",
            rank_name="Rookie",
            rep_track="Security",
        )
        assert missions["my_title"] == [_make_variant(desc_key="my_desc", **shared)]
        assert missions["sub_title"] == [_make_variant(desc_key="sub_desc", **shared)]
        assert missions["sub_no_desc_title"] == [_make_variant(desc_key="my_desc", **shared)]
