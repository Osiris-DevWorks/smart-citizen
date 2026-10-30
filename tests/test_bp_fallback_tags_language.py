"""Fuel nozzle [FN] tags in mission blueprint lists on a non-English run.

Fuel nozzles' entity XMLs are not UUID-linked to their blueprints (#281), so
their POTENTIAL BLUEPRINTS bullet gets its Type tag only from
``name_fallback_tags``, which ``bare_type_name_tag_lookup`` derives from the
item's "Item Type: Fuel Nozzle" description line (#266 follow-up). That line
only exists in the English base.ini, and the bullet names are English too
(``entity_names`` is built from the English loc), so the lookup must read the
English loc (``ctx["tag_loc"]``). It used to read the run's own language: a
French run found no "Item Type:" line, built the pools with no [FN] tag, and
pickled them under a key with no language in it, so a later English run reused
the untagged pools until the next DataForge extraction.

``_LOOKUP_VERSIONS["blueprint_pools"]`` was bumped to v15 with the fix so a
pickle written by the old code is rebuilt instead of reused.
"""
from __future__ import annotations

import importlib.util
import logging
import pickle
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location(
        "generate_enhancements_ini_fallback_language_test",
        REPO / "scripts" / "generate_enhancements_ini.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_POOL_UUID = "44444444-4444-4444-4444-444444444444"
_BP_UUID = "55555555-5555-5555-5555-555555555555"
_TITLE_KEY = "nozzle_fallback_test_title_001"
_DESC_KEY = "nozzle_fallback_test_desc_001"
_NAME_KEY = "Nozzle_FuelGiver_GRIN_NozzleFast_Name"
_DESC_ITEM_KEY = "Nozzle_FuelGiver_GRIN_NozzleFast_Desc"

_EN = {
    _TITLE_KEY: "Refuel the Relay",
    _DESC_KEY: "Refuel the relay station.",
    _NAME_KEY: "Norfield",
    _DESC_ITEM_KEY: "Manufacturer: Greycat\\nItem Type: Fuel Nozzle\\n\\nFast fuel nozzle.",
}
_FR = {
    _TITLE_KEY: "Ravitailler le relais",
    _DESC_KEY: "Ravitaillez la station relais.",
    _NAME_KEY: "Norfield",
    _DESC_ITEM_KEY: "Fabricant : Greycat\\nType d'objet : Buse de carburant\\n\\nBuse rapide.",
}


def _records(tmp_path: Path) -> Path:
    records = tmp_path / "records"
    contractgen = records / "contracts" / "contractgenerator"
    bp_dir = records / "crafting" / "blueprints" / "crafting"
    pool_dir = records / "crafting" / "blueprintrewards"
    for d in (contractgen, bp_dir, pool_dir):
        d.mkdir(parents=True, exist_ok=True)
    (contractgen / "gen.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<ContractGenerator>'
        '<ContractGeneratorHandler_List debugName="Stanton_Test">'
        '<Contract debugName="Stanton_Refuel" notForRelease="0" minStanding="">'
        f'<ContractStringParam param="Title" value="@{_TITLE_KEY}" />'
        f'<ContractStringParam param="Description" value="@{_DESC_KEY}" />'
        f'<BlueprintRewards blueprintPool="{_POOL_UUID}" chance="1" />'
        "</Contract></ContractGeneratorHandler_List></ContractGenerator>",
        encoding="utf-8",
    )
    # No entity UUID link at all, as for the real fuel nozzles (#281): the
    # name comes from the blueprint filename alias, the tag only from the
    # name-keyed fallback.
    (bp_dir / "bp_craft_nozzle_fuelgiver_grin_nozzlefast.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<CraftingBlueprintRecord __ref="{_BP_UUID}">'
        '<CraftingProcess_Creation entityClass="66666666-6666-6666-6666-666666666666" />'
        "</CraftingBlueprintRecord>",
        encoding="utf-8",
    )
    (pool_dir / "bp_rewards_test.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<BlueprintPoolRecord __ref="{_POOL_UUID}">'
        f'<BlueprintReward blueprintRecord="{_BP_UUID}" /></BlueprintPoolRecord>',
        encoding="utf-8",
    )
    return records


def _components_cfg(gen):
    cfg = gen.DEFAULT_TAG_CONFIGS["components"]
    elements = [gen.ElementSpec(e.kind, e.enabled or e.kind == "type", "short"
                                if e.kind == "type" else e.style) for e in cfg.elements]
    return gen.TagConfig(elements=elements, separator=cfg.separator, enclosing=cfg.enclosing,
                         placement=cfg.placement, class_mapping=dict(cfg.class_mapping))


def _run(gen, tmp_path, loc, forge_dir):
    cfg = _components_cfg(gen)
    ctx = {
        "records": _records(tmp_path),
        "forge_dir": forge_dir,
        "loc": loc,
        "tag_loc": dict(_EN),
        "entity_names": {},
        "reputation_lookup": {},
        "tag_configs": {"components": cfg},
        "annotate_mission_descs": True,
    }
    out = gen._run_gen_missions(ctx)
    lines = [ln for ln in out[_DESC_KEY].split("\\n") if ln.startswith("- ")]
    assert len(lines) == 1, out[_DESC_KEY]
    return lines[0]


class TestFallbackTagsOnATranslatedRun:
    def test_english_run_tags_the_nozzle(self, gen, tmp_path):
        assert _run(gen, tmp_path, dict(_EN), tmp_path / "forge") == "- [FN] Norfield"

    def test_french_run_tags_the_nozzle(self, gen, tmp_path):
        assert _run(gen, tmp_path, dict(_FR), tmp_path / "forge") == "- [FN] Norfield"

    def test_french_run_does_not_poison_a_later_english_run(self, gen, tmp_path):
        forge_dir = tmp_path / "forge"
        _run(gen, tmp_path, dict(_FR), forge_dir)
        assert _run(gen, tmp_path, dict(_EN), forge_dir) == "- [FN] Norfield"

    def test_pools_pickled_by_the_old_code_are_rebuilt(self, gen, tmp_path):
        """A v14 pickle holding untagged pools, as the old code wrote on a
        non-English run, must not be reused."""
        forge_dir = tmp_path / "forge"
        cfg = _components_cfg(gen)
        lookups = forge_dir / ".lookups"
        lookups.mkdir(parents=True)
        old_key = f"v14:{gen._dataforge_cache_key(forge_dir)}:{cfg.to_json()}|annotate=1"
        with (lookups / "blueprint_pools.pkl").open("wb") as f:
            pickle.dump((old_key, ({_POOL_UUID: ["Norfield"]}, {})), f)
        assert gen._LOOKUP_VERSIONS["blueprint_pools"] != "v14"
        assert _run(gen, tmp_path, dict(_EN), forge_dir) == "- [FN] Norfield"


class TestNozzleNameOnATranslatedRun:
    """The nozzle's own item name gets the same [FN] from the same English
    "Item Type:" line (enhancements_bare_type_tags), whatever language the
    run writes."""

    def _ctx(self, gen, loc):
        return {"loc": loc, "tag_loc": dict(_EN),
                "tag_configs": {"components": _components_cfg(gen)}}

    def test_english_run(self, gen):
        assert gen.enhancements_bare_type_tags(self._ctx(gen, dict(_EN))) == {
            _NAME_KEY: "[FN] Norfield"}

    def test_french_run(self, gen):
        fr = dict(_FR, **{_NAME_KEY: "Norfield FR"})
        assert gen.enhancements_bare_type_tags(self._ctx(gen, fr)) == {
            _NAME_KEY: "[FN] Norfield FR"}


class TestMissingEnglishBaseIni:
    """A translated run whose English base.ini is missing (Clear Cache deletes
    it, a declined re-extraction leaves it gone) falls back to the run's own
    loc. Every pickle built from that loc (standings) is keyed apart, per
    language, so neither the next English run nor another language's
    fallback run reuses it. scitem_lookups and blueprint_pools hold XML
    facts only and resolve their names through the loc on every run (perf
    proposal), so one pickle serves every language and needs no mark."""

    _LINK_UUID = "77777777-7777-7777-7777-777777777777"
    _LINK_BP_UUID = "88888888-8888-8888-8888-888888888888"
    _LINK_NAMES = {"en": "Link Item", "fr": "Objet Lien", "de": "Verbindungsobjekt"}

    @pytest.fixture
    def layout(self, gen, tmp_path):
        """The nozzle tree plus one item that IS UUID-linked to its blueprint,
        so its bullet name comes from the pickled scitem entity names."""
        staged = _records(tmp_path / "staging")
        entity = staged / "entities" / "scitem" / "misc" / "link_item.xml"
        entity.parent.mkdir(parents=True)
        entity.write_text(
            f'<EntityClassDefinition.link_item __ref="{self._LINK_UUID}">'
            '<SItemComponentParams Name="@item_Name_link_item" Description="@item_Desc_link_item"/>'
            "</EntityClassDefinition.link_item>", encoding="utf-8")
        (staged / "crafting" / "blueprints" / "crafting" / "bp_craft_link_item.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            f'<CraftingBlueprintRecord __ref="{self._LINK_BP_UUID}">'
            f'<CraftingProcess_Creation entityClass="{self._LINK_UUID}" />'
            "</CraftingBlueprintRecord>", encoding="utf-8")
        (staged / "crafting" / "blueprintrewards" / "bp_rewards_test.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            f'<BlueprintPoolRecord __ref="{_POOL_UUID}">'
            f'<BlueprintReward blueprintRecord="{_BP_UUID}" />'
            f'<BlueprintReward blueprintRecord="{self._LINK_BP_UUID}" /></BlueprintPoolRecord>',
            encoding="utf-8")
        forge_dir = tmp_path / "forge"
        shutil.copytree(staged, forge_dir / gen.DATAFORGE_RECORDS_SUBPATH)
        de = dict(_FR, **{_DESC_ITEM_KEY: "Typ: Tankdüse\\n\\nSchnelle Düse."})
        bases = {}
        for lang, loc in (("en", _EN), ("fr", _FR), ("de", de)):
            loc = dict(loc, item_Name_link_item=self._LINK_NAMES[lang])
            base = tmp_path / lang / "base.ini"
            base.parent.mkdir()
            base.write_text("".join(f"{k}={v}\n" for k, v in loc.items()), encoding="utf-8")
            bases[lang] = base
        return forge_dir, bases

    def _bullets(self, gen, base: Path) -> set:
        out = gen.parse_ini(base.parent / "mission_rewards_enhancements.ini")
        return {ln for ln in out[_DESC_KEY].split("\\n") if ln.startswith("- ")}

    def _run(self, gen, forge_dir, base, english):
        gen.main(base, forge_dir, categories={"mission_rewards"}, max_workers=1,
                 tag_configs={"components": _components_cfg(gen)},
                 english_base_ini_path=english)

    @staticmethod
    def _stored_keys(forge_dir: Path) -> dict:
        keys = {}
        for name in ("scitem_lookups", "standings", "blueprint_pools"):
            with (forge_dir / ".lookups" / f"{name}.pkl").open("rb") as f:
                keys[name] = pickle.load(f)[0]
        return keys

    def test_fallback_run_does_not_poison_the_next_english_run(self, gen, layout, caplog):
        forge_dir, bases = layout
        missing = bases["en"].parent / "missing.ini"
        caplog.set_level(logging.WARNING)
        self._run(gen, forge_dir, bases["fr"], missing)
        warned = any("English base.ini" in r.getMessage() for r in caplog.records
                     if r.levelno >= logging.WARNING)
        self._run(gen, forge_dir, bases["en"], bases["en"])
        assert self._bullets(gen, bases["en"]) == {"- [FN] Norfield", "- Link Item"}
        assert warned, "a run without its English base.ini should say so in the log"

    def test_only_the_pickle_from_the_fallback_loc_is_marked_per_language(self, gen, layout):
        forge_dir, bases = layout
        missing = bases["en"].parent / "missing.ini"
        self._run(gen, forge_dir, bases["fr"], missing)
        fr_keys = self._stored_keys(forge_dir)
        assert fr_keys["standings"].endswith(f"|en_loc=fallback:{bases['fr']}")
        self._run(gen, forge_dir, bases["en"], bases["en"])
        en_keys = self._stored_keys(forge_dir)
        for name, key in en_keys.items():
            assert "en_loc=fallback" not in key, name
        # The XML-facts pickles: no mark, one key for both languages.
        for name in ("scitem_lookups", "blueprint_pools"):
            assert fr_keys[name] == en_keys[name], name
            assert "en_loc=fallback" not in fr_keys[name], name

    def test_two_fallback_languages_each_show_their_own_names(self, gen, layout):
        forge_dir, bases = layout
        missing = bases["en"].parent / "missing.ini"
        self._run(gen, forge_dir, bases["fr"], missing)
        assert "- Objet Lien" in self._bullets(gen, bases["fr"])
        self._run(gen, forge_dir, bases["de"], missing)
        assert "- Verbindungsobjekt" in self._bullets(gen, bases["de"])
