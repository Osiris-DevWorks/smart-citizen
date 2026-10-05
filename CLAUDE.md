# CLAUDE.md

This file guides Claude Code (claude.ai/code) when working in this repo.

> **Before editing files under `src/<dir>/`, `scripts/`, or `tests/`, read that directory's `CLAUDE.md` first.** See *Per-directory guides* below for the list.

## Communication style

- **Plain words, short sentences.** Cut adjectives, hedges, and throat-clearing. If a sentence isn't earning its weight, drop it.
- **One concept per message.** When the work involves several distinct concepts, present the first, stop, and ask the user before moving on. Do not stack ideas, decisions, or trade-offs in a wall of text.
- **Prompt at decision points.** When the next step needs the user's preference, judgment, or clarification, ask before proceeding. A one-line confirmation is cheaper than redoing work.

## Project Overview

Smart Citizen (formerly SC Localization Editor) is a Windows-only PyQt6 GUI for customizing Star Citizen localization strings. Tagline: *Smarter Strings for Star Citizen*. Users edit strings in a table backed by the `global` source (locally cached `base.ini` from Data.p4k) merged with per-channel `user.ini` overrides, then apply the result to their game with backup management.

**Branding**: User-facing strings, registry path (`Osiris DevWorks\Smart Citizen`), and the default data root (`Documents\Smart Citizen\`) use the new name. `AppSettings` keeps one-shot migrators for the legacy `Osiris DevWorks\SC Localization Editor` registry tree and `Documents\SC Localization Editor\` folder (rebrand was 0.9.0); keep them while pre-0.9 users may upgrade.

**Version**: `VERSION.TXT` is the sole source of truth. Now 2.3.1.

Build modes are covered in `src/utils/CLAUDE.md` under *Portable vs registry build mode*.

## Per-directory guides

Directory-specific docs (read the one for the layer you're touching):

- `src/gui/CLAUDE.md` — GUI layer (PyQt6 widgets, workers, table model).
- `src/utils/CLAUDE.md` — settings, build-mode flag, P4K extraction, enhancement helpers.
- `src/parser/CLAUDE.md` — INI parsing, status classification.
- `src/merger/CLAUDE.md` — source merge engine.
- `src/models/CLAUDE.md` — domain data models.
- `scripts/CLAUDE.md` — standalone CLI scripts and the build pipeline.
- `tests/CLAUDE.md` — test suite layout, pytest config.

Entry point: `src/main.py`.

## Quick Commands

```bash
# Setup
pip install -r requirements.txt           # production deps
pip install -r requirements-dev.txt       # plus pytest, flake8, black, mypy

# Run
python src/main.py

# Testing
pytest tests/                                                    # all
pytest tests/test_core.py                                        # one file
pytest tests/test_core.py::TestIniParsing                        # one class
pytest tests/test_core.py::TestIniParsing::test_parse_basic_ini  # one test
pytest tests/ -v                                                 # verbose
pytest tests/ --cov=src --cov-report=html                        # HTML coverage
pytest tests/ -n auto                                            # parallel (pytest-xdist)

# Code Quality
black src/ tests/ scripts/        # format
flake8 src/ tests/ scripts/       # lint
isort src/ tests/ scripts/        # sort imports
mypy src/                         # types

# Building
cd scripts/build && python build_exe.py             # registry build
cd scripts/build && python build_exe.py --portable  # portable build
cd scripts/build && build_all.bat                   # exe + installer (needs Inno Setup)

# Data Generation
python scripts/generate_enhancements_ini.py [base_ini_path [dataforge_cache_dir]]
python scripts/extract_components.py [--stock path] [--base path] [--output path] [--dry-run]
```

## Cross-cutting design decisions

Per-layer decisions live in the per-directory guides above. The ones below span layers.

### File naming: base.ini vs global.ini
The cached global source is saved as `base.ini` (not `global.ini`) to avoid confusion with the game's `global.ini` at `LIVE/data/Localization/english/global.ini`.

### Threading model
I/O-bound work (file loads, network, P4K extraction) runs in `QThread` workers in `src/gui/workers.py` (lone exception: `AppUpdateCheckWorker` in `src/utils/app_updater.py`, next to its companion logic). Workers emit `finished()`; cleanup needs `quit()` + `wait()`. Never block the main thread on file or network I/O. Wrap bulk table updates in `setUpdatesEnabled(False)`. `AppSettings` is thread-safe — use from main or worker. Worker logger names: `src.gui.workers` post-extraction (`src.gui.main_window` pre-extraction) — matters when grepping logs.

### Startup initialization
On first run, the app sets up user data dirs, validates the SC install path, and may show a startup dialog to guide config. Later runs check source freshness and apply any pending DataForge cache updates.

### DataForge extraction is a four-step pipeline
The "Extract DataForge from P4K" button triggers, in order:
1. Unpack Data.p4k → entity XMLs via `src/utils/pak_extractor.py`. The bundled unp4k is a parallelised fork (`odw-fast-unp4k`) using `ThreadPoolExecutor` for extraction and `lxml` for unforge.
2. Apply declarative patches from `patches/` via `src/utils/dataforge_patcher.py` to fix upstream CIG data bugs. Idempotent; runs on the extracted cache even when step 1 is skipped as fresh.
3. Run `scripts/generate_enhancements_ini.py` over the XMLs (only for categories the diff cache flags as dirty — see `src/utils/CLAUDE.md` → *DataForge diff cache*).
4. Reload all strings to refresh the table.

The progress dialog stays continuous across steps 1–3 so users see one bar from start to finish.

### Merge hierarchy
Sources merge in user-defined order. Later sources overwrite earlier ones; user overrides apply last and survive source updates. As of 1.0 the seeded default is just `[global, user]` — the URL sources (contracts/components/ships/commodities) and `gear` retired in 0.7.0 when extraction moved to local Data.p4k, and `migrate_remove_retired_url_sources()` removes them from upgrader registries. `load_sources_from_settings()` also injects a synthetic `enhancements` source at runtime when any enhancement category is enabled on the Enhancements tab — it is *not* a registry entry; don't add it to the hierarchy by hand.

### Language system (2.0, #30)
Two independent layers share one selected language (`AppSettings.get_selected_language()`, set from the Config tab):

1. **UI chrome** is translated via `src/utils/i18n.py`: `tr("dot.path.key", **kwargs)` reads `languages/{lang}/ui.json`, overlaid on English so missing keys fall back (then to the bare key). A runtime switch re-merges strings but already-built widgets keep the old text; full chrome refresh needs a restart. Languages whose `ui.json` is a stub (only `_comment`) are hidden from the selector by `get_available_languages()`.
2. **Game strings**: English `base.ini` comes from local P4K extraction; every other language downloads a community `global.ini` per `languages/sources.json` (per-user URL override via the Config tab's *Map Language File* dialog). Caches are per-language: English at `{channel}\cache\base.ini`, others at `{channel}\cache\lang\{language}\base.ini` (`get_base_ini_path(language)`).

Enhancements are language-aware: generated INIs live next to that language's `base.ini` (`get_enhancements_dir()`), and a `.dataforge_stamp` marker per language triggers regeneration on switch when stale. Generator annotation paths always parse the *English* base.ini, so stat blocks stay English by design; mixed values (e.g. `Role: Cannoniere`) are intentional. The apply side is language-aware too: `get_global_ini_path()` writes `Localization\{sc_id}\global.ini` and `ensure_user_cfg_language()` sets `g_language` to match, both via `SC_LANGUAGE_IDS` (app folder name `portuguese_br` → game id `portuguese_(brazil)`).

`languages/` must be bundled in **both** build lists (`SmartCitizen.spec` and `scripts/build/build_exe.py`), or the frozen app shows raw `tr()` keys.

### Favorites use value prefix
Favorites prepend a configurable prefix (default `*`) to `custom_value`. Stored via `AppSettings.FAVORITE_PREFIX`.

### Code deduplication (DRY)
Prefer one canonical implementation over copy-paste. Calibration:

- **Two occurrences**: usually fine — leave it.
- **Three or more**: extract. The third repeat is the signal.
- **Magic literals used in 2+ places**: extract a named constant immediately. Common offenders: settings keys, source names (`"global"`, `"user"`, `"enhancements"`), channel names (`"LIVE"`, `"PTU"`, `"EPTU"`, `"HOTFIX"`, `"TECH-PREVIEW"`), column indices, file extensions, path segments.
- **Near-duplicates differing in one literal or branch**: parameterize. Two functions that diverge on a single string or boolean are one function with an argument.

Anchor examples already in-tree: `COL_*` constants in `src/gui/string_table_model.py`, `_entry_index_for_row()` on `MainWindow`, `AppSettings` helpers (one backend abstraction, not mode-conditional call sites), `ProgressSink` (one shared progress channel for all parallel workers).

**Tolerated exception**: `CATEGORY_SUBTREES` (`src/utils/dataforge_diff.py`) ↔ `DATAFORGE_KEEP_SUBPATHS` (`src/utils/pak_extractor.py`) — two lists kept in sync deliberately; they serve different consumers and the contract is locked by tests.

**Don't over-abstract.** Three similar lines beats a premature abstraction. Single-use helpers, one-off config classes, and clever metaprogramming for code that runs in one place are worse than the inline version.

## PyInstaller specs

`SmartCitizen.spec` at the repo root is the live spec. The `SCLocalizationEditor-v*.spec` and `SmartCitizen-v0.9.*.spec` files are archival — do not edit for new builds.

## File Locations

| What | Where |
|------|-------|
| Settings (registry build) | Windows Registry: `HKEY_CURRENT_USER\Software\Osiris DevWorks\Smart Citizen` |
| Settings (portable build) | `<user_data_dir>/config.json` via `JsonSettings` |
| User data root (registry build) | Configurable via `user_data_dir` (alias `UserDataDir` also read); default `Documents\Smart Citizen\` |
| User data root (portable build) | `<exe-dir>/data/` when frozen; `<repo-root>/portable_data/` unfrozen |
| **Per-channel data** | `{user_data_root}\{LIVE\|PTU\|EPTU\|HOTFIX\|TECH-PREVIEW}\` — 0.9.3+ nests user.ini / cache / backups / dataforge under the active channel so each SC channel is isolated. Migrator: `AppSettings.migrate_game_path_to_channel_layout()`. |
| User overrides | `{user_data_root}\{active_channel}\user.ini` (legacy `overrides.ini` auto-migrated) |
| Cached sources | `{user_data_root}\{active_channel}\cache\` — only `base.ini` post-1.0 (four legacy URL sources retired in 0.7.0); enhancement INIs live here too. Non-English languages cache their downloaded base.ini at `cache\lang\{language}\base.ini` (2.0); resolved via `AppSettings.get_base_ini_path(language)` |
| DataForge cache | `%LOCALAPPDATA%\Smart Citizen\{active_channel}\cache\dataforge\` by default (entity XMLs from Data.p4k); overrideable independently of the user-data root via the `CACHE_DIR` registry key (1.4.1+ — `AppSettings.get_cache_dir_override()` / `set_cache_dir()`, wired to the Config tab's *DataForge Cache Folder*; the cache override does *not* fall back to the user-data override). Moved out of `Documents\` in 1.x — `migrate_dataforge_cache_to_local()` relocates the legacy `…\cache\dataforge\` tree on first launch. Resolved via `AppSettings.get_dataforge_cache_dir()`. |
| Crash dumps + log exports | `{user_data_root}\logs\` (NOT per-channel — a crash can fire before the channel context is established, e.g. during startup migrators). Resolved via `AppSettings.get_logs_dir()`; created lazily on first crash or export. |
| Enhancement INIs | next to the active language's base.ini via `AppSettings.get_enhancements_dir(language)`: `{user_data_root}\{active_channel}\cache\` for English, `cache\lang\{language}\` otherwise (`ships_desc_enhancements.ini`, `components_desc_enhancements.ini`, `ship_weapons_desc_enhancements.ini`, `fps_weapons_desc_enhancements.ini`, `mission_rewards_enhancements.ini`, `commodity_crafting_enhancements.ini`, `medical_consumables_enhancements.ini`; plus a `.dataforge_stamp` freshness marker) |
| Backups | `{user_data_root}\{active_channel}\backups\` (max 5, oldest auto-deleted) |
| Game file | `{sc_install_root}\{active_channel}\data\Localization\{sc_language_id}\global.ini` — `AppSettings.get_global_ini_path()` (language dir follows the selected language via `SC_LANGUAGE_IDS`) |
| UI translations + language source map | `languages/{language}/ui.json` (UI strings) and `languages/sources.json` (per-language base.ini download URLs). Bundled via both `SmartCitizen.spec` and `scripts/build/build_exe.py` |
| P4K tools | `assets/unp4k/` (`unp4k.exe`, `unforge.exe`) |
| DataForge patches | `patches/` (JSON files mirroring DataForge layout; applied post-extraction) |
| Help/About | `docs/HELP.md`, `docs/ABOUT.md` — bundled under `docs/` via `SmartCitizen.spec` (and `scripts/build/build_exe.py` for the CLI path); rendered in-app via `get_resource_path("docs/HELP.md")` so dev and frozen resolve symmetrically |
| Legal tab | `docs/LEGAL.md` — CIG community-content compliance, license summaries, privacy/data-handling disclosure, AI-use statement. Bundled via `SmartCitizen.spec` (source `docs/LEGAL.md`, dest `docs`); same markdown→HTML pipeline as About |
| Linux/Wine guide | `docs/LINUX.md` — user-facing Wine-prefix walkthrough; not loaded by the app |
| Release notes | `docs/{X.Y.Z}-RELEASE-NOTES.md`. Release workflow at `.github/workflows/release.yml` looks here first; falls back to repo root for pre-1.4.1 re-runs |

## Common Modification Points

| Task | File | Key Function |
|------|------|-------------|
| Add/change table columns | `src/gui/main_window.py`, `src/gui/string_table_model.py` | `setup_string_table()`, `NUM_COLUMNS` + `COL_*` constants (also referenced by `entry_filter.py`'s getter tuple) |
| Add/change filters (UI wiring) | `src/gui/main_window.py` | `apply_filters()`, `on_filter_changed()` |
| Change row-filter logic | `src/utils/entry_filter.py` | `filter_entry_indices()` (delegated to from `MainWindow._filtered_entry_indices`) |
| Change per-column filter widgets | `src/gui/filter_header.py` | `FilterHeaderView` |
| Change category extraction | `src/models/string_model.py` | `StringEntry.extract_category()` |
| Modify INI parsing | `src/parser/ini_parser.py` | `parse_ini_file()` |
| Change merge logic | `src/merger/ini_merger.py` | `merge_sources_by_hierarchy()` |
| Change overrides persistence | `src/utils/user_ini_manager.py` (save) / `src/parser/ini_parser.py` (load) | `save_user_ini()`, `load_overrides()` |
| Change user INI import behavior | `src/gui/import_dialog.py`, `src/utils/user_ini_manager.py` | `ImportConflictDialog` |
| Change table model | `src/gui/string_table_model.py`, `src/gui/main_window.py` | `StringTableModel`, `COL_*` constants, `setup_string_table()` |
| Modify auto-update | `src/utils/updater.py` | `check_for_updates()`, `download_base_file()` |
| Change backup behavior | `src/gui/main_window.py` | `manage_backups()` |
| Modify P4K extraction | `src/utils/pak_extractor.py` | `extract_dataforge()` |
| Change enhancements generation | `scripts/generate_enhancements_ini.py` | (standalone script) |
| Add performance profiling | `src/utils/perf.py` | `@timed` decorator |
| Change user data paths | `src/utils/settings.py` | `AppSettings.get_user_data_dir()` |
| Change DataForge freshness | `src/utils/settings.py`, `src/gui/main_window.py` | `dataforge_cache_is_fresh()` |
| Change stats/favorites UI | `src/gui/enhancements_tab.py` | `setup_ui()` |
| Manage Config tab UI | `src/gui/config_tab.py` | `setup_ui()`, drag-drop hierarchy |
| Manage Enhancements tab UI | `src/gui/enhancements_tab.py` | `setup_ui()`, stats toggle, favorites config |
| Manage Blueprint Tracker tab UI | `src/gui/blueprint_tracker_tab.py` | `setup_ui()`, `set_blueprint_items()`, `_render_blueprint_lists()` |
| Change blueprint type/class/size/grade classification | `src/utils/blueprint_meta.py` | `build_blueprint_metadata()`, `blueprint_type_from_key()` |
| Change the "Scan Logs for Owned Blueprints" log parsing | `src/utils/blueprint_log_scanner.py` | `extract_blueprint_names()`, `find_log_files()` |
| Change in-app logging | `src/gui/log_tab.py` | `LogTab`, `_QtLogHandler` |
| Change user.cfg behavior | `src/utils/user_cfg.py` | `ensure_user_cfg_language()` |
| Fix an upstream DataForge data bug | `patches/<category>/.../<name>.patch.json`, `src/utils/dataforge_patcher.py` | `apply_patches()` |
| Change parallel progress reporting | `src/utils/progress_sink.py` | `ProgressSink.advance()` |
| Change post-apply validation | `src/utils/applied_file_validator.py` | `validate_applied_file()` (wrapped by `MainWindow._validate_applied_file`) |
| Change About / Help markdown rendering | `src/gui/markdown_renderer.py` | `markdown_to_html()` (wrapped by `MainWindow.markdown_to_html`, which supplies palette colours) |
| Add or modify a background worker | `src/gui/workers.py` | The relevant `*Worker` class (subclass of `QThread`) |
| Change resource-path resolution (bundle vs dev) | `src/utils/resource_path.py` | `get_resource_path()`, `resolve_patches_dir()` |
| Toggle portable vs registry build mode | `scripts/build/build_exe.py`, `src/utils/build_mode.py` | `--portable` flag, `IS_PORTABLE` |
| Change portable-mode settings backend | `src/utils/json_settings.py`, `src/utils/settings.py` | `JsonSettings`, `AppSettings._backend` |
| Skip clean enhancement categories on re-extract | `src/utils/dataforge_diff.py`, `src/utils/pak_extractor.py` | `update_manifest()`, `dirty_categories()`, `CATEGORY_SUBTREES` (mirrors `DATAFORGE_KEEP_SUBPATHS`) |
| Change Export Loc-Pack zip behavior | `src/utils/locpack_exporter.py` | `default_locpack_filename()`, `write_locpack_zip()` |
| Change apply-time launcher watermark | `src/gui/main_window.py` | `_stamp_frontend_version()`, `_FRONTEND_VERSION_KEY`, `_FRONTEND_VERSION_STAMP_RE` |
| Change Modified/Enhanced/Unmodified/New status logic | `src/parser/ini_parser.py` | `_determine_status_from_source()` |
| Adjust close-time user.ini autosave guard | `src/utils/user_ini_manager.py` | `should_autosave_user_ini()` |
| Change "Reset user.ini" tool behavior | `src/utils/user_ini_manager.py`, `src/gui/config_tab.py` | `reset_user_ini()` (+ Config-tab button wiring) |
| Change user.ini backup/restore behavior | `src/utils/user_ini_manager.py`, `src/gui/main_window.py` | `backup_user_ini()` / `list_user_ini_backups()` / `restore_user_ini_backup()` (rotating snapshots in `backups/`, #172); Config-tab **Restore user.ini** → `_handle_restore_user_ini()` |
| Move DataForge XML cache out of Documents | `src/utils/settings.py` | `migrate_dataforge_cache_to_local()`, `get_dataforge_cache_dir()` |
| Add a tag-builder element/style/category | `src/utils/tag_builder.py` | `CATEGORY_ELEMENT_KINDS`, `STYLES_BY_KIND`, `DEFAULT_TAG_CONFIGS`, `render_tag()` |
| Change Tag Builder UI / live preview | `src/gui/enhancements_tab.py`, `src/gui/tag_mapping_dialog.py` | `_PREVIEW_VALUES`, `TagMappingDialog` |
| Persist/load tag configs | `src/utils/settings.py` | `AppSettings.get_tag_config()`, `set_tag_config()`, `get_all_tag_configs()` |
| Add a new stats-enhancement generator (e.g. mining/salvage analogue) | `scripts/generate_enhancements_ini.py` | `enhancements_mining_laser`, `enhancements_salvage_tool` (reference pattern); register in `CATEGORY_SUBTREES` + `DATAFORGE_KEEP_SUBPATHS` |
| Add a new *static* enhancement category with no DataForge dependency | `scripts/generate_enhancements_ini.py` | `enhancements_medical_consumables` (reference pattern) — reads only `loc`/base.ini, no XML scan, so it's exempt from `CATEGORY_SUBTREES` / `DATAFORGE_KEEP_SUBPATHS`; still needs `ENHANCEMENTS_FILES` + `ENHANCEMENT_LABELS` + `ENHANCEMENT_CATEGORY_FILES` entries in `settings.py` |
| Change crash-dump behavior | `src/utils/crash_handler.py`, `src/main.py` | `install_crash_handler()`; install site is the early `main()` setup, before the QApplication is constructed |
| Change error-dialog cooldown / coalescing | `src/gui/main_window.py`, `src/gui/error_dialog.py` | `MainWindow._show_error_dialog()` (cooldown / spam protection lives on the slot, not the `ErrorDialogHandler`) |
| Move the DataForge cache off the default path | `src/utils/settings.py`, `src/gui/config_tab.py` | `AppSettings.get_cache_dir_override()` / `set_cache_dir()` (1.4.1+; independent of the user-data override) |
| Add or fix a translated UI string | `languages/{language}/ui.json`, `src/utils/i18n.py` | `tr()`, `set_language()` (dot-path keys; English is the fallback base) |
| Change the language-switch flow | `src/gui/config_tab.py`, `src/gui/main_window.py` | `language_changed` signal, `MainWindow._on_language_changed()` (retranslate chrome, repoint the `global` source, download base.ini when a URL is mapped, regen stale enhancements, reload) |
| Change per-language base.ini download / URL mapping | `src/gui/workers.py`, `src/utils/settings.py`, `languages/sources.json` | `LanguageBaseDownloadWorker`, `get_language_base_url()`, `LanguageSourceDialog` (Config tab's *Map Language File*) |
| Change per-language cache or enhancements layout | `src/utils/settings.py` | `get_base_ini_path(language)`, `get_enhancements_dir(language)`, `get_/set_enhancements_stamp()` |
| Toggle mission-detail fields per user | `src/gui/enhancements_tab.py`, `src/utils/settings.py` | `_MISSION_FIELD_SETTING` (per-field show/hide for mission bodies, #121); the `route` key adds the haul route to titles (#166) |
| Change hauling/delivery route-in-title | `scripts/generate_enhancements_ini.py` | `_derive_route_fragment()` / `_route_token_role()` / `_title_route_token()` / `_expand_nested_route_vars()` (#166, reworked in #200: |Address default, comma-listed endpoints, one-level `*Token` expansion, per-body intersection; applied in both the contractgen title loop and the pu-only second pass; placed before the [BP]/XP tags via the mission_titles TagConfig) |
| Change stock-title shortening (Mission Titles) | `src/utils/tag_builder.py`, `scripts/generate_enhancements_ini.py` | `SHORTEN_PHRASE_OPTIONS` (phrase→shorter-phrase) + `REMOVE_WORD_OPTIONS` (Cargo/Haul/Rank word removal, Rank merged to one checkbox covering both dash- and comma-led contexts) + `abbreviate_title()`; `RANK_SEPARATORS` (None/Dash/Pipe/Colon rendered after the Rank position regardless of removal; "none" default, "space" omitted as indistinguishable from "none" post-normalization); `SIZE_ABBREVIATIONS` + `_size_abbreviation_overrides()` (cargo-grade words to XS/S/M/L via loc-key overrides, each size independently opted in via `TagConfig.shortened_sizes`); word/phrase removal gated by `TagConfig.abbreviated_phrases` (empty by default), applied at both title-emission sites (#200 follow-up, generalized) |
| Change Simple/Advanced view mode | `src/gui/main_window.py`, `src/gui/simple_mode_widget.py`, `src/utils/settings.py`, `installer.iss` | `_apply_ui_mode()` (QStackedWidget swap), `_run_simple_apply()` (one-button extract→generate→apply chain via the `_simple_run_active` flag), `get_/set_ui_mode()`, installer `ModeChoicePage` writing `ui_mode` (#180) |
| Change data-folder move behavior | `src/utils/user_ini_manager.py`, `src/gui/config_tab.py` | `migrate_user_data_dir(old, new, move=...)` (merge-never-overwrite; `move=True` deletes migrated originals and prunes empty dirs) |
| Change the OneDrive data-root warning | `src/utils/onedrive.py`, `src/gui/main_window.py`, `src/gui/config_tab.py` | `is_onedrive_path()` / `suggest_local_data_dir()`; `_maybe_warn_onedrive_data_dir()` (startup, suppressible) + Config-tab folder-pick warning; `ConfigTab.change_data_dir_to()` for the one-click move (#172) |
| Change the toolbar More overflow menu | `src/gui/main_window.py` | `more_menu` block in toolbar setup (restore backup, clear loc/cache, import/export, open loc dir) |
| Change the tester Test Plan panel / content | `src/utils/test_plan.py`, `src/gui/test_plan_panel.py` | `TEST_SECTIONS` (per-release checklist), `TestPlanPanel`, `_ensure_test_plan_dock()` / `show_test_plan()` (#144) |
| Change the uninstaller's opt-in "Also delete all saved settings" wipe | `installer.iss` | `InitializeUninstall()` (the dialog; skipped on `/SILENT` and `/VERYSILENT` unless `/SHOWDELETEOPTION=1`), `DeleteAllUserSettings()` (also the default data and cache folders when overridden, the legacy `Documents\SC Localization Editor` folder, and the queued `pending_cache_cleanup` tree), `DeleteOwnedSubpaths()` (app-owned names only; the old root-level `cache` only when `LooksLikeScCache()` says it holds a Smart Citizen cache, meaning a `base.ini`, a `dataforge` folder or a `<channel>\cache` folder; a folder is removed only if that left it empty), `UnsafeDeleteRootReason()` (also gates `CleanCachedData()` and `CleanPerChannelCaches()`, the cache cleaning that runs on every install, upgrade and normal uninstall: a refused data folder is skipped with the reason in the log and no dialog, and `CleanCachedData()` clears the flat root-level `cache` under the same `LooksLikeScCache()` rule; refuses drive and share roots, device paths, Documents (the shell's and the local `%USERPROFILE%\Documents`), `%USERPROFILE%`, `{app}`, links, and any folder that is or contains the SC install, by registry and by `HasScGameData()` markers: `install_scanner.SC_CHANNEL_MARKERS` plus the player-data extras `USER`, `ScreenShots`, `logbackups`, `Game.log`) (#357) |

## Version & Release

### Branching model

Smart Citizen uses **long-lived release branches as integration targets**, not feature-branch-into-main.

- After a release ships, the next `release/X.Y.Z` branch opens off `main` and `VERSION.TXT` bumps on it. That branch becomes the integration target until it ships.
- **The version in the branch name signals scope.** A patch bump (e.g. `release/1.4.1`) is reserved for **bug fixes and minor polish** — anything bigger waits for the next minor or major. Use the branch version as a scope filter when reviewing or proposing changes: don't land a new feature on a patch branch without flagging the mismatch.
- **PRs target the active `release/X.Y.Z`, not `main`.** `main` only receives the release-branch merge.
- When the integration branch is feature-complete and stable, **the user adds the `build-installer` label to a PR** to produce a tester installer artifact (see *Tester pre-release installers*). Tests run against those artifacts before any merge to `main`.
- **Merging `release/X.Y.Z` → `main` is the release trigger.** That merge runs the per-release checklist below (tag, GitHub release, Discord webhook). Until then, no commit on the release branch is "released."

Don't propose tagging, drafting release notes, or merging to `main` mid-integration — the user drives that handoff. During integration, normal work is just landing PRs on the release branch.

### Branch protection

The branching model above is enforced by GitHub settings, not just convention. Don't propose workflows that fight these rules.

- **`release/*` is governed by the "Protect release branches" ruleset** (active; targets `refs/heads/release/*`). It requires every change to land via a pull request (no direct pushes), requires **one approving review from the code owner** (`@Osiris-DevWorks` via `.github/CODEOWNERS`, which owns `*`), forbids the author's own last push from being the approval, and blocks force-pushes and branch deletion. Net effect: a contributor can open a PR against a release branch, but only the owner's review can clear it to merge.
- **`.github/CODEOWNERS` lives on `main`** so every `release/X.Y.Z` cut from `main` inherits the owner gate automatically. A release branch created before the file existed needs it added directly (that's why `release/2.1.0` carries its own copy).
- **`main` has classic branch protection** (PR required, 0 approvals, admins included) — the release-branch merge still goes through a PR.
- **The repo owner (admin) bypasses the ruleset.** That's how the owner runs `start_release` (the initial `VERSION.TXT` bump is a direct push to the new branch), lands hotfixes, and merges PRs with `gh pr merge --admin`. Contributors have no bypass.
- **Process violations get reverted.** A direct push to a release branch that slips through (e.g. before protection existed) should be backed out via a revert PR, not left in place. The work returns through a normal PR.
- **Platform limit:** this is a personal (non-org) repo, so GitHub can't restrict the literal merge-button click to one user. The code-owner approval is the real gate; nothing merges without the owner's review even though the final click isn't account-restricted. Tightening that further would require moving the repo under an org.

### Release checklist (release/X.Y.Z → main)
1. `VERSION.TXT` should already match the branch name from when it opened — confirm (sole source of truth; `installer.iss` reads it via ISPP at compile time).
2. Build the PyInstaller onedir: `.venv/Scripts/python.exe scripts/build/build_exe.py`
3. Compile the installer (Inno Setup 6.6.0 or newer, which `installer.iss` enforces; Inno Setup is per-user; invoke via PowerShell): `powershell -NoProfile -Command "& 'C:\Users\<you>\AppData\Local\Programs\Inno Setup 6\ISCC.exe' installer.iss"`
4. Test the installer from `dist/SmartCitizen-{VERSION}-Setup.exe`
5. Merge `release/X.Y.Z` into `main`, then tag on `main` (`git tag -a vX.Y.Z -m "Release vX.Y.Z"`), push branch + tag.
6. Create the GitHub release and attach `dist/SmartCitizen-{VERSION}-Setup.exe` (installer only; portable onefile exe is retired).
7. Open the next `release/X.Y.(Z+1)` off `main` and bump `VERSION.TXT` — the new integration target.

Discord notification fires via GitHub Actions (`scripts/discord_notify.py`) when `DISCORD_RELEASE_WEBHOOK_URL` secret is set.

**Tester pre-release installers**: `.github/workflows/installer-preview.yml` builds a downloadable `SmartCitizen-{VERSION}-Setup.exe` artifact outside the standard release flow. Triggers: (1) `workflow_dispatch` from the Actions tab against any branch, (2) adding the `build-installer` label to a PR (later pushes to the labeled PR rebuild via `synchronize`; remove the label to stop rebuilds). In the integration-branch model this is the *primary* signal that a release is near test sign-off — when the user adds the label, treat the active release branch as approaching ship. Artifact: `smartcitizen-installer-{SHA}`, 30-day retention (testers need lead time vs. CI's 7). The `concurrency` group cancels in-flight builds when a newer commit lands on the same PR / branch.

**Tester pre-release portable builds**: `.github/workflows/portable-preview.yml` is the sibling of installer-preview for the portable variant. Same triggers and gate, but keyed off the `build-portable` label and `workflow_dispatch`; it runs `build_exe.py --portable` and uploads the `SmartCitizen-Portable-v{VERSION}.zip` (a no-install onedir: unzip, run the `.exe`, portable mode writes `data/` next to it). Artifact: `smartcitizen-portable-{SHA}`, 30-day retention, same concurrency cancel behavior. Use it when a tester wants to run without installing or to smoke-test portable-mode behavior (no registry) before a release.

**Preview artifact cleanup**: `installer-preview-cleanup.yml` (workflow name "Preview Artifact Cleanup") deletes the tester-build artifacts on PR merge so storage doesn't accumulate stale builds. It cleans *both* preview workflows (installer + portable). Its `WORKFLOWS` list must stay in sync with any new `*-preview.yml` that uploads per-PR artifacts.

## Debugging

- **Registry**: `regedit` → `HKEY_CURRENT_USER\Software\Osiris DevWorks\Smart Citizen` (live tree). Pre-0.9 installs leave a parallel `Osiris DevWorks\SC Localization Editor` tree the in-app migrator drains on next launch.
- **User data path**: if `Documents` is redirected (OneDrive), Registry stores the override under `user_data_dir` (legacy/manual alias `UserDataDir` also honored); delete that value to reset and auto-detect on next run.
- **Threading hangs**: check `worker.quit()` + `worker.wait()` in finished slots. Watch the Log Tab.
- **File encoding**: parser expects UTF-8; BOM or other encodings fail silently. Ensure cache files are UTF-8 no-BOM.
- **GitHub API rate limit**: unauthenticated, 60 req/hr per IP. Check updater logs if auto-update stalls.
- **Overrides not loading**: verify `{user_data_root}\{active_channel}\user.ini` exists with `key=value` format (no sections). A legacy `Documents\SC Localization Editor\overrides.ini` triggers both the rename (`overrides.ini` → `user.ini`) and the channel-nesting migration lazily on next launch.
- **Performance**: use `@timed` on slow functions and check elapsed times in DEBUG logs.

## Dependencies

- **PyQt6** (>=6.10.0) — GUI framework
- **pyinstaller** (>=6.3.0) — executable builder
- **pyperclip** (>=1.8.2) — clipboard
- **lxml** (>=5.0) — XML parsing for DataForge entity XMLs (`src/utils/dataforge_patcher.py`, mission classifiers in `scripts/generate_enhancements_ini.py`)

Windows-only by default (Windows Registry via QSettings in the standard build; portable builds skip the registry and write a JSON file next to the `.exe`). Python 3.9+, 3.10+ recommended.
