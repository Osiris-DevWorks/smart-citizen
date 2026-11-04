"""FPS armor weight-class tags (#492).

The Tag Builder's Armor category tags FPS armor, helmets, backpacks and
clothing with their weight class ("[H] ADP-mk4 Core"), using the same
element/style/mapping/separator/enclosing/placement machinery as the other
categories. Covers:

- ``_armor_weight``: the stock "Item Type:" line wins when it names a class
  (only it knows Super Heavy and Utility), then an armor slot's AttachDef
  SubType where it names a class, then Clothing for any clothing or
  accessory slot. Undersuits, flight suits and the racing and flight helmets
  with the plain "Helmet" SubType (most of them) get nothing; the few in a
  Light or Medium slot get that class.
- ``build_wearable_index`` and ``_run_gen_armor`` on fabricated entity XML:
  off by default, only ``item_Name*`` keys, base.ini's own key casing for
  both the name and the description, a fixed class order when entities share
  a name (whatever the file order), English descriptions for a translated
  base.ini, ``_short`` keys, and the user's style/mapping/enclosing/placement.
- ``main()`` writes the tags into ``fps_weapons_desc_enhancements.ini``, the
  Gear checkbox's existing file, so an upgrade adds no INI that the startup
  freshness check would report missing.
- The tag config defaults, the settings wiring, the Blueprint Tracker's
  enclosing set and the Armor page in the Tag Builder.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from src.utils.owned_items import enclosings_from_tag_configs  # noqa: E402
from src.utils.settings import AppSettings  # noqa: E402
from src.utils.tag_builder import (  # noqa: E402
    CATEGORIES, CATEGORY_ELEMENT_KINDS, DEFAULT_ARMOR_WEIGHT_MAPPING,
    DEFAULT_KIND_MAPPINGS, DEFAULT_TAG_CONFIGS, ELEMENT_LABELS,
    MAPPED_KIND_NAMES, STYLES_BY_KIND, ElementSpec, default_config, render_tag,
)

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def gen():
    script_path = REPO / "scripts" / "generate_enhancements_ini.py"
    spec = importlib.util.spec_from_file_location(
        "generate_enhancements_ini_armor_test", script_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _armor_cfg(style="short", **overrides):
    """The default Armor config with the Weight element ticked on, as a user
    does from the Tag Builder."""
    cfg = default_config("armor")
    cfg.elements = [ElementSpec("weight", True, style)]
    for attr, value in overrides.items():
        setattr(cfg, attr, value)
    return cfg


def _desc(item_type: str) -> str:
    return f"Manufacturer: CDS\\nItem Type: {item_type}\\nDamage Reduction: 30%\\n\\nLore text."


def _write_wearable(records: Path, rel: str, name: str, desc: str,
                    attach_type: str, subtype: str) -> None:
    path = records / "entities" / "scitem" / "characters" / "human" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'<EntityClassDefinition.{path.stem} __ref="00000000-0000-0000-0000-000000000000">'
        "<Components>"
        '<SAttachableComponentParams attachToTileItemPort="NoConnection">'
        f'<AttachDef Type="{attach_type}" SubType="{subtype}" Size="1" Grade="1">'
        f'<Localization Name="{name}" ShortName="@LOC_EMPTY" Description="{desc}"/>'
        "</AttachDef>"
        "</SAttachableComponentParams>"
        "</Components>"
        f"</EntityClassDefinition.{path.stem}>",
        encoding="utf-8",
    )


def _ctx(records: Path, forge_dir: Path, loc: dict, cfg=None, tag_loc=None) -> dict:
    return {
        "loc": loc,
        "tag_loc": tag_loc if tag_loc is not None else loc,
        "tag_configs": {"armor": cfg} if cfg is not None else {},
        "records": records,
        "forge_dir": forge_dir,
        "xml_path_index": None,
    }


@pytest.fixture
def cache(tmp_path):
    """A records tree plus a separate forge dir for the lookup pickles."""
    records = tmp_path / "records"
    records.mkdir()
    forge_dir = tmp_path / "forge"
    forge_dir.mkdir()
    return records, forge_dir


class TestArmorWeight:
    @pytest.mark.parametrize("item_type,expected", [
        ("Light Armor", "Light"),
        ("Medium Armor", "Medium"),
        ("Heavy Armor", "Heavy"),
        ("Super Heavy Armor", "Super Heavy"),
        ("Light Backpack", "Light"),
        ("Medium Backpack", "Medium"),
        ("Heavy Backpack", "Heavy"),
        ("Light Helmet", "Light"),
        ("Heavy Utility", "Utility"),
        ("Light Armor ", "Light"),  # CIG trailing-space variant
    ])
    def test_item_type_names_the_class(self, gen, item_type, expected):
        assert gen._armor_weight(_desc(item_type), "", "") == expected

    def test_item_type_beats_the_subtype(self, gen):
        # BUL-H4: Super Heavy is only in the description.
        assert gen._armor_weight(
            _desc("Super Heavy Armor"), "Char_Armor_Helmet", "Heavy") == "Super Heavy"
        # Novikov unified suit: an undersuit slot with SubType Heavy.
        assert gen._armor_weight(
            _desc("Heavy Utility"), "Char_Armor_Undersuit", "Heavy") == "Utility"
        # Ixonia Armor: armor sold in a clothing slot.
        assert gen._armor_weight(_desc("Heavy Armor"), "Char_Clothing_Torso_1", "Heavy") == "Heavy"

    def test_subtype_decides_when_the_item_type_names_no_class(self, gen):
        # A few racing helmets (the Interceptor ones) say "Racing Helmet" but
        # sit in a Light armor slot; most have the plain "Helmet" SubType.
        assert gen._armor_weight(_desc("Racing Helmet"), "Char_Armor_Helmet", "Light") == "Light"
        assert gen._armor_weight("", "Char_Armor_Torso", "Medium") == "Medium"
        assert gen._armor_weight("", "Char_Armor_Legs", "Heavy") == "Heavy"
        # Arden-CL backpacks spell it "LightArmor".
        assert gen._armor_weight("", "Char_Armor_Backpack", "LightArmor") == "Light"
        # The OMNI-AFS flight helmets say "Flight Helmet" but sit in a Light
        # armor slot: the game's own class wins, as for racing helmets.
        assert gen._armor_weight(_desc("Flight Helmet"), "Char_Armor_Helmet", "Light") == "Light"

    @pytest.mark.parametrize("desc,attach_type,subtype", [
        (_desc("Flight Helmet"), "Char_Armor_Helmet", "Helmet"),
        (_desc("Racing Helmet"), "Char_Armor_Helmet", "Helmet"),  # most of them
        (_desc("Undersuit"), "Char_Armor_Undersuit", "UNDEFINED"),
        (_desc("Racing Flight Suit"), "Char_Armor_Undersuit", "UNDEFINED"),
        (_desc("Ammo Carrier"), "Char_Armor_Backpack", "Personal"),
        ("", "Char_Armor_Torso", "UNDEFINED"),
        ("", "Char_Body", "Male"),
        ("", "Char_Head_Piercings", "UNDEFINED"),
        (_desc("Utility"), "", ""),  # multi-tools say plain "Utility"
    ])
    def test_no_weight_class(self, gen, desc, attach_type, subtype):
        assert gen._armor_weight(desc, attach_type, subtype) is None

    @pytest.mark.parametrize("attach_type", [
        "Char_Clothing_Torso_1", "Char_Clothing_Legs", "Char_Clothing_Feet",
        "Char_Clothing_Hat", "Char_Accessory_Eyes",
    ])
    def test_clothing_and_accessory_slots_are_clothing(self, gen, attach_type):
        desc = "A comfy item with no stats."
        assert gen._armor_weight(desc, attach_type, "UNDEFINED") == "Clothing"


class TestBuildWearableIndex:
    def test_reads_name_desc_and_attachdef(self, gen, cache):
        records, _ = cache
        _write_wearable(records, "armor/pu_armor/heavy/core/adp_core.xml",
                        "@item_Name_adp_core", "@item_Desc_adp_core", "Char_Armor_Torso", "Heavy")
        idx = gen.build_wearable_index(records / gen._WEARABLES_SUBPATH)
        assert idx == [("item_Name_adp_core", "item_Desc_adp_core", "Char_Armor_Torso", "Heavy")]

    def test_skips_sentinel_names_missing_attachdef_and_bad_xml(self, gen, cache):
        records, _ = cache
        _write_wearable(records, "armor/part.xml", "@LOC_PLACEHOLDER", "@LOC_PLACEHOLDER",
                        "AttachedPart", "UNDEFINED")
        no_attach = records / "entities" / "scitem" / "characters" / "human" / "armor" / "plain.xml"
        no_attach.write_text('<EntityClassDefinition.plain><Localization Name="@item_Name_x"/>'
                             "</EntityClassDefinition.plain>", encoding="utf-8")
        (no_attach.parent / "broken.xml").write_text("<not closed", encoding="utf-8")
        assert gen.build_wearable_index(records / gen._WEARABLES_SUBPATH) == []

    def test_missing_description_reads_as_empty(self, gen, cache):
        records, _ = cache
        _write_wearable(records, "clothing/hat.xml", "@item_Name_hat", "@LOC_EMPTY",
                        "Char_Clothing_Hat", "UNDEFINED")
        idx = gen.build_wearable_index(records / gen._WEARABLES_SUBPATH)
        assert idx == [("item_Name_hat", "", "Char_Clothing_Hat", "UNDEFINED")]


class TestRunGenArmor:
    def test_off_by_default_writes_nothing(self, gen, cache):
        records, forge_dir = cache
        _write_wearable(records, "armor/core.xml", "@item_Name_core", "@item_Desc_core",
                        "Char_Armor_Torso", "Heavy")
        loc = {"item_Name_core": "ADP-mk4 Core", "item_Desc_core": _desc("Heavy Armor")}
        assert gen._run_gen_armor(_ctx(records, forge_dir, loc)) == {}
        assert gen._run_gen_armor(_ctx(records, forge_dir, loc, default_config("armor"))) == {}

    def test_off_skips_the_scan(self, gen, cache, monkeypatch):
        records, forge_dir = cache
        (records / gen._WEARABLES_SUBPATH).mkdir(parents=True)

        def _no_scan(*_args, **_kwargs):
            raise AssertionError("scanned the wearables with the tag off")

        monkeypatch.setattr(gen, "build_wearable_index", _no_scan)
        assert gen._run_gen_armor(_ctx(records, forge_dir, {}, default_config("armor"))) == {}

    def test_tags_each_class(self, gen, cache):
        records, forge_dir = cache
        rows = [
            ("light", "Char_Armor_Arms", "Light", "Light Armor", "Field Recon Suit Arms"),
            ("medium", "Char_Armor_Legs", "Medium", "Medium Armor", "Aves Legs"),
            ("heavy", "Char_Armor_Torso", "Heavy", "Heavy Armor", "ADP-mk4 Core"),
            ("superheavy", "Char_Armor_Helmet", "Heavy", "Super Heavy Armor", "BUL-H4 Helmet"),
            ("utility", "Char_Armor_Helmet", "Heavy", "Heavy Utility", "Novikov Helmet"),
            ("jacket", "Char_Clothing_Torso_1", "UNDEFINED", None, "Legion Jacket"),
            ("flight", "Char_Armor_Helmet", "Helmet", "Flight Helmet", "A23 Flight Helmet"),
        ]
        loc = {}
        for stem, attach_type, subtype, item_type, name in rows:
            _write_wearable(records, f"x/{stem}.xml", f"@item_Name_{stem}", f"@item_Desc_{stem}",
                            attach_type, subtype)
            loc[f"item_Name_{stem}"] = name
            loc[f"item_Desc_{stem}"] = _desc(item_type) if item_type else "A jacket."
        out = gen._run_gen_armor(_ctx(records, forge_dir, loc, _armor_cfg()))
        assert out == {
            "item_Name_light": "[L] Field Recon Suit Arms",
            "item_Name_medium": "[M] Aves Legs",
            "item_Name_heavy": "[H] ADP-mk4 Core",
            "item_Name_superheavy": "[S] BUL-H4 Helmet",
            "item_Name_utility": "[U] Novikov Helmet",
            "item_Name_jacket": "[C] Legion Jacket",
        }

    def test_only_item_name_keys_are_tagged(self, gen, cache):
        """A few clothing records point their Name at shared item-port strings
        ("Body"), which must never change."""
        records, forge_dir = cache
        _write_wearable(records, "clothing/gown.xml", "@itemport_body_itemport", "@LOC_EMPTY",
                        "Char_Clothing_Torso_0", "Medical")
        loc = {"itemport_body_itemport": "Body"}
        assert gen._run_gen_armor(_ctx(records, forge_dir, loc, _armor_cfg())) == {}

    def test_name_and_description_keys_ignore_case(self, gen, cache):
        """Only the description says Super Heavy (the SubType says Heavy), so
        [S] proves the case-mismatched description key was found."""
        records, forge_dir = cache
        _write_wearable(records, "armor/helmet.xml", "@item_Name_bul_helmet",
                        "@item_desc_bul_helmet", "Char_Armor_Helmet", "Heavy")
        loc = {"Item_Name_bul_helmet": "BUL-H4 Helmet",
               "Item_Desc_bul_helmet": _desc("Super Heavy Armor")}
        out = gen._run_gen_armor(_ctx(records, forge_dir, loc, _armor_cfg()))
        assert out == {"Item_Name_bul_helmet": "[S] BUL-H4 Helmet"}

    def test_english_description_key_ignores_case_too(self, gen, cache):
        records, forge_dir = cache
        _write_wearable(records, "armor/helmet.xml", "@item_Name_nov", "@ITEM_DESC_NOV",
                        "Char_Armor_Helmet", "Heavy")
        loc = {"item_Name_nov": "Casque Novikov", "item_Desc_nov": "Casque."}
        tag_loc = {"item_Name_nov": "Novikov Helmet", "Item_Desc_Nov": _desc("Heavy Utility")}
        out = gen._run_gen_armor(_ctx(records, forge_dir, loc, _armor_cfg(), tag_loc=tag_loc))
        assert out == {"item_Name_nov": "[U] Casque Novikov"}

    def test_short_key_is_tagged_too(self, gen, cache):
        records, forge_dir = cache
        _write_wearable(records, "armor/core.xml", "@item_Name_core", "@item_Desc_core",
                        "Char_Armor_Torso", "Heavy")
        loc = {"item_Name_core": "ADP-mk4 Core", "item_Name_core_short": "ADP Core",
               "item_Desc_core": _desc("Heavy Armor")}
        out = gen._run_gen_armor(_ctx(records, forge_dir, loc, _armor_cfg()))
        assert out["item_Name_core_short"] == "[H] ADP Core"

    @pytest.mark.parametrize("clothing_first", [True, False])
    def test_armor_beats_clothing_on_a_shared_name(self, gen, cache, clothing_first):
        records, forge_dir = cache
        first, second = ("a", "b")
        clothing_stem, armor_stem = (first, second) if clothing_first else (second, first)
        _write_wearable(records, f"x/{clothing_stem}.xml", "@item_Name_shared", "@item_Desc_cloth",
                        "Char_Clothing_Torso_1", "UNDEFINED")
        _write_wearable(records, f"x/{armor_stem}.xml", "@item_Name_shared", "@item_Desc_armor",
                        "Char_Armor_Torso", "Medium")
        loc = {"item_Name_shared": "Ixonia Armor", "item_Desc_cloth": "A jacket.",
               "item_Desc_armor": _desc("Medium Armor")}
        out = gen._run_gen_armor(_ctx(records, forge_dir, loc, _armor_cfg()))
        assert out == {"item_Name_shared": "[M] Ixonia Armor"}

    @pytest.mark.parametrize("item_types,expected", [
        (("Heavy Armor", "Super Heavy Armor"), "[S]"),
        (("Heavy Armor", "Heavy Utility"), "[U]"),
        (("Light Armor", "Medium Armor"), "[M]"),
    ])
    @pytest.mark.parametrize("reverse", [False, True])
    def test_shared_name_class_does_not_depend_on_file_order(
            self, gen, cache, item_types, expected, reverse):
        records, forge_dir = cache
        loc = {"item_Name_shared": "Shared Helmet"}
        order = list(reversed(item_types)) if reverse else list(item_types)
        for i, item_type in enumerate(order):
            _write_wearable(records, f"x/{i}.xml", "@item_Name_shared", f"@item_Desc_{i}",
                            "Char_Armor_Helmet", "UNDEFINED")
            loc[f"item_Desc_{i}"] = _desc(item_type)
        out = gen._run_gen_armor(_ctx(records, forge_dir, loc, _armor_cfg()))
        assert out == {"item_Name_shared": f"{expected} Shared Helmet"}

    def test_translated_base_ini_reads_the_english_description(self, gen, cache):
        """A translated base.ini has no English "Item Type:" line. The class
        comes from the English description, the name from the translation."""
        records, forge_dir = cache
        _write_wearable(records, "armor/helmet.xml", "@item_Name_bul", "@item_Desc_bul",
                        "Char_Armor_Helmet", "Heavy")
        loc = {"item_Name_bul": "Casque BUL-H4",
               "item_Desc_bul": "Type d'objet : Armure super lourde"}
        tag_loc = {"item_Name_bul": "BUL-H4 Helmet", "item_Desc_bul": _desc("Super Heavy Armor")}
        out = gen._run_gen_armor(_ctx(records, forge_dir, loc, _armor_cfg(), tag_loc=tag_loc))
        assert out == {"item_Name_bul": "[S] Casque BUL-H4"}

    def test_empty_name_is_left_alone(self, gen, cache):
        records, forge_dir = cache
        _write_wearable(records, "armor/core.xml", "@item_Name_core", "@item_Desc_core",
                        "Char_Armor_Torso", "Heavy")
        loc = {"item_Name_core": "", "item_Desc_core": _desc("Heavy Armor")}
        assert gen._run_gen_armor(_ctx(records, forge_dir, loc, _armor_cfg())) == {}

    def test_user_style_mapping_enclosing_and_placement(self, gen, cache):
        records, forge_dir = cache
        _write_wearable(records, "armor/helmet.xml", "@item_Name_nov", "@item_Desc_nov",
                        "Char_Armor_Helmet", "Heavy")
        loc = {"item_Name_nov": "Novikov Helmet", "item_Desc_nov": _desc("Heavy Utility")}
        mapping = dict(DEFAULT_ARMOR_WEIGHT_MAPPING)
        mapping["Utility"] = ("H", "HV-U", "Heavy Utility")
        cfg = _armor_cfg("med", class_mapping=mapping, enclosing="round", placement="append")
        out = gen._run_gen_armor(_ctx(records, forge_dir, loc, cfg))
        assert out == {"item_Name_nov": "Novikov Helmet (HV-U)"}

    def test_no_wearables_folder(self, gen, cache):
        records, forge_dir = cache
        ctx = _ctx(records, forge_dir, {"item_Name_x": "X"}, _armor_cfg())
        assert gen._run_gen_armor(ctx) == {}


class TestMainWritesTheArmorIni:
    @pytest.fixture
    def layout(self, tmp_path, gen):
        base_ini = tmp_path / "base.ini"
        base_ini.write_text(
            "item_Name_core=ADP-mk4 Core\n"
            f"item_Desc_core={_desc('Heavy Armor')}\n",
            encoding="utf-8",
        )
        forge_dir = tmp_path / "forge"
        records = forge_dir / gen.DATAFORGE_RECORDS_SUBPATH
        records.mkdir(parents=True)
        _write_wearable(records, "armor/core.xml", "@item_Name_core", "@item_Desc_core",
                        "Char_Armor_Torso", "Heavy")
        return base_ini, forge_dir

    GEAR_INI = "fps_weapons_desc_enhancements.ini"

    def test_tag_on(self, gen, layout):
        base_ini, forge_dir = layout
        gen.main(base_ini, forge_dir, categories={"fps_weapon_descs"}, max_workers=1,
                 tag_configs={"armor": _armor_cfg()})
        out = gen.parse_ini(base_ini.parent / self.GEAR_INI)
        assert out == {"item_Name_core": "[H] ADP-mk4 Core"}

    def test_tag_off_leaves_the_names_out(self, gen, layout):
        base_ini, forge_dir = layout
        gen.main(base_ini, forge_dir, categories={"fps_weapon_descs"}, max_workers=1)
        out_path = base_ini.parent / self.GEAR_INI
        assert out_path.exists()
        assert "item_Name_core" not in gen.parse_ini(out_path)

    def test_not_generated_without_gear(self, gen, layout):
        base_ini, forge_dir = layout
        gen.main(base_ini, forge_dir, categories={"medical_consumables"}, max_workers=1,
                 tag_configs={"armor": _armor_cfg()})
        assert not (base_ini.parent / self.GEAR_INI).exists()
        written = "".join(p.read_text(encoding="utf-8") for p in base_ini.parent.glob("*.ini")
                          if p != base_ini)
        assert "ADP-mk4 Core" not in written


class TestTagConfigDefaults:
    def test_category_is_last_so_its_tab_is_rightmost(self):
        # The Tag Builder builds one tab per CATEGORIES entry, in order.
        assert CATEGORIES[-1] == "armor"
        assert CATEGORY_ELEMENT_KINDS["armor"] == ("weight",)

    def test_off_by_default_with_short_style(self):
        cfg = DEFAULT_TAG_CONFIGS["armor"]
        assert [(e.kind, e.enabled, e.style) for e in cfg.elements] == [("weight", False, "short")]
        assert (cfg.separator, cfg.enclosing, cfg.placement) == ("hyphen", "square", "prepend")
        assert cfg.class_mapping == DEFAULT_ARMOR_WEIGHT_MAPPING
        assert render_tag(cfg, {"weight": "Heavy"}) == ""

    def test_codes_from_the_issue(self):
        assert DEFAULT_ARMOR_WEIGHT_MAPPING == {
            "Light": ("L", "LT", "Light"),
            "Medium": ("M", "MD", "Medium"),
            "Heavy": ("H", "HV", "Heavy"),
            "Super Heavy": ("S", "SH", "Super Heavy"),
            "Utility": ("U", "UT", "Utility"),
            "Clothing": ("C", "CL", "Clothing"),
        }

    @pytest.mark.parametrize("style,expected", [
        ("short", "[H]"), ("med", "[HV]"), ("long", "[Heavy]"),
    ])
    def test_each_style_renders(self, style, expected):
        assert render_tag(_armor_cfg(style), {"weight": "Heavy"}) == expected

    def test_weight_is_a_mapped_kind_with_styles_and_a_label(self):
        assert "weight" in MAPPED_KIND_NAMES
        assert DEFAULT_KIND_MAPPINGS["weight"] is DEFAULT_ARMOR_WEIGHT_MAPPING
        assert [k for k, _ in STYLES_BY_KIND["weight"]] == ["short", "med", "long"]
        assert ELEMENT_LABELS["weight"] == "Weight"

    def test_default_config_is_a_fresh_copy(self):
        cfg = default_config("armor")
        cfg.elements[0].enabled = True
        cfg.class_mapping["Heavy"] = ("X", "X", "X")
        assert DEFAULT_TAG_CONFIGS["armor"].elements[0].enabled is False
        assert DEFAULT_TAG_CONFIGS["armor"].class_mapping["Heavy"] == ("H", "HV", "Heavy")

    def test_fingerprint_counts_armor_only_while_its_tag_is_on(self):
        """An Armor tag that is off shapes no output, so it must not change
        the Save Tag Changes fingerprint, or every pre-#492 stamp would read
        stale after upgrading."""
        from src.utils.tag_builder import tag_config_fingerprint
        cfgs = {cat: default_config(cat) for cat in CATEGORIES}
        pre_armor = {cat: cfg for cat, cfg in cfgs.items() if cat != "armor"}
        assert tag_config_fingerprint(cfgs, True) == tag_config_fingerprint(pre_armor, True)
        cfgs["armor"].enclosing = "round"  # restyled while off: still nothing
        assert tag_config_fingerprint(cfgs, True) == tag_config_fingerprint(pre_armor, True)
        cfgs["armor"] = _armor_cfg()
        assert tag_config_fingerprint(cfgs, True) != tag_config_fingerprint(pre_armor, True)


class TestSettingsWiring:
    def test_armor_tags_add_no_enhancement_file(self):
        """The tags ride in the Gear checkbox's existing INI. A file of their
        own would be missing for everyone right after upgrading, and the
        startup freshness check would then ask every Gear user to regenerate
        for a tag that is off by default."""
        assert AppSettings.ENHANCEMENT_CATEGORY_FILES["gear"] == ["fps_weapon_descs"]
        assert not any("armor" in key or "armor" in name
                       for key, name in AppSettings.ENHANCEMENTS_FILES.items())

    def test_profile_defaults_cover_the_armor_config(self):
        assert "tag_builder/armor/config" in AppSettings.profile_default_values()

    def test_blueprint_tracker_strips_an_armor_only_enclosing(self):
        """Armor pieces are blueprint rewards, so an armor tag in Round
        brackets must still be stripped back off the item name."""
        cfgs = {cat: default_config(cat) for cat in CATEGORIES}
        cfgs["armor"] = _armor_cfg(enclosing="round")
        assert ("(", ")") in enclosings_from_tag_configs(cfgs)

    def test_armor_enclosing_ignored_while_the_tag_is_off(self):
        cfgs = {cat: default_config(cat) for cat in CATEGORIES}
        cfgs["armor"].enclosing = "round"
        assert ("(", ")") not in enclosings_from_tag_configs(cfgs)

    def test_stored_armor_none_brackets_load_as_square(self, tmp_path):
        """The Armor tab offers no None brackets; an imported or hand-edited
        config that says "none" loads as Square."""
        from src.utils.json_settings import JsonSettings
        saved = AppSettings._backend
        AppSettings._backend = JsonSettings(tmp_path / "config.json")
        try:
            AppSettings.set_tag_config("armor", _armor_cfg(enclosing="none"))
            assert AppSettings.get_tag_config("armor").enclosing == "square"
            cfg = default_config("components")
            cfg.enclosing = "none"
            AppSettings.set_tag_config("components", cfg)
            assert AppSettings.get_tag_config("components").enclosing == "none"
        finally:
            AppSettings._backend = saved

    @pytest.mark.parametrize("on", [False, True])
    def test_armor_none_never_adds_the_space_only_pair(self, on):
        """The None pair switches on the space-only heuristic for everybody,
        and that heuristic could not strip a one-word armor tag anyway."""
        cfgs = {cat: default_config(cat) for cat in CATEGORIES}
        cfgs["armor"] = _armor_cfg(enclosing="none") if on else default_config("armor")
        cfgs["armor"].enclosing = "none"
        assert ("", "") not in enclosings_from_tag_configs(cfgs)

    def test_other_categories_none_still_counts(self):
        cfgs = {cat: default_config(cat) for cat in CATEGORIES}
        cfgs["components"].enclosing = "none"
        assert ("", "") in enclosings_from_tag_configs(cfgs)


class TestArmorPage:
    @pytest.fixture
    def page(self, qapp):
        from src.gui.enhancements_tab import _TagBuilderPage
        return _TagBuilderPage("armor", default_config("armor"))

    def test_tab_label_and_preview_samples_exist(self):
        from src.gui.enhancements_tab import _CATEGORY_LABELS, _PREVIEW_NAMES, _PREVIEW_VALUES
        assert _CATEGORY_LABELS["armor"] == "Armor"
        assert _PREVIEW_VALUES["armor"] == {"weight": "Heavy"}
        assert _PREVIEW_NAMES["armor"]
        # Every category the Tag Builder builds a tab for has a label.
        assert set(CATEGORIES) <= set(_CATEGORY_LABELS)

    def test_armor_is_the_rightmost_tab(self, qapp, tmp_path):
        from src.gui.enhancements_tab import EnhancementsTab
        from src.utils.json_settings import JsonSettings
        saved = AppSettings._backend
        AppSettings._backend = JsonSettings(tmp_path / "config.json")
        try:
            AppSettings.set_user_data_dir(tmp_path / "data")
            tab = EnhancementsTab()
            tabs = tab._tag_builder_tabs
            labels = [tabs.tabText(i) for i in range(tabs.count())]
            tab.deleteLater()
        finally:
            AppSettings._backend = saved
        assert labels == ["Components", "Missiles", "Ship Weapons", "Commodities",
                          "Mission Titles", "Armor"]

    def test_standard_controls(self, page):
        assert [r.spec.kind for r in page._rows] == ["weight"]
        row = page._rows[0]
        assert row.edit_btn is not None
        assert [row.style_combo.itemData(i) for i in range(row.style_combo.count())] == [
            "short", "med", "long"]
        assert row.style_combo.itemText(0) == "Short (H)"
        assert page.sep_combo.count() > 1
        assert page.enc_combo.count() > 1
        assert page.placement_combo.count() == 2
        assert page.usage_sep_combo is None

    def test_no_none_brackets_on_the_armor_tab_only(self, page, qapp):
        """A known limitation: without brackets the Blueprint Tracker could
        not strip a one-word armor tag back off a Game.log name."""
        from src.gui.enhancements_tab import _TagBuilderPage
        keys = [page.enc_combo.itemData(i) for i in range(page.enc_combo.count())]
        assert "none" not in keys
        assert keys[0] == "square"
        other = _TagBuilderPage("components", default_config("components"))
        assert "none" in [other.enc_combo.itemData(i) for i in range(other.enc_combo.count())]

    def test_mapping_tooltip_is_the_weight_one(self, page):
        from src.utils.i18n import tr
        row = page._rows[0]
        assert row._mapping_tooltip_key("weight") == "enhancements.tag_mapping_tooltip_weight"
        assert row.edit_btn.toolTip() == tr("enhancements.tag_mapping_tooltip_weight")
        assert "weight class" in tr("enhancements.tag_mapping_tooltip_weight")

    def test_ticking_weight_previews_the_tag_and_marks_dirty(self, page):
        fired = []
        page.config_changed.connect(lambda: fired.append(True))
        assert "[H]" not in page.preview_label.text()
        page._rows[0].enable_cb.setChecked(True)
        assert fired
        assert "[H] ADP-mk4 Core" in page.preview_label.text()
        page.placement_combo.setCurrentIndex(page.placement_combo.findData("append"))
        assert "ADP-mk4 Core [H]" in page.preview_label.text()

    def test_reset_turns_it_back_off(self, page):
        page._rows[0].enable_cb.setChecked(True)
        page._reset_to_defaults()
        assert page.config.elements[0].enabled is False
        assert page._rows[0].enable_cb.isChecked() is False
