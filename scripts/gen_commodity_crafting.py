"""Generate commodity_crafting_enhancements.ini with blueprint usage data."""
from lxml import etree as ET
from pathlib import Path
from collections import defaultdict
import subprocess, re, os, sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.generate_enhancements_ini import (
    DEFAULT_BASE_INI, DEFAULT_FORGE_DIR, parse_ini, write_ini, APP_CACHE_DIR,
    DATAFORGE_RECORDS_SUBPATH,
)

base_ini = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_BASE_INI
dataforge_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_FORGE_DIR
candidate_records_dir = dataforge_dir / DATAFORGE_RECORDS_SUBPATH
records_dir = candidate_records_dir if candidate_records_dir.exists() else dataforge_dir
scitem_dir = records_dir / "entities" / "scitem"
bp_dir = records_dir / "crafting" / "blueprints" / "crafting"

loc = parse_ini(base_ini)

# Step 1: Resource UUID -> commodity name
resource_uuids_all = set()
for xml_file in bp_dir.rglob("*.xml"):
    try:
        root = ET.parse(xml_file).getroot()
        for elem in root.iter():
            if elem.get("__polymorphicType") == "CraftingCost_Resource":
                r = elem.get("resource", "")
                if r and r != "00000000-0000-0000-0000-000000000000":
                    resource_uuids_all.add(r)
    except:
        pass

uuid_names = {}
for uid in resource_uuids_all:
    result = subprocess.run(
        ["grep", "-rl", uid, str(scitem_dir / "carryables")],
        capture_output=True, text=True, timeout=30
    )
    files = [f for f in result.stdout.strip().split("\n") if f]
    if files:
        fname = Path(files[0]).stem
        m = re.search(r"commodity_(?:metal|mineral|minerals|nonmetal|gas)_(\w+?)(?:_[a-d])?$", fname)
        if m:
            uuid_names[uid] = m.group(1).lower()

# Step 2: Entity UUID -> item display name
entity_names = {}
for xml_file in scitem_dir.rglob("*.xml"):
    try:
        root = ET.parse(xml_file).getroot()
        ref = root.get("__ref", "")
        if not ref:
            continue
        for elem in root.iter():
            name_attr = elem.get("Name", "")
            if name_attr and name_attr.startswith("@"):
                loc_key = name_attr.lstrip("@")
                display = loc.get(loc_key, loc_key)
                entity_names[ref] = display
                break
    except:
        pass

# Step 3: Parse blueprints
commodity_items = defaultdict(list)
for xml_file in sorted(bp_dir.rglob("*.xml")):
    try:
        root = ET.parse(xml_file).getroot()
        rel = xml_file.relative_to(bp_dir)
        category = str(rel.parent).replace(os.sep, "/")
        item_name = xml_file.stem.replace("bp_craft_", "")
        for elem in root.iter():
            if elem.get("__polymorphicType") == "CraftingProcess_Creation":
                entity_ref = elem.get("entityClass", "")
                if entity_ref in entity_names:
                    item_name = entity_names[entity_ref]
                break
        materials = set()
        for elem in root.iter():
            if elem.get("__polymorphicType") == "CraftingCost_Resource":
                r = elem.get("resource", "")
                if r in uuid_names:
                    materials.add(uuid_names[r])
        for mat in materials:
            commodity_items[mat].append((category, item_name))
    except:
        pass


def condense_items(items_list):
    by_cat = defaultdict(list)
    for cat, name in items_list:
        by_cat[cat].append(name)
    lines = []
    for cat in sorted(by_cat.keys()):
        names = sorted(set(by_cat[cat]))
        parts = cat.split("/")
        if "ammo" in cat:
            ammo_type = parts[-1].title() if len(parts) > 2 else "Ammo"
            lines.append(f"{ammo_type} Ammo")
            continue
        if "weapons" in cat:
            base_names = set()
            for n in names:
                clean = re.sub(r'\s*"[^"]*"\s*', ' ', n).strip()
                clean = re.sub(r'\s+', ' ', clean)
                base_names.add(clean)
            if len(base_names) <= 3:
                lines.append(", ".join(sorted(base_names)))
            else:
                weapon_type = parts[-1].title()
                lines.append(f"{weapon_type}s ({len(base_names)} types)")
            continue
        if "armour" in cat:
            weight = parts[-1].title() if len(parts) > 2 else ""
            armour_type = parts[-2].title() if len(parts) > 2 else "Armour"
            set_names = set()
            for n in names:
                m2 = re.match(r'^([\w-]+(?:\s[\w-]+)?)\s+(?:Arms|Core|Legs|Helmet|Backpack|Suit|Armor)', n)
                if m2:
                    set_names.add(m2.group(1))
                else:
                    set_names.add(n.split()[0] if n else n)
            if len(set_names) <= 3:
                label = ", ".join(sorted(set_names))
            else:
                label = f"{len(set_names)} sets"
            if weight and armour_type != weight:
                lines.append(f"{label} ({weight} {armour_type})")
            else:
                lines.append(f"{label} ({armour_type})")
            continue
        lines.append(f"{cat}: {len(names)} items")
    return lines


# Commodity internal name -> (name_loc_key, desc_loc_key)
commodity_loc = {
    "agricium": ("items_commodities_agricium", "items_commodities_agricium_desc"),
    "aluminium": ("items_commodities_aluminum_ore", "items_commodities_aluminum_ore_desc"),
    "aslarite": ("items_commodities_aslarite", "items_commodities_aslarite_desc"),
    "beryl": ("items_commodities_beryl", "items_commodities_beryl_desc"),
    "copper": ("items_commodities_copper", "items_commodities_copper_desc"),
    "corundum": ("items_commodities_corundum", "items_commodities_corundum_desc"),
    "gold": ("items_commodities_gold", "items_commodities_gold_desc"),
    "hephaestanite": ("items_commodities_hephaestanite", "items_commodities_hephaestanite_desc"),
    "iron": ("items_commodities_iron", "items_commodities_iron_desc"),
    "laranite": ("items_commodities_laranite", "items_commodities_laranite_desc"),
    "lindinium": ("items_commodities_lindinium", "items_commodities_lindinium_des"),
    "ouratite": ("items_commodities_ouratite", "items_commodities_ouratite_desc"),
    "quartz": ("items_commodities_quartz", "items_commodities_quartz_desc"),
    "riccite": ("items_commodities_riccite", "items_commodities_riccite_des"),
    "savrilium": ("items_commodities_savrilium", "items_commodities_savrilium_des"),
    "silicon": ("items_commodities_silicon", "items_commodities_silicon_desc"),
    "stileron": ("items_commodities_stileron", "items_commodities_stileron_des"),
    "taranite": ("items_commodities_taranite", "items_commodities_taranite_desc"),
    "tin": ("items_commodities_tin", "items_commodities_tin_desc"),
    "titanium": ("items_commodities_titanium", "items_commodities_titanium_desc"),
    "torite": ("items_commodities_torite", "items_commodities_torite_des"),
    "tungsten": ("items_commodities_tungsten", "items_commodities_tungsten_desc"),
}

# Build output
out = {}
for commodity in sorted(commodity_items.keys()):
    if commodity not in commodity_loc:
        continue
    name_key, desc_key = commodity_loc[commodity]

    base_name = loc.get(name_key, "")
    if base_name:
        out[name_key] = f"{base_name} <EM4>[CF]</EM4>"

    base_desc = loc.get(desc_key, "")
    if base_desc:
        condensed = condense_items(commodity_items[commodity])
        bp_block = "\\n".join(f"- {line}" for line in condensed)
        stats_block = f"== Blueprint Data ==\\n{bp_block}"
        out[desc_key] = f"{base_desc}\\n\\n{stats_block}"

output_dir = base_ini.parent if base_ini.parent.exists() else APP_CACHE_DIR
output_path = output_dir / "commodity_crafting_enhancements.ini"
write_ini(output_path, out)
print(f"Written {len(out)} entries to {output_path}")

# Preview
for key in ["items_commodities_iron", "items_commodities_iron_desc",
            "items_commodities_hephaestanite", "items_commodities_hephaestanite_desc"]:
    if key in out:
        val = out[key].replace("\\n", "\n")
        print(f"\n{key}:\n  {val[:400]}")
