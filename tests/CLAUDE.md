# tests/CLAUDE.md

Test suite layout. See the root `CLAUDE.md` for project context.

## Unit tests

Split by domain:

- `test_core.py` — INI parsing/merging/category extraction. `TestStringEntry` is `@pytest.mark.skip`: its constructor calls predate `category` and `status` becoming required positional args (cleanup pending).
- `test_missions.py` — mission rewards pipeline.
- `test_mission_engagement.py` — FPS / Ship / FPS&Ship engagement classifier from CIG loc-key naming.
- `test_mission_turrets.py` — turret detection from `SpawnDescription_ShipGroup Name="Turrets"` plus the `OverrideTurretHosility_BP` mission-variable signal. Fabricated XML, so no populated cache needed.
- `test_spawn_classifier.py` — 1.4.1 4-bucket spawn classifier (Crew / Boarders / Wave Hostiles / Wave Allies) that replaced the flat "Enemies" tally on mission descriptions.
- `test_mission_variant_tuple.py` — 1.4.1 regression: a variant adding an 11th tuple field threw `ValueError: too many values to unpack (expected 10)`. Locks the variant-tuple shape.
- `test_mission_desc_annotation_toggle.py` — 1.4.1 Tag-Builder toggle that suppresses `[CLASS-…]` component annotations inside mission descriptions while leaving the standalone component INIs annotated.
- `test_missile_name_tag.py` — 1.4.1: bomb name tags carry their ordinance letter, not size-only, so the variant column distinguishes `[BOMB-X-…]` from `[BOMB-Y-…]`.
- `test_commodity_journal.py` — 1.4.1 generator guard for the `commodity_journal` unpack crash when the crafting cache directory is missing.
- `test_blueprint_pools.py` — multi-source pool merge regression, component-style tag annotation, CIG-prefix strip, pool rank-tier label.
- `test_blueprint_filename_fallback.py` — #281 fuel-nozzle alias correction in `_name_from_blueprint_filename`, so all 8 variants resolve to their real names instead of garbled title-cased-slug fallback text in mission blueprint bullets.
- `test_blueprint_log_scanner.py` — #222 BP Scan log scanner (#223 moved its button + result UI onto the Blueprint Tracker tab; the scanning internals tested here are unchanged by that move). `parse_events` keys only on the `<SHUDEvent_OnNotification> Added notification "Received Blueprint: <name>: "` line (embedded quotes survive, UI-echo/continuation lines and malformed timestamps ignored); `scan_files` applies the March-2026 epoch floor + exclusive watermark, de-dups names across files, and advances `latest_timestamp` past the watermark for a monotonic mark; `find_log_files` discovers `logbackups\*.log` + `Game.log` oldest-first with an mtime pre-filter (also honoring the watermark, so an unchanged rotated log isn't re-opened on a later scan); `scan_channel` composes the two for the worker's entry point. Fabricated logs via `tmp_path`, no SC install or Qt. The worker + MainWindow fold-in stay manual-test only.
- `test_blueprints_shuttle.py` — Blueprint Tracker's Available/Owned split (`BlueprintTrackerTab._available_blueprints`, a pure staticmethod).
- `test_pak_extraction.py` — P4K/DataForge.
- `test_xml_path_index_cache.py` — 2.2.0 regression: `xml_path_index` had no `_LOOKUP_VERSIONS` entry, so it silently defaulted to `"v1"` forever. Once `main()` started wrapping `forge_dir`/`records_dir` via `win_paths.win_long_path` (#231), a pre-#231 pickle (unprefixed paths) kept getting reused against post-#231 callers comparing prefixed paths, crashing `scan_crafting_blueprints`'s `xml_file.relative_to(bp_dir)`. Locks that `xml_path_index` has its own pinned version and that a stale pre-bump pickle is invalidated while a matching-version one still hits cache.
- `test_progress_sink.py` — thread-safe progress coalescing.
- `test_dataforge_patcher.py` — declarative XML patching.
- `test_app_updater.py` — GitHub Releases version-check worker, plus the #211 auto-updater's installer-asset picker (`pick_installer_asset`: anchored name match, malformed-entry tolerance).
- `test_channel_layout.py` — per-channel directory migration.
- `test_cache_dir.py` — 1.4.1 split of the DataForge cache override from the user-data override: `CACHE_DIR` is its own registry key, defaults to `%LOCALAPPDATA%\Smart Citizen\<channel>\cache\dataforge\` when unset, and never falls back to the user-data override.
- `test_retired_url_sources_migration.py` — 1.0 cleanup of contracts/components/ships/commodities/gear sources retired in 0.7.0. Covers fresh-install defaults, upgrade-time prune, URL-vs-local guard, idempotence.
- `test_applied_file_validator.py` — post-apply `global.ini` vs stock `base.ini`.
- `test_entry_filter.py` — column-filter logic plus the `NUM_COLUMNS` getter-tuple drift guard.
- `test_markdown_renderer.py` — About/Help markdown→HTML.
- `test_resource_path.py` — PyInstaller `_MEIPASS`-aware paths.
- `test_status_classification.py` — post-1.3.0 `_determine_status_from_source` (Enhanced vs Modified).
- `test_user_cfg.py` — `g_language` in user.cfg follows the selected language (mapped through `SC_LANGUAGE_IDS`; updates in place, no duplicate lines).
- `test_user_ini_autosave_guard.py` — v1.3.0 regression guard: `should_autosave_user_ini` refuses a close-time autosave that would truncate a populated `user.ini` to 0 bytes after a load mismatch.
- `test_frontend_version_stamp.py` — `Frontend_PU_Version` watermark applied at apply-to-game time.
- `test_portable_mode.py` — portable flag flips `AppSettings._backend` to `JsonSettings` and routes `get_user_data_dir()` next to the exe.
- `test_build_info_fallback.py` — `build_mode.py` falls back to `IS_PORTABLE = False` when `_build_info.py` is absent.
- `test_json_settings.py` — file-backed `QSettings`-API shim for portable mode.
- `test_locpack_exporter.py` — Loc-Pack zip writer.
- `test_tag_builder.py` — TagConfig serialization + `render_tag` output shape.
- `test_tag_config_settings.py` — TagConfig persistence via `AppSettings`. Covers the 1.4.0 rename `Phys`/`Distort`/`Bio` → `Physical`/`Distortion`/`Biochemical`.
- `test_mining_salvage_stats.py` — 1.4.0 `enhancements_mining_laser` / `enhancements_salvage_tool` extractors. Per-mode beam stats for mining heads and handheld salvage tools, fabricated XML.
- `test_medical_consumables.py` — 2.2.0 `enhancements_medical_consumables`, the one enhancement category with no DataForge XML dependency. Static `MEDICAL_CONSUMABLE_EFFECTS` dict driven straight off a plain `loc` dict (no XML, no tmp_path cache): every known CureLife pen key gets an appended effect line while the original lore is preserved, unknown/missing keys are skipped silently, unrelated loc keys are untouched, `stats_prepend` puts the effect line first, no `<EM4>` tags, and the locked set of exactly 7 known pen keys (base AdrenaPen/CorticoPen/DeconPen/DetoxPen/MedPen/OpioPen/OxyPen — not the Xtra variants, BoostPen, or VitalityPen).
- `test_ship_weapon_tag.py` — 1.4.0 guard for `_ship_weapon_name_tag_factory`: EMP devices with size but no damage and tractor beams must NOT emit a damage tag; real combat weapons must.
- `test_user_ini_reset.py` — `reset_user_ini(path, *, backup=True)` contract for the Config tab's **Reset user.ini** button. Returns `None` when source absent, `backup=True` renames to a timestamped sibling, `backup=False` deletes outright, same-second double-call doesn't clobber the first backup.
- `test_user_ini_backups.py` — rotating `user.ini` snapshots + restore (#172). `backup_user_ini` snapshots into `backups/` and rotates to keep 5 (sorted by name, so deterministic under rapid same-tick saves), no-ops on missing/empty; `save_user_ini` snapshots before a content-changing overwrite (and not when unchanged); `restore_user_ini_backup` restores and snapshots the current file first (reversible). Includes the disaster regression: an empty save over a populated `user.ini` snapshots the prior 36-override state first.
- `test_crash_handler.py` — `sys.excepthook` + `threading.excepthook` install plus the ring-buffer log dump to `{logs_dir}/crash_*.log`. Also the 2.0 crash-dialog wiring: the main-thread hook hands `crash_logger.show_crash_dialog` the dump path, and a dialog that raises must neither eat the dump nor break the original-hook chain.
- `test_error_dialog.py` — `logging.ERROR`/`CRITICAL` → modal-dialog handler plus the main-thread signal hop.
- `test_available_languages.py`: 2.0 language selector gate. `get_available_languages()` hides languages whose `ui.json` is a stub (only `_comment`); English is always offered.
- `test_i18n.py`: 2.0 UI translation contract. `tr()` dot-path resolution, English fallback for untranslated keys, bare-key fallback when missing everywhere, kwargs interpolation degradation, `_deep_merge` scalar-over-dict tolerance, lazy English load when `set_language` was never called (workers' progress strings).
- `test_language_paths.py`: 2.0 per-language cache layout. English base.ini at the cache root vs `cache/lang/{language}/` for others, enhancements dir = base.ini parent, per-language `.dataforge_stamp` isolation, base.ini URL resolution (override > bundled sources.json > ''), `SC_LANGUAGE_IDS` mapping fallback, and `get_localized_doc_path` (translated HELP/ABOUT/LEGAL win for non-English, bundled `docs/` is the fallback).
- `test_language_overlay.py`: 2.0 merge overlay. `load_sources_from_settings()` inserts the bundled `languages/<lang>/global.ini` as a `language` source just before `user` (appended without user); missing or empty overlay degrades to English-only without touching the hierarchy.
- `test_user_data_dir_migration.py`: `migrate_user_data_dir` (#103). Merge-never-overwrite copy when the user changes the data folder; `move=True` deletes transferred originals and prunes emptied dirs; the new-folder-nested-inside-old case can't recurse.
- `test_onedrive.py`: OneDrive data-root detection (#172). `is_onedrive_path` matches under `%OneDrive%`-style roots and `OneDrive` / `OneDrive - Org` path segments (case-insensitive), rejects look-alikes (`OneDriveBackups`) and sibling-prefix paths (`...\OneDriveStuff` is not under `...\OneDrive`); `suggest_local_data_dir` returns `%USERPROFILE%\Documents\Smart Citizen` and is itself not OneDrive. Plain environ dict, no registry.
- `test_mission_detail_fields.py`: per-field mission-detail toggles (#121). AppSettings contract (all fields default on, round-trip, unknown keys ignored) plus a line-for-line replica of the generator's `if _show(field)` gating.
- `test_window_state_portable.py`: #141 regression. Window geometry/state is base64-encoded so the portable `JsonSettings` backend can store the `QByteArray` without crashing on close.
- `test_backfill_new_elements.py`: `AppSettings._backfill_new_elements` upgrade path. Saved tag configs from older versions gain newly added element kinds disabled, so existing output is unchanged.
- `test_discovered_items.py`: XML-based item discovery. Items whose loc key is absent from base.ini get synthesized descriptions and appear with status "New".
- `test_not_for_release.py`: contracts/handlers with `notForRelease="1"` are skipped entirely by `scan_contract_generators` (the 1.4.2 dev-contract leak fix).
- `test_blueprint_list_type_tag.py`: #101 regression. The component Type element renders on component entries inside mission blueprint lists, not just standalone component names.
- `test_commodity_tagging.py`: #97 commodity tagging. Crafting (CF) and Collection flags share one `<EM4>[...]</EM4>` wrapper; single-flag items drop the empty flag; crafting-only output matches pre-1.5.0.
- `test_favorite_prefix_whitespace.py`: #100 regression. A single-space favourite prefix survives the user.ini round-trip (`parse_ini_file` gained a `strip_values` flag, False for user.ini).
- `test_mission_header_em_tag.py`: #99. Mission-header emphasis options are exactly EM3/EM4 (EM1/EM2 never render in-game); stored legacy values coerce back to the default.
- `test_mission_rep_label.py`: #102. `_rep_reward_line` uses the configurable `rep_xp_label` as field name or trailing unit, never both ("Rep: +500 Rep" is locked out).
- `test_mission_titles_page_dirty_signal.py`: #259. Four Mission Titles page checkbox handlers (`_on_mt_standardize_toggle`, `_on_mt_abbrev_toggle`, `_on_mt_shorten_titles_toggle`, `_on_mt_shorten_sizes_toggle` — 7 checkboxes total) updated `self.config` but never emitted `config_changed`, so Save Tag Changes never armed. Drives the real `_TagBuilderPage` widget headlessly (`QT_QPA_PLATFORM=offscreen`), same pattern as `test_restore_backup.py` — no pytest-qt.
- `test_sc_install_root.py`: `get_sc_install_root` cross-check. `GAME_INSTALL_PATH` wins over a stale pre-1.4.2 `SC_INSTALL_ROOT`; `os.path.normcase` comparison absorbs drive-letter casing.
- `test_string_table_model_bounds.py`: #110 regression. `entry_for_row` tolerates out-of-range rows after a failed/empty load; uses `__new__` to stay Qt-free.
- `test_mission_route_title.py`: #166 hauling/delivery route-in-title, reworked for the #200 hotfix. The pure `_derive_route_fragment` / `_route_token_role` / `_title_route_token` / `_expand_nested_route_vars` helpers in `generate_enhancements_ini.py` driven with synthetic bodies: |Address is the default token modifier (|name fails to resolve on some instances), multi-endpoint sides render comma lists (`A > B, C`), bare `*Token` vars expand one level against the loc table keeping only endpoints every variant registers, per-body intersection drops vars pooled bodies disagree on (var-less bodies abstain), Pickup/Dropoff copied verbatim. Deliberately does NOT use the stale `kraken_4.7.ini` fixture.
- `test_ui_mode.py`: #180 Simple/Advanced view. AppSettings `ui_mode` contract (default 'simple', round-trip, unknown coerces), `SimpleModeWidget` signal/`set_busy` behavior, and `MainWindow._apply_ui_mode` page-swap driven on a lightweight stub `self` (no full window — no pytest-qt). Imports `AppSettings` via `src.utils.settings` so the monkeypatch hits the same class object `main_window` uses.
- `test_scitem_lookup_bare_type_and_mining_laser.py`: #266 bare-type (fuel nozzle) and mining-laser bullet tags, plus the #345 size-line fix. `_SIZE_LINE_RE` is the one pattern every desc-size read shares; `TestSizeLineRegex` covers both CIG size forms (`Size: 1` and the S-prefixed `Size: S0` used by mining heads, bomb racks, scopes) and carries a drift guard that greps the generator for a forked bare-digit copy, which is how the bug happened.
- `test_owned_items.py`: `[Owned]` tag weaving and the name normalizer. `TestNormalize` locks the #346 alias fold: `BULLET_NAME_ALIASES` lives in `owned_items` (not `blueprint_meta`) so both sides of every comparison fold through it, the fold runs after the tag/annotation strips, and it's idempotent (no real name is itself an alias key).
- `test_favorite_toggle_stranded.py`: #330 follow-up. `MainWindow.toggle_favorite` driven on a stub `self` (same pattern as `test_ui_mode`): a stranded pre-#329 favorite prefix on a non-favoritable row (ship description, or any category) is removable and never re-addable; name-row add/remove unchanged; an empty prefix can't turn the stranded path into a value-clearing no-op.
- `test_drop_none_entries.py`: #389 crash mitigation. `MainWindow._drop_none_entries` strips stray `None` items out of a freshly loaded/merged entries list before anything downstream (`_restore_pending_user_edits`'s `e.key` read, `update_category_combo`'s `e.category` read, the table model) can dereference one and crash. Covers empty/no-`None`/single/multiple/all-`None` inputs, order preservation, and that a warning logs only when something was actually dropped.
- `test_single_job_skips_threadpool.py`: #389 mitigation. `scripts/generate_enhancements_ini.py`'s `main()` must not construct a `ThreadPoolExecutor` when exactly one lookup/generator job is selected (a pool of one buys no parallelism, and is the exact shape the reported native heap-corruption crash, 0xC0000374, traced back to — a background thread nested under another background thread doing lxml-based XML parsing). Runs the real `main()` against a fabricated single-category (`medical_consumables`) job with `ThreadPoolExecutor` patched to prove it's never constructed, and separately confirms the single-job path still produces correct output.

QThread workers in `src/gui/workers.py` have no automated tests — they need `pytest-qt` (not a dev dep). Manual smoke testing is the only path.

## Pytest config

`pytest.ini` at the project root, not under `tests/` — placing it there makes rootdir resolve to `tests/` and breaks the `from src.X` imports CI uses. `pythonpath = . src` (project root for `from src.X`, `src/` for legacy `from utils.X`). Markers: `unit`, `integration`, `slow`, `critical`, `regression`.

## Test isolation

Tests should not depend on Registry state; mock `AppSettings` or use conftest fixtures.

## GUI testing

Manual. Run app, load base file, edit a value, apply to game, restart to verify persistence. Watch the Log Tab for load/merge/apply errors.
