"""The tester test-plan: content, progress math, and report formatting (#144).

Smart Citizen ships a "Test Plan" panel so testers on a pre-release build can
work through what changed in the release and check items off as they verify
them. This module is the Qt-free core: the plan content itself, the
progress/key helpers, and the markdown report a tester submits. The Qt panel
(`src/gui/test_plan_panel.py`) and the Discord-submit worker
(`TestPlanSubmitWorker` in `src/gui/workers.py`) build on these.

The content tracks the diff that the active release branch carries over its
integration base, so each release's plan covers exactly what's new. Update
TEST_SECTIONS when a release's scope changes; `plan_hash()` changes with it, so
a tester's stale check-marks are dropped rather than silently mislabelled.
"""
from __future__ import annotations

import hashlib
import json

# Each section is a title plus a flat list of one-line test items. Keep items
# imperative and self-contained ("do X, confirm Y") so a tester needs no other
# doc. This plan covers Smart Citizen 3.0.1 (the diff over its 3.0.0 base).
#
# Keep each item under ~190 characters. tests/test_test_plan.py chunks the
# submitted report at a 200-char limit and asserts every line survives intact,
# so a longer item fails that test rather than just wrapping awkwardly.
TEST_SECTIONS: list[dict] = [
    {
        "title": "Core workflow (smoke)",
        "items": [
            "Launch the app: it opens to the strings table with no crash dialog.",
            "Config tab: Extract from Data.p4k, then Generate Enhancements; the progress bar keeps moving and the table reloads.",
            "Edit a string's Custom Value, then Apply to Game; confirm the change shows in game.",
            "Upgrade over 3.0.0: settings, user.ini, owned blueprints and backups survive.",
        ],
    },
    {
        "title": "Play button reminder (#566)",
        "items": [
            "Apply in English and start the game: the main menu's Play button has a second line, Run Smart Citizen after every patch, centred under the first.",
            "Apply twice and start the game: the reminder shows once, not twice.",
            "Apply in Japanese, Korean or Russian and start the game: both lines on the Play button are centred.",
        ],
    },
    {
        "title": "Apply when Windows blocks the game file",
        "items": [
            "Right-click the game's global.ini, tick Read-only, then Apply: it works, and the file is no longer read-only.",
            "Start Star Citizen, then Apply: the box says the game is running and to close it.",
            "With the game in Program Files, turn on Controlled folder access in Windows Security, then Apply: the box lists the steps to try instead of an Errno 13 error.",
        ],
    },
    {
        "title": "Blueprint scan in other languages (#564)",
        "items": [
            "Select Spanish, apply, and receive a blueprint in game. Scan Logs for Owned Blueprints: it is added to Owned.",
            "With the overlay running in Spanish and Mark new blueprints as owned on, receive a blueprint: it moves to Owned without a scan.",
            "In English, Scan Logs for Owned Blueprints: it finds the same blueprints as 3.0.0 did.",
        ],
    },
    {
        "title": "Overlay: Order tab (3.1.0)",
        "items": [
            "Extract DataForge, then generate with Commodities ticked. Drawer Order tab: search an item and click it. It shows as a line, and the Order summary at the top lists its materials.",
            "Add the same item again: its count goes up, with no second line. Use - and + and the X: the count and the summary follow.",
            "Open a line: each slot shows its material and amount. Drag a quality slider: the stat bonuses change, and the summary splits that material by quality.",
            "Compare one blueprint with RK Crafting Central: same materials, amounts and stat bonuses at the same qualities.",
            "Show SCU and Show cSCU switch the amounts. Copy, then paste in Discord: the order and its materials.",
            "Watch minerals: the Minerals tab ticks the order's minerals. New order needs a second click, and its Sure? stays on screen.",
            "Restart the app: the order is still there.",
            "Search NDB-30 (and other items you know): they show whether you own them or not. Tick Owned only: only owned blueprints are listed.",
            "With the overlay running, mark a blueprint owned in the Blueprint Tracker tab: the Order card's not-owned mark goes at once.",
            "Type a name, click Save, then New order. Pick the name under Saved orders and click Load: the order comes back. The file is in your data folder under orders.",
            "Pick a saved order and click Delete twice: the name leaves the list and the order you built stays.",
            "Open an item made of an ore: its slider has tick marks and stops only on them, and the label shows the tier (e.g. Q 786 (C)).",
            "Untick Snap to ore qualities: the ticks go and the slider takes any quality, e.g. Q 650. Tick it again: each slider snaps back to a tier. Restart: the choice is kept.",
        ],
    },
    {
        "title": "Overlay: Item Finder (#606)",
        "items": [
            "Start the overlay and open the magnifying glass tab: the bottom line says where the shop data is from and when it was updated.",
            "Type an item (e.g. P4-AR): matches show with a shop count. Expand one: its shops are grouped by star system, cheapest first in each.",
            "Hover a shop: the tooltip shows its full place and price. Long item and shop names wrap onto a second line, not cut off.",
            "Type a single exact item name: its match opens by itself. Type a nonsense name: the tab says no shop sells it.",
            "Turn off your internet and restart the app and overlay: the finder still works from the saved copy and says UEX could not be reached.",
            "Turn Item Finder off on the Overlay tab: its tab leaves the drawer.",
        ],
    },
    {
        "title": "Owned names after a language switch (#569, #570)",
        "items": [
            "Upgrade with an existing Owned list and open the Blueprint Tracker: no owned blueprint is lost.",
            "With some blueprints owned, switch English to Spanish: Owned shows them under their Spanish names, none listed twice or back in Available.",
            "Switch back to English: Owned shows the English names again.",
            "A Spanish Owned list that showed the S-38 Pistol twice (English and Spanish) shows it once after the upgrade.",
            "Export Owned Blueprints in English, switch to Spanish, Import it: every blueprint matches, none skipped.",
        ],
    },
    {
        "title": "Overlay: closing the drawer with its tab (#585)",
        "items": [
            "In game, hold F, click a drawer tab, click an item in it, then click the same tab to close it: keys and a single click work in game at once.",
            "In game, open the drawer with its hotkey, click an item with F held, then close it with the hotkey: keys and a single click work in game at once, as in 3.0.0.",
        ],
    },
    {
        "title": "Overlay: scan decoder (#546, #563)",
        "items": [
            "Golem or Prospector, HDR off: scan rocks; the label shows the deposit as in 3.0.0.",
            "Scan on a bright planet or in snow (e.g. Microtech), and with Windows HDR on if you have it: the label still reads.",
            "Set the field of view to its maximum and scan: the label still reads.",
            "Aurora at 1080p: scan a rock; the label reads. Note your ship and resolution if it does not.",
        ],
    },
    {
        "title": "Overlay: drawer while aiming (#582)",
        "items": [
            "Drawer at top right, in game: aim with the pointer hidden and shoot across the drawer and the screen corner. The game keeps focus and every shot fires.",
            "Hold F (or open the mobiGlas) and click a drawer tab: it opens. Click back into the game, then aim and shoot over the drawer: the game keeps focus.",
            "With the Smart Citizen window in front, click a drawer tab: it opens as in 3.0.0.",
            "Windows scale at 125% or 150%, drawer at middle right: click the drawer's outermost edge pixels; a tab opens each time.",
            "Two screens at different scales, the second to the right: open and close the drawer at middle right; it stays on the main screen at its usual size.",
        ],
    },
    {
        "title": "Overlay: drawer hotkey (#587)",
        "items": [
            "Set a drawer hotkey on the Overlay tab and start the overlay. In game, press it: the drawer opens. Hold F to use it, then press the hotkey again: it closes.",
            "In game, press the hotkey's key alone, or with one modifier more than it has (Ctrl+Alt+8 for Alt+8): the drawer stays as it is.",
            "With the Smart Citizen window in front, press the hotkey: the drawer opens in front. Press it again: it closes.",
            "Set Pause as the drawer hotkey and start the overlay. In game, press Pause: the drawer opens. Press it again: it closes.",
            "Alt-Tab into the game and at once press the hotkey, holding it a moment: the drawer opens.",
        ],
    },
    {
        "title": "Enhancements (#555, #561)",
        "items": [
            "Generate with Commodities ticked. Point a mining tool at an unfractured Aphorite, Dolivine or Hadanite rock: its HUD name carries the [CF] tag.",
            "Generate with Ships ticked. Open the Carrack's map: room labels show no ship stats.",
            "Generate with every category ticked: it finishes with no error and the mission contracts carry their details.",
        ],
    },
    {
        "title": "Mission ships and cooldowns (3.1.0)",
        "items": [
            "Upgrade from 3.0.x and start the app: it asks to extract DataForge again. Say Yes and let it generate.",
            "Enhancements tab: beside Hostiles, Ships per type reads 8 and offers 4 to 128 and All. Unticking Hostiles greys it out.",
            "Find an Eckhart Ship Ambush (Medium): Hostiles lists ships by name, one heading per variant, e.g. Targets: 1x of Argo RAFT, Drake Cutlass Black, or MISC Freelancer MIS.",
            "At 8, find Stand Our Ground (Headhunters, Very Hard): each variant's groups read Wave 1, Wave 2, ..., one line each, with type names.",
            "In that mission, Ship types under Friendlies lists each type biggest first: up to 8 ships, or 3, (… N others), 3.",
            "Pick 4 and generate: each big type reads largest, (… N others), smallest. Pick All: every ship is listed.",
            "Find Tactical Strike Group Needed: its waves read Wave 1 to Wave 8, each on one line, and name the RSI Constellation Mk IV Andromeda.",
            "Find Gilly's Combat Gauntlet part 7: its wave names the Aegis Hammerhead.",
            "Find a Headhunters claim sweep: a ship no real model matches reads as a kind, e.g. 1x Very Easy Ninetails ship, with no brackets.",
            "Missions with ground enemies still list them with a count, e.g. Soldiers x6, in the same list.",
            "Mission details carry a Cooldown line: e.g. 15 min, or None. An abandon time of 1 min is left out; a longer one shows, e.g. None (abandon: 2 min).",
            "Find Ambush Op (HeadHunters, Medium): no Ace Pilots or Hostile Allies line, no Ace Pilot line, and no [ACE?] in its title.",
            "Its variants are named, not numbered: Hostiles (Stanton, Pyro), Hostiles (Nyx), Hostiles (Nyx, Vanduul), and the Cooldown line names them the same way.",
            "Find Crash some ships (Headhunters, Medium): a Regions block after the flavour text, e.g. Pyro Region B: Bloom; Orbituary, Starlight Service Station.",
            "In that mission, blueprint headers read [Pyro Region A] and Hostiles read (Pyro Regions B, C, D). No mission text says Pyro RegionA any more.",
            "Rat's Nest, Rod's Fuel and the Terminus stops other than Ruin Station appear on no Regions line (they carry no region tag).",
            "Find a CFP security patrol: it lists Ace Pilots (5% chance), its title reads [ACE?], Ace Pilot reads 5% chance, and the CHCO Auris PDC Monitor shows.",
            "Find a CleanAir ship escort: its two Reinforcements lines read Reinforcements 1 and Reinforcements 2. A Headhunters claim sweep lists Prospectors once, 4x.",
            "Find an IASI patrol: a type reads Criminal Combat Rating 2 ship (not Raiting2), numbered ship 1 and ship 2 where two pools differ, each listed under Ship types.",
            "In that patrol, Targets 2 reads 3x Criminal Combat Rating 2 ship 1, not 1x ... ship 1 and 2x ... ship 1. No line names one ship type twice.",
            "Find a Headhunters ship ambush (Easy): Hostiles (Stanton, Nyx, Pyro) and Hostiles (Nyx, Vanduul); Cooldown reads Stanton, Nyx, Pyro: 15 min; Nyx, Vanduul: 1 h.",
            "Without the tag tree (before the first extraction), a wave that spawns 3 or 4 ships reads Hostile Wave x3-4, not every option added up.",
            "Enhancements tab: untick Cooldown, then Hostiles, and generate: each line leaves the mission text.",
            "Select German and generate: ship names come from the German strings and the words (Abklingzeit, oder, Welle, eines von) are German.",
        ],
    },
    {
        "title": "What's New pop-up (3.1.0)",
        "items": [
            "Install over 3.0.1 and start the app: once the update check is done, What's New opens with the 3.1.0 notes, no download or Windows blocks text at the top.",
            "Close it and restart the app: What's New does not open again.",
            "Fresh install on a PC that never had Smart Citizen: What's New opens once on the first start.",
            "Select German and restart after a fresh install: the title, line and button are in German; the notes stay English.",
            "When it offers an update, take it: after the update, What's New shows the new version's notes.",
        ],
    },
    {
        "title": "Guided tour (#545)",
        "items": [
            "Start the guided tour: it has 21 steps, including Settings Backup and Star Citizen Tools, and each step points at the right control.",
        ],
    },
    {
        "title": "README badges (#601)",
        "items": [
            "Open the README on GitHub: a row of five badges sits under the title (Windows, Linux (Wine), version, license, VirusTotal).",
            "Click the Linux (Wine) badge: it opens the Linux guide. Click the version badge: it opens Releases.",
            "After the 3.1.0 release is published: the version badge reads v3.1.0 and the VirusTotal badge opens the 3.1.0 installer's scan.",
            "The 3.1.0 release notes on GitHub have no VirusTotal links added at the end.",
        ],
    },
    {
        "title": "CSV export and import (#565)",
        "items": [
            "Filter the String Editor to Missions, then More > Export CSV: the saved file holds only the rows the table showed, in the same order.",
            "Open the CSV in Excel: accents and other scripts show right, and the columns are Key, Category, Default Value, Current Value, Custom Value, Status.",
            "Fill in Custom Value on a few rows, save as CSV, then More > Import CSV: the box counts the new keys and the skipped rows; after Yes those rows show Modified.",
            "Save the CSV from Excel as plain CSV (not CSV UTF-8) with a ; separator and import it: it still reads.",
            "Import a CSV whose Custom Value matches a row's Current Value (an Enhanced row): it is skipped and the row stays Enhanced.",
            "Import a CSV that changes a key you already edited: the conflict box opens, as it does for Import INI.",
            "Import a CSV with no Key or Custom Value column: one box says what the file needs, nothing changes.",
            "Export INI, then Import INI that same file: nothing to import, and the box says how many were skipped.",
            "Switch to German: both CSV items in More and their tooltips are in German.",
        ],
    },
    {
        "title": "Portable build",
        "items": [
            "Unzip the portable build into a deep folder path, run it, extract, generate and apply: no path-length errors.",
            "Start the overlay from the portable build: it runs and the drawer works.",
        ],
    },
]


def plan_hash() -> str:
    """Short stable digest of the plan content.

    Stored alongside a tester's check-marks; when the plan changes the hash
    changes, so stale marks (now pointing at different items) are discarded.
    """
    blob = json.dumps(TEST_SECTIONS, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def item_key(section_idx: int, item_idx: int) -> str:
    """Stable key for one checklist item (``"<section>:<item>"``)."""
    return f"{section_idx}:{item_idx}"


def all_item_keys() -> list[str]:
    """Every item key in section/item order."""
    return [
        item_key(s, i)
        for s, section in enumerate(TEST_SECTIONS)
        for i in range(len(section["items"]))
    ]


def total_items() -> int:
    return sum(len(section["items"]) for section in TEST_SECTIONS)


def progress(checked) -> tuple[int, int, int]:
    """Return (done, total, percent) for the set of checked item keys.

    Only keys that exist in the current plan count, so a stale/foreign key
    can't push the count past the total.
    """
    valid = set(all_item_keys())
    done = sum(1 for k in checked if k in valid)
    total = len(valid)
    pct = round(done * 100 / total) if total else 0
    return done, total, pct


def build_report(
    checked,
    tester_name: str,
    version: str,
    notes: str = "",
    item_notes: dict | None = None,
) -> str:
    """Render the tester's run as a markdown report (clipboard or Discord).

    Shows overall and per-section progress and a ✅/⬜ line per item, so a
    reader sees exactly what was and wasn't verified. A tester's note on an
    item (*item_notes*, keyed by ``item_key``) follows that item's line.
    """
    checked = set(checked)
    item_notes = item_notes or {}
    done, total, pct = progress(checked)
    tester = tester_name.strip() or "Anonymous"
    lines = [
        f"**Smart Citizen v{version} - Test Plan Report**",
        f"Tester: {tester}",
        f"Progress: {done}/{total} ({pct}%)",
        "",
    ]
    for s, section in enumerate(TEST_SECTIONS):
        sec_keys = [item_key(s, i) for i in range(len(section["items"]))]
        sec_done = sum(1 for k in sec_keys if k in checked)
        lines.append(f"__{section['title']}__ ({sec_done}/{len(sec_keys)})")
        for i, text in enumerate(section["items"]):
            key = item_key(s, i)
            mark = "✅" if key in checked else "⬜"
            lines.append(f"{mark} {text}")
            note = " ".join(str(item_notes.get(key, "")).split())
            if note:
                lines.append(f"> 📝 {note}")
        lines.append("")
    notes = notes.strip()
    if notes:
        lines.append("__Notes__")
        lines.append(notes)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def discord_chunks(report: str, limit: int = 1900) -> list[str]:
    """Split a report into Discord-message-sized chunks (2000-char hard cap).

    Splits on line boundaries so a markdown line is never cut mid-way. A single
    line longer than *limit* is hard-sliced as a last resort.
    """
    chunks: list[str] = []
    current = ""
    for line in report.split("\n"):
        while len(line) > limit:
            # Pathological single long line: hard-slice it.
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = line if not current else current + "\n" + line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks
