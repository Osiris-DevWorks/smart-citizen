# 智慧公民 — 法律与合规

本页面在一处汇总了智慧公民所有的法律、许可及数据处理披露信息。如果此处内容与可执行文件旁附带的 `LICENSE` 或 `NOTICE` 文件有冲突，以那些文件为准。

## 星际公民 / Cloud Imperium 致谢声明

智慧公民是《星际公民》的**非官方社区工具**。它并非由 Cloud Imperium Games（CIG）或 Roberts Space Industries（RSI）开发、认可、赞助或以任何方式关联。智慧公民遵循 CIG 针对粉丝制作内容和工具的“由社区制作”准则。

**Star Citizen®**、**Roberts Space Industries®** 和 **Cloud Imperium®** 是 Cloud Imperium Rights LLC 和 Cloud Imperium Rights Ltd. 的注册商标。所有《星际公民》游戏数据，包括 `Data.p4k` 的内容、飞船和组件模型、物品名称、任务文本及背景设定，均为 Cloud Imperium Rights LLC 的知识产权。

智慧公民不会重新分发任何 CIG 或 RSI 的内容。该应用读取的是**你本机上自己已授权的《星际公民》安装文件**，并将用户自定义的字符串写回同一安装目录。任何 CIG 拥有的内容都不会通过智慧公民离开你的电脑。

## 智慧公民许可证

智慧公民是采用 **Apache 许可证 2.0 版** 授权的开源软件。你可以在 [apache.org/licenses/LICENSE-2.0](https://www.apache.org/licenses/LICENSE-2.0) 获取许可证副本。完整的许可证文本随附于可执行文件旁的 `LICENSE` 文件中，源代码可在 [GitHub 仓库](https://github.com/Osiris-DevWorks/smart-citizen) 获取。

除非适用法律要求或经书面同意，根据本许可证分发的软件是按“**原样**”提供的，不附带任何明示或暗示的保证或条件。有关许可证下权限和限制的具体规定，请参阅许可证原文。

## 捆绑的第三方软件

智慧公民的安装程序中捆绑了以下第三方软件。每项的完整署名文本均位于可执行文件旁的 `NOTICE` 文件中。

- **unp4k / unforge** —— 捆绑于 `assets/unp4k/`，即 `unp4k.exe` 和 `unforge.exe`。Osiris DevWorks 提供自己的分支（[odw-fast-unp4k](https://github.com/Osiris-DevWorks/odw-fast-unp4k)），基于原始的 [dolkensp/unp4k](https://github.com/dolkensp/unp4k) 项目，带有并行提取和性能改进。用于解包 `Data.p4k` 并将 DataForge 实体文件转换为 XML。采用 **MIT 许可证**。
- **PyQt6** —— 图形界面框架，由 Riverbank Computing 提供。非商业分发采用 **GNU 通用公共许可证 v3（GPL-3.0）**；Riverbank 也提供商业许可。智慧公民是免费的开源社区工具，符合 GPL-3.0 条款。
- **lxml** —— XML 解析库，由 lxml.de 提供。采用 **BSD-3-Clause 许可证**。

由 PyInstaller 捆绑的 Python 标准库及其他运行时依赖项各自拥有自己的许可证；请参阅 Python 软件基金会许可证 [docs.python.org/3/license.html](https://docs.python.org/3/license.html)。

## 隐私与数据处理

智慧公民是一款**本地桌面应用程序**。它不会将你的编辑内容、`user.ini`、`base.ini`、自定义内容或电脑中的任何其他内容传输到 Osiris DevWorks 或任何第三方运营的服务器。

### 保留在你电脑上的内容

一切内容。你的本地化编辑、备份、应用设置和 DataForge 缓存均仅存放在你的本地磁盘上：

- **设置** —— 默认安装方式下位于 Windows 注册表 `HKEY_CURRENT_USER\Software\Osiris DevWorks\Smart Citizen`；便携版则位于可执行文件旁的 `config.json`。
- **用户编辑内容与备份** —— 默认位于 `文档\Smart Citizen\{频道}\`（可在配置标签页中修改；便携版则使用 `<可执行文件目录>\data\`）。
- **DataForge XML 缓存** —— `%LOCALAPPDATA%\Smart Citizen\{频道}\cache\dataforge\`。
- **崩溃转储与手动导出的日志** —— `文档\Smart Citizen\logs\`（或便携版对应位置），仅在应用崩溃或你在日志标签页点击“导出”时才会写入。

### 通过网络传输的内容

智慧公民仅在以下三种情况下发出出站网络请求：

- **更新检查** —— 大约每 6 小时向 `api.github.com/repos/Osiris-DevWorks/smart-citizen/releases/latest` 发送一次小型的未经身份验证的请求，以比较已安装版本与最新 GitHub 发布版本。仅返回发布元数据（标签名称、发布页面地址）；不会发送任何智慧公民的状态数据。
- **语言下载** —— 当你切换到非英语语言时，智慧公民会从配置的地址下载该语言社区翻译的 `global.ini`（默认来自 [Dymerz/StarCitizen-Localization](https://github.com/Dymerz/StarCitizen-Localization) GitHub 仓库）。下载内容会在本地缓存；你机器上的任何内容都不会被发送出去。
- **用户自定义的远程来源** —— 如果你在配置标签页中配置了指向 `http(s)://` 地址的数据来源，智慧公民会在刷新源文件时获取该地址。默认情况下，这仅适用于 `global` 来源的 GitHub-raw 地址形式；自 v1.0 起，标准配置改为从你本地的 Data.p4k 提取内容中读取 `base.ini`。

### 智慧公民**不会**做的事

- 不进行任何形式的遥测、分析或使用情况报告。
- 不收集、存储或传输任何个人身份信息。
- 不进行后台数据上传。
- 不向远程服务器自动上报崩溃——崩溃转储**仅在本地**写入 `文档\Smart Citizen\logs\`。如果你想为 Bug 报告分享一份，需要你自己手动复制粘贴该文件。
- 没有账号、没有登录、没有远程身份。

如果你发现有与上述内容不符的行为，请在 [github.com/Osiris-DevWorks/smart-citizen/issues](https://github.com/Osiris-DevWorks/smart-citizen/issues) 提交 Bug 报告。

## AI 使用声明

智慧公民的部分源代码是在 Anthropic 的 AI 编程助手 **Claude** 的协助下编写的。生成的代码在合并前**由人类维护者审阅并批准**——AI 不会直接提交代码，其待遇与任何其他代码贡献相同：经过阅读、测试后再基于其本身价值决定是否采纳。

具体而言：

- AI 协助加速了生成器、分类器、重构和测试的开发；由 AI 协助编写的提交在提交信息中带有 `Co-Authored-By: Claude` 尾注，因此历史记录可供审计。
- 所有《星际公民》游戏数据解析逻辑、任务分类和字符串处理规则均由人类维护者设计，并针对真实的 DataForge 缓存样本进行验证。
- 智慧公民的部分界面和文档翻译是 AI 生成的占位翻译，直到有人类翻译到来为止。这些内容会按语言、按字符串在 `languages/TRANSLATIONS.md` 中进行追踪，并在人类翻译完成后被替换。现有的人类翻译永远不会被 AI 修改。
- **应用程序本身不包含任何 AI 或机器学习功能。** 智慧公民不捆绑任何模型，运行时不调用任何 AI 服务，也不会将你的编辑内容或《星际公民》游戏数据传输给任何 AI 提供商。

## 报告法律相关问题

如果你认为智慧公民侵犯了你持有的版权、商标或其他权利——或者你对该应用如何处理你的数据有疑问——请提交 issue，或通过 [Osiris DevWorks Discord](https://discord.gg/BNzRegKZ7k) 联系维护者。
