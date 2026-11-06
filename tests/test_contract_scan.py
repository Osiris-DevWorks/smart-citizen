"""``scan_contract_generators``: what it does with data and code that go wrong.

A contract that raises is skipped, leaves nothing behind and the rest of the scan goes
on, with one WARNING naming it. The line used to be at DEBUG, which the app does not
show in a normal run, so one wrong ``ContractVariant(...)`` call emptied every contract's
variants while the generation still finished as a success with nothing in the log. Now
a scan that skips more contracts than it builds fails the run, and the worker words the
failure in the selected language. Game data should not be able to do that, so a spawn
count that is not a whole number no longer raises.

Every field of a contract's and a sub-contract's variant is checked in
``test_mission_variant_tuple.py``.
"""
from __future__ import annotations

import collections
import importlib.util
import json
import logging
import string
import sys
from pathlib import Path

import pytest
from PyQt6.QtCore import Qt

from src.gui.workers import EnhancementsGeneratorWorker
from src.utils import i18n
from src.utils.pak_extractor import DATAFORGE_RECORDS_SUBPATH
from src.utils.settings import AppSettings

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "generate_enhancements_ini.py"
_LANGUAGES = Path(__file__).resolve().parent.parent / "languages"
_UI_FILES = sorted(_LANGUAGES.glob("*/ui.json"))
_KEY_FIELDS = {
    "contract_scan_failed": {"skipped", "total", "first"},
    "contract_scan_stopped": {"first"},
}
# The name EnhancementsGeneratorWorker.run loads the generator script under.
_WORKER_MODULE = "generate_enhancements_ini_worker"


@pytest.fixture(scope="module")
def gen_module():
    spec = importlib.util.spec_from_file_location(
        "generate_enhancements_ini_contract_scan_test", _SCRIPT
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _scan_all(gen_module, tmp_path, *xmls, **lookups):
    contractgen_dir = tmp_path / "contractgenerators"
    contractgen_dir.mkdir()
    for number, xml in enumerate(xmls):
        (contractgen_dir / f"contracts_{number}.xml").write_text(xml, encoding="utf-8")
    return gen_module.scan_contract_generators(contractgen_dir, **lookups)


def _scan(gen_module, tmp_path, *xmls):
    return _scan_all(gen_module, tmp_path, *xmls)[0]


def _warnings_and_up(caplog):
    return [(r.levelname, r.getMessage()) for r in caplog.records
            if r.levelno >= logging.WARNING]


def _generator(*contracts, handler_inside=""):
    return (
        '<ContractGenerator>\n  <ContractGeneratorHandler_Career debugName="Test_Handler">\n'
        + handler_inside
        + "".join(contracts)
        + "  </ContractGeneratorHandler_Career>\n</ContractGenerator>\n"
    )


def _contract(name, inside="", title=None):
    return f"""\
    <CareerContract debugName="{name}">
      <ContractStringParam param="Title" value="@{title or name}_title" />
      <ContractStringParam param="Description" value="@{name}_desc" />
      {inside}
    </CareerContract>
"""


_REWARDS = """<BlueprintRewards blueprintPool="pool" chance="0.25" />
      <ContractResult_Item entityClass="item" />"""


def _raises_for(gen_module, monkeypatch, *names):
    """Contracts with these debug names raise ``ValueError("odd")`` at the difficulty
    step, after their rewards are read and before their variant is built."""
    real = gen_module._extract_difficulty

    def difficulty(element):
        if element.get("debugName") in names:
            raise ValueError("odd")
        return real(element)

    monkeypatch.setattr(gen_module, "_extract_difficulty", difficulty)


def _wider_variant(gen_module):
    """A ``ContractVariant`` with a field the real call does not pass."""
    return collections.namedtuple(
        "ContractVariant", gen_module.ContractVariant._fields + ("extra",)
    )


class TestASkippedContract:
    def test_it_gets_one_warning_and_the_others_are_kept(
        self, gen_module, tmp_path, caplog, monkeypatch
    ):
        _raises_for(gen_module, monkeypatch, "odd")
        xml = _generator(_contract("first"), _contract("odd"), _contract("last"))
        with caplog.at_level(logging.WARNING):
            missions = _scan(gen_module, tmp_path, xml)

        assert sorted(missions) == ["first_title", "last_title"]
        assert _warnings_and_up(caplog) == [
            ("WARNING", "Skipped contract odd: ValueError: odd"),
        ]

    @pytest.mark.parametrize("raises", [False, True], ids=["control", "raises"])
    def test_it_leaves_no_blueprints_or_items_behind(
        self, gen_module, tmp_path, monkeypatch, raises
    ):
        """The control is the same contract, whose rewards are recorded."""
        if raises:
            _raises_for(gen_module, monkeypatch, "rewards")
        _, blueprints, chance, items = _scan_all(
            gen_module, tmp_path,
            _generator(_contract("good"), _contract("rewards", _REWARDS)),
            blueprint_pools={"pool": ["Some Armor"]},
            entity_names={"item": "Some Item"},
        )
        assert ("rewards_title" in blueprints) is not raises
        assert chance == ({} if raises else {"rewards_title": 0.25})
        assert items == ({} if raises else {"rewards_title": ["Some Item"]})

    def test_a_failed_call_leaves_no_title_with_no_variants(
        self, gen_module, tmp_path, monkeypatch
    ):
        """Such a title read as every variant having a blueprint (``all([])`` is True)."""
        real = gen_module.ContractVariant

        def fails_for_one(**fields):
            if fields["bp_variant"] == "odd":
                raise TypeError("a wrong call")
            return real(**fields)

        monkeypatch.setattr(gen_module, "ContractVariant", fails_for_one)
        xml = _generator(_contract("first"), _contract("odd"), _contract("last"))
        assert sorted(_scan(gen_module, tmp_path, xml)) == ["first_title", "last_title"]

    def test_a_titles_chance_stays_its_first_pools(self, gen_module, tmp_path):
        """The chance is kept back until the variant is built, and still the first one."""
        pools = (
            '<BlueprintRewards blueprintPool="pool" chance="0.25" />'
            '<BlueprintRewards blueprintPool="pool" chance="0.5" />'
        )
        _, _, chance, _ = _scan_all(
            gen_module, tmp_path, _generator(_contract("a", pools, title="shared")),
            blueprint_pools={"pool": ["Some Armor"]},
        )
        assert chance == {"shared_title": 0.25}

    def test_one_that_reads_fine_logs_nothing(self, gen_module, tmp_path, caplog):
        with caplog.at_level(logging.WARNING):
            missions = _scan(gen_module, tmp_path, _generator(_contract("fine")))

        assert list(missions) == ["fine_title"]
        assert _warnings_and_up(caplog) == []


_SHIPS = """<SpawnDescription_ShipGroup Name="Pirates">
        <SpawnDescription_Ship concurrentAmount="{first}" />
        <SpawnDescription_Ship concurrentAmount="2" />
      </SpawnDescription_ShipGroup>"""

_NPCS = """<SpawnDescription_NPC_Group Name="Guards">
        <autoSpawnSettings maxSpawns="{spawns}" maxConcurrentSpawns="{concurrent}" />
        <autoSpawnSettings maxSpawns="3" />
      </SpawnDescription_NPC_Group>"""


class TestASpawnCountThatIsNotAWholeNumber:
    """Over half of LIVE's contracts read a count, so one change to how counts are written
    must not lose them and fail every generation."""

    @pytest.mark.parametrize("inside, attribute, value", [
        (_SHIPS.format(first="4.5"), "Pirates concurrentAmount", "4.5"),
        (_SHIPS.format(first="inf"), "Pirates concurrentAmount", "inf"),
        (_SHIPS.format(first="nan"), "Pirates concurrentAmount", "nan"),
        (_NPCS.format(spawns="lots", concurrent="1"), "Guards maxSpawns", "lots"),
        (_NPCS.format(spawns="-1", concurrent="lots"), "Guards maxConcurrentSpawns", "lots"),
    ], ids=["ship", "ship_inf", "ship_nan", "npc", "npc_concurrent"])
    def test_it_counts_as_nothing_and_the_contract_stays(
        self, gen_module, tmp_path, caplog, inside, attribute, value
    ):
        with caplog.at_level(logging.WARNING):
            missions = _scan(gen_module, tmp_path, _generator(_contract("odd", inside)))

        counts = {label: count for bucket in missions["odd_title"][0].spawns.values()
                  for label, count in bucket.items()}
        assert list(counts.values()) == [2 if "Pirates" in attribute else 3]
        assert _warnings_and_up(caplog) == [(
            "WARNING",
            f"Spawn count is not a whole number, counted as 0: {attribute}={value!r}",
        )]

    def test_a_whole_number_written_with_a_point_is_read(self, gen_module, tmp_path, caplog):
        with caplog.at_level(logging.WARNING):
            missions = _scan(gen_module, tmp_path, _generator(
                _contract("odd", _SHIPS.format(first="4.0"))))

        counts = {label: count for bucket in missions["odd_title"][0].spawns.values()
                  for label, count in bucket.items()}
        assert list(counts.values()) == [6]
        assert _warnings_and_up(caplog) == []

    def test_every_contract_with_one_does_not_fail_the_run(self, gen_module, tmp_path):
        inside = _SHIPS.format(first="4.5")
        missions = _scan(gen_module, tmp_path, _generator(
            _contract("a", inside), _contract("b", inside), _contract("c", inside)))
        assert sorted(missions) == ["a_title", "b_title", "c_title"]

    def test_one_in_a_handlers_own_spawns_is_the_same(self, gen_module, tmp_path, caplog):
        with caplog.at_level(logging.WARNING):
            missions = _scan(gen_module, tmp_path, _generator(
                _contract("kept"), handler_inside=_SHIPS.format(first="4.5")))

        assert list(missions) == ["kept_title"]
        assert [level for level, _ in _warnings_and_up(caplog)] == ["WARNING"]


class TestAFailureInAHandlersOwnSpawns:
    def test_it_ends_nothing(self, gen_module, tmp_path, caplog, monkeypatch):
        """Its contracts stay, with their own spawns or none, the file after it is read,
        and the variants are still sorted with Stanton first."""
        real = gen_module._extract_spawn_counts

        def spawn_counts(element, exclude_within=None):
            if exclude_within:
                raise ValueError("odd")
            return real(element)

        monkeypatch.setattr(gen_module, "_extract_spawn_counts", spawn_counts)
        first_file = _generator(
            _contract("Pyro_x", title="shared"), _contract("Stanton_x", title="shared"))
        with caplog.at_level(logging.WARNING):
            missions = _scan(gen_module, tmp_path, first_file, _generator(_contract("later")))

        assert sorted(missions) == ["later_title", "shared_title"]
        assert [v.system_name for v in missions["shared_title"]] == ["Stanton", "Pyro"]
        assert missions["shared_title"][0].spawns == gen_module._empty_spawn_breakdown()
        assert _warnings_and_up(caplog) == [
            ("WARNING", "Skipped the shared spawns of handler Test_Handler: ValueError: odd"),
        ] * 2


_SCENARIO_REWARD = """<ContractResult_ScenarioProgress PointsToAward="{points}">
        <missionResults><Bool value="1" /></missionResults>
      </ContractResult_ScenarioProgress>"""


def test_points_that_are_infinite_skip_only_that_reward(gen_module, tmp_path, caplog):
    inside = _SCENARIO_REWARD.format(points="inf") + _SCENARIO_REWARD.format(points="500")
    with caplog.at_level(logging.WARNING):
        missions = _scan(gen_module, tmp_path, _generator(_contract("odd", inside)))

    assert missions["odd_title"][0].success_xp == 500
    assert _warnings_and_up(caplog) == []


class TestMostContractsSkipped:
    def test_a_wrong_contractvariant_call_fails_the_scan(
        self, gen_module, tmp_path, caplog, monkeypatch
    ):
        """It raises for every contract. Each gets a line naming the error, none at ERROR
        here (the worker's failure path opens the error box), and the failure holds the
        counts and the first."""
        monkeypatch.setattr(gen_module, "ContractVariant", _wider_variant(gen_module))
        with caplog.at_level(logging.WARNING), pytest.raises(
            gen_module.ContractScanFailed
        ) as failure:
            _scan(gen_module, tmp_path, _generator(_contract("a"), _contract("b")))

        assert (failure.value.skipped, failure.value.total) == (2, 2)
        assert failure.value.first.startswith("a: TypeError: ")
        assert "'extra'" in failure.value.first
        assert str(failure.value).startswith("2 of 2 contracts could not be read. The first: a: ")
        logged = _warnings_and_up(caplog)
        assert [level for level, _ in logged] == ["WARNING", "WARNING"]
        for (_, message), name in zip(logged, ("a", "b")):
            assert message.startswith(f"Skipped contract {name}: TypeError: ")

    def test_more_skipped_than_built_fails(self, gen_module, tmp_path, monkeypatch):
        _raises_for(gen_module, monkeypatch, "bad1", "bad2")
        with pytest.raises(gen_module.ContractScanFailed) as failure:
            _scan(gen_module, tmp_path, _generator(
                _contract("good"), _contract("bad1"), _contract("bad2")))
        assert (failure.value.skipped, failure.value.total) == (2, 3)

    def test_half_does_not_fail(self, gen_module, tmp_path, monkeypatch):
        _raises_for(gen_module, monkeypatch, "bad")
        xml = _generator(_contract("good"), _contract("bad"))
        assert list(_scan(gen_module, tmp_path, xml)) == ["good_title"]

    def test_no_contracts_at_all_is_not_a_failure(self, gen_module, tmp_path):
        assert _scan(gen_module, tmp_path, _generator()) == {}

    def _roots(self, gen_module, *contracts):
        """Roots that hold *contracts*, then raise, as a bug in the walk does."""
        for contract in contracts:
            yield gen_module.ET.fromstring(_generator(contract))
        raise OSError("a bug")

    def test_a_walk_that_stops_before_any_variant_fails(self, gen_module, tmp_path, caplog):
        with caplog.at_level(logging.WARNING), pytest.raises(
            gen_module.ContractScanFailed
        ) as failure:
            gen_module.scan_contract_generators(
                tmp_path, template_lookup={}, roots=self._roots(gen_module))

        assert (failure.value.skipped, failure.value.total) == (0, 0)
        assert failure.value.first == "OSError: a bug"
        assert str(failure.value) == "The contract scan stopped: OSError: a bug"
        assert _warnings_and_up(caplog) == [
            ("WARNING", "Error scanning contract generators: a bug"),
        ]

    def test_a_walk_that_stops_later_keeps_what_it_read(self, gen_module, tmp_path):
        missions, _, _, _ = gen_module.scan_contract_generators(
            tmp_path, template_lookup={}, roots=self._roots(gen_module, _contract("read")))
        assert list(missions) == ["read_title"]

    @pytest.mark.parametrize("max_workers", [1, 6], ids=["serial", "pool"])
    @pytest.mark.parametrize("wrong_call", [False, True], ids=["control", "wrong_call"])
    def test_main_then_keeps_the_old_ini(
        self, gen_module, tmp_path, monkeypatch, wrong_call, max_workers
    ):
        """A wrong call fails the run and leaves the old INI byte for byte, on the serial
        path the GUI takes and the pool the CLI takes. The control is the same run with
        the real class, which replaces it."""
        forge_dir = tmp_path / "forge"
        contractgen_dir = forge_dir / DATAFORGE_RECORDS_SUBPATH / "contracts" / "contractgenerator"
        contractgen_dir.mkdir(parents=True)
        (contractgen_dir / "contracts.xml").write_text(
            _generator(_contract("a")), encoding="utf-8"
        )
        base_ini = tmp_path / "base.ini"
        base_ini.write_text("a_title=A Title\na_desc=A description\n", encoding="utf-8")
        old_ini = tmp_path / "mission_rewards_enhancements.ini"
        old_ini.write_bytes(b"old=old\r\n")

        def generate():
            gen_module.main(
                base_ini, forge_dir, categories={"mission_rewards", "medical_consumables"},
                max_workers=max_workers,
            )

        if wrong_call:
            monkeypatch.setattr(gen_module, "ContractVariant", _wider_variant(gen_module))
            with pytest.raises(gen_module.ContractScanFailed):
                generate()
            assert old_ini.read_bytes() == b"old=old\r\n"
        else:
            generate()
            assert old_ini.read_bytes() != b"old=old\r\n"


@pytest.fixture
def worker_loads_the_script_with(tmp_path, monkeypatch):
    """The worker loads the real script with one piece of it changed."""
    script = tmp_path / "scripts" / "generate_enhancements_ini.py"
    script.parent.mkdir()
    real = importlib.util.spec_from_file_location

    def spec_from_file_location(name, location=None, *args, **kwargs):
        if name == _WORKER_MODULE:
            location = script
        return real(name, location, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "spec_from_file_location", spec_from_file_location)
    monkeypatch.setitem(sys.modules, _WORKER_MODULE, None)
    monkeypatch.setattr(sys, "path", list(sys.path))

    def change(old, new):
        text = _SCRIPT.read_text(encoding="utf-8")
        assert text.count(old) == 1
        script.write_text(text.replace(old, new), encoding="utf-8")

    return change


class TestTheFailureReachesTheUser:
    @pytest.mark.parametrize("old, new, language, opening, tail", [
        ("rep_track=rep_track,", "", "english",
         "Enhancement generation stopped because 1 of 1 contracts could not be read.",
         "\nodd: TypeError: "),
        ("rep_track=rep_track,", "", "german",
         "Die Erzeugung der Erweiterungen wurde gestoppt, weil 1 von 1 Aufträgen",
         "\nodd: TypeError: "),
        ("handler_flags = []", "raise OSError('a bug')", "english",
         "Enhancement generation stopped because the contract scan ended with an error.",
         "\nOSError: a bug"),
        ("handler_flags = []", "raise OSError('a bug')", "german",
         "Die Erzeugung der Erweiterungen wurde gestoppt, weil das Lesen der Aufträge",
         "\nOSError: a bug"),
    ], ids=["call_english", "call_german", "walk_english", "walk_german"])
    def test_in_the_selected_language_with_the_old_set_kept(
        self, tmp_profile, qapp, english_ui, worker_loads_the_script_with, caplog,
        old, new, language, opening, tail
    ):
        """The real worker running the script on a real cache folder and base.ini."""
        worker_loads_the_script_with(old, new)
        i18n.set_language(language)
        contractgen_dir = (
            AppSettings.get_dataforge_cache_leaf() / DATAFORGE_RECORDS_SUBPATH
            / "contracts" / "contractgenerator"
        )
        contractgen_dir.mkdir(parents=True)
        (contractgen_dir / "contracts.xml").write_text(
            _generator(_contract("odd")), encoding="utf-8"
        )
        base_ini = AppSettings.get_base_ini_path()
        base_ini.parent.mkdir(parents=True, exist_ok=True)
        base_ini.write_text("odd_title=Odd\n", encoding="utf-8")
        old_ini = AppSettings.get_enhancements_dir() / "mission_rewards_enhancements.ini"
        old_ini.write_bytes(b"old=old\r\n")
        AppSettings.set_enhancements_stamp("an old build")

        worker = EnhancementsGeneratorWorker(
            categories={"mission_rewards"}, tag_configs=AppSettings.get_all_tag_configs()
        )
        finished, errors = [], []
        worker.finished.connect(finished.append, Qt.ConnectionType.DirectConnection)
        worker.error.connect(errors.append, Qt.ConnectionType.DirectConnection)
        with caplog.at_level(logging.WARNING):
            worker.start()
            assert worker.wait(60000), "the generator worker did not finish"

        assert finished == [False]
        assert len(errors) == 1 and errors[0].startswith(opening)
        assert tail in errors[0]
        assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == errors
        assert old_ini.read_bytes() == b"old=old\r\n"
        assert not AppSettings.get_enhancements_stamp()

    def test_english_in_full(self, english_ui):
        assert i18n.tr("extract.contract_scan_failed", skipped=2, total=3, first="x: Error") == (
            "Enhancement generation stopped because 2 of 3 contracts could not be read. Your "
            "existing enhancements are unchanged. Please report this, as it is usually a fault "
            "in Smart Citizen.\n\nThe first contract:\nx: Error"
        )
        assert i18n.tr("extract.contract_scan_stopped", first="OSError: x") == (
            "Enhancement generation stopped because the contract scan ended with an error. Your "
            "existing enhancements are unchanged. Please report this, as it is usually a fault "
            "in Smart Citizen.\n\nThe error:\nOSError: x"
        )

    @pytest.mark.parametrize("key", sorted(_KEY_FIELDS))
    @pytest.mark.parametrize("ui_json", _UI_FILES, ids=lambda p: p.parent.name)
    def test_every_language_has_the_texts(self, ui_json, key):
        """Its fields, the contract or error on a line of its own at the end, and the
        provenance languages/TRANSLATIONS.md asks for."""
        node = json.loads(ui_json.read_text(encoding="utf-8"))["extract"][key]
        if ui_json.parent.name == "english":
            assert node["ht"] and node["at"] == ""
        else:
            assert node["ht"] == "" and node["at"]
        text = node["ht"] or node["at"]
        fields = {field for _, field, _, _ in string.Formatter().parse(text) if field}
        assert fields == _KEY_FIELDS[key]
        assert text.endswith("\n{first}")
        formatted = text.format(skipped=1, total=2, first="x")
        assert "{" not in formatted and "}" not in formatted


_SUB_CONTRACTS = """<subContracts>
        <SubContract>
          <ContractStringParam param="Title" value="@sentinel_desc_title" />
          <ContractStringParam param="Description" value="@LOC_EMPTY" />
        </SubContract>
        <SubContract>
          <ContractStringParam param="Description" value="@no_title_desc" />
        </SubContract>
      </subContracts>"""


class TestSubContractVariants:
    def _missions(self, gen_module, tmp_path):
        return _scan(gen_module, tmp_path, _generator(_contract("parent", _SUB_CONTRACTS)))

    def test_a_sentinel_description_counts_as_none(self, gen_module, tmp_path):
        """``@LOC_EMPTY`` is the game's placeholder, so the contract's description stays."""
        missions = self._missions(gen_module, tmp_path)
        assert missions["sentinel_desc_title"][0].desc_key == "parent_desc"
        assert missions["sentinel_desc_title"] == missions["parent_title"]

    def test_one_with_no_title_adds_nothing(self, gen_module, tmp_path):
        assert sorted(self._missions(gen_module, tmp_path)) == [
            "parent_title", "sentinel_desc_title",
        ]
