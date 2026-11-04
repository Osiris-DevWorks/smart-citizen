"""Perf proposal: the enhancement generator reads the DataForge XMLs as few
times as it can (each pu_missions and contractgen XML once, where it used to
read them up to five times), and its lookup pickles hold XML
facts rather than text rendered from the loc file and the Tag Builder
config, all without changing a byte of what it writes.

* The scitem lookup (~24k files) and the blueprint pools cache only XML
  facts per DataForge build; names and [CLASS-Sx-grade] tags are rendered
  from them on every run, so a Tag Builder change no longer re-parses
  every scitem XML. ``_component_name_tag`` and the mining-laser tagger
  share one implementation with that cached path. A frozen copy of the
  pre-split scitem walk and component tagger is the oracle here.
* The scitem walk finds the magazine with lxml's tag filter when a file
  holds no ``__polymorphicType`` attribute, and keeps the per-element loop
  otherwise.
* _run_gen_missions parses each pu_missions XML once (it was five passes),
  each contractgen XML once and the contract templates once (three and two
  passes), with each step's own error handling. The titles it writes from
  the pu_missions pass ([BP] / [BP?], the orphan drop, pu-only routes and
  XP, the "titles skipped" count) are checked end to end.
* scan_crafting_blueprints parses each blueprint once, reads a carryable
  only when its filename names a commodity, and lowercases the loc keys
  once per scan rather than once per commodity (the SCO crafting index's
  names included).
* The flight controller and armour lookups keep values, not lxml trees, and
  an armour value that cannot be formatted still fails only its ship. They
  are not pickled, so a patched XML shows on the next run.
* _build_xml_path_index works out each folder's key once, not per file.

The whole-output proof (every file the generator writes byte-identical on a
real LIVE cache, cold, warm, after a components change and with non-default
configs) was run by hand; see scripts/CLAUDE.md.
"""
from __future__ import annotations

import importlib.util
import io
import logging
import pathlib
import pickle
import re
import sys
from collections import defaultdict
from pathlib import Path

import pytest
from lxml import etree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.fixture(scope="module")
def gen_module():
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "generate_enhancements_ini.py"
    spec = importlib.util.spec_from_file_location(
        "generate_enhancements_ini_single_pass_test", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _write(path: Path, text: str, encoding: str = "utf-8") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode(encoding))
    return path


class _ParseCounter:
    """Counts parses per file, through both the generator's
    _parse_xml_file and lxml's own parse."""

    def __init__(self, gen_module, monkeypatch):
        self.counts: dict[str, int] = defaultdict(int)
        real_file = gen_module._parse_xml_file
        real_parse = gen_module.ET.parse

        def counted_file(xml_file):
            self.counts[Path(xml_file).name] += 1
            return real_file(xml_file)

        def counted_parse(source, *args, **kwargs):
            self.counts[Path(source).name] += 1
            return real_parse(source, *args, **kwargs)

        monkeypatch.setattr(gen_module, "_parse_xml_file", counted_file)
        monkeypatch.setattr(gen_module.ET, "parse", counted_parse)


class _BuiltinsOnly(pickle.Unpickler):
    """Refuses every global, so a load proves the pickle holds builtins
    only and loads whatever name the generator module was loaded under."""

    def find_class(self, module, name):
        raise pickle.UnpicklingError(f"pickle names {module}.{name}")


def _load_builtins_only(pkl: Path):
    return _BuiltinsOnly(io.BytesIO(pkl.read_bytes())).load()


# ── Frozen copies of the pre-split code, the oracle for the scitem tests ─────

_OLD_SENTINELS = frozenset({
    "LOC_BADSTRING", "LOC_BADTOKEN", "LOC_DEBUG", "LOC_EMPTY", "LOC_INVALID",
    "LOC_NOINNERTHOUGHT", "LOC_PLACEHOLDER", "LOC_UNINITIALIZED",
})


def _old_component_name_tag(gen, desc_value, root=None, config=None, component_type=""):
    """_component_name_tag before the facts split (the XML reads inline)."""
    attach_def = None
    attach_grade_letter = None
    attach_class_name = None
    if root is not None:
        attach_el = gen._find(root, "SAttachableComponentParams")
        if attach_el is not None:
            attach_def = attach_el.find("AttachDef")
    size_m = gen._SIZE_LINE_RE.search(desc_value)
    size = size_m.group(1) if size_m else None
    if size is None and root is not None:
        root_tag = root.tag.split(".")[-1] if "." in root.tag else root.tag
        xml_size = gen._extract_item_size(root_tag)
        if xml_size:
            size = xml_size.lstrip("S")
    if size is None and root is not None:
        name_key = gen._loc_name_key(root)
        if name_key:
            key_size = gen._extract_item_size(name_key)
            if key_size:
                size = key_size.lstrip("S")
    if size is None and attach_def is not None:
        raw_size = attach_def.get("Size", "")
        if raw_size.isdigit():
            size = raw_size
    if size is None:
        return None
    grade_m = re.search(r"Grade:\s*([A-D])", desc_value)
    class_m = re.search(r"Class:\s*(\w+)", desc_value)
    if not grade_m and attach_def is not None:
        num_grade = attach_def.get("Grade", "")
        if num_grade.isdigit():
            g_idx = int(num_grade) - 1
            if 0 <= g_idx <= 3:
                attach_grade_letter = "ABCD"[g_idx]
    if not class_m and attach_def is not None:
        subtype = attach_def.get("SubType", "")
        if subtype:
            attach_class_name = re.sub(r"([a-z])([A-Z])", r"\1 \2", subtype)
    grade_letter = (grade_m.group(1) if grade_m else None) or attach_grade_letter
    class_name = (class_m.group(1) if class_m else None) or attach_class_name
    xml_item_type = None
    if not class_name and root is not None:
        icp = gen._find(root, "ItemComponentParams")
        if icp is not None:
            xml_item_type = re.sub(r"([a-z])([A-Z])", r"\1 \2", icp.get("itemType", ""))
    if grade_letter and class_name and class_name in gen.DEFAULT_COMPONENT_CLASS_MAPPING:
        cfg = config or gen.DEFAULT_TAG_CONFIGS.get("components")
        values = {"class": class_name, "size": size, "grade": grade_letter}
        if component_type:
            values["type"] = component_type
        out = gen.render_tag(cfg, values)
        if out:
            return out
        abbrev_tuple = gen.DEFAULT_COMPONENT_CLASS_MAPPING.get(class_name)
        if abbrev_tuple:
            return f"[{abbrev_tuple[1]}-S{size}-{grade_letter}]"
    type_abbrev = None
    type_m = re.search(r"Item Type:\s*([^\\\n]+?)\s*(?:\\n|\n|$)", desc_value)
    if type_m:
        type_abbrev = gen._ITEM_TYPE_ABBREV.get(type_m.group(1).strip())
    if not type_abbrev and xml_item_type:
        type_abbrev = gen._ITEM_TYPE_ABBREV.get(xml_item_type)
    if not type_abbrev and class_name:
        type_abbrev = gen._ITEM_TYPE_ABBREV.get(class_name)
    if not type_abbrev:
        return None
    parts = [type_abbrev, f"S{size}"]
    if grade_letter:
        parts.append(grade_letter)
    return f"[{'-'.join(parts)}]"


def _old_mining_laser_component_tag(gen, desc_value, root, mining_tag_cfg):
    """_mining_laser_component_tag before the name split."""
    if mining_tag_cfg is None or root is None:
        return None
    if gen._find(root, "SEntityComponentMiningLaserParams") is None:
        return None
    size = None
    m = re.search(r"_S0*(\d+)_", root.get("Name") or root.get("name") or "")
    if m:
        size = str(int(m.group(1)))
    if not size:
        ds = gen._SIZE_LINE_RE.search(desc_value)
        if ds:
            size = ds.group(1)
    return gen.render_tag(mining_tag_cfg, {"type": "Mining Laser", "size": size or ""}) or None


def _old_build_scitem_lookups(gen, scitem_dir, loc, tag_config):
    """build_scitem_lookups before the facts split: one walk that rendered
    names and tags as it went, magazine found by _poly_type per element."""
    mag_lookup, entity_names, by_filename, tags = {}, {}, {}, {}
    mining_tag_cfg = gen._build_mining_laser_tag_cfg(tag_config)
    null_uuid = "00000000-0000-0000-0000-000000000000"
    for xml_file in scitem_dir.rglob("*.xml"):
        try:
            root = ET.parse(xml_file).getroot()
        except ET.ParseError:
            continue
        ref = root.get("__ref", "")
        entity_name = root.tag.split(".")[-1] if "." in root.tag else xml_file.stem
        found_mag = found_name = found_desc = False
        resolved = None
        desc_loc_key = None
        for elem in root.iter():
            if not found_mag and (elem.get("__polymorphicType") or elem.tag) == gen._MAGAZINE_TYPE:
                ammo_ref = elem.get("ammoParamsRecord", "")
                if ammo_ref and ammo_ref != null_uuid:
                    mag_lookup[entity_name] = (ammo_ref, elem.get("maxAmmoCount", ""))
                found_mag = True
            if not found_name:
                name_attr = elem.get("Name", "")
                if name_attr and name_attr.startswith("@"):
                    resolved = loc.get(name_attr.lstrip("@"), name_attr.lstrip("@"))
                    if ref:
                        entity_names[ref] = resolved
                    found_name = True
            if not found_desc:
                desc_attr = elem.get("Description", "")
                if (desc_attr and desc_attr.startswith("@")
                        and desc_attr.lstrip("@") not in _OLD_SENTINELS):
                    desc_loc_key = desc_attr.lstrip("@")
                    found_desc = True
            if found_mag and found_name and found_desc:
                break
        if resolved:
            by_filename[xml_file.stem.lower()] = resolved
        if ref and desc_loc_key:
            desc_value = loc.get(desc_loc_key, "")
            parts = {p.lower() for p in xml_file.parts}
            is_mining = "weapons" in parts and gen._find(
                root, "SEntityComponentMiningLaserParams") is not None
            if desc_value and ("weapons" not in parts or is_mining):
                if is_mining:
                    tag = _old_mining_laser_component_tag(gen, desc_value, root, mining_tag_cfg)
                else:
                    comp_type = next(
                        (t for sd, t in gen._SUBDIR_TO_TYPE.items() if sd in parts), "")
                    tag = _old_component_name_tag(gen, desc_value, root, tag_config, comp_type)
                    if not tag:
                        tag = gen._bare_type_tag_from_desc(desc_value, tag_config)
                if tag and not gen._TYPELESS_COMPONENT_TAG_RE.search(tag):
                    tags[ref] = tag
    return mag_lookup, entity_names, by_filename, tags


# ── A scitem tree that reaches every branch of the walk ──────────────────────

_MAG = "SAmmoContainerComponentParams"


def _ref(n: int) -> str:
    """The __ref of the n-th entity _scitem_tree writes."""
    return f"11111111-0000-0000-0000-00000000000{n}"


def _entity(cls, ref, body, name_attr=""):
    ref_attr = f' __ref="{ref}"' if ref else ""
    return (f'<EntityClassDefinition.{cls}{ref_attr}{name_attr}><Components>{body}'
            f'</Components></EntityClassDefinition.{cls}>')


def _scitem_tree(root: Path) -> dict[str, str]:
    """Write the scitem fixture under *root* and return its English loc."""
    s = root / "ships"
    _write(s / "shieldgenerator" / "shld_strict.xml", _entity(
        "SHLD_GODI_S02_Strict_SCItem", "11111111-0000-0000-0000-000000000001",
        '<SAttachableComponentParams><AttachDef Size="2" Grade="1" SubType="UNDEFINED">'
        '<Localization Name="@nm_strict" Description="@ds_strict"/></AttachDef>'
        '</SAttachableComponentParams>'))
    # Size from the class name, grade from AttachDef, type from ItemComponentParams.
    _write(s / "shieldgenerator" / "shld_facts.xml", _entity(
        "SHLD_GODI_S03_Facts_SCItem", "11111111-0000-0000-0000-000000000002",
        '<SAttachableComponentParams><AttachDef Size="9" Grade="2" SubType="">'
        '<Localization Name="@nm_facts" Description="@ds_facts"/></AttachDef>'
        '</SAttachableComponentParams><ItemComponentParams itemType="ShieldGenerator"/>'))
    # Size only from the AttachDef, class from its SubType.
    _write(s / "bombcompartments" / "brk_attach.xml", _entity(
        "BRK_Attach", "11111111-0000-0000-0000-000000000003",
        '<SAttachableComponentParams><AttachDef Size="4" Grade="3" SubType="BombRack">'
        '<Localization Name="@nm_attach" Description="@ds_attach"/></AttachDef>'
        '</SAttachableComponentParams>'))
    # Size only from the item_Name loc key; a typeless tag the lookup drops.
    _write(s / "cooler" / "cool_namekey.xml", _entity(
        "COOL_NameKey", "11111111-0000-0000-0000-000000000004",
        '<SAttachableComponentParams><AttachDef Grade="4">'
        '<Localization Name="@item_NameCOOL_X_S01_Key" Description="@ds_namekey"/></AttachDef>'
        '</SAttachableComponentParams>'))
    # A sentinel description first, the real one later in the document.
    _write(s / "radar" / "radr_sentinel.xml", _entity(
        "RADR_X_S01_Sentinel", "11111111-0000-0000-0000-000000000005",
        '<A Description="@LOC_EMPTY"/><B Name="@nm_radar"/>'
        '<SAttachableComponentParams><AttachDef Size="1" Grade="1">'
        '<Localization Description="@ds_radar"/></AttachDef></SAttachableComponentParams>'))
    _write(root / "misc" / "nozzle.xml", _entity(
        "nozzle", "11111111-0000-0000-0000-000000000006",
        '<SItemComponentParams Name="@nm_nozzle" Description="@ds_nozzle"/>'))
    _write(s / "weapons" / "mininglaser.xml", _entity(
        "Mining_Laser_S2_Test", "11111111-0000-0000-0000-000000000007",
        '<SItemComponentParams Name="@nm_ml" Description="@ds_ml"/>'
        '<SEntityComponentMiningLaserParams/>', name_attr=' Name="MINING_S02_Laser"'))
    _write(root / "weapons" / "fps_weapons" / "rifle.xml", _entity(
        "rifle", "11111111-0000-0000-0000-000000000008",
        '<SItemComponentParams Name="@nm_rifle" Description="@ds_rifle"/>'
        f'<{_MAG} ammoParamsRecord="aaaa0000-0000-0000-0000-000000000001" maxAmmoCount="30"/>'))
    # Magazines: the attribute form, an element whose tag says magazine but
    # whose polymorphic type does not, and a null record.
    _write(root / "weapons" / "magazines" / "mag_poly.xml", _entity(
        "mag_poly", "",
        f'<{_MAG} __polymorphicType="Other"'
        ' ammoParamsRecord="bbbb0000-0000-0000-0000-000000000001"/>'
        f'<Base __polymorphicType="{_MAG}" maxAmmoCount="12"'
        ' ammoParamsRecord="bbbb0000-0000-0000-0000-000000000002"/>'
        '<SItemComponentParams Name="@nm_mag"/>'))
    _write(root / "weapons" / "magazines" / "mag_null.xml", _entity(
        "mag_null", "11111111-0000-0000-0000-000000000009",
        f'<{_MAG} ammoParamsRecord="00000000-0000-0000-0000-000000000000" maxAmmoCount="5"/>'
        '<SItemComponentParams Name="@"/>'))
    # A name that does not resolve, no ref, a file lxml cannot parse.
    _write(root / "misc" / "unresolved.xml", _entity(
        "unresolved", "", '<SItemComponentParams Name="@nm_missing"/>'))
    _write(root / "misc" / "broken.xml", "<EntityClassDefinition.broken><oops>")
    return {
        "nm_strict": "Strict Shield",
        "ds_strict": "Item Type: Shield Generator\\nSize: 2\\nGrade: A\\nClass: Military",
        "nm_facts": "Facts Shield", "ds_facts": "Item Type: Shield Generator\\n",
        "nm_attach": "Attach Rack", "ds_attach": "Manufacturer: X\\n",
        "item_NameCOOL_X_S01_Key": "Key Cooler", "ds_namekey": "Manufacturer: Y\\n",
        "nm_radar": "Sentinel Radar",
        "ds_radar": "Item Type: Radar\\nSize: 1\\nGrade: B\\nClass: Civilian",
        "nm_nozzle": "RN-7s", "ds_nozzle": "Manufacturer: MISC\\nItem Type: Fuel Nozzle\\n",
        "nm_ml": "Helix II", "ds_ml": "Item Type: Mining Laser\\nSize: 2\\n",
        "nm_rifle": "P4-AR", "ds_rifle": "Size: 3 Grade: A Class: Military",
        "nm_mag": "P4-AR Magazine",
    }


def _custom_components_cfg(gen):
    from src.utils.tag_builder import DEFAULT_TAG_CONFIGS
    return gen.TagConfig(
        elements=[
            gen.ElementSpec("type", True, "long"),
            gen.ElementSpec("grade", True, "grade_letter"),
            gen.ElementSpec("class", True, "long"),
            gen.ElementSpec("size", True, "size_n"),
        ],
        separator="pipe", enclosing="round", placement="append",
        class_mapping=dict(DEFAULT_TAG_CONFIGS["components"].class_mapping),
    )


def _size_grade_cfg(gen):
    """Class and type off: the strict tags come out typeless ("[S2-A]"),
    which the lookup drops (#160)."""
    from src.utils.tag_builder import DEFAULT_TAG_CONFIGS
    default = DEFAULT_TAG_CONFIGS["components"]
    return gen.TagConfig(
        elements=[
            gen.ElementSpec("class", False, "med"),
            gen.ElementSpec("size", True, "sn"),
            gen.ElementSpec("grade", True, "letter"),
            gen.ElementSpec("type", False, "short"),
        ],
        separator=default.separator, enclosing=default.enclosing,
        class_mapping=dict(default.class_mapping),
    )


def _components_config(gen, name):
    if name == "default":
        return gen.DEFAULT_TAG_CONFIGS["components"]
    if name == "custom":
        return _custom_components_cfg(gen)
    return _size_grade_cfg(gen)


def _items(lookups):
    """The four lookups as ordered item lists, so insertion order counts."""
    return tuple(list(d.items()) for d in lookups)


class TestScitemFactsMatchTheSingleWalk:
    """The facts walk plus the per-run render give exactly what the old
    single walk gave: same entries, same insertion order, every config."""

    @pytest.mark.parametrize("config", ["default", "custom", "size_grade"])
    def test_lookups_match_the_pre_split_walk(self, gen_module, tmp_path, config):
        loc = _scitem_tree(tmp_path)
        cfg = _components_config(gen_module, config)
        new = gen_module.build_scitem_lookups(tmp_path, loc=loc, tag_config=cfg)
        old = _old_build_scitem_lookups(gen_module, tmp_path, loc, cfg)
        assert _items(new) == _items(old)
        # The fixture reaches the branches it is meant to.
        mags, names, by_file, tags = new
        assert mags == {"rifle": ("aaaa0000-0000-0000-0000-000000000001", "30"),
                        "mag_poly": ("bbbb0000-0000-0000-0000-000000000002", "12")}
        assert names["11111111-0000-0000-0000-000000000009"] == ""
        assert by_file["unresolved"] == "nm_missing"
        assert tags[_ref(2)] == "[SHLD-S3-B]"   # size, grade and type from the XML
        assert tags[_ref(3)] == "[BRK-S4-C]"    # size and class from the AttachDef
        if config == "custom":                   # Type on: mining laser and nozzle
            assert _ref(6) in tags and _ref(7) in tags
        if config == "size_grade":               # typeless strict tags are dropped
            assert _ref(1) not in tags and _ref(5) not in tags
        else:
            assert _ref(1) in tags and _ref(5) in tags

    def test_component_tag_from_facts_matches_the_live_root_tagger(self, gen_module, tmp_path):
        loc = _scitem_tree(tmp_path)
        cfgs = [None] + [_components_config(gen_module, n)
                         for n in ("default", "custom", "size_grade")]
        descs = [v for k, v in loc.items() if k.startswith("ds_")] + ["", "Size: 3"]
        checked = 0
        for xml_file in sorted(tmp_path.rglob("*.xml")):
            try:
                root = ET.parse(xml_file).getroot()
            except ET.ParseError:
                continue
            for desc in descs:
                for cfg in cfgs:
                    for comp_type in ("", "Shield Generator"):
                        old = _old_component_name_tag(gen_module, desc, root, cfg, comp_type)
                        assert gen_module._component_name_tag(desc, root, cfg, comp_type) == old
                        facts = gen_module._component_tag_facts(root)
                        assert gen_module._component_name_tag_from_facts(
                            desc, facts, cfg, comp_type) == old
                        checked += 1
        assert checked > 300
        # No root: the description alone.
        for desc in descs:
            assert gen_module._component_name_tag(desc) == _old_component_name_tag(gen_module, desc)


class TestScitemFactsCache:
    """With forge_dir the walk is pickled once per DataForge build and every
    Tag Builder config renders from it."""

    def test_a_components_change_renders_from_the_cached_walk(
            self, gen_module, tmp_path, monkeypatch):
        loc = _scitem_tree(tmp_path / "scitem")
        forge = tmp_path / "forge"
        forge.mkdir()
        (forge / ".p4k_mtime").write_text("12345", encoding="utf-8")
        real = gen_module._scitem_facts
        calls = []
        monkeypatch.setattr(gen_module, "_scitem_facts",
                            lambda *a, **k: calls.append(1) or real(*a, **k))
        default_cfg = gen_module.DEFAULT_TAG_CONFIGS["components"]
        custom_cfg = _custom_components_cfg(gen_module)
        first = gen_module.build_scitem_lookups(tmp_path / "scitem", loc, tag_config=default_cfg,
                                                forge_dir=forge)
        second = gen_module.build_scitem_lookups(tmp_path / "scitem", loc, tag_config=custom_cfg,
                                                 forge_dir=forge)
        assert len(calls) == 1, "a Tag Builder change re-parsed the scitem XMLs"
        assert _items(first) == _items(
            _old_build_scitem_lookups(gen_module, tmp_path / "scitem", loc, default_cfg))
        assert _items(second) == _items(
            _old_build_scitem_lookups(gen_module, tmp_path / "scitem", loc, custom_cfg))
        assert first[3] != second[3]

    def test_the_pickle_holds_builtins_only(self, gen_module, tmp_path):
        loc = _scitem_tree(tmp_path / "scitem")
        forge = tmp_path / "forge"
        forge.mkdir()
        gen_module.build_scitem_lookups(tmp_path / "scitem", loc, forge_dir=forge)
        key, facts = _load_builtins_only(forge / ".lookups" / "scitem_lookups.pkl")
        assert key.startswith(gen_module._LOOKUP_VERSIONS["scitem_lookups"] + ":")
        assert facts == gen_module._scitem_facts(tmp_path / "scitem")


class TestMagazineFastPath:
    def test_only_ascii_compatible_files_without_the_attribute_qualify(self, gen_module):
        ok = gen_module._holds_no_poly_type_attr
        assert ok(b'<A x="1"/>')
        assert ok(b'\xef\xbb\xbf<?xml version="1.0"?><A/>')
        assert ok(b'\r\n  <A/>')
        assert not ok(b'<A __polymorphicType="B"/>')
        assert not ok('<A x="1"/>'.encode("utf-16"))      # with a byte-order mark
        assert not ok('<A x="1"/>'.encode("utf-16-le"))   # without one
        assert not ok('<A x="1"/>'.encode("utf-16-be"))
        assert not ok('<A x="1"/>'.encode("utf-32"))
        assert not ok("<A/>".encode("cp500"))             # EBCDIC

    def test_a_plain_file_never_runs_poly_type(self, gen_module, tmp_path, monkeypatch):
        _write(tmp_path / "rifle.xml", _entity(
            "rifle", "r",
            f'<X/><{_MAG} ammoParamsRecord="a" maxAmmoCount="3"/><Y Name="@n" Description="@d"/>'))
        calls = []
        real = gen_module._poly_type
        monkeypatch.setattr(gen_module, "_poly_type", lambda e: calls.append(e) or real(e))
        mags, names, candidates = gen_module._scitem_facts(tmp_path)
        assert mags == {"rifle": ("a", "3")}
        assert names == [("r", "rifle", "n")]
        assert calls == []

    def test_a_file_with_the_attribute_keeps_the_poly_type_loop(self, gen_module, tmp_path):
        _write(tmp_path / "mag.xml", _entity(
            "mag", "", f'<{_MAG} __polymorphicType="Other" ammoParamsRecord="first"/>'
            f'<Base __polymorphicType="{_MAG}" ammoParamsRecord="second" maxAmmoCount="7"/>'))
        mags, _names, _candidates = gen_module._scitem_facts(tmp_path)
        assert mags == {"mag": ("second", "7")}


# ── Blueprint pools ──────────────────────────────────────────────────────────

def _pool_tree(root: Path) -> tuple[Path, Path]:
    bp_dir = root / "blueprints"
    pool_dir = root / "pools"
    blueprints = [("e-1", "shld_one"), ("e-2", "nozzle_fuelgiver_grin_nozzlefast"),
                  ("e-3", "cool_three")]
    for i, (ent, stem) in enumerate(blueprints):
        _write(bp_dir / f"bp_craft_{stem}.xml",
               f'<CraftingBlueprintRecord __ref="bp-{i}">'
               f'<CraftingProcess_Creation entityClass="{ent}"/></CraftingBlueprintRecord>')
    _write(pool_dir / "bp_rewards_shubinrank0to1.xml",
           '<BlueprintPoolRecord __ref="pool-a"><BlueprintReward blueprintRecord="bp-0"/>'
           '<BlueprintReward blueprintRecord="bp-1"/><BlueprintReward blueprintRecord="missing"/>'
           '<BlueprintReward blueprintRecord="bp-2"/></BlueprintPoolRecord>')
    _write(pool_dir / "bp_rewards_empty.xml",
           '<BlueprintPoolRecord __ref="pool-b"><BlueprintReward blueprintRecord="missing"/>'
           '</BlueprintPoolRecord>')
    return pool_dir, bp_dir


class TestBlueprintPoolFactsCache:
    def test_names_and_tags_render_per_run_from_one_cached_walk(
            self, gen_module, tmp_path, monkeypatch):
        pool_dir, bp_dir = _pool_tree(tmp_path)
        forge = tmp_path / "forge"
        forge.mkdir()
        real = gen_module._blueprint_pool_facts
        calls = []
        monkeypatch.setattr(gen_module, "_blueprint_pool_facts",
                            lambda *a, **k: calls.append(1) or real(*a, **k))
        names = {"e-1": "S1 Shield One", "e-3": "Cooler Three"}
        runs = [
            dict(entity_name_tags={}, name_tag_placement="prepend"),
            dict(entity_name_tags={"e-1": "[MIL-S1-A]"}, name_tag_placement="prepend"),
            dict(entity_name_tags={"e-1": "(Military|Size 1)"}, name_tag_placement="append",
                 name_fallback_tags={"Norfield": "[FNoz]"}),
        ]
        for kwargs in runs:
            cached = gen_module.build_blueprint_pool_lookup(
                pool_dir, bp_dir, names, forge_dir=forge, **kwargs)
            direct = gen_module.build_blueprint_pool_lookup(pool_dir, bp_dir, names, **kwargs)
            assert cached == direct
        assert len(calls) == 1 + len(runs), "the cached walk ran again on a config change"
        items, pool_names = cached
        assert items == {
            "pool-a": ["Cooler Three", "Norfield [FNoz]", "Shield One (Military|Size 1)"]
        }
        assert pool_names == {"pool-a": "shubinrank0to1"}
        _key, facts = _load_builtins_only(forge / ".lookups" / "blueprint_pools.pkl")
        assert facts == real(pool_dir, bp_dir)


# ── Flight controller and armour lookups ─────────────────────────────────────

def _ship_tree(root: Path) -> Path:
    scitem = root / "scitem" / "ships"
    _write(scitem / "controller" / "controller_flight_aegs_test.xml",
           '<Controller><IFCSParams scmSpeed="220" maxSpeed="1200" boostSpeedForward="400" '
           'boostSpeedBackward="300"/><Profiles><SIFCSSpeedProfile>'
           '<angularVelocity x="60" y="120" z="45"/></SIFCSSpeedProfile></Profiles></Controller>')
    _write(scitem / "armor" / "armr_good.xml",
           '<EntityClassDefinition.ARMR_AEGS_Good><SHealthComponentParams Health="5000"/>'
           '<damageMultiplier><DamageInfo DamagePhysical="0.8" DamageEnergy="1.2"/>'
           '</damageMultiplier><armorDeflection>'
           '<deflectionValue DamagePhysical="10" DamageThermal="3"/></armorDeflection>'
           '</EntityClassDefinition.ARMR_AEGS_Good>')
    _write(scitem / "armor" / "armr_bad.xml",
           '<EntityClassDefinition.ARMR_AEGS_Bad><SHealthComponentParams Health="inf"/>'
           '</EntityClassDefinition.ARMR_AEGS_Bad>')
    ships = root / "spaceships"
    for cls, armour in (("AEGS_Test", "ARMR_AEGS_Good"), ("AEGS_Bad", "ARMR_AEGS_Bad")):
        _write(ships / f"{cls.lower()}.xml",
               f'<EntityClassDefinition.{cls}><Components>'
               f'<VehicleComponentParams crewSize="1" vehicleDescription="@desc_{cls}"/>'
               '<SEntityComponentDefaultLoadoutParams><loadout><entries>'
               '<SItemPortLoadoutEntryParams itemPortName="hardpoint_armor"'
               f' entityClassName="{armour}"/>'
               '</entries></loadout></SEntityComponentDefaultLoadoutParams>'
               f'</Components></EntityClassDefinition.{cls}>')
    return root


class TestShipLookupsHoldValues:
    def test_the_values_render_the_old_ship_block(self, gen_module, tmp_path):
        root = _ship_tree(tmp_path)
        controllers = gen_module.build_controller_lookup(root / "scitem" / "ships" / "controller")
        armour = gen_module.build_armor_lookup(root / "scitem" / "ships" / "armor")
        assert controllers == {"aegs_test": ("220", "1200", "400", "300", "60", "120", "45")}
        loc = {"desc_AEGS_Test": "A test ship."}
        out = gen_module.scan_spaceships(root / "spaceships", controllers, loc, armour)
        assert out["desc_AEGS_Test"] == (
            "A test ship." + gen_module.ENHANCEMENT_SEPARATOR
            + "SCM: 220 m/s  |  Max: 1,200 m/s\\nBoost: +400 m/s  /  -300 m/s"
            "\\nPitch: 60°/s  |  Roll: 120°/s  |  Yaw: 45°/s\\nCrew: 1"
            "\\nArmor HP: 5,000\\nDmg Mult: P 0.80x  |  E 1.20x  |  D ?  |  T ?"
            "\\nDeflect: P 10  |  E ?  |  D ?  |  T 3"
        )

    def test_an_unformattable_armour_value_still_fails_only_its_ship(
            self, gen_module, tmp_path, caplog):
        root = _ship_tree(tmp_path)
        armour = gen_module.build_armor_lookup(root / "scitem" / "ships" / "armor")
        loc = {"desc_AEGS_Test": "A test ship.", "desc_AEGS_Bad": "A bad ship."}
        with caplog.at_level(logging.WARNING):
            out = gen_module.scan_spaceships(root / "spaceships", {}, loc, armour)
        assert "desc_AEGS_Test" in out
        assert "desc_AEGS_Bad" not in out
        assert any("aegs_bad.xml" in r.getMessage() for r in caplog.records)

    @pytest.mark.parametrize("xml, old, new, old_text, new_text", [
        ("controller/controller_flight_aegs_test.xml", 'scmSpeed="220"', 'scmSpeed="235"',
         "SCM: 220 m/s", "SCM: 235 m/s"),
        ("armor/armr_good.xml", 'Health="5000"', 'Health="6500"',
         "Armor HP: 5,000", "Armor HP: 6,500"),
    ])
    def test_a_changed_xml_shows_on_the_next_run_without_a_re_extraction(
            self, gen_module, tmp_path, xml, old, new, old_text, new_text):
        """DataForge patches are applied again before every generation, with
        no re-extraction, so a controller or armour XML can change while the
        DataForge build stays the same. The next run shows the new value, as
        it did when both lookups held lxml trees read on every run, because
        neither is pickled."""
        forge = tmp_path / "forge"
        records = forge / gen_module.DATAFORGE_RECORDS_SUBPATH
        _ship_tree(records / "entities")
        (forge / ".p4k_mtime").write_text("12345", encoding="utf-8")
        base = _write(tmp_path / "out" / "base.ini", "desc_AEGS_Test=A test ship.\n")

        def ship_block():
            gen_module.main(base, forge, categories={"ship_descs"}, max_workers=1)
            return gen_module.parse_ini(base.parent / "ships_desc_enhancements.ini")[
                "desc_AEGS_Test"]

        assert old_text in ship_block()
        patched = records / "entities" / "scitem" / "ships" / xml
        patched.write_bytes(patched.read_bytes().replace(old.encode(), new.encode()))
        block = ship_block()
        assert new_text in block and old_text not in block
        assert not list((forge / ".lookups").glob("ship_*.pkl"))


# ── Commodity crafting ───────────────────────────────────────────────────────

def _old_discover_commodity_loc_pairs(internal_name, loc):
    """_discover_commodity_loc_pairs before the prefilter."""
    prefix = f"items_commodities_{internal_name.lower()}"
    name_keys, desc_by_base = [], {}
    for key in loc:
        klow = key.lower()
        if not klow.startswith(prefix):
            continue
        if klow.endswith("_desc"):
            desc_by_base[klow[:-5]] = key
        elif klow.endswith("_des"):
            desc_by_base.setdefault(klow[:-4], key)
        else:
            name_keys.append(key)
    return [(n, desc_by_base[n.lower()]) for n in name_keys if n.lower() in desc_by_base]


_COMMODITY_LOC = {
    "items_commodities_Iron": "Iron", "items_commodities_iron_desc": "Iron desc",
    "Items_Commodities_Iron_Ore": "Iron (Ore)", "items_commodities_iron_ore_des": "Iron ore des",
    "items_commodities_iron_ore_desc": "Iron ore desc", "items_commodities_ironwood": "Ironwood",
    "items_commodities_gold": "Gold", "items_commodities_gold_desc": "Gold desc",
    "items_commodities_quartz_raw": "Quartz (Raw)",
    "items_commodities_quartz_raw_DESC": "Quartz desc",
    "item_Name_iron": "not a commodity", "Journal_General_Mining_Compendium_Content": "",
}


class TestCommodityLocPrefilter:
    @pytest.mark.parametrize("name", ["iron", "IRON", "gold", "quartz", "ironwood", "tin", ""])
    def test_pairs_match_a_scan_of_every_key(self, gen_module, name):
        keys = gen_module._commodity_loc_keys(_COMMODITY_LOC)
        expected = _old_discover_commodity_loc_pairs(name, _COMMODITY_LOC)
        assert gen_module._discover_commodity_loc_pairs(name, _COMMODITY_LOC, keys) == expected
        assert gen_module._discover_commodity_loc_pairs(name, _COMMODITY_LOC) == expected

    def test_the_prefilter_keeps_loc_order(self, gen_module):
        keys = gen_module._commodity_loc_keys(_COMMODITY_LOC)
        assert [k for k, _ in keys] == [k for k in _COMMODITY_LOC
                                        if k.lower().startswith("items_commodities_")]
        assert all(low == k.lower() for k, low in keys)


def _crafting_tree(root: Path) -> tuple[Path, Path]:
    bp_dir = root / "blueprints" / "crafting"
    carry = root / "carryables"
    iron, gold, gem = ("aaaa0000-0000-0000-0000-00000000000%d" % i for i in (1, 2, 3))
    _write(bp_dir / "vehiclegear" / "cooler" / "bp_craft_cool_a.xml",
           '<CraftingBlueprintRecord><CraftingProcess_Creation entityClass="ent-a"/>'
           f'<CraftingCost_Resource resource="{iron}"/><CraftingCost_Resource resource="{gold}"/>'
           '</CraftingBlueprintRecord>')
    _write(bp_dir / "vehiclegear" / "quantumdrive" / "size2" / "bp_craft_qd_b.xml",
           '<CraftingBlueprintRecord><CraftingProcess_Creation entityClass="ent-unknown"/>'
           f'<Base __polymorphicType="CraftingCost_Item" entityClass="{gem}"/>'
           f'<CraftingCost_Resource resource="{iron}"/>'
           '<CraftingCost_Resource resource="00000000-0000-0000-0000-000000000000"/>'
           '</CraftingBlueprintRecord>')
    _write(bp_dir / "bp_craft_broken.xml", "<CraftingBlueprintRecord>")
    _write(carry / "carryable_1h_commodity_metal_iron.xml", f'<E><T v="{iron}"/></E>')
    _write(carry / "carryable_1h_commodity_metal_gold_a.xml", f'<E><T v="{gold}"/></E>')
    _write(carry / "harvestable_mineral_1h_hadanite.xml", f'<E __ref="{gem}"/>')
    _write(carry / "some_crate.xml", f'<E><T v="{iron}"/></E>')
    return bp_dir, carry


_CRAFT_LOC = {
    "items_commodities_iron": "Iron", "items_commodities_iron_desc": "Iron desc",
    "items_commodities_gold": "Gold", "items_commodities_gold_desc": "Gold desc",
    "items_commodities_hadanite": "Hadanite", "items_commodities_hadanite_desc": "Hadanite desc",
}


class TestCraftingBlueprintsSinglePass:
    def test_each_blueprint_is_parsed_once(self, gen_module, tmp_path, monkeypatch):
        bp_dir, carry = _crafting_tree(tmp_path)
        names = {"ent-a": "Cooler A"}
        expected = gen_module.scan_crafting_blueprints(bp_dir, carry, names, _CRAFT_LOC)
        counter = _ParseCounter(gen_module, monkeypatch)
        out = gen_module.scan_crafting_blueprints(bp_dir, carry, names, _CRAFT_LOC)
        assert out == expected
        assert dict(counter.counts) == {"bp_craft_cool_a.xml": 1, "bp_craft_qd_b.xml": 1,
                                        "bp_craft_broken.xml": 1}
        commodities, _journal = out
        assert "Cooler" in commodities["items_commodities_iron_desc"]
        assert "Quantum Drives: 1 items (S2)" in commodities["items_commodities_hadanite_desc"]
        assert "items_commodities_gold_desc" in commodities

    def test_the_loc_keys_are_lowercased_once_per_scan(self, gen_module, tmp_path, monkeypatch):
        bp_dir, carry = _crafting_tree(tmp_path)
        real = gen_module._commodity_loc_keys
        calls = []
        monkeypatch.setattr(gen_module, "_commodity_loc_keys",
                            lambda loc: calls.append(1) or real(loc))
        loc = dict(_CRAFT_LOC, Journal_General_Mining_Compendium_Title="Mining",
                   Journal_General_Mining_Compendium_Content="Iron - Daymar\\n\\nGold - Yela")
        gen_module.scan_crafting_blueprints(bp_dir, carry, {}, loc)
        assert len(calls) == 1

    def test_the_crafting_index_reads_the_same_prefiltered_keys(
            self, gen_module, tmp_path, monkeypatch):
        """The SCO drawer's crafting index (#474) finds each material's names
        through the keys the scan lowercased once, and gets the names a
        scan of every loc key gives."""
        bp_dir, carry = _crafting_tree(tmp_path)
        loc = dict(_CRAFT_LOC, Items_Commodities_Iron_Ore="Iron (Ore)",
                   items_commodities_iron_ore_desc="Iron ore desc",
                   items_commodities_gold_raw="  ", items_commodities_gold_raw_desc="x")
        real = gen_module._commodity_loc_keys
        calls = []
        monkeypatch.setattr(gen_module, "_commodity_loc_keys",
                            lambda loc_: calls.append(1) or real(loc_))
        index: dict = {}
        gen_module.scan_crafting_blueprints(bp_dir, carry, {"ent-a": "Cooler A"}, loc,
                                            crafting_index=index)
        assert len(calls) == 1
        expected = {}
        for mat in ("iron", "gold", "hadanite"):
            pairs = _old_discover_commodity_loc_pairs(mat, loc)
            names = {loc[key].strip() for key, _desc in pairs if loc.get(key, "").strip()}
            expected[mat] = sorted(names, key=lambda n: (len(n), n))
        assert {mat: entry["names"] for mat, entry in index.items()} == expected
        assert expected["iron"] == ["Iron", "Iron (Ore)"]

    def test_a_carryable_is_read_only_when_its_name_names_a_commodity(
            self, gen_module, tmp_path, monkeypatch):
        _bp_dir, carry = _crafting_tree(tmp_path)
        read = []
        real = pathlib.Path.read_text
        monkeypatch.setattr(pathlib.Path, "read_text",
                            lambda self, *a, **k: read.append(self.name) or real(self, *a, **k))
        uuids = {"aaaa0000-0000-0000-0000-000000000001", "aaaa0000-0000-0000-0000-000000000003"}
        names = gen_module._build_uuid_to_commodity(uuids, carry)
        assert names == {"aaaa0000-0000-0000-0000-000000000001": "iron",
                         "aaaa0000-0000-0000-0000-000000000003": "hadanite"}
        assert "some_crate.xml" not in read
        assert sorted(read) == ["carryable_1h_commodity_metal_gold_a.xml",
                                "carryable_1h_commodity_metal_iron.xml",
                                "harvestable_mineral_1h_hadanite.xml"]


# ── Missions ─────────────────────────────────────────────────────────────────

def _pu_mission(title, desc, hostiles=0, xp_reward="", extra=""):
    ships = (
        '<SpawnDescription_ShipGroup Name="Pirates"><ships>'
        f'<SpawnDescription_Ship concurrentAmount="{hostiles}"/>'
        '</ships></SpawnDescription_ShipGroup>'
        if hostiles else ""
    )
    rep = (
        '<missionResultReputationRewards><SReputationAmountListParams><reputationAmounts>'
        f'<SReputationAmountParams reputationScope="s" reward="{xp_reward}"/>'
        '</reputationAmounts></SReputationAmountListParams></missionResultReputationRewards>'
        if xp_reward else ""
    )
    return (f'<MissionBrokerEntry title="@{title}" description="@{desc}">'
            f'<spawnDescriptions>{ships}</spawnDescriptions>{rep}{extra}</MissionBrokerEntry>')


_BATTAGLIA_CONTRACT = (
    '<CareerContract debugName="Battaglia_Scan"><paramOverrides><stringParamOverrides>'
    '<ContractStringParam param="Title" value="@Battaglia_RPT_Scan_01_title"/>'
    '</stringParamOverrides><propertyOverrides>'
    '<MissionProperty extendedTextToken="ResourceType"><value><MissionPropertyValue_StringHash>'
    '<options><MissionPropertyValueOption_StringHash textId="@mineabletype_primary_iron"/>'
    '</options>'
    '</MissionPropertyValue_StringHash></value></MissionProperty>'
    '</propertyOverrides></paramOverrides></CareerContract>'
)


def _missions_tree(root: Path) -> Path:
    records = root / "records"
    pu = records / "missionbroker" / "pu_missions"
    _write(pu / "cargo" / "haul_1.xml", _pu_mission("Haul_title", "Haul_desc", xp_reward="rep-100"))
    # Three XMLs share Mixed_desc with different hostiles (#165), the last
    # one read (whose body is the one kept) with some; two share Same_desc
    # with the same hostiles.
    _write(pu / "combat" / "mixed_1.xml", _pu_mission("Mixed_title", "Mixed_desc"))
    _write(pu / "combat" / "mixed_2.xml", _pu_mission("Mixed_title", "Mixed_desc", hostiles=2))
    _write(pu / "combat" / "mixed_3.xml", _pu_mission("Mixed_title", "Mixed_desc", hostiles=5))
    _write(pu / "combat" / "same_1.xml", _pu_mission("Same_title", "Same_desc", hostiles=3))
    _write(pu / "combat" / "same_2.xml", _pu_mission("Same_title", "Same_desc", hostiles=3))
    _write(pu / "combat" / "nokey.xml", '<MissionBrokerEntry title="@X_title"/>')
    _write(pu / "combat" / "broken.xml", "<MissionBrokerEntry>")
    cg = records / "contracts" / "contractgenerator"
    _write(cg / "battaglia.xml",
           '<ContractGenerator><ContractGeneratorHandler_Career debugName="Battaglia">'
           f'<contracts>{_BATTAGLIA_CONTRACT}</contracts></ContractGeneratorHandler_Career>'
           '</ContractGenerator>')
    _write(cg / "dynamic.xml",
           '<ContractGenerator><ContractGeneratorHandler_List debugName="Dyn"><contracts>'
           '<Contract debugName="Dynamic" template="tmpl-1"><ContractStringParam param="Title" '
           'value="@dynamic_reward_title"/><contractResults><ContractResult_CalculatedReward/>'
           '</contractResults></Contract></contracts></ContractGeneratorHandler_List>'
           '</ContractGenerator>')
    _write(records / "contracts" / "contracttemplates" / "tmpl.xml",
           '<ContractTemplate __ref="tmpl-1"><LocID value="@dynamic_reward_title"/>'
           '<LocID value="@dynamic_reward_desc"/></ContractTemplate>')
    return records


def _missions_ctx(records: Path, tmp_path: Path) -> dict:
    loc = {
        "Haul_title": "Haul", "Haul_desc": "Haul cargo.", "Mixed_title": "Mixed",
        "Mixed_desc": "Mixed hostiles.", "Same_title": "Same", "Same_desc": "Same hostiles.",
        "Battaglia_RPT_Scan_01_title": "Scan for ore", "dynamic_reward_title": "Dynamic",
        "dynamic_reward_desc": "A dynamic reward.", "mineabletype_primary_iron": "Iron",
    }
    return {
        "records": records,
        "forge_dir": tmp_path / "forge",
        "loc": loc,
        "tag_loc": loc,
        "entity_names": {},
        "reputation_lookup": {"rep-100": 100},
    }


class TestMissionsSinglePass:
    def test_each_mission_xml_is_parsed_once(self, gen_module, tmp_path, monkeypatch):
        records = _missions_tree(tmp_path)
        counter = _ParseCounter(gen_module, monkeypatch)
        gen_module._run_gen_missions(_missions_ctx(records, tmp_path))
        pu = {p.name for p in (records / "missionbroker" / "pu_missions").rglob("*.xml")}
        cg = {"battaglia.xml", "dynamic.xml", "tmpl.xml"}
        parsed = {n: c for n, c in counter.counts.items() if n in pu | cg}
        assert parsed == dict.fromkeys(pu | cg, 1)

    def test_hostiles_drop_only_from_a_shared_desc_whose_xmls_disagree(self, gen_module, tmp_path):
        """#165 through the single pass: the pick between the plain body and
        the one without hostiles waits until every XML has been read."""
        out = gen_module._run_gen_missions(_missions_ctx(_missions_tree(tmp_path), tmp_path))
        assert "Hostiles:" not in out["Mixed_desc"]
        assert "<EM4>Hostiles:</EM4> Pirates x3" in out["Same_desc"]
        assert out["Haul_title"] == "Haul <EM4>[100 Rep]</EM4>"

    def test_the_contractgen_scans_share_the_parse(self, gen_module, tmp_path, caplog):
        with caplog.at_level(logging.INFO):
            out = gen_module._run_gen_missions(_missions_ctx(_missions_tree(tmp_path), tmp_path))
        assert out["Battaglia_RPT_Scan_01_title"].endswith("<EM4>[RS 4270]</EM4>")
        assert any("dynamically-calculated reward" in r.getMessage()
                   and "dynamic_reward_title" in r.getMessage() for r in caplog.records)
        assert sum("Contract template lookup" in r.getMessage() for r in caplog.records) == 1

    def test_a_battaglia_failure_still_ends_the_run(self, gen_module, tmp_path, monkeypatch):
        def boom(*_args, **_kwargs):
            raise RuntimeError("battaglia boom")

        monkeypatch.setattr(gen_module, "_battaglia_mineable_rs_in", boom)
        records = _missions_tree(tmp_path)
        with pytest.raises(RuntimeError, match="battaglia boom"):
            gen_module._run_gen_missions(_missions_ctx(records, tmp_path))
        # Unlike the calculated-reward diagnostic, the Battaglia scan always
        # ran, so its failure ends the run with the Rep tag off too, when no
        # contractgen title has zero XP.
        ctx = dict(_missions_ctx(records, tmp_path), mission_title_tags={"rep": False})
        with pytest.raises(RuntimeError, match="battaglia boom"):
            gen_module._run_gen_missions(ctx)

    def test_a_held_battaglia_error_wins_over_a_later_listing_failure(
            self, gen_module, tmp_path, monkeypatch):
        """The Battaglia scan raised its own first error before the listing
        failed, so that error, not the listing's, ends the run."""
        def boom(*_args):
            raise RuntimeError("battaglia boom")

        real = gen_module._indexed_xml_files

        def fails_after_one(entity_dir, xml_path_index=None, records_dir=None):
            files = iter(real(entity_dir, xml_path_index, records_dir))
            if entity_dir.name == "contractgenerator":
                yield next(files)
                raise OSError("listing failed part-way")
            yield from files

        monkeypatch.setattr(gen_module, "_battaglia_mineable_rs_in", boom)
        monkeypatch.setattr(gen_module, "_indexed_xml_files", fails_after_one)
        with pytest.raises(RuntimeError, match="battaglia boom"):
            gen_module._run_gen_missions(_missions_ctx(_missions_tree(tmp_path), tmp_path))

    def test_the_other_scans_see_every_file_when_the_contract_scan_stops_early(
            self, gen_module, tmp_path, monkeypatch):
        records = _missions_tree(tmp_path)
        seen = []
        real = gen_module._battaglia_mineable_rs_in
        monkeypatch.setattr(gen_module, "_battaglia_mineable_rs_in",
                            lambda root, *a: seen.append(root.tag) or real(root, *a))

        def stops_after_one(*_args, roots=None, **_kwargs):
            next(iter(roots), None)
            return {}, {}, {}, {}

        monkeypatch.setattr(gen_module, "scan_contract_generators", stops_after_one)
        gen_module._run_gen_missions(_missions_ctx(records, tmp_path))
        assert len(seen) == 2

    def test_a_listing_that_fails_part_way_still_ends_the_run(
            self, gen_module, tmp_path, monkeypatch, caplog):
        """Before the shared walk, the Battaglia scan listed the contractgen
        files again and raised a listing failure out of the run, after
        scan_contract_generators had logged it and stopped. The shared walk
        must not let that scan's broad except swallow it."""
        real = gen_module._indexed_xml_files

        def fails_after_one(entity_dir, xml_path_index=None, records_dir=None):
            files = iter(real(entity_dir, xml_path_index, records_dir))
            if entity_dir.name == "contractgenerator":
                yield next(files)
                raise OSError("listing failed part-way")
            yield from files

        monkeypatch.setattr(gen_module, "_indexed_xml_files", fails_after_one)
        with caplog.at_level(logging.WARNING), pytest.raises(OSError, match="part-way"):
            gen_module._run_gen_missions(_missions_ctx(_missions_tree(tmp_path), tmp_path))
        assert sum("Error scanning contract generators" in r.getMessage()
                   for r in caplog.records) == 1

    def test_a_listing_that_fails_outright_ends_the_run_before_the_scan(
            self, gen_module, tmp_path, monkeypatch, caplog):
        """scan_contract_generators asked for its file list outside its try,
        so a listing that failed outright ended the run unlogged."""
        real = gen_module._indexed_xml_files

        def fails(entity_dir, xml_path_index=None, records_dir=None):
            if entity_dir.name == "contractgenerator":
                raise OSError("listing failed")
            return real(entity_dir, xml_path_index, records_dir)

        monkeypatch.setattr(gen_module, "_indexed_xml_files", fails)
        with caplog.at_level(logging.WARNING), pytest.raises(OSError, match="listing failed"):
            gen_module._run_gen_missions(_missions_ctx(_missions_tree(tmp_path), tmp_path))
        assert not any("Error scanning contract generators" in r.getMessage()
                       for r in caplog.records)

    def test_a_calculated_reward_failure_ends_the_run_where_its_scan_ran(
            self, gen_module, tmp_path, monkeypatch):
        """Before the shared walk, the calculated-reward scan ran only once a
        contractgen title had zero XP, and a failure in it ended the run. The
        shared walk holds the failure and raises it there, and only there."""
        def boom(*_args):
            raise RuntimeError("calculated reward boom")

        monkeypatch.setattr(gen_module, "_calculated_reward_titles_in", boom)
        records = _missions_tree(tmp_path)
        with pytest.raises(RuntimeError, match="calculated reward boom"):
            gen_module._run_gen_missions(_missions_ctx(records, tmp_path))
        # With the rep tag off no zero-XP title is collected, so the scan
        # never ran and the run finishes.
        ctx = dict(_missions_ctx(records, tmp_path), mission_title_tags={"rep": False})
        out = gen_module._run_gen_missions(ctx)
        assert out["Battaglia_RPT_Scan_01_title"].endswith("<EM4>[RS 4270]</EM4>")

    @pytest.mark.parametrize("scan", ["_battaglia_mineable_rs_in", "_calculated_reward_titles_in"])
    def test_the_first_error_is_the_one_raised(self, gen_module, tmp_path, monkeypatch, scan):
        """Each separate scan stopped at its first error and raised it. The
        shared walk holds that first error and asks the failed scan about no
        other file, so a later file's error never takes its place."""
        calls = []

        def boom(*_args):
            calls.append(None)
            raise RuntimeError(f"error {len(calls)}")

        monkeypatch.setattr(gen_module, scan, boom)
        with pytest.raises(RuntimeError) as raised:
            gen_module._run_gen_missions(_missions_ctx(_missions_tree(tmp_path), tmp_path))
        assert str(raised.value) == "error 1"
        assert len(calls) == 1


_ROUTE_BODY = "Take it from ~mission(Location|Address) to ~mission(Destination|Address)."


def _titles_tree(root: Path) -> Path:
    """A [BP] contractgen title that pu_missions XMLs share (#31, #102), a
    second one whose only pu_missions description is a sentinel, a pu-only
    delivery title whose route comes from its description (#166, #200), the
    same with no XP, and a title whose description is a sentinel."""
    records = root / "records"
    _write(records / "contracts" / "contractgenerator" / "career.xml",
           '<ContractGenerator><ContractGeneratorHandler_List debugName="Stanton_Test">'
           '<Contract debugName="Stanton_Shared" notForRelease="0">'
           '<ContractStringParam param="Title" value="@Shared_Bp_title"/>'
           '<ContractStringParam param="Description" value="@Shared_Cg_desc"/>'
           '<BlueprintRewards blueprintPool="pool-bp" chance="1"/>'
           '</Contract>'
           '<Contract debugName="Stanton_Other" notForRelease="0">'
           '<ContractStringParam param="Title" value="@Other_Bp_title"/>'
           '<ContractStringParam param="Description" value="@Other_Cg_desc"/>'
           '<BlueprintRewards blueprintPool="pool-bp" chance="1"/>'
           '</Contract></ContractGeneratorHandler_List></ContractGenerator>')
    _write(records / "crafting" / "blueprints" / "crafting" / "bp_craft_cool_three.xml",
           '<CraftingBlueprintRecord __ref="bp-3"><CraftingProcess_Creation entityClass="e-3"/>'
           '</CraftingBlueprintRecord>')
    _write(records / "crafting" / "blueprintrewards" / "bp_rewards_shared.xml",
           '<BlueprintPoolRecord __ref="pool-bp"><BlueprintReward blueprintRecord="bp-3"/>'
           '</BlueprintPoolRecord>')
    pu = records / "missionbroker" / "pu_missions"
    # Under the [BP] title, three bodies contractgen never writes: a cargo
    # haul and a delivery haul (kept, #102) and a combat one (an orphan,
    # dropped, #31).
    _write(pu / "cargo" / "shared_haul.xml", _pu_mission("Shared_Bp_title", "Shared_Haul_desc"))
    _write(pu / "delivery" / "shared_haul.xml",
           _pu_mission("Shared_Bp_title", "Shared_Delivery_desc"))
    # Under the second [BP] title, only a cargo haul whose description is a
    # sentinel: no body, so nothing to demote the title for.
    _write(pu / "cargo" / "other_sentinel.xml", _pu_mission("Other_Bp_title", "LOC_EMPTY"))
    _write(pu / "combat" / "shared_orphan.xml",
           _pu_mission("Shared_Bp_title", "Shared_Orphan_desc"))
    _write(pu / "delivery" / "route.xml",
           _pu_mission("Covalex_Delivery_Route_title", "Route_desc", xp_reward="rep-100"))
    _write(pu / "delivery" / "zero.xml", _pu_mission("Covalex_Delivery_Zero_title", "Zero_desc"))
    _write(pu / "combat" / "sentinel.xml", _pu_mission("Sentinel_Desc_title", "LOC_EMPTY"))
    return records


def _titles_ctx(records: Path, tmp_path: Path) -> dict:
    loc = {
        "Shared_Bp_title": "Shared", "Shared_Cg_desc": "Career body.",
        "Shared_Haul_desc": "Haul body.", "Shared_Orphan_desc": "Orphan body.",
        "Shared_Delivery_desc": "Delivery body.",
        "Other_Bp_title": "Other", "Other_Cg_desc": "Other career body.",
        "Covalex_Delivery_Route_title": "Deliver", "Route_desc": _ROUTE_BODY,
        "Covalex_Delivery_Zero_title": "Deliver for nothing", "Zero_desc": _ROUTE_BODY,
        "Sentinel_Desc_title": "Sentinel",
    }
    return {
        "records": records,
        "forge_dir": tmp_path / "forge",
        "loc": loc,
        "tag_loc": loc,
        "entity_names": {},
        "reputation_lookup": {"rep-100": 100},
    }


class TestTitlesFromThePuMissionsPass:
    """The title half of _scan_pu_missions (each title's desc keys, the
    cargo and delivery ones among them, and the positive XP per title),
    end to end through _run_gen_missions, against what the generator wrote
    before the single pass."""

    @pytest.fixture
    def run(self, gen_module, tmp_path, caplog):
        caplog.set_level(logging.INFO)
        out = gen_module._run_gen_missions(_titles_ctx(_titles_tree(tmp_path), tmp_path))
        return out, [r.getMessage() for r in caplog.records]

    def test_a_cargo_haul_keeps_its_body_and_demotes_the_bp_title(self, run):
        """#102: the haul's body survives the orphan drop, and the title reads
        [BP?], not [BP], because that haul awards no blueprints (#31)."""
        out, _logs = run
        assert out["Shared_Bp_title"] == "Shared <EM4>[BP?]</EM4>"
        assert out["Shared_Haul_desc"].startswith("Haul body.")
        assert "Cool Three" in out["Shared_Cg_desc"]

    def test_a_delivery_haul_keeps_its_body_too(self, run):
        """#102 counts the delivery folder as a haul, as it does cargo."""
        out, _logs = run
        assert out["Shared_Delivery_desc"].startswith("Delivery body.")

    def test_a_sentinel_description_does_not_demote_a_bp_title(self, run):
        """#31: a [BP] title is demoted for a haul body that awards no
        blueprints, and a haul whose description is a sentinel (LOC_EMPTY)
        has no body."""
        out, _logs = run
        assert out["Other_Bp_title"] == "Other <EM4>[BP]</EM4>"
        assert "Cool Three" in out["Other_Cg_desc"]

    def test_a_pu_only_body_under_a_bp_title_is_dropped(self, run):
        """#31: a body under a [BP] title that contractgen never writes, and
        that is no haul, is an orphan."""
        out, _logs = run
        assert "Shared_Orphan_desc" not in out

    def test_a_pu_only_route_title_takes_its_route_from_its_descriptions(self, run):
        """#166 / #200: a pu-only delivery title gets the route its own
        description names, then its XP."""
        out, _logs = run
        title = out["Covalex_Delivery_Route_title"]
        assert "~mission(Location" in title and "~mission(Destination" in title
        assert title.startswith("Deliver") and title.endswith("<EM4>[100 Rep]</EM4>")

    def test_a_pu_only_title_with_no_xp_is_left_alone(self, run):
        """Only positive XP counts, so a zero-XP title gets no route, no
        shortening and no tag."""
        out, _logs = run
        assert "Covalex_Delivery_Zero_title" not in out

    def test_the_titles_skipped_count_takes_a_sentinel_description(self, run):
        """The end-of-run diagnostic counts every pu_missions title with an @
        title and description that nothing wrote, one whose description is a
        sentinel (LOC_EMPTY) included."""
        _out, logs = run
        coverage = next(m for m in logs if m.startswith("Mission XP coverage"))
        assert coverage.endswith(", 2 titles skipped")
        no_rep = next(m for m in logs if "Skipped (no_rep_data)" in m)
        assert set(no_rep.split("e.g. ", 1)[1].split(", ")) == {
            "Covalex_Delivery_Zero_title", "Sentinel_Desc_title"}


# ── XML path index ───────────────────────────────────────────────────────────

def _old_build_xml_path_index(records_dir: Path) -> dict:
    idx = defaultdict(list)
    for xml_file in records_dir.rglob("*.xml"):
        idx[xml_file.parent.relative_to(records_dir).as_posix()].append(str(xml_file))
    return {k: sorted(v) for k, v in idx.items()}


class TestXmlPathIndex:
    def _tree(self, root: Path) -> Path:
        for rel in ("top.xml", "a/one.xml", "a/two.xml", "a/b/three.xml", "a/b/four.xml",
                    "c/five.xml", "c/d/e/six.xml", "c/d/e/seven.xml", "c/d/notxml.txt"):
            _write(root / rel, "<x/>")
        return root

    def test_the_index_matches_a_per_file_walk_in_order(self, gen_module, tmp_path):
        records = self._tree(tmp_path / "records")
        new = gen_module._build_xml_path_index(records)
        old = _old_build_xml_path_index(records)
        assert list(new.items()) == list(old.items())
        assert "." in new

    def test_each_folder_key_is_worked_out_once(self, gen_module, tmp_path, monkeypatch):
        records = self._tree(tmp_path / "records")
        calls = []
        real = pathlib.PurePath.relative_to
        monkeypatch.setattr(pathlib.PurePath, "relative_to",
                            lambda self, *a, **k: calls.append(1) or real(self, *a, **k))
        gen_module._build_xml_path_index(records)
        assert len(calls) == 5  # top, a, a/b, c, c/d/e; eight XML files


class TestParseXmlFile:
    """_parse_xml_file gives the tree ET.parse gives, so the hot loops that
    use it write the same text."""

    @pytest.mark.parametrize("data", [
        b'<A x="1"><B>text</B>\n  <C/></A>',
        b'\xef\xbb\xbf<?xml version="1.0" encoding="utf-8"?>\r\n<A y="\xc3\xa9"/>',
        '<?xml version="1.0" encoding="utf-16"?><A z="2"/>'.encode("utf-16"),
        b'<?xml version="1.0" encoding="windows-1252"?><A w="\xe9"/>',
    ])
    def test_the_same_tree_as_lxml_parse(self, gen_module, tmp_path, data):
        f = tmp_path / "f.xml"
        f.write_bytes(data)
        assert ET.tostring(gen_module._parse_xml_file(f)) == ET.tostring(ET.parse(f).getroot())

    @pytest.mark.parametrize("data", [b"", b"   ", b"<A><B></A>", b"not xml"])
    def test_a_broken_file_raises_parse_error(self, gen_module, tmp_path, data):
        f = tmp_path / "f.xml"
        f.write_bytes(data)
        with pytest.raises(ET.ParseError):
            gen_module._parse_xml_file(f)

    def test_a_missing_file_raises_os_error(self, gen_module, tmp_path):
        with pytest.raises(OSError):
            gen_module._parse_xml_file(tmp_path / "missing.xml")
