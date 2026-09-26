# Phase 1 Browser GUI

CLIで行っていた繰り返し作業を、ローカルブラウザから操作するためのGUIです。

## セットアップ

既存の仮想環境を有効にして、依存関係を更新します。

```powershell
cd phase1_proto
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Reverb Token は2通りの方法で設定できます。

1. WebUI右上の **Token設定** から入力して保存
2. 従来どおり環境変数 `REVERB_API_TOKEN` を設定

WebUIで保存したTokenを優先し、未設定の場合は環境変数を使用します。

WebUI保存時のTokenはブラウザの `localStorage` に保存され、SQLite DBやGitHubには保存されません。

環境変数を使う場合:

```powershell
$env:REVERB_API_TOKEN="YOUR_TOKEN"
```

macOS / Linux:

```bash
export REVERB_API_TOKEN="YOUR_TOKEN"
```

## 起動

```powershell
ygc-web
```

通常はブラウザが自動的に開きます。

手動で開く場合:

```text
http://127.0.0.1:8765
```

ブラウザを自動起動しない場合:

```powershell
ygc-web --no-browser
```

## GUIでできること

- Token設定
  - Reverb Personal Access TokenをWebUIへ貼り付けて保存
  - 同じブラウザではWebUI再起動後も保持
  - SQLite DBやGitHubには保存しない
  - WebUI保存Tokenを優先し、なければ環境変数を使用
  - 「削除」でブラウザ保存Tokenを消去
- Dashboard
  - Observations
  - Serial Observations
  - Serial extraction rate
  - Individuals
  - Repeated Individuals
- Batch Crawl
  - 複数のReverb検索クエリを1回で順次実行
  - クエリ入力欄は横幅いっぱいに表示し、その下に Year Min / Year Max / Limit / Workers / Start Crawl を1行で配置
  - Reverb APIの `year_min` / `year_max` を検索段階で適用
  - 既定では Year Max = 1980。空欄にするとその側のYear制限を無効化
  - queryごとのlimit指定
  - detail APIのworker数指定
  - 既取得Listingの自動スキップ
  - 進行状況とquery別結果の表示
- Individuals
  - Maker / Model / Finish / Year / Serialでフィルタ
  - ID / Maker / Model / Finish / Year / Serial / Obs の各列ヘッダーをクリックして昇順・降順ソート
  - 一覧にModel / Finish / Yearを表示
  - Individualをクリックすると、Individualと各ObservationのModel / Finish / Yearを表示
  - Detailを「最新Observation」と「履歴」に分け、Observationをカード表示
  - Detail上部ではIDを表示せず、Finish / Year / Serial / Current Ownerを独立項目として表示
  - Current Ownerは最新ObservationのOwnerを使用。将来user型OwnerにプロフィールURLが付いた場合はプロフィールリンクとして表示できる構造
  - 最新Observation領域は情報量増加に備えて縦スクロール対応
  - 各カードに日付 / Owner / Shop（Ownerと異なる場合）/ Listing / Info / Sourceを表示
  - Reverb由来ObservationではShop名をOwnerとして保持し、将来のユーザー由来Observationではユーザー名をOwnerとして扱えるよう `owner_name` / `owner_type` を保持
  - Detail上部に最新ObservationのReverb代表画像を1枚表示
  - 画像本体はYGCへ保存せず、ObservationにはReverb側の画像URLだけを保存
  - Detail内のSource URLは最新Observationだけハイパーリンク化し、過去ObservationのURLは参照用テキストとして表示
  - 「既存DBバックフィル」は今回のメタデータ移行用。Reverb Listingを再取得して既存ObservationへModel / Finish / Year / image URLを補完し、Individualへ同期
- DBエクスポート
  - 画面右上の「DBエクスポート」から現在のSQLite DBをダウンロード
  - 直接DBファイルをコピーするのではなく、SQLiteのbackup APIで一貫したスナップショットを作成
  - ファイル名は `ygc_chronicle_YYYYMMDD_HHMMSS.db`
- DBインポート
  - 画面右上の「DBインポート」から、別環境でエクスポートしたYGC SQLite DBを選択
  - 現在のDBを選択したDBで置き換える
  - SQLite形式、整合性、YGC必須テーブル・主要カラムを確認してから置換
  - 100 MBを上限とし、Crawlやバックフィル実行中はインポート不可
  - インポート後に現在のスキーマ migration を自動適用し、Dashboard / Individuals を再読み込み
  - インポート前に必要なら現在のDBをエクスポートしてバックアップする
- DB初期化
  - 画面右上の「DB初期化」からObservation / Individual / Crawl履歴をすべて削除
  - 誤操作防止の確認ダイアログと `RESET` 入力が必要
  - Crawl実行中は初期化不可
  - 初期化後は空のSQLite DBを自動再作成

## 既定のBatch Query

GUIには現在のPhase 1検証で使っている以下を初期値として入れています。

```text
Fender Stratocaster
Fender Telecaster
Fender Jazzmaster
Fender Jaguar
Gibson Les Paul
Gibson SG
Gibson ES-335
```

## データ

GUIはCLIと同じSQLite DBを使用します。

```text
phase1_proto/data/chronicle.db
```

CLIで収集したデータはGUIからそのまま見えます。逆にGUIで収集したデータもCLIの `ygc stats`, `ygc individuals`, `ygc serial-audit` から確認できます。

別環境へ渡す場合は、WebUI右上の **DBエクスポート** を押してください。ブラウザからSQLiteスナップショットをダウンロードできます。エクスポートは元DBを変更しません。

## セキュリティ

GUIはローカル利用を前提として、既定では `127.0.0.1` のみにbindします。

WebUIで設定したReverb Tokenはブラウザの `localStorage` に保存され、APIリクエスト時だけローカルYGCサーバーへ送信されます。SQLite DBやGitHubには保存されません。ブラウザのlocalStorageは平文相当の保存領域なので、共有PCでは使用せず、必要に応じてWebUIの「Token設定 → 削除」で消してください。

環境変数 `REVERB_API_TOKEN` も引き続き利用できます。WebUI保存Tokenがある場合はそちらを優先します。

LAN内の別端末から使う必要がある場合のみ、明示的に:

```powershell
ygc-web --host 0.0.0.0
```

としてください。Phase 1には認証機能がないため、外部公開はしないでください。


## Reverb Year Filter

Reverb Listings API の検索パラメータ `year_min` と `year_max` を利用します。

Phase 1では WebUI の既定値を次のようにしています。

```text
Year Min: 空欄
Year Max: 1980
```

YearフィルターはReverb側で候補を絞るための一次フィルターです。
取得後もYGCのVintage classifierを通し、復刻モデルや不整合データを二次チェックします。

Year情報が未設定・不正確なListingはReverb側のYear検索から漏れる可能性があるため、
網羅性を確認したい場合はYear Min / Maxを空欄にして従来方式でも取得できます。


## Model / Finish / Year metadata migration

新規CrawlではReverb Listingの構造化フィールドから以下をObservationへ保存します。

```text
model
finish
year
```

Serialを持つObservationからGuitar Individualを作成する際にも同じ情報をIndividualへ保持します。

既存DBはWebUI起動時にスキーマだけ自動移行され、`finish` / `year` カラムが追加されます。既存行の値を埋めるには、今回のみ **Individuals → 既存DBバックフィル** を実行してください。

バックフィルは保存済みReverb Listing IDを使ってListing詳細を再取得し、構造化されたModel / Finish / YearをObservationへ保存した後、Individualへ同期します。既に値があるIndividualメタデータは上書きせず、不足値だけ補完します。

バックフィル後は通常このボタンを再実行する必要はありません。今後の新規Crawlでは自動的に同じ情報が保存されます。


## WebUI simplification

Vintage Audit と Serial Audit はPhase 1の初期検証で役割を果たしたため、WebUIからは削除しました。
内部のVintage分類とSerial抽出処理はCrawl時に引き続き使用されます。


## 複数環境でのDB移動

PC間で同じChronicle DBを使う場合は、元環境で **DBエクスポート** を実行し、移動先のWebUIで **DBインポート** を実行してください。

DBインポートはマージではなく、移動先の現在DBを選択したエクスポートDBで置き換えます。
そのため、両方の環境で別々にCrawlしたDBを自動統合する用途ではありません。
現在のDBを残したい場合は、インポート前に必ずエクスポートしてください。


## One-click launcher

WebUIの確認手順を短縮するため、リポジトリ直下に起動スクリプトを用意しています。

macOS:

```bash
./start_webui.command
```

Finderから `start_webui.command` をダブルクリックして起動することもできます。初回のみ実行権限が必要な場合は:

```bash
chmod +x start_webui.command
```

Windows:

```text
start_webui.bat
```

をダブルクリックします。

どちらのスクリプトも、現在チェックアウト中のブランチに対して `git pull --ff-only` を実行し、`phase1_proto/.venv` がなければ作成、依存関係を更新してから `ygc-web` を起動します。

ブランチ切り替えは自動では行いません。検証したいブランチへ一度 `git switch <branch>` した後は、そのままランチャーを繰り返し利用できます。


## External listing images

Observationには代表画像のURLだけを `image_url` として保持します。画像データ自体はSQLite DBやGitHubには保存しません。

新規CrawlではReverb Listing詳細の先頭画像URLを保存します。既存DBは **既存DBバックフィル** を実行すると、Model / Finish / Yearとあわせてimage URLも補完されます。

画像は参照元のReverb URLからブラウザが直接読み込みます。そのため、参照元Listingや画像URLが将来無効になった場合はYGC上でも表示できなくなる可能性があります。


## Observation Owner

Observationは、観測時点でその個体を扱っていた主体を `owner_name` / `owner_type` として保持します。

現時点のReverb Observationでは、Reverb ListingのShop名を `owner_name`、`owner_type=shop` として保存します。既存DBも起動時migrationで、Reverb Observationの既存 `seller` 値からOwnerを補完します。

将来ユーザー投稿Observationを追加する場合は、ユーザー名を `owner_name`、`owner_type=user` として保存できる設計です。`seller` はマーケットプレイス上の販売主体というSource固有メタデータとして残し、Ownerとは別フィールドにしています。
