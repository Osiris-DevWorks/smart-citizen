"""
dataforge_diff.py — Diff-cache for the DataForge XML cache.

Usage
-----
After unforge writes the cache, call `update_manifest` to snapshot it.
Before running enhancement generators, call `dirty_categories` to find
out which ones actually need to re-run.

    from utils.dataforge_diff import update_manifest, dirty_categories

    # In EnhancementsGeneratorWorker / pak_extractor, after extraction:
    update_manifest(cache_dir)

    # Before each generator run:
    dirty = dirty_categories(cache_dir)
    # dirty == None  →  no prior manifest; run everything
    # dirty == set() →  nothing changed; skip everything
    # dirty == {"ships", "missions"} →  only re-run those two
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Optional

from src.utils.win_paths import win_long_path

logger = logging.getLogger(__name__)

MANIFEST_FILE = ".diff_manifest.json"

# Default parallel workers for the per-file hash sweep. ~31k tiny XMLs on
# Windows hit Defender / Search Indexer / OneDrive on every open, so the
# work is I/O-bound, not CPU-bound; oversubscribing past CPU count helps.
_HASH_WORKERS = max(8, (os.cpu_count() or 4) * 2)

# Maps category name → DataForge subtree prefixes it reads from.
# Mirrors DATAFORGE_KEEP_SUBPATHS in pak_extractor.py — keep in sync.
CATEGORY_SUBTREES: dict[str, list[str]] = {
    "ships":       ["entities/ships", "entities/spaceships"],
    "components":  ["entities/itemports", "entities/scitem"],
    "ship_weapons":["entities/scitem/weapons/spacecraft"],
    "fps_weapons": ["entities/scitem/weapons/fps"],
    "missions":    ["entities/missions", "libs/foundry/records/missions", "reputation/standings"],
    "commodities": ["entities/scitem/cargo", "libs/economy"],
    "journal":     ["libs/foundry/records/journal"],
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _hash_file(path: Path) -> str:
    """SHA-256 of file content, hex-encoded."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _build_snapshot(
    cache_dir: Path,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> dict[str, dict]:
    """
    Walk the dataforge cache and return a snapshot dict:
        { "relative/path.xml": {"mtime": float, "sha256": str}, ... }

    Hashes every XML in parallel — the cache holds ~31k XMLs and a
    serial sweep over them costs minutes on Windows because each
    file-open is intercepted by Defender / Search Indexer / OneDrive.
    A bounded ThreadPoolExecutor brings that down to seconds-to-tens.

    Optional ``progress_callback`` receives ``(completed, total, label)``
    so callers can drive a determinate progress bar; without it the
    sweep runs silently. Progress is throttled to roughly every 256
    completions to keep the Qt event loop unbloated.
    """
    # Enumerate first so we know the total up front for progress reporting.
    paths: list[tuple[Path, str]] = []
    for root, _, files in os.walk(cache_dir):
        for fname in files:
            if not fname.endswith(".xml"):
                continue
            abs_path = Path(root) / fname
            rel = str(abs_path.relative_to(cache_dir)).replace("\\", "/")
            paths.append((abs_path, rel))

    total = len(paths)
    if progress_callback:
        progress_callback(0, total, f"Snapshotting cache for diff (0/{total})…")

    snapshot: dict[str, dict] = {}
    if total == 0:
        return snapshot

    def _hash_one(item: tuple[Path, str]) -> tuple[str, dict]:
        abs_path, rel = item
        return rel, {
            "mtime": abs_path.stat().st_mtime,
            "sha256": _hash_file(abs_path),
        }

    completed = 0
    next_report = 256
    with ThreadPoolExecutor(max_workers=_HASH_WORKERS) as pool:
        for fut in as_completed(pool.submit(_hash_one, item) for item in paths):
            rel, entry = fut.result()
            snapshot[rel] = entry
            completed += 1
            if progress_callback and completed >= next_report:
                progress_callback(
                    completed, total,
                    f"Snapshotting cache for diff ({completed}/{total})…",
                )
                next_report = completed + 256

    if progress_callback:
        progress_callback(total, total, f"Snapshotting cache for diff ({total}/{total})…")
    return snapshot


def _manifest_path(cache_dir: Path) -> Path:
    return cache_dir / MANIFEST_FILE


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def update_manifest(
    cache_dir: Path,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> None:
    """
    Snapshot the current state of the DataForge cache and persist it.
    Call this *after* a successful extraction so the next run can diff
    against it.

    ``progress_callback(completed, total, label)`` is forwarded to the
    underlying snapshot sweep. The sweep is the long-running part —
    SHA-256 of ~31k files — so wiring this in is the difference between
    a frozen progress bar and a moving one.
    """
    # Long-path safety for the hash sweep below — see win_paths.win_long_path
    # (#221; this is the post-extraction snapshot pass where the crash was
    # originally reported).
    cache_dir = Path(win_long_path(cache_dir))
    snapshot = _build_snapshot(cache_dir, progress_callback=progress_callback)
    # The hash sweep above reports 100% the instant it finishes, but writing
    # ~31k entries out is itself not instantaneous — without this the bar
    # sat pinned at "100%"/full width while the JSON write was still going,
    # reading as frozen. Drop back to indeterminate with a distinct label so
    # it's visibly still doing something until the write actually completes.
    if progress_callback:
        progress_callback(0, 0, "Writing diff manifest…")
    with open(_manifest_path(cache_dir), "w", encoding="utf-8") as f:
        # Compact (no indent) — this file is machine-read only, and skipping
        # pretty-printing cuts the write time for ~31k entries noticeably.
        json.dump(snapshot, f)


def dirty_categories(cache_dir: Path) -> Optional[set[str]]:
    """
    Compare the current DataForge cache against the stored manifest and
    return the set of category names whose source XMLs have changed.

    Return values:
        None        — no prior manifest exists; treat all categories as dirty
        set()       — nothing changed; all generators can be skipped
        {"ships", …} — only these categories need to re-run
    """
    cache_dir = Path(win_long_path(cache_dir))
    manifest_file = _manifest_path(cache_dir)

    if not manifest_file.exists():
        return None  # first run — regenerate everything

    try:
        with open(manifest_file, encoding="utf-8") as f:
            old: dict[str, dict] = json.load(f)
    except (OSError, ValueError) as e:
        # ValueError covers both JSONDecodeError and UnicodeDecodeError — a
        # corrupt manifest (#251 bug class) previously crashed the whole
        # enhancements run. Treat it like a missing manifest: regenerate
        # everything, and update_manifest rewrites a clean one afterwards.
        logger.warning(f"Unreadable diff manifest {manifest_file} ({e}); regenerating all")
        return None

    new = _build_snapshot(cache_dir)

    # Find changed paths (added, removed, or different hash)
    all_paths = set(old) | set(new)
    changed: set[str] = set()
    for rel in all_paths:
        if rel not in old or rel not in new:
            changed.add(rel)  # added or removed
        elif old[rel]["mtime"] != new[rel]["mtime"]:
            # mtime differs — confirm with hash before marking dirty
            if old[rel]["sha256"] != new[rel]["sha256"]:
                changed.add(rel)

    if not changed:
        return set()  # clean — skip all generators

    # Map changed paths → categories
    dirty: set[str] = set()
    for rel_path in changed:
        for category, subtrees in CATEGORY_SUBTREES.items():
            if any(rel_path.startswith(prefix) for prefix in subtrees):
                dirty.add(category)
                break

    return dirty