# Smart Citizen — 法的情報とコンプライアンス

> このページは情報提供を目的として提供される翻訳です。**正文は英語版です**。相違がある場合は、英語のテキスト（および実行ファイルの隣に同梱される `LICENSE` と `NOTICE` ファイル）が優先されます。

このページは、Smart Citizen に関する法的、ライセンス、およびデータ取り扱いに関するすべての開示事項を 1 か所にまとめたものです。ここに記載された内容が、実行ファイルの隣に同梱される `LICENSE` または `NOTICE` ファイルと矛盾する場合は、それらのファイルが優先されます。

## Star Citizen / Cloud Imperium に関する表示

Smart Citizen は、Star Citizen 向けの**非公式なコミュニティツール**です。Cloud Imperium Games（CIG）または Roberts Space Industries（RSI）によって開発、承認、後援されたものではなく、いかなる形でも提携していません。Smart Citizen は、ファンによる制作物やツールに関する CIG の「Made by the Community」ガイドラインの対象となります。

**Star Citizen®**、**Roberts Space Industries®**、**Cloud Imperium®** は、Cloud Imperium Rights LLC および Cloud Imperium Rights Ltd. の登録商標です。`Data.p4k` の内容、艦船やコンポーネントのモデル、アイテム名、ミッションテキスト、ロアを含む、Star Citizen のすべてのゲームデータは、Cloud Imperium Rights LLC の知的財産です。

Smart Citizen は、CIG または RSI のコンテンツを一切再配布しません。本アプリは、あなたのローカルマシン上にある**あなた自身のライセンス済み Star Citizen インストール**からファイルを読み取り、ユーザーがカスタマイズした文字列を同じインストールに書き戻します。CIG が所有するコンテンツが Smart Citizen を通じてあなたのコンピューターから外に出ることはありません。

## Smart Citizen のライセンス

Smart Citizen は、**Apache License, Version 2.0** の下でライセンスされるオープンソースソフトウェアです。ライセンスのコピーは [apache.org/licenses/LICENSE-2.0](https://www.apache.org/licenses/LICENSE-2.0) で入手できます。ライセンスの全文は実行ファイルの隣にある `LICENSE` ファイルに同梱されており、ソースコードは [GitHub リポジトリ](https://github.com/Osiris-DevWorks/smart-citizen) で入手できます。

適用される法律で要求される場合、または書面で合意された場合を除き、本ライセンスの下で配布されるソフトウェアは、明示または黙示を問わず、**いかなる種類の保証や条件もなく「現状のまま」提供されます**。権限および制限を規定する具体的な文言については、ライセンスを参照してください。

## 同梱されるサードパーティソフトウェア

Smart Citizen は、以下のサードパーティソフトウェアをインストーラー内に同梱しています。それぞれの完全な帰属表示テキストは、実行ファイルの隣にある `NOTICE` ファイルに記載されています。

- **unp4k / unforge** — `assets/unp4k/` に `unp4k.exe` および `unforge.exe` として同梱されています。Osiris DevWorks は、オリジナルの [dolkensp/unp4k](https://github.com/dolkensp/unp4k) プロジェクトの独自フォーク（[odw-fast-unp4k](https://github.com/Osiris-DevWorks/odw-fast-unp4k)）を、並列抽出とパフォーマンス改善を加えて提供しています。`Data.p4k` の展開と、DataForge エンティティファイルの XML への変換に使用されます。**MIT ライセンス**の下でライセンスされています。
- **PyQt6** — GUI フレームワーク、Riverbank Computing 製。非商用配布については **GNU General Public License v3（GPL-3.0）**の下で使用されています。Riverbank から商用ライセンスも入手可能です。Smart Citizen は無料のオープンソースコミュニティツールであり、GPL-3.0 の条件を満たしています。
- **lxml** — XML 解析ライブラリ、lxml.de 製。**BSD-3-Clause ライセンス**の下で使用されています。

PyInstaller によって同梱される Python 標準ライブラリおよびその他のランタイム依存関係は、それぞれ独自のライセンスを持ちます。Python Software Foundation ライセンスについては [docs.python.org/3/license.html](https://docs.python.org/3/license.html) を参照してください。

## プライバシーとデータの取り扱い

Smart Citizen は、**ローカルのデスクトップアプリケーション**です。あなたの編集内容、`user.ini`、`base.ini`、カスタマイズ、その他あなたのコンピューター上のいかなるコンテンツも、Osiris DevWorks または第三者が運用するサーバーへ送信することはありません。

### コンピューターに残るもの

すべてです。あなたのローカライズ編集、バックアップ、アプリケーション設定、DataForge キャッシュは、すべてあなたのローカルディスク上にのみ保存されます。

- **設定** — デフォルトのインストールでは Windows レジストリの `HKEY_CURRENT_USER\Software\Osiris DevWorks\Smart Citizen`、ポータブルビルドでは実行ファイルの隣の `config.json`。
- **ユーザー編集 + バックアップ** — デフォルトでは `Documents\Smart Citizen\{channel}\`（Config タブで設定可能。ポータブルビルドは代わりに `<exe-dir>\data\` を使用）。
- **DataForge XML キャッシュ** — `%LOCALAPPDATA%\Smart Citizen\{channel}\cache\dataforge\`。
- **クラッシュダンプ + 手動のログエクスポート** — `Documents\Smart Citizen\logs\`（またはポータブル相当）。アプリがクラッシュしたとき、または Log タブで *エクスポート* をクリックしたときにのみ書き込まれます。

### ネットワークを経由するもの

Smart Citizen が外部へのネットワークリクエストを行うのは、次の 3 つの場合のみです。

- **アップデート確認** — インストール中のバージョンを最新の GitHub リリースと比較するため、約 6 時間ごとに `api.github.com/repos/Osiris-DevWorks/smart-citizen/releases/latest` へ小さな認証なしのリクエストを送ります。返されるのはリリースのメタデータ（タグ名、リリース URL）のみで、Smart Citizen の状態は一切送信されません。
- **言語のダウンロード** — 英語以外の言語に切り替えると、Smart Citizen は設定された URL（デフォルトでは [Dymerz/StarCitizen-Localization](https://github.com/Dymerz/StarCitizen-Localization) GitHub リポジトリ）から、その言語のコミュニティ翻訳された `global.ini` をダウンロードします。ダウンロードはローカルにキャッシュされ、あなたのマシンからは何も送信されません。
- **ユーザーが設定したリモートソース** — Config タブで `http(s)://` URL を指すデータソースを設定している場合、Smart Citizen はソースファイルの更新時にその URL を取得します。標準状態では、これは `global` ソースの GitHub-raw URL 形式にのみ該当します。v1.0 以降の標準構成では、代わりにローカルの Data.p4k 抽出から `base.ini` を読み込みます。

### Smart Citizen が**しない**こと

- いかなる種類のテレメトリー、分析、利用状況レポートも行いません。
- 個人を特定できる情報の収集、保存、送信は一切行いません。
- バックグラウンドでのデータアップロードは行いません。
- リモートサーバーへの自動クラッシュレポートは行いません。クラッシュダンプは `Documents\Smart Citizen\logs\` に**ローカルにのみ**書き込まれます。バグ報告のために共有したい場合は、あなた自身がファイルをコピー＆ペーストします。
- アカウント、ログイン、リモート ID はありません。

上記に反する動作を発見した場合は、[github.com/Osiris-DevWorks/smart-citizen/issues](https://github.com/Osiris-DevWorks/smart-citizen/issues) にバグ報告を提出してください。

## AI 利用に関する声明

Smart Citizen のソースコードの一部は、Anthropic の AI コーディングアシスタント **Claude** の支援を受けて書かれています。生成されたコードは、**マージ前に人間のメンテナーによってレビューおよび承認されます** — AI が直接コミットすることはなく、他のあらゆるコード貢献と同じように扱われ、読まれ、テストされ、その内容のみに基づいて受け入れられます。

具体的には次のとおりです。

- AI の支援は、ジェネレーター、分類器、リファクタリング、テストの開発を加速します。AI の助けを借りて作成されたコミットには、履歴を監査可能にするため、コミットメッセージに `Co-Authored-By: Claude` トレーラーが付きます。
- Star Citizen のゲームデータ解析ロジック、ミッション分類、文字列処理ルールはすべて人間のメンテナーによって設計され、実際の DataForge キャッシュのサンプルに対して検証されています。
- Smart Citizen のインターフェースおよびドキュメントの翻訳の一部は、人間による翻訳が届くまでのプレースホルダーとして AI によって生成されています。これらは言語ごと・文字列ごとに `languages/TRANSLATIONS.md` で追跡され、人間による翻訳が到着次第、置き換えられます。既存の人間による翻訳が AI によって変更されることはありません。
- **アプリケーション自体には、AI や機械学習の機能は一切含まれていません。** Smart Citizen は、いかなるモデルも同梱せず、実行時にいかなる AI サービスも呼び出さず、あなたの編集内容や Star Citizen のゲームデータを AI プロバイダーに送信することもありません。

## 法的懸念の報告

Smart Citizen があなたの保有する著作権、商標、その他の権利を侵害していると思われる場合、またはアプリがあなたのデータをどのように扱うかについて質問がある場合は、Issue を作成するか、[Osiris DevWorks Discord](https://discord.gg/BNzRegKZ7k) からメンテナーにご連絡ください。
