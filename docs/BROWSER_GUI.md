# Phase 0 Browser GUI

CLIで行っていた繰り返し作業を、ローカルブラウザから操作するためのGUIです。

## セットアップ

既存の仮想環境を有効にして、依存関係を更新します。

```powershell
cd phase0_proto
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Reverb Token は従来どおり環境変数で設定します。ブラウザへTokenを入力・保存する方式にはしていません。

```powershell
$env:REVERB_API_TOKEN="YOUR_TOKEN"
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

- Dashboard
  - Observations
  - Serial Observations
  - Serial extraction rate
  - Individuals
  - Repeated Individuals
- Batch Crawl
  - 複数のReverb検索クエリを1回で順次実行
  - queryごとのlimit指定
  - detail APIのworker数指定
  - 既取得Listingの自動スキップ
  - 進行状況とquery別結果の表示
- Vintage Audit
  - 保存せずにReverb summaryを分類
  - vintage / modern / unknown / non_target の件数と理由を表示
- Individuals
  - Maker / Model / Serialでフィルタ
  - IndividualをクリックしてObservation履歴を表示
- Serial Audit
  - DB内のSerialを現在のextractorで再評価
  - MATCH / CHECK / SUSPICIOUS を表示
  - `XXXX`, `THATDATESTO...`, `DATEBACK...`, `--YOUR` 等の既知の怪しい形式を強調表示
- DBエクスポート
  - 画面右上の「DBエクスポート」から現在のSQLite DBをダウンロード
  - 直接DBファイルをコピーするのではなく、SQLiteのbackup APIで一貫したスナップショットを作成
  - ファイル名は `ygc_chronicle_YYYYMMDD_HHMMSS.db`

## 既定のBatch Query

GUIには現在のPhase 0検証で使っている以下を初期値として入れています。

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
phase0_proto/data/chronicle.db
```

CLIで収集したデータはGUIからそのまま見えます。逆にGUIで収集したデータもCLIの `ygc stats`, `ygc individuals`, `ygc serial-audit` から確認できます。

別環境へ渡す場合は、WebUI右上の **DBエクスポート** を押してください。ブラウザからSQLiteスナップショットをダウンロードできます。エクスポートは元DBを変更しません。

## セキュリティ

GUIはローカル利用を前提として、既定では `127.0.0.1` のみにbindします。

Reverb TokenはHTMLやLocalStorageに保存せず、サーバープロセスの `REVERB_API_TOKEN` 環境変数だけを使用します。

LAN内の別端末から使う必要がある場合のみ、明示的に:

```powershell
ygc-web --host 0.0.0.0
```

としてください。Phase 0には認証機能がないため、外部公開はしないでください。
