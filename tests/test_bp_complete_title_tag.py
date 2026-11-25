"""The [BP Complete] mission title tag (General Tags' "BP Completed").

A mission whose every blueprint is in the Owned set gets ``[BP Complete]`` on
its title, right after the generator's ``[BP]`` / ``[BP?]`` tag. The
generator does not write the tag: it records each blueprint mission's
description keys (``blueprint_meta.MISSION_BLUEPRINT_DESCS_FILE``), and
``MainWindow`` weaves the tag in on every load and Owned change, as it weaves
``[Owned]`` into blueprint bullets, so it follows the Owned set with no new
generation. Covers:

- ``owned_items.apply_bp_complete_to_title``: placement after ``[BP]`` /
  ``[BP?]`` or at the end, idempotent, taken off again.
- ``owned_items.complete_mission_titles``: every description's names count,
  one unowned name or no names at all keeps a mission incomplete.
- ``build_blueprint_metadata``'s ``names_by_desc``: the names the tracker
  and the Owned set use, aliases resolved.
- The record: written and read back, missing or broken reads as empty, the
  generator fills it for a blueprint title only, and ``main()`` writes it
  beside the mission INI.
- The setting (on by default), ``MainWindow._bp_complete_titles``,
  ``_read_mission_bp_descs``, ``_recompute_owned`` and Apply's merge.
- The Enhancements tab checkbox re-weaves at once and lights no Save Tag
  Changes.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import QSettings

REPO = Path(__file__).resolve().parent.parent

from src.gui.main_window import (  # noqa: E402
    MainWindow, _ApplyMergeInputs, _enhancement_summary_block, _merge_for_apply,
)
from src.models.string_model import CATEGORY_MISSIONS  # noqa: E402
from src.utils.blueprint_meta import (  # noqa: E402
    MISSION_BLUEPRINT_DESCS_FILE,
    build_blueprint_metadata,
    complete_titles_in_strings,
    read_mission_blueprint_descs,
    write_mission_blueprint_descs,
)
from src.utils.json_settings import JsonSettings  # noqa: E402
from src.utils.owned_items import (  # noqa: E402
    BULLET_NAME_ALIASES,
    apply_bp_complete_to_title,
    bp_title_tag,
    complete_mission_titles,
    has_bp_complete_tag,
)
from src.utils.settings import AppSettings  # noqa: E402

pytestmark = pytest.mark.unit

BP_COMPLETE = AppSettings.MISSION_TITLE_TAG_BP_COMPLETE
TAG = "<EM4>[BP Complete]</EM4>"


def _desc(*names: str) -> str:
    bullets = "".join(f"\\n- {n}" for n in names)
    return f"Clear the outpost.\\n\\n<EM3>POTENTIAL BLUEPRINTS</EM3>{bullets}"


def _entry(key: str, value: str, category: str = CATEGORY_MISSIONS):
    return SimpleNamespace(key=key, original_value=value, category=category, custom_value="")


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    """One shared file-backed QSettings, as test_mission_title_tags.py uses."""
    shared = QSettings(str(tmp_path / "reg.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(AppSettings, "settings", staticmethod(lambda: shared))
    return shared


# ── apply_bp_complete_to_title ──────────────────────────────────────────────

class TestApplyToTitle:
    def test_replaces_the_bp_tag(self):
        value = "Salvager Needed <EM4>[BP]</EM4> <EM4>[100 Rep]</EM4>"
        assert apply_bp_complete_to_title(value, True) == (
            f"Salvager Needed {TAG} <EM4>[100 Rep]</EM4>"
        )

    def test_replaces_an_uncertain_bp_tag(self):
        value = "Haul <EM4>[BP?]</EM4> <EM4>[50 Rep]</EM4>"
        assert apply_bp_complete_to_title(value, True) == f"Haul {TAG} <EM4>[50 Rep]</EM4>"

    def test_puts_back_the_tag_it_replaced(self):
        value = "Haul <EM4>[BP?]</EM4> <EM4>[50 Rep]</EM4>"
        tagged = apply_bp_complete_to_title(value, True)
        assert bp_title_tag(value) == "<EM4>[BP?]</EM4>"
        assert apply_bp_complete_to_title(tagged, False, bp_title_tag(value)) == value

    def test_unknown_replaced_tag_puts_back_bp(self):
        """Apply merges fresh strings, so only a user's override carries the
        tag there, with nothing to say what it replaced."""
        assert apply_bp_complete_to_title(f"Haul {TAG} <EM4>[50 Rep]</EM4>", False) == (
            "Haul <EM4>[BP]</EM4> <EM4>[50 Rep]</EM4>"
        )

    def test_an_earlier_versions_tag_beside_bp(self):
        """3.0.1's first build wrote it next to [BP]; that reads as one tag now."""
        old = f"Haul <EM4>[BP]</EM4> {TAG} <EM4>[50 Rep]</EM4>"
        assert apply_bp_complete_to_title(old, True) == f"Haul {TAG} <EM4>[50 Rep]</EM4>"
        assert apply_bp_complete_to_title(old, False) == "Haul <EM4>[BP]</EM4> <EM4>[50 Rep]</EM4>"

    def test_goes_at_the_end_without_a_bp_tag(self):
        # The BP Tag switched off leaves no [BP] to follow.
        assert apply_bp_complete_to_title("Haul <EM4>[50 Rep]</EM4>", True) == (
            f"Haul <EM4>[50 Rep]</EM4> {TAG}"
        )

    def test_is_idempotent(self):
        once = apply_bp_complete_to_title("Clear <EM4>[BP]</EM4>", True)
        assert apply_bp_complete_to_title(once, True) == once
        assert once.count("[BP Complete]") == 1

    def test_comes_off_again_exactly(self):
        value = "Salvager Needed <EM4>[BP]</EM4> <EM4>[100 Rep]</EM4>"
        tagged = apply_bp_complete_to_title(value, True)
        assert apply_bp_complete_to_title(tagged, False) == value
        assert apply_bp_complete_to_title(value, False) == value
        # Added at the end (no [BP] tag): comes off with nothing put back.
        plain = "Haul <EM4>[50 Rep]</EM4>"
        assert apply_bp_complete_to_title(
            apply_bp_complete_to_title(plain, True), False, bp_title_tag(plain)) == plain

    def test_empty_value_stays_empty(self):
        assert apply_bp_complete_to_title("", True) == ""

    def test_has_tag(self):
        assert has_bp_complete_tag(apply_bp_complete_to_title("A <EM4>[BP]</EM4>", True))
        assert not has_bp_complete_tag("A <EM4>[BP]</EM4>")
        assert not has_bp_complete_tag("")


# ── complete_mission_titles ─────────────────────────────────────────────────

class TestCompleteMissionTitles:
    TITLES = {"T": ("D1", "D2")}
    NAMES = {"D1": frozenset({"Arrow"}), "D2": frozenset({"Bolt", "Arrow"})}

    def test_complete_when_every_description_name_is_owned(self):
        assert complete_mission_titles(self.TITLES, self.NAMES, {"Arrow", "Bolt", "X"}) == {"T"}

    def test_one_unowned_name_in_any_description_keeps_it_incomplete(self):
        # D1 alone is complete; D2's Bolt is not owned.
        assert complete_mission_titles(self.TITLES, self.NAMES, {"Arrow"}) == frozenset()

    def test_no_names_is_never_complete(self):
        # The POTENTIAL BLUEPRINTS body hidden: nothing says what it awards.
        assert complete_mission_titles({"T": ("D9",)}, self.NAMES, {"Arrow"}) == frozenset()

    def test_nothing_owned(self):
        assert complete_mission_titles(self.TITLES, self.NAMES, set()) == frozenset()


# ── build_blueprint_metadata's names_by_desc ────────────────────────────────

class TestNamesByDesc:
    def test_resolved_names_per_description(self):
        alias, real = next(iter(BULLET_NAME_ALIASES.items()))
        entries = [
            _entry("item_NameArrow", "Arrow", "Gear"),
            _entry("M_Title_001", "Clear <EM4>[BP]</EM4>"),
            _entry("M_Desc_001", _desc("Arrow", alias)),
            _entry("Other_Desc", "No blueprints here."),
        ]
        names: dict = {}
        meta = build_blueprint_metadata(entries, names_by_desc=names)
        assert names == {"M_Desc_001": frozenset({"Arrow", real})}
        # The same names the tracker offers, so the Owned set can match them.
        assert names["M_Desc_001"] <= set(meta)

    def test_not_given_changes_nothing(self):
        entries = [_entry("M_Desc_001", _desc("Arrow"))]
        assert build_blueprint_metadata(entries) == build_blueprint_metadata(
            entries, names_by_desc={},
        )


# ── The record ──────────────────────────────────────────────────────────────

class TestRecordFile:
    def test_round_trip(self, tmp_path):
        path = tmp_path / MISSION_BLUEPRINT_DESCS_FILE
        write_mission_blueprint_descs(path, {"T2": ["D3"], "T1": ["D1", "D2"]})
        assert read_mission_blueprint_descs(path) == {"T1": ("D1", "D2"), "T2": ("D3",)}

    def test_sorted_so_runs_match(self, tmp_path):
        a, b = tmp_path / "a.json", tmp_path / "b.json"
        write_mission_blueprint_descs(a, {"T2": ["D3"], "T1": ["D1"]})
        write_mission_blueprint_descs(b, {"T1": ["D1"], "T2": ["D3"]})
        assert a.read_bytes() == b.read_bytes()

    def test_missing_reads_empty(self, tmp_path):
        assert read_mission_blueprint_descs(tmp_path / "nope.json") == {}

    @pytest.mark.parametrize("text", ["{not json", "[]", '{"titles": []}',
                                      '{"titles": {"T": "D"}}'])
    def test_broken_reads_empty(self, tmp_path, text):
        path = tmp_path / MISSION_BLUEPRINT_DESCS_FILE
        path.write_text(text, encoding="utf-8")
        assert read_mission_blueprint_descs(path) == {}


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location(
        "generate_enhancements_ini_bp_complete_test",
        REPO / "scripts" / "generate_enhancements_ini.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop(spec.name, None)


_POOL_UUID = "11111111-1111-1111-1111-111111111111"
_BP_UUID = "22222222-2222-2222-2222-222222222222"
_ENTITY_UUID = "33333333-3333-3333-3333-333333333333"
_TITLE_KEY = "bpcomplete_test_title_001"
_DESC_KEY = "bpcomplete_test_desc_001"
_PLAIN_TITLE = "bpcomplete_plain_title_001"
_PLAIN_DESC = "bpcomplete_plain_desc_001"

_CONTRACT_GEN_XML = f"""\
<?xml version="1.0" encoding="utf-8"?>
<ContractGenerator>
  <ContractGeneratorHandler_List debugName="Stanton_Test">
    <Contract debugName="Stanton_BpComplete" notForRelease="0" minStanding="">
      <ContractStringParam param="Title" value="@{_TITLE_KEY}" />
      <ContractStringParam param="Description" value="@{_DESC_KEY}" />
      <BlueprintRewards blueprintPool="{_POOL_UUID}" chance="1" />
    </Contract>
    <Contract debugName="Stanton_NoBlueprint" notForRelease="0" minStanding="">
      <ContractStringParam param="Title" value="@{_PLAIN_TITLE}" />
      <ContractStringParam param="Description" value="@{_PLAIN_DESC}" />
    </Contract>
  </ContractGeneratorHandler_List>
</ContractGenerator>
"""
_BP_RECORD_XML = f"""\
<?xml version="1.0" encoding="utf-8"?>
<CraftingBlueprintRecord __ref="{_BP_UUID}">
  <CraftingProcess_Creation entityClass="{_ENTITY_UUID}" />
</CraftingBlueprintRecord>
"""
_POOL_RECORD_XML = f"""\
<?xml version="1.0" encoding="utf-8"?>
<BlueprintPoolRecord __ref="{_POOL_UUID}">
  <BlueprintReward blueprintRecord="{_BP_UUID}" />
</BlueprintPoolRecord>
"""
_LOC = {
    _TITLE_KEY: "Clear the Outpost", _DESC_KEY: "Clear the outpost of hostiles.",
    _PLAIN_TITLE: "Plain Job", _PLAIN_DESC: "A job with no blueprints.",
    "item_Name_test_rifle": "Test Rifle",
}


def _run_missions(gen, tmp_path):
    records = tmp_path / "records"
    contractgen = records / "contracts" / "contractgenerator"
    bp_dir = records / "crafting" / "blueprints" / "crafting"
    pool_dir = records / "crafting" / "blueprintrewards"
    for d in (contractgen, bp_dir, pool_dir):
        d.mkdir(parents=True, exist_ok=True)
    (contractgen / "gen.xml").write_text(_CONTRACT_GEN_XML, encoding="utf-8")
    (bp_dir / "bp_craft_test_rifle.xml").write_text(_BP_RECORD_XML, encoding="utf-8")
    (pool_dir / "bp_rewards_test.xml").write_text(_POOL_RECORD_XML, encoding="utf-8")
    ctx = {
        "records": records,
        "forge_dir": tmp_path / "forge",
        "loc": dict(_LOC),
        "tag_loc": dict(_LOC),
        "entity_names": {_ENTITY_UUID: "Test Rifle"},
        "reputation_lookup": {},
    }
    return gen._run_gen_missions(ctx), ctx


class TestGenerator:
    def test_records_a_blueprint_title_only(self, gen, tmp_path):
        out, ctx = _run_missions(gen, tmp_path)
        assert "<EM4>[BP]</EM4>" in out[_TITLE_KEY]
        assert ctx["mission_blueprint_descs"] == {_TITLE_KEY: [_DESC_KEY]}

    def test_writes_no_tag_of_its_own(self, gen, tmp_path):
        out, _ctx = _run_missions(gen, tmp_path)
        assert not any(has_bp_complete_tag(v) for v in out.values())

    def test_end_to_end_with_the_owned_set(self, gen, tmp_path):
        """What a load does with the generator's output and record."""
        out, ctx = _run_missions(gen, tmp_path)
        entries = [_entry(k, v) for k, v in out.items()]
        names: dict = {}
        build_blueprint_metadata(entries, names_by_desc=names)
        titles = {t: tuple(d) for t, d in ctx["mission_blueprint_descs"].items()}
        assert complete_mission_titles(titles, names, {"Test Rifle"}) == {_TITLE_KEY}
        assert complete_mission_titles(titles, names, {"Other"}) == frozenset()
        tagged = apply_bp_complete_to_title(out[_TITLE_KEY], True)
        assert "<EM4>[BP Complete]</EM4>" in tagged and "<EM4>[BP]</EM4>" not in tagged

    def test_main_writes_the_record_beside_the_mission_ini(self, gen, tmp_path):
        base_ini = tmp_path / "base.ini"
        base_ini.write_text("Dummy_Key=Dummy\n", encoding="utf-8")
        forge_dir = tmp_path / "forge"
        (forge_dir / "raw" / "libs" / "foundry" / "records").mkdir(parents=True)

        def fake_missions(ctx):
            ctx["mission_blueprint_descs"]["T"] = ["D1", "D2"]
            return {"T": "Title <EM4>[BP]</EM4>"}

        with patch.object(gen, "_run_gen_missions", side_effect=fake_missions):
            gen.main(base_ini_path=base_ini, forge_dir=forge_dir,
                     categories={"mission_rewards"}, max_workers=1)
        assert (tmp_path / "mission_rewards_enhancements.ini").exists()
        assert read_mission_blueprint_descs(tmp_path / MISSION_BLUEPRINT_DESCS_FILE) == {
            "T": ("D1", "D2"),
        }


# ── The setting ─────────────────────────────────────────────────────────────

class TestSetting:
    def test_is_a_general_tag(self):
        assert BP_COMPLETE in AppSettings.MISSION_TITLE_TAG_KEYS

    def test_on_by_default(self, isolated_settings):
        assert AppSettings.get_mission_title_tags()[BP_COMPLETE] is True
        assert AppSettings.get_mission_title_tag_default(BP_COMPLETE) is True

    def test_round_trips(self, isolated_settings):
        AppSettings.set_mission_title_tag(BP_COMPLETE, False)
        assert AppSettings.get_mission_title_tags()[BP_COMPLETE] is False


# ── MainWindow ──────────────────────────────────────────────────────────────

class _Window:
    """Carries what the [BP Complete] weave touches."""

    _bp_complete_record = MainWindow._bp_complete_record
    _bp_complete_titles = MainWindow._bp_complete_titles
    _read_mission_bp_descs = MainWindow._read_mission_bp_descs
    _recompute_owned = MainWindow._recompute_owned
    _apply_merge_inputs = MainWindow._apply_merge_inputs

    def __init__(self, entries=(), titles=None, names=None):
        self.entries = list(entries)
        self._mission_bp_descs = titles or {}
        self._bp_names_by_desc = names or {}
        self._mission_bp_descs_key = None
        self._bp_tags_under_complete = {}
        self._bp_item_names = set()
        self._blueprint_meta = {}
        self._sco_overlay = None
        self._model = MagicMock()
        self.marked_dirty = 0

    def _bp_header(self):
        return None

    def _mark_apply_dirty(self):
        self.marked_dirty += 1


_TITLES = {"M_Title_001": ("M_Desc_001",)}
_NAMES = {"M_Desc_001": frozenset({"Arrow"})}


@pytest.fixture
def owned(isolated_settings, monkeypatch):
    state = {"owned": set()}
    monkeypatch.setattr(AppSettings, "get_owned_items", staticmethod(lambda: set(state["owned"])))
    monkeypatch.setattr(AppSettings, "get_all_tag_configs", staticmethod(lambda: {}))
    return state


class TestBpCompleteTitles:
    def test_complete_titles(self, owned):
        assert _Window(titles=_TITLES, names=_NAMES)._bp_complete_titles({"Arrow"}) == {
            "M_Title_001",
        }

    def test_switch_off_tags_nothing(self, owned):
        AppSettings.set_mission_title_tag(BP_COMPLETE, False)
        assert _Window(titles=_TITLES, names=_NAMES)._bp_complete_titles({"Arrow"}) == frozenset()

    def test_no_record_tags_nothing(self, owned):
        assert _Window(names=_NAMES)._bp_complete_titles({"Arrow"}) == frozenset()


class TestRecomputeOwned:
    def _window(self):
        return _Window(
            [_entry("M_Title_001", "Clear <EM4>[BP]</EM4> <EM4>[100 Rep]</EM4>"),
             _entry("M_Desc_001", _desc("Arrow"))],
            titles=_TITLES, names=_NAMES,
        )

    def test_owning_every_blueprint_tags_the_title(self, owned):
        owned["owned"] = {"Arrow"}
        window = self._window()
        window._recompute_owned()
        assert window.entries[0].original_value == f"Clear {TAG} <EM4>[100 Rep]</EM4>"
        assert window.marked_dirty == 1

    def test_unowning_one_takes_the_tag_off(self, owned):
        owned["owned"] = {"Arrow"}
        window = self._window()
        window._recompute_owned()
        owned["owned"] = set()
        window._recompute_owned()
        assert window.entries[0].original_value == "Clear <EM4>[BP]</EM4> <EM4>[100 Rep]</EM4>"

    def test_an_uncertain_bp_tag_comes_back_as_it_was(self, owned):
        """The table edits values in place, so it remembers the tag it
        replaced: [BP?] must not come back as [BP]."""
        window = _Window(
            [_entry("M_Title_001", "Haul <EM4>[BP?]</EM4> <EM4>[50 Rep]</EM4>"),
             _entry("M_Desc_001", _desc("Arrow"))],
            titles=_TITLES, names=_NAMES,
        )
        owned["owned"] = {"Arrow"}
        window._recompute_owned()
        window._recompute_owned()  # again while still complete
        assert window.entries[0].original_value == f"Haul {TAG} <EM4>[50 Rep]</EM4>"
        owned["owned"] = set()
        window._recompute_owned()
        assert window.entries[0].original_value == "Haul <EM4>[BP?]</EM4> <EM4>[50 Rep]</EM4>"
        assert window._bp_tags_under_complete == {}

    def test_switching_off_takes_the_tag_off(self, owned):
        owned["owned"] = {"Arrow"}
        window = self._window()
        window._recompute_owned()
        AppSettings.set_mission_title_tag(BP_COMPLETE, False)
        window._recompute_owned()
        assert not has_bp_complete_tag(window.entries[0].original_value)


class TestReadRecord:
    @pytest.fixture
    def data_dir(self, tmp_path):
        saved = AppSettings._backend
        AppSettings._backend = JsonSettings(tmp_path / "config.json")
        AppSettings.set_user_data_dir(tmp_path / "data")
        yield AppSettings.get_base_ini_leaf().parent
        AppSettings._backend = saved

    def test_reads_from_the_loaded_languages_folder(self, data_dir):
        data_dir.mkdir(parents=True)
        write_mission_blueprint_descs(data_dir / MISSION_BLUEPRINT_DESCS_FILE, {"T": ["D"]})
        window = _Window()
        window._read_mission_bp_descs()
        assert window._mission_bp_descs == {"T": ("D",)}

    def test_read_again_only_once_it_changes(self, data_dir):
        data_dir.mkdir(parents=True)
        path = data_dir / MISSION_BLUEPRINT_DESCS_FILE
        write_mission_blueprint_descs(path, {"T": ["D"]})
        window = _Window()
        window._read_mission_bp_descs()
        with patch("src.utils.blueprint_meta.read_mission_blueprint_descs") as read:
            window._read_mission_bp_descs()
        read.assert_not_called()
        write_mission_blueprint_descs(path, {"T": ["D"], "T2": ["D2", "D3"]})
        window._read_mission_bp_descs()
        assert window._mission_bp_descs == {"T": ("D",), "T2": ("D2", "D3")}

    def test_missing_makes_no_folder(self, data_dir):
        window = _Window()
        window._read_mission_bp_descs()
        assert window._mission_bp_descs == {}
        assert not data_dir.exists()


# ── Apply's merge ───────────────────────────────────────────────────────────

def _inputs(**overrides) -> _ApplyMergeInputs:
    values = dict(
        user_overrides={}, discarded_new_keys=frozenset(), owned=set(),
        enclosings=(), bp_header=None, sc_language_id="english",
    )
    values.update(overrides)
    return _ApplyMergeInputs(**values)


class TestMergeForApply:
    """Apply works the complete titles out from the strings it writes."""

    TITLE = "Clear <EM4>[BP]</EM4> <EM4>[100 Rep]</EM4>"
    TAGGED = f"Clear {TAG} <EM4>[100 Rep]</EM4>"

    def _sources(self, *names):
        return {"global": {"M_Title_001": self.TITLE, "X": "x"},
                "enhancements": {"M_Desc_001": _desc(*names)}}

    def _merge(self, sources, **inputs):
        return _merge_for_apply(sources, ["global", "enhancements"],
                                _inputs(bp_complete_record=_TITLES, **inputs))

    def test_tags_a_mission_whose_every_blueprint_is_owned(self):
        merged = self._merge(self._sources("Arrow", "Gladius"), owned={"Arrow", "Gladius"})
        assert merged["M_Title_001"] == self.TAGGED
        assert merged["X"] == "x"

    def test_one_blueprint_not_owned_leaves_it_off(self):
        merged = self._merge(self._sources("Arrow", "Gladius"), owned={"Arrow"})
        assert merged["M_Title_001"] == self.TITLE

    def test_no_record_or_nothing_owned_scans_nothing(self):
        with patch("src.utils.blueprint_meta.build_blueprint_metadata") as scan:
            _merge_for_apply(self._sources("Arrow"), ["global", "enhancements"],
                             _inputs(owned={"Arrow"}))
            self._merge(self._sources("Arrow"), owned=set())
        scan.assert_not_called()

    def test_reads_the_bullets_the_user_wrote(self):
        """A user override of the description is what the file gets, so it
        is what the tag goes by."""
        merged = self._merge(self._sources("Arrow"), owned={"Arrow"},
                             user_overrides={"M_Desc_001": _desc("Arrow", "Gladius")})
        assert merged["M_Title_001"] == self.TITLE

    def test_strips_an_override_for_a_mission_no_longer_complete(self):
        tagged = apply_bp_complete_to_title(self.TITLE, True)
        merged = _merge_for_apply(
            {"global": {"M_Title_001": self.TITLE}}, ["global"],
            _inputs(user_overrides={"M_Title_001": tagged}),
        )
        assert merged["M_Title_001"] == self.TITLE


class TestApplyStraightAfterAGeneration:
    """Simple mode applies right after the generation that wrote the record,
    before the reload that reads it, so the window's names are from before
    the run. Apply must still tag the title in the file it writes."""

    @pytest.fixture
    def data_dir(self, owned, tmp_path):
        saved = AppSettings._backend
        AppSettings._backend = JsonSettings(tmp_path / "config.json")
        AppSettings.set_user_data_dir(tmp_path / "data")
        folder = AppSettings.get_base_ini_leaf().parent
        folder.mkdir(parents=True)
        yield folder
        AppSettings._backend = saved

    def test_a_record_written_after_the_load_is_used(self, owned, data_dir):
        window = _Window()  # loaded before the run: no record, no names
        window._read_mission_bp_descs()
        assert window._mission_bp_descs == {}
        write_mission_blueprint_descs(data_dir / MISSION_BLUEPRINT_DESCS_FILE,
                                      {"M_Title_001": ["M_Desc_001"]})
        owned["owned"] = {"Arrow"}

        merged = _merge_for_apply(
            {"global": {"M_Title_001": TestMergeForApply.TITLE},
             "enhancements": {"M_Desc_001": _desc("Arrow")}},
            ["global", "enhancements"], window._apply_merge_inputs(),
        )
        assert merged["M_Title_001"] == TestMergeForApply.TAGGED

    def test_switch_off_hands_apply_no_record(self, owned, data_dir):
        write_mission_blueprint_descs(data_dir / MISSION_BLUEPRINT_DESCS_FILE,
                                      {"M_Title_001": ["M_Desc_001"]})
        owned["owned"] = {"Arrow"}
        AppSettings.set_mission_title_tag(BP_COMPLETE, False)
        assert _Window()._apply_merge_inputs().bp_complete_record == {}


class TestCompleteTitlesInStrings:
    def test_matches_the_tables_names(self):
        """The same item resolution as the load: a bullet with a Tag Builder
        tag resolves to the item's plain name, as the Owned set holds it."""
        strings = {
            "item_NameSHLD_Arrow": "Arrow [MIL-S1-A]",
            "M_Desc_001": _desc("Arrow [MIL-S1-A]"),
        }
        assert complete_titles_in_strings(
            strings, _TITLES, {"Arrow"}, default_values={"item_NameSHLD_Arrow": "Arrow"},
        ) == {"M_Title_001"}

    def test_empty_record_or_owned_set(self):
        strings = {"M_Desc_001": _desc("Arrow")}
        assert complete_titles_in_strings(strings, {}, {"Arrow"}) == frozenset()
        assert complete_titles_in_strings(strings, _TITLES, set()) == frozenset()


# ── A set generated before the record existed ───────────────────────────────

class TestRecordMissingIsOutOfDate:
    """Without the record no title can be tagged, and only a generation
    writes it, so a set without one must not read as current."""

    @pytest.fixture
    def enh_dir(self, isolated_settings, tmp_path, monkeypatch):
        AppSettings.set_user_data_dir(tmp_path / "data")
        monkeypatch.setattr(AppSettings, "get_dataforge_build_key",
                            staticmethod(lambda forge_dir=None: "build-1"))
        folder = AppSettings.get_enhancements_dir()
        folder.mkdir(parents=True, exist_ok=True)
        AppSettings.set_enhancements_stamp("build-1")
        (folder / AppSettings.ENHANCEMENTS_FILES[AppSettings.ENHANCEMENT_FILE_MISSIONS]
         ).write_text("; generated\n", encoding="utf-8")
        return folder

    def _missions(self, monkeypatch, on):
        cats = {AppSettings.ENHANCEMENT_FILE_MISSIONS} if on else {"ship_descs"}
        monkeypatch.setattr(AppSettings, "get_enabled_enhancement_categories",
                            staticmethod(lambda: set(cats)))

    def test_missing_record_is_out_of_date(self, enh_dir, monkeypatch):
        self._missions(monkeypatch, True)
        assert AppSettings.enhancements_built_from_current_dataforge() is False

    def test_with_the_record_it_is_current(self, enh_dir, monkeypatch):
        self._missions(monkeypatch, True)
        write_mission_blueprint_descs(enh_dir / MISSION_BLUEPRINT_DESCS_FILE, {})
        assert AppSettings.enhancements_built_from_current_dataforge() is True

    def test_missions_off_needs_no_record(self, enh_dir, monkeypatch):
        self._missions(monkeypatch, False)
        assert AppSettings.enhancements_built_from_current_dataforge() is True


# ── The Apply success box ───────────────────────────────────────────────────

class TestApplySummary:
    CATS = Counter({"Ship Items": 900, CATEGORY_MISSIONS: 1200, "Gear": 300})

    def test_count_goes_right_under_missions(self):
        lines = _enhancement_summary_block(self.CATS, 112).splitlines()
        missions = lines.index(f"    {CATEGORY_MISSIONS}: 1,200")
        assert lines[missions + 1] == "      Missions marked [BP Complete]: 112"
        assert lines[0] == "  Smart Citizen enhancements (2,400 total):"

    def test_switch_off_shows_no_count(self):
        assert "[BP Complete]" not in _enhancement_summary_block(self.CATS, None)

    def test_a_zero_count_is_still_shown(self):
        assert "[BP Complete]: 0" in _enhancement_summary_block(self.CATS, 0)

    def test_no_missions_category_no_count(self):
        assert "[BP Complete]" not in _enhancement_summary_block(Counter({"Gear": 3}), 5)

    def test_nothing_enhanced(self):
        assert _enhancement_summary_block(Counter(), 5) == "  Smart Citizen enhancements: 0"


# ── The Enhancements tab checkbox ───────────────────────────────────────────

@pytest.fixture
def json_backend(tmp_path):
    saved = AppSettings._backend
    AppSettings._backend = JsonSettings(tmp_path / "config.json")
    AppSettings.set_user_data_dir(tmp_path / "data")
    yield AppSettings._backend
    AppSettings._backend = saved


class TestCheckbox:
    def _page(self):
        from src.gui.enhancements_tab import EnhancementsTab

        tab = EnhancementsTab()
        return tab, tab._tag_builder_pages["mission_titles"]

    def test_toggle_saves_and_asks_for_a_reweave_not_a_generation(self, qapp, json_backend):
        tab, page = self._page()
        reweaves = []
        tab.bp_complete_tag_changed.connect(lambda: reweaves.append(1))
        box = page._title_tag_checkboxes[BP_COMPLETE]
        assert box.isChecked() is True
        box.setChecked(False)
        assert AppSettings.get_mission_title_tags()[BP_COMPLETE] is False
        assert reweaves == [1]
        assert tab._tag_dirty is False

    def test_label_is_translated_text(self, qapp, json_backend):
        _tab, page = self._page()
        assert page._title_tag_checkboxes[BP_COMPLETE].text() == (
            'BP Completed (adds "[BP Complete]")'
        )

    def test_box_comes_right_after_bp_tag(self, qapp, json_backend):
        _tab, page = self._page()
        boxes = page._title_tag_checkboxes
        layout = boxes["blueprint"].parentWidget().layout()

        def position(box):
            # The boxes may sit in a nested layout: search it too.
            for i in range(layout.count()):
                item = layout.itemAt(i)
                if item.widget() is box:
                    return (i, -1)
                inner = item.layout()
                if inner is not None and inner.indexOf(box) >= 0:
                    return (i, inner.indexOf(box))
            raise AssertionError("checkbox not found in the page layout")

        outer, inner = position(boxes["blueprint"])
        right_after = (outer, inner + 1) if inner >= 0 else (outer + 1, -1)
        assert position(boxes[BP_COMPLETE]) == right_after

    def test_reset_to_defaults_asks_for_a_reweave_when_it_changes(self, qapp, json_backend):
        tab, page = self._page()
        page._title_tag_checkboxes[BP_COMPLETE].setChecked(False)
        reweaves = []
        tab.bp_complete_tag_changed.connect(lambda: reweaves.append(1))
        page._reset_to_defaults()
        assert AppSettings.get_mission_title_tags()[BP_COMPLETE] is True
        assert reweaves == [1]
        page._reset_to_defaults()  # already at its default: nothing to re-weave
        assert reweaves == [1]


def test_every_language_has_the_label():
    for path in sorted((REPO / "languages").glob("*/ui.json")):
        entry = json.loads(path.read_text(encoding="utf-8"))["enhancements"].get(
            "mt_tag_bp_complete_cb", {})
        assert entry.get("ht") or entry.get("at"), path.parent.name
        assert "[BP Complete]" in (entry.get("ht") or entry.get("at")), path.parent.name
