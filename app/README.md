# Your Guitar Chronicle — ローカル試作

ギター個体の来歴をClaim中心に保存・表示するFastAPI + SQLiteのローカルアプリ。公開サービス向けの本人確認・権限検査はまだない。Reverbからの収集は公式APIを使う。設計と現行機能は [ドキュメント一覧](../docs/README.md) を参照。

## 開始

Python 3.12以降を用意して、この `app` ディレクトリで実行する。

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
python ../scripts/install_dependencies.py
```

## テスト

Python・JavaScript・ブラウザ検証、データ隔離と後片付けは[開発・検証手順](../docs/development/DEVELOPMENT_WORKFLOW.md)を参照。リポジトリ直下で `app/.venv/bin/python scripts/run_tests.py` を実行する。

macOSはリポジトリ直下の `start_webui.command`、Windowsは `start_webui.bat` でも起動できる。手動起動は次の通り。

```bash
ygc init-db
ygc-web
```

表示されたlocalhostのURLを開く。`/` は管理用Browser Console、`/user-view` はゲストも閲覧できるTop Page。`ygc-web` はローカルダミー認証・アカウントDB分離モードで起動する。初回起動時に既存DBの安全用コピーを保存して移行し、以後は `accounts.sqlite` とChronicleを独立してバックアップ／復元できる。テストユーザーの選択で認証成功を代用するため、実際の本人確認を行うものではない。Browser Consoleの管理トークンは同じプロセス・localhostでだけ有効。

CLIや `uvicorn ygc.web:app` も同じデータを扱う場合は `YGC_IDENTITY_BACKEND=local_dummy` を設定する。分離前の互換動作は `ygc-web --identity-backend prototype` で利用できるが、分離済みデータでは拒否する。詳しい保存対象・移行条件は [ローカル認証とアカウント分離](../docs/migration/GCP_BOUNDARIES.md#ローカル実装アカウント分離とダミー認証) を参照。

## Reverbの収集

Reverb Personal Access Tokenを読み取りに必要な最小権限で用意し、Browser Consoleのトークン欄、または環境変数 `REVERB_API_TOKEN` に設定する。トークンをGitにコミットしない。

- **Manual Crawl:** ボタンからモーダルを開き、任意の検索語を1行ずつ入力する。
- **Incremental Crawl:** Electric + Acoustic Guitarsを一括対象とし、製造年範囲を指定してCrawl Nowを押すたびに次へ進む。1回の一覧処理は最大2000件。対象候補の詳細に別の件数上限はない。
- **保存済み詳細を再判定:** 保存したReverbレスポンスをネットワークアクセスなしで再抽出・照合する。
- CLIで1ステップ進める場合は `ygc crawl-step --category electric_acoustic --year-min 1950 --year-max 1980`。

収集の条件・再開・統計の定義は [incremental-crawl.md](../docs/features/incremental-crawl.md)。古いDBは収集前に `ygc claim-status` でreadinessを確認し、必要ならバックアップ後 `ygc migrate-claims` を実行する。管理画面のDB初期化・復元操作はバックアップを確認してから行う。`ygc init-db` は既存DBの初期化・互換列追加を行う。

現在値は共通Observation評価器から生成する。`ygc audit-observation-migration --sample-limit 20` は保存済みSnapshotと再評価結果、掲載・取得日のEvidence欠損を読み取り専用で照合する。`claim-status` は起動時のスキーマ更新を含むため、完全な読み取り専用監査とは異なる。旧DBのEvidence複写と互換処理の整理手順は [Observation移行の残作業](../docs/migration/TEMP_OBSERVATION_MIGRATION_PLAN.md) を参照。

`ygc show ID` はClaimによる来歴を表示する。旧履歴オプションは廃止済み。個体詳細APIは旧 `observations` を返さず、作成APIは旧Observation IDの代わりにClaim IDを返す。Claim編集は旧履歴に同期しない。

未登録クロール記録は、バックアップ後に `ygc archive-unregistered-crawl` で全列を専用保管先へ複写できる。元行の削除・上書きは行わず、不一致時は複写全体を取り消す。まずDBコピーで確認する。保管先には期限を設けず、元行がなくても既知Listing判定と公開状態確認に使用できる。

新規の未登録記録は `crawl_unregistered_records` に入力全体を保存し、旧Observationを作成しない。`ygc stats` は旧行数ではなく、既知外部掲載数・シリアル付き登録掲載数・その比率を表示する。詳細な集計定義と旧APIの撤去内容は上記の移行文書を参照。

## ローカルデータと設定

既定のSQLiteは `app/data/chronicle.db`、画像は `app/data/media` に保存される。保存先は `YGC_DATA_DIR` / `YGC_DB_PATH`、Reverbへの間隔は `YGC_REQUEST_DELAY` などで変更できる。**Chronicle DBとコンテンツ画像は一緒にバックアップする**。User Accountsはaccounts.sqliteとaccount_mediaを別対象として保存・復元する。管理画面のエクスポート／復元はローカル試作用である。

Cloud Runではこの構成を動かさず、未実装のGCPアダプターを要求して起動を止める。交換箇所と残作業は [GCP_BOUNDARIES.md](../docs/migration/GCP_BOUNDARIES.md)。

## 開発環境の管理

[開発・検証手順](../docs/development/DEVELOPMENT_WORKFLOW.md)に依存固定・更新方法、PR自動チェック、mainの保護設定、残る検証範囲をまとめている。
