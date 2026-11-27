# CLAUDE.md

This file guides Claude Code (claude.ai/code) when working in this repo.

> **Before editing files under `src/<dir>/`, `scripts/`, or `tests/`, read that directory's `CLAUDE.md` first.** See *Per-directory guides* below for the list.

## Osiris DevWorks development pipeline (universal)

This section is identical in every Osiris DevWorks repo's CLAUDE.md. Change it in all of them at once. The line just below it says how this repo applies it. Where an older section of this file conflicts with it, this section wins.

The goal is little friction and few GitHub Actions runs: checks and code review run once per release, not once per feature.

1. **Grill the idea.** When Amr brings a new idea, ask questions until it is ready to build. Ask every question as a multiple-choice decision card (`request_decision`, or `AskUserQuestion` in the CLI) with a recommended option, never as questions in prose. A few cards at a time is fine.
2. **Mock up any UI.** When a feature adds or changes UI, show an HTML Artifact mockup during grilling. Build it from the app's real colors, fonts, spacing and layout, read from the source, and show the current screen next to the changed one. Grilling isn't done until Amr approves the mockup.
3. **Grilling sign-off is the approval.** Once Amr says the idea is ready, build it without further check-ins: no step-by-step plan approvals, no code-block reviews, and no commit-message review. Ask again only if the work hits a choice that grilling did not settle.
4. **Push straight to the integration branch, with no feature PR.** Run the repo's tests, lint and type check in your own session. Update this repo's test plan, if it has one, with concrete pass/fail items for the feature. Then push **one squashed commit per feature** to the integration branch, with a message like `#123: short summary` (`Fixes #123` in the body when it closes the issue). A feature branch is fine while you work; only the squashed result lands. Never force-push the integration branch.
5. **Release: one PR, all checks, one review.** When Amr calls a release, open one PR from the integration branch to production. Every pre-release check and the code review run on that PR, once. Fix what they find with more commits on the integration branch. Amr runs the test plan (on preview builds or staging) and merges, or tells you to merge.
6. **Hotfixes.** For an urgent production fix, branch off production, open a PR straight to production (full checks and review run on it), and once it merges, merge production back into the integration branch.
7. **Outside PRs.** Contributor and Dependabot PRs get CI only, with no Claude review bot. Dependabot is grouped and runs monthly.
8. **Workflow triggers.** Keep workflows off feature work: no `push` triggers on integration branches except where a deploy needs one, and the Claude review workflow runs only on PRs into production. Don't add a workflow that runs on every push without Amr's OK.

**How this repo applies it: desktop app.** The integration branch is the active `release/X.Y.Z` and production is `main`. Each feature push also adds its section to the in-app tester Test Plan (`TEST_SECTIONS` in `src/utils/test_plan.py`). Amr runs the plan on the `build-installer` / `build-portable` preview builds of the release PR before it merges. `/begin_work` drives a feature; `/PRE_RELEASE` and `/SHIP_RELEASE` drive the release. See *Version & Release* below.

## Communication style

- **Plain words, short sentences.** Cut adjectives, hedges, and throat-clearing. If a sentence isn't earning its weight, drop it.
- **One concept per message.** When the work involves several distinct concepts, present the first, stop, and ask the user before moving on. Do not stack ideas, decisions, or trade-offs in a wall of text.
- **Prompt at decision points.** When the next step needs the user's preference, judgment, or clarification, ask before proceeding. A one-line confirmation is cheaper than redoing work.

## Project Overview

Smart Citizen (formerly SC Localization Editor) is a Windows-only PyQt6 GUI for customizing Star Citizen localization strings. Tagline: *Smarter Strings for Star Citizen*. Users edit strings in a table backed by the `global` source (locally cached `base.ini` from Data.p4k) merged with per-channel `user.ini` overrides, then apply the result to their game with backup management.

**Branding**: User-facing strings, registry path (`Osiris DevWorks\Smart Citizen`), and the default data root (`Documents\Smart Citizen\`) use the new name. `AppSettings` keeps one-shot migrators for the legacy `Osiris DevWorks\SC Localization Editor` registry tree and `Documents\SC Localization Editor\` folder (rebrand was 0.9.0); keep them while pre-0.9 users may upgrade.

**Version**: `VERSION.TXT` is the sole source of truth. Now 3.0.0.

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
flake8 src/ tests/ scripts/       # lint, settings in .flake8
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
I/O-bound work (file loads, network, P4K extraction) runs in `QThread` workers in `src/gui/workers.py` (lone exception: `AppUpdateCheckWorker` in `src/utils/app_updater.py`, next to its companion logic). The one plain `threading.Thread` in `workers.py` is `LanguageNameTablesRead` (#569): `perform_merge_and_reload` reads the other languages' base.ini files on it beside its own merge and waits for it just before the rebuild. A reload that stops before that (no sources, or a merge that fails) leaves it running, and a `QThread` dropped while it runs aborts the app, where this daemon thread just finishes. Workers emit `finished()`; cleanup needs `quit()` + `wait()`. Never block the main thread on file or network I/O. Wrap bulk table updates in `setUpdatesEnabled(False)`. `AppSettings` is thread-safe — use from main or worker. Worker logger names: `src.gui.workers` post-extraction (`src.gui.main_window` pre-extraction) — matters when grepping logs.

### Startup initialization
On first run, the app sets up user data dirs, validates the SC install path, and may show a startup dialog to guide config. Later runs check source freshness and apply any pending DataForge cache updates.

### DataForge extraction is a four-step pipeline
The "Extract DataForge from P4K" button triggers, in order:
1. Unpack Data.p4k → entity XMLs via `src/utils/pak_extractor.py`. The bundled unp4k and unforge are .NET tools from the `odw-fast-unp4k` fork: unp4k reads Data.p4k's directory once and extracts through the archive it opened for the listing (on every core when there are several matches), and unforge reads the records on every core, leaving out the record folders the generator never reads (#522 and #529; which commits the bundled exes are built from is in `src/utils/CLAUDE.md` → `pak_extractor.py`). unp4k and unforge work in a per-run folder beside the DataForge cache rather than in `%TEMP%` (#471; `%TEMP%` is only the fallback for a cache on OneDrive, a network share, a removable or network drive, or nested too deep), and closing the app stops them; see `src/utils/CLAUDE.md` → `pak_extractor.py`.
2. Apply declarative patches from `patches/` via `src/utils/dataforge_patcher.py` to fix upstream CIG data bugs. Idempotent; runs on the extracted cache even when step 1 is skipped as fresh.
3. Run `scripts/generate_enhancements_ini.py` over the XMLs for every enabled category. Every file it writes is replaced in one step (`src/utils/atomic_io.py`), so a run cut off part-way leaves each file whole, old or new. Closing the app stops it at its next job boundary, never during its writes (see `src/gui/CLAUDE.md` → *Closing stops a running extraction*). Nothing hashes the cache any more: the old diff manifest, which nothing read, is gone (#495).
4. Reload all strings to refresh the table.

The progress dialog stays continuous across steps 1–3 so users see one bar from start to finish. Run in Background, one of the choices Esc or the X on the dialog offers, sends the run and its generation to the status bar instead, with what they depend on locked until they end (#483, see `src/gui/CLAUDE.md` → *Run in Background and the job lock*). A generation's own dialog asks the same question.

### Merge hierarchy
Sources merge in user-defined order. Later sources overwrite earlier ones; user overrides apply last and survive source updates. As of 1.0 the seeded default is just `[global, user]` — the URL sources (contracts/components/ships/commodities) and `gear` retired in 0.7.0 when extraction moved to local Data.p4k, and `migrate_remove_retired_url_sources()` removes them from upgrader registries. `load_sources_from_settings()` also injects a synthetic `enhancements` source at runtime when any enhancement category is enabled on the Enhancements tab — it is *not* a registry entry; don't add it to the hierarchy by hand.

### Language system (2.0, #30)
Two independent layers share one selected language (`AppSettings.get_selected_language()`, set from the Config tab):

1. **UI chrome** is translated via `src/utils/i18n.py`: `tr("dot.path.key", **kwargs)` reads `languages/{lang}/ui.json`, overlaid on English so missing keys fall back (then to the bare key). A runtime switch re-merges strings, and `MainWindow.retranslate_ui()` (with each tab's own `retranslate_ui`) sets the built widgets' texts again, the texts a refresh or a load writes included, so a switch shows what a restart in that language shows. `tests/test_language_switch_text.py` compares the two text by text, in both views with nothing loaded, and fails on a text there that has no `retranslate_ui` line (#540). Languages whose `ui.json` is a stub (only `_comment`) are hidden from the selector by `get_available_languages()`.
2. **Game strings**: English `base.ini` comes from local P4K extraction; every other language downloads a community `global.ini` per `languages/sources.json` (per-user URL override via the Config tab's *Map Language File* dialog). Caches are per-language: English at `{channel}\cache\base.ini`, others at `{channel}\cache\lang\{language}\base.ini` (`get_base_ini_path(language)`). The `global` merge source follows the selected language by one rule, `AppSettings.get_global_source_base_ini()` (the language's own base.ini when this channel has it, otherwise the English one), at startup, after a channel switch or a data-folder change and after a successful global.ini extraction (#502). The Blueprint Tracker's Owned set holds display names, so each load renames an owned name saved in another language to the loaded one through its loc key, read from one cached base.ini per other language (whichever channel has it), and a scan and Import Owned Blueprints do the same with their names (#569, see `src/gui/CLAUDE.md`).

Enhancements are language-aware: generated INIs live next to that language's `base.ini` (`get_enhancements_dir()`), and a `.dataforge_stamp` marker per language triggers regeneration on switch when stale (English included). A generation empties that stamp just before the generator's `main()` runs (a failure before that keeps the old one) and writes it when `main()` returns, so the startup check also offers to regenerate a set whose last run was cut off or failed. Generator annotation paths always parse the *English* base.ini (tags and lookups stay English), while the text the generator adds itself (stat labels, mission details, journal lines) is translated through `languages/{lang}/enhancements.json` (#579, see `src/utils/CLAUDE.md` → `enhancement_text.py`); the mission section headers, the Rep label, tags such as `[BP]` and item names stay as they are. A translated language's `.dataforge_stamp` carries its table's fingerprint (`AppSettings.enhancements_stamp_value`), so an update that changes the table makes the set out of date. Each start also fetches the selected language's community global.ini again when its source is a URL (`MainWindow._check_language_translation_at_startup`, a conditional request) and, when a new file came down, empties that language's stamp and reloads as a language switch does, so a translation fixed after a game patch arrives without a switch. The apply side is language-aware too: `get_global_ini_path()` writes `Localization\{sc_id}\global.ini` and `ensure_user_cfg_language()` sets `g_language` to match, both via `SC_LANGUAGE_IDS` (app folder name `portuguese_br` → game id `portuguese_(brazil)`). Turkish borrows `polish_(poland)` and Russian borrows `korean_(south_korea)`, because the game accepts neither language's own id; Russian and Korean sharing one slot is the one deliberate exception to "a borrowed slot is never shared" (the Korean font is the only in-game font with Cyrillic), so applying either replaces the other's `global.ini`.

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
| Cached sources | `{user_data_root}\{active_channel}\cache\` — only `base.ini` post-1.0 (four legacy URL sources retired in 0.7.0), with its `.base_ini_stamp` (the size of the Data.p4k it was extracted from and base.ini's own size, #522); enhancement INIs live here too. Non-English languages cache their downloaded base.ini at `cache\lang\{language}\base.ini` (2.0); resolved via `AppSettings.get_base_ini_path(language)` |
| DataForge cache | `%LOCALAPPDATA%\Smart Citizen\{active_channel}\cache\dataforge\` by default (entity XMLs from Data.p4k); overrideable independently of the user-data root via the `CACHE_DIR` registry key (1.4.1+ — `AppSettings.get_cache_dir_override()` / `set_cache_dir()`, wired to the Config tab's *DataForge Cache Folder*; the cache override does *not* fall back to the user-data override). Moved out of `Documents\` in 1.x — `migrate_dataforge_cache_to_local()` relocates the legacy `…\cache\dataforge\` tree on first launch. Resolved via `AppSettings.get_dataforge_cache_dir()`, which creates it, only where the folder is meant to be made (the migrator, an extraction about to fill it or work beside it, a newly picked folder in the Config tab), and via `get_dataforge_cache_leaf()`, which creates nothing, everywhere else: every status check, Clear Cache (#479), and the enhancement generator, which writes into a cache its launcher has already checked is there. So a folder Windows refuses or a drive that is gone reads as not extracted (#494). An extraction works in a sibling `…\cache\dataforge.extracting-XXXXXXXX\` folder (up to about 4.5 GB free while it runs, checked before any tool starts (#482), deleted when it ends, or after a successful DataForge run in the background while enhancements are generated, with the old cache set aside in it (#522); the global.ini extraction in `globalini.extracting-XXXXXXXX`) so the heavy writes land on the cache's drive (#471). A cache on OneDrive, a network share, a removable or network drive, or nested too deep sends the run to `%TEMP%\SmartCitizen-DataForge-XXXXXXXX\` instead (`SmartCitizen-GlobalIni-` for global.ini). A DataForge run there first makes and removes one empty `dataforge.extracting-` folder beside the cache folder, so a folder that would not let the wipe make the cache folder again is refused before any tool runs, with the old cache kept (#494). A cache folder that is itself a junction or a symbolic link is refused before an extraction runs, with the old cache and the link kept, because nothing is deleted through a link (#491). |
| Saved crafting orders (SCO Order tab, 3.1.0) | `{user_data_root}\orders\<name>.json` (not per-channel). Resolved via `AppSettings.get_sco_orders_dir()`; made on the first save. The order being built lives in settings (`sco/order`) |
| Crash dumps + log exports | `{user_data_root}\logs\` (NOT per-channel — a crash can fire before the channel context is established, e.g. during startup migrators). Resolved via `AppSettings.get_logs_dir()`; created lazily on first crash or export. |
| Enhancement INIs | next to the active language's base.ini via `AppSettings.get_enhancements_dir(language)`: `{user_data_root}\{active_channel}\cache\` for English, `cache\lang\{language}\` otherwise (`ships_desc_enhancements.ini`, `components_desc_enhancements.ini`, `ship_weapons_desc_enhancements.ini`, `fps_weapons_desc_enhancements.ini` (also carries the #492 armor weight tags), `mission_rewards_enhancements.ini`, `commodity_crafting_enhancements.ini`, `journal_enhancements.ini`, `missile_enhancements.ini`, `medical_consumables_enhancements.ini`; plus the `.dataforge_stamp` freshness marker and the `.tag_config_stamp` Tag Builder marker, and `crafting_index.json` for the overlay drawer's Crafting search and, since 3.1.0, its Order tab (each blueprint's slots, the stats they move and their quality curves), written whenever Commodities or Journal is generated, and `mission_blueprint_descs.json`, each blueprint mission's description keys for the `[BP Complete]` title tag, written whenever Missions is generated) |
| Overlay scan samples | `{user_data_root}\logs\sco_samples\` (not per-channel): a crop of each distinct signature reading while the overlay's scan decoder runs, at most 200 per session, and a session's first save prunes the folder to the newest 1000 (`sco_overlay.prune_samples`), so misreads can become reference glyphs. Tuning only: written only when the `SMART_CITIZEN_SCO_SAMPLES` environment variable (`sco_overlay.SAVE_SAMPLES_ENV`) is set when the app starts; players never get it and the app has no switch for it. Resolved via `AppSettings.get_sco_samples_dir()` at save time |
| SCO Item Finder shop list | `{user_data_root}\{active_channel}\cache\uex_shops.json` (`uex_shops.SHOP_CACHE_FILE`): the shops that sell each item and their prices, trimmed from UEX's `items_prices_all` and `terminals?type=item` answers, fetched at most every 12 hours (`MAX_AGE_S`) while the overlay runs with its Item Finder on, and used as it is when UEX cannot be reached (#606) |
| Backups | `{user_data_root}\{active_channel}\backups\` (max 5, oldest auto-deleted) |
| Game file | `{sc_install_root}\{active_channel}\data\Localization\{sc_language_id}\global.ini` — `AppSettings.get_global_ini_path()` (language dir follows the selected language via `SC_LANGUAGE_IDS`); `get_applied_global_ini(channel_dir)` names it in any channel's install folder |
| UI translations + language source map | `languages/{language}/ui.json` (UI strings) and `languages/sources.json` (per-language base.ini download URLs). Bundled via both `SmartCitizen.spec` and `scripts/build/build_exe.py` |
| P4K tools | `assets/unp4k/` (`unp4k.exe`, `unforge.exe`), built from `odw-fast-unp4k` (the commits are in `src/utils/CLAUDE.md` → `pak_extractor.py`) |
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
| Change what Apply says when Windows refuses the game folder (Errno 13) | `src/gui/main_window.py`, `src/merger/ini_merger.py`, `src/utils/read_only.py` | the `except PermissionError` in `apply_to_game()` and `_show_game_folder_refused()` (`apply.refused_game_running_body` when `shader_cache.is_star_citizen_running()`, else `apply.refused_body`); `merge_ini_files` re-raises a `PermissionError` unwrapped; `clear_read_only()` before the write and on each backup |
| Modify P4K extraction | `src/utils/pak_extractor.py` | `extract_dataforge()` |
| Change the extraction free-space check | `src/utils/pak_extractor.py` | `_require_free_space()`, `_dataforge_needs()`, `_require_room_for_new_cache()`, the #482 constants |
| Change how a folder tree is deleted (working folder, old cache, Clear Cache, queued cleanup) | `src/utils/pak_extractor.py` | `robust_rmtree()`, `_delete_files_first()` (the threaded file pass, #522), `_DELETE_THREADS` |
| Change enhancements generation | `scripts/generate_enhancements_ini.py` | (standalone script) |
| Add performance profiling | `src/utils/perf.py` | `@timed` decorator |
| Change user data paths | `src/utils/settings.py` | `AppSettings.get_user_data_dir()` |
| Change DataForge freshness | `src/utils/settings.py`, `src/gui/main_window.py` | `dataforge_cache_is_fresh()` |
| Change how generated files are written | `src/utils/atomic_io.py` | `atomic_writer()`, `atomic_write_text()`, `read_bytes_retrying()` (the enhancement INIs, `crafting_index.json`, both stamps, the lookup pickles and patched cache XMLs are swapped in whole, never written in place) |
| Change the enhancements out-of-date check | `src/utils/settings.py`, `src/gui/main_window.py`, `src/gui/workers.py` | `enhancements_built_from_current_dataforge()` (the one definition of "current", shared by the startup check, the Generate button and the language switch; `_mission_record_missing()` makes a Missions set without its `[BP Complete]` record out of date), `_check_enhancements_freshness()`, `EnhancementsGeneratorWorker.run()` (empties `.dataforge_stamp` before the generator runs, writes it after) |
| Change base.ini freshness (the Extract prompt and the Extract button's red nudge) | `src/utils/pak_extractor.py` | `base_ini_is_fresh()`, `BASE_INI_STAMP` (#522: Data.p4k's size, as #209 for DataForge, with base.ini's own size so the stamp speaks only for the base.ini it was written for; read by `MainWindow._check_p4k_freshness` and `ConfigTab._refresh_p4k_status`) |
| Change Run in Background or the job lock | `src/gui/main_window.py`, `src/gui/config_tab.py`, `src/gui/enhancements_tab.py`, `src/gui/simple_mode_widget.py`, `src/gui/theme.py` | `_confirm_stop_dataforge_extraction()`, `_send_dataforge_run_to_background()`, `_confirm_stop_generation()` (the same question on the generation dialog), `_stop_generation_from_dialog()`, `_send_generation_to_background()`, `_job_running()`, `_closing_would_wait()` (what Import Settings and an update's install ask: `_job_running()` plus a background working-folder delete), `_refresh_job_lock()`, `_dataforge_run_matches_settings()`, `_ask_after_the_job()` (a startup question a job put off, asked again after the load that ends it), `ConfigTab.set_data_locations_locked()`, `EnhancementsTab.set_changes_locked()`, `SimpleModeWidget.set_busy(busy, reason)`, `theme.needs_apply_style()`, `theme.dimmed_color()` (#483) |
| Change stats/favorites UI | `src/gui/enhancements_tab.py` | `setup_ui()` |
| Manage Config tab UI | `src/gui/config_tab.py` | `setup_ui()`, drag-drop hierarchy |
| Manage Enhancements tab UI | `src/gui/enhancements_tab.py` | `setup_ui()`, stats toggle, favorites config |
| Manage Blueprint Tracker tab UI | `src/gui/blueprint_tracker_tab.py` | `setup_ui()`, `set_blueprint_items()`, `_render_blueprint_lists()` |
| Change blueprint type/class/size/grade classification | `src/utils/blueprint_meta.py` | `build_blueprint_metadata()`, `blueprint_type_from_key()` |
| Add a blueprint every player starts with (never logged, never a mission reward) | `src/utils/blueprint_meta.py`, `src/gui/main_window.py` | `DEFAULT_OWNED_BLUEPRINTS` (by loc key, English name as fallback), `_seed_default_owned_blueprints()` (adds each to Owned once, on the first scan after it is declared, recorded by loc key, #416); their mission label `DEFAULT_OWNED_MISSION_LABEL` stays English in the metadata and shows translated through `mission_display_name()` |
| Change the "Scan Logs for Owned Blueprints" log parsing | `src/utils/blueprint_log_scanner.py`, `src/gui/main_window.py` | `parse_events()`, `scan_files()`, `find_log_files()`, `notification_templates()` (the notification in the language the game shows, #564), `main_window._blueprint_notification_files()` (the loc files its text is read from) |
| Change the owned-name repair (names another editor left, #372; items' short labels, #570; names saved in another language, #569) | `src/utils/owned_items.py`, `src/utils/blueprint_meta.py`, `src/utils/settings.py`, `src/gui/main_window.py` | `resolve_against_catalogue()`, `repair_foreign_owned_names()`, `drop_short_labels()` (keeps a label another language uses as an item's name), `rename_across_languages()` (through the loc key), `known_item_names()` (every real item name, short labels left out), `short_label_names()`, `item_name_sets()` (both, and each item's name by loc key, in one pass, what a load uses), `item_keys_by_name()` (another language's names, from its base.ini), `other_language_files()` (one cached copy per language but the loaded one), `read_item_keys_by_name()` (reads only new or changed files), `AppSettings.get_cached_base_ini_paths()` (every channel), `workers.read_language_name_tables()` (never on the GUI thread: the loader's thread, or `LanguageNameTablesRead` beside a synchronous reload), `MainWindow._repair_foreign_owned_names()` (on every load), `MainWindow._rename_from_other_languages()` (the load, a scan's names and Import Owned Blueprints), `BlueprintTrackerTab.set_name_renamer()` |
| Change the `[BP Complete]` mission title tag (General Tags' *BP Completed*) | `src/utils/owned_items.py`, `src/utils/blueprint_meta.py`, `scripts/generate_enhancements_ini.py`, `src/gui/main_window.py`, `src/gui/enhancements_tab.py` | `complete_mission_titles()`, `apply_bp_complete_to_title()`, `build_blueprint_metadata(names_by_desc=...)`, `MISSION_BLUEPRINT_DESCS_FILE` (the generator's title → description keys record, filled in `_run_gen_missions`, written by `main()`), `MainWindow._read_mission_bp_descs()` / `_bp_complete_titles()` / `_recompute_owned()`, `_ApplyMergeInputs.bp_complete_record` with `complete_titles_in_strings()` (Apply's own pass over the strings it writes), `AppSettings._mission_record_missing()`, the tab's `bp_complete_tag_changed` (a re-weave, never a generation) |
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
| Change what unforge leaves out of the DataForge cache | `src/utils/dataforge_exclude.py`, `src/utils/pak_extractor.py` | `DATAFORGE_EXCLUDE_SUBPATHS` (never a `DATAFORGE_KEEP_SUBPATHS` path, one under it or one above it), `_write_unforge_exclude_list()`, `_unlisted_records()` |
| Change Export / Import CSV, or which imported values are skipped (#565) | `src/utils/strings_csv.py`, `src/gui/main_window.py` | `write_strings_csv()` / `read_strings_csv()` (fixed English headers `CSV_COLUMNS`, UTF-8 with a BOM, the delimiter sniffed among `,;\t`, the system code page when the file is not UTF-8), `plan_override_import()` (the one skip rule for Import CSV and Import INI: empty, or the same as the Default or Current text), `MainWindow._export_csv()` (the rows the table shows, in its order), `_handle_import_csv()`, `_import_override_values()` (shared with `_handle_import_ini()`) |
| Change Export Loc-Pack zip behavior | `src/utils/locpack_exporter.py` | `default_locpack_filename()`, `write_locpack_zip()` |
| Change apply-time launcher watermark | `src/gui/main_window.py` | `_stamp_frontend_version()`, `_FRONTEND_VERSION_KEY`, `_FRONTEND_VERSION_STAMP_RE` |
| Change the Karolinger Guides links (footer logo, Help, the tour's video step) | `src/utils/karolinger.py`, `src/gui/main_window.py`, `assets/tutorial.json` | `KAROLINGER_GUIDES_URL`, `KAROLINGER_VIDEO_TUTORIAL_URL` (placeholders, #602), `with_guides_url()` (the `{KAROLINGER_GUIDES_URL}` token in every `HELP.md`), `MainWindow._footer_pixmap()` (every footer image), the `guides` tour step |
| Change the main-menu Play button reminder | `src/gui/main_window.py` | `_add_play_button_reminder()`, `_PLAY_BUTTON_KEY`, `_PLAY_BUTTON_REMINDER` (a replaced wording must stay in `_PLAY_BUTTON_REMINDER_RE`), `_centre_menu_lines()`, the button's fonts `_BLENDER_PRO_MEDIUM` and `_NOTO_SANS` (for `_NOTO_SANS_SLOTS`, picked by `_ApplyMergeInputs.sc_language_id`) (#566) |
| Change Modified/Enhanced/Unmodified/New status logic | `src/parser/ini_parser.py` | `_determine_status_from_source()` |
| Adjust close-time user.ini autosave guard | `src/utils/user_ini_manager.py` | `should_autosave_user_ini()` |
| Change "Reset user.ini" tool behavior | `src/utils/user_ini_manager.py`, `src/gui/config_tab.py` | `reset_user_ini()` (+ Config-tab button wiring) |
| Change user.ini backup/restore behavior | `src/utils/user_ini_manager.py`, `src/gui/main_window.py` | `backup_user_ini()` / `list_user_ini_backups()` / `restore_user_ini_backup()` (rotating snapshots in `backups/`, #172); Config-tab **Restore user.ini** → `_handle_restore_user_ini()` |
| Move DataForge XML cache out of Documents | `src/utils/settings.py` | `migrate_dataforge_cache_to_local()`, `get_dataforge_cache_dir()` |
| Add a tag-builder element/style/category | `src/utils/tag_builder.py` | `CATEGORY_ELEMENT_KINDS`, `STYLES_BY_KIND`, `DEFAULT_TAG_CONFIGS`, `render_tag()` |
| Change Tag Builder UI / live preview | `src/gui/enhancements_tab.py`, `src/gui/tag_mapping_dialog.py` | `_PREVIEW_VALUES`, `TagMappingDialog` |
| Persist/load tag configs | `src/utils/settings.py` | `AppSettings.get_tag_config()`, `set_tag_config()`, `get_all_tag_configs()` |
| Add a new stats-enhancement generator (e.g. mining/salvage analogue) | `scripts/generate_enhancements_ini.py` | `enhancements_mining_laser`, `enhancements_salvage_tool` (reference pattern); register in `DATAFORGE_KEEP_SUBPATHS`, and take the path out of `DATAFORGE_EXCLUDE_SUBPATHS` |
| Add a new *static* enhancement category with no DataForge dependency | `scripts/generate_enhancements_ini.py` | `enhancements_medical_consumables` (reference pattern) — reads only `loc`/base.ini, no XML scan, so it needs no `DATAFORGE_KEEP_SUBPATHS` entry; still needs `ENHANCEMENTS_FILES` + `ENHANCEMENT_LABELS` + `ENHANCEMENT_CATEGORY_FILES` entries in `settings.py` |
| Change crash-dump behavior | `src/utils/crash_handler.py`, `src/main.py` | `install_crash_handler()`; install site is the early `main()` setup, before the QApplication is constructed |
| Change error-dialog cooldown / coalescing | `src/gui/main_window.py`, `src/gui/error_dialog.py` | `MainWindow._show_error_dialog()` (cooldown / spam protection lives on the slot, not the `ErrorDialogHandler`) |
| Move the DataForge cache off the default path | `src/utils/settings.py`, `src/gui/config_tab.py` | `AppSettings.get_cache_dir_override()` / `set_cache_dir()` (1.4.1+; independent of the user-data override); `ConfigTab._maybe_apply_cache_change()` (undoes a change whose cache folder cannot be made, as Cancel does, and `_report_cache_folder_error()` says why in one box, #494) |
| Add or fix a translated UI string | `languages/{language}/ui.json`, `src/utils/i18n.py` | `tr()`, `set_language()` (dot-path keys; English is the fallback base) |
| Change the language-switch flow | `src/gui/config_tab.py`, `src/gui/main_window.py` | `language_changed` signal, `MainWindow._on_language_changed()` (retranslate chrome, repoint the `global` source, download base.ini when a URL is mapped, regen stale enhancements, reload) |
| Translate the text the generator adds (stat labels, mission details, journal lines) | `scripts/generate_enhancements_ini.py`, `src/utils/enhancement_text.py`, `languages/{language}/enhancements.json` | `_t()` (keyed by the English text), `load_table()`, `table_fingerprint()`; after adding a `_t()` text run `python tests/test_enhancement_text.py --write` and add it to every language's table (#579) |
| Change per-language base.ini download / URL mapping | `src/gui/workers.py`, `src/utils/settings.py`, `languages/sources.json` | `LanguageBaseDownloadWorker`, `get_language_base_url()`, `LanguageSourceDialog` (Config tab's *Map Language File*), `MainWindow._check_language_translation_at_startup()` / `_on_language_translation_checked()` (the start-time re-download, #579) |
| Change per-language cache or enhancements layout | `src/utils/settings.py` | `get_base_ini_path(language)` (and `get_base_ini_leaf(language, channel)`, the same file for any channel with no folder made, #564), `get_enhancements_dir(language)`, `get_/set_enhancements_stamp()` (the setters' `folder=` takes the folder a generation started with), `invalidate_enhancements_stamp()` |
| Toggle mission-detail fields per user | `src/gui/enhancements_tab.py`, `src/utils/settings.py` | `_MISSION_FIELD_SETTING` (per-field show/hide for mission bodies, #121); the `route` key adds the haul route to titles (#166) |
| Change hauling/delivery route-in-title | `scripts/generate_enhancements_ini.py` | `_derive_route_fragment()` / `_route_token_role()` / `_title_route_token()` / `_expand_nested_route_vars()` (#166, reworked in #200: |Address default, comma-listed endpoints, one-level `*Token` expansion, per-body intersection; applied in both the contractgen title loop and the pu-only second pass; placed before the [BP]/XP tags via the mission_titles TagConfig) |
| Change stock-title shortening (Mission Titles) | `src/utils/tag_builder.py`, `scripts/generate_enhancements_ini.py` | `SHORTEN_PHRASE_OPTIONS` (phrase→shorter-phrase) + `REMOVE_WORD_OPTIONS` (Cargo/Haul/Rank word removal, Rank merged to one checkbox covering both dash- and comma-led contexts) + `abbreviate_title()`; `RANK_SEPARATORS` (None/Dash/Pipe/Colon rendered after the Rank position regardless of removal; "none" default, "space" omitted as indistinguishable from "none" post-normalization); `SIZE_ABBREVIATIONS` + `_size_abbreviation_overrides()` (cargo-grade words to XS/S/M/L via loc-key overrides, each size independently opted in via `TagConfig.shortened_sizes`); word/phrase removal gated by `TagConfig.abbreviated_phrases` (empty by default), applied at both title-emission sites (#200 follow-up, generalized) |
| Change the UI font size (Small/Medium/Large) | `src/utils/ui_scale.py`, `src/utils/settings.py`, `src/gui/config_tab.py`, `src/main.py` | `FONT_SCALE_FACTORS`, `apply_font_size_env()` (sets `QT_SCALE_FACTOR` before the `QApplication` is built, so a change needs a restart: `MainWindow.restart_app()`), `get_/set_font_size()`, `_on_font_size_changed()`. A Qt scale factor rather than the app font because most labels set px sizes in their own stylesheets and many controls have fixed widths |
| Change minimize to tray, or the second start that brings a copy in the tray back | `src/gui/tray.py`, `src/main.py`, `src/gui/config_tab.py`, `src/gui/main_window.py`, `src/gui/global_hotkey.py`, `src/utils/settings.py` | `TrayController` (the icon, the hide on a minimize through an event filter, `restore()`, `quit()`, `shut_down()` from `closeEvent`, the wake socket only while hidden, and `_show_notice_once()`, the "still running" notice on the first trip to the tray ever, recorded by `AppSettings.get_/set_tray_notice_shown()`), `instance_name()` (one per Windows user for installed copies, one per portable folder), `bring_back_hidden_copy()` (plain Windows pipe calls, asked in `main()` right after the crash handler, before any migrator or window, and taken back if the copy does not read it in time, so a busy copy never leaves two windows), `global_hotkey.allow_any_foreground()` (which the second start calls first, handing on its right to bring a window to the front so the copy comes back in front), `AppSettings.get_/set_minimize_to_tray()`, `ConfigTab.minimize_to_tray_changed`. See `src/gui/CLAUDE.md` → `tray.py` |
| Change the Clear Shader Cache tool (Config tab's *Star Citizen Tools*) | `src/utils/shader_cache.py`, `src/gui/shader_cache_dialog.py`, `src/gui/config_tab.py` | `find_shader_cache_dirs()`, `humanize_cache_name()`, `clean_shader_cache()` / `remove_build_folder()`, `ShaderCacheDialog` (per-row Clean / Remove, runs `ShaderCacheWorker`) |
| Change Simple/Advanced view mode | `src/gui/main_window.py`, `src/gui/simple_mode_widget.py`, `src/utils/settings.py`, `installer.iss` | `_apply_ui_mode()` (QStackedWidget swap), `_run_simple_apply()` (one-button extract→generate→apply chain via the `_simple_run_active` flag), `get_/set_ui_mode()`, installer `ModeChoicePage` writing `ui_mode` (#180); the Simple page's Start/Stop Overlay button (`SimpleModeWidget.overlay_toggled` drives the toolbar's `sco_btn`, `MainWindow._mirror_sco_running()` shows the overlay's state on it and on the Overlay tab) |
| Change data-folder move behavior | `src/utils/user_ini_manager.py`, `src/gui/config_tab.py` | `migrate_user_data_dir(old, new, move=...)` (merge-never-overwrite; `move=True` deletes migrated originals and prunes empty dirs) |
| Change the OneDrive data-root warning | `src/utils/onedrive.py`, `src/gui/main_window.py`, `src/gui/config_tab.py` | `is_onedrive_path()` / `suggest_local_data_dir()`; `_maybe_warn_onedrive_data_dir()` (startup, suppressible) + Config-tab folder-pick warning; `ConfigTab.change_data_dir_to()` for the one-click move (#172) |
| Change the data move after a YES on Setup's OneDrive warning | `installer.iss`, `src/utils/settings.py`, `src/utils/user_ini_manager.py`, `src/main.py`, `src/gui/main_window.py` | `NextButtonClick` (a YES remembers the data folder in `OneDriveMoveFrom` when it is the one being left, a NO forgets it, and leaving the page works out `PendingDataMoveFrom`) and `WriteInstallerChoicesToRegistry` (writes it as `pending_data_move_from`); `AppSettings.migrate_installer_data_move()` (reads and deletes the value, one try, before the channel-layout and cache migrators); `move_owned_user_data()` (only `OWNED_DATA_FOLDERS`, the channel folders and `logs`, merged, never overwriting); `MainWindow._report_installer_data_move()` (a status bar note, or a box when files stayed) (#455) |
| Change the What's New pop-up after an install or update | `src/gui/whats_new_dialog.py`, `src/utils/release_notes.py`, `src/gui/main_window.py`, `SmartCitizen.spec`, `scripts/build/build_exe.py` | `WhatsNewDialog`, `bundled_release_notes()` (`docs/{VERSION}-RELEASE-NOTES.md`, bundled only when it exists), `MainWindow._maybe_show_whats_new()` (after the startup update check), `AppSettings.get_/set_whats_new_seen_version()` |
| Change the toolbar More overflow menu | `src/gui/main_window.py` | `more_menu` block in toolbar setup (restore backup, clear loc/cache, import/export, open loc dir) |
| Change the tester Test Plan panel / content | `src/utils/test_plan.py`, `src/gui/test_plan_panel.py` | `TEST_SECTIONS` (per-release checklist), `TestPlanPanel`, `_ensure_test_plan_dock()` / `show_test_plan()` (#144) |
| Change the Smart Citizen Overlay (SCO) | `src/gui/sco_overlay.py`, `src/gui/global_hotkey.py`, `src/gui/game_screen.py`, `src/utils/mining_signatures.py`, `src/utils/sco_digit_reader.py`, `src/utils/blueprint_log_scanner.py` | `ScoOverlay`, `BlueprintDrawer`, `ScanLabelWindow` (the watched-target alerts, `ALERTS`, and the text size, #523), `SCAN_REGION`, `decode_signature()`, `format_matches()`, `read_signature()` (+ `DIGIT_SAMPLES` reference glyphs), `GameLogTail`, `GlobalHotkey` (the drawer hotkey), `game_screen()` (the drawer and the capture follow the game's monitor, #573) and `ScoOverlay.toggle_drawer()`; MainWindow `_toggle_sco_overlay()` / `_on_sco_blueprints_found()` / `_on_sco_hotkey_problem()` |
| Fix an SCO scan misread (teach the digit reader a new glyph) | `scripts/add_sco_sample.py`, `src/utils/sco_digit_samples.py`, `src/utils/sco_digit_reader.py` | Start the app with `SMART_CITIZEN_SCO_SAMPLES=1` so the overlay saves crops, rename the crop from `logs\sco_samples` to the real number (or pass `--digits`), run `add_sco_sample.py <crop> --write` (`cut_glyphs()` cuts the digits without matching them), copy the crop to `tests/fixtures/sco/<source>_<digits>.png`; `DIGIT_SAMPLES` |
| Change the SCO drawer's Minerals / Crafting searches | `src/utils/mining_catalog.py`, `src/gui/sco_overlay.py`, `scripts/generate_enhancements_ini.py` | `parse_mining_compendium()` / `read_compendium()`, `star_system()` (+ `STAR_SYSTEM_LOCATIONS`), `CraftingIndex` / `crafting_index.json` (written by `scan_crafting_blueprints(crafting_index=...)`), `BlueprintDrawer.set_catalog()`, `MainWindow._refresh_sco_catalog()` |
| Change the SCO drawer's Order tab (3.1.0) | `src/gui/sco_order.py`, `src/utils/crafting_order.py`, `scripts/generate_enhancements_ini.py`, `src/utils/mining_catalog.py`, `src/utils/settings.py` | `OrderSection` / `OrderLineCard` (the summary on top, search, one card per item), `material_totals()` / `stat_modifiers()` / `add_to_order()` / `load_order()` (Qt-free order maths), `_blueprint_order_facts()` / `_build_crafting_order()` (each blueprint's slots, pick groups, stat names and quality curves, read from `crafting/blueprints` and `crafting/craftedproperties`), `CraftingIndex.blueprints` / `stats` / `curves` (`crafting_index.json` version 2), `AppSettings.get_/set_sco_order()` (user data, left out of profile defaults) and `get_/set_sco_order_volume()` |
| Change the SCO drawer's Item Finder (where to buy an item, #606) | `src/utils/uex_shops.py`, `src/gui/sco_overlay.py`, `src/gui/workers.py`, `src/gui/main_window.py` | `load_shop_data()` (cache under 12 hours old, else UEX, else the old cache), `build_shop_data()` (LIVE shops with a buy price only), `ShopData.search()`, `BlueprintDrawer.set_shop_data()` / `_render_finder()`, `UexShopDataWorker`, `MainWindow._refresh_sco_shops()` (run from `_apply_sco_options` while the overlay runs; retries a failed load only after `UEX_RETRY_S`) |
| Change Smart Sync (owned blueprints, string edits and settings across PCs, #567) | `src/utils/smart_sync.py`, `src/utils/settings.py`, `src/gui/workers.py`, `src/gui/main_window.py`, `src/gui/config_tab.py` | `smart_sync.sync()` / `record()` / `merge()`, `AppSettings.get_/set_smart_sync_folder()` and the `smart_sync/*` keys, `set_owned_items` (records the ledger), `import_values` (adds while sync is on), `SmartSyncWorker`, `MainWindow._start_smart_sync()` / `_smart_sync_inputs()` / `_take_smart_sync_result()` / `_take_synced_edits()` / `_take_synced_user_ini()` / `_finish_smart_sync_for_close()`, `smart_sync.record_values()` / `merge_values()`, `AppSettings.apply_synced_settings_at_startup()` / `write_smart_sync_backup()` / `SMART_SYNC_LOCAL_KEYS`, the Config tab's Smart Sync group |
| Change the Overlay tab / SCO on-off switches | `src/gui/overlay_tab.py`, `src/utils/settings.py`, `src/gui/main_window.py` | `OverlayTab`, `AppSettings.SCO_OPTION_SETTING` + `get_/set_sco_option()` (the `alert_` switches included), `get_/set_sco_drawer_position()` (`SCO_DRAWER_POSITIONS` → `BlueprintDrawer.set_position()`), `get_/set_sco_label_size()` (`SCO_LABEL_SIZES` → `ScoOverlay.set_label_size()`), `get_/set_sco_drawer_hotkey()` (→ `ScoOverlay.set_drawer_hotkey()`), `MainWindow._apply_sco_options()` |
| Change the uninstaller's opt-in "Also delete all saved settings" wipe | `installer.iss` | `InitializeUninstall()` (the dialog; skipped on `/SILENT` and `/VERYSILENT` unless `/SHOWDELETEOPTION=1`), `DeleteAllUserSettings()` (also the default data and cache folders when overridden, the legacy `Documents\SC Localization Editor` folder, and the queued `pending_cache_cleanup` tree), `DeleteOwnedSubpaths()` (app-owned names only; the old root-level `cache` only when `LooksLikeScCache()` says it holds a Smart Citizen cache, meaning a `base.ini`, a `dataforge` folder or a `<channel>\cache` folder; a folder is removed only if that left it empty), `UnsafeDeleteRootReason()` (also gates `CleanCachedData()` and `CleanPerChannelCaches()`, the cache cleaning that runs on every install, upgrade and normal uninstall: a refused data folder is skipped with the reason in the log and no dialog, and `CleanCachedData()` clears the flat root-level `cache` under the same `LooksLikeScCache()` rule; refuses drive and share roots, device paths, Documents (the shell's and the local `%USERPROFILE%\Documents`), `%USERPROFILE%`, `{app}`, links, and any folder that is or contains the SC install, by registry and by `HasScGameData()` markers: `install_scanner.SC_CHANNEL_MARKERS` plus the player-data extras `USER`, `ScreenShots`, `logbackups`, `Game.log`) (#357) |
| Change what Setup deletes in the install folder, or where it installs | `installer.iss` | `[InstallDelete]` (`{app}\*` only behind `InstallDirMayBeEmptied()`; elsewhere only the program names a release installed (each `?` stands for one version digit), `SmartCitizen.exe`, `SmartCitizen-v?.?.?.exe`, `SCLocalizationEditor.exe`, `SCLocalizationEditor-v?.?.?.exe`, and `_internal`), `WholeInstallDirReason()` / `ScanInstallDir()` / `IsOwnProgramFile()` / `IsVersionedProgramName()` (what counts as Smart Citizen's, by long name, kept in step with those entries: the folder is emptied whole only when nothing else is in it, whatever it is called, and `unins000.exe` / `.dat` / `.msg` count only beside a program file or `_internal`), `NewInstallDir()` / `GiveInstallItsOwnFolder()` (the install folder page adds `\Smart Citizen` to a folder that holds files Smart Citizen did not install, silent runs too, never to the previous install's folder or past `MaxInstallDirLength`, Setup's 240 characters; where only that length stops it, `NewInstallDir`'s `TooLong` makes an interactive run show a box asking for a shorter or empty folder and stay on the page, while a silent run logs why and stops without installing, because the narrow `_internal` entry could take another program's) (#454) |

## Version & Release

### Branching model

Smart Citizen uses **long-lived release branches as integration targets**, not feature-branch-into-main.

- After a release ships, the next `release/X.Y.Z` branch opens off `main` and `VERSION.TXT` bumps on it. That branch becomes the integration target until it ships.
- **The version in the branch name signals scope.** A patch bump (e.g. `release/1.4.1`) is reserved for **bug fixes and minor polish** — anything bigger waits for the next minor or major. Use the branch version as a scope filter when reviewing or proposing changes: don't land a new feature on a patch branch without flagging the mismatch.
- **Features are pushed straight to the active `release/X.Y.Z`**, one squashed commit each, with no feature PR. Contributor PRs also target it. `main` only receives the release PR's merge and hotfix PRs.
- When the integration branch is feature-complete and stable, **the `build-installer` / `build-portable` labels go on the release PR** to produce tester artifacts (see *Tester pre-release installers*). Tests run against those artifacts before any merge to `main`.
- **Merging `release/X.Y.Z` → `main` is the release trigger.** That merge runs the per-release checklist below (tag, GitHub release, Discord webhook). Until then, no commit on the release branch is "released."

Don't propose tagging, drafting release notes, or merging to `main` mid-integration — the user drives that handoff. During integration, normal work is just pushing squashed feature commits to the release branch.

### Branch protection

The branching model above is enforced by GitHub settings, not just convention. Don't propose workflows that fight these rules.

- **`release/*` is governed by the "Protect release branches" ruleset** (targets `refs/heads/release/*`). It blocks force-pushes and branch deletion. Under the pipeline, Amr's and Claude's feature pushes must be allowed straight onto the branch, either because the ruleset no longer requires a PR or because they are bypass actors. Contributors still go through a PR, which needs **one approving review from the code owner** (`@Osiris-DevWorks` via `.github/CODEOWNERS`, which owns `*`). If a push is refused by the ruleset, stop and tell Amr; don't open a PR to get around it.
- **`.github/CODEOWNERS` lives on `main`** so every `release/X.Y.Z` cut from `main` inherits the owner gate automatically. A release branch created before the file existed needs it added directly (that's why `release/2.1.0` carries its own copy).
- **`main` has classic branch protection** (PR required, 0 approvals, admins included) — the release-branch merge still goes through a PR.
- **The repo owner (admin) bypasses the ruleset.** That's how the owner runs `start_release` (the initial `VERSION.TXT` bump is a direct push to the new branch) and merges PRs with `gh pr merge --admin`. Contributors have no bypass.
- **Hotfixes** branch off `main` and go through a PR into `main` (CI and the Claude review run on it); once merged, `main` is merged back into the active release branch.
- **Platform limit:** this is a personal (non-org) repo, so GitHub can't restrict the literal merge-button click to one user. The code-owner approval is the real gate; nothing merges without the owner's review even though the final click isn't account-restricted. Tightening that further would require moving the repo under an org.

### Release checklist (release/X.Y.Z → main)
1. `VERSION.TXT` should already match the branch name from when it opened — confirm (sole source of truth; `installer.iss` reads it via ISPP at compile time).
2. Build the PyInstaller onedir: `.venv/Scripts/python.exe scripts/build/build_exe.py`
3. Compile the installer (Inno Setup 6.6.0 or newer, which `installer.iss` enforces; Inno Setup is per-user; invoke via PowerShell): `powershell -NoProfile -Command "& 'C:\Users\<you>\AppData\Local\Programs\Inno Setup 6\ISCC.exe' installer.iss"`
4. Test the installer from `dist/SmartCitizen-{VERSION}-Setup.exe`
5. Merge `release/X.Y.Z` into `main`, then tag on `main` (`git tag -a vX.Y.Z -m "Release vX.Y.Z"`), push branch + tag.
6. Create the GitHub release and attach `dist/SmartCitizen-{VERSION}-Setup.exe` (installer only; portable onefile exe is retired).
7. Open the next `release/X.Y.(Z+1)` off `main` and bump `VERSION.TXT` — the new integration target.

**Code signing**: `release.yml` signs `SmartCitizen.exe` (with the bundled unp4k/unforge), the installer and the portable `.exe` files through Azure Artifact Signing, then zips the portable folder again (`build_exe.py --portable --zip-only`). It runs only when the `AZURE_SIGNING_ACCOUNT` repository variable is set; the job uses the `release` environment so the Azure federated credential has one subject. Inno signs the installer and its uninstaller itself through `scripts/build/sign_file.ps1` (`/DSIGN` turns on `SignTool=azure` in `installer.iss`).

**Download checks**: every release gets a build provenance attestation for the installer and the portable zip (`gh attestation verify <file> --repo Osiris-DevWorks/smart-citizen`), and, when the `VIRUSTOTAL_API_KEY` secret is set, a VirusTotal scan. The README's VirusTotal badge links to `https://osiris-devworks.github.io/smart-citizen/virustotal/`, a redirect page on the `gh-pages` branch that the release workflow rewrites to the installer's newest scan (#601); the release notes no longer carry scan links, and the README never needs a hand edit. Security reports go through `SECURITY.md` (GitHub private vulnerability reporting).

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
