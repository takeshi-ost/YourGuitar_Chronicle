# Accounts同期Job

更新日：2026-10-04。基本認証試験後、Accounts正本の更新をChronicleへ反映する既存Outbox処理をCloud Run Jobsへ配置した。所有判定の規則やアカウント採番方法を変更しない。

## 実行範囲

`python -m ygc.account_projection_job --limit 100` を実行する。1回で最大100イベントを処理し、`status`・`processed`・`pending`だけをJSONで出力する。アカウントID、名前、メール、トークン、パスワードはログに含めない。失敗時は汎用のfailedをstderrへ出し、終了コード1とする。

Accountsの正本と未反映イベントをロックし、Chronicleへ参加者・反映版・必要なSnapshotをコミットしてからOutboxを完了にする。中断・再実行は同じID／UUIDで再反映する。ID衝突・正本の版後退・Snapshot再評価失敗は未反映を維持して拒否する。複数実行が重なっても、既存のイベントロックと投影ロックを利用する。

`YGC_PLATFORM_TARGET=gcp`、`YGC_DATABASE_BACKEND=postgres`、`YGC_GCP_PROJECT_ID`とPostgreSQL接続設定を明示する。Cloud SQLのプロジェクト不一致、Webサービスとしての起動、複数task設定は拒否する。ローカルSQLite、ダミー認証、DDL、復元後の全件reconcile、Webサーバー、Crawl、バックアップは起動しない。

通常の同期はOperationsのoffline／メンテナンス中も動く内部処理。ChronicleのReset／Restoreを行う際は、定期起動を停止して実行中Jobが終了したことを確認する。reconcileは停止下で行う別の管理操作であり、このJobが自動で不整合を修正した扱いにはしない。

## 配置構成

| 項目 | 設定 |
| --- | --- |
| プロジェクト・リージョン | `your-guitar-chronicle-staging` / `asia-northeast1` |
| Cloud Run Job | `ygc-staging-account-projection` |
| 実行用SA | `ygc-staging-projection@your-guitar-chronicle-staging.iam.gserviceaccount.com` |
| 実行用IAM | プロジェクトのcloudsql.client、DBパスワードsecretだけのsecretAccessor |
| DB接続 | 既存のygc_app、Cloud SQL Unix socket、Secret Manager version 1 |
| リソース | 1 vCPU / 512 MiB、task 1、parallelism 1、300秒、失敗時再試行1回 |
| Scheduler | `ygc-staging-account-projection`、5分間隔、Asia/Tokyo |
| 起動用SA | `ygc-staging-scheduler@your-guitar-chronicle-staging.iam.gserviceaccount.com` |
| 起動用IAM | 当該Jobだけのrun.invoker。DB・Secret Manager・Storageへの権限なし |

実行用SAにはFirebase Auth・Storage権限や鍵ファイルを追加しない。DB内部では既存ygc_appの業務テーブル権限を共有する。SchedulerはOAuthでGoogleのCloud Run v2 jobs:run APIを呼び、公開HTTPエンドポイントや未認証の起動経路は作らない。

5分間隔はステージングの初期設定。処理上限と待ち行列により反映まで時間がかかる場合がある。後続のWebUI移行で、反映待ちの表示と必要な反映速度を確認する。Cloud Run JobとSchedulerの実行は課金対象になり得るため、既存の予算アラートと請求画面で監視する。

## 運用操作

手動実行：

```bash
gcloud run jobs execute ygc-staging-account-projection \
  --project=your-guitar-chronicle-staging --region=asia-northeast1 --wait
```

定期起動の停止・再開：

```bash
gcloud scheduler jobs pause ygc-staging-account-projection \
  --project=your-guitar-chronicle-staging --location=asia-northeast1
gcloud scheduler jobs resume ygc-staging-account-projection \
  --project=your-guitar-chronicle-staging --location=asia-northeast1
```

pauseは既に起動済みのCloud Run実行を停止しない。実行一覧・終了結果はCloud Run JobsのExecutionsで確認する。Schedulerの成功は起動APIの受理であり、実処理成功はCloud RunのExecutionと件数ログで確認する。

再配置は[認証画面と同じビルド手順](CLOUD_RUN_ACCOUNT_STAGING.md)で新しいコンテナを作り、成功したimage digestをJobへ指定する。Jobのcommandはpython、argsは `-m,ygc.account_projection_job,--limit,100`。DB secretは参照として設定し、値を取得しない。WebサービスのimageはこのJob配置によって変更しない。

## 検証

Python532件・JavaScript65件と実PostgreSQLの共通検証が成功。Job入口の不正環境・件数制限・失敗時の秘密非表示を確認した。使い捨てPostgreSQLでは件数上限、空の再実行、2Worker同時実行、衝突時の拒否を追加し、既存の中断再試行・Acquire／Transfer／自己判定禁止／Admin別経路／BANとSnapshot整合も通過した。

実GCPではJob配置後の初回実行 `ygc-staging-account-projection-fk2gq` が成功し、ログはprocessed 1／pending 0。読取り専用の独立照合でも、Accounts登録1件／Chronicle参加者1件／未反映0、ID・UUID・反映版一致、ギター個体0を確認した。Schedulerの手動Runによる起動APIはHTTP 200、そのExecution `ygc-staging-account-projection-btkd7` もprocessed 0／pending 0で成功し、二重登録を生じなかった。

ビルド：`c44c7c21-4f8e-471d-8c95-d7efa0a3ec30`。固定image digest：`sha256:399772bd744d2d349b59b3214d7992b0f44d6b81eabd1110b5c01bdf3b1c1a84`。独立照合に使ったローカルAuth Proxyは終了済み。実ユーザー認証の基本試験は利用者により完了。失効・無効化確認、残りのWebUI/API、画像、Crawl、独立バックアップ／復元は移行対象として残る。

公式手順：[Cloud Run Job作成](https://docs.cloud.google.com/run/docs/create-jobs)、[Schedulerの認証付き定期実行](https://docs.cloud.google.com/run/docs/execute/jobs-on-schedule)。
