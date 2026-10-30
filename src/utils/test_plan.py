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
# doc. This plan covers Smart Citizen 3.0.0 (the diff over its 2.4.0 base).
#
# Keep each item under ~190 characters. tests/test_test_plan.py chunks the
# submitted report at a 200-char limit and asserts every line survives intact,
# so a longer item fails that test rather than just wrapping awkwardly.
TEST_SECTIONS: list[dict] = [
    {
        "title": "Core workflow (smoke)",
        "items": [
            "Launch the app: it opens to the strings table with no crash dialog.",
            "Config tab: Extract from Data.p4k, then Generate Enhancements; the DataForge progress bar keeps moving start to finish and the table reloads.",
            "Generate Enhancements, edit a string's Custom Value, then Apply to Game; confirm the change shows in-game.",
            "Restore Backup (More menu): a previous global.ini is offered and restores cleanly.",
        ],
    },
    {
        "title": "Overlay: mining scan decoder (#474, #523)",
        "items": [
            "Run the game borderless windowed. Overlay tab: Start Overlay. Scan a rock: the label under the radar shows the deposit (e.g. 3 × Lindinium).",
            "Scan a ship wreck: the label shows Salvage. Scan an ROC or hand-mining deposit: it decodes too.",
            "Try each Scan text size (Small to Extra large): the label resizes and stays centred under the scan number.",
            "Drawer Minerals: tick a mineral, then scan it. The label glows and flashes; with Play a sound on, it chimes once, not again while it stays.",
            "Turn on Change text color and Bigger text: a watched scan shows green and larger. Tick Salvage at the bottom of the list: a wreck alerts too.",
            "Set Font size Large (Config tab) and restart: the scan decoder still reads signatures.",
            "Play 30 minutes with the overlay running: no Easy Anti-Cheat warning or kick.",
        ],
    },
    {
        "title": "Overlay: drawer (#474, #523)",
        "items": [
            "Click a drawer tab to open its section, click it again to close. Try a few Drawer position spots: the drawer moves there.",
            "Set a Drawer hotkey (e.g. Ctrl+Alt+B). In game, press it: the drawer opens on the section used last; press again: it closes.",
            "Blueprints: search an item, tick it owned. The Blueprint Tracker tab shows it under Owned.",
            "Minerals: type a mineral: its locations show grouped by star system. Type a location: its minerals show.",
            "Generate with Commodities ticked. Crafting: type a mineral to see items that use it, or an item to see its minerals.",
            "Turn off one section on the Overlay tab: its tab leaves the drawer. Turn the drawer off: the drawer is gone.",
            "Mark new blueprints as owned on: receive a blueprint in game while the overlay runs. It moves to Owned without a scan.",
        ],
    },
    {
        "title": "Blueprints (#416, #527)",
        "items": [
            "Scan Logs for Owned Blueprints: the P4-AR Rifle, S-38 Pistol, their magazines and the four Field Recon Suit pieces are added to Owned.",
            "Their tooltip and the Mission filter show Default blueprint (every player has it), in the selected language.",
            "Move a starter back to Available and scan again: it stays in Available.",
            "When a scan ends, the status bar shows its result, not Finishing up….",
        ],
    },
    {
        "title": "Extraction (#483, #507, #482, #490, #491, #494, #517, #484, #522, #529)",
        "items": [
            "Clear Cache (More menu), then Generate Enhancements: the DataForge extraction is noticeably faster than in 2.4, and the stats still appear.",
            "During a DataForge extraction, press Esc and pick Run in Background: progress moves to the status bar and the folder, channel and language settings lock.",
            "When that background run ends, the settings unlock and the table reloads. Pick Stop on another run: the previous cache still works.",
            "Generate Enhancements, press Esc: the same Stop / Run in Background choice appears.",
            "Point the DataForge cache folder at a nearly full drive and Generate: one message names the drive, what's free and what's needed.",
            "Pick a DataForge cache folder Windows refuses (e.g. under C:\\Windows): one message says why and the old folder is kept.",
            "Make the cache folder a junction to another folder and Generate: the extraction refuses, naming the link, and nothing is deleted.",
            "While the RSI Launcher patches or verifies, click Extract from Data.p4k: it says Star Citizen is updating. With only the game running, it extracts.",
        ],
    },
    {
        "title": "Generation, cache and closing (#476, #478, #479, #486)",
        "items": [
            "Close the app during Generate Enhancements: it closes without a hang. On the next start it offers to regenerate.",
            "After a game patch, Extract from Data.p4k: when it finishes it asks whether to update the out-of-date DataForge cache.",
            "More menu, Clear Cache: it finds the DataForge cache in its real folder and clears it.",
        ],
    },
    {
        "title": "Edits and categories (#531, #532)",
        "items": [
            "Clear a Custom Value you had set, then Generate Enhancements (which reloads): the value stays cleared.",
            "Reset user.ini, then Restore user.ini: the overrides come back.",
            "Tick a new category on the Enhancements tab without its small Apply, then Generate: the new category is included.",
            "Tick a category, switch tabs and come back: the tick is still pending and Apply Enhancements is red.",
        ],
    },
    {
        "title": "Languages (#502, #514, #535)",
        "items": [
            "Select French, then switch channel, or change the data folder: the game strings stay French, not English.",
            "Select French, then Extract from Data.p4k: the game strings stay French.",
            "Select Russian: the UI, Help and About are Russian and the game strings load. Apply and launch: Russian shows in game.",
            "Apply Russian, then apply Korean: Korean replaces Russian in game (the two share one game slot).",
            "In each other language, Help and About mention the Overlay tab, armor tags and Font size.",
        ],
    },
    {
        "title": "Armor tags and font size (#492, #475)",
        "items": [
            "Enhancements tab, Tag Builder, Armor tab: the brackets list has no None. Generate with Gear: armor names carry [L], [M] or [H].",
            "Scan Logs after receiving armor in game: the tagged armor still shows under Owned.",
            "Config tab, Font size Small then Large: it offers to restart, and after the restart the whole window scales with nothing cut off.",
        ],
    },
    {
        "title": "Installer (#455)",
        "items": [
            "With the data folder on OneDrive, upgrade and answer YES to the OneDrive warning: on first start the data is in the new local folder.",
            "Answer NO instead: the data stays on OneDrive and nothing moves.",
            "Upgrade over 2.4.0: settings, user.ini, owned blueprints and backups survive.",
        ],
    },
    {
        "title": "Portable build",
        "items": [
            "Unzip the portable build into a deep folder path (several nested folders), run it, extract, generate and apply: no path-length errors.",
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


def build_report(checked, tester_name: str, version: str, notes: str = "") -> str:
    """Render the tester's run as a markdown report (clipboard or Discord).

    Shows overall and per-section progress and a ✅/⬜ line per item, so a
    reader sees exactly what was and wasn't verified.
    """
    checked = set(checked)
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
            mark = "✅" if item_key(s, i) in checked else "⬜"
            lines.append(f"{mark} {text}")
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
