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
# doc. This plan covers Smart Citizen 3.1.0 (the diff over its 3.0.1 base).
#
# Keep each item under ~190 characters. tests/test_test_plan.py chunks the
# submitted report at a 200-char limit and asserts every line survives intact,
# so a longer item fails that test rather than just wrapping awkwardly.
TEST_SECTIONS: list[dict] = [
    {
        "title": "Core workflow (smoke)",
        "items": [
            "Launch the app: it opens to the strings table with no crash dialog.",
            "Edit a string's Custom Value, then Apply to Game; confirm the change shows in game.",
            "Upgrade over 3.0.1: settings, user.ini, owned blueprints and backups survive.",
            "In this Test Plan, type a note under an item and restart: it is still there, and Copy Report shows it under that item.",
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
        "title": "Smart Sync (#567)",
        "items": [
            "Two PCs, Smart Sync on both pointed at one cloud-synced folder: on A mark a blueprint Owned and edit a string. B shows both, and its Apply button turns red.",
            "Change a setting on A (e.g. Theme to Light), then restart B: B uses it.",
            "After each sync that changes B, B's backups\\smart-sync folder has a new zip, and only the newest 5 are kept.",
            "Turn on Smart Sync on a third PC with that folder: it takes the shared settings, string edits and Owned blueprints.",
        ],
    },
    {
        "title": "Minimize to Tray (#577)",
        "items": [
            "Tick Minimize to Tray on the Config tab and minimise: the window goes to the tray. Start Smart Citizen again: the hidden window comes back, no second copy.",
        ],
    },
    {
        "title": "Generated text in your language (#579)",
        "items": [
            "Select German and Generate Enhancements: ship stats, mission details and journal lines in the table are in German.",
        ],
    },
    {
        "title": "Linked channel folder (#595)",
        "items": [
            "With PTU linked to LIVE, install over 3.0.1 with Launch Smart Citizen ticked: the app opens with no WinError 448 and is not running as admin.",
        ],
    },
    {
        "title": "Simple mode Overlay button",
        "items": [
            "In Simple mode, click Start Overlay: the overlay starts and the button reads Stop Overlay. Click it: the overlay stops.",
        ],
    },
    {
        "title": "[BP Complete] mission tag",
        "items": [
            "Generate with Missions ticked, own every blueprint a mission rewards, then Apply: in game that mission's title reads [BP Complete] in place of [BP].",
        ],
    },
    {
        "title": "Karolinger Guides footer (#602)",
        "items": [
            "Click the Karolinger Guides logo in the footer: a page opens in your browser. The logo matches the Osiris DevWorks logo's size and gold.",
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
        "title": "Overlay: scans and screens (#573, #592)",
        "items": [
            "Game on your second monitor: start the overlay. The drawer docks on the game's screen and a rock scan still reads.",
            "Open a cargo inventory showing a µSCU amount with the overlay on: no scan label pops up. Then scan a rock: it reads as usual.",
        ],
    },
    {
        "title": "Overlay: drawer after a screen change (#583)",
        "items": [
            "Start the overlay, drawer closed at middle right. Change the Windows display scale (e.g. 100% to 150%): within a second the drawer is back against the right edge at its usual size.",
            "Open the drawer and change the scale back: it stays open and docks back against the edge.",
            "With the overlay running, change the screen resolution: the drawer docks back against its edge, fully on the screen.",
            "Drawer at bottom right: turn taskbar auto-hide on, then off. The drawer moves down to the screen's bottom edge, then back up above the taskbar.",
            "Windows 10 only: move the taskbar to the right edge, then back to the bottom. Each time the drawer docks beside the taskbar, never under it.",
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
