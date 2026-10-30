# Translation Provenance

Provenance is tracked **inline** in each `languages/<lang>/ui.json` (#182). Every
leaf is an object with two fields:

```json
"apply_btn": { "ht": "Appliquer au jeu", "at": "Appliquer au jeu" }
```

- **`ht`** — the human translation. Non-empty means a human translated this key.
- **`at`** — the AI translation, used as a fallback. `tr()` shows `ht` when it is
  non-empty and falls back to `at` otherwise.

So the structure itself says who translated what:

- **`ht` non-empty** → human-translated. Never edited or overwritten by AI; only
  replaced by a better human translation.
- **`ht` empty, `at` non-empty** → no human translation yet; the app shows the AI
  string. **These are exactly the keys a human translator should review.** Find
  them by grepping a language file for `"ht": ""`.
- **both empty** → untranslated; the app falls back to the English base.

The English file is the source: every leaf is `{"ht": "<source text>", "at": ""}`
(English needs no AI fallback).

## Workflow

- **Translators:** translate a key by filling its `ht`. That immediately takes
  over from the AI `at` in the app — no list to update, the structure is the
  record. Leave `at` as-is (it stays as the safety net if `ht` is ever cleared).
- **Pre-release AI backfill:** any key still missing an `at` for an exposed
  language gets one (Claude, styled on the file's existing human strings for
  register and terminology), so no shipped language shows raw English. Seeding a
  human key's `at` from its own `ht` is fine — the known-good human text is the
  best fallback.
- The guided tour lives in `assets/tutorial.json` (English) and is translated per
  language under the `tutorial.*` keys. English has no `tutorial.*` section, so
  those keys are language-only by design.

## Needs human re-review

Keys whose **English source changed after they were human-translated**. The
`ht` values below are still the translator's words for the old English text,
so they were left untouched (AI never edits `ht`); a human should re-translate
them against the new source.

- `enhancements.apply_tag_changes_btn` — English renamed from "Apply Tag
  Changes" to "Save Tag Changes" (#214, 2.1.2). Affects french,
  portuguese_br, spanish (all three still translate "Apply...").
- `config.map_language_desc`, `dialogs.language_no_url`,
  `dialogs.language_download_failed` — English reworded from URL-only to
  URL-or-local-file phrasing for #367's local-file *Map Language File*
  support. Affects spanish, whose human `ht` for all three still describes
  a URL-only flow ("Define una URL al global.ini...", "No hay URL de
  descarga configurada..."). The AI `at` fallback for every other non-English
  language had the same staleness (no `ht` to protect there, so the 2026-10-01
  backfill below refreshed all of them directly instead of just flagging it).
- `enhancements.cat_desc_gear` — English changed from "Combat stats for FPS
  weapons" to "Combat stats for FPS weapons and armor weight tags" (#492: the
  Gear checkbox now also governs the Tag Builder's armor tags). Affects
  french, portuguese_br and spanish, whose human `ht` still describes weapon
  stats only. The AI `at` fallbacks were refreshed.
- `enhancements.annotate_mission_descs_cb` — English changed from "Annotate
  components in mission descriptions" to "Annotate components and armor in
  mission descriptions" (#492: the checkbox now also covers armor weight tags
  in POTENTIAL BLUEPRINTS lists). Affects french, portuguese_br and spanish,
  whose human `ht` still says components only. The AI `at` fallbacks were
  refreshed where one existed (spanish's was empty and stays empty).
- `enhancements.desc` and `enhancements.tag_builder_desc` — English now
  lists every tagged category ("components, missiles, ship weapons,
  commodities, and armor", and the caption also the route on hauling mission
  titles) instead of only the first three (#492 review). Affects french,
  portuguese_br and spanish, whose human `ht` still names three categories.
  The AI `at` fallbacks were refreshed where one existed (spanish's are empty
  and stay empty).
- `config.data_desc` — English's size for the DataForge cache changed from
  ~1.4 GB to ~1.2 GB (#482, 2.5.0), the size measured on LIVE 4.10. Affects
  french, portuguese_br and spanish, whose human `ht` still says 1,4 Go or
  1,4 GB (in french and portuguese_br the `at` is a copy of that `ht` and
  was left as it is too). The seven other languages had no `ht` there, so
  their `at` was corrected directly (2.5.0 entry below).

## Backfill log

- **2.5.0 cycle (2026-10-29, Claude Opus 5.5):** the overlay's scan-sample
  capture left the app (it is now for tuning the digit reader only, behind
  an environment variable). Removed in every language: `overlay.samples_group`,
  `overlay.save_samples`, `overlay.save_samples_hint` and
  `overlay.open_samples_btn` from `ui.json`, HELP's **Save scan samples**
  bullet and LEGAL's **Overlay scan samples** data-location bullet. Nothing
  added, so nothing to translate.
- **2.5.0 cycle (2026-10-28, Claude Sonnet 5.5):** a language check of
  everything added for 2.5 found `HELP.md` and `ABOUT.md` out of date in ten
  languages (not russian, which was brought current on 2026-10-20), so they
  are caught up with English. HELP's Tag Builder entry gains #492's armor
  text: the Armor tab's one Weight element, the `L`, `M`, `H`, `S` and `U`
  classes and `C` for clothing, **Edit mapping…**, that the tags are written
  with the Gear enhancements, that the annotate checkbox also puts them on
  armor in the POTENTIAL BLUEPRINTS lists (which come from Missions, so they
  show even with Gear off), and why the Armor tab has no None brackets.
  HELP's Appearance entry gains the Font size choice (Small, Medium or Large,
  with an offer to restart). ABOUT's Tag Builder entry gains armor and its
  Weight element. The older Map Language File text from #367 (a local file
  through Browse, and the warning to copy its `global.ini` out of the
  Star Citizen install) is added in the eight languages that still described
  a URL only: german, french, spanish, italian, portuguese_br, japanese,
  chinese and chinese_traditional (korean and turkish already had it).
  Armor, Weight, the class names and POTENTIAL BLUEPRINTS stay in English
  because the app shows them in English, as russian does. The buttons and
  checkboxes named are each language's own `ui.json` text, and each file's
  own words for the category names (Gear, Missions) and the Blueprint
  Tracker. In french, portuguese_br and spanish the annotate checkbox is
  quoted as the app shows it, and its human `ht` still says components only
  until a translator re-translates it (see Needs human re-review). AI text
  throughout, checked against English for length, the `L`, `M`, `H`, `S`, `U`
  and `C` letters and the Korean sentence-spacing rule, not back-translated.
  No `ui.json` changed.
- **2.5.0 cycle (2026-10-23, Claude Opus 5.5):** #523, overlay feedback.
  28 new keys: `overlay.scan_group`, `overlay.drawer_group`,
  `overlay.blueprint_watch_group` and `overlay.samples_group` (the Overlay
  tab's four boxes), `sco.surface_only`, `sco.watch_salvage_tooltip` and
  `sco.tooltip_salvage_signature` (the Minerals section's Salvage row and
  round numbers that list salvage first), `overlay.label_size` with
  `overlay.size_small` / `_medium` / `_large` / `_extra_large` (the scan
  text size), `overlay.alerts_title` with `overlay.alert_glow`, `_flash`,
  `_color`, `_bigger` and `_sound` and a `_hint` for each (what a watched
  mineral or salvage sets off), and `overlay.drawer_hotkey`,
  `overlay.drawer_hotkey_clear` (the Clear button beside the box),
  `overlay.drawer_hotkey_hint` (with its example, Alt+8, the same in every
  language: Star Citizen's default bindings never use 8 or Alt on its own,
  and 8 has one key code on every layout), `overlay.hotkey_taken`
  and `overlay.hotkey_unsupported` (the drawer hotkey). Four English texts
  changed: `sco.crafting_search_placeholder` ("Type a scannable or item
  name...", since more than components can be crafted),
  `overlay.drawer_crafting_hint` (items, not components),
  `sco.watch_mineral_tooltip` (the label alerts, not only glows) and
  `overlay.desc` (with a drawer hotkey set, the overlay watches key presses
  for that one combination). `overlay.drawer_hotkey_hint` also says that
  Star Citizen still gets those keys, since the overlay watches the
  keyboard's raw input while the game keeps registered hotkeys away, and
  that in game the player still holds F to use the mouse in the drawer
  (Windows does not let the overlay take focus from the game). AI `at`
  in all 11 other languages; none had an `ht` on any of these keys, so
  nothing needs human re-review. The same change updated
  `docs/HELP.md`'s Overlay Tab section, `docs/FAQ.md`'s overlay paragraph
  and `docs/ABOUT.md`'s overlay bullet, and the 11 translated copies of
  each, worded with each `ui.json`'s own names: the text size, the alerts,
  the Salvage row, round numbers listing salvage first, the drawer hotkey
  (that it needs Ctrl, Alt or Win unless it is an F key or Pause, and in
  the FAQ, the raw input it watches and what it never does), and items
  instead of components.
- **2.5.0 cycle (2026-10-20, Claude):** New language **russian** added,
  split out of #488 by **h0use** (Den McConan) without that PR's channel
  badge. AI translation of every UI key (`at`-only, `ht` empty), the full
  20-step guided tour (`tutorial.*`, translated from `assets/tutorial.json`
  and including the Overlay step), and `HELP.md`, `ABOUT.md`, `LEGAL.md` and
  `FAQ.md`, brought current with English (Overlay tab, armor weight tags,
  starter blueprints, free-space and cache-folder troubleshooting). Base
  `global.ini` mapped to **n1ghter/StarCitizenRu**
  (`data/Localization/korean_(south_korea)/global.ini`). Russian borrows the
  `korean_(south_korea)` slot, shared with Korean on purpose (see the
  per-language note); `HELP.md` in every language now says the two replace
  each other's applied file.
- **2.5.0 cycle (2026-10-17, Claude Opus 5.5):** #479 makes More > Clear
  Cache clear the DataForge cache in use and moves every text it shows into
  `ui.json`; before, only its four titles and its cache-empty text were
  translated. Ten new keys, after `dialogs.cache_cleared_title`:
  `dialogs.clear_cache_busy` (Clear
  Cache is not available while an extraction or an enhancement generation
  runs, try again once it has finished; shown in the status bar),
  `dialogs.clear_cache_files_body` (the cached files that will be deleted,
  `{files}`, and that base.ini will need extracting again from Data.p4k
  before strings can load; the old English text kept),
  `dialogs.clear_cache_dataforge_body` (also clear the DataForge cache?,
  `{folder}`, what it holds and that making it again takes a few minutes,
  and to keep it to refresh only the localization strings),
  `dialogs.clear_cache_dataforge_unreachable` (the DataForge cache folder
  `{folder}` could not be reached, so it was not cleared),
  `dialogs.clear_cache_progress_title`, `dialogs.clear_cache_progress_files`,
  `dialogs.clear_cache_progress_file` (`{name}`) and
  `dialogs.clear_cache_progress_dataforge` (the progress dialog's title and
  labels), `dialogs.cache_cleared_body` (`{count}` items deleted) and
  `dialogs.cache_cleared_failed` (could not delete, then `{failures}`, one
  per line, each Windows' own error text, not translated). `{folder}` stands
  on a line of its own. In all 10 languages, `at`-only (`ht` empty), with
  each file's own words for Clear Cache (the menu item's), the cache, the
  DataForge cache folder (as in the #494 entry below) and the enhancements
  (the Enhancements tab's name: enrichissements, Erweiterungen,
  miglioramenti, mejoras, aprimoramentos, geliştirme, 拡張, 강화, 增强内容,
  增強內容). The DataForge question's old warning sign and its closing
  "Clear DataForge cache?" line are gone: the title already asks.
  chinese_traditional follows the chinese strings in Taiwan terms (快取,
  資料夾, 檔案, 存取, 重新整理). Each string was back-translated and compared
  with the English in the same pass, not by a separate checker: no meaning
  errors, and the Korean sentence-spacing rule holds. No human string
  changed. `tests/test_clear_cache.py` checks every language's placeholders,
  the folder on a line of its own, and this `ht`/`at` split.
- **2.5.0 cycle (2026-10-17, Claude Opus 5.5):** #455: a YES on Setup's
  OneDrive warning now moves the data at the app's next start, and the app
  says what it did. Three new `onedrive.*` keys after `dont_warn_again`:
  `installer_move_done` (the status bar note: the files moved out of
  OneDrive into the new data folder), `installer_move_left_title` and
  `installer_move_left_body` (the box when some files stayed in the old
  folder: why, that the Log tab lists them, and to check the old folder
  before deleting it). In all 10 languages, `at`-only (`ht` empty), worded
  with each file's own words from `onedrive.warning_*` and
  `config.migrate_data_done_body` (the "file(s)" form, the data folder, the
  reader's form of address) and its own name for the Log tab. Each string was
  back-translated and compared with the English in the same pass, not by a
  separate checker: no meaning errors, and the Korean sentence-spacing rule
  holds. `tests/test_installer_data_move.py` checks every language's
  `ht`/`at` split and placeholders.
- **2.5.0 cycle (2026-10-17, Claude Opus 5.5):** #483 brings back Run in
  Background for the DataForge extraction (the 2.4.0 entry below has the
  button's first pass) and locks what a running job depends on. Four
  `extract.*` keys, the three new ones right after `dataforge_stop_btn`:
  `dataforge_background_btn` ("Run in Background") and the three-choice
  `dataforge_running_body` (stop it now, or let it carry on in the background
  while you keep working; if you stop it, you can run it again later), both
  with the text each file had when the button was dropped in 2.4.0, and two
  new keys. `dataforge_settings_changed`: the DataForge extraction finished,
  but the DataForge cache folder or the channel changed while it ran, so no
  enhancements were generated and no old cache was cleared, with each file's
  word for the DataForge cache folder from `config.dataforge_cache_label`.
  `locked_while_job_runs`: locked while an extraction or an enhancement
  generation is running, and unlocked again when it finishes (shown on the
  Config tab, as the Apply Category Changes, Save Tag Changes, Generate
  Enhancements and Simple-mode tooltips, in a box when an install the scan
  found is picked during a job, and in the status bar), with each file's
  words for the extraction and for
  generating enhancements from `extract.dataforge_extraction_title` and
  `status_bar.generating_enhancements_background`. In all 11 languages,
  `at`-only (`ht` empty). No language had a human `dataforge_running_body`,
  so nothing needs human re-review. The two new strings were back-translated
  and compared with the English in the same pass, not by a separate checker:
  no meaning errors, and the Korean sentence-spacing rule holds.
  `tests/test_run_in_background.py` checks the four keys' `ht`/`at` split in
  every language.
  Russian, added later in 2.5.0 (#514), got the four keys when this was
  merged with it (2026-10-21), `at`-only: the two new strings, the button, and
  its two-choice `extract.dataforge_running_body` rewritten as the
  three-choice question. Back-translated with no meaning errors.
  The enhancement generation dialog asks the same question since 2026-10-23
  (it used to hide, and showed itself again as soon as more progress
  arrived). Three new `extract.*` keys after `locked_while_job_runs`:
  `generation_running_title` (enhancement generation running),
  `generation_running_body` (enhancement generation is still running, then
  the same second paragraph as `dataforge_running_body`) and
  `generation_stopping` (stopping enhancement generation), and one
  `status_bar.*` key after `enhancement_generation_failed`:
  `enhancement_generation_stopped` (enhancement generation stopped). Its
  buttons reuse `dataforge_stop_btn` and `dataforge_background_btn`. In all
  11 languages, `at`-only (`ht` empty). Each takes its second paragraph word
  for word from its own `dataforge_running_body`, and its words for
  generating enhancements from `progress.generating_enhancements_title` and
  `status_bar.enhancement_generation_failed`. The pronoun follows the noun:
  Russian's "его" for the neuter "Извлечение" becomes "её" for the feminine
  "Генерация", while the French, Italian, Spanish, Portuguese and German
  nouns for the extraction and the generation are both feminine, so their
  pronouns stay. All 44 strings were back-translated and compared with the
  English in the same pass, not by a separate checker: no meaning errors,
  and the Korean sentence-spacing rule holds.
- **2.5.0 cycle (2026-10-16, Claude Opus 5.5):** #491 refuses a DataForge
  cache folder that is a link (a junction or a symbolic link made by hand,
  usually to keep the cache on another drive), because an extraction
  deletes nothing through a link and used to fail after unforge. One new
  key, after `extract.cache_folder_unusable`:
  `extract.cache_folder_is_link` (the DataForge cache folder `{folder}` is
  a link to another folder, it leads to `{target}`, Smart Citizen does not
  delete anything through a link, so the extraction did not start and
  nothing was changed, and the user can choose the folder it leads to as
  the DataForge cache folder in the Config tab and try again). `{folder}`
  and `{target}` each stand on a line of their own. In all 10 languages,
  `at`-only (`ht` empty), with each file's own names from the #494 entry
  below: the Config tab, the DataForge cache folder and the extraction. A
  link is each language's plain word for one (french lien, german Link,
  italian collegamento, spanish enlace, portuguese_br link, turkish
  bağlantı, japanese リンク, korean 링크, chinese 链接, chinese_traditional
  連結); german says Link, not Verknüpfung, which reads as a desktop
  shortcut. "It leads to" became the language's own way of naming where
  a link goes (japanese リンク先, korean 연결 대상, turkish Gittiği yer).
  chinese_traditional follows the chinese strings in Taiwan terms (透過 as
  in #490, and 連結 for a link). Each string was back-translated and compared with the
  English in the same pass, not by a separate checker: no meaning errors,
  and the Korean sentence-spacing rule holds. No human string changed.
  `tests/test_linked_cache_folder.py` checks every language's
  placeholders, the folder and the folder it leads to each on a line of
  their own, and this `ht`/`at` split.
  The same change adds an "Extraction says the DataForge cache folder is a
  link to another folder" line to Troubleshooting in `docs/HELP.md` and the
  10 translated `HELP.md` files, after #494's line, with each file's own
  names for the Config tab and the DataForge cache folder. It names a
  junction or a symbolic link in each language's Windows words (french
  jonction, german Verzeichnisverbindung, italian giunzione, spanish unión,
  portuguese_br junção, turkish bağlantı noktası with junction in brackets,
  japanese ジャンクション, korean 정션, chinese 目录联接, chinese_traditional
  目錄連接), back-translated the same way.
- **2.5.0 cycle (2026-10-15, Claude Opus 5.5):** #494 keeps a DataForge
  cache folder that Windows refuses, or one on a drive that is gone, from
  stopping Smart Citizen opening, and says so in one box where the folder
  is about to be made. Seven new keys. After
  `config.invalid_cache_folder_title`: `config.cache_folder_refused`
  (Windows denied Smart Citizen permission to create its cache in
  `{folder}`, and the DataForge cache folder was not changed),
  `config.cache_folder_unreachable` (Smart Citizen could not reach
  `{folder}`, and the folder was not changed),
  `config.cache_folder_unusable` (Smart Citizen could not use `{folder}`,
  then `{reason}`, and the folder was not changed) and
  `config.cache_folder_is_file` (the selected cache folder is a file, not a
  folder, which replaces English the Config tab had hard-coded). After
  `extract.folder_refused_fix`: `extract.cache_folder_refused` (Windows
  denied Smart Citizen permission to create the DataForge cache in
  `{folder}`, so the extraction did not start and nothing was changed),
  `extract.cache_folder_unreachable` (Smart Citizen could not reach the
  DataForge cache folder `{folder}`, the extraction did not start, and the
  user can reconnect the drive or choose another DataForge cache folder in
  the Config tab) and `extract.cache_folder_unusable` (Smart Citizen could
  not use the DataForge cache folder `{folder}`, then `{reason}`, so the
  extraction did not start and nothing was changed). The two `*_unusable`
  keys are for an error that is neither a refusal nor a folder that cannot
  be reached, such as a folder name Windows does not take or a path that
  runs through a file. `{reason}` is Windows' own reason (the error's
  `strerror`), which is already in the user's Windows language, so it is
  passed in as it is and never translated. `{folder}`, and `{reason}`
  where there is one, stand on a line of their own in each. The
  Config tab's refusal is followed by #490's `extract.folder_refused_fix`
  and the extraction's by `extract.folder_refused_fix_cache`, so no new
  advice was needed. In all 10 languages, `at`-only (`ht` empty), in each
  file's own register and its own names, as in the #490 entry below: the
  Config tab (`tabs.config`), the DataForge cache folder
  (`config.dataforge_cache_label`), a drive (as in the #482 strings:
  disque, Laufwerk, unità, unidad, unidade, sürücü, ドライブ, 드라이브,
  驱动器, 驅動器) and the extraction. "Could not reach" became "could not
  access" where that reads more naturally (french accéder, spanish acceder,
  portuguese_br acessar, japanese アクセス, korean 접근, chinese 访问,
  chinese_traditional 存取), and the Config tab's short version names what
  could not be reached (this folder, the following location) where the
  language needs an object. "Could not use" is each language's plain verb
  for using something (french utiliser, german verwenden, italian usare,
  spanish and portuguese_br usar, turkish kullanmak, japanese 使用, korean
  사용, chinese and chinese_traditional 使用). The Config tab's short
  version names what could not be used as its could-not-reach one does,
  and each `*_unusable` value ends with its file's own last sentence from
  `config.cache_folder_unreachable` or `extract.cache_folder_refused`. The
  "is a file" text follows each file's `config.invalid_data_folder_body`,
  saying folder where that one says directory, as the new English does.
  chinese_traditional was converted from the chinese strings with OpenCC
  `s2twp`, then given #490's Taiwan terms by hand: 權限, 安全性 and 存取
  (OpenCC gives 許可權, 安全中心 and 訪問); the two `*_unusable` values
  needed no hand fix. Each string was back-translated and compared with
  the English in the same pass, not by a separate checker: no meaning
  errors, and the Korean sentence-spacing rule holds. No human string
  changed. `tests/test_cache_folder_strings.py` checks every language's
  placeholders, the folder and the reason each on a line of its own, and
  this `ht`/`at` split.
  The same change adds a "Windows denied permission to create the
  DataForge cache, or Smart Citizen could not reach it" bullet to the
  Troubleshooting section of `docs/HELP.md` and the 10 translated
  `HELP.md` files, after #490's working folder one, worded from each
  language's own `*.cache_folder_*` strings and #490's bullet, with its
  `HELP.md`'s own names for the Config tab, the DataForge cache folder and
  the Enhancements tab, and back-translated in the same pass. The bullet
  does not cover the two `*_unusable` boxes, which carry Windows' own
  reason, and was left as it was when they were added.
- **2.5.0 cycle (2026-10-15, Claude Opus 5.5):** #416 added a *Starter
  blueprints* bullet to the Blueprint Tracker section of each `HELP.md`, just
  before the "which servers the scan reads" bullet: every player owns the
  P4-AR Rifle, the S-38 Pistol, their magazines and the four Field Recon Suit
  pieces, the tracker lists them under the mission label *Default blueprint
  (every player has it)*, and the first scan after updating adds them to the
  owned list once. In all 10 languages, AI translation, using each file's own
  words for the two lists and the scan. The label stays in English because
  the app shows it untranslated (like *Limited time event reward*), and the
  item names stay as the game data writes them. No `ui.json` key changed. A
  separate checker back-translated every bullet and compared it with the
  English and with each file's own terms: chinese, chinese_traditional,
  french, german, portuguese_br and spanish needed nothing. Five wording fixes
  followed: korean and japanese read as "the game offers no mission", so the
  mission is now the subject ("이를 제공하는 임무도 없으므로", "これらを提供するミッションもないため"),
  korean uses the file's usual 레이블 for "label", turkish says "üretim
  cihazından" (the pack uses "üretici" for a manufacturer) and "mevcut
  listeye", and italian says "la loro ricezione" instead of "di averli
  ricevuti", which made the game the receiver.
- **2.5.0 cycle (2026-10-15, Claude Opus 5.5):** #492 added
  `enhancements.tag_mapping_tooltip_weight` (the Edit mapping tooltip on the
  Tag Builder's Armor > Weight row) and reworded `enhancements.cat_desc_gear`.
  AI `at` for the new key in all ten languages, styled on each file's
  `tag_mapping_tooltip_type`. `cat_desc_gear`'s `at` refreshed in the seven
  AI-only languages and in french and portuguese_br; spanish's `at` was
  empty and stays empty. The guided tour's Tag Builder step
  (`tutorial.enh_tag_builder.description`, English in
  `assets/tutorial.json`) now lists armor too; its `at` was updated in all
  ten languages, none of which has a human `ht` for it. Armor tags in mission
  POTENTIAL BLUEPRINTS lists reworded `enhancements.annotate_mission_descs_cb`
  and `enhancements.annotate_mission_descs_tooltip`: AI `at` refreshed for
  both in all ten languages, except spanish's empty checkbox `at` beside its
  human `ht`. The #492 review then reworded `enhancements.desc`,
  `enhancements.tag_builder_desc`, `enhancements.reset_tag_tooltip` and
  `enhancements.tag_enabled_tooltip` (they listed only components, missiles
  and ship weapons) and shortened `annotate_mission_descs_tooltip`: AI `at`
  refreshed in all ten languages except the empty spanish `at` beside its
  human `desc` and `tag_builder_desc`. The #492 re-review then made
  `reset_tag_tooltip` name the one exception (the Mission Titles tab's
  General Tags save at once, so Reset restores them straight away) and
  dropped the "not with None brackets" clause from
  `annotate_mission_descs_tooltip`, since the Armor tab no longer offers None
  brackets: AI `at` refreshed for both in all ten languages (neither has a
  human `ht` anywhere; "Mission Titles" stays English as the tab label does,
  "General Tags" uses each file's own `mt_general_tags_group`). No human `ht`
  was touched. The translated `HELP.md` and `ABOUT.md` copies do not mention
  the Armor tab yet and are left for the pre-release docs sync.
- **2.5.0 cycle (2026-10-13, Claude Opus 5.5):** #490 stops an extraction
  whose working folder Windows refuses, with a message, instead of retrying
  for hours. Three new keys after `extract.size_mb`:
  `extract.folder_refused` (Windows denied Smart Citizen permission to
  create a working folder in `{folder}`, which stands on a line of its own,
  and nothing was changed), `extract.folder_refused_fix_cache` (check that
  folder's permissions, allow Smart Citizen through Controlled folder
  access in Windows Security, or choose another DataForge cache folder in
  the Config tab, then try again) and `extract.folder_refused_fix` (the
  same without the cache folder, for `%TEMP%`). In all 10 languages,
  `at`-only (`ht` empty), in each file's own register (as its #482 strings:
  du in german, tu in italian and spanish, vous in french, the polite forms
  elsewhere) and its own names for the Config tab (`tabs.config`), the
  DataForge cache folder and the extraction. Windows Security, Controlled
  folder access and a folder's permissions use Microsoft's names in each
  language, so the user can find them in Windows: french Sécurité Windows,
  Accès contrôlé aux dossiers, autorisations; german Windows-Sicherheit,
  überwachter Ordnerzugriff, Berechtigungen (the older AI text in
  `apply.cannot_save_edits_body` says Ordnerzugriffssteuerung and was left
  as it is); italian Sicurezza di Windows, accesso controllato alle
  cartelle, autorizzazioni; spanish Seguridad de Windows, acceso controlado
  a carpetas, permisos; portuguese_br Segurança do Windows, Acesso
  controlado a pastas, permissões; turkish Windows Güvenliği, Denetimli
  klasör erişimi, izinler; japanese Windows セキュリティ, アクセス許可;
  korean Windows 보안, 제어된 폴더 액세스, 권한; chinese Windows 安全中心,
  权限. japanese コントロールされたフォルダーアクセス and chinese
  受控文件夹访问 are spelt as in each file's `apply.cannot_save_edits_body`.
  chinese_traditional was converted from the chinese strings with OpenCC
  `s2twp`, as in #403 and #482, then given Taiwan's terms by hand:
  Windows 安全性, 受控資料夾存取 and 權限 (OpenCC gives 安全中心, 受控資料夾訪問
  and 許可權). The italian and chinese_traditional names for Controlled
  folder access follow Microsoft's documentation and were not checked
  against a Windows in that language. Each string was back-translated and
  compared with the English in the same pass, not by a separate checker: no
  meaning errors, and the Korean sentence-spacing rule holds. No human
  string changed. `tests/test_folder_refused_strings.py` checks every
  language's placeholders and this `ht`/`at` split.
  The same change adds an "Extraction says Windows denied permission to
  create a working folder" bullet to the Troubleshooting section of
  `docs/HELP.md` and the 10 translated `HELP.md` files, after the
  not-enough-free-space one, worded from each language's own
  `extract.folder_refused*` strings and its `HELP.md`'s own names for the
  Config tab and the DataForge cache folder, and back-translated in the
  same pass.
  A fourth key followed on 2026-10-16, after `extract.folder_refused_fix`:
  `extract.folder_unusable` (Smart Citizen could not use a working folder in
  `{folder}`, then Windows' own reason as `{reason}`, each on a line of its
  own, and nothing was changed), for a drive Windows will not write to
  (write-protected, failing, or a file in the way held by another program),
  which is not a matter of permissions. `{reason}` is Windows' own text,
  already in the user's Windows language, and is never translated. In all
  10 languages, `at`-only (`ht` empty), with each file's own words for a
  working folder from its `extract.folder_refused` and its closing sentence
  from the same string, back-translated in the same pass. No human string
  changed, and no `HELP.md` change: the message carries its own reason.
- **2.5.0 cycle (2026-10-13, Claude Opus 5.5):** #482 checks free space
  before a P4K extraction. Ten new keys: the not-enough-space messages
  `extract.no_space_dataforge`, `no_space_global_ini`, `no_space_drive`,
  `no_space_fix_cache`, `no_space_fix_temp`, `no_space_fix` and
  `no_space_cache_incomplete`, the size templates `extract.size_gb` and
  `size_mb` (all nine after `extract.dataforge_timeout`), and
  `progress.reloading_with_extracted_base` (the progress text after a
  global.ini extraction, English-only in the code until now), after
  `progress.reloading_after_user_ini_restore`. In all 10 languages,
  `at`-only (`ht` empty), in each file's own register and terms, with every
  placeholder kept and the line breaks where the English has them. The
  Config tab is named with each file's own `tabs.config` (french
  Paramètres, german Konfiguration, italian and portuguese_br Config,
  spanish Configuración, turkish Yapılandırma, japanese 設定, korean 설정,
  chinese and chinese_traditional 配置) and the folder with its
  `config.dataforge_cache_label`. `{drive}` is a label such as `D:` or a
  network share, so it carries no particle in korean and no case suffix in
  turkish. The size templates own the decimal mark and the unit: a decimal
  comma in french (`Go`, `Mo`), german, italian, portuguese_br, spanish and
  turkish, and no space before the unit in korean.
  Also reworded `config.cache_dir_tooltip` in all 10 languages to match the
  new English: the cache is about 1.2 GB (it said ~1.4 GB), and two new
  sentences say an extraction needs up to about 4.5 GB free on that drive
  while it runs and when its working files go to `%TEMP%` instead. No
  language had an `ht` there. The figure in `config.data_desc` went from
  1.4 to 1.2 GB in the seven AI-only languages. french, portuguese_br and
  spanish have a human `ht` there, which was left alone (see *Needs human
  re-review*). chinese_traditional was converted from the chinese strings
  with OpenCC `s2twp`, as in #403, and checked by hand. Each string was
  back-translated and compared with the English in the same pass, not by a
  separate checker: no meaning errors, and the Korean sentence-spacing rule
  holds. No human string changed.
  The same change updated `docs/HELP.md` and the 10 translated `HELP.md`
  files. In the Config Tab's *DataForge cache folder* bullet, the "about
  2 GB of working space" sentence now says an extraction needs up to about
  4.5 GB free while it runs (less when a cache is already there), keeps the
  `%TEMP%` fallback cases, and says it stops before it starts when there is
  not enough room. Troubleshooting gained an "Extraction says there is not
  enough free space" bullet after the locked Data.p4k one. Each file writes
  the figure its own way (french 4,5 Go, german, italian, portuguese_br,
  spanish and turkish 4,5 GB, and korean "4.5 GB" with a space, as its HELP
  already wrote "2 GB"). Bold labels reuse each file's own *DataForge cache
  folder* label and the Config Tab name its other Troubleshooting bullets
  use, which for italian ("scheda Configurazione") and japanese ("Config
  タブ") is the section heading rather than `tabs.config`. The new bullet
  uses the separator the rest of each list uses. In chinese,
  chinese_traditional, german, italian and japanese the older locked
  Data.p4k bullet uses a colon instead (left as it was). The cache bullet
  was AI text from the 2026-10-06 docs sync and every translated `HELP.md`
  is AI-only, so no human text changed and nothing needs human re-review.
  Korean keeps a space after every sentence end. HELP files have no
  `ht`/`at` split, so this log is their only record.
- **2.5.0 cycle (2026-10-12, Claude Opus 5.5):** #476: a generation cut off by
  closing the app, a crash or a failed write is now offered again at the next
  start, and that question has its own body, `extract.outdated_categories_body`
  ("out of date", with no count, because the count's noun keys say "missing"
  in several languages). It sits right after `extract.missing_category_label`.
  In all 10 languages, `at`-only (`ht` empty), worded in that file's own
  register and with its existing words for enhancements and for generating
  them (german "erzeugen", like the rest of its `extract.*` block). The
  newlines sit where the English has them. The second and third lines are
  that file's own from `extract.missing_categories_body`, word for word,
  except french: "Sélectionnez ceux à générer" (the enhancements) where the
  missing body's "celles" stands for the categories it names. "Out of date"
  follows the file's word for an outdated DataForge cache where one fits
  (chinese 已过期, german veraltet, japanese 古くなっています, portuguese_br
  desatualizados, turkish güncel değil). Each string was back-translated and
  compared with the English in the same pass, not by a separate checker: no
  meaning errors, and the Korean sentence-spacing rule holds. No existing
  string changed. Russian, added later in 2.5.0 (#514), got the same key when
  this was merged with it (2026-10-21), `at`-only, its second and third lines
  taken from its own `extract.missing_categories_body`, back-translated with
  no meaning errors.
- **2.4.0 pre-release (2026-10-06, Claude Opus 5.5):** in-app docs brought
  current with English after the pre-release docs sync. In all 10 languages:
  `HELP.md`'s Config Tab data-folder bullet no longer claims the DataForge
  extraction, plus a new *DataForge cache folder* bullet (default
  `%LOCALAPPDATA%`, the ~2 GB extraction work beside it since #471); `ABOUT.md`
  gained the *Verify Install Location* feature line (#385) and the startup
  auto-scan clause on the Blueprint Tracker line (#386). Eight languages (all
  but korean and turkish) gained the Blueprint Tracker "hover any blueprint"
  bullet. korean, turkish and chinese_traditional, translated earlier this
  cycle from an older English, also gained the two auto-scan bullets, the
  Verify Install Location bullet, the "Apply says it worked but the game
  looks unchanged" troubleshooting entry and missing Supporters lines, and got
  a full parity pass (language lists, the Export Settings defaults sentence,
  the current PayPal link). Bold UI labels use each file's own `ui.json`
  strings. All AI translation; no human text existed in these docs.
- **2.4.0 cycle (2026-10-06, Claude Opus 5.5):** #471 added seven `extract.*`
  keys. Five are for a running DataForge extraction: `dataforge_running_title`,
  `dataforge_running_body` and `dataforge_stop_btn` (the Stop / Cancel
  question Esc or the X on the extraction dialog now asks) and the
  status-bar `dataforge_stopping` and `dataforge_stopped`. The three question
  keys replaced a Yes/No pair (`dataforge_stop_title`, `dataforge_stop_body`)
  during the review, before any release. A Run in Background button
  (`dataforge_background_btn`) came and went in the same review, and the
  body was translated again without it. The other two, `p4k_stopping` and `p4k_stopped`, are
  the status bar's global.ini counterparts, shown when Esc or the X on the
  P4K Extraction dialog stops that extraction.
  In all 10 languages, `at`-only (`ht` empty), each worded in that file's own
  register and with its existing name for the DataForge extraction (the
  `p4k_*` pair mirrors that file's DataForge pair
  and keeps `global.ini` as written). A separate checker back-translated
  every string and compared it with the English (again after the
  two-button rewording, and for the `p4k_*` pair): no meaning errors,
  register and terms matched each file, and the Korean sentence-spacing
  rule holds. No existing string changed.
- **2.4.0 cycle (2026-10-04, Claude Sonnet 5.5):** #446 removed the Blueprint
  Tracker's "Also scan LIVE/HOTFIX" tickbox. Scan Logs now always reads LIVE,
  plus HOTFIX when it is installed, and never PTU, EPTU or TECH-PREVIEW. In
  all 10 languages: removed `blueprint_tracker.scan_other_channels_checkbox`
  and `blueprint_tracker.scan_other_channels_tooltip`, reworded
  `blueprint_tracker.scan_logs_tooltip` (the existing first sentence is kept
  word for word and one new sentence follows it), added
  `enhancements.bp_scan_no_live_hotfix`, and replaced the old LIVE/HOTFIX
  bullet in each `HELP.md` with a "which servers the scan reads" bullet. All
  `at`-only (`ht` empty). None of the replaced strings had a human `ht`, so no
  human translation was overwritten. Each language was translated by its own
  agent, then back-translated and compared with the English by a separate
  checker (no meaning errors). Four wording fixes followed the check: korean
  got the word for "never" back in the dialog and the Help bullet, spanish
  says "se reinician" instead of "se borran" in the Help bullet (which could
  read as the servers being deleted), japanese got the "because" back in the
  Help sentence, and chinese_traditional uses 帳號 instead of 賬號. After the
  hand test the tooltip was cut to two lines: the existing first sentence and
  a short second line (LIVE, plus HOTFIX when installed, because the two share
  a server and account progression). The English second line dropped "too" and
  "one", and the other ten languages keep their existing second line, which
  says the same. The sentences about the test servers never being scanned and
  about the Config tab make no difference now live only in the Help bullet and
  the dialog.
  For a native reviewer: most old texts called PTU, EPTU and TECH-PREVIEW "test
  builds", and the new texts say "test servers" because the English now does
  (turkish "sunucu" where the old text said "test sürümleri" is the clearest
  case). "Wiped" is rendered as: chinese 清档, chinese_traditional 重置, french
  réinitialisés, german zurückgesetzt, italian azzerati, japanese
  データがより頻繁に消去される, korean 초기화 (the game slang 와이프 is an
  alternative), portuguese_br zerados, spanish se reinician, turkish
  sıfırlanan. Each new text names the Config tab with that language's own
  `tabs.config` label. Older strings in french, italian, japanese and spanish
  call the same tab by a different name (left as they were). Two splits come
  from the old text: german "Kontofortschritt" (tooltip) against
  "Konto-Progression" (Help), and japanese アカウント進捗 against アカウント進行.

- **2.4.0 cycle (2026-10-02, Claude Opus 5.5):** #398 follow-up reworded the
  English `simple_mode.generate_apply_tip_disabled` (the green Simple-mode
  button's tooltip) from "nothing has changed since the last time you
  applied" to say the game matches the current settings and that a click
  still regenerates and re-applies, for example after a game patch. The
  button stays clickable when green, and the check compares the game file
  with the current settings rather than tracking changes. Refreshed the `at`
  in all 10 other languages to match. No language had an `ht` for this key,
  so nothing needs human re-review. The Advanced-mode green tooltip
  `toolbar.apply_disabled_tooltip` got the same reword in English, without
  the click hint (that button is disabled while green), and its `at` was
  refreshed in the 10 other languages (Claude Sonnet 5.5), again with no `ht`
  to protect. The same change added one sentence to
  `docs/HELP.md` and the 10 translated `HELP.md` files (Claude Sonnet 5.5):
  restoring a backup or clearing the localization turns the Apply button
  red, but closing afterwards does not ask. The translations are AI-written,
  styled on each file's existing register, and each names the action with
  that language's own menu label. HELP files have no `ht`/`at` split, so
  this log is their only record.
- **2.4.0 cycle (2026-10-01, Claude Sonnet 5):** Merged `release/2.4.0` into
  Korean's PR branch (#409) and backfilled the 50 English keys that had
  landed since Korean's own translation pass: the duplicate-install-detection
  feature's 44 `config.dupe_*` keys and the blueprint auto-scan feature's 6
  `blueprint_tracker.auto_scan_*` / `scan_logs_already_running_tooltip` keys.
  All `at`-only, styled on Korean's existing formal register. One further key
  (`simple_mode.generate_apply_tip_disabled`) was still on an unmerged PR at
  backfill time. Its Korean `at` was added later on #409's branch (1f22a15),
  after #398's still-unmerged branch had been merged into it. #398 and then
  #409 merged minutes later.
  Also added `config.map_language_overwrite_warning` (new #409-follow-up
  guard against mapping a language's own apply target as its source) across
  all 10 languages, backfilled turkish's own missing `dialogs.language_copying`
  (added by Korean's original pass before turkish existed, #404 never saw
  it), and refreshed the stale URL-only `at` text on the 4 keys above for
  french, portuguese_br, japanese, chinese, italian, german, and turkish
  (Spanish's human `ht` is untouched, per the note above; its one AT-only key
  among the four, `map_language_tooltip`, was refreshed too).
- **2.4.0 cycle (2026-10-01, Claude Sonnet 5):** Merged `release/2.4.0` into
  Traditional Chinese's PR branch (#407) and backfilled the real missing-key
  gap it exposed (the same duplicate-install-detection and blueprint
  auto-scan keys Korean's #409 needed, measured fresh rather than reused from
  that count since the two branches diverged from different points).
  Renumbered the installer's `LanguageIndex` from 8 to 10: Turkish (#404)
  had already merged upstream and claimed 8, which this PR's original index
  assumed was free, and Korean (#409) merged first and took 9. Dropped the hardcoded
  "(67.3%)" from `_LANGUAGE_COMBO_LABEL_OVERRIDES` and installer.iss's
  `Chinese (Traditional)` — unified on **"Traditional Chinese"** in both per
  the review: a hand-measured percentage goes stale the moment the English
  key set changes, and the two files had drifted to different names for the
  same language. Reverted an unnecessary realignment of the whole
  `SC_LANGUAGE_IDS` dict (the original PR widened every column to fit the
  new key, which only grows future merge-conflict surface for no behavioral
  benefit) back to the existing narrow alignment, appending the new entry
  as the review asked.
  On merging after Korean (#409), added the 3 keys that had landed since
  (`simple_mode.generate_apply_tip_disabled`, `config.map_language_overwrite_warning`,
  `dialogs.language_copying`) and refreshed the 4 reworded Map Language File
  keys from URL-only to URL-or-local-file text, converted from chinese.
- **2.4.0 cycle (2026-09-10, Claude Sonnet 5):** New language **korean** added
  (#367), shipped as bring-your-own-file rather than with a bundled source.
  Full AI translation of all 668 `ui.json` keys plus the 19-step guided tour
  (`tutorial.*`), all `at`-only (`ht` empty). Translated `HELP.md`, `ABOUT.md`,
  `LEGAL.md`, and `FAQ.md`. Unlike every other language here, `sources.json`
  carries no URL for Korean (deliberately blank, with a comment explaining
  why) — the Star Citizen Korean Localization Project (스타 시티즌 유저
  한국어 프로젝트, run by the Shatagon/MGM Star Fleet/Falco Rescue guilds at
  sc.galaxyhub.kr) licenses their `global.ini` for non-redistribution: it can
  only be downloaded through their own patcher with a daily Discord-issued
  access code. `SC_LANGUAGE_IDS["korean"] = "korean_(south_korea)"`, one of
  the twelve official CIG Localization slots (confirmed via the community's
  own installation guides, since Korean — unlike Turkish in the parallel
  #404 work this cycle — has a real dedicated slot and needs no borrowing).
  installer `LanguageChoicePage` gained a Korean option.

  This is the first language to exercise **Map Language File**'s new
  local-file support, added alongside it: `LanguageBaseDownloadWorker`
  (`src/gui/workers.py`) now detects whether its mapped source is an
  `http(s)://` URL (downloaded, freshness-checked, same as every other
  language) or a local file path (copied via `shutil.copy2`, no network
  round trip), and the *Map Language File* dialog (`config_tab.py`) gained a
  per-row **Browse...** button so a user doesn't have to hand-type a Windows
  path. `AppSettings.get_language_base_url()`'s docstring and the relevant
  `ui.json` strings (`config.map_language_desc`, `config.map_language_tooltip`,
  `dialogs.language_no_url`, `dialogs.language_download_failed`) were
  reworded from URL-specific to source-agnostic language; a new
  `dialogs.language_copying` key covers the copy-in-progress dialog title a
  local source shows in place of "Downloading...". All 7 other languages
  gained an AI `at`-only backfill for that one new key so their
  key-universe tests stay green. Locked by `tests/test_korean_activation.py`.
- **2.4.0 cycle (2026-09-08, Claude Sonnet 5):** New language **chinese_traditional** added (#403). Unlike every prior AI-translated language, which independently translated the full English `ui.json` from scratch, this one was generated by converting the existing **chinese** (Simplified) translation to Traditional Chinese via OpenCC's `s2twp` config (Taiwan standard, phrase-aware — not a bare character swap: `软件`→`軟體`, `服务器`→`伺服器`, `文件`→`檔案`, not just `软`→`軟` etc.), since chinese's docs were confirmed section-for-section current with English first (`## ` header counts matched exactly across `HELP.md`/`ABOUT.md`/`LEGAL.md`/`FAQ.md`). All 668 `ui.json` keys plus the 19-step guided tour (`tutorial.*`) converted this way, all `at`-only (`ht` empty) since chinese itself has no `ht` strings yet either. Spot-checked two of the classic Simplified→Traditional ambiguous-character cases across every converted file: `后` (after) vs `后` (empress) — all 56 instances converted correctly to `後`; `并` (and) vs `合并` (merge) — 35 of 36 correct, one genuine miss found and fixed by hand (`并为` "and, for" was rendered `併為`, the "merge" reading, instead of `並為`, the conjunction reading — three occurrences across `ui.json` and `HELP.md`). Base `global.ini` sourced from **Orbit-Startech/StarCitizen-TCTP** (`chinese_(traditional)/global.ini`, GPL-3.0, verified HTTP 200 at wiring time); `SC_LANGUAGE_IDS["chinese_traditional"] = "chinese_(traditional)"`; installer `LanguageChoicePage` gained a "Traditional Chinese" option (index 10 as of the 2026-10-01 follow-up above; originally wired as index 8). **Known, permanent coverage gap**: the source hasn't updated since May 2024 and covered only 67.3% of the English key set measured at issue-filing time — about a third of in-game strings fall back to English, a fraction that only grows as English gains keys. Originally flagged with a hardcoded percentage in the language selector; the 2026-10-01 follow-up above dropped the number (it could only go stale) in favor of just the corrected name. A Traditional-Chinese-speaking reviewer replacing the `at` strings with `ht` (and, ideally, finding a more current source) is the next step.
- **2.4.0 (2026-09-08, Claude Fable 5.1):** New language **turkish** added
  (#404). Full AI translation of all 668 UI keys plus the 19-step guided
  tour (`tutorial.*`), all `at`-only (`ht` empty). Translated `HELP.md`,
  `ABOUT.md`, `LEGAL.md`, and `FAQ.md`. Base `global.ini` mapped to
  Dymerz/StarCitizen-Localization
  (`data/Localization/turkish_(turkey)/global.ini`, 95% key coverage
  against the current English file) in `sources.json`, the same source
  repo already used for french, portuguese_br, and italian. **Turkish
  borrows the game's `polish_(poland)` slot**:
  `SC_LANGUAGE_IDS["turkish"] = "polish_(poland)"`. `turkish_(turkey)` is
  not a `g_language` value the game accepts, so Turkish has to ride on an
  official slot; Polish is unclaimed by our own languages and needs the
  same Latin Extended-A block Turkish does (ł ą ę ż ź ć ń ś vs ğ ı İ ş),
  so the game font already draws our glyphs. `russian_(russia)` was tried
  first and rejected — the game does not recognise it. Dymerz's own guide
  maps Turkish onto `german_(germany)`, which would collide with our
  German language. Installer `LanguageChoicePage` gained a Turkish option.
  The seven other translated `ABOUT.md` files gained Turkish in both the
  Dymerz credit line and the *Multi-Language Support* bullet, so all nine
  language lists agree. Locked by `tests/test_turkish_activation.py`.

- **2.3.1 pre-release (2026-08-28, Claude Opus 5):** `ABOUT.md` docs-parity
  follow-up to the `HELP.md` sweep below — the window-layout work (#364) was
  described in Help but had no entry in the in-app About feature list, so the
  English list gained a **Flexible Window & Columns** bullet and all 7
  translated `ABOUT.md` files gained the matching bullet in the same position
  (Core Features, before the guided-tutorial entry). Each translation quotes
  that language's own **Reset Window Proportions** menu string verbatim from
  its `ui.json` (`toolbar.menu_reset_window_proportions`) and reuses the
  More-menu phrasing already established in its `HELP.md`, so the doc and the
  running app cannot disagree. Verified programmatically: exactly one bullet
  per file, each containing that language's exact menu string. AI translations
  styled on each file's existing register; no `ht` strings were touched, since
  these are documents rather than `ui.json` keys.

- **2.3.1 cycle (2026-08-27, Claude Opus 5):** `HELP.md` docs-parity for the
  window-layout work (#364), across all 7 translated languages. Per language:
  the resizable-columns bullet in section 2, a new **Window Layout** section
  covering persisted window/dock/column state and **Reset Window Proportions**,
  and section 13's machine-specific-exclusions list extended to name the
  String Editor column widths (which Export Settings deliberately leaves out).
  AI translations styled on each file's existing register; no `ht` strings were
  touched, since these are documents rather than `ui.json` keys.
- **2.3.0 pre-release (2026-08-02, Claude Fable 5):** Full docs-parity sweep
  for all 7 languages, bringing every `HELP.md` and `ABOUT.md` up to the
  English originals at the 2.3.0 pre-release gate. Per language: the new
  HELP section 13 (Export / Import Settings, #311) with renumbering of the
  following sections to 14/15/16; the Blueprint Tracker additions (scan
  LIVE/HOTFIX #268, rescan-all #308, export/import owned blueprints #336,
  Ammo in the Type filter example #249); the Ship Favorites name-row rules
  and the Ship/Vehicle Names Only filter (#329); the RS ore-name bullet and
  Mission Details field-list rework with the General Tags `[BP]`/`[BP?]`
  explanation (#331, #341); the commodities Tag Builder defaults (#325);
  the Config Tab Export/Import entry and the locked-Data.p4k
  troubleshooting bullet (#303); ABOUT's eight-language list, source
  credits (incl. correcting Spanish to Thord82/Star_citizen_ES, which
  `sources.json` actually pulls from, in English and all translations),
  Settings Backup and blueprint export/import mentions. japanese and
  german additionally caught up on Known Issues, the own-line watermark
  wording (#304), and ABOUT's Video Guides section; german's literal
  `[Besessen]` code spans were corrected to the in-game `[Owned]` token.
  Also filled `extract.p4k_locked` (`at` only) for french, spanish, and
  portuguese_br (#303 stubs). All new text is AI, `at`-only / prose-only,
  flagged for the language leads per the policy below.
- **2.3.0 cycle (2026-08-01, Claude Fable 5):** Corrected the french, spanish,
  and portuguese_br AI strings for the #311 Settings Backup feature (the
  `settings_backup.*` and `config.backup*`/`config.*_settings_*` keys). Two
  fixes: the import-confirm dialog pointed users at the Reset user.ini button
  ("Réinitialiser"/"Restablecer"/"Redefinir") where English references
  Restore user.ini (now "Restaurer"/"Restaurar"/"Restaurar", matching each
  file's own `config.restore_user_ini_btn`), and the whole key set shipped
  without diacritics ("parametres", "configuracoes"), inconsistent with the
  rest of those files. All corrected strings stay `at`-only, `ht: ""`.
- **2.2.1 pre-release (2026-07-18, Claude Fable 5):** AI backfill of the 215
  keys the #247 hardcoded-string sweep added in English only (Tag Builder
  tooltips and labels, Mission Titles page, mission detail fields, the Import
  INI flow, OneDrive warnings, user.ini restore/reset dialogs, DataForge
  extraction prompts, status-bar messages, String Editor context menu, and the
  Test Plan panel). french, portuguese_br, and spanish each gained the same
  215 `at`-only keys, styled on each file's existing human strings ("
  enrichissements/étiquettes", "aprimoramentos/tags", "mejoras/etiquetas").
  The `{plural}` placeholder was deliberately dropped where suffix-plurals
  don't work in the target language (str.format ignores unused kwargs). All
  new strings are `ht: ""` so translators can find them the usual way.
- **2.3.0 cycle (2026-07-18, Claude Fable 5):** AI backfill of two doc sections
  that landed in English after the initial #248 backfill below: the "Known
  Issues" / "Problèmes connus" / "Problemas Conhecidos" / "Problemas
  conocidos" entry for the #281 fuel-nozzle-name bug (in `HELP.md`, all three
  languages, including a small broadening of the section's intro paragraph
  to match the English edit), and a "Video Guides" section crediting
  Karolinger's community overview video (in `ABOUT.md`, all three
  languages). Same AI-styled-on-existing-human-strings approach and the
  same review flag as the entry below.
- **2.3.0 cycle (2026-07-17, Claude Sonnet 5):** AI backfill of the in-app docs
  (#248). french and portuguese_br `HELP.md`/`ABOUT.md` gained the 2.2.0
  sections they were missing (Simple & Advanced mode, dirty-state button
  colors + Unapplied Changes prompt, App Updates, Blueprint Tracker tab,
  Mission Titles, FAQ tab, medical consumables, RS tags/rep-track XP, Restore
  user.ini, credits updates); their `LEGAL.md` was already current. spanish
  gained its first `HELP.md`/`ABOUT.md`/`LEGAL.md`, translated in full from
  the English originals using Thord82's ui.json terminology (Mejoras,
  Rastreador de blueprints, Aplicar mejoras, …). All of it is AI text styled
  on the existing human ui.json strings — flagged for review by the language
  leads (Akwa/Ishikudeska for french, Nxzzin for portuguese_br, Thord82 for
  spanish) per the policy below; button names in the docs follow what the
  translated UI actually shows today, including french's stale
  `apply_tag_changes_btn` (see *Needs human re-review*).
- **2.3.0 cycle (2026-07-24, Claude Sonnet 5):** Full AI translation for the new
  **italian** language (#298). All 376 `ui.json` keys plus the full 19-step
  `tutorial.*` guided tour (38 keys) translated to Italian, `ht: ""` / `at:
  "<translation>"` throughout — there is no human translator yet, so every
  key is a review candidate (grep `"ht": ""` finds all of it). `HELP.md`,
  `ABOUT.md`, `LEGAL.md`, and `FAQ.md` translated in full from the English
  originals. The base `global.ini` for Italian is sourced from
  `Dymerz/StarCitizen-Localization`
  (`data/Localization/italian_(italy)/global.ini`), the same source repo
  already used for french and portuguese_br. Italian writes to the game's
  `italian_(italy)` Localization folder with `g_language = italian_(italy)`
  (`SC_LANGUAGE_IDS`). Also added Italian to the installer's
  `LanguageChoicePage` (`installer.iss`) as the 5th option.
- **2.3.0 (2026-07-25, Claude Sonnet 5):** New language **chinese** added
  (#300). Full AI translation of all 376 UI keys plus the 19-step guided tour
  (`tutorial.*`), all `at`-only (`ht` empty). Translated `HELP.md`,
  `ABOUT.md`, `LEGAL.md`, and `FAQ.md`. Base `global.ini` mapped to
  [42Kit](https://ini.42kit.com/full/global.ini) (a Simplified Chinese
  community translation — confirmed by character form, e.g. 开 not 開) in
  `sources.json`; `SC_LANGUAGE_IDS["chinese"] = "chinese_(simplified)"`;
  installer `LanguageChoicePage` gained a Chinese option. Unlike the other
  community sources, Star Citizen has no official Chinese localization
  folder shipped by CIG — 42Kit's file is meant as a full replacement for
  the game's English strings — but `chinese_(simplified)` /
  `chinese_(traditional)` are both documented, working `g_language` /
  Localization-folder values via the community, so Chinese follows the same
  per-language-folder pattern as every other language here rather than
  overwriting the `english` folder. Also fixed `download_file_if_changed`
  (`src/utils/updater.py`) sending no `User-Agent`, which 42Kit's host
  rejects with an HTTP 403 (GitHub-raw-hosted sources never hit this since
  GitHub doesn't check). Locked by `tests/test_chinese_activation.py`.
- **2.3.0 (2026-07-24, Claude Fable 5):** New language **japanese** added (#301).
  Full AI translation of all 376 UI keys plus the 19-step guided tour
  (`tutorial.*`), all `at`-only (`ht` empty). Translated `HELP.md`, `ABOUT.md`,
  and `LEGAL.md` (the latter carries the standard "English version is
  authoritative" caveat). Base `global.ini` mapped to
  stdblue/StarCitizenJapaneseResources in `sources.json`;
  `SC_LANGUAGE_IDS["japanese"] = "japanese_(japan)"`; installer
  `LanguageChoicePage` gained a Japanese option. Locked by
  `tests/test_japanese_activation.py`.
- **2.3.0 cycle (2026-08-01, Claude Sonnet 5):** AI translation of `FAQ.md`
  for **japanese**. The original #301 PR translated `HELP.md`/`ABOUT.md`/
  `LEGAL.md` but missed `FAQ.md` (unlike italian and chinese, which both
  shipped it from day one), so `get_localized_doc_path` was silently
  falling back to the English FAQ tab. Found while portable-testing the
  #306 fix above. Styled on the existing `HELP.md`/`ABOUT.md` terminology
  (more menu, apply/restore/clear-localization action names) and register
  (polite desu/masu form, matching the rest of the Japanese docs). Locked
  by `tests/test_language_paths.py::TestIssue306FaqBackfill` (japanese
  folded into the #306 parametrize on merge).
- **2.3.0 cycle (2026-08-01, Claude Fable 5):** German top-up of the 45 keys
  added in English by the 2.3.0 feature PRs that merged after German landed
  (#272, #310, #332, #303, #311, #330). Translations taken verbatim from the
  author's German backfill branch (PR #338), merged early in scoped form
  because the German coverage test was red mid-cycle; #338 remains open for
  the keys that depend on the still-open #336. All `at`-only, `ht: ""`.
- **2.3.0 cycle (2026-08-01, Claude Sonnet 5):** AI translation of `FAQ.md`
  for **french**, **spanish**, and **portuguese_br** (#306). `docs/FAQ.md`
  (#152) landed after these three languages' initial doc translation work
  (the #248 backfill above covers `HELP.md`/`ABOUT.md`/`LEGAL.md` only), so
  `get_localized_doc_path` had been silently falling back to the English FAQ
  tab for all three ever since. italian and chinese both shipped a
  translated `FAQ.md` from day one; this closes the gap for the three
  languages that predate #152 (japanese also missed it, tracked and fixed
  separately since it wasn't part of #306's original scope). Styled on each
  file's existing
  human `HELP.md`/`ABOUT.md` terminology (french: "Effacer la localisation"
  / "Restaurer une sauvegarde"; spanish: "Limpiar localización" / "Restaurar
  copia"; portuguese_br: "Limpar Localização" / "Restaurar Backup") and
  register (french *vous*, spanish *tú*, portuguese_br *você*), matching
  what the translated UI actually shows today. Flagged for review by the
  language leads (Akwa/Ishikudeska for french, Nxzzin for portuguese_br,
  Thord82 for spanish) per the policy below. Locked by
  `tests/test_language_paths.py::TestIssue306FaqBackfill`.
- **2.3.0 (2026-07-25, Claude Sonnet 5):** New language **german** added (#299).
  Full AI translation of all 376 UI keys plus the 19-step guided tour
  (`tutorial.*`), all `at`-only (`ht` empty). Translated `HELP.md`, `ABOUT.md`,
  `LEGAL.md`, and `FAQ.md`. Base `global.ini` mapped to
  rjcncpt/StarCitizen-Deutsch-INI (`live/global.ini`, the standard hybrid
  translation, not the extended "Deutsch+" variant) in `sources.json`;
  `SC_LANGUAGE_IDS["german"] = "german_(germany)"`; installer
  `LanguageChoicePage` gained a German option. Locked by
  `tests/test_german_activation.py`.

- **2.2.0 pre-release (2026-07-15, Claude Fable 5):** AI backfill of the keys
  this cycle added in English only. french and portuguese_br each gained 43
  `at`-only keys (Blueprint Tracker tab, blueprint shuttle/facets, log-scan
  dialogs, Unapplied Changes dialog, medical consumables description, plus the
  tour's new `blueprint_tracker` step); spanish gained 75, including its first
  full guided-tour translation (`tutorial.*`, all 19 steps). The stale
  `tutorial.enh_categories.description` `at` in french/portuguese_br was
  refreshed for the two categories added this cycle (it had no `ht`). All new
  strings are `ht: ""` so translators can find them the usual way.

## Per-language notes

- **english** — source language. All strings authored by the maintainer.
- **french** — human-translated by **Akwa**, process led by **Ishikudeska**. AI
  fallbacks (Claude Opus 4.8) cover the keys whose `ht` is still empty (the tour,
  progress strings, and a handful of dialogs/config keys — grep `"ht": ""`), plus
  the `HELP.md` / `ABOUT.md` / `LEGAL.md` documents in this folder.
- **portuguese_br** — human-translated by **Nxzzin**, process led by
  **Ishikudeska**. Same AI-fallback coverage as french (grep `"ht": ""`), plus the
  `HELP.md` / `ABOUT.md` / `LEGAL.md` documents.
- **spanish** — human-translated by **Thord82**. The in-app UI strings were
  contributed as a full `ui.json` and converted to the `{ht, at}` shape (his
  strings landed in `ht`; `at` left empty). A handful of newer keys added after
  his contribution are still untranslated (grep `"ht": ""` — the simple-mode
  page, FAQ tab, a few toolbar/filter/column labels); they fall back to English
  until the pre-release AI backfill. The `HELP.md` / `ABOUT.md` / `LEGAL.md`
  documents in this folder are AI translations (2.3.0 cycle) pending Thord82's
  review. The base `global.ini` for Spanish is sourced
  from Thord82's repo (`Thord82/Star_citizen_ES`, branch `propuestas_thord`),
  which tracks the current game build far more completely than the prior Dymerz
  source (99.9% vs 78.4% key coverage). Spanish writes to the game's
  `spanish_(spain)` Localization folder with `g_language = spanish_(spain)`
  (`SC_LANGUAGE_IDS`), confirmed to render in-game.
- **italian** — AI-translated by **Claude** (#298). No human translator yet, so
  **every** key is `at`-only (`ht` empty) — the whole UI, the guided tour
  (`tutorial.*`), and the `HELP.md` / `ABOUT.md` / `LEGAL.md` / `FAQ.md`
  documents are awaiting human review (grep `"ht": ""` returns the entire
  file by design). The base `global.ini` is sourced from
  **Dymerz/StarCitizen-Localization**
  (`data/Localization/italian_(italy)/global.ini`), the same source repo
  already used for french and portuguese_br. Italian writes to the game's
  `italian_(italy)` Localization folder with `g_language = italian_(italy)`
  (`SC_LANGUAGE_IDS`). An Italian-speaking reviewer replacing the `at`
  strings with `ht` is the next step to promote it from AI-only to
  human-reviewed.
- **chinese** — AI-translated by **Claude** (#300). No human translator yet,
  so **every** key is `at`-only (`ht` empty) — the whole UI, the guided tour
  (`tutorial.*`), and the `HELP.md` / `ABOUT.md` / `LEGAL.md` / `FAQ.md`
  documents are awaiting human review (grep `"ht": ""` returns the entire
  file by design). The base `global.ini` is sourced from
  **[42Kit](https://ini.42kit.com/full/global.ini)**, a Simplified Chinese
  community translation. Chinese writes to the game's `chinese_(simplified)`
  Localization folder with `g_language = chinese_(simplified)`
  (`SC_LANGUAGE_IDS`) — a community-known value CIG doesn't officially ship
  a stock folder for, unlike the other languages here. A Chinese-speaking
  reviewer replacing the `at` strings with `ht` is the next step to promote
  it from AI-only to human-reviewed.
- **japanese** — AI-translated by **Claude** (#301). No human translator yet, so
  **every** key is `at`-only (`ht` empty) — the whole UI, the guided tour
  (`tutorial.*`), and the `HELP.md` / `ABOUT.md` / `LEGAL.md` documents are
  awaiting human review (grep `"ht": ""` returns the entire file by design).
  The base `global.ini` is sourced from **stdblue/StarCitizenJapaneseResources**
  (`v4.x/release/japanese_(japan)/global.ini`) rather than Dymerz, which does not
  ship a Japanese pack. Japanese writes to the game's `japanese_(japan)`
  Localization folder with `g_language = japanese_(japan)` (`SC_LANGUAGE_IDS`).
  A Japanese-speaking reviewer replacing the `at` strings with `ht` is the next
  step to promote it from AI-only to human-reviewed.
- **german** — AI-translated by **Claude** (#299). No human translator yet, so
  **every** key is `at`-only (`ht` empty) — the whole UI, the guided tour
  (`tutorial.*`), and the `HELP.md` / `ABOUT.md` / `LEGAL.md` / `FAQ.md`
  documents are awaiting human review (grep `"ht": ""` returns the entire
  file by design). The base `global.ini` is sourced from
  **rjcncpt/StarCitizen-Deutsch-INI** (`live/global.ini`), a community
  translation project with its own launcher and Discord. German writes to
  the game's `german_(germany)` Localization folder with
  `g_language = german_(germany)` (`SC_LANGUAGE_IDS`). A German-speaking
  reviewer replacing the `at` strings with `ht` is the next step to promote
  it from AI-only to human-reviewed.
- **korean** — AI-translated by **Claude** (#367). No human translator yet, so
  **every** key is `at`-only (`ht` empty) — the whole UI, the guided tour
  (`tutorial.*`), and the `HELP.md` / `ABOUT.md` / `LEGAL.md` / `FAQ.md`
  documents are awaiting human review (grep `"ht": ""` returns the entire
  file by design). Unlike every other language here, Korean ships with
  **no bundled `global.ini` source** — `sources.json`'s `korean` entry is
  deliberately blank. The community source, the Star Citizen Korean
  Localization Project (스타 시티즌 유저 한국어 프로젝트, sc.galaxyhub.kr),
  licenses their file for non-redistribution and gates the download behind
  a daily Discord access code, so there is no public URL Smart Citizen
  could fetch even if it wanted to. Instead, a Korean-speaking user installs
  the community patch themselves, then uses the Config tab's *Map Language
  File* (now with a **Browse...** button, #367) to point Smart Citizen at
  the `global.ini` they already have locally — Smart Citizen copies it in
  rather than downloading it, and never redistributes it. Korean writes to
  the game's `korean_(south_korea)` Localization folder with
  `g_language = korean_(south_korea)` (`SC_LANGUAGE_IDS`) — one of CIG's
  twelve official Localization slots. A Korean-speaking reviewer replacing
  the `at` strings with `ht` is the next step to promote it from AI-only to
  human-reviewed.
- **chinese_traditional** — Generated by **Claude** (#403) via OpenCC `s2twp`
  conversion of the **chinese** (Simplified) translation, not an independent
  translation from English — see the 2.4.0 backfill-log entry above for the
  method and the ambiguous-character verification pass. No human translator
  yet, so **every** key is `at`-only (`ht` empty) — the whole UI, the guided
  tour (`tutorial.*`), and the `HELP.md` / `ABOUT.md` / `LEGAL.md` / `FAQ.md`
  documents are awaiting human review (grep `"ht": ""` returns the entire
  file by design). The base `global.ini` is sourced from
  **Orbit-Startech/StarCitizen-TCTP** (`chinese_(traditional)/global.ini`),
  which stopped updating in May 2024 and covers only 67.3% of the current
  English key set — flagged in the language selector as "Traditional
  Chinese" (the 2026-10-01 follow-up dropped the hardcoded percentage, which
  could only go stale, keeping just the corrected name) rather than left as
  a silent surprise. chinese_traditional writes to the game's
  `chinese_(traditional)` Localization folder with
  `g_language = chinese_(traditional)` (`SC_LANGUAGE_IDS`). A
  Traditional-Chinese-speaking reviewer replacing the `at` strings with `ht`
  — and ideally finding a more current source — is the next step to promote
  it from AI-only to human-reviewed.
- **turkish** — AI-translated by **Claude** (#404). No human translator yet, so
  **every** key is `at`-only (`ht` empty) — the whole UI, the guided tour
  (`tutorial.*`), and the `HELP.md` / `ABOUT.md` / `LEGAL.md` / `FAQ.md`
  documents are awaiting human review (grep `"ht": ""` returns the entire
  file by design). The base `global.ini` is sourced from
  **Dymerz/StarCitizen-Localization**
  (`data/Localization/turkish_(turkey)/global.ini`), the same source repo
  already used for french, portuguese_br, and italian. Turkish writes to
  the game's `polish_(poland)` Localization folder with
  `g_language = polish_(poland)` (`SC_LANGUAGE_IDS`) — a borrowed slot,
  not a Turkish one: `turkish_(turkey)` is not a `g_language` value the
  game accepts, `russian_(russia)` was tried first and is not recognised
  by the game either, and Dymerz's suggested `german_(germany)` is already
  taken by our German language. Polish is unclaimed by our own languages
  and shares Turkish's Latin Extended-A glyph needs. A Turkish-speaking
  reviewer replacing the `at`
  strings with `ht` is the next step to promote it from AI-only to
  human-reviewed.
- **russian** — AI-translated by **Claude**. No human translator yet, so
  **every** key is `at`-only (`ht` empty): the whole UI, the guided tour
  (`tutorial.*`), and the `HELP.md` / `ABOUT.md` / `LEGAL.md` / `FAQ.md`
  documents are awaiting human review. The base `global.ini` is sourced from
  **n1ghter/StarCitizenRu** (`data/Localization/korean_(south_korea)/global.ini`),
  the main Russian community translation project. Russian writes to the
  game's `korean_(south_korea)` Localization folder with
  `g_language = korean_(south_korea)` (`SC_LANGUAGE_IDS`): a borrowed slot,
  shared with Korean on purpose. `russian_(russia)` is not a value the game
  accepts, and the Korean font is the only in-game font that covers
  Cyrillic. Only one of Russian or Korean can be applied at a time: applying
  one overwrites the other's `global.ini` in that folder. A Russian-speaking
  reviewer replacing the `at` strings with `ht` is the next step to promote
  it from AI-only to human-reviewed.
