# Cloud SQLへの接続確認と初期化

更新日：2026-10-04。Cloud SQLの4DB初期化と制限付きアプリユーザーによる確認が完了。ローカルの実DBを移送しない。

## 実接続で確認したこと

- `your-guitar-chronicle-staging:asia-northeast1:ygc-staging-db` はRUNNABLE／POSTGRES_18。
- 公式Cloud SQL Auth Proxy 2.26.0のmacOS arm64版を一時領域に取得し、既存gcloudユーザー認証・127.0.0.1:55432で接続した。
- Secret Manager `ygc-staging-db-password` のversion 1をメモリ内だけで取得して使用し、`ygc_app` で4DBすべてに接続できた。値を表示・ファイル保存・文書記載していない。
- 読取り専用トランザクションで、各DBのpublicテーブル数が0、ygc_appのrolcreatedb／rolcreaterole／rolsuperがfalseであることを確認した。以前のcloudsqlsuperuser所属falseの確認はSQL Studioのユーザー報告に基づく。
- 認証APIの失効・無効化確認用に、`firebaseauth.users.get` だけを含むプロジェクト独自ロール `ygcIdentityTokenVerifier` を作成し、アプリ実行用サービスアカウントへ付与した。ロール定義とIAM割当てを取得して確認済み。実行用資格での実token検証はまだ行っていない。

接続試験ではDBへ変更を書き込んでいない。通常のアプリ起動にスキーマ初期化を混ぜない。postgres所有者のパスワードはアプリ用シークレットと別であり、チャットで取得しない。

## 初期化CLIの修正

既存CLIのmigrate分岐は、パスワード入力なしでは設定読込み前に実行してエラーとなり、入力ありではstatusへ分岐して移行を実行していなかった。分岐を修正した。

新しい `initialize` は、パッケージ内の全移行のチェックサム・順序を確認した後、4DBそれぞれのbootstrap・migrate・statusを順番に実行する。パスワードは1回だけ非表示入力する。初期化と更新は各DB内でコミットするため、4DBを一括でロールバックする操作ではない。途中失敗は、接続・権限・スキーマを確認して同じコマンドを再実行する。既存の版・データを上書きしない。未知の構造は拒否する。

期待版はChronicle 2、Accounts 2、Operations 1、Authentication 1。Operationsはoffline、Auto Crawl・GPT反映・定期バックアップはOFFの初期状態。ユーザーや個体の試験データは投入しない。

## ユーザーが非表示入力して実行する手順

CLI修正を含む最新版で実行する。プロジェクトのルートから、まずアプリ用venvへ固定依存を入れる。

```bash
app/.venv/bin/python scripts/install_dependencies.py --postgres --identity
```

ターミナル1でProxyを起動し、このターミナルは起動したままにする。

```bash
/private/tmp/ygc-cloud-sql-proxy-2.26.0 --gcloud-auth --address=127.0.0.1 --port=55432 your-guitar-chronicle-staging:asia-northeast1:ygc-staging-db
```

一時ファイルがなくなった場合、公式案内のMac M1版2.26.0を同じ場所へ取得する（Intel Macはdarwin.amd64版）。

```bash
curl --fail --location https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.26.0/cloud-sql-proxy.darwin.arm64 --output /private/tmp/ygc-cloud-sql-proxy-2.26.0
chmod +x /private/tmp/ygc-cloud-sql-proxy-2.26.0
```

別のターミナル2で以下を実行する。`Database password (not saved):` に、インスタンス作成時の**postgresユーザーのパスワード**を入力する。文字が表示されなくても入力されている。環境変数やコマンド引数へパスワードを記載しない。

```bash
YGC_POSTGRES_HOST=127.0.0.1 YGC_POSTGRES_PORT=55432 YGC_POSTGRES_USER=postgres app/.venv/bin/python -m ygc.db.postgres initialize --password-prompt
```

結果は各DBのtarget・version・tables・initialized・appliedを含むJSON。初回は通常initialized=true、途中からの再開や再実行は対応する対象でfalseとなる。appliedはAccounts／Chronicleで初回 `[2]`、移行済みなら `[]`。テーブル初期化後、エージェントがアプリ用シークレットで4DBのstatusと権限を再確認する。

完了したらターミナル1のProxyをCtrl+Cで停止する。postgresパスワードを忘れた場合はCloud SQL Consoleでpostgresのみ再設定してから実行する。ygc_appのパスワードや権限を変更する必要はない。

## 検証と残る作業

Python513件・JavaScript65件と使い捨てPostgreSQL 18の統合検証が通過。実CLI経由で部分初期化からの再開、全対象の移行、再実行での既存データ保持、migrateの実行を確認した。依存整合・スキーマ生成物・actionlintも通過。CLIのみの変更のため今回はブラウザを再実行していない。

認証確認画面用の起動設定・コンテナ・Cloud Run配置、実認証、Chronicle投影Worker、現行WebUIの移植はまだ残る。

関連：[スキーマ仕様](POSTGRES_BOOTSTRAP.md)、[構築状況](GCP_STAGING_SETUP.md)。公式参照：[Cloud SQL Auth Proxy](https://docs.cloud.google.com/sql/docs/postgres/connect-auth-proxy)、[Identity Platformの権限](https://docs.cloud.google.com/identity-platform/docs/access-control)。

## 実Cloud SQLの初期化完了（2026-10-04）

ユーザーがpostgresパスワードをターミナルで非表示入力し、initializeを実行。4対象すべてinitialized=true、Accounts／Chronicleの002移行適用を報告した。その後、エージェントがygc_appとSecret Manager version 1で接続し、読取り専用トランザクションで以下を独立確認した。

| DB | 版 | 業務テーブル数 | 確認結果 |
| --- | --- | --- | --- |
| Chronicle | 2 | 42 | 個体0・参加者0 |
| Accounts | 2 | 8 | アカウント0 |
| Operations | 1 | 7 | offline、Auto Crawl・GPT反映・定期バックアップOFF |
| Authentication | 1 | 3 | スキーマ一致 |

各対象のSQLチェックサムとテーブル／列構造が配布定義に一致し、全業務テーブルのSELECT／INSERT／UPDATE／DELETE権限があることを確認した。publicスキーマのCREATEとスキーマ版テーブルのUPDATEは許可されていない。テーブル数はygc_schema_versionを除く。ユーザー・ギター・ローカルデータの移送は行っていない。

これは実DB接続・スキーマ・付与権限・初期値の確認であり、Cloud Run配置や実Googleユーザーによる認証・アプリ操作の成功を示すものではない。接続確認用の一時Proxyは確認後に停止した。
