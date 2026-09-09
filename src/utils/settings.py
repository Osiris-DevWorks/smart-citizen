"""Settings management using QSettings."""
import base64
import datetime
import json
import logging
import os
import string
from pathlib import Path

from PyQt6.QtCore import QSettings
import winreg

logger = logging.getLogger(__name__)

_LANG_SOURCES_CACHE: "dict | None" = None


def _bundled_language_sources() -> dict:
    """Load the bundled ``languages/sources.json`` map (language → base.ini URL).

    Cached after the first read. Returns {} if the file is missing or unreadable
    so a packaging hiccup degrades to "no mapped URL" rather than crashing.
    """
    global _LANG_SOURCES_CACHE
    if _LANG_SOURCES_CACHE is None:
        try:
            from src.utils.resource_path import get_resource_path
            path = Path(get_resource_path("languages/sources.json"))
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                _LANG_SOURCES_CACHE = data if isinstance(data, dict) else {}
            else:
                _LANG_SOURCES_CACHE = {}
        except (OSError, ValueError) as exc:
            logger.warning("Could not load languages/sources.json: %s", exc)
            _LANG_SOURCES_CACHE = {}
    return _LANG_SOURCES_CACHE


# Maps our internal language folder name → Star Citizen's language identifier
# used in Localization directory paths and g_language in user.cfg.
SC_LANGUAGE_IDS: dict[str, str] = {
    "english":       "english",
    "french":        "french_(france)",
    "spanish":       "spanish_(spain)",
    "portuguese_br": "portuguese_(brazil)",
    "japanese":      "japanese_(japan)",
    "chinese":       "chinese_(simplified)",
    "italian":       "italian_(italy)",
    "german":        "german_(germany)",
}


def _is_valid_sc_root(path: str) -> bool:
    """Return True if *path* looks like a valid Star Citizen install root.

    Checks whether the directory contains at least one channel subfolder
    (LIVE, PTU, EPTU, HOTFIX, TECH-PREVIEW).  This guards against stale
    registry values like ``SmartCitizen 1.4.1`` being returned as the
    install root.
    """
    try:
        p = Path(path)
        if not p.is_dir():
            return False
        return any((p / ch).is_dir() for ch in (
            "LIVE", "PTU", "EPTU", "HOTFIX", "TECH-PREVIEW"
        ))
    except (OSError, ValueError):
        return False


def _path_ends_in_channel(path: str) -> bool:
    """Return True if *path*'s last component is a recognised channel name.

    Used to distinguish per-channel paths (``...\\LIVE``) from install roots
    (``...\\StarCitizen``).  Case-insensitive match against
    :data:`AppSettings.AVAILABLE_CHANNELS`.
    """
    try:
        name = Path(path).name.upper()
    except (OSError, ValueError):
        return False
    return name in {c.upper() for c in AppSettings.AVAILABLE_CHANNELS}


# Relative install paths under a drive's root, in the order real installs are
# most likely to use them. RSI Launcher's own default is the first two; the
# rest cover users who point the launcher at a secondary drive and either
# keep RSI's own folder shape or nest it under a personal "Games" folder --
# both are common in the wild (a real tester install turned up at
# ``E:\Games\Roberts Space Industries\StarCitizen``, which none of the
# previous hardcoded C:\ candidates could ever have matched).
_COMMON_SC_SUBPATHS = (
    r"Program Files\Roberts Space Industries\StarCitizen",
    r"Program Files (x86)\Roberts Space Industries\StarCitizen",
    r"Roberts Space Industries\StarCitizen",
    r"Games\Roberts Space Industries\StarCitizen",
)


# Sentinel distinct from a real scan outcome — the scan legitimately returns
# None ("nothing found"), so that value can't double as "not run yet".
_SC_SCAN_UNSET = object()
_sc_scan_cache: "str | None | object" = _SC_SCAN_UNSET


def _scan_common_sc_install_locations() -> "str | None":
    """Search every local drive letter for a real Star Citizen install.

    Only a last-resort fallback (see :meth:`AppSettings.get_sc_install_root`)
    -- everywhere else, an explicit setting or a registry trace from the
    installer already told us where the game is. This exists for the case
    none of those do: a portable build's first run, or a fresh profile,
    where the only way to find an install on a non-default drive is to look.
    Cheap in practice -- most drive letters don't exist and short-circuit on
    the very first ``exists()`` check, and a hit is validated the same way
    every other candidate is (:func:`_is_valid_sc_root`), so an empty/stub
    folder (e.g. a partial RSI Launcher download with no real ``Data.p4k``
    channel folder yet) is never mistaken for a real install.

    Cached in-memory for the process's lifetime, including a "found
    nothing" result -- without this, a no-install profile re-walks every
    drive letter on every call (e.g. after each channel switch clears
    GAME_INSTALL_PATH), and a disconnected network drive can make a single
    ``exists()`` check hang for seconds. The cache resets naturally on app
    restart since it's a plain module global, not persisted to settings.
    """
    global _sc_scan_cache
    if _sc_scan_cache is not _SC_SCAN_UNSET:
        return _sc_scan_cache

    candidates: list[str] = []
    for letter in string.ascii_uppercase:
        drive_root = Path(f"{letter}:\\")
        if not drive_root.exists():
            continue
        for subpath in _COMMON_SC_SUBPATHS:
            candidate = drive_root / subpath
            if _is_valid_sc_root(str(candidate)):
                candidates.append(str(candidate))

    if not candidates:
        _sc_scan_cache = None
        return None

    _sc_scan_cache = _pick_live_sc_install(candidates)
    return _sc_scan_cache


def _newest_p4k_mtime(root: str) -> float:
    """Most recent Data.p4k mtime across *root*'s channel folders, or 0.0.

    Every channel is checked rather than LIVE alone: a user who plays PTU
    keeps that channel current while LIVE sits untouched, and picking the
    install by its stalest channel would get the comparison backwards.
    """
    newest = 0.0
    for channel in AppSettings.AVAILABLE_CHANNELS:
        try:
            newest = max(newest, (Path(root) / channel / "Data.p4k").stat().st_mtime)
        except (OSError, ValueError):
            continue
    return newest


def _pick_live_sc_install(candidates: "list[str]") -> str:
    r"""Choose the install the RSI Launcher is actually maintaining.

    The scan used to return its first hit and stop. That is drive-major over
    a subpath list whose first entry is ``Program Files\Roberts Space
    Industries\StarCitizen``, so an abandoned install on an earlier drive
    beat the real one every time. Issue #370 was exactly that: a leftover
    ``D:\Program Files\Roberts Space Industries\StarCitizen`` won over the
    live ``E:\Roberts Space Industries\StarCitizen``, and because the
    orphan's Data.p4k still held an older DataForge database (Game.dcb
    rather than the current Game2.dcb) every downstream step failed in ways
    that pointed anywhere but here. The user was told to verify their game
    files, which did nothing, because the launcher was dutifully verifying
    the install we were not reading.

    Newest Data.p4k wins. An abandoned install's archive is frozen at
    whenever it stopped being patched, while the live one moves with every
    game update, so recency is the one signal that separates them without
    asking the launcher where it thinks the game is. Ties and unreadable
    timestamps fall back to the original scan order, so a single-install
    machine behaves exactly as before.

    Every candidate is logged either way. The heuristic can still be wrong,
    and when it is, a support log that names the alternatives turns a long
    diagnostic thread into one line someone can read.
    """
    # One filesystem walk per candidate, reused for both the ranking and the
    # log line below. Calling _newest_p4k_mtime again while building the
    # message would not just double the stat calls; it would read the disk a
    # second time, so the install we ranked and the date we report could
    # disagree about the same folder.
    mtimes = {c: _newest_p4k_mtime(c) for c in candidates}
    ranked = sorted(candidates, key=lambda c: -mtimes[c])
    chosen = ranked[0]
    if len(candidates) > 1:
        listing = ", ".join(
            f"{c} (Data.p4k "
            + (
                datetime.datetime.fromtimestamp(mtimes[c]).strftime("%Y-%m-%d")
                if mtimes[c] else "none"
            )
            + ")"
            for c in ranked
        )
        logger.warning(
            f"Multiple Star Citizen installs found; using the one with the "
            f"newest Data.p4k: {chosen}. All candidates: {listing}. If the "
            f"wrong one was picked, set the install path in the Config tab."
        )
    else:
        logger.info(f"Auto-detected Star Citizen install: {chosen}")
    return chosen

class AppSettings:
    """Wrapper around QSettings for application configuration."""

    ORG_NAME = "Osiris DevWorks"
    # QSettings registry node — 0.9.2+ uses "Smart Citizen" to match the
    # product rebrand. Legacy installs at "SC Localization Editor" are
    # migrated on first launch by migrate_registry_appname().
    APP_NAME = "Smart Citizen"
    # The old node name, preserved so the one-shot migration can find it.
    _LEGACY_APP_NAME = "SC Localization Editor"

    # Settings keys - Favorites
    FAVORITE_PREFIX = "favorite_prefix"
    DEFAULT_FAVORITE_PREFIX = "*"

    # Settings keys - Test Plan panel (#144)
    TEST_PLAN_CHECKS = "test_plan/checks"        # JSON: {"hash": ..., "checked": [...]}
    TEST_PLAN_TESTER = "test_plan/tester_name"
    TEST_WEBHOOK_URL = "test_plan/webhook_url"   # falls back to env var when unset
    TEST_WEBHOOK_ENV = "SMART_CITIZEN_TEST_WEBHOOK_URL"

    # Settings keys - Mission labels
    REP_XP_LABEL = "rep_xp_label"
    MISSION_HEADER_DETAILS = "mission_header/details"
    MISSION_HEADER_BLUEPRINTS = "mission_header/blueprints"
    MISSION_HEADER_ITEMS = "mission_header/items"
    MISSION_HEADER_BLUEPRINT_DATA = "mission_header/blueprint_data"
    MISSION_HEADER_EM_TAG = "mission_header/em_tag"

    # Mission label defaults — source of truth for fallback values
    DEFAULT_REP_XP_LABEL = "Rep"
    DEFAULT_MISSION_HEADER_EM_TAG = "EM3"
    # Selectable emphasis tags. EM1/EM2 were removed in 1.5.0 — they never
    # render in-game (only EM3 = underline and EM4 = color do). See issue #99.
    MISSION_HEADER_EM_TAGS = ("EM3", "EM4")

    # Mission detail fields (#121): which generated lines appear in a mission
    # DETAILS body. All default on (the pre-#121 behaviour). Baked at
    # generation time, so a change takes effect on the next Generate
    # Enhancements run.
    # NOTE: the 2.0 "route" field moved to the Mission Titles Tag Builder tab in
    # 2.1 (route arrow / placement / location detail live there now), so it is
    # no longer a mission-detail toggle. migrate_route_toggle_to_mission_titles()
    # carries a user's old off-state into the new config.
    # "blueprint_tag" moved out entirely (2.2.0) — it never controlled a body
    # line, only the [BP]/[BP?] title tag, so it now lives under
    # MISSION_TITLE_TAG_KEYS below with the other title-only toggles.
    MISSION_FIELD_KEYS = (
        "mission_type", "difficulty", "spawns", "reputation",
        "blueprints", "ace", "resource_signatures",
    )
    _MISSION_FIELD_SETTING = {
        "mission_type":  "mission_field/mission_type",
        "difficulty":    "mission_field/difficulty",
        "spawns":        "mission_field/spawns",
        "reputation":    "mission_field/reputation",
        "blueprints":    "mission_field/blueprints",
        # #158, split from the title tag in 2.2.0 (see MISSION_TITLE_TAG_KEYS):
        # this key now controls ONLY the "Ace Pilot: Yes" body line.
        "ace":           "mission_field/ace",
        # #331: Recco Battaglia's Scan/Mining contracts already carry a flat
        # [RS ####] tag on the mission TITLE (MISSION_TITLE_TAG_KEYS' "rs"),
        # independent of this key. This one gates a fuller "Resource
        # Signatures:" breakdown in the DETAILS body -- one line per targeted
        # ore with its full RS value progression, not just the title's single
        # flattened number. Separate from RS_ORE_NAME_ANNOTATIONS below,
        # which patches the ore's own display name instead of adding a body
        # line -- a user can have either, both, or neither.
        "resource_signatures": "mission_field/resource_signatures",
    }

    # Mission TITLE tags (2.2.0, "General Tags" section): independent of the
    # mission-detail body fields above — these gate the [BP]/[ACE]/[REP]
    # markers appended to the mission TITLE only. All default on (prior
    # behaviour: blueprint_tag was already title-only and on by default; the
    # ace title tag and the rep/xp title tag were both unconditionally shown
    # before this split). migrate_title_tag_settings() carries a user's prior
    # blueprint_tag / ace choice forward once.
    MISSION_TITLE_TAG_KEYS = ("rep", "blueprint", "ace", "rs", "rep_track")
    _MISSION_TITLE_TAG_SETTING = {
        "rep":       "mission_title_tag/rep",
        "blueprint": "mission_title_tag/blueprint",
        "ace":       "mission_title_tag/ace",
        # RS ("resonance signature") tag for Recco Battaglia's Scan/Mining
        # contracts (4.9+) — see MINEABLE_RS_VALUES in generate_enhancements_ini.py.
        "rs":        "mission_title_tag/rs",
        # Reputation TRACK suffix (e.g. "(Security)"/"(Contractor)") on the
        # title's Rep tag — see issue #161. Off by default (see
        # _MISSION_TITLE_TAG_DEFAULTS below): unlike the other title tags,
        # this one is new to a lot of titles at once and can make an already
        # busy title noisier, so it's opt-in. The equivalent body-line
        # suffix (MISSION DETAILS' Reputation field) is unconditional and
        # always on, independent of this toggle.
        "rep_track": "mission_title_tag/rep_track",
    }
    # Per-field default for get_mission_title_tags() — every title tag
    # defaults on except where overridden here.
    _MISSION_TITLE_TAG_DEFAULTS = {
        "rep_track": False,
    }
    MISSION_HEADER_DEFAULTS = {
        "details": "MISSION DETAILS",
        # Kept in sync with owned_items.BP_SECTION_HEADER (the settings-free
        # matcher modules can't import AppSettings, so they carry the default).
        "blueprints": "POTENTIAL BLUEPRINTS",
        "items": "ITEM REWARDS",
        "blueprint_data": "BLUEPRINT DATA",
    }
    # Field name → settings key, the counterpart to MISSION_HEADER_DEFAULTS
    # above. Extracted (#383) because three places needed the same mapping:
    # get_mission_headers, set_mission_header, and profile_default_values.
    _MISSION_HEADER_SETTING = {
        "details":        MISSION_HEADER_DETAILS,
        "blueprints":     MISSION_HEADER_BLUEPRINTS,
        "items":          MISSION_HEADER_ITEMS,
        "blueprint_data": MISSION_HEADER_BLUEPRINT_DATA,
    }

    # Settings keys - Appearance
    THEME = "theme"
    # #180: "simple" (one-button generate+apply) vs "advanced" (full UI).
    # The installer writes this on a fresh registry install; the in-app
    # toggle changes it at runtime. Defaults to "simple" when unset.
    UI_MODE = "ui_mode"
    UI_MODE_SIMPLE = "simple"
    UI_MODE_ADVANCED = "advanced"

    # Settings keys - Enhancements
    ENHANCEMENTS_ENABLED = "enhancements_enabled"
    INCLUDE_NEW_LINES = "include_new_lines"

    # When the user dismisses the "your data is in OneDrive" warning with
    # "don't warn again", we stop nagging on startup (#172).
    ONEDRIVE_WARNING_DISMISSED = "onedrive_warning_dismissed"

    # Settings keys - Tutorial
    # Stores the app version string ("0.9.3") that last marked the guided tour
    # as completed, so a future release can re-trigger it if the tour gains
    # new steps worth showing again. Empty string means "never shown".
    TUTORIAL_COMPLETED_VERSION = "tutorial_completed_version"
    TUTORIAL_DISABLED = "tutorial_disabled"

    # Settings keys - App self-update check
    # Settings keys - Star Citizen channel selection
    # Star Citizen ships multiple channels (LIVE/PTU/EPTU/HOTFIX/TECH-PREVIEW)
    # under a common install root, each with its own Data.p4k. We store the
    # root directory + the active channel name separately so the rest of the
    # app can resolve channel-specific paths from a single source of truth.
    # Legacy installs with ``GAME_INSTALL_PATH = {root}\LIVE`` are migrated
    # by ``migrate_game_path_to_channel_layout`` on first launch.
    SC_INSTALL_ROOT = "sc_install_root"
    ACTIVE_CHANNEL = "active_channel"
    CHANNEL_LAYOUT_MIGRATED = "_channel_layout_migrated"  # one-shot marker

    # Channel names are the folder names Star Citizen uses under its install
    # root. Order here drives the combo box order in the Config tab.
    CHANNEL_LIVE = "LIVE"
    CHANNEL_PTU = "PTU"
    CHANNEL_EPTU = "EPTU"
    CHANNEL_HOTFIX = "HOTFIX"
    CHANNEL_TECH_PREVIEW = "TECH-PREVIEW"
    AVAILABLE_CHANNELS = (
        CHANNEL_LIVE,
        CHANNEL_PTU,
        CHANNEL_EPTU,
        CHANNEL_HOTFIX,
        CHANNEL_TECH_PREVIEW,
    )
    DEFAULT_CHANNEL = CHANNEL_LIVE

    # Settings key - Language selection
    SELECTED_LANGUAGE = "selected_language"
    DEFAULT_LANGUAGE = "english"
    # Per-language override URL for the base.ini (global.ini) download. Set via
    # the Config tab's "Map Language File" dialog; wins over the bundled
    # languages/sources.json map. Keyed LANG_SOURCE_OVERRIDE_PREFIX/<language>.
    LANG_SOURCE_OVERRIDE_PREFIX = "language_source_url"

    # Enhancements cache filenames (written by generate_enhancements_ini.py into cache dir)
    ENHANCEMENTS_FILES = {
        "ship_descs":          "ships_desc_enhancements.ini",
        "component_descs":     "components_desc_enhancements.ini",
        "ship_weapon_descs":   "ship_weapons_desc_enhancements.ini",
        "fps_weapon_descs":    "fps_weapons_desc_enhancements.ini",
        "mission_rewards":     "mission_rewards_enhancements.ini",
        "commodity_crafting":  "commodity_crafting_enhancements.ini",
        "journal":            "journal_enhancements.ini",
        "missile_enhancements": "missile_enhancements.ini",
        "medical_consumables": "medical_consumables_enhancements.ini",
    }

    # User-facing category labels — match the filter categories on the main page
    ENHANCEMENT_LABELS = {
        "ships":       "Ships",
        "ship_items":  "Ship Items",
        "gear":        "Gear",
        "missions":    "Missions",
        "commodities": "Commodities",
        "journal":     "Journal",
        "medical_consumables": "Medical Consumables",
    }

    # Maps each checkbox key to the enhancement file keys it controls
    ENHANCEMENT_CATEGORY_FILES = {
        "ships":       ["ship_descs"],
        "ship_items":  ["component_descs", "ship_weapon_descs", "missile_enhancements"],
        "gear":        ["fps_weapon_descs"],
        "missions":    ["mission_rewards"],
        "commodities": ["commodity_crafting"],
        "journal":     ["journal"],
        "medical_consumables": ["medical_consumables"],
    }

    # Settings keys - Legacy (kept for migration)
    BASE_GLOBAL_PATH = "base_global_path"
    VEHICLES_PATH = "vehicles_path"
    LAST_OVERRIDES_PATH = "last_overrides_path"
    GAME_INSTALL_PATH = "game_install_path"
    AUTO_WRITE_ENABLED = "auto_write_enabled"
    WINDOW_GEOMETRY = "window_geometry"
    WINDOW_STATE = "window_state"
    # String Editor column widths, written only once the user has actually
    # dragged (or double-click-fitted) a column. Absent means "never touched",
    # which is what keeps every fresh install opening at the same computed
    # default layout. See get_string_column_widths.
    STRING_COLUMN_WIDTHS = "string_column_widths"
    # Explicit override for the user-data directory. When set, takes
    # precedence over the Documents\Smart Citizen\ default. Users who have
    # Documents redirected to OneDrive can point this at a local path to
    # avoid slow extraction / rmtree races on OneDrive-synced folders.
    USER_DATA_DIR = "user_data_dir"
    # Compatibility alias for older docs/manual registry edits. The installer
    # and current app write ``user_data_dir``; read both so either spelling works.
    USER_DATA_DIR_ALIASES = ("UserDataDir",)
    # Explicit override for the DataForge XML cache root. Independent of
    # USER_DATA_DIR so a user can keep user.ini / source cache / backups in
    # Documents (or wherever) while sending the ~1.4 GB DataForge tree to a
    # fast local SSD (or to a folder excluded from OneDrive / Defender).
    # Pre-1.4.1 the cache was hard-pinned to %LOCALAPPDATA% with no way to
    # move it; this key is the configurable replacement.
    CACHE_DIR = "cache_dir"
    # Set by the Config tab when the user accepts a cache-path change with
    # "delete old cache after re-extraction". The path is removed after the
    # next successful P4K extraction so the 1.4 GB orphan doesn't linger.
    PENDING_CACHE_CLEANUP = "pending_cache_cleanup"
    # When True (default) the components Tag Builder annotation is woven
    # into the POTENTIAL BLUEPRINTS lists inside mission descriptions
    # (e.g. "[MIL-S1-A] Norfield"). Users who want clean mission body
    # text can turn it off here without affecting the inline tags on
    # the actual component names elsewhere. Issue #31 follow-up.
    TAG_ANNOTATE_MISSION_DESCS = "tag_builder/annotate_mission_descs"
    STATS_PREPEND = "stats_prepend"  # #153: stats block above the description
    STANDARDIZE_EARNABLE_SHIP_NAMES = "standardize_earnable_ship_names"
    # #331: appends " (RS ####)" to every mineable ore's own display name
    # (mineabletype_primary_<ore>), so Recco Battaglia's base resource
    # signature shows up everywhere the game renders that ore's name --
    # including the top-right mission tracker, which is what users actually
    # asked for. Default on, matching the established MISSION_FIELD_KEYS /
    # MISSION_TITLE_TAG_KEYS toggles -- the earlier attempt that pulled this
    # feature entirely was a call about bundling it into one all-or-nothing
    # toggle with the DETAILS breakdown, not about the ore-name annotation
    # being undesirable by default now that it's independently toggleable.
    # Independent of the "resource_signatures" Mission Detail Field above
    # (the DETAILS-body breakdown) -- see
    # scripts/generate_enhancements_ini.py's _build_mineable_rs_name_overrides
    # for the full history (shipped bundled with the breakdown, then pulled
    # for being too broad, now split into its own toggle).
    RS_ORE_NAME_ANNOTATIONS = "enhancements/rs_ore_name_annotations"
    OWNED_ITEMS = "owned_items"      # #157: blueprint items the user owns (JSON list of names)
    # #222: newest "Received Blueprint" log event a BP Scan has already
    # consumed, so a re-scan only imports genuinely new blueprints. Per-channel
    # (each SC channel has its own LogBackups), stored as an ISO-8601 string
    # under "{BLUEPRINT_LOG_WATERMARK}/{channel}".
    BLUEPRINT_LOG_WATERMARK = "blueprint_log_watermark"
    # #221: whether the Blueprints tracker's Available/Owned lists show each
    # item's Tag Builder tag (e.g. "Norfield [MIL-S1-A]") instead of the bare
    # name. Off by default — the bare name is the list's long-standing
    # display; this only affects the app's own list, never the in-game
    # mission text, which always shows the tag regardless of this setting.
    BLUEPRINT_SHOW_TAGS = "blueprints/show_tags"
    # #268: whether "Scan Logs for Owned Blueprints" also scans whichever of
    # LIVE/HOTFIX isn't the active channel. Enabled by default -- most
    # players with a HOTFIX-era account run both channels, and scanning the
    # inactive one too is what makes the Owned set actually complete. Never
    # covers PTU/EPTU/TECH-PREVIEW -- those are separate test builds with
    # their own progression, not the same account/blueprint history as
    # LIVE/HOTFIX.
    BLUEPRINT_SCAN_OTHER_CHANNELS = "blueprints/scan_other_channels"

    # Set at Import Settings time so the NEXT launch can prompt "your imported
    # settings need enhancements regenerated + applied" once the app is fully
    # up (the import itself ends in a restart, so the freshly-imported
    # settings are what the pipeline reads). Cleared as soon as the prompt is
    # shown — one-shot, never lingers.
    POST_IMPORT_APPLY_PENDING = "post_import/apply_pending"

    # Keys that never travel in an Export Settings backup: the data-root and
    # cache overrides (pointing them at a drive that doesn't exist on the
    # target machine would strand every path derived from them), window
    # placement (QByteArray, monitor-specific), and legacy path keys. Keys
    # starting with "_" (one-shot migration markers) are excluded by rule in
    # is_profile_excluded_key, as are local (non-URL) data_sources/*/path
    # values. The same filter runs on export AND import — defense in depth
    # against hand-edited or older backup files.
    #
    # NOT excluded (deliberately): sc_install_root / game_install_path. The
    # Star Citizen folder is the single most tedious thing to re-pick, and
    # for the common restore (same PC, fresh portable unzip) it's already
    # correct. It's validated on import by reconcile_imported_install_path()
    # — kept when the folder really exists here, dropped in favour of
    # auto-detection when it doesn't — so a backup from another machine
    # can't strand the user on a dead path.
    PROFILE_EXCLUDE_KEYS = frozenset({
        "user_data_dir",
        "UserDataDir",
        "cache_dir",
        "pending_cache_cleanup",
        "window_geometry",
        "window_state",
        # Column widths are machine-local for the same reason window geometry
        # is: they are measured against one screen. Exported and adopted
        # verbatim, a wide-monitor layout arrives on a laptop with columns
        # running off the edge, and HELP.md promises an export carries no
        # machine-specific layout.
        "string_column_widths",
        "base_global_path",
        "vehicles_path",
        "last_overrides_path",
        POST_IMPORT_APPLY_PENDING,
    })

    # Keys that have a default but are deliberately NOT materialised into a
    # backup by profile_default_values() (#383). These are per-machine state
    # or user *data*, not preferences, so writing their "unset" default into
    # every export would make an import destructive rather than restorative:
    #   - the install paths: an empty value clears a working path and forces
    #     re-detection, which can silently land on a different install (#370).
    #   - owned_items: the player's blueprint collection. Rebuilt by a log
    #     scan, but wiping it from a settings restore is real data loss.
    #   - the blueprint log watermark: scan position, per-channel, and
    #     resetting it only forces a slow full re-scan.
    #   - the test-plan keys: tester identity and per-run progress.
    #   - tutorial_completed_version: per-install first-run state.
    # Keys already in PROFILE_EXCLUDE_KEYS never reach this stage at all.
    PROFILE_DEFAULT_EXCLUDE_KEYS = frozenset({
        "sc_install_root",
        "game_install_path",
        "owned_items",
        "tutorial_completed_version",
        "test_plan/checks",
        "test_plan/tester_name",
        "test_plan/webhook_url",
    })
    # Prefixes of the same, for per-channel keys whose full name is dynamic.
    PROFILE_DEFAULT_EXCLUDE_PREFIXES = ("blueprint_log_watermark",)

    # reconcile_imported_install_path() outcomes.
    INSTALL_PATH_RESTORED = "restored"     # backup's path is valid here
    INSTALL_PATH_REDETECTED = "redetected"  # backup's path was bad; found another
    INSTALL_PATH_NONE = "none"             # nothing resolved on this machine

    # Settings keys - Data sources (new)
    # Prefix: data_sources/{source_name}/
    DATA_SOURCES_PREFIX = "data_sources"
    MERGE_HIERARCHY = "merge_hierarchy"
    SOURCE_AUTO_UPDATE_PREFIX = "source_auto_update"

    # Available data sources
    SOURCE_GLOBAL = "global"
    SOURCE_CONTRACTS = "contracts"
    SOURCE_COMPONENTS = "components"
    SOURCE_SHIPS = "ships"
    SOURCE_COMMODITIES = "commodities"
    SOURCE_GEAR = "gear"
    SOURCE_USER = "user"
    AVAILABLE_SOURCES = [SOURCE_GLOBAL, SOURCE_USER]

    # Backend override hook — kept None by default so production stays on
    # QSettings (registry mode). PR-B in the standalone-build series sets
    # this to a JsonSettings instance during portable-mode startup. Tests
    # can also assign it to swap in a JsonSettings backed by a tmp_path
    # for hermetic settings testing without touching the real registry.
    _backend: object | None = None

    @staticmethod
    def settings():
        """Return the active settings backend.

        Defaults to a per-call QSettings(ORG_NAME, APP_NAME) — same
        behavior as before. When `_backend` is set (PR-B portable mode
        or test injection), returns that backend instead. Both paths
        expose the same minimal API: ``value(key, default, type=...)``,
        ``setValue(key, value)``, ``remove(key)``, ``sync()``.
        """
        if AppSettings._backend is not None:
            return AppSettings._backend
        return QSettings(AppSettings.ORG_NAME, AppSettings.APP_NAME)

    @staticmethod
    def get_enhancements_enabled() -> bool:
        """Check whether enhancements are enabled (default: True)."""
        return AppSettings.settings().value(AppSettings.ENHANCEMENTS_ENABLED, True, type=bool)

    @staticmethod
    def set_enhancements_enabled(enabled: bool) -> None:
        """Enable or disable enhancements."""
        AppSettings.settings().setValue(AppSettings.ENHANCEMENTS_ENABLED, enabled)

    @staticmethod
    def get_include_new_lines() -> bool:
        """Check whether discovered items (status 'New') are included in apply output."""
        return AppSettings.settings().value(AppSettings.INCLUDE_NEW_LINES, False, type=bool)

    @staticmethod
    def set_include_new_lines(enabled: bool) -> None:
        """Include or exclude discovered items from apply output."""
        AppSettings.settings().setValue(AppSettings.INCLUDE_NEW_LINES, enabled)

    @staticmethod
    def get_onedrive_warning_dismissed() -> bool:
        """Whether the user dismissed the OneDrive data-root warning (#172)."""
        return AppSettings.settings().value(
            AppSettings.ONEDRIVE_WARNING_DISMISSED, False, type=bool
        )

    @staticmethod
    def set_onedrive_warning_dismissed(dismissed: bool) -> None:
        """Persist 'don't warn me again' for the OneDrive data-root warning."""
        AppSettings.settings().setValue(
            AppSettings.ONEDRIVE_WARNING_DISMISSED, dismissed
        )

    @staticmethod
    def get_enhancement_category_enabled(key: str) -> bool:
        """Check if a specific enhancement category is enabled (default: True)."""
        return AppSettings.settings().value(
            f"enhancements/categories/{key}/enabled", True, type=bool)

    @staticmethod
    def set_enhancement_category_enabled(key: str, enabled: bool) -> None:
        """Enable or disable a specific enhancement category."""
        AppSettings.settings().setValue(
            f"enhancements/categories/{key}/enabled", enabled)

    @staticmethod
    def get_enabled_enhancement_categories() -> set[str]:
        """Return the set of enabled enhancement file keys (expanding grouped categories)."""
        result = set()
        for checkbox_key, file_keys in AppSettings.ENHANCEMENT_CATEGORY_FILES.items():
            if AppSettings.get_enhancement_category_enabled(checkbox_key):
                result.update(file_keys)
        return result

    @staticmethod
    def get_theme() -> str:
        """Get UI theme name ('light' or 'dark')."""
        from src.gui.theme import DEFAULT_THEME, AVAILABLE_THEMES
        value = AppSettings.settings().value(AppSettings.THEME, DEFAULT_THEME)
        return value if value in AVAILABLE_THEMES else DEFAULT_THEME

    @staticmethod
    def set_theme(theme: str) -> None:
        """Persist UI theme name."""
        AppSettings.settings().setValue(AppSettings.THEME, theme)

    @staticmethod
    def get_ui_mode() -> str:
        """Return the UI mode: 'simple' or 'advanced' (#180).

        Defaults to 'simple' for fresh installs (the installer may have
        already written the user's choice). Any unrecognized stored value
        coerces back to 'simple'.
        """
        value = AppSettings.settings().value(
            AppSettings.UI_MODE, AppSettings.UI_MODE_SIMPLE
        )
        return (
            value
            if value in (AppSettings.UI_MODE_SIMPLE, AppSettings.UI_MODE_ADVANCED)
            else AppSettings.UI_MODE_SIMPLE
        )

    @staticmethod
    def set_ui_mode(mode: str) -> None:
        """Persist the UI mode. Unknown values fall back to 'simple'."""
        if mode not in (AppSettings.UI_MODE_SIMPLE, AppSettings.UI_MODE_ADVANCED):
            mode = AppSettings.UI_MODE_SIMPLE
        AppSettings.settings().setValue(AppSettings.UI_MODE, mode)

    @staticmethod
    def get_selected_language() -> str:
        """Return the active language name (default: 'english')."""
        return AppSettings.settings().value(
            AppSettings.SELECTED_LANGUAGE, AppSettings.DEFAULT_LANGUAGE
        )

    @staticmethod
    def set_selected_language(language: str) -> None:
        """Persist the active language name."""
        AppSettings.settings().setValue(AppSettings.SELECTED_LANGUAGE, language)

    @staticmethod
    def get_sc_language_id(language: str | None = None) -> str:
        """Map our internal language folder name to the SC language identifier.

        Star Citizen uses identifiers like ``portuguese_(brazil)`` in both its
        Localization directory paths and ``g_language`` in user.cfg.  Our folder
        names (e.g. ``portuguese_br``) are shorter for filesystem convenience.
        Falls back to the raw name if no mapping entry exists.
        """
        if language is None:
            language = AppSettings.get_selected_language()
        return SC_LANGUAGE_IDS.get(language, language)

    @staticmethod
    def get_languages_dir() -> "Path":
        """Return the bundled languages/ directory (dev or PyInstaller-frozen)."""
        from src.utils.resource_path import get_resource_path
        return Path(get_resource_path("languages"))

    @staticmethod
    def get_available_languages() -> list:
        """Return sorted language names that are usable in the UI.

        A folder under languages/ is offered only if it ships a non-empty
        ui.json (at least one translated string); DEFAULT_LANGUAGE (English,
        the base) is always included. This hides stub languages whose ui.json
        exists but carries no translations: selecting one would render the
        whole UI in English and read as broken. The untranslated Spanish
        placeholder is the motivating case.
        """
        lang_dir = AppSettings.get_languages_dir()
        if not lang_dir.exists():
            return [AppSettings.DEFAULT_LANGUAGE]
        names = []
        for d in sorted(lang_dir.iterdir()):
            if not d.is_dir():
                continue
            if (d.name == AppSettings.DEFAULT_LANGUAGE
                    or AppSettings._ui_json_has_translations(d / "ui.json")):
                names.append(d.name)
        if AppSettings.DEFAULT_LANGUAGE not in names:
            names.append(AppSettings.DEFAULT_LANGUAGE)
        return sorted(names) if names else [AppSettings.DEFAULT_LANGUAGE]

    @staticmethod
    def _ui_json_has_translations(ui_json_path) -> bool:
        """True if *ui_json_path* exists and holds at least one translation
        string. The ``_comment`` metadata field is ignored at every level, so
        a stub file carrying only a comment counts as empty. Used to keep
        untranslated languages out of the selector."""
        import json
        try:
            if not ui_json_path.exists():
                return False
            with ui_json_path.open(encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return False

        def _leaf_count(node) -> int:
            if isinstance(node, dict):
                return sum(_leaf_count(v) for k, v in node.items() if k != "_comment")
            return 1

        return isinstance(data, dict) and _leaf_count(data) > 0

    @staticmethod
    def get_language_global_ini_path(language: str | None = None) -> "Path | None":
        """Return path to languages/<lang>/global.ini, or None if absent."""
        if language is None:
            language = AppSettings.get_selected_language()
        path = AppSettings.get_languages_dir() / language / "global.ini"
        return path if path.exists() else None

    @staticmethod
    def get_localized_doc_path(filename: str, language: "str | None" = None) -> "Path":
        """Resolve an in-app document (HELP.md / ABOUT.md / LEGAL.md) for *language*.

        Non-English languages may ship a translated copy at
        ``languages/<lang>/<filename>``; English (and any language without a
        translated copy) falls back to the bundled ``docs/<filename>``.
        """
        from src.utils.resource_path import get_resource_path
        if language is None:
            language = AppSettings.get_selected_language()
        if language != AppSettings.DEFAULT_LANGUAGE:
            candidate = AppSettings.get_languages_dir() / language / filename
            if candidate.exists():
                return candidate
        return Path(get_resource_path(f"docs/{filename}"))

    @staticmethod
    def get_language_languages_ini_path(language: str | None = None) -> "Path | None":
        """Return path to languages/<lang>/languages.ini, or None if absent."""
        if language is None:
            language = AppSettings.get_selected_language()
        path = AppSettings.get_languages_dir() / language / "languages.ini"
        return path if path.exists() else None

    @staticmethod
    def get_languages_ini_dest_path() -> "Path":
        """Return the game-side destination for languages.ini: {channel}/data/languages.ini."""
        channel_path = AppSettings.get_channel_install_path()
        if channel_path:
            return Path(channel_path) / "data" / "languages.ini"
        game_path = Path(AppSettings.get_game_install_path())
        if game_path.name.upper() in {c.upper() for c in AppSettings.AVAILABLE_CHANNELS}:
            return game_path / "data" / "languages.ini"
        return game_path / AppSettings.get_active_channel() / "data" / "languages.ini"

    @staticmethod
    def get_favorite_prefix() -> str:
        """Get the character prepended to favorited ship names (default '*')."""
        return AppSettings.settings().value(
            AppSettings.FAVORITE_PREFIX, AppSettings.DEFAULT_FAVORITE_PREFIX
        )

    @staticmethod
    def set_favorite_prefix(prefix: str) -> None:
        """Set the character prepended to favorited ship names."""
        AppSettings.settings().setValue(AppSettings.FAVORITE_PREFIX, prefix)

    # ── Test Plan panel (#144) ───────────────────────────────────────────────
    @staticmethod
    def get_test_plan_checks() -> set:
        """Return the tester's checked item keys, or empty if the plan changed.

        Stored with the plan hash it was saved against; when TEST_SECTIONS
        changes the hash no longer matches and the stale marks are dropped.
        """
        from src.utils.test_plan import plan_hash
        raw = AppSettings.settings().value(AppSettings.TEST_PLAN_CHECKS, "")
        if not raw:
            return set()
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return set()
        if data.get("hash") != plan_hash():
            return set()
        return set(data.get("checked", []))

    @staticmethod
    def set_test_plan_checks(checked) -> None:
        """Persist the tester's checked item keys against the current plan hash."""
        from src.utils.test_plan import plan_hash
        payload = json.dumps({"hash": plan_hash(), "checked": sorted(checked)})
        AppSettings.settings().setValue(AppSettings.TEST_PLAN_CHECKS, payload)

    @staticmethod
    def get_tester_name() -> str:
        return AppSettings.settings().value(AppSettings.TEST_PLAN_TESTER, "")

    @staticmethod
    def set_tester_name(name: str) -> None:
        AppSettings.settings().setValue(AppSettings.TEST_PLAN_TESTER, name)

    @staticmethod
    def get_test_webhook_url() -> str:
        """Resolve the test-report Discord webhook: stored override, then env.

        Returns "" when neither is set; the panel disables Submit in that case
        and falls back to Copy Report. No webhook URL is ever bundled.
        """
        stored = AppSettings.settings().value(AppSettings.TEST_WEBHOOK_URL, "")
        return (stored or os.environ.get(AppSettings.TEST_WEBHOOK_ENV, "")).strip()

    @staticmethod
    def set_test_webhook_url(url: str) -> None:
        AppSettings.settings().setValue(AppSettings.TEST_WEBHOOK_URL, url)

    @staticmethod
    def get_rep_xp_label() -> str:
        """Label shown on single-tier mission XP lines (default 'Rep')."""
        return AppSettings.settings().value(AppSettings.REP_XP_LABEL, AppSettings.DEFAULT_REP_XP_LABEL)

    @staticmethod
    def set_rep_xp_label(label: str) -> None:
        AppSettings.settings().setValue(AppSettings.REP_XP_LABEL, label)

    @staticmethod
    def get_mission_headers() -> dict[str, str]:
        s = AppSettings.settings()
        d = AppSettings.MISSION_HEADER_DEFAULTS
        return {
            name: s.value(key, d[name])
            for name, key in AppSettings._MISSION_HEADER_SETTING.items()
        }

    @staticmethod
    def set_mission_header(key: str, value: str) -> None:
        setting = AppSettings._MISSION_HEADER_SETTING.get(key)
        if setting:
            AppSettings.settings().setValue(setting, value)

    @staticmethod
    def get_mission_header_em_tag() -> str:
        tag = AppSettings.settings().value(
            AppSettings.MISSION_HEADER_EM_TAG, AppSettings.DEFAULT_MISSION_HEADER_EM_TAG
        )
        # Coerce a stored EM1/EM2 (removed in 1.5.0; never rendered in-game)
        # back to the default so generated output never carries a dead tag.
        if tag not in AppSettings.MISSION_HEADER_EM_TAGS:
            return AppSettings.DEFAULT_MISSION_HEADER_EM_TAG
        return tag

    @staticmethod
    def set_mission_header_em_tag(tag: str) -> None:
        AppSettings.settings().setValue(AppSettings.MISSION_HEADER_EM_TAG, tag)

    @staticmethod
    def migrate_route_toggle_to_mission_titles() -> None:
        """One-time (2.1): carry the retired #166 ``route`` mission-detail toggle
        into the new mission_titles tag config. Only acts when the user had route
        explicitly OFF and hasn't configured the new tab yet — so a deliberate
        opt-out survives the move and nobody is silently flipped back on."""
        s = AppSettings.settings()
        marker = "mission_field/route_migrated"
        if s.value(marker, False, type=bool):
            return
        old = s.value("mission_field/route", None)
        was_off = old is not None and str(old).strip().lower() in ("false", "0")
        already = s.value("tag_builder/mission_titles/config", "", type=str)
        if was_off and not already:
            from src.utils.tag_builder import default_config
            cfg = default_config("mission_titles")
            for e in cfg.elements:
                if e.kind == "route":
                    e.enabled = False
            AppSettings.set_tag_config("mission_titles", cfg)
        s.setValue(marker, True)
        s.sync()

    @staticmethod
    def migrate_mission_titles_location_detail() -> None:
        """One-time (2.1.1, #200): flip a saved mission_titles config from the
        2.1.0-seeded ``location_detail: "name"`` to ``"address"``. The short
        ``|name`` modifier fails to resolve for some mission instances in-game
        (raw "Locationname" text in the title); ``|Address`` is what mission
        bodies themselves use and always resolves. 2.1.0 seeded "name" as the
        default, so a saved "name" was never a deliberate choice. Marker-gated:
        a user who picks Name afterward isn't re-flipped."""
        s = AppSettings.settings()
        marker = "tag_builder/mission_titles/location_detail_migrated"
        if s.value(marker, False, type=bool):
            return
        raw = s.value("tag_builder/mission_titles/config", "", type=str)
        if raw:
            try:
                from src.utils.tag_builder import TagConfig
                cfg = TagConfig.from_json(raw)
                if cfg.location_detail == "name":
                    cfg.location_detail = "address"
                    AppSettings.set_tag_config("mission_titles", cfg)
            except Exception:
                # Unreadable blob: leave it, get_tag_config already falls
                # back to the (now address-defaulted) default config.
                pass
        s.setValue(marker, True)
        s.sync()

    @staticmethod
    def get_mission_detail_fields() -> dict:
        """Return {field: enabled} for the mission DETAILS body fields (#121).

        Every field defaults to True, so an unconfigured user gets the full
        body exactly as before. Consumed by the enhancements generator at
        generation time (passed through the worker into its ctx).
        """
        s = AppSettings.settings()
        return {
            field: bool(s.value(reg_key, True, type=bool))
            for field, reg_key in AppSettings._MISSION_FIELD_SETTING.items()
        }

    @staticmethod
    def set_mission_detail_field(field: str, enabled: bool) -> None:
        """Persist one mission-detail field toggle. Unknown keys are ignored."""
        reg_key = AppSettings._MISSION_FIELD_SETTING.get(field)
        if reg_key:
            AppSettings.settings().setValue(reg_key, enabled)

    @staticmethod
    def get_mission_title_tags() -> dict:
        """Return {field: enabled} for the mission TITLE tags (2.2.0, "General
        Tags"): rep/xp, blueprint, ace, rep_track. Independent of
        get_mission_detail_fields() — see MISSION_TITLE_TAG_KEYS. Every field
        defaults to True (matching prior, unsplit behaviour) except where
        overridden in _MISSION_TITLE_TAG_DEFAULTS (currently just
        "rep_track", off by default — see issue #161)."""
        s = AppSettings.settings()
        return {
            field: bool(s.value(
                reg_key, AppSettings._MISSION_TITLE_TAG_DEFAULTS.get(field, True), type=bool
            ))
            for field, reg_key in AppSettings._MISSION_TITLE_TAG_SETTING.items()
        }

    @staticmethod
    def set_mission_title_tag(field: str, enabled: bool) -> None:
        """Persist one mission-title-tag toggle. Unknown keys are ignored."""
        reg_key = AppSettings._MISSION_TITLE_TAG_SETTING.get(field)
        if reg_key:
            AppSettings.settings().setValue(reg_key, enabled)

    @staticmethod
    def get_mission_title_tag_default(field: str) -> bool:
        """The out-of-the-box value for one mission-title-tag field — True
        unless overridden in _MISSION_TITLE_TAG_DEFAULTS. Lets callers (e.g.
        the Enhancements tab's "Reset to defaults") restore the correct
        per-field default instead of assuming every tag defaults on."""
        return AppSettings._MISSION_TITLE_TAG_DEFAULTS.get(field, True)

    @staticmethod
    def migrate_title_tag_settings() -> None:
        """One-shot (2.2.0): the [BP]/[ACE] title tags used to share a
        toggle with mission-detail-body settings — "blueprint_tag" already
        controlled only the title (just lived in the wrong group);
        "ace" controlled BOTH a body line and the title tag together. The
        new independent "General Tags" toggles need a starting value that
        respects whatever the user had already chosen, so this copies the
        old blueprint_tag/ace values into the new keys once. Reading the old
        key with its own default (True) makes this a safe no-op for anyone
        who never touched those checkboxes — only an explicit prior "off"
        carries forward. After this runs, the two evolve independently."""
        s = AppSettings.settings()
        marker = "mission_title_tag/migrated"
        if s.value(marker, False, type=bool):
            return
        old_bp = s.value("mission_field/blueprint_tag", True, type=bool)
        old_ace = s.value("mission_field/ace", True, type=bool)
        s.setValue(AppSettings._MISSION_TITLE_TAG_SETTING["blueprint"], bool(old_bp))
        s.setValue(AppSettings._MISSION_TITLE_TAG_SETTING["ace"], bool(old_ace))
        s.setValue(marker, True)
        s.sync()

    @staticmethod
    def get_tag_config(category: str):
        """Return the user's TagConfig for *category*, or the default if absent/bad.

        Stored as one JSON blob per category under tag_builder/{category}/config
        so the slash-key contract honored by JsonSettings (see test_json_settings)
        doesn't have to round-trip a nested dict.
        """
        # Deferred import — tag_builder lives in src.utils too, and importing it
        # at module load time would create a circular import for callers that
        # do `from src.utils.settings import AppSettings` very early.
        from src.utils.tag_builder import TagConfig, default_config
        raw = AppSettings.settings().value(f"tag_builder/{category}/config", "", type=str)
        if not raw:
            return default_config(category)
        try:
            cfg = TagConfig.from_json(raw)
        except (ValueError, TypeError) as e:
            import logging
            logging.getLogger(__name__).warning(
                f"Stored tag config for '{category}' is malformed ({e}); falling back to defaults."
            )
            return default_config(category)
        AppSettings._migrate_tag_config_mapping(category, cfg)
        AppSettings._backfill_new_elements(category, cfg)
        # 1.5.0: commodities gained a second flag (Collection). A stored
        # single-element config used separator "none" (meaningless when there
        # was only one flag), which post-1.5.0 would mash the two flags into
        # "[CFCollection]". Upgrade that leftover to "pipe" ONCE (marker-gated)
        # so existing users don't regress — but never clamp again, so a user
        # can deliberately choose "none" and have it stick (#97 follow-up).
        if category == "commodities":
            marker = "tag_builder/commodities/sep_migrated"
            if not AppSettings.settings().value(marker, False, type=bool):
                if cfg.separator == "none":
                    cfg.separator = "pipe"
                    AppSettings.settings().setValue(
                        f"tag_builder/{category}/config", cfg.to_json()
                    )
                AppSettings.settings().setValue(marker, True)
                AppSettings.settings().sync()
        return cfg

    @staticmethod
    def _migrate_tag_config_mapping(category: str, cfg) -> None:
        """Upgrade the mapping dict in *cfg* to the current key vocabulary.

        Early ship-weapon configs stored damage entries under the compact
        generator labels ("Phys", "Distort", "Bio") and a brief experiment
        also kept the long-form duplicates ("Physical", "Distortion",
        "Biochemical") side-by-side. The current mapping keys on the long
        form so users see real English in the variant editor. Rename in
        place when an old key is present without its new counterpart;
        drop the old key if a new-key row already exists.
        """
        if category != "ship_weapons":
            return
        renames = {
            "Phys":    "Physical",
            "Distort": "Distortion",
            "Bio":     "Biochemical",
        }
        mapping = cfg.class_mapping
        for old, new in renames.items():
            if old not in mapping:
                continue
            if new in mapping:
                # Both present — keep the user-friendly new entry and drop
                # the orphan old one.
                del mapping[old]
            else:
                mapping[new] = mapping.pop(old)

    @staticmethod
    def _backfill_new_elements(category: str, cfg) -> None:
        """Insert element kinds added in a newer version that the stored config
        doesn't have yet (e.g. ``type`` added to components in 1.4.2, ``usage``
        added to commodities in 2.1). New elements inherit the default config's
        enabled state (per-category, e.g. commodities' three elements are all
        disabled by default as of #325, while components/missiles/ship_weapons
        default their own elements enabled), and are inserted at their
        canonical position in ``CATEGORY_ELEMENT_KINDS`` (not appended) so an
        element added in the middle of the order — like ``usage`` between ``label`` and
        ``collection`` — renders in the right place for upgraded users too."""
        from src.utils.tag_builder import (
            CATEGORY_ELEMENT_KINDS, DEFAULT_TAG_CONFIGS, DEFAULT_KIND_MAPPINGS,
            ElementSpec,
        )
        expected_kinds = CATEGORY_ELEMENT_KINDS.get(category, ())
        existing_kinds = {e.kind for e in cfg.elements}
        defaults = DEFAULT_TAG_CONFIGS.get(category)
        for pos, kind in enumerate(expected_kinds):
            if kind not in existing_kinds:
                default_spec = None
                if defaults:
                    default_spec = next((e for e in defaults.elements if e.kind == kind), None)
                new_spec = ElementSpec(
                    kind=kind,
                    enabled=default_spec.enabled if default_spec else False,
                    style=default_spec.style if default_spec else "",
                )
                # Insert just after the last already-present element that
                # precedes `kind` in canonical order; falls back to `pos`.
                preceding = {k for k in expected_kinds[:pos]}
                insert_at = 0
                for i, el in enumerate(cfg.elements):
                    if el.kind in preceding:
                        insert_at = i + 1
                cfg.elements.insert(insert_at, new_spec)
            kind_mapping = DEFAULT_KIND_MAPPINGS.get(kind, {})
            for key, val in kind_mapping.items():
                if key not in cfg.class_mapping:
                    cfg.class_mapping[key] = val

    @staticmethod
    def set_tag_config(category: str, config) -> None:
        """Persist *config* (a TagConfig) for *category* as a JSON blob."""
        AppSettings.settings().setValue(
            f"tag_builder/{category}/config", config.to_json()
        )

    @staticmethod
    def get_all_tag_configs() -> dict:
        """Return TagConfigs for every supported category (defaults fill in)."""
        from src.utils.tag_builder import CATEGORIES
        return {cat: AppSettings.get_tag_config(cat) for cat in CATEGORIES}

    @staticmethod
    def get_tag_annotate_mission_descs() -> bool:
        """Whether component tags are woven into POTENTIAL BLUEPRINTS lists
        inside mission descriptions. Default True (annotation enabled),
        preserving the v1.4.0 behavior. Issue #31 follow-up — when False,
        the BP-pool resolver skips the tag weave entirely and mission
        bodies render with bare names."""
        raw = AppSettings.settings().value(
            AppSettings.TAG_ANNOTATE_MISSION_DESCS, True, type=bool
        )
        # QSettings on registry mode round-trips True via the bool type
        # arg; JsonSettings stores the raw value and we may get None
        # for "never set", which falls through to True by intent.
        if raw is None:
            return True
        return bool(raw)

    @staticmethod
    def set_tag_annotate_mission_descs(enabled: bool) -> None:
        """Persist the mission-desc annotation toggle."""
        AppSettings.settings().setValue(
            AppSettings.TAG_ANNOTATE_MISSION_DESCS, bool(enabled)
        )
        AppSettings.settings().sync()

    @staticmethod
    def get_stats_prepend() -> bool:
        """#153: whether the generated stats block is placed ABOVE the prose
        description (True) instead of appended below it (False, default).
        Applies to ship and component/weapon descriptions; baked at generation
        time, so it takes effect on the next Generate Enhancements run."""
        return bool(AppSettings.settings().value(
            AppSettings.STATS_PREPEND, False, type=bool
        ))

    @staticmethod
    def set_stats_prepend(enabled: bool) -> None:
        """Persist the stats-above-description toggle (#153)."""
        AppSettings.settings().setValue(AppSettings.STATS_PREPEND, bool(enabled))
        AppSettings.settings().sync()

    @staticmethod
    def get_standardize_earnable_ship_names() -> bool:
        """Whether to apply standardized display names for earnable ships
        (PYX exec-hangar and WIK Wikelo variants). Off by default."""
        return bool(AppSettings.settings().value(
            AppSettings.STANDARDIZE_EARNABLE_SHIP_NAMES, False, type=bool
        ))

    @staticmethod
    def set_standardize_earnable_ship_names(enabled: bool) -> None:
        AppSettings.settings().setValue(
            AppSettings.STANDARDIZE_EARNABLE_SHIP_NAMES, bool(enabled)
        )
        AppSettings.settings().sync()

    @staticmethod
    def get_rs_ore_name_annotations() -> bool:
        """#331: whether mineable ore display names are annotated with their
        base Resource Signature value (" (RS ####)"). Default on -- see
        RS_ORE_NAME_ANNOTATIONS for why."""
        return bool(AppSettings.settings().value(
            AppSettings.RS_ORE_NAME_ANNOTATIONS, True, type=bool
        ))

    @staticmethod
    def set_rs_ore_name_annotations(enabled: bool) -> None:
        AppSettings.settings().setValue(
            AppSettings.RS_ORE_NAME_ANNOTATIONS, bool(enabled)
        )
        AppSettings.settings().sync()

    @staticmethod
    def get_owned_items() -> set:
        """Return the set of owned blueprint item names (#157).

        Stored as a JSON list string so it round-trips identically through the
        registry (QSettings) and the portable JSON backend — a raw Python list
        in QSettings comes back as a QStringList and mangles single-item sets.
        """
        import json
        raw = AppSettings.settings().value(AppSettings.OWNED_ITEMS, "", type=str)
        if not raw:
            return set()
        try:
            return set(json.loads(raw))
        except (ValueError, TypeError):
            return set()

    @staticmethod
    def set_owned_items(names) -> None:
        """Persist the owned blueprint item-name set (#157)."""
        import json
        AppSettings.settings().setValue(
            AppSettings.OWNED_ITEMS, json.dumps(sorted(names))
        )
        AppSettings.settings().sync()

    @staticmethod
    def get_blueprint_show_tags() -> bool:
        """Whether the Blueprints tracker shows each item's Tag Builder tag
        inline (e.g. "Norfield [MIL-S1-A]") instead of the bare name (#221).
        Default False. Purely a display toggle for the app's own Available/
        Owned lists — matching, filtering, and Owned tracking always use the
        bare, tag-free name regardless of this setting."""
        return bool(AppSettings.settings().value(
            AppSettings.BLUEPRINT_SHOW_TAGS, False, type=bool
        ))

    @staticmethod
    def set_blueprint_show_tags(enabled: bool) -> None:
        """Persist the Blueprints tracker's show-tags display toggle (#221)."""
        AppSettings.settings().setValue(
            AppSettings.BLUEPRINT_SHOW_TAGS, bool(enabled)
        )
        AppSettings.settings().sync()

    @staticmethod
    def toggle_owned_item(name: str) -> bool:
        """Add/remove *name* from the owned set; return the new owned state."""
        owned = AppSettings.get_owned_items()
        if name in owned:
            owned.discard(name)
            new_state = False
        else:
            owned.add(name)
            new_state = True
        AppSettings.set_owned_items(owned)
        return new_state

    @staticmethod
    def _blueprint_watermark_key(channel: "str | None" = None) -> str:
        """Per-channel storage key for the BP Scan watermark (#222).

        *channel* targets a specific channel's watermark without needing to
        flip ``active_channel`` (#268's multi-channel scan reads/writes
        LIVE's and HOTFIX's watermarks independently in the same pass, and
        switching active_channel mid-scan would trigger its own unrelated
        side effects). Defaults to the active channel, unchanged from before.
        """
        return (f"{AppSettings.BLUEPRINT_LOG_WATERMARK}/"
                f"{channel or AppSettings.get_active_channel()}")

    @staticmethod
    def get_blueprint_log_watermark(channel: "str | None" = None):
        """Return *channel*'s (default: active channel) BP Scan watermark, or
        ``None`` (#222).

        The watermark is the newest received-blueprint event a prior scan
        consumed. Returns a timezone-aware ``datetime`` (the stored ISO string
        carries the ``+00:00`` offset); ``None`` when unset or unparseable, in
        which case the scanner falls back to the March-2026 blueprint epoch.
        """
        from datetime import datetime
        raw = AppSettings.settings().value(
            AppSettings._blueprint_watermark_key(channel), "", type=str
        )
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    @staticmethod
    def set_blueprint_log_watermark(when, channel: "str | None" = None) -> None:
        """Persist *channel*'s (default: active channel) BP Scan watermark (#222).

        *when* is a ``datetime`` (the scanner emits timezone-aware UTC); stored
        as its ISO-8601 string so it round-trips through both settings backends.
        """
        AppSettings.settings().setValue(
            AppSettings._blueprint_watermark_key(channel), when.isoformat()
        )
        AppSettings.settings().sync()

    @staticmethod
    def get_scan_other_channels_enabled() -> bool:
        """Whether "Scan Logs for Owned Blueprints" also scans whichever of
        LIVE/HOTFIX isn't the active channel (#268). Default True — most
        players with a HOTFIX-era account run both channels, and scanning
        the inactive one too is what makes the Owned set actually complete;
        opting in after the fact means missing blueprints already earned
        there before the user thinks to enable it."""
        return bool(AppSettings.settings().value(
            AppSettings.BLUEPRINT_SCAN_OTHER_CHANNELS, True, type=bool
        ))

    @staticmethod
    def set_scan_other_channels_enabled(enabled: bool) -> None:
        """Persist the multi-channel BP Scan checkbox state (#268)."""
        AppSettings.settings().setValue(
            AppSettings.BLUEPRINT_SCAN_OTHER_CHANNELS, bool(enabled)
        )
        AppSettings.settings().sync()

    @staticmethod
    def get_tutorial_completed_version() -> str:
        """App version string that last completed the guided tour, or '' if never."""
        return AppSettings.settings().value(AppSettings.TUTORIAL_COMPLETED_VERSION, "")

    @staticmethod
    def set_tutorial_completed_version(version: str) -> None:
        """Record that the guided tour was completed for *version*."""
        AppSettings.settings().setValue(AppSettings.TUTORIAL_COMPLETED_VERSION, version)
        AppSettings.settings().sync()

    @staticmethod
    def get_tutorial_disabled() -> bool:
        """When True, the tutorial never auto-launches (Config tab opt-out)."""
        return AppSettings.settings().value(AppSettings.TUTORIAL_DISABLED, False, type=bool)

    @staticmethod
    def set_tutorial_disabled(disabled: bool) -> None:
        AppSettings.settings().setValue(AppSettings.TUTORIAL_DISABLED, bool(disabled))
        AppSettings.settings().sync()

    @staticmethod
    def get_base_global_path() -> str:
        """Get legacy base global path (for backward compatibility).

        This is deprecated. Use get_source_path(SOURCE_GLOBAL) instead.
        """
        return AppSettings.settings().value(AppSettings.BASE_GLOBAL_PATH, "")

    @staticmethod
    def set_base_global_path(path: str) -> None:
        """Set legacy base global path (for backward compatibility).

        This is deprecated. Use set_source_path(SOURCE_GLOBAL, path) instead.
        """
        AppSettings.settings().setValue(AppSettings.BASE_GLOBAL_PATH, path)

    @staticmethod
    def get_vehicles_path() -> str:
        """Get path to vehicles.ini."""
        return AppSettings.settings().value(AppSettings.VEHICLES_PATH, "")

    @staticmethod
    def set_vehicles_path(path: str) -> None:
        """Set path to vehicles.ini."""
        AppSettings.settings().setValue(AppSettings.VEHICLES_PATH, path)

    @staticmethod
    def get_last_overrides_path() -> str:
        """Get last directory used for overrides."""
        return AppSettings.settings().value(AppSettings.LAST_OVERRIDES_PATH, "")

    @staticmethod
    def set_last_overrides_path(path: str) -> None:
        """Set last directory used for overrides."""
        AppSettings.settings().setValue(AppSettings.LAST_OVERRIDES_PATH, path)

    @staticmethod
    def _read_legacy_installer_sc_directory() -> "str | None":
        """Return the raw ``sc_directory`` value the older installer flow
        wrote to the registry, or ``None`` if the key is absent/unreadable.

        Shared by `get_game_install_path()` and `get_sc_install_root()` —
        both used to carry their own copy of this same registry read
        (identical path + value name), each interpreting the raw value
        differently (one keeps a channel-suffixed path as-is, the other
        strips to the root). ``WindowsError`` is just an alias of `OSError`
        in Python 3, so catching the latter covers both.
        """
        try:
            reg_path = r'Software\Osiris DevWorks\SC Localization Editor'
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path) as registry_key:
                sc_directory, _ = winreg.QueryValueEx(registry_key, 'sc_directory')
            return sc_directory or None
        except OSError:
            return None

    @staticmethod
    def get_game_install_path() -> str:
        """Return the install path of the **active channel**.

        Post 0.9.3 this resolves as ``{sc_install_root}\\{active_channel}``.
        Kept under the old name so existing callers (which assume "the"
        game install path means the active channel) still work; there's no
        semantic change for pre-channel-aware code paths that always
        operated on LIVE.

        Falls back to the legacy ``GAME_INSTALL_PATH`` stored value, and
        then to the installer-written registry key, for users whose
        settings haven't been through :meth:`migrate_game_path_to_channel_layout`
        yet (should be a vanishingly small window — the migrator runs at
        ``main()`` startup).
        """
        root = AppSettings.settings().value(AppSettings.SC_INSTALL_ROOT, "")
        if root:
            return str(Path(root) / AppSettings.get_active_channel())

        # Legacy path stored under the old key.
        saved = AppSettings.settings().value(AppSettings.GAME_INSTALL_PATH, "")
        if saved:
            saved_path = Path(saved)
            if _path_ends_in_channel(saved):
                # Ends with a channel name — trust it.
                return saved
            # Doesn't end with a channel name — might be a stale root.
            # Only trust it if it actually contains channel subdirs.
            if _is_valid_sc_root(saved):
                return saved

        # Installer-written registry key (older flow).
        sc_directory = AppSettings._read_legacy_installer_sc_directory()
        if sc_directory:
            if _path_ends_in_channel(sc_directory):
                AppSettings.settings().setValue(AppSettings.GAME_INSTALL_PATH, sc_directory)
                return sc_directory
            if _is_valid_sc_root(sc_directory):
                AppSettings.settings().setValue(AppSettings.GAME_INSTALL_PATH, sc_directory)
                return sc_directory

        root = _scan_common_sc_install_locations()
        if root:
            result = str(Path(root) / AppSettings.get_active_channel())
            # _scan_common_sc_install_locations only proves SOME channel
            # folder exists at this root (via _is_valid_sc_root) — not
            # necessarily the active one. Caching a path the active
            # channel doesn't actually have would just get discarded by
            # whatever reads it next, forcing a rescan anyway; skip the
            # write so a later channel switch (or the channel actually
            # appearing after an install) gets a fresh scan instead of a
            # stale miss.
            if Path(result).is_dir():
                AppSettings.settings().setValue(AppSettings.GAME_INSTALL_PATH, result)
            return result

        return ""

    @staticmethod
    def get_game_version() -> str:
        """Get Star Citizen game version from build_manifest.id.

        Returns:
            Version string (e.g., "4.7.176.58286") or empty string if not found/invalid
        """
        import json
        game_path = AppSettings.get_game_install_path()
        if not game_path:
            return ""

        manifest_path = Path(game_path) / "build_manifest.id"
        if not manifest_path.exists():
            return ""

        try:
            with open(manifest_path, 'r') as f:
                data = json.load(f)
                version = data.get("Data", {}).get("Version", "")
                return version
        except Exception as e:
            logger.debug(f"Could not read game version from {manifest_path}: {e}")
            return ""

    @staticmethod
    def set_game_install_path(path: str) -> None:
        """Set Star Citizen install path."""
        AppSettings.settings().setValue(AppSettings.GAME_INSTALL_PATH, path)

    @staticmethod
    def get_auto_write_enabled() -> bool:
        """Get auto-write to game enabled flag."""
        return AppSettings.settings().value(AppSettings.AUTO_WRITE_ENABLED, False, type=bool)

    @staticmethod
    def set_auto_write_enabled(enabled: bool) -> None:
        """Set auto-write to game enabled flag."""
        AppSettings.settings().setValue(AppSettings.AUTO_WRITE_ENABLED, enabled)

    @staticmethod
    def _encode_qbytes(value) -> str:
        """Encode a QByteArray / bytes as a base64 ASCII string.

        Window geometry/state come from QWidget.saveGeometry()/saveState() as
        QByteArray. QSettings stores those natively, but the portable backend
        (JsonSettings) json.dumps its store, and a QByteArray isn't
        JSON-serialisable — storing it raw crashed portable-mode close (#141).
        Base64 text round-trips through both backends.
        """
        if not value:
            return ""
        try:
            return base64.b64encode(bytes(value)).decode("ascii")
        except (TypeError, ValueError):
            return ""

    @staticmethod
    def _decode_qbytes(value) -> bytes:
        """Inverse of _encode_qbytes. Tolerates a legacy raw QByteArray / bytes
        value stored in the registry by builds before the base64 change, so
        existing registry installs keep their saved geometry on upgrade."""
        if not value:
            return b""
        if isinstance(value, str):
            try:
                return base64.b64decode(value.encode("ascii"))
            except (ValueError, TypeError):
                return b""
        try:
            return bytes(value)  # legacy QByteArray / bytes from the registry
        except (TypeError, ValueError):
            return b""

    @staticmethod
    def get_window_geometry() -> bytes:
        """Get saved window geometry."""
        return AppSettings._decode_qbytes(
            AppSettings.settings().value(AppSettings.WINDOW_GEOMETRY, "")
        )

    @staticmethod
    def set_window_geometry(geometry) -> None:
        """Save window geometry (stored as base64 text; see _encode_qbytes)."""
        AppSettings.settings().setValue(
            AppSettings.WINDOW_GEOMETRY, AppSettings._encode_qbytes(geometry)
        )

    @staticmethod
    def get_window_state() -> bytes:
        """Get saved window state."""
        return AppSettings._decode_qbytes(
            AppSettings.settings().value(AppSettings.WINDOW_STATE, "")
        )

    @staticmethod
    def set_window_state(state) -> None:
        """Save window state (stored as base64 text; see _encode_qbytes)."""
        AppSettings.settings().setValue(
            AppSettings.WINDOW_STATE, AppSettings._encode_qbytes(state)
        )

    @staticmethod
    def reset_window_layout() -> None:
        """Forget every persisted size: window geometry, dock/toolbar layout,
        and String Editor column widths.

        Backs the "Reset Window Proportions" action. Removing the keys rather
        than writing defaults into them is deliberate — absence is what the
        rest of the code already treats as "never customised", so the window
        falls back to its mode-driven size and the table recomputes its
        column layout, exactly as on a fresh install. Touches nothing else:
        game paths, language, and localization data are unaffected.
        """
        settings = AppSettings.settings()
        for key in (AppSettings.WINDOW_GEOMETRY,
                    AppSettings.WINDOW_STATE,
                    AppSettings.STRING_COLUMN_WIDTHS):
            settings.remove(key)
        settings.sync()

    @staticmethod
    def get_string_column_widths() -> list[int]:
        """Return saved String Editor column widths, or [] if never set.

        Stored as a JSON list string for the same reason as get_owned_items:
        a raw Python list round-trips through the registry as a QStringList.

        An empty list means the user has never resized a column, and the
        table computes its default layout from the current window and data
        instead. That is what makes every fresh install open identically
        while still letting a user's own widths stick once they set them.
        Any non-int or malformed value degrades to [] rather than raising —
        a corrupt setting must never stop the table from being built.
        """
        import json
        raw = AppSettings.settings().value(
            AppSettings.STRING_COLUMN_WIDTHS, "", type=str
        )
        if not raw:
            return []
        try:
            widths = json.loads(raw)
            return [int(w) for w in widths] if isinstance(widths, list) else []
        except (ValueError, TypeError):
            return []

    @staticmethod
    def set_string_column_widths(widths) -> None:
        """Persist String Editor column widths (list of pixel ints).

        Defensive for the same reason the getter is, and more so: this runs
        from closeEvent, so an unhandled coercion error here would surface
        while the window is shutting down. A layout that can't be stored is
        dropped, which just means the table recomputes its default next
        launch.
        """
        import json
        try:
            cleaned = [int(w) for w in widths]
        except (TypeError, ValueError):
            logger.warning("Discarding unstorable column widths: %r", widths)
            return
        AppSettings.settings().setValue(
            AppSettings.STRING_COLUMN_WIDTHS, json.dumps(cleaned)
        )
        AppSettings.settings().sync()

    @staticmethod
    def get_source_path(source_name: str) -> str:
        """Get path/URL for a data source.

        Args:
            source_name: One of SOURCE_GLOBAL, SOURCE_CONTRACTS, SOURCE_COMPONENTS, SOURCE_SHIPS, SOURCE_USER

        Returns:
            Path or URL string, empty string if not set
        """
        key = f"{AppSettings.DATA_SOURCES_PREFIX}/{source_name}/path"
        return AppSettings.settings().value(key, "")

    @staticmethod
    def set_source_path(source_name: str, path: str) -> None:
        """Set path/URL for a data source.

        Args:
            source_name: One of SOURCE_GLOBAL, SOURCE_CONTRACTS, SOURCE_COMPONENTS, SOURCE_SHIPS, SOURCE_USER
            path: File path or URL
        """
        key = f"{AppSettings.DATA_SOURCES_PREFIX}/{source_name}/path"
        AppSettings.settings().setValue(key, path)

    @staticmethod
    def is_source_enabled(source_name: str) -> bool:
        """Check if a data source is enabled.

        Args:
            source_name: One of SOURCE_GLOBAL, SOURCE_CONTRACTS, SOURCE_COMPONENTS, SOURCE_SHIPS, SOURCE_USER

        Returns:
            True if enabled, False otherwise. Defaults to True for Global and User, False for others.
        """
        key = f"{AppSettings.DATA_SOURCES_PREFIX}/{source_name}/enabled"
        # Default: Global and User always enabled, others disabled
        default = source_name in [AppSettings.SOURCE_GLOBAL, AppSettings.SOURCE_USER]
        return AppSettings.settings().value(key, default, type=bool)

    @staticmethod
    def set_source_enabled(source_name: str, enabled: bool) -> None:
        """Enable or disable a data source.

        Args:
            source_name: One of SOURCE_GLOBAL, SOURCE_CONTRACTS, SOURCE_COMPONENTS, SOURCE_SHIPS, SOURCE_USER
            enabled: True to enable, False to disable
        """
        key = f"{AppSettings.DATA_SOURCES_PREFIX}/{source_name}/enabled"
        AppSettings.settings().setValue(key, enabled)

    @staticmethod
    def get_merge_hierarchy() -> list:
        """Get the merge hierarchy (ordered list of source names).

        Returns:
            List of source names in merge order, e.g. ["global", "user"]
        """
        default = [AppSettings.SOURCE_GLOBAL, AppSettings.SOURCE_USER]
        value = AppSettings.settings().value(AppSettings.MERGE_HIERARCHY, default)
        # Handle QVariant/list conversion
        if isinstance(value, str):
            # If stored as comma-separated string, split it
            return value.split(",") if value else default
        return value if value else default

    @staticmethod
    def set_merge_hierarchy(hierarchy: list) -> None:
        """Set the merge hierarchy (ordered list of source names).

        Args:
            hierarchy: List of source names in merge order
        """
        AppSettings.settings().setValue(AppSettings.MERGE_HIERARCHY, hierarchy)

    @staticmethod
    def get_source_auto_update(source_name: str) -> bool:
        """Check if auto-update is enabled for a source.

        Args:
            source_name: One of SOURCE_GLOBAL, SOURCE_CONTRACTS, SOURCE_COMPONENTS, SOURCE_SHIPS
            (SOURCE_USER does not support auto-update)

        Returns:
            True if auto-update enabled, False otherwise. Defaults to True.
        """
        if source_name == AppSettings.SOURCE_USER:
            return False  # User source never auto-updates
        key = f"{AppSettings.SOURCE_AUTO_UPDATE_PREFIX}/{source_name}"
        return AppSettings.settings().value(key, True, type=bool)

    @staticmethod
    def set_source_auto_update(source_name: str, enabled: bool) -> None:
        """Enable or disable auto-update for a source.

        Args:
            source_name: One of SOURCE_GLOBAL, SOURCE_CONTRACTS, SOURCE_COMPONENTS, SOURCE_SHIPS
            enabled: True to auto-update, False to disable
        """
        if source_name == AppSettings.SOURCE_USER:
            return  # Cannot change auto-update for User source
        key = f"{AppSettings.SOURCE_AUTO_UPDATE_PREFIX}/{source_name}"
        AppSettings.settings().setValue(key, enabled)

    # One-shot marker for migrate_remove_retired_url_sources(). Versioned
    # so the migration can pick up new retired source names in later
    # releases without being blocked by an earlier run's marker. Always bump
    # the version when expanding RETIRED_URL_SOURCE_NAMES — the prior marker
    # stays in the registry but is ignored.
    #
    # v3 (1.3.1): re-runs to prune orphan hierarchy entries that v2 left
    # behind. v2 correctly handled URL-backed and orphan-no-path entries
    # in the same pass, but users who had a stored local path at v2-run
    # time (later cleared, leaving an orphan hierarchy slot with no path)
    # didn't get re-cleaned. v3 re-runs the (idempotent) prune so those
    # tail-end orphans surface and get removed. Local-path overrides are
    # still preserved — the URL-vs-local guard inside the migrator is
    # unchanged.
    RETIRED_URL_SOURCES_PRUNED = "_retired_url_sources_pruned_v3"

    # Sources that were retired in 0.7.0 when the app moved to local Data.p4k
    # extraction + locally-generated *_enhancements.ini files. New installs
    # don't get them; existing installs with these sources still in their
    # registry get them pruned by migrate_remove_retired_url_sources().
    RETIRED_URL_SOURCE_NAMES = (
        SOURCE_CONTRACTS,
        SOURCE_COMPONENTS,
        SOURCE_SHIPS,
        SOURCE_COMMODITIES,
        SOURCE_GEAR,
    )

    @staticmethod
    def migrate_legacy_settings() -> None:
        """Initialize default sources for a fresh install.

        Despite the name, this is the "set defaults if no settings exist"
        function — it short-circuits if the global source has already been
        registered. It seeds only the two sources the app actually uses:

          * ``global`` — locally-cached ``base.ini`` from Data.p4k extraction
          * ``user``   — per-channel ``user.ini`` (created lazily on first edit)

        The ``enhancements`` source is dynamically injected by
        :func:`load_sources_from_settings` based on which enhancement
        categories the user has enabled — it doesn't need a registry entry.

        The 0.x defaults registered four extra URL-based sources
        (contracts/components/ships/commodities) pointing at a ``data/``
        folder that was retired in 0.7.0. Those are no longer registered for
        new installs, and existing installs are cleaned up by
        :func:`migrate_remove_retired_url_sources`.
        """
        settings = AppSettings.settings()

        # Idempotence: check the global source registration as the marker.
        # (Pre-1.0 the marker was the contracts source — that key may still
        # exist on upgraders but the dedicated retired-source migrator below
        # will remove it on the same launch.)
        if settings.value(f"{AppSettings.DATA_SOURCES_PREFIX}/{AppSettings.SOURCE_GLOBAL}/path"):
            return

        # Global: locally-cached base.ini, populated by P4K extraction.
        global_local_path = str(AppSettings.get_cache_dir() / 'base.ini')
        AppSettings.set_source_path(AppSettings.SOURCE_GLOBAL, global_local_path)
        AppSettings.set_source_enabled(AppSettings.SOURCE_GLOBAL, True)
        AppSettings.set_source_auto_update(AppSettings.SOURCE_GLOBAL, False)

        # User: per-channel user.ini.
        user_path = str(AppSettings.get_user_ini_path())
        AppSettings.set_source_path(AppSettings.SOURCE_USER, user_path)

        # Default hierarchy: global → user. The enhancements source is
        # auto-inserted between them at load time when its files exist.
        AppSettings.set_merge_hierarchy(
            [AppSettings.SOURCE_GLOBAL, AppSettings.SOURCE_USER]
        )

    @staticmethod
    def migrate_remove_retired_url_sources() -> bool:
        """One-shot prune of the four URL-based sources retired in 0.7.0.

        Pre-1.0 ``migrate_legacy_settings()`` registered ``contracts``,
        ``components``, ``ships``, and ``commodities`` pointing at a
        ``data/<name>.ini`` folder in the GitHub repo. That folder was
        retired in 0.7.0 when the app switched to local Data.p4k extraction
        + locally-generated ``*_enhancements.ini``, so those URLs have been
        404-ing silently for ~10 versions and produce zero-key rows in the
        Merge Preview.

        For each retired source name:
          * if its registered path is a URL (the original default state),
            delete the source's registry entries and remove it from the
            merge hierarchy;
          * if its path is a local file (rare — user manually re-pointed
            it at their own INI), leave it alone.

        Marker-gated via :data:`RETIRED_URL_SOURCES_PRUNED` so this runs
        exactly once per user.

        Returns:
            True if any source was actually removed, False if the migration
            had already run or there was nothing to clean up.
        """
        settings = AppSettings.settings()
        if settings.value(AppSettings.RETIRED_URL_SOURCES_PRUNED, False, type=bool):
            return False

        # First pass: figure out which retired sources to prune. A source is
        # eligible if EITHER its registry path is a URL (the original default
        # state) OR it's in the merge hierarchy with no path stored at all
        # (orphan hierarchy entry — happens when an even earlier version
        # added the name to the hierarchy without a per-source registration).
        # Sources with a local-file path are preserved (rare user override).
        prior_hierarchy = AppSettings.get_merge_hierarchy()
        in_hierarchy = set(prior_hierarchy)
        prune: list[str] = []
        for source_name in AppSettings.RETIRED_URL_SOURCE_NAMES:
            path = AppSettings.get_source_path(source_name)
            if path and not (path.startswith('http://') or path.startswith('https://')):
                logger.info(
                    f"Skipping retired-source prune for {source_name}: "
                    f"path is local ({path}), not a URL — preserving user override"
                )
                continue
            if not path and source_name not in in_hierarchy:
                # No path AND not in hierarchy — nothing to prune for this one.
                continue
            prune.append(source_name)

        for source_name in prune:
            # Nuke every key under data_sources/<name>/... (no-op if no path
            # was registered, which is fine — Qt's remove() on a missing key
            # is idempotent).
            settings.remove(f"{AppSettings.DATA_SOURCES_PREFIX}/{source_name}")

        if prune:
            new_hierarchy = [s for s in prior_hierarchy if s not in prune]
            if new_hierarchy != prior_hierarchy:
                AppSettings.set_merge_hierarchy(new_hierarchy)
            logger.info(
                f"Pruned retired URL-based sources: {prune} — "
                f"these defunct defaults from pre-0.7.0 produce no data and "
                f"have been removed from the merge hierarchy"
            )

        settings.setValue(AppSettings.RETIRED_URL_SOURCES_PRUNED, True)
        return bool(prune)

    @staticmethod
    def migrate_global_to_p4k_local() -> bool:
        """Migrate global source from any remote URL to local cached base.ini (v0.6.0+).

        For existing users whose Global source still points to MrKraken, BeltaKoda,
        or any other remote URL: switch to local cache path and disable auto-update
        so the file is managed by P4K extraction instead of remote download.

        Returns:
            True if migration was performed, False if already using local path.
        """
        current_path = AppSettings.get_source_path(AppSettings.SOURCE_GLOBAL)
        if current_path.startswith('http'):
            local_path = str(AppSettings.get_cache_dir() / 'base.ini')
            AppSettings.set_source_path(AppSettings.SOURCE_GLOBAL, local_path)
            AppSettings.set_source_auto_update(AppSettings.SOURCE_GLOBAL, False)
            logger.info("Migrated global source from remote URL to local P4K cache path")
            return True
        return False





    @staticmethod
    def _resolve_docs_base() -> Path:
        """Resolve the real Documents root (honors OneDrive redirection)."""
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
            )
            docs_path = Path(winreg.QueryValueEx(key, "Personal")[0])
            winreg.CloseKey(key)
        except (WindowsError, OSError):
            docs_path = Path.home() / "Documents"
        return docs_path

    # ── Registry appname migration (0.9.0 rebrand) ──────────────────────────
    # Rebrand moved the product name from "SC Localization Editor" to
    # "Smart Citizen" in 0.9.0. The Documents folder got renamed back then
    # (see migrate_docs_folder_rename). The registry node was left alone
    # to preserve existing users' settings, which meant fresh-eyes readers
    # kept seeing the old name under HKCU. The helpers below perform a
    # one-shot copy from the legacy node to the new node, then delete the
    # old subtree. A marker value (_MIGRATION_MARKER) short-circuits
    # subsequent runs so this is cheap on every startup.

    _MIGRATION_MARKER = "_migrated_from_legacy_appname"

    @staticmethod
    def migrate_registry_appname() -> None:
        r"""Copy HKCU\Software\<ORG>\SC Localization Editor → HKCU\Software\<ORG>\Smart Citizen.

        Must run **before** any ``AppSettings.settings()`` call — QSettings
        under the new APP_NAME would otherwise read from an empty node and
        silently lose every saved preference (themes, paths, favorites,
        window geometry, the USER_DATA_DIR override, etc.).

        Idempotent: a marker value written under the new node on first
        success prevents re-migration on every startup. Fresh installs
        (no legacy node present) stamp the marker directly so the check
        stays cheap.
        """
        org = AppSettings.ORG_NAME
        old_path = rf"SOFTWARE\{org}\{AppSettings._LEGACY_APP_NAME}"
        new_path = rf"SOFTWARE\{org}\{AppSettings.APP_NAME}"

        # Fast-path: marker already set → nothing to do.
        if AppSettings._reg_has_marker(new_path, AppSettings._MIGRATION_MARKER):
            return

        # No legacy node present — this is a fresh install (or an already-
        # cleaned-up migration where the marker was somehow lost). Stamp
        # the marker so future runs short-circuit.
        if not AppSettings._reg_key_exists(old_path):
            AppSettings._reg_write_marker(new_path, AppSettings._MIGRATION_MARKER)
            return

        logger.info(
            f"Migrating registry settings "
            f"HKCU\\{old_path}  →  HKCU\\{new_path}"
        )
        try:
            AppSettings._reg_copy_tree(old_path, new_path)
            AppSettings._reg_write_marker(new_path, AppSettings._MIGRATION_MARKER)
            AppSettings._reg_delete_tree(old_path)
            logger.info("Registry migration complete — legacy node removed")
        except OSError as e:
            # Leave the marker unset so we retry next launch. Log loudly
            # so any partial migration is visible in the Log tab.
            logger.error(f"Registry migration failed: {e}", exc_info=True)

    @staticmethod
    def _reg_key_exists(path: str) -> bool:
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ)
            winreg.CloseKey(k)
            return True
        except FileNotFoundError:
            return False

    @staticmethod
    def _reg_has_marker(path: str, marker: str) -> bool:
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ)
        except FileNotFoundError:
            return False
        try:
            winreg.QueryValueEx(k, marker)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(k)

    @staticmethod
    def _reg_write_marker(path: str, marker: str) -> None:
        k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, path)
        try:
            winreg.SetValueEx(k, marker, 0, winreg.REG_SZ, "1")
        finally:
            winreg.CloseKey(k)

    @staticmethod
    def _reg_copy_tree(src_path: str, dst_path: str) -> None:
        """Recursive copy of every value and subkey from src to dst under HKCU.

        Preserves value types (REG_SZ / REG_DWORD / REG_BINARY / REG_MULTI_SZ
        / REG_EXPAND_SZ) by passing EnumValue's returned type directly to
        SetValueEx. Creates dst and its subtree as needed.
        """
        src = winreg.OpenKey(winreg.HKEY_CURRENT_USER, src_path, 0, winreg.KEY_READ)
        dst = winreg.CreateKey(winreg.HKEY_CURRENT_USER, dst_path)
        try:
            # Values at this level
            i = 0
            while True:
                try:
                    name, data, vtype = winreg.EnumValue(src, i)
                except OSError:
                    break
                # Skip the marker if it happens to exist on the source side
                # (shouldn't, but defensive against manual registry edits).
                if name != AppSettings._MIGRATION_MARKER:
                    winreg.SetValueEx(dst, name, 0, vtype, data)
                i += 1
            # Recurse into subkeys
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(src, i)
                except OSError:
                    break
                AppSettings._reg_copy_tree(
                    f"{src_path}\\{sub}", f"{dst_path}\\{sub}"
                )
                i += 1
        finally:
            winreg.CloseKey(src)
            winreg.CloseKey(dst)

    @staticmethod
    def _reg_delete_tree(path: str) -> None:
        """Depth-first delete of an HKCU subtree (winreg.DeleteKey refuses
        to remove a key that still has children, so we strip leaves first)."""
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_ALL_ACCESS
            )
        except FileNotFoundError:
            return
        try:
            while True:
                try:
                    sub = winreg.EnumKey(key, 0)
                except OSError:
                    break
                AppSettings._reg_delete_tree(f"{path}\\{sub}")
        finally:
            winreg.CloseKey(key)
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        except FileNotFoundError:
            pass

    @staticmethod
    def migrate_docs_folder_rename() -> None:
        r"""Rename legacy Documents\SC Localization Editor\ → Documents\Smart Citizen\.

        Safe to call on every startup — only acts when the old folder exists
        and the new one does not. The installer handles this on upgrade; this
        path covers dev runs and anyone who bypassed the installer.
        """
        docs = AppSettings._resolve_docs_base()
        old_dir = docs / "SC Localization Editor"
        new_dir = docs / "Smart Citizen"
        if old_dir.exists() and not new_dir.exists():
            try:
                old_dir.rename(new_dir)
                logger.info(f"Renamed data folder: {old_dir} → {new_dir}")
            except OSError as e:
                logger.warning(f"Could not rename data folder {old_dir}: {e}")

    @staticmethod
    def migrate_game_path_to_channel_layout() -> None:
        r"""One-shot migration to the 0.9.3 channel-aware layout.

        Two orthogonal bits of migration happen here; both are idempotent
        and short-circuited by a single marker (:data:`CHANNEL_LAYOUT_MIGRATED`)
        so every subsequent launch no-ops cheaply.

        **Registry side:** if ``GAME_INSTALL_PATH`` is set but ``SC_INSTALL_ROOT``
        isn't, split the stored path on a trailing ``\{CHANNEL}`` suffix and
        record the parent as ``SC_INSTALL_ROOT``. ``ACTIVE_CHANNEL`` is set
        to the stripped channel name (``LIVE`` when the stored path has no
        recognizable channel suffix — matches pre-0.9.3 behavior).

        **Filesystem side:** if ``Documents\Smart Citizen\`` contains the
        old flat layout (``base.ini`` / ``cache\`` / ``backups\`` / ``user.ini``)
        and no ``LIVE\`` (or other channel) subfolder exists, move those
        entries into a new ``LIVE\`` subfolder so every path helper starts
        resolving channel-scoped. Skips anything that looks like a channel
        directory, the migration marker, and the registry mirror files,
        leaving unrelated files untouched.

        Failures during the filesystem move are logged but not raised — the
        app degrades to "user re-runs Extract" at worst rather than
        crashing at startup.
        """
        settings = AppSettings.settings()
        if settings.value(AppSettings.CHANNEL_LAYOUT_MIGRATED, False, type=bool):
            return

        # --- Registry: split GAME_INSTALL_PATH into SC_INSTALL_ROOT + ACTIVE_CHANNEL
        if not settings.value(AppSettings.SC_INSTALL_ROOT, ""):
            legacy = settings.value(AppSettings.GAME_INSTALL_PATH, "")
            if legacy:
                legacy_path = Path(legacy)
                tail = legacy_path.name.upper()
                channels_upper = {c.upper(): c for c in AppSettings.AVAILABLE_CHANNELS}
                if tail in channels_upper:
                    settings.setValue(AppSettings.SC_INSTALL_ROOT, str(legacy_path.parent))
                    settings.setValue(AppSettings.ACTIVE_CHANNEL, channels_upper[tail])
                    logger.info(
                        f"Migrated GAME_INSTALL_PATH {legacy!r} → "
                        f"SC_INSTALL_ROOT={legacy_path.parent}, "
                        f"ACTIVE_CHANNEL={channels_upper[tail]}"
                    )
                else:
                    settings.setValue(AppSettings.SC_INSTALL_ROOT, legacy)
                    settings.setValue(AppSettings.ACTIVE_CHANNEL, AppSettings.DEFAULT_CHANNEL)
                    logger.info(
                        f"Migrated GAME_INSTALL_PATH {legacy!r} (no channel suffix) → "
                        f"SC_INSTALL_ROOT={legacy}, ACTIVE_CHANNEL={AppSettings.DEFAULT_CHANNEL}"
                    )

        if not settings.value(AppSettings.ACTIVE_CHANNEL, ""):
            settings.setValue(AppSettings.ACTIVE_CHANNEL, AppSettings.DEFAULT_CHANNEL)

        # --- Filesystem: move flat layout into a {active_channel}/ subfolder
        root = AppSettings.get_user_data_dir()
        channels_upper = {c.upper() for c in AppSettings.AVAILABLE_CHANNELS}

        # Whether a channel subfolder has any *real* content (files or nested
        # dirs) vs. just being an empty shell auto-created by a path helper's
        # ``mkdir(exist_ok=True)`` — the latter shouldn't block migration.
        def _has_content(p: Path) -> bool:
            try:
                for sub in p.rglob("*"):
                    if sub.is_file():
                        return True
            except OSError:
                return False
            return False

        populated_channel_dirs = [
            p for p in (root.iterdir() if root.exists() else [])
            if p.is_dir() and p.name.upper() in channels_upper and _has_content(p)
        ]

        if populated_channel_dirs:
            logger.info(
                f"Populated channel subfolders already present under {root}: "
                f"{[p.name for p in populated_channel_dirs]}; skipping filesystem migration"
            )
        else:
            target_channel = settings.value(AppSettings.ACTIVE_CHANNEL, AppSettings.DEFAULT_CHANNEL)
            target_dir = root / target_channel
            moved = []
            skipped = []
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
                for entry in list(root.iterdir()):
                    if entry == target_dir:
                        continue
                    # Skip anything that matches another channel name — either
                    # a populated sibling channel dir (bail above caught that)
                    # or an empty shell for a different channel (we leave
                    # alone; the current active channel is the only migration
                    # target).
                    if entry.is_dir() and entry.name.upper() in channels_upper:
                        skipped.append(entry.name)
                        continue
                    try:
                        # If the target already has an entry of the same name
                        # (e.g. empty ``LIVE\cache\`` auto-created by a path
                        # helper before the migrator ran), merge by moving
                        # the flat entry's contents into the existing target
                        # and then removing the now-empty flat dir.
                        dest = target_dir / entry.name
                        if dest.exists():
                            if entry.is_dir() and dest.is_dir():
                                for child in list(entry.iterdir()):
                                    try:
                                        child.rename(dest / child.name)
                                    except OSError as move_err:
                                        logger.warning(
                                            f"Could not merge {child} into {dest}: {move_err}"
                                        )
                                try:
                                    entry.rmdir()  # now empty
                                except OSError:
                                    pass
                                moved.append(f"{entry.name}/* → {dest}")
                                continue
                            # File-vs-file or mismatched-type collision —
                            # skip with a warning; user keeps both copies.
                            logger.warning(
                                f"Migration skipped {entry} — target {dest} already exists"
                            )
                            skipped.append(entry.name)
                            continue
                        entry.rename(dest)
                        moved.append(entry.name)
                    except OSError as move_err:
                        logger.warning(
                            f"Could not move {entry} into {target_dir}: {move_err}"
                        )
                if moved:
                    logger.info(
                        f"Migrated flat user-data layout into {target_dir}: "
                        f"moved {moved}"
                    )
                if skipped:
                    logger.debug(f"Skipped (already channel dirs or collisions): {skipped}")
            except OSError as e:
                logger.warning(f"Channel-layout filesystem migration failed: {e}")

        settings.setValue(AppSettings.CHANNEL_LAYOUT_MIGRATED, True)
        settings.sync()

    @staticmethod
    def _get_user_data_dir_override() -> str:
        """Return the configured user-data directory override, if any.

        Current builds store this as ``user_data_dir``. Some docs and manual
        support notes referred to ``UserDataDir``; migrate that alias lazily
        so users who followed those instructions don't fall back to Documents.
        """
        settings = AppSettings.settings()
        raw = settings.value(AppSettings.USER_DATA_DIR, "", type=str)
        if raw and str(raw).strip():
            return str(raw).strip()

        for alias in AppSettings.USER_DATA_DIR_ALIASES:
            raw_alias = settings.value(alias, "", type=str)
            if raw_alias and str(raw_alias).strip():
                value = str(raw_alias).strip()
                settings.setValue(AppSettings.USER_DATA_DIR, value)
                settings.sync()
                logger.info(
                    f"Migrated user data directory setting {alias} → "
                    f"{AppSettings.USER_DATA_DIR}: {value}"
                )
                return value

        return ""

    @staticmethod
    def get_user_data_dir_override() -> str:
        """Return the explicit user-data directory override, or ``""`` when unset."""
        return AppSettings._get_user_data_dir_override()

    @staticmethod
    def _get_cache_dir_override() -> str:
        """Return the configured DataForge cache-directory override, if any."""
        settings = AppSettings.settings()
        raw = settings.value(AppSettings.CACHE_DIR, "", type=str)
        return str(raw).strip() if raw and str(raw).strip() else ""

    @staticmethod
    def get_cache_dir_override() -> str:
        """Return the explicit DataForge cache directory override, or ``""`` when unset."""
        return AppSettings._get_cache_dir_override()

    @staticmethod
    def set_cache_dir(path: "str | Path | None") -> None:
        """Persist (or clear) the DataForge cache directory override.

        ``None`` or an empty string clears the override; subsequent
        :meth:`get_dataforge_cache_dir` calls fall back to the platform
        default (%LOCALAPPDATA% in registry mode, ``<exe-dir>/data/cache/``
        in portable mode).
        """
        settings = AppSettings.settings()
        if path is None or (isinstance(path, str) and not path.strip()):
            settings.remove(AppSettings.CACHE_DIR)
        else:
            settings.setValue(AppSettings.CACHE_DIR, str(path))
        settings.sync()

    @staticmethod
    def get_pending_cache_cleanup() -> str:
        """Return the path queued for deletion after the next successful P4K
        re-extraction, or ``""`` when no cleanup is pending."""
        settings = AppSettings.settings()
        raw = settings.value(AppSettings.PENDING_CACHE_CLEANUP, "", type=str)
        return str(raw).strip() if raw and str(raw).strip() else ""

    @staticmethod
    def set_pending_cache_cleanup(path: "str | Path | None") -> None:
        """Mark (or clear) a directory for deletion after re-extraction."""
        settings = AppSettings.settings()
        if path is None or (isinstance(path, str) and not path.strip()):
            settings.remove(AppSettings.PENDING_CACHE_CLEANUP)
        else:
            settings.setValue(AppSettings.PENDING_CACHE_CLEANUP, str(path))
        settings.sync()

    @staticmethod
    def get_user_data_dir() -> Path:
        r"""Get the user data directory.

        Portable mode (build_mode.IS_PORTABLE = True): always returns
        the ``data/`` directory next to the running binary. Registry
        override and Documents fallback are skipped — portability is
        the whole point. ``<exe-dir>/data/`` when frozen,
        ``<repo-root>/portable_data/`` when running from source.

        Registry mode (default) resolution order:
          1. Registry override ``USER_DATA_DIR`` — set by users who want the
             cache/user.ini off a OneDrive-synced Documents folder (extraction
             and rmtree are much slower under OneDrive's sync hooks).
          2. ``Documents\Smart Citizen\`` via the ``Personal`` shell-folder
             key, which honors OneDrive/folder redirection.
          3. ``~/Documents/Smart Citizen\`` as a last-ditch fallback.

        Returns:
            Path to the resolved directory (created if needed).
        """
        # Portable build: always next to the binary, no overrides.
        from src.utils import build_mode
        if build_mode.IS_PORTABLE:
            data_dir = AppSettings._portable_data_dir()
            data_dir.mkdir(parents=True, exist_ok=True)
            return data_dir

        override = AppSettings._get_user_data_dir_override()
        if override:
            override_path = Path(os.path.expandvars(override)).expanduser().resolve()
            try:
                override_path.mkdir(parents=True, exist_ok=True)
                return override_path
            except OSError as e:
                logger.warning(
                    f"USER_DATA_DIR override {override!r} not usable ({e}); "
                    f"falling back to Documents default"
                )
        data_dir = AppSettings._resolve_docs_base() / "Smart Citizen"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir

    @staticmethod
    def _portable_data_dir() -> Path:
        """Resolve the portable-mode data root.

        Frozen (PyInstaller): ``<exe-dir>/data/`` — true portable, no
        machine state outside the .exe's folder. ``sys.executable``
        points at the bundled .exe, not the Python interpreter.

        Unfrozen (dev / tests): ``<repo-root>/portable_data/`` so a
        developer running ``python src/main.py`` with a monkeypatched
        IS_PORTABLE = True can exercise the portable code path without
        accidentally polluting Documents\\Smart Citizen.
        """
        import sys
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent / "data"
        # src/utils/settings.py → src/utils → src → repo root
        repo_root = Path(__file__).resolve().parent.parent.parent
        return repo_root / "portable_data"

    @staticmethod
    def setup_portable_backend_if_needed() -> None:
        """Wire the JSON settings backend on portable startup.

        Called from main.py once at startup, BEFORE any AppSettings
        accessor that depends on get_user_data_dir() (which the JSON
        backend file path is derived from). No-op in registry mode —
        the existing QSettings default keeps working.

        Idempotent: safe to call multiple times. Subsequent calls are
        a no-op once `_backend` is set.
        """
        from src.utils import build_mode
        if not build_mode.IS_PORTABLE:
            return
        if AppSettings._backend is not None:
            return
        from src.utils.json_settings import JsonSettings
        # Lives next to all the other portable data so the whole
        # standalone install is one folder the user can copy/move.
        config_path = AppSettings._portable_data_dir() / "config.json"
        AppSettings._backend = JsonSettings(config_path)
        logger.info("Portable mode active — settings backend: %s", config_path)

    @staticmethod
    def set_user_data_dir(path: "str | Path | None") -> None:
        r"""Override the user data directory. Pass ``None`` or an empty
        string to clear the override and revert to the Documents default.

        Writes to the Osiris DevWorks\Smart Citizen registry key (same scope
        as every other AppSettings value), so it survives reinstalls and is
        per-user.
        """
        settings = AppSettings.settings()
        if not path:
            settings.remove(AppSettings.USER_DATA_DIR)
            for alias in AppSettings.USER_DATA_DIR_ALIASES:
                settings.remove(alias)
        else:
            expanded = Path(os.path.expandvars(str(path))).expanduser().resolve()
            settings.setValue(AppSettings.USER_DATA_DIR, str(expanded))
            for alias in AppSettings.USER_DATA_DIR_ALIASES:
                settings.remove(alias)
        settings.sync()

    # ── Channel selection API ────────────────────────────────────────────────

    @staticmethod
    def get_active_channel() -> str:
        r"""Return the active Star Citizen channel (LIVE/PTU/EPTU/HOTFIX/TECH-PREVIEW).

        Falls back to :data:`DEFAULT_CHANNEL` when unset or unrecognized —
        safer than raising, since path helpers downstream depend on this and
        a bad value would break every subsequent call.
        """
        value = AppSettings.settings().value(AppSettings.ACTIVE_CHANNEL, AppSettings.DEFAULT_CHANNEL)
        if value in AppSettings.AVAILABLE_CHANNELS:
            return value
        logger.warning(
            f"Unknown active_channel {value!r}; defaulting to {AppSettings.DEFAULT_CHANNEL}"
        )
        return AppSettings.DEFAULT_CHANNEL

    @staticmethod
    def set_active_channel(channel: str) -> None:
        """Persist the active channel name. Must be a member of AVAILABLE_CHANNELS.

        Also syncs the legacy GAME_INSTALL_PATH key so any pre-migration
        caller still reads the correct channel-specific path without needing
        a manual sync at every call site.
        """
        if channel not in AppSettings.AVAILABLE_CHANNELS:
            raise ValueError(
                f"Unknown channel {channel!r}; expected one of {AppSettings.AVAILABLE_CHANNELS}"
            )
        AppSettings.settings().setValue(AppSettings.ACTIVE_CHANNEL, channel)
        AppSettings.settings().sync()
        # Sync legacy key so all callers stay current with no extra bookkeeping.
        AppSettings.set_game_install_path(AppSettings.get_channel_install_path())

    @staticmethod
    def get_sc_install_root() -> str:
        r"""Return the Star Citizen install root (parent of the channel folders).

        This is the directory containing ``LIVE\``, ``PTU\``, etc. Resolution
        order mirrors :meth:`get_game_install_path`:
          1. QSettings value for :data:`SC_INSTALL_ROOT`
          2. Derived from legacy ``GAME_INSTALL_PATH`` (strip trailing
             ``\LIVE`` if present)
          3. The old installer's registry key (``sc_directory``)
          4. Auto-detected by scanning every local drive letter for a
             real install at a common RSI Launcher install path (see
             :func:`_scan_common_sc_install_locations`) -- covers a
             default C:\\ install, a secondary drive kept in the same
             shape, and one nested under a personal "Games" folder.
             Persists the result once found, so this scan only runs
             once per profile.

        Returns an empty string when nothing resolves — the Config tab shows
        a placeholder in that case.
        """
        saved = AppSettings.settings().value(AppSettings.SC_INSTALL_ROOT, "")

        # Cross-check: the installer writes both game_install_path and
        # sc_install_root.  If the user reinstalled with a different SC
        # path, game_install_path is fresh but a stale sc_install_root
        # from a prior migration could survive (pre-1.4.2 installers
        # didn't write sc_install_root).  When the two disagree, derive
        # from game_install_path — it was written more recently.
        legacy = AppSettings.settings().value(AppSettings.GAME_INSTALL_PATH, "")
        if saved and legacy:
            legacy_path = Path(legacy)
            if _path_ends_in_channel(legacy):
                derived_root = str(legacy_path.parent)
                if os.path.normcase(derived_root) != os.path.normcase(saved):
                    logger.info(
                        f"SC_INSTALL_ROOT {saved!r} disagrees with "
                        f"GAME_INSTALL_PATH {legacy!r} — using derived root {derived_root!r}"
                    )
                    AppSettings.settings().setValue(AppSettings.SC_INSTALL_ROOT, derived_root)
                    return derived_root

        if saved and _is_valid_sc_root(saved):
            return saved

        # Derive from the legacy per-channel path if it's set.
        if legacy:
            legacy_path = Path(legacy)
            if _path_ends_in_channel(legacy):
                return str(legacy_path.parent)
            if _is_valid_sc_root(legacy):
                return legacy

        # Installer-written registry key (older flow) — same source
        # get_game_install_path() falls back to. Without this, a fresh
        # profile whose only trace of the install is this key sees
        # get_game_install_path() (and thus extraction) resolve correctly
        # while the Config tab, which reads only this method, stayed blank
        # until some other code path happened to call get_game_install_path()
        # first and persist GAME_INSTALL_PATH as a side effect.
        sc_directory = AppSettings._read_legacy_installer_sc_directory()
        if sc_directory:
            root = None
            if _path_ends_in_channel(sc_directory):
                root = str(Path(sc_directory).parent)
            elif _is_valid_sc_root(sc_directory):
                root = sc_directory
            if root:
                AppSettings.settings().setValue(AppSettings.SC_INSTALL_ROOT, root)
                return root

        root = _scan_common_sc_install_locations()
        if root:
            AppSettings.settings().setValue(AppSettings.SC_INSTALL_ROOT, root)
            return root
        return ""

    @staticmethod
    def set_sc_install_root(path: str) -> None:
        """Persist the SC install root. Callers should pass the directory
        that contains ``LIVE\\``, ``PTU\\``, etc., not a specific channel.

        Also syncs the legacy GAME_INSTALL_PATH key so all callers stay
        consistent without manual bookkeeping at each call site.
        """
        AppSettings.settings().setValue(AppSettings.SC_INSTALL_ROOT, path)
        # Compose the active-channel path from the value we were just handed,
        # NOT via get_channel_install_path()/get_sc_install_root(). That getter
        # runs a cross-check against the still-stale GAME_INSTALL_PATH and, when
        # the user switches install locations (e.g. C: default → D:), reverts
        # SC_INSTALL_ROOT back to the old root before we get a chance to refresh
        # the legacy key — silently discarding the path the user just picked.
        channel_path = (
            str(Path(path) / AppSettings.get_active_channel()) if path else ""
        )
        AppSettings.set_game_install_path(channel_path)

    @staticmethod
    def get_available_channels() -> list[str]:
        """Return channels for which ``{root}\\{channel}\\Data.p4k`` exists.

        Used by the Config tab to grey-out channel combo entries the user
        can't actually switch to. When the root isn't configured yet we
        return all channels so the combo isn't empty — the user can still
        pick one before the path is set.
        """
        root = AppSettings.get_sc_install_root()
        if not root:
            return list(AppSettings.AVAILABLE_CHANNELS)
        root_path = Path(root)
        return [
            channel for channel in AppSettings.AVAILABLE_CHANNELS
            if (root_path / channel / "Data.p4k").exists()
        ]

    @staticmethod
    def get_channel_install_path() -> str:
        r"""Return ``{sc_install_root}\{active_channel}``.

        This is the "game install path" for whichever channel is currently
        active — equivalent to what :meth:`get_game_install_path` returned
        before the channel layout landed.
        """
        root = AppSettings.get_sc_install_root()
        if not root:
            return ""
        return str(Path(root) / AppSettings.get_active_channel())

    @staticmethod
    def get_channel_data_dir() -> Path:
        r"""Return ``{user_data_dir}\{active_channel}\`` (created if needed).

        All per-channel user data (cache, backups, user.ini, DataForge
        extraction) lives under this. :meth:`get_user_data_dir` stays the
        root holding every channel's subfolder.
        """
        channel_dir = AppSettings.get_user_data_dir() / AppSettings.get_active_channel()
        channel_dir.mkdir(parents=True, exist_ok=True)
        return channel_dir

    # ── Channel-scoped cache/backup/user.ini paths ──────────────────────────
    # These all used to nest directly under get_user_data_dir(); now they
    # nest under the active channel's subfolder. That makes every downstream
    # caller channel-aware automatically.

    @staticmethod
    def get_cache_dir() -> Path:
        r"""Get the active channel's cache directory (``…\{channel}\cache\``)."""
        cache_dir = AppSettings.get_channel_data_dir() / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    @staticmethod
    def get_base_ini_path(language: "str | None" = None) -> Path:
        r"""Path to the base.ini for *language* (default: the selected language).

        English uses the P4K-extracted base.ini at the channel cache root
        (``…\{channel}\cache\base.ini``). Other languages use a downloaded
        global.ini cached per-language at ``…\{channel}\cache\lang\{language}\
        base.ini`` so switching back to a previously-used language reuses the
        cached copy instead of re-downloading. The parent directory is created
        on demand for non-English languages.
        """
        if language is None:
            language = AppSettings.get_selected_language()
        cache_dir = AppSettings.get_cache_dir()
        if language == AppSettings.DEFAULT_LANGUAGE:
            return cache_dir / "base.ini"
        lang_dir = cache_dir / "lang" / language
        lang_dir.mkdir(parents=True, exist_ok=True)
        return lang_dir / "base.ini"

    @staticmethod
    def get_enhancements_dir(language: "str | None" = None) -> Path:
        r"""Directory holding *language*'s generated ``*_enhancements.ini`` files.

        Enhancements always live next to the base.ini they were generated
        from, so this is just ``get_base_ini_path(language).parent``: the
        channel cache root for English (``…\{channel}\cache\``), and the
        per-language subdir for everything else (``…\cache\lang\{language}\``).
        Routing every enhancement read/write through here is what makes a
        non-English language show its own prose with the English stat blocks
        (#30, Approach 1) instead of the English enhancements bleeding through.
        """
        return AppSettings.get_base_ini_path(language).parent

    # Marker file stamped into a language's enhancement dir recording which
    # DataForge build its enhancements were generated against. Regeneration is
    # forced when this is missing or stale (see get_/set_enhancements_stamp).
    ENHANCEMENTS_STAMP_NAME = ".dataforge_stamp"

    @staticmethod
    def get_enhancements_stamp(language: "str | None" = None) -> str:
        """Return the DataForge build key recorded for *language*'s enhancements,
        or '' when no stamp has been written yet."""
        stamp = AppSettings.get_enhancements_dir(language) / AppSettings.ENHANCEMENTS_STAMP_NAME
        try:
            return stamp.read_text(encoding="utf-8").strip()
        except (OSError, ValueError):
            # ValueError: a corrupt stamp raises UnicodeDecodeError (#251
            # bug class) — treat it like a missing stamp, not a crash.
            return ""

    @staticmethod
    def set_enhancements_stamp(key: str, language: "str | None" = None) -> None:
        """Record *key* (a DataForge build fingerprint) for *language*'s
        enhancements, so a later switch can tell fresh from stale."""
        stamp = AppSettings.get_enhancements_dir(language) / AppSettings.ENHANCEMENTS_STAMP_NAME
        try:
            stamp.parent.mkdir(parents=True, exist_ok=True)
            stamp.write_text(key, encoding="utf-8")
        except OSError as e:
            logger.warning(f"Could not write enhancements stamp for {language!r}: {e}")

    # Marker file stamped into a language's enhancement dir recording which
    # Tag Builder config its enhancements were generated against. Sibling of
    # ENHANCEMENTS_STAMP_NAME: that one tracks the DataForge *build*, this one
    # tracks the *tag config*, so the Save Tag Changes button can do a real
    # per-channel freshness check on switch instead of always lighting up.
    TAG_CONFIG_STAMP_NAME = ".tag_config_stamp"

    @staticmethod
    def get_tag_config_stamp(language: "str | None" = None) -> str:
        """Return the Tag Builder config fingerprint recorded for *language*'s
        enhancements, or '' when no stamp has been written yet."""
        stamp = AppSettings.get_enhancements_dir(language) / AppSettings.TAG_CONFIG_STAMP_NAME
        try:
            return stamp.read_text(encoding="utf-8").strip()
        except (OSError, ValueError):
            # ValueError: a corrupt stamp raises UnicodeDecodeError (#251
            # bug class) — treat it like a missing stamp, not a crash.
            return ""

    @staticmethod
    def set_tag_config_stamp(key: str, language: "str | None" = None) -> None:
        """Record *key* (a Tag Builder config fingerprint) for *language*'s
        enhancements, so a later channel switch can tell whether the current
        Tag Builder config still matches what these INIs were generated with."""
        stamp = AppSettings.get_enhancements_dir(language) / AppSettings.TAG_CONFIG_STAMP_NAME
        try:
            stamp.parent.mkdir(parents=True, exist_ok=True)
            stamp.write_text(key, encoding="utf-8")
        except OSError as e:
            logger.warning(f"Could not write tag-config stamp for {language!r}: {e}")

    @staticmethod
    def get_current_tag_config_fingerprint() -> str:
        """Fingerprint of the Tag Builder config as it stands in settings right
        now — compare against get_tag_config_stamp() to decide whether a
        channel's generated INIs already carry the current tags."""
        from src.utils.tag_builder import tag_config_fingerprint
        return tag_config_fingerprint(
            AppSettings.get_all_tag_configs(),
            AppSettings.get_tag_annotate_mission_descs(),
        )

    @staticmethod
    def get_language_source_override(language: str) -> str:
        """User-set override URL for *language*'s base.ini, or '' if unset."""
        raw = AppSettings.settings().value(
            f"{AppSettings.LANG_SOURCE_OVERRIDE_PREFIX}/{language}", "", type=str
        )
        return str(raw or "")

    @staticmethod
    def set_language_source_override(language: str, url: str) -> None:
        """Persist (or clear, when *url* is empty) the override URL for *language*."""
        key = f"{AppSettings.LANG_SOURCE_OVERRIDE_PREFIX}/{language}"
        if url:
            AppSettings.settings().setValue(key, url)
        else:
            AppSettings.settings().remove(key)

    @staticmethod
    def get_language_base_url(language: str) -> str:
        """Resolve the global.ini download URL for *language*.

        User override (Map Language File dialog) wins over the bundled
        ``languages/sources.json`` map. Returns '' when nothing is mapped
        (e.g. English, which uses the local P4K extraction, or a language
        with no URL yet).
        """
        override = AppSettings.get_language_source_override(language)
        if override:
            return override
        return _bundled_language_sources().get(language, "")

    @staticmethod
    def get_user_ini_path() -> Path:
        r"""Get the active channel's ``user.ini`` path.

        Each channel has its own user.ini — PTU and LIVE can have entirely
        different loc-key sets, so sharing edits across channels would
        require merging logic we don't want to maintain.

        Migrates from ``overrides.ini`` → ``user.ini`` on first call if
        needed, within the active channel's folder.
        """
        data_dir = AppSettings.get_channel_data_dir()
        user_ini = data_dir / "user.ini"
        old_overrides = data_dir / "overrides.ini"

        if old_overrides.exists() and not user_ini.exists():
            try:
                old_overrides.rename(user_ini)
                logger.info(f"Migrated {old_overrides} → {user_ini}")
            except OSError as e:
                logger.warning(f"Failed to migrate overrides.ini → user.ini: {e}")
                return old_overrides

        return user_ini

    @staticmethod
    def get_backups_dir() -> Path:
        r"""Get the active channel's backups directory (``…\{channel}\backups\``).

        Backups are per-channel because each channel's global.ini has its
        own stock baseline — restoring a LIVE backup into PTU would mix
        stock strings from different game builds.
        """
        backups_dir = AppSettings.get_channel_data_dir() / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        return backups_dir

    @staticmethod
    def get_logs_dir() -> Path:
        r"""Get the logs directory (``{user_data_dir}\logs\``).

        Crash dumps and manual log exports both land here. NOT per-channel:
        a crash can fire before the channel context is established (e.g.
        during startup migrators), so the path is rooted at the
        user-data dir directly. Created lazily so a fresh install doesn't
        carry an empty ``logs/`` until the first crash or export.
        """
        logs_dir = AppSettings.get_user_data_dir() / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        return logs_dir

    @staticmethod
    def migrate_dataforge_cache_to_local() -> None:
        r"""One-shot move of the DataForge XML cache from Documents → AppData\Local.

        Pre-1.0 the DataForge cache lived inside get_cache_dir() (Documents\…),
        putting ~1.4 GB of extracted XMLs into the OneDrive sync tree. Moving it
        to AppData\Local eliminates per-file OneDrive / Defender / Indexer hooks
        during extraction and keeps large build-artefact files out of cloud sync.

        Idempotent: no-ops when the old path is already absent. If the new
        location already has a valid stamp the old directory is cleaned up and
        the migration is considered complete.
        """
        import shutil

        old_dir = AppSettings.get_cache_dir() / "dataforge"
        local_appdata = Path(
            os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        )
        new_dir = (
            local_appdata / "Smart Citizen"
            / AppSettings.get_active_channel()
            / "cache" / "dataforge"
        )

        if not old_dir.exists():
            return

        from src.utils.pak_extractor import P4K_MTIME_STAMP
        if (new_dir / P4K_MTIME_STAMP).exists():
            logger.info(
                f"DataForge cache already at new location; removing old copy at {old_dir}"
            )
            try:
                shutil.rmtree(old_dir, ignore_errors=True)
            except Exception as e:
                logger.warning(f"Could not remove old DataForge cache at {old_dir}: {e}")
            return

        logger.info(f"Migrating DataForge cache: {old_dir} → {new_dir}")
        try:
            new_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old_dir), str(new_dir))
            logger.info("DataForge cache migration complete")
        except Exception as e:
            logger.warning(
                f"DataForge cache migration failed ({e}); "
                "cache will be re-extracted on next use"
            )

    @staticmethod
    def migrate_data_to_documents() -> None:
        """Copy user data files from old AppData location to new Documents location.

        Safe to call on every startup — skips files that already exist at the
        destination. Handles the upgrade path for users on previous versions.
        """
        import shutil

        old_base = Path(
            os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
        ) / "Osiris DevWorks" / "SC Localization Editor"
        old_cache = old_base / "cache"

        new_base  = AppSettings.get_user_data_dir()
        new_cache = AppSettings.get_cache_dir()

        # Migrate overrides.ini
        old_overrides = old_base / "overrides.ini"
        new_overrides = new_base / "overrides.ini"
        if old_overrides.exists() and not new_overrides.exists():
            try:
                shutil.copy2(old_overrides, new_overrides)
                logger.info(f"Migrated overrides.ini to Documents")
            except Exception as e:
                logger.warning(f"Could not migrate overrides.ini: {e}")

        # Migrate cache files
        if old_cache.exists():
            for ini_file in old_cache.glob("*.ini"):
                dest = new_cache / ini_file.name
                if not dest.exists():
                    try:
                        shutil.copy2(ini_file, dest)
                        logger.info(f"Migrated {ini_file.name} to Documents cache")
                    except Exception as e:
                        logger.warning(f"Could not migrate {ini_file.name}: {e}")

        # Migrate backup files from old AppData location
        old_backups = old_base / "backups"
        if old_backups.exists():
            new_backups = AppSettings.get_backups_dir()
            for bak_file in old_backups.glob("global.ini.bak_*"):
                dest = new_backups / bak_file.name
                if not dest.exists():
                    try:
                        shutil.copy2(bak_file, dest)
                        logger.info(f"Migrated {bak_file.name} to Documents backups")
                    except Exception as e:
                        logger.warning(f"Could not migrate {bak_file.name}: {e}")

    @staticmethod
    def get_unp4k_exe_path() -> Path:
        """Resolve bundled unp4k.exe — works both frozen (PyInstaller) and in dev."""
        import sys
        if getattr(sys, 'frozen', False):
            base = Path(sys._MEIPASS)
        else:
            # src/utils/settings.py → src/utils → src → project root
            base = Path(__file__).parent.parent.parent
        return base / 'assets' / 'unp4k' / 'unp4k.exe'

    @staticmethod
    def get_unforge_exe_path() -> Path:
        """Resolve bundled unforge.exe — works both frozen (PyInstaller) and in dev."""
        import sys
        if getattr(sys, 'frozen', False):
            base = Path(sys._MEIPASS)
        else:
            base = Path(__file__).parent.parent.parent
        return base / 'assets' / 'unp4k' / 'unforge.exe'

    @staticmethod
    def get_dataforge_cache_base() -> Path:
        """Return the *base* directory for DataForge caches (without the
        active-channel suffix). The full per-channel cache path lives at
        ``{base}/{channel}/cache/dataforge/`` — see
        :meth:`get_dataforge_cache_dir` for the resolved leaf.

        Resolution order (registry mode):
          1. ``CACHE_DIR`` registry override — set by users splitting the
             DataForge cache off the user-data dir (e.g. fast SSD for the
             cache, OneDrive Documents for user.ini).
          2. ``%LOCALAPPDATA%\\Smart Citizen\\`` — the pre-1.4.1 default,
             preserved so unchanged installs see no path movement.

        Portable mode:
          1. ``CACHE_DIR`` override if set (portable users may want the
             1.4 GB cache off a slow USB stick).
          2. ``<exe-dir>/data/cache/`` — sits next to all other portable
             data so a USB-stick install is one fully self-contained folder.
        """
        from src.utils import build_mode
        override = AppSettings._get_cache_dir_override()
        if override:
            return Path(os.path.expandvars(override)).expanduser().resolve()
        if build_mode.IS_PORTABLE:
            return AppSettings._portable_data_dir() / "cache"
        return Path(
            os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        ) / "Smart Citizen"

    @staticmethod
    def get_dataforge_cache_dir() -> Path:
        """Return the directory where DataForge entity XMLs are cached after unforge.

        Defaults to ``%LOCALAPPDATA%\\Smart Citizen\\{channel}\\cache\\dataforge\\``
        — never OneDrive-synced, eliminating per-file sync hooks during
        extraction of the ~1.4 GB / ~28k-file XML tree. A user can override
        the base via the Config tab (Smart Citizen Data → DataForge Cache
        Folder); see :meth:`get_dataforge_cache_base` for the resolution
        order. Channel nesting is preserved across all variants so each
        SC channel stays isolated.
        """
        cache_dir = (
            AppSettings.get_dataforge_cache_base()
            / AppSettings.get_active_channel()
            / "cache" / "dataforge"
        )
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    @staticmethod
    def get_dataforge_build_key() -> str:
        r"""Return a fingerprint for the current DataForge extraction.

        Reads the ``.p4k_mtime`` stamp pak_extractor writes, falling back to
        the records-dir mtime. Mirrors ``_dataforge_cache_key`` in
        ``scripts/generate_enhancements_ini.py`` so a per-language enhancement
        stamp can be compared against the build its files were generated from
        (see :meth:`get_enhancements_stamp`). Returns 'unknown' when no
        DataForge cache exists yet.
        """
        from src.utils.pak_extractor import P4K_MTIME_STAMP
        forge_dir = AppSettings.get_dataforge_cache_dir()
        stamp = forge_dir / P4K_MTIME_STAMP
        try:
            text = stamp.read_text(encoding="utf-8").strip()
            if text:
                return text
        except (OSError, ValueError):
            # ValueError: a corrupt stamp raises UnicodeDecodeError (#251
            # bug class) — fall through to the records-dir heuristic.
            pass
        records = forge_dir / "raw" / "libs" / "foundry" / "records"
        try:
            if records.exists():
                return f"mtime:{int(records.stat().st_mtime)}"
        except OSError:
            pass
        return "unknown"

    @staticmethod
    def get_p4k_path() -> Path:
        """Return path to Data.p4k for the active channel.

        Resolves via :meth:`get_channel_install_path` which already nests the
        channel under the SC install root. Falls back to the legacy
        single-channel logic (where ``get_game_install_path()`` may have
        returned either the root or the channel dir) for users whose
        migration hasn't run yet — harmless on migrated installs since the
        active-channel branch wins above.
        """
        channel_path = AppSettings.get_channel_install_path()
        if channel_path:
            return Path(channel_path) / "Data.p4k"

        game_path = Path(AppSettings.get_game_install_path())
        if game_path.name.upper() in {c.upper() for c in AppSettings.AVAILABLE_CHANNELS}:
            return game_path / "Data.p4k"
        return game_path / AppSettings.get_active_channel() / "Data.p4k"

    @staticmethod
    def get_global_ini_path() -> Path:
        r"""Return the active channel's applied ``global.ini`` location.

        Equivalent to ``{sc_install_root}\{active_channel}\data\Localization\{language}\global.ini``
        — the file "Apply to Game" writes and "Clear Localization" deletes.
        The language directory reflects :meth:`get_selected_language`.
        Callers should use this instead of reconstructing the path from
        :meth:`get_game_install_path`, which the pre-0.9.3 code did with
        scattered ``if name == "LIVE"`` branches that don't cover the new
        channels.
        """
        sc_lang = AppSettings.get_sc_language_id()
        channel_path = AppSettings.get_channel_install_path()
        if channel_path:
            return Path(channel_path) / "data" / "Localization" / sc_lang / "global.ini"

        game_path = Path(AppSettings.get_game_install_path())
        if game_path.name.upper() in {c.upper() for c in AppSettings.AVAILABLE_CHANNELS}:
            return game_path / "data" / "Localization" / sc_lang / "global.ini"
        return (
            game_path / AppSettings.get_active_channel()
            / "data" / "Localization" / sc_lang / "global.ini"
        )

    @staticmethod
    def ensure_user_ini_file() -> None:
        """Ensure user.ini exists, creating empty file if needed."""
        user_ini_path = AppSettings.get_user_ini_path()

        user_ini_path.parent.mkdir(parents=True, exist_ok=True)

        if not user_ini_path.exists():
            try:
                user_ini_path.touch()
                logger.info(f"Created empty user.ini: {user_ini_path}")
            except Exception as e:
                logger.error(f"Failed to create user.ini: {e}")

    # ── Export / Import Settings (settings backup) ───────────────────────
    # Backend-agnostic snapshot + restore of every stored setting, powering
    # the Config tab's Export Settings / Import Settings buttons. The zip
    # layout and validation live in src/utils/settings_profile.py; these
    # methods own the backend enumeration and the machine-key filter.

    @staticmethod
    def is_profile_excluded_key(key: str, value=None) -> bool:
        """True when *key* must not travel in a settings backup.

        Three rules:
          1. Exact members of :data:`PROFILE_EXCLUDE_KEYS` (machine-local
             paths, window placement, legacy path keys).
          2. Keys starting with ``_`` — one-shot migration markers; a fresh
             target profile should run its own (idempotent) migrators.
          3. ``data_sources/*/path`` values that are NOT URLs — post-1.0 the
             ``global`` source path points at the local cached base.ini,
             which is meaningless on another machine (the app re-derives it
             on load). URL-mapped custom sources survive: they're part of
             the user's setup and work anywhere.
        """
        if key in AppSettings.PROFILE_EXCLUDE_KEYS:
            return True
        if key.startswith("_"):
            return True
        if (
            key.startswith(f"{AppSettings.DATA_SOURCES_PREFIX}/")
            and key.endswith("/path")
        ):
            text = str(value) if value is not None else ""
            if not text.lower().startswith(("http://", "https://")):
                return True
        return False

    @staticmethod
    def profile_default_values() -> dict:
        """Every preference's default value, for materialising into a backup.

        A setting is only written to the backend when the user changes it, so
        anything still at its default has no key to enumerate. That made a
        backup silently partial (#383): restoring it could not put a
        preference *back* to its default, because the backup never said what
        the default was. Importing one therefore left every
        since-changed-from-default setting untouched — the Mission Labels
        case the issue was reported against, but equally theme, UI mode, the
        favourites prefix, and every checkbox.

        Built as a function rather than a class constant for two reasons:
        some keys (``merge_hierarchy``) are defined further down the class
        body, and the theme default lives in ``src.gui.theme``, which must
        stay a deferred import here. Not cached — it is built once per
        export, and a cache would go stale under tests that patch defaults.

        ``PROFILE_DEFAULT_EXCLUDE_KEYS`` documents what is deliberately left
        out and why. ``tests/test_settings_profile_defaults.py`` locks this
        map against the getters so a newly added setting can't quietly go
        missing from backups the way these did.
        """
        from src.gui.theme import DEFAULT_THEME
        from src.utils.tag_builder import DEFAULT_TAG_CONFIGS

        defaults: dict = {
            AppSettings.THEME: DEFAULT_THEME,
            AppSettings.UI_MODE: AppSettings.UI_MODE_SIMPLE,
            AppSettings.ACTIVE_CHANNEL: AppSettings.DEFAULT_CHANNEL,
            AppSettings.SELECTED_LANGUAGE: AppSettings.DEFAULT_LANGUAGE,
            AppSettings.MERGE_HIERARCHY: list(AppSettings.AVAILABLE_SOURCES),
            AppSettings.FAVORITE_PREFIX: AppSettings.DEFAULT_FAVORITE_PREFIX,
            AppSettings.REP_XP_LABEL: AppSettings.DEFAULT_REP_XP_LABEL,
            AppSettings.MISSION_HEADER_EM_TAG: AppSettings.DEFAULT_MISSION_HEADER_EM_TAG,
            AppSettings.ENHANCEMENTS_ENABLED: True,
            AppSettings.INCLUDE_NEW_LINES: False,
            AppSettings.STATS_PREPEND: False,
            AppSettings.AUTO_WRITE_ENABLED: False,
            AppSettings.STANDARDIZE_EARNABLE_SHIP_NAMES: False,
            AppSettings.RS_ORE_NAME_ANNOTATIONS: True,
            AppSettings.ONEDRIVE_WARNING_DISMISSED: False,
            AppSettings.TUTORIAL_DISABLED: False,
            AppSettings.BLUEPRINT_SHOW_TAGS: False,
            AppSettings.BLUEPRINT_SCAN_OTHER_CHANNELS: True,
            AppSettings.TAG_ANNOTATE_MISSION_DESCS: True,
        }
        # Composed from the same maps the getters read, so these can't drift.
        defaults.update({
            key: AppSettings.MISSION_HEADER_DEFAULTS[name]
            for name, key in AppSettings._MISSION_HEADER_SETTING.items()
        })
        defaults.update({
            key: True for key in AppSettings._MISSION_FIELD_SETTING.values()
        })
        defaults.update({
            key: AppSettings._MISSION_TITLE_TAG_DEFAULTS.get(name, True)
            for name, key in AppSettings._MISSION_TITLE_TAG_SETTING.items()
        })
        defaults.update({
            f"enhancements/categories/{cat}/enabled": True
            for cat in AppSettings.ENHANCEMENT_LABELS
        })
        # "" is the stored form of "use DEFAULT_TAG_CONFIGS", so materialising
        # it is what lets an import reset a customised Tag Builder back to
        # stock rather than leaving the customisation in place.
        defaults.update({
            f"tag_builder/{cat}/config": "" for cat in DEFAULT_TAG_CONFIGS
        })
        return defaults

    @staticmethod
    def is_profile_default_materialised(key: str, value=None) -> bool:
        """True when *key*'s default belongs in a backup (see #383).

        *value* is threaded through to is_profile_excluded_key's own
        data_sources/*/path URL check, the same way export_all_values does
        for a real stored value — without it, that check sees no value and
        can't tell a URL-mapped default from a local one, so it falls back
        to treating any such key as non-URL (excluded). No default in
        profile_default_values() has that shape today, so this is currently
        a no-op in practice; passing it costs nothing and keeps the two
        exclusion checks answering the same question the same way if one
        ever does.
        """
        if key in AppSettings.PROFILE_DEFAULT_EXCLUDE_KEYS:
            return False
        if key.startswith(AppSettings.PROFILE_DEFAULT_EXCLUDE_PREFIXES):
            return False
        return not AppSettings.is_profile_excluded_key(key, value)

    @staticmethod
    def export_all_values() -> dict:
        """Snapshot every setting for a backup, defaults included.

        Works against either backend: ``QSettings.allKeys()`` (registry
        build) or ``JsonSettings.keys()`` (portable build / tests). Values
        that JSON can't serialise (e.g. a stray QByteArray) are skipped with
        a warning rather than poisoning the whole export — the known binary
        keys (window geometry/state) are already excluded by the filter.

        Defaults are laid down first and stored values written over them
        (#383), so the result describes the user's whole configuration
        rather than only the parts that happen to differ from stock. That is
        what makes an import able to restore a setting *to* its default.
        """
        backend = AppSettings.settings()
        if hasattr(backend, "allKeys"):
            keys = list(backend.allKeys())
        else:
            keys = backend.keys()

        out: dict = {
            key: value
            for key, value in AppSettings.profile_default_values().items()
            if AppSettings.is_profile_default_materialised(key, value)
        }
        for key in keys:
            value = backend.value(key)
            if AppSettings.is_profile_excluded_key(key, value):
                continue
            try:
                json.dumps(value)
            except (TypeError, ValueError):
                logger.warning(
                    "Export Settings: skipping non-serialisable value for key "
                    "%r (%s)", key, type(value).__name__,
                )
                continue
            out[key] = value
        return out

    @staticmethod
    def import_values(values: dict) -> int:
        """Write backup values into the live backend. Returns keys applied.

        Runs the same machine-specific filter as export (a hand-edited or
        pre-filter backup can't smuggle in a stale install path), writes
        everything else verbatim, and syncs once at the end. Existing keys
        not present in *values* are left untouched — an import layers the
        backup over the current profile rather than wiping it, so local
        state like the SC install path survives a same-machine restore.
        """
        backend = AppSettings.settings()
        applied = 0
        for key, value in values.items():
            if not isinstance(key, str) or not key:
                continue
            if AppSettings.is_profile_excluded_key(key, value):
                continue
            backend.setValue(key, value)
            applied += 1
        backend.sync()
        logger.info("Import Settings: applied %d settings keys", applied)
        return applied

    @staticmethod
    def reconcile_imported_install_path() -> str:
        """Validate a just-imported Star Citizen path against this machine.

        The backup carries ``sc_install_root`` so the common restore (same
        PC, fresh portable unzip) doesn't make the user re-pick their game
        folder. But a backup from *another* machine can name a path that
        doesn't exist here, so the imported value is only trusted when
        :func:`_is_valid_sc_root` still recognises it as a real install.

        When it doesn't, both path keys are cleared so
        :meth:`get_sc_install_root` runs its normal detection chain instead
        of leaving the user pinned to a dead path.

        Returns one of :data:`INSTALL_PATH_RESTORED`,
        :data:`INSTALL_PATH_REDETECTED`, or :data:`INSTALL_PATH_NONE`.
        """
        imported = AppSettings.settings().value(AppSettings.SC_INSTALL_ROOT, "")

        if imported and _is_valid_sc_root(imported):
            # Re-persist through the setter so game_install_path is derived
            # from the active channel and can't disagree with the root.
            AppSettings.set_sc_install_root(imported)
            logger.info(f"Import Settings: restored SC install path {imported!r}")
            return AppSettings.INSTALL_PATH_RESTORED

        if imported:
            logger.info(
                f"Import Settings: backup's SC install path {imported!r} is not "
                f"valid on this machine — falling back to auto-detection"
            )
        settings = AppSettings.settings()
        settings.remove(AppSettings.SC_INSTALL_ROOT)
        settings.remove(AppSettings.GAME_INSTALL_PATH)

        detected = AppSettings.get_sc_install_root()
        if detected:
            logger.info(f"Import Settings: auto-detected SC install {detected!r}")
            return AppSettings.INSTALL_PATH_REDETECTED
        return AppSettings.INSTALL_PATH_NONE

    @staticmethod
    def get_post_import_apply_pending() -> bool:
        """Whether imported settings are still waiting for their first
        regenerate + apply (checked once per launch, then cleared)."""
        return AppSettings.settings().value(
            AppSettings.POST_IMPORT_APPLY_PENDING, False, type=bool
        )

    @staticmethod
    def set_post_import_apply_pending(pending: bool) -> None:
        """Set or clear the post-import "enhancements need applying" flag."""
        if pending:
            AppSettings.settings().setValue(
                AppSettings.POST_IMPORT_APPLY_PENDING, True
            )
        else:
            AppSettings.settings().remove(AppSettings.POST_IMPORT_APPLY_PENDING)

    @staticmethod
    def get_channel_user_ini_path(channel: str) -> Path:
        r"""Return ``{user_data_dir}\{channel}\user.ini`` for any channel.

        Unlike :meth:`get_user_ini_path` this doesn't run the legacy
        ``overrides.ini`` migration and doesn't depend on the *active*
        channel — Export/Import Settings walks every channel, not just the
        current one.
        """
        return AppSettings.get_user_data_dir() / channel / "user.ini"

    @staticmethod
    def export_channel_overrides() -> dict:
        """Collect ``{channel: user.ini text}`` for every channel with one.

        Reads ``user.ini`` (or the legacy ``overrides.ini`` when only that
        exists) from each known channel dir. Empty files are skipped — no
        point carrying zero-byte overrides in a backup.
        """
        overrides: dict = {}
        for channel in AppSettings.AVAILABLE_CHANNELS:
            path = AppSettings.get_channel_user_ini_path(channel)
            if not path.exists():
                legacy = path.parent / "overrides.ini"
                if legacy.exists():
                    path = legacy
                else:
                    continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                logger.warning(
                    "Export Settings: could not read %s: %s", path, e
                )
                continue
            if text.strip():
                overrides[channel] = text
        return overrides
