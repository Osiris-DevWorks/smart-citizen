"""Armor weight tags on mission POTENTIAL BLUEPRINTS bullets (#492).

With Armor > Weight on and "Annotate components and armor in mission
descriptions" ticked, an armor bullet reads exactly like its tagged item name
("- [H] ADP-mk4 Core"). The tag is added only when a bullet line is written
(``_build_blueprint_body_parts`` with ``armor_bullet_names``), never baked
into the ``blueprint_pools`` pickle, so its key stays the same whatever the
armor config. Covers:

- ``armor_bullet_names``: the same tag as the item name for every class,
  nothing when the tag is off, a hand-edited None bracket read as Square (the
  Armor tab offers no None), the user's style/mapping/enclosing/placement, a
  display name behind two different tags stays bare, CIG's size prefix and a
  non-breaking space in the key.
- ``_build_blueprint_body_parts``: tagged bullets, while overrides, the drift
  check, "Set" headers and bullet and section order keep reading bare names,
  and no ``bullet_names`` leaves the output unchanged.
- ``_run_gen_missions`` end to end: tagged when on (Square for a hand-edited
  None), bare when the tag or the annotate toggle is off (no wearables scan
  when off), English tags on a translated run, and a warm-cache restyle that
  changes the bullets while the stored ``blueprint_pools`` key stays put.
- ``main()`` loads the wearables once per run, not at all with the tag off,
  and tags the bullets with only the missions enhancements selected.
- The Blueprint Tracker: ``[Owned]`` lands after a tagged bullet in every
  bracketed style, and a tagged bullet joins its bare Armor row.
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

from src.utils.blueprint_meta import build_blueprint_metadata  # noqa: E402
from src.utils.owned_items import (  # noqa: E402
    apply_owned_to_value, enclosings_from_tag_configs,
)
from src.utils.tag_builder import (  # noqa: E402
    CATEGORIES, DEFAULT_ARMOR_WEIGHT_MAPPING, ElementSpec, default_config, tag_enabled,
)

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location(
        "generate_enhancements_ini_armor_bullets_test",
        REPO / "scripts" / "generate_enhancements_ini.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _armor_cfg(style="short", **overrides):
    cfg = default_config("armor")
    cfg.elements = [ElementSpec("weight", True, style)]
    for attr, value in overrides.items():
        setattr(cfg, attr, value)
    return cfg


def _desc(item_type: str) -> str:
    return f"Manufacturer: CDS\\nItem Type: {item_type}\\n\\nLore text."


def _write_wearable(records: Path, rel: str, name_key: str, desc_key: str,
                    attach_type: str = "Char_Armor_Torso", subtype: str = "UNDEFINED") -> None:
    path = records / "entities" / "scitem" / "characters" / "human" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'<EntityClassDefinition.{path.stem} __ref="00000000-0000-0000-0000-000000000000">'
        '<Components><SAttachableComponentParams>'
        f'<AttachDef Type="{attach_type}" SubType="{subtype}" Size="1" Grade="1">'
        f'<Localization Name="@{name_key}" Description="@{desc_key}"/>'
        "</AttachDef></SAttachableComponentParams></Components>"
        f"</EntityClassDefinition.{path.stem}>",
        encoding="utf-8",
    )


def _wearables(gen, tmp_path, rows):
    """Write (stem, name_key, desc_key) wearables and index them."""
    records = tmp_path / "records"
    for stem, name_key, desc_key in rows:
        _write_wearable(records, f"armor/{stem}.xml", name_key, desc_key)
    return gen.build_wearable_index(records / gen._WEARABLES_SUBPATH)


class TestTagEnabled:
    def test_none_off_and_on(self):
        assert tag_enabled(None) is False
        assert tag_enabled(default_config("armor")) is False
        assert tag_enabled(_armor_cfg()) is True


class TestArmorBulletNames:
    ROWS = [
        ("light", "item_Name_light", "item_Desc_light", "Light Armor", "Field Recon Suit Arms"),
        ("medium", "item_Name_medium", "item_Desc_medium", "Medium Armor", "Aves Legs"),
        ("heavy", "item_Name_heavy", "item_Desc_heavy", "Heavy Armor", "ADP-mk4 Core"),
        ("superheavy", "item_Name_sh", "item_Desc_sh", "Super Heavy Armor", "BUL-H4 Helmet"),
        ("utility", "item_Name_util", "item_Desc_util", "Heavy Utility", "Novikov Helmet"),
    ]

    def _setup(self, gen, tmp_path):
        idx = _wearables(gen, tmp_path, [(s, n, d) for s, n, d, _, _ in self.ROWS])
        loc = {}
        for _s, name_key, desc_key, item_type, name in self.ROWS:
            loc[name_key] = name
            loc[desc_key] = _desc(item_type)
        return idx, loc

    @pytest.mark.parametrize("cfg_kwargs", [
        {}, {"enclosing": "round", "placement": "append"}, {"enclosing": "curly"},
    ])
    def test_bullet_reads_like_the_item_name(self, gen, tmp_path, cfg_kwargs):
        idx, loc = self._setup(gen, tmp_path)
        cfg = _armor_cfg(**cfg_kwargs)
        bullets = gen.armor_bullet_names(idx, loc, cfg)
        names = gen._run_gen_armor({
            "loc": loc, "tag_loc": loc, "tag_configs": {"armor": cfg},
            "records": tmp_path / "records", "forge_dir": tmp_path / "forge",
            "wearables": idx,
        })
        assert len(bullets) == len(self.ROWS)
        for _s, name_key, _d, _t, name in self.ROWS:
            assert bullets[name] == names[name_key]

    def test_default_style(self, gen, tmp_path):
        idx, loc = self._setup(gen, tmp_path)
        assert gen.armor_bullet_names(idx, loc, _armor_cfg()) == {
            "Field Recon Suit Arms": "[L] Field Recon Suit Arms",
            "Aves Legs": "[M] Aves Legs",
            "ADP-mk4 Core": "[H] ADP-mk4 Core",
            "BUL-H4 Helmet": "[S] BUL-H4 Helmet",
            "Novikov Helmet": "[U] Novikov Helmet",
        }

    def test_off_gives_nothing(self, gen, tmp_path):
        idx, loc = self._setup(gen, tmp_path)
        assert gen.armor_bullet_names(idx, loc, None) == {}

    @pytest.mark.parametrize("placement", ["prepend", "append"])
    def test_hand_edited_none_brackets_read_as_square(self, gen, tmp_path, placement):
        """The Armor tab offers no None brackets (the Tracker could not strip a
        one-word armor tag); _armor_tag_cfg turns a stored "none" into Square."""
        idx, loc = self._setup(gen, tmp_path)
        cfg = gen._armor_tag_cfg({"armor": _armor_cfg(enclosing="none", placement=placement)})
        assert cfg.enclosing == "square"
        tagged = "[H] ADP-mk4 Core" if placement == "prepend" else "ADP-mk4 Core [H]"
        assert gen.armor_bullet_names(idx, loc, cfg)["ADP-mk4 Core"] == tagged

    def test_user_style_and_mapping(self, gen, tmp_path):
        idx, loc = self._setup(gen, tmp_path)
        mapping = dict(DEFAULT_ARMOR_WEIGHT_MAPPING)
        mapping["Utility"] = ("H", "HV-U", "Heavy Utility")
        cfg = _armor_cfg("med", class_mapping=mapping, enclosing="angle", placement="append")
        bullets = gen.armor_bullet_names(idx, loc, cfg)
        assert bullets["Novikov Helmet"] == "Novikov Helmet <HV-U>"
        assert bullets["ADP-mk4 Core"] == "ADP-mk4 Core <HV>"

    @pytest.mark.parametrize("first,second", [("Light Armor", "Heavy Armor"),
                                              ("Heavy Armor", "Light Armor")])
    def test_shared_display_name_with_two_tags_stays_bare(self, gen, tmp_path, first, second):
        """a.xml is always read first, so swapping the classes between the two
        files is what really changes which class is seen first."""
        idx = _wearables(gen, tmp_path, [("a", "item_Name_a", "item_Desc_a"),
                                         ("b", "item_Name_b", "item_Desc_b")])
        assert [row[0] for row in idx] == ["item_Name_a", "item_Name_b"]
        loc = {"item_Name_a": "Shared Helmet", "item_Desc_a": _desc(first),
               "item_Name_b": "Shared Helmet", "item_Desc_b": _desc(second)}
        assert gen.armor_bullet_names(idx, loc, _armor_cfg()) == {}

    def test_shared_display_name_with_one_tag_is_tagged(self, gen, tmp_path):
        idx = _wearables(gen, tmp_path, [("a", "item_Name_a", "item_Desc_a"),
                                         ("b", "item_Name_b", "item_Desc_b")])
        loc = {"item_Name_a": "Shared Helmet", "item_Desc_a": _desc("Heavy Armor"),
               "item_Name_b": "Shared Helmet", "item_Desc_b": _desc("Heavy Armor")}
        assert gen.armor_bullet_names(idx, loc, _armor_cfg()) == {
            "Shared Helmet": "[H] Shared Helmet"}

    def test_size_prefix_is_stripped_like_the_bullets(self, gen, tmp_path):
        idx = _wearables(gen, tmp_path, [("a", "item_Name_a", "item_Desc_a")])
        loc = {"item_Name_a": "S1 Odd Helmet", "item_Desc_a": _desc("Light Armor")}
        assert gen.armor_bullet_names(idx, loc, _armor_cfg()) == {"Odd Helmet": "[L] Odd Helmet"}

    def test_non_breaking_space_is_kept(self, gen, tmp_path):
        idx = _wearables(gen, tmp_path, [("a", "item_Name_a", "item_Desc_a")])
        loc = {"item_Name_a": "Lynx\xa0Legs", "item_Desc_a": _desc("Medium Armor")}
        assert gen.armor_bullet_names(idx, loc, _armor_cfg()) == {
            "Lynx\xa0Legs": "[M] Lynx\xa0Legs"}


class TestBodyParts:
    BULLETS = {"ADP-mk4 Core": "[H] ADP-mk4 Core", "Palatino Core": "[M] Palatino Core",
               "Siebe Helmet": "[L] Siebe Helmet"}

    def test_single_set(self, gen):
        unique_fps = {("ADP-mk4 Core", "Norfield"): [("Stanton", "")]}
        parts = gen._build_blueprint_body_parts(unique_fps, True, self.BULLETS)
        assert parts == ["- [H] ADP-mk4 Core\\n- Norfield"]

    @pytest.mark.parametrize("bullet_names", [None, {}])
    def test_without_bullet_names_output_is_unchanged(self, gen, bullet_names):
        unique_fps = {("ADP-mk4 Core", "Norfield"): [("Stanton", "")],
                      ("Aves Legs",): [("Stanton", "")]}
        plain = gen._build_blueprint_body_parts(unique_fps)
        assert gen._build_blueprint_body_parts(unique_fps, True, bullet_names) == plain
        assert "[H]" not in "".join(plain)

    def test_colliding_header_set_name_stays_bare(self, gen):
        unique_fps = {("ADP-mk4 Core", "Norfield"): [("Stanton", "")],
                      ("Aves Legs",): [("Stanton", "")]}
        parts = gen._build_blueprint_body_parts(unique_fps, True, self.BULLETS)
        text = "\\n".join(parts)
        assert "<EM4>[Stanton, ADP-mk4 Core Set]</EM4>" in text
        assert "- [H] ADP-mk4 Core" in text
        assert "[H] ADP-mk4 Core Set" not in text

    def test_section_order_follows_the_bare_names(self, gen):
        """Several same-system sets are sorted on their bare item names, so
        ticking Armor > Weight never reorders the sections ("[" would sort
        after "A"). The tagged output is the bare output with the tags added."""
        unique_fps = {("Aves Legs",): [("Stanton", "")],
                      ("ADP-mk4 Core", "Norfield"): [("Stanton", "")]}
        bare = gen._build_blueprint_body_parts(unique_fps)
        tagged = gen._build_blueprint_body_parts(unique_fps, True, self.BULLETS)
        assert [p.split("\\n")[0] for p in tagged] == [
            "<EM4>[Stanton, ADP-mk4 Core Set]</EM4>", "<EM4>[Stanton, Aves Legs Set]</EM4>"]
        assert [p.replace("[H] ", "") for p in tagged] == bare

    def test_bullet_order_follows_the_bare_names(self, gen):
        unique_fps = {("ADP-mk4 Core", "Aves Legs", "Zeus Helmet"): [("Stanton", "")]}
        parts = gen._build_blueprint_body_parts(
            unique_fps, True, {"Zeus Helmet": "[A] Zeus Helmet", **self.BULLETS})
        assert parts == ["- [H] ADP-mk4 Core\\n- Aves Legs\\n- [A] Zeus Helmet"]

    def test_override_label_still_matches_tagged_set(self, gen):
        yormandi = next(k for k, v in gen._BLUEPRINT_POOL_LABEL_OVERRIDES.items()
                        if v == "Yormandi Eyes")
        items = tuple(sorted(yormandi))
        bullets = {n: f"[M] {n}" for n in items if n.startswith("Palatino")}
        parts = gen._build_blueprint_body_parts({items: [("Stanton", "")]}, True, bullets)
        assert parts[0].startswith("<EM4>[Yormandi Eyes]</EM4>\\n")
        assert "- [M] Palatino Core" in parts[0]

    def test_tagged_override_set_logs_no_drift_warning(self, gen, caplog):
        pearls = next(k for k, v in gen._BLUEPRINT_POOL_LABEL_OVERRIDES.items()
                      if v == "Irradiated Valakkar Pearls")
        items = tuple(sorted(pearls))
        caplog.set_level(logging.WARNING)
        parts = gen._build_blueprint_body_parts({items: [("Stanton", "")]}, True, self.BULLETS)
        assert parts[0].startswith("<EM4>[Irradiated Valakkar Pearls]</EM4>")
        assert "- [L] Siebe Helmet" in parts[0]
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


# ── _run_gen_missions end to end ────────────────────────────────────────────

_POOL_UUID = "11111111-1111-1111-1111-111111111111"
_BP_UUID = "22222222-2222-2222-2222-222222222222"
_ENTITY_UUID = "33333333-3333-3333-3333-333333333333"
_TITLE_KEY = "armorbullet_test_title_001"
_DESC_KEY = "armorbullet_test_desc_001"

_CONTRACT_GEN_XML = f"""\
<?xml version="1.0" encoding="utf-8"?>
<ContractGenerator>
  <ContractGeneratorHandler_List debugName="Stanton_Test">
    <Contract debugName="Stanton_ArmorBullet" notForRelease="0" minStanding="">
      <ContractStringParam param="Title" value="@{_TITLE_KEY}" />
      <ContractStringParam param="Description" value="@{_DESC_KEY}" />
      <BlueprintRewards blueprintPool="{_POOL_UUID}" chance="1" />
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
_EN_LOC = {
    _TITLE_KEY: "Clear the Outpost",
    _DESC_KEY: "Clear the outpost of hostiles.",
    "item_Name_adp_core": "ADP-mk4 Core",
    "item_Desc_adp_core": _desc("Heavy Armor"),
}


def _records(tmp_path: Path) -> Path:
    records = tmp_path / "records"
    contractgen = records / "contracts" / "contractgenerator"
    bp_dir = records / "crafting" / "blueprints" / "crafting"
    pool_dir = records / "crafting" / "blueprintrewards"
    for d in (contractgen, bp_dir, pool_dir):
        d.mkdir(parents=True, exist_ok=True)
    (contractgen / "gen.xml").write_text(_CONTRACT_GEN_XML, encoding="utf-8")
    (bp_dir / "bp_craft_adp_core.xml").write_text(_BP_RECORD_XML, encoding="utf-8")
    (pool_dir / "bp_rewards_test.xml").write_text(_POOL_RECORD_XML, encoding="utf-8")
    _write_wearable(records, "armor/pu_armor/heavy/core/adp_core.xml",
                    "item_Name_adp_core", "item_Desc_adp_core", subtype="Heavy")
    return records


def _run_missions(gen, tmp_path, cfg=None, annotate=True, loc=None, forge_dir=None):
    ctx = {
        "records": _records(tmp_path),
        "forge_dir": forge_dir or (tmp_path / "forge"),
        "loc": loc if loc is not None else dict(_EN_LOC),
        "tag_loc": dict(_EN_LOC),
        "entity_names": {_ENTITY_UUID: "ADP-mk4 Core"},
        "reputation_lookup": {},
        "tag_configs": {"armor": cfg} if cfg is not None else {},
        "annotate_mission_descs": annotate,
    }
    return gen._run_gen_missions(ctx)


def _bullet_line(out: dict) -> str:
    body = out[_DESC_KEY]
    lines = [ln for ln in body.split("\\n") if ln.startswith("- ")]
    assert len(lines) == 1, body
    return lines[0]


class TestMissionBullets:
    def test_fixture_produces_a_blueprint_bullet(self, gen, tmp_path):
        out = _run_missions(gen, tmp_path)
        assert "POTENTIAL BLUEPRINTS" in out[_DESC_KEY]
        assert _bullet_line(out) == "- ADP-mk4 Core"

    def test_tagged_when_on(self, gen, tmp_path):
        out = _run_missions(gen, tmp_path, _armor_cfg())
        assert _bullet_line(out) == "- [H] ADP-mk4 Core"

    def test_style_follows_the_armor_config(self, gen, tmp_path):
        out = _run_missions(gen, tmp_path, _armor_cfg("med", enclosing="round", placement="append"))
        assert _bullet_line(out) == "- ADP-mk4 Core (HV)"

    @pytest.mark.parametrize("cfg,annotate", [(None, True), ("on", False)])
    def test_bare_when_off_or_unannotated(self, gen, tmp_path, cfg, annotate):
        cfg = {None: None, "on": _armor_cfg()}[cfg]
        out = _run_missions(gen, tmp_path, cfg, annotate=annotate)
        assert _bullet_line(out) == "- ADP-mk4 Core"

    def test_hand_edited_none_brackets_tag_as_square(self, gen, tmp_path):
        out = _run_missions(gen, tmp_path, _armor_cfg(enclosing="none"))
        assert _bullet_line(out) == "- [H] ADP-mk4 Core"

    def test_off_skips_the_wearables_scan(self, gen, tmp_path, monkeypatch):
        def _no_scan(*_a, **_k):
            raise AssertionError("scanned the wearables with the armor tag off")

        monkeypatch.setattr(gen, "build_wearable_index", _no_scan)
        out = _run_missions(gen, tmp_path, default_config("armor"))
        assert _bullet_line(out) == "- ADP-mk4 Core"

    def test_translated_run_keeps_the_english_tagged_bullet(self, gen, tmp_path):
        fr = {_TITLE_KEY: "Nettoyer l'avant-poste", _DESC_KEY: "Nettoyez l'avant-poste.",
              "item_Name_adp_core": "Noyau ADP-mk4", "item_Desc_adp_core": "Armure lourde."}
        out = _run_missions(gen, tmp_path, _armor_cfg(), loc=fr)
        assert _bullet_line(out) == "- [H] ADP-mk4 Core"

    def test_restyle_on_a_warm_cache_changes_bullets_not_the_pool_key(self, gen, tmp_path):
        forge_dir = tmp_path / "forge"
        pkl = forge_dir / ".lookups" / "blueprint_pools.pkl"
        lines, keys = [], []
        for cfg in (None, _armor_cfg(), _armor_cfg(enclosing="round", placement="append")):
            out = _run_missions(gen, tmp_path, cfg, forge_dir=forge_dir)
            lines.append(_bullet_line(out))
            with pkl.open("rb") as f:
                keys.append(pickle.load(f)[0])
        assert lines == ["- ADP-mk4 Core", "- [H] ADP-mk4 Core", "- ADP-mk4 Core (H)"]
        assert keys[0] == keys[1] == keys[2]
        with pkl.open("rb") as f:
            assert "[H]" not in repr(pickle.load(f)[1])


class TestMainLoadsWearablesOnce:
    @pytest.fixture
    def layout(self, tmp_path, gen):
        base_ini = tmp_path / "base.ini"
        base_ini.write_text("".join(f"{k}={v}\n" for k, v in _EN_LOC.items()), encoding="utf-8")
        forge_dir = tmp_path / "forge"
        records = forge_dir / gen.DATAFORGE_RECORDS_SUBPATH
        shutil.copytree(_records(tmp_path / "staging"), records)
        return base_ini, forge_dir

    def _spy(self, gen, monkeypatch):
        calls = []
        real = gen.build_wearable_index

        def _spy_index(*args, **kwargs):
            calls.append(args)
            return real(*args, **kwargs)

        monkeypatch.setattr(gen, "build_wearable_index", _spy_index)
        return calls

    def test_one_load_shared_by_both_generators(self, gen, layout, monkeypatch):
        base_ini, forge_dir = layout
        calls = self._spy(gen, monkeypatch)
        gen.main(base_ini, forge_dir, categories={"fps_weapon_descs", "mission_rewards"},
                 max_workers=2, tag_configs={"armor": _armor_cfg()})
        assert len(calls) == 1
        gear = gen.parse_ini(base_ini.parent / "fps_weapons_desc_enhancements.ini")
        assert gear["item_Name_adp_core"] == "[H] ADP-mk4 Core"
        missions = gen.parse_ini(base_ini.parent / "mission_rewards_enhancements.ini")
        assert "- [H] ADP-mk4 Core" in missions[_DESC_KEY]

    def test_missions_without_gear_still_tag_the_bullets(self, gen, layout):
        """Like component tags, the bullets follow the annotate toggle and the
        Missions enhancements, not the Gear checkbox."""
        base_ini, forge_dir = layout
        gen.main(base_ini, forge_dir, categories={"mission_rewards"}, max_workers=1,
                 tag_configs={"armor": _armor_cfg()})
        assert not (base_ini.parent / "fps_weapons_desc_enhancements.ini").exists()
        missions = gen.parse_ini(base_ini.parent / "mission_rewards_enhancements.ini")
        assert "- [H] ADP-mk4 Core" in missions[_DESC_KEY]

    def test_no_load_with_the_tag_off(self, gen, layout, monkeypatch):
        base_ini, forge_dir = layout
        calls = self._spy(gen, monkeypatch)
        gen.main(base_ini, forge_dir, categories={"fps_weapon_descs", "mission_rewards"},
                 max_workers=1)
        assert calls == []


class TestTrackerMatching:
    @pytest.mark.parametrize("enclosing", ["square", "round", "curly", "angle"])
    @pytest.mark.parametrize("placement", ["prepend", "append"])
    def test_owned_lands_after_a_tagged_bullet(self, enclosing, placement):
        from src.utils.tag_builder import join_tag, render_tag
        cfg = _armor_cfg(enclosing=enclosing, placement=placement)
        tagged = join_tag("ADP-mk4 Core", render_tag(cfg, {"weight": "Heavy"}), placement)
        cfgs = {cat: default_config(cat) for cat in CATEGORIES}
        cfgs["armor"] = cfg
        enclosings = enclosings_from_tag_configs(cfgs)
        value = ("Go.\\n\\n<EM3>POTENTIAL BLUEPRINTS</EM3>"
                 f"\\n- {tagged}\\n- ADP-mk4 Core Justified\\n\\n<EM3>MISSION DETAILS</EM3>")
        once = apply_owned_to_value(value, {"ADP-mk4 Core"}, enclosings)
        assert f"- {tagged} <EM4>[Owned]</EM4>" in once
        assert "- ADP-mk4 Core Justified\\n" in once
        assert apply_owned_to_value(once, {"ADP-mk4 Core"}, enclosings) == once

    def test_tagged_bullet_joins_its_armor_row(self):
        cfgs = {cat: default_config(cat) for cat in CATEGORIES}
        cfgs["armor"] = _armor_cfg()
        enclosings = enclosings_from_tag_configs(cfgs)
        desc = "x\\n<EM4>POTENTIAL BLUEPRINTS</EM4>\\n- [H] ADP-mk4 Core"
        entries = [
            type("E", (), {"key": "M_Desc_001", "original_value": desc,
                           "category": "Missions"})(),
            type("E", (), {"key": "item_Name_cds_heavy_armor_01_core",
                           "original_value": "[H] ADP-mk4 Core", "category": "Gear"})(),
        ]
        meta = build_blueprint_metadata(
            entries, enclosings,
            default_values={"item_Name_cds_heavy_armor_01_core": "ADP-mk4 Core"})
        # The manual and starter items are always folded in too, so check
        # only that the tagged bullet joined the bare row, with no tagged twin.
        assert not [name for name in meta
                    if "[H]" in name or ("ADP-mk4 Core" in name and name != "ADP-mk4 Core")]
        assert meta["ADP-mk4 Core"].type == "Armor"
        assert meta["ADP-mk4 Core"].tagged_name == "[H] ADP-mk4 Core"
