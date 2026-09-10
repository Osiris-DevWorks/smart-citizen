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

## Backfill log

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
  The seven other translated `ABOUT.md` files still list eight languages;
  left for the pre-release docs-parity sweep. Locked by
  `tests/test_turkish_activation.py`.

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
