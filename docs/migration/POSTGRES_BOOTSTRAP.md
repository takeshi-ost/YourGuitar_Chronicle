# PostgreSQL接続・初期スキーマ

更新日：2026-10-04。PR #19までmain統合済みの移行基盤。WebUIは引き続きSQLiteを使い、Cloud Runでローカル実装を拒否する起動制限も維持している。

## 今回の実装範囲

`ygc.db.postgres` はCloud SQLのUnix socket、またはローカルのCloud SQL Auth Proxyへの接続と、4つの新規DBの初期化を提供する。`chronicle`、`accounts`、`operations`、`authentication` を個別に扱い、初期化を通常のアプリ起動から分離する。AuthenticationはGPT実験用で、Identity Platformのユーザー認証とは別。

初期化はPostgreSQL 18以降・空のpublicスキーマが対象。DBそのものと `ygc_app` の作成は事前に必要。別のスキーマ所有者で実行し、対象DBごとのトランザクションと排他ロックでテーブル・制約・索引・判定保護トリガー・権限・バージョン記録を作成する。通常ユーザーにはデータの読書きとシーケンス使用を許可し、テーブル作成とバージョン書換えは許可しない。

再実行時には初期値やデータを上書きせず、バージョン・SQLチェックサム・テーブル名／列名を照合する。既存の未バージョンDBや構造差は拒否する。これは初期化処理であり、リセット・バックアップ復元の機能ではない。既存DBの更新は明示的なmigrateコマンドで行う。制約や索引の手動変更を網羅して検出する監査機能でもない。4つのDBを横断した一括トランザクションは提供しない。

初期Operationsはoffline、Auto Crawl・GPT回答反映・定期バックアップはOFF。ユーザー・ギター・試験データや旧ローカルDBは投入しない。

## ローカル検証

依存を固定して導入する。

```bash
python scripts/install_dependencies.py --postgres
python scripts/build_postgres_schema.py --check
python scripts/run_tests.py --postgres-bin /path/to/postgresql18/bin
```

`--postgres-bin` は一時クラスタを作成・停止・削除する。CIは専用PostgreSQLサービスに `--postgres-port 5432` で接続し、ランダム名の試験DB・試験ロールだけを作成／削除する。GCP、実DB、ローカルの資格情報には接続しない。ブラウザも含める場合は依存導入に `--browser`、実行に `--browser` を追加する。

検証対象は4スキーマの生成・再実行・既存データ保持、実行用権限、UUID更新／削除禁止、外部キー・JSON・係争中の変更禁止、初期の運用停止状態、列構造差の拒否。[Accounts同期・所有判定のDB層](POSTGRES_ACCOUNT_SYNC.md)も追加し、Owner VerificationとTransferはSQLite・PostgreSQLの両方で検証する。WebUI全体の移植が完了したという意味ではない。

## Cloud SQLで初期化するとき

2026-10-04、実Cloud SQLの4DBで初期化を実行済み。Accounts／Chronicleは002、Operations／Authenticationは001で、制限ユーザーの権限とスキーマ一致も確認済み。接続確認と、パスワード入力1回で4対象を処理する新しいinitialize手順は[Cloud SQL初期化](CLOUD_SQL_INITIALIZATION.md)を参照。以下は対象別に処理する場合のコマンド。Cloud SQL Auth Proxyで `your-guitar-chronicle-staging:asia-northeast1:ygc-staging-db` への接続を用意した後、以下を実行する。ProxyのIAM認証と、DBユーザーのパスワード認証は別。

```bash
export YGC_POSTGRES_HOST=127.0.0.1
export YGC_POSTGRES_PORT=5432
export YGC_POSTGRES_USER=postgres
export YGC_POSTGRES_PREFIX=ygc_
python -m ygc.db.postgres bootstrap --target chronicle --password-prompt
python -m ygc.db.postgres bootstrap --target accounts --password-prompt
python -m ygc.db.postgres bootstrap --target operations --password-prompt
python -m ygc.db.postgres bootstrap --target authentication --password-prompt
python -m ygc.db.postgres migrate --target accounts --password-prompt
python -m ygc.db.postgres migrate --target chronicle --password-prompt
```

非表示入力にはDB所有者 `postgres` のパスワードを使う。チャット・コマンド引数・履歴・文書にパスワードを貼らない。各DBで `initialized: true` が返れば作成済み、同じスキーマの再実行は `false`。権限が不足する場合は所有者側で修正し、`ygc_app` に管理者権限を戻さない。

その後 `YGC_POSTGRES_USER=ygc_app` に変更し、4対象について `python -m ygc.db.postgres status --target chronicle --password-prompt` などを実行する。こちらはアプリ用パスワードを使い、スキーマの読取りを確認する。Secret Manager値と実パスワードの一致も別途接続時に確認する。

## スキーマの保守と残作業

`app/src/ygc/db/postgres/*_001.sql` と `manifest.json` は、空の隔離SQLite DBの定義から `scripts/build_postgres_schema.py` で生成する。PostgreSQL固有の保護・初期値は同じフォルダの `*_guards.sql` を使う。実データを読み込まない。CIで `--check` による生成物の一致も確認する。

既に初期化したDBに合わせて001を書き換える運用はしない。002はAccountsの更新版・OutboxとChronicleの反映版・ID保護を追加する。移行ファイルとmigration_manifest.jsonを別途管理し、SQLチェックサムと順序を照合する。今後の変更も明示的な次バージョン移行として追加する。

AccountsとChronicleのDB間同期、およびOwner Verification／TransferのDB層は追加済み（詳細は[同期と所有判定](POSTGRES_ACCOUNT_SYNC.md)）。WebUI全Repository・残るSQLite固有SQL、独立バックアップ／復元／リセット、Identity Platform、Cloud Storage、ジョブは未移植。Cloud Runに配置する前にこれらと管理者・メンテナンス権限を実装し、クラウドで再検証する。[GCP境界](GCP_BOUNDARIES.md)、[構築状況](GCP_STAGING_SETUP.md)を参照。
