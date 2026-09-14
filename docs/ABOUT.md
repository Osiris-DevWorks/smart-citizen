# Smart Citizen

*Smarter Strings for Star Citizen*

## About This Project

**Smart Citizen** is a powerful, user-friendly tool for Star Citizen players to customize their game's localization strings. Load, edit, and apply localization changes with full persistence, automatic backups, and seamless support for game updates.

Developed by **Osiris DevWorks**, a one-man development studio dedicated to creating valuable tools for the gaming community.

## The Osiris DevWorks Promise

All Osiris DevWorks tools will be either **completely free** or have a **free tier**. We believe in creating value for gamers without paywalls or mandatory subscriptions.

## ODW Team

- **Osiris_x**
- **Tichro**

## Contributors

Thanks to those who've contributed code to Smart Citizen:

- **Stealrull**
- **Ishikudeska**
- **jonigirl**
- **Coerwyn**
- **denis-coach** (h0use)
- **scubamount**
- **hkstrongside**
- **odw-okano**

## Translators

Thanks to those who've translated Smart Citizen's interface:

- **Akwa** (Français)
- **Nxzzin** (Português brasileiro)
- **Thord82** (Español)

## Acknowledgements

Thanks to the testers who helped shape Smart Citizen with their feedback:

- **Boogie Man**
- **Perseuscz**
- **Flat Earth**
- **Lord Valium**
- **Zero**
- **Apolleon Phoibos**
- **Epiq**
- **Narull**
- **XaileiShiv**
- **Mindbulletz**

### Supporters

Thanks to those who've supported the project financially — your contributions help keep Smart Citizen free for everyone:

- **Dimwit the Wise**

Smart Citizen also bundles upstream tooling from:

- [**Osiris-DevWorks/odw-fast-unp4k**](https://github.com/Osiris-DevWorks/odw-fast-unp4k) — `unp4k.exe` and `unforge.exe`, used to unpack `Data.p4k` and convert DataForge to XML. This is our fork of the original [**dolkensp/unp4k**](https://github.com/dolkensp/unp4k) with parallel extraction and other performance improvements.

The non-English game strings are community translations:

- [**Dymerz/StarCitizen-Localization**](https://github.com/Dymerz/StarCitizen-Localization) — the community-maintained `global.ini` translations that power the French, Brazilian Portuguese, Italian, and Turkish language options. Their translators do the real work here; we just deliver it.
- [**Thord82/Star_citizen_ES**](https://github.com/Thord82/Star_citizen_ES): the community-maintained `global.ini` translation that powers the Spanish language option.
- [**stdblue/StarCitizenJapaneseResources**](https://github.com/stdblue/StarCitizenJapaneseResources) — the community-maintained `global.ini` translation that powers the Japanese language option.
- [**42Kit**](https://ini.42kit.com/) — the community-maintained `global.ini` translation that powers the Chinese language option.
- [**rjcncpt/StarCitizen-Deutsch-INI**](https://github.com/rjcncpt/StarCitizen-Deutsch-INI) — the community-maintained `global.ini` translation that powers the German language option.

## Key Features

### 🎯 Core Features
- **Load & Edit**: Load `global.ini` from your Star Citizen installation and customize strings in an intuitive table view
- **Multi-Channel Support**: LIVE / PTU / EPTU / HOTFIX / TECH-PREVIEW each get their own isolated `user.ini`, cache, backups, and DataForge extraction — switch channels from the Config tab without restarting
- **Multi-Language Support**: Switch the app and game strings between English, French, Spanish, Brazilian Portuguese, Japanese, Chinese, Italian, German, and Turkish from the Config tab. Non-English languages layer a community-translated `global.ini` over the English base, with English fallback for anything untranslated. More languages will be exposed as community translations land (see `languages/TRANSLATIONS.md`)
- **Mission Contracts**: Edit mission contract and briefing text from the dedicated Missions category
- **Smart Filtering**: Search strings, filter by category (Ships, Ship Items, Missions, Gear, Commodities, Journal, Other), or modification status
- **Per-Column Filters**: Type directly into filter boxes below each column header for fine-grained searching
- **Live Preview Pane**: A side preview renders the selected row's text with the game's loc-tokens (line breaks, EM3/EM4 emphasis, mission placeholders) translated to styled HTML so you see roughly how the string will read in-game
- **Editor Side-Panel**: Toolbar-toggleable, drag-resizable, undockable canvas for editing long values (journal entries, mission briefings, ship descriptions) with Underline/Highlight buttons and live cross-pane sync
- **Safe Application**: Apply writes to `global.ini` with an automatic timestamped backup first, validates the output against the stock key set, and auto-rolls back on any mismatch
- **Restore Backups**: Keep up to 5 backup versions per channel — revert changes anytime with one click
- **Clear Localization**: Revert your game to vanilla text without losing your saved overrides
- **Import INI**: Import an existing INI file and resolve conflicts key-by-key with the built-in conflict dialog
- **Simple & Advanced Mode**: Open to a two-button Simple screen (one button applies enhancements with your saved settings, the other switches to Advanced), or use the full Advanced UI (table, filters, Enhancements, Config) whenever you want to hand-edit. Pick your default at install and flip between them in-app
- **FAQ Tab**: The questions we hear most, answered right in the app — what files get touched, ban risk, the Windows unrecognized-app warning, and how to undo changes
- **Flexible Window & Columns**: Resize the window to any size — each tab scrolls its own content rather than squeezing or clipping controls. String Editor columns are drag-resizable (double-click a divider to fit its content) and your widths and window layout persist between launches, with **More → Reset Window Proportions** to restore the defaults
- **Guided Tutorial**: A coach-mark tour walks new users through the workflow on first launch of each version — replayable any time from the Tutorial button

### 🔄 Data Sourcing & Persistence
- **Sourced from Data.p4k**: All stock localization and DataForge entity data is unpacked directly from your installed `Data.p4k` — no downloads, no community mirrors, always in sync with your actual game version
- **Persistent Edits**: Your customizations are automatically saved and reloaded in every session
- **Seamless Migration**: When Star Citizen updates, re-extract from the patched `Data.p4k` — your saved edits re-apply to the new base strings automatically
- **Clean UI**: High-performance table view with filters, in-line editing, keyboard shortcuts, and a modern interface

### 📊 Enhancements
- **Ship Stats**: SCM speed, hydrogen/quantum fuel, cargo capacity, full weapon loadouts, and armor multipliers (physical / energy / distortion / thermal) appended to ship descriptions
- **Component Stats**: Shield HP, power draw, cooling rate, regen, and similar stats for shields, coolers, power plants, quantum drives, and radars — with `[MIL-S2-A]`-style name tags by default (fully customizable in the Tag Builder)
- **Weapon Stats**: DPS, fire rate, range, and damage on ship guns and turrets from S1 through capital. Ship weapons get a `[E-S2]`-style damage+size tag, missiles `[IR-S1] Arrester III`, and bombs `[S5] 500SCB Cluster`
- **Mission Annotations**: `[BP]` / `[BP?]` blueprint reward tags on titles, plus structured *MISSION DETAILS*, *POTENTIAL BLUEPRINTS*, and *ITEM REWARDS* blocks in descriptions. Reputation tier lines show actual rank names (Rookie, Jr. Contractor, etc.) instead of generic numbering. Mission XP names the reputation track it feeds, and Battaglia scan/mine titles carry `[RS ####]` resource-signature tags, joined by a MISSION DETAILS "Resource Signatures" breakdown per targeted ore and an ore-name annotation shown everywhere the game displays that name, including the mission tracker (two independent toggles, both on by default)
- **Journal Cross-References**: Mining Compendium entries get crafting cross-references and each ore's base resource signature; commodities used in crafting get a customizable `[CF]` name tag and a list of every blueprint that calls for them
- **Medical Consumable Effects**: The base CureLife pens (MedPen, OxyPen, AdrenaPen, and friends) get a plain-language effect line, so the description says what the pen does instead of just its lore
- **Ship Favorites**: Star a ship to prepend a configurable prefix (default `*`) so favorites sort to the top of the in-game ASOP terminal
- **Tag Builder**: Customize the bracketed tags on components, missiles, ship weapons, and commodities — reorder elements, change abbreviation length (M / MIL / Military), pick separators and brackets, or place the tag after the name instead of before. Components have an optional Type element (Shield, Cooler, etc.); commodities have a Usage element showing what their crafting materials feed into
- **Mission Titles**: Lead hauling titles with their route (e.g. `Area18 > Lorville`) — configurable placement, arrow, separator, and location detail, plus optional stock-title shortening, with a live preview
- **Stats Above or Below**: Choose whether a stat block sits at the top or the bottom of the description
- **Blueprint Tracker**: A dedicated tab for marking the crafting blueprints you already own. Shuttle items between Available and Owned, filter by Mission / Type / Class / Size / Grade, and owned items get a blue `[Owned]` tag in mission blueprint lists. **Scan Logs for Owned Blueprints** populates ownership automatically from your Star Citizen log files, importing only what's new since the last scan, and **Export / Import Owned Blueprints** moves the owned list between PCs (JSON or CSV; imports only ever add, and scmdb.net exports work too)
- **Mission Labels**: Rename the section headers (MISSION DETAILS, POTENTIAL BLUEPRINTS, etc.), the XP label, and the emphasis tag used for headers
- **Declarative CIG Data-Bug Patches**: A patch system applies fixes to known DataForge bugs at extraction time so in-game text reads correctly without waiting on CIG
- **Selective Categories**: Enable or disable each enhancement category independently from the Enhancements tab

### 🎨 Themes
- **Default**: Deep-navy cyber theme inspired by Star Citizen's mobiGlas UI
- **Light / Dark**: Classic UI themes
- **ODW**: Osiris DevWorks signature theme — navy charcoal with antique gold

### 🛡️ Data Management
- **Automatic Backups**: Timestamped backups created before applying changes to your game (up to 5 per channel)
- **Registry Persistence**: All paths and preferences saved securely in Windows Registry
- **Configurable Data Storage**: Your custom edits are stored under `<data folder>\<channel>\` (default `Documents\Smart Citizen`, one isolated subtree per Star Citizen channel) for safe persistence across sessions
- **Settings Backup**: Export your whole setup (preferences, tag configurations, and every channel's string overrides) to one small zip, then import it on a new PC or after a fresh portable unzip. Imports snapshot your current files first, so they're reversible
- **In-App Log Viewer**: Real-time application log with level filter, auto-scroll, and an Export button for bug reports
- **Auto-Updater**: Smart Citizen checks GitHub Releases at launch and shows the release notes in-app; one click (plus a Windows permission prompt) downloads the update, installs it, and reopens the app

## Quick Start

1. **First Launch**: App auto-detects your Star Citizen installation (editable in the **Config** tab)
2. **Extract**: Click **Extract from Data.p4k** in the Config tab to unpack stock localization + DataForge entity data from your installed game — the strings load into the table automatically when extraction finishes
3. **Edit Strings**: Use the search and filter tools, then double-click any Custom Value cell to customize text
4. **Apply**: Click **Apply Enhancements** — your changes are saved and applied with an automatic backup
5. **Enhancements (Optional)**: Open the Enhancements tab to enable stat overlays for ships, components, weapons, and mission rewards
6. **After Game Updates**: Re-run Extract from Data.p4k — your edits reapply automatically

## Community & Support

### Join Us
- 💬 [Discord Community](https://discord.gg/BNzRegKZ7k) - Get support, share configs, request features
- 🐛 [Smart Citizen Feedback, Bugs, & Feature Voting](https://discord.com/channels/1438175448420057323/1472394204347895890) - Dedicated channel for bug reports, feedback, and voting on upcoming features (join the server first via the invite above)

### Video Guides
- 🎥 [Star Citizen Hides Important Mission Info – This Tool Shows It In-Game & More!](https://www.youtube.com/watch?v=Xo1t404gsgs) by **Karolinger** - a community overview of Smart Citizen's features

### Support This Project
Smart Citizen is completely free. If you find it valuable:
- 💳 [Donate via PayPal](https://www.paypal.com/ncp/payment/YAWXHMGZH8T76)
- 💰 [Donate via Venmo](https://venmo.com/u/Amr-Abouelleil)

## Other Tools by Osiris DevWorks

- **[Battlestations](https://battlestations.osiris-devworks.com/)** - Manage and share Star Citizen hangar battlestation builds
- **[SC Profile Editor](https://github.com/Osiris-DevWorks/sc-profile-editor)** - Import, edit, and export Star Citizen control profiles
- **[Extended AFK](https://github.com/Osiris-RK/extended-afk)** - AFK tool to prevent idle timeouts

## Built On

Built with **PyQt6** and inspired by the Star Citizen community's localization work.

**GitHub**: https://github.com/Osiris-DevWorks/smart-citizen

## License & Legal

Smart Citizen is licensed under the **Apache License, Version 2.0**.

See the **Legal** tab for the full license summary, bundled third-party software attributions (unp4k / PyQt6 / lxml), Cloud Imperium "Made by the Community" acknowledgements, privacy & data-handling disclosure, and AI-use statement.
