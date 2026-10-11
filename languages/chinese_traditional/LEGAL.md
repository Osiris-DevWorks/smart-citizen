# 智慧公民 — 法律與合規

本頁面在一處彙總了智慧公民所有的法律、許可及資料處理披露資訊。如果此處內容與可執行檔案旁附帶的 `LICENSE` 或 `NOTICE` 檔案有衝突，以那些檔案為準。

## 星際公民 / Cloud Imperium 致謝宣告

智慧公民是《星際公民》的**非官方社群工具**。它並非由 Cloud Imperium Games（CIG）或 Roberts Space Industries（RSI）開發、認可、贊助或以任何方式關聯。智慧公民遵循 CIG 針對粉絲製作內容和工具的“由社群製作”準則。

**Star Citizen®**、**Roberts Space Industries®** 和 **Cloud Imperium®** 是 Cloud Imperium Rights LLC 和 Cloud Imperium Rights Ltd. 的註冊商標。所有《星際公民》遊戲資料，包括 `Data.p4k` 的內容、飛船和元件模型、物品名稱、任務文字及背景設定，均為 Cloud Imperium Rights LLC 的智慧財產權。

智慧公民不會重新分發任何 CIG 或 RSI 的內容。該應用讀取的是**你本機上自己已授權的《星際公民》安裝檔案**，並將使用者自定義的字串寫回同一安裝目錄。任何 CIG 擁有的內容都不會透過智慧公民離開你的電腦。

## 智慧公民許可證

智慧公民是採用 **Apache 許可證 2.0 版** 授權的開源軟體。你可以在 [apache.org/licenses/LICENSE-2.0](https://www.apache.org/licenses/LICENSE-2.0) 獲取許可證副本。完整的許可證文字隨附於可執行檔案旁的 `LICENSE` 檔案中，原始碼可在 [GitHub 倉庫](https://github.com/Osiris-DevWorks/smart-citizen) 獲取。

除非適用法律要求或經書面同意，根據本許可證分發的軟體是按“**原樣**”提供的，不附帶任何明示或暗示的保證或條件。有關許可證下許可權和限制的具體規定，請參閱許可證原文。

## 捆綁的第三方軟體

智慧公民的安裝程式中捆綁了以下第三方軟體。每項的完整署名文字均位於可執行檔案旁的 `NOTICE` 檔案中。

- **unp4k / unforge** —— 捆綁於 `assets/unp4k/`，即 `unp4k.exe` 和 `unforge.exe`。Osiris DevWorks 提供自己的分支（[odw-fast-unp4k](https://github.com/Osiris-DevWorks/odw-fast-unp4k)），基於原始的 [dolkensp/unp4k](https://github.com/dolkensp/unp4k) 專案，帶有並行提取和效能改進。用於解包 `Data.p4k` 並將 DataForge 實體檔案轉換為 XML。採用 **MIT 許可證**。
- **PyQt6** —— 圖形介面框架，由 Riverbank Computing 提供。非商業分發採用 **GNU 通用公共許可證 v3（GPL-3.0）**；Riverbank 也提供商業許可。智慧公民是免費的開源社群工具，符合 GPL-3.0 條款。
- **lxml** —— XML 解析庫，由 lxml.de 提供。採用 **BSD-3-Clause 許可證**。

由 PyInstaller 捆綁的 Python 標準庫及其他執行時依賴項各自擁有自己的許可證；請參閱 Python 軟體基金會許可證 [docs.python.org/3/license.html](https://docs.python.org/3/license.html)。

## 隱私與資料處理

智慧公民是一款**本地桌面應用程式**。它不會將你的編輯內容、`user.ini`、`base.ini`、自定義內容或電腦中的任何其他內容傳輸到 Osiris DevWorks 或任何第三方運營的伺服器。

### 保留在你電腦上的內容

一切內容。你的本地化編輯、備份、應用設定和 DataForge 快取均僅存放在你的本地磁碟上：

- **設定** —— 預設安裝方式下位於 Windows 登錄檔 `HKEY_CURRENT_USER\Software\Osiris DevWorks\Smart Citizen`；便攜版則位於可執行檔案旁的 `config.json`。
- **使用者編輯內容與備份** —— 預設位於 `文件\Smart Citizen\{頻道}\`（可在配置標籤頁中修改；便攜版則使用 `<可執行檔案目錄>\data\`）。
- **DataForge XML 快取** —— `%LOCALAPPDATA%\Smart Citizen\{頻道}\cache\dataforge\`。
- **崩潰轉儲與手動匯出的日誌** —— `文件\Smart Citizen\logs\`（或便攜版對應位置），僅在應用崩潰或你在日誌標籤頁點選“匯出”時才會寫入。

### 透過網路傳輸的內容

智慧公民僅在以下三種情況下發出出站網路請求：

- **更新檢查** —— 大約每 6 小時向 `api.github.com/repos/Osiris-DevWorks/smart-citizen/releases/latest` 傳送一次小型的未經身份驗證的請求，以比較已安裝版本與最新 GitHub 釋出版本。僅返回釋出後設資料（標籤名稱、釋出頁面地址）；不會傳送任何智慧公民的狀態資料。
- **語言下載** —— 當你切換到非英語語言時，智慧公民會從配置的地址下載該語言社群翻譯的 `global.ini`（預設來自 [Dymerz/StarCitizen-Localization](https://github.com/Dymerz/StarCitizen-Localization) GitHub 倉庫）。下載內容會在本地快取；你機器上的任何內容都不會被髮送出去。
- **使用者自定義的遠端來源** —— 如果你在配置標籤頁中配置了指向 `http(s)://` 地址的資料來源，智慧公民會在重新整理原始檔時獲取該地址。預設情況下，這僅適用於 `global` 來源的 GitHub-raw 地址形式；自 v1.0 起，標準配置改為從你本地的 Data.p4k 提取內容中讀取 `base.ini`。

### 智慧公民**不會**做的事

- 不進行任何形式的遙測、分析或使用情況報告。
- 不收集、儲存或傳輸任何個人身份資訊。
- 不進行後臺資料上傳。
- 不向遠端伺服器自動上報崩潰——崩潰轉儲**僅在本地**寫入 `文件\Smart Citizen\logs\`。如果你想為 Bug 報告分享一份，需要你自己手動複製貼上該檔案。
- 沒有賬號、沒有登入、沒有遠端身份。

如果你發現有與上述內容不符的行為，請在 [github.com/Osiris-DevWorks/smart-citizen/issues](https://github.com/Osiris-DevWorks/smart-citizen/issues) 提交 Bug 報告。

## AI 使用宣告

智慧公民的部分原始碼是在 Anthropic 的 AI 程式設計助手 **Claude** 的協助下編寫的。生成的程式碼在合併前**由人類維護者審閱並批准**——AI 不會直接提交程式碼，其待遇與任何其他程式碼貢獻相同：經過閱讀、測試後再基於其本身價值決定是否採納。

具體而言：

- AI 協助加速了生成器、分類器、重構和測試的開發；由 AI 協助編寫的提交在提交資訊中帶有 `Co-Authored-By: Claude` 尾註，因此歷史記錄可供審計。
- 所有《星際公民》遊戲資料解析邏輯、任務分類和字串處理規則均由人類維護者設計，並針對真實的 DataForge 快取樣本進行驗證。
- 智慧公民的部分介面和文件翻譯是 AI 生成的佔位翻譯，直到有人類翻譯到來為止。這些內容會按語言、按字串在 `languages/TRANSLATIONS.md` 中進行追蹤，並在人類翻譯完成後被替換。現有的人類翻譯永遠不會被 AI 修改。
- **應用程式本身不包含任何 AI 或機器學習功能。** 智慧公民不捆綁任何模型，執行時不呼叫任何 AI 服務，也不會將你的編輯內容或《星際公民》遊戲資料傳輸給任何 AI 提供商。

## 報告法律相關問題

如果你認為智慧公民侵犯了你持有的版權、商標或其他權利——或者你對該應用如何處理你的資料有疑問——請提交 issue，或透過 [Osiris DevWorks Discord](https://discord.gg/BNzRegKZ7k) 聯絡維護者。
