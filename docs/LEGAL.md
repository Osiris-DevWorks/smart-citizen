# Smart Citizen — Legal & Compliance

This page collects every legal, licensing, and data-handling disclosure for Smart Citizen in one place. If something here conflicts with the `LICENSE` or `NOTICE` files shipped next to the executable, those files are authoritative.

## Star Citizen / Cloud Imperium Acknowledgement

Smart Citizen is an **unofficial community tool** for Star Citizen. It is not developed, endorsed, sponsored, or affiliated with Cloud Imperium Games (CIG) or Roberts Space Industries (RSI) in any way. Smart Citizen falls under CIG's "Made by the Community" guidelines for fan-made content and tools.

**Star Citizen®**, **Roberts Space Industries®**, and **Cloud Imperium®** are registered trademarks of Cloud Imperium Rights LLC and Cloud Imperium Rights Ltd. All Star Citizen game data, including the contents of `Data.p4k`, ship and component models, item names, mission text, and lore, is the intellectual property of Cloud Imperium Rights LLC.

Smart Citizen does not redistribute any CIG or RSI content. The app reads files from **your own licensed Star Citizen installation** on your local machine and writes user-customized strings back to that same installation. No CIG-owned content leaves your computer through Smart Citizen.

## Smart Citizen License

Smart Citizen is open-source software licensed under the **Apache License, Version 2.0**. You may obtain a copy of the License at [apache.org/licenses/LICENSE-2.0](https://www.apache.org/licenses/LICENSE-2.0). The full license text ships in the `LICENSE` file next to the executable, and the source code is available at the [GitHub repository](https://github.com/Osiris-DevWorks/smart-citizen).

Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an **"AS IS" basis, without warranties or conditions of any kind**, either express or implied. See the License for the specific language governing permissions and limitations.

## Bundled Third-Party Software

Smart Citizen ships the following third-party software inside its installer. The full attribution text for each is in the `NOTICE` file next to the executable.

- **unp4k / unforge** — Bundled at `assets/unp4k/` as `unp4k.exe` and `unforge.exe`. Osiris DevWorks ships its own fork ([odw-fast-unp4k](https://github.com/Osiris-DevWorks/odw-fast-unp4k)) of the original [dolkensp/unp4k](https://github.com/dolkensp/unp4k) project with parallel extraction and performance improvements. Used to unpack `Data.p4k` and convert DataForge entity files to XML. Licensed under the **MIT License**.
- **PyQt6** — GUI framework, by Riverbank Computing. Used under the **GNU General Public License v3 (GPL-3.0)** for non-commercial distribution; commercial licensing is also available from Riverbank. Smart Citizen is a free, open-source community tool and qualifies under the GPL-3.0 terms.
- **lxml** — XML parsing library, by lxml.de. Used under the **BSD-3-Clause License**.

The Python standard library and other runtime dependencies bundled by PyInstaller carry their own licenses; see the Python Software Foundation License at [docs.python.org/3/license.html](https://docs.python.org/3/license.html).

## Privacy & Data Handling

Smart Citizen is a **local desktop application**. It does not transmit your edits, your `user.ini`, your `base.ini`, your customizations, or any other content from your computer to any server operated by Osiris DevWorks or any third party.

### What stays on your computer

Everything. Your localization edits, backups, application settings, and DataForge cache live exclusively on your local disk:

- **Settings** — Windows Registry under `HKEY_CURRENT_USER\Software\Osiris DevWorks\Smart Citizen` in the default install, or `config.json` next to the executable in the portable build.
- **User edits + backups** — `Documents\Smart Citizen\{channel}\` by default (configurable in the Config tab; portable build uses `<exe-dir>\data\` instead).
- **DataForge XML cache** — `%LOCALAPPDATA%\Smart Citizen\{channel}\cache\dataforge\`.
- **Crash dumps + manual log exports** — `Documents\Smart Citizen\logs\` (or portable equivalent), only written when the app crashes or you click *Export* in the Log tab.

### What goes over the network

Smart Citizen makes outbound network requests in only three circumstances:

- **Update check** — A small unauthenticated request to `api.github.com/repos/Osiris-DevWorks/smart-citizen/releases/latest` approximately once every 6 hours to compare the installed version against the latest GitHub release. Returns release metadata only (tag name, release URL); no Smart Citizen state is sent.
- **Language downloads** — When you switch to a non-English language, Smart Citizen downloads that language's community-translated `global.ini` from the configured URL (by default the [Dymerz/StarCitizen-Localization](https://github.com/Dymerz/StarCitizen-Localization) GitHub repository). The download is cached locally; nothing from your machine is sent.
- **User-configured remote sources** — If you have configured a data source pointing at an `http(s)://` URL in the Config tab, Smart Citizen fetches that URL when refreshing source files. Out of the box this only applies to the `global` source's GitHub-raw URL form; the standard configuration since v1.0 reads `base.ini` from your local Data.p4k extraction instead.

### What Smart Citizen does **not** do

- No telemetry, analytics, or usage reporting of any kind.
- No personally identifiable information collected, stored, or transmitted.
- No background data uploads.
- No automatic crash reporting to a remote server — crash dumps are written **locally only** under `Documents\Smart Citizen\logs\`. If you want to share one for a bug report, you copy and paste the file yourself.
- No accounts, no login, no remote identity.

If you discover behavior that conflicts with the above, please file a bug report at [github.com/Osiris-DevWorks/smart-citizen/issues](https://github.com/Osiris-DevWorks/smart-citizen/issues).

## AI Use Statement

Portions of Smart Citizen's source code were written with assistance from **Claude**, Anthropic's AI coding assistant. Generated code is **reviewed and approved by a human maintainer before merging** — the AI does not commit directly and is treated the same as any other code contribution: read, tested, and accepted only on its merits.

Specifically:

- AI assistance accelerates development of generators, classifiers, refactors, and tests; commits authored with AI help carry a `Co-Authored-By: Claude` trailer in their commit message so the history is auditable.
- All Star Citizen game-data parsing logic, mission classification, and string-handling rules are designed by the human maintainers and validated against real DataForge cache samples.
- Some of Smart Citizen's interface and documentation translations are AI-generated as placeholders until human translations arrive. They are tracked, per language and per string, in `languages/TRANSLATIONS.md`, and are replaced as human translations land. Existing human translations are never modified by AI.
- **The application itself contains no AI or machine-learning features.** Smart Citizen does not bundle any model, does not call any AI service at runtime, and does not transmit your edits or Star Citizen game data to an AI provider.

## Reporting Legal Concerns

If you believe Smart Citizen infringes on a copyright, trademark, or other right you hold — or if you have a question about how the app handles your data — open an issue or contact the maintainers via the [Osiris DevWorks Discord](https://discord.gg/BNzRegKZ7k).
