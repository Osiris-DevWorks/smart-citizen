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
# doc. This plan covers Smart Citizen 2.4.0 (the diff over its 2.3.1 base).
#
# Keep each item under ~190 characters. tests/test_test_plan.py chunks the
# submitted report at a 200-char limit and asserts every line survives intact,
# so a longer item fails that test rather than just wrapping awkwardly.
TEST_SECTIONS: list[dict] = [
    {
        "title": "Core workflow (smoke)",
        "items": [
            "Launch the app: it opens to the strings table with no crash dialog.",
            "Config tab: extract DataForge from Data.p4k; the progress bar runs start to finish and the table reloads.",
            "Generate Enhancements, edit a string's Custom Value, then Apply to Game; confirm the change shows in-game.",
            "Restore Backup (More menu): a previous global.ini is offered and restores cleanly.",
        ],
    },
    {
        "title": "Verify Install Location (#385, #429, #440-#442)",
        "items": [
            "Config tab: click Verify Install Location. The dialog names the install the RSI Launcher starts and says whether Smart Citizen points at it.",
            "With a second (or leftover) Star Citizen folder on the PC: both show as cards; a folder with no Data.p4k is marked as unplayable.",
            "Press Use this install on the launcher's install: the Config path and channel list update, and the next Apply lands in that install.",
            "Press Scan all drives with an install in a custom folder: it is found. Cancel a scan midway: the dialog says the list may be short.",
        ],
    },
    {
        "title": "First-run install detection (#429, #453, #438, #439)",
        "items": [
            "Fresh install with Star Citizen in a custom folder: first run finds it from the launcher log rather than asking you to browse.",
            "First run never saves a folder that holds no Data.p4k as the install path.",
        ],
    },
    {
        "title": "Apply button state (#387, #397, #398, #428)",
        "items": [
            "Launch with nothing changed since the last Apply: the Apply button starts green, not red.",
            "Edit a Custom Value: Apply goes red. Apply to Game: it goes green and stays green, and closing gives no unapplied-changes warning.",
            "Simple mode: Apply Enhancements turns the button green afterwards, and closing gives no unapplied-changes warning.",
            "Switch language without applying: Apply goes red, because the game's user.cfg still names the old language.",
            "Make Apply fail (e.g. game running or file read-only): the button stays red for a retry.",
        ],
    },
    {
        "title": "Apply Preview and success counts (#399, #400, #425, #443)",
        "items": [
            "Config tab Apply Preview: the enhancement counts per category match the Apply success dialog for the same run.",
            "First Simple-mode apply on a fresh install: the success dialog reports a non-zero enhancement count.",
        ],
    },
    {
        "title": "Blueprint Tracker scanning (#446, #386, #401)",
        "items": [
            "Scan Logs for Owned Blueprints with PTU selected: it reads LIVE (and HOTFIX if installed), never PTU, EPTU or TECH-PREVIEW logs.",
            "Tick Auto-scan logs on startup and restart: the scan runs on its own and reports in the status bar, with no popup.",
            "Also tick Show popup for new blueprints found by auto-scan: on a restart that finds new ones, the summary popup appears.",
            "The keyword search box sits beneath the dropdown filters.",
        ],
    },
    {
        "title": "Extraction (#471, #473, #402, #389)",
        "items": [
            "Set the DataForge cache folder to another drive and extract: the ~2 GB working folder appears beside it on that drive, not on C:, and is gone when done.",
            "During a DataForge extraction, press Esc or the X: it asks Stop or Cancel. Cancel keeps it running; Stop ends it and the previous cache still works.",
            "Close the app during a DataForge extraction: it asks to stop first, and the extraction tools don't keep running after the app closes.",
            "During Extract from Data.p4k (global.ini), press Esc: the extraction stops, base.ini is unchanged and the status bar says it stopped.",
            "At startup, answer Yes to extract, then press Esc: the app loads your previous strings rather than an empty table.",
            "Generate Enhancements with only one category ticked: it completes without a crash.",
        ],
    },
    {
        "title": "New languages (#404, #367, #403)",
        "items": [
            "Switch to Turkish, then Traditional Chinese: UI, Help and About show in that language and game strings load.",
            "Korean: Map Language File, Browse to a copy of the community global.ini (outside the SC install), switch to Korean: strings load.",
            "Korean: try mapping the global.ini Smart Citizen itself applies in your install: it is refused with an explanation.",
            "Turkish in game: Apply, launch, and confirm Turkish text shows (it uses the game's polish_(poland) slot).",
        ],
    },
    {
        "title": "Settings backup (#383)",
        "items": [
            "Rename a Mission Label, Export Settings, set the label back to default, then Import: the rename comes back. Repeat in reverse: the default comes back.",
        ],
    },
    {
        "title": "Installer and uninstaller (#357, #418, #452, #454, #432, #451, #420, #434, #422)",
        "items": [
            "Install into a folder holding other files: Setup offers <folder>\\Smart Citizen instead, and nothing else in that folder is deleted.",
            "Upgrade over an existing install: settings, user.ini and backups survive; the app relaunches after an in-app auto-update.",
            "Uninstall with Also delete all saved settings unticked: user.ini and backups stay. Ticked: Smart Citizen's data and caches go, nothing else.",
            "With Documents on OneDrive (personal or work/school): the data-folder page suggests a local folder, and cache cleaning runs without errors.",
            "Upgrade from a pre-0.9 install whose data is on OneDrive: the old data folder is kept, not replaced by a new empty one.",
        ],
    },
    {
        "title": "Portable build",
        "items": [
            "Unzip the portable build into a deep folder path (several nested folders), run it, extract and apply: no path-length errors.",
            "Close the app and delete the whole portable folder to the Recycle Bin: the delete succeeds without a path-too-long failure.",
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
