# クラウドDB別バックアップの保存基盤

2026-10-05。Crawl移植の前提として、DBごとの論理スナップショット保存と読み戻し検証、Consoleの保存履歴を追加した。定期保存・保持世代の削除・復元・リセットは本段階に含めない。Crawlは引き続き未接続。

## 保存単位と入口

`chronicle`、`accounts`、`operations`、`authentication`を個別に指定する。一度の実行で4DBをまとめて保存しない。Crawl前の保存はChronicleだけを使う予定。User AccountsはCrawlの頻度で保存しない。OperationsとAuthentication experimentの保存は任意の管理用途で、Google Identity Platformの認証アカウント保存とは異なる。

IAM専用Cloud Run Job `ygc-staging-db-backup` を単一タスク・retry 0で実行する。Jobの既定操作はChronicleの最新保存の検証だけ。保存する際は対象を指定した引数上書きを明示する。HTTPの保存／復元APIや公開Invokerを設けず、Schedulerにも接続しない。

```sh
# Chronicleだけを保存
 gcloud run jobs execute ygc-staging-db-backup \
   --project=your-guitar-chronicle-staging --region=asia-northeast1 \
   --args=-m,ygc.cloud_backup_job,--confirm-project=your-guitar-chronicle-staging,--target=chronicle \
   --wait

# Accountsだけを保存する場合は上記のtarget=chronicleをtarget=accountsへ変更する。
# 最新保存を検証するだけ（既定操作）
 gcloud run jobs execute ygc-staging-db-backup \
   --project=your-guitar-chronicle-staging --region=asia-northeast1 --wait
```

上書き実行には通常のJob実行より広いIAM権限が必要な場合がある。Jobは明示プロジェクト一致、単一タスク、Webサービス内実行禁止、GCP/GCSの明示設定、Storage Emulator禁止を確認してから接続する。資格情報・データ本文・内部例外はログへ出さない。処理段階だけを記録し、失敗箇所を切り分ける。

## 保存内容と検証

対象DBだけをREPEATABLE READ / READ ONLYで読み、パッケージ内の既知スキーマ版・チェックサムと実テーブル／カラムを照合する。全業務テーブルの値と採番状態をgzip形式のJSON Linesへ保存する。TIMESTAMPTZは時刻精度とタイムゾーンを保持した型付き値、DB内BYTEAは型付きBase64で保存し、通常の文字列と区別する。DDLや実行するSQLを保存／受け付ける方式ではない。テーブルの行数と内容チェックサム、アーカイブ全体のSHA256を記録する。

1レコード最大8MiB、展開後合計128MiB、圧縮後25MiB。保存上限を超えたDBでは失敗し、成功として台帳へ記録しない。現段階の小規模ステージング用上限であり、大規模DBのバックアップを保証しない。SQL実行30秒・ロック待ち2秒、Jobの実行時間上限も設ける。検証は展開サイズを制限して逐次読み、ファイル展開やSQL実行をしない。

Chronicleはcontent、他の3対象はaccountsの非公開バケットへ、不変のObjectReferenceで保存する。既存のUUIDキー方式を使い、MIMEはapplication/gzip。画像APIはJPEG参照等の形式を要求するため、バックアップを画像として配信しない。保存後に固定generationで読み戻し、チェックサム一致を確認する。

DB内のBYTEAに格納される根拠等はDBの値として含む。Cloud Storage上の画像実体やGoogle側の認証情報はアーカイブに複写しない。DBにある画像参照は保存する。画像実体は別途保持し、バックアップと画像の保持・復元整合を後続で設計する。現在のクラウドアカウント画像は更新前・削除前の実体を保持しているが、これを全コンテンツ画像の完全復元保証とは扱わない。

シーケンスの値は通常の行Snapshotとは異なり、同時採番で進むことがある。復元時は保存行の最大IDと現在予約済みのIDも考慮し、値を戻して別人へIDを再割当しない設計が必要。JSONの構造・件数・ハッシュ検証は、参照整合や所有状態の復元リハーサルの代わりではない。

## 台帳と失敗時処理

同じ対象の保存はOperationsのadvisory lockで排他する。保存・読み戻し成功後、OperationsのeventsにバックアップUUID、対象、時刻、スキーマ版、件数、SHA256、固定オブジェクト参照とJob executionを記録する。対象DBの業務データは変更しない。Operations自身の保存も、今回の保存台帳を書き込む前のSnapshotとなる。

台帳コミット前の失敗では、新しく作成した世代だけを補償削除する。コミット結果不明時や作成結果不明時は、保存済み参照を壊さないよう候補／孤立オブジェクトを保持する。既存画像・過去バックアップを広範に削除しない。孤立オブジェクト回収・世代保持・Soft deleteの費用管理は後続。

ConsoleのDatabase backupsで対象DBを選択し、保存時刻・スキーマ版・テーブル数・行数を最大50件表示する。確認済みメール・Accounts正本のAdminと操作中の資格再確認を必須とし、メンテナンスでも閲覧できる。オブジェクト参照・ハッシュ・Job内部情報や生データは返さない。この一覧は台帳の保存記録であり、閲覧時に全アーカイブの存在や内容を毎回検証するものではない。

台帳はOperationsにあるため、将来Operationsを復元する際は現在の台帳を保持／再構築する手順が必要。現在の方式だけでOperations復元後に全履歴が自動で戻るとは扱わない。

## 残る接続

Consoleからの手動保存、対象別の定期保存・保持世代、長時間Jobの状態表示、クラウド復元・復元前の安全保存・最新Accounts再投影・ID予約・画像の整合確認、Crawl前のChronicle保存を順に接続する。復元はメンテナンス必須かつAdminの別経路で行う。保存基盤の完成を、公開前の復旧試験完了とは扱わない。

## 検証

隔離PostgreSQLで4対象の保存・読み戻し・既知スキーマ・全テーブル・採番状態・DB別台帳・監査失敗時の補償を検証した。単体検証では改ざん・不正形式・不明版・展開上限・不正シーケンス・権限・入力拒否・読み戻し不一致・コミット結果不明時の保持を確認。ブラウザでは対象切替・保存履歴・空一覧・資格解除・左右独立スクロール・日英表示を確認した。これらの試験データを実ステージングへ投入しない。

実環境の初回保存では、同期済みレコードのTIMESTAMPTZをJSONへ直接変換できず、アップロード前に失敗した。型付きの日時／BYTEA保存へ修正し、同期済みv2 outbox・receiptとBYTEA入りデータの回帰検証を追加した。修正後の統一検証はPython644件・JavaScript71件・共通ブラウザ・実PostgreSQLが成功し、依存とスキーマ整合も確認済み。

### ステージング実行記録（2026-10-05）

Cloud Build `cc661a88-031b-4199-9ec0-3beb544ddb21` 成功。デプロイしたイメージのdigestは `sha256:7b7a2405cecfb522307b023d4bc3dd4673a5209f39570b5e4dda4476f3d20367`、Webのready revisionは `ygc-staging-accounts-00010-5jh`。Jobも同じイメージを使用する。

専用サービスアカウント `ygc-staging-backup` にCloud SQL接続、DBパスワードSecret単体への参照、content/accountsバケット内のObject操作を付与した。サービスアカウント鍵は作成していない。Jobは単一タスク・並列1・retry 0・時間上限300秒で、既定引数はChronicleの検証のみ。公開Invokerや定期実行は追加していない。

| 対象 | 保存成功 execution | 読み戻し検証成功 execution |
| --- | --- | --- |
| Chronicle（42テーブル） | `ygc-staging-db-backup-pdbgf` | `ygc-staging-db-backup-ts87w` |
| Accounts（8テーブル） | `ygc-staging-db-backup-pmwcc` | `ygc-staging-db-backup-lxc79` |

OperationsとAuthenticationの保存は隔離試験で確認し、実ステージングではまだ実行していない。匿名アクセスではConsole/静的資産/readyが正常応答し、バックアップ一覧等の管理APIが401になることを確認した。実URLのデスクトップ・モバイル表示も確認済み。サービスモードはデプロイ前後ともOfflineを維持した。復元・初期化・Crawl・定期保存は実行していない。Adminによる実Consoleの保存一覧は利用者確認済みで、保存基盤のPR #28はmainへマージ済み。

## Console手動保存の接続

「今すぐ保存 / Save now」で選択した1DBの保存を開始し、5秒間隔の状態確認と再読み込み後の継続確認を行う。保存対象切替・SignOutで古い画面のポーリングを停止する。公開URLのAPI入口でも、確認済みIdentity Platformトークン・Accounts正本のAdmin・操作中の役割再確認を必須とする。全モードでAdminの保存を許可する。保存は読取専用Snapshotで、復元権限とは別。

対象と正規UUIDだけを受け付け、Job名・プロジェクト・リージョン・実行引数・資格情報をブラウザから指定させない。サーバー側で既定Jobに固定し、保存対象と要求UUIDだけを引数・環境変数に上書きする。Job定義の既定操作は検証のまま変更しない。

Operations eventsに要求UUID・操作主体・対象・時刻をコミットしてから非冪等のJob起動APIを呼ぶ。同じUUIDの再送は再起動せず、他の対象や操作主体への使い回しを拒否する。同じDBの未完了要求は10分間、新しい起動を拒否する。Google側の通信失敗は「結果未確認」とし、自動で再起動しない。台帳記録と要求UUIDの一致を成功条件とし、Job終了だけでは成功にしない。Job側のDB別advisory lockも維持する。

10分経過しても確認できない場合は、新しい明示操作を許可する。長いプロビジョニングや通信の不確定性に対する無期限のexactly-once保証ではない。保存履歴を確認してから再試行する。Job状態参照に失敗しても保存要求を消さない。HTTP応答へOperation/Execution名、内部例外、生データを返さない。

### IAMと配置状況

アプリ用SA `ygc-staging-app` に、既存の非公開Job `ygc-staging-db-backup` 単体で `run.jobs.run`、`run.jobs.runWithOverrides`、`run.executions.get` を許可するカスタムロールを付与済み。Operation参照には別のカスタムロールで `run.operations.get` だけをプロジェクトに付与した。Job編集・削除・キャンセル・他Job起動・IAM編集・新しいSecret参照を追加しない。既存カスタムロールがあれば内容一致を確認し、別の権限を上書きしない。

呼出し形式はGoogle公式の [Job実行API](https://docs.cloud.google.com/run/docs/reference/rest/v2/projects.locations.jobs/run)、[Operation参照API](https://docs.cloud.google.com/run/docs/reference/rest/v2/projects.locations.operations/get)、[Execution形式](https://docs.cloud.google.com/run/docs/reference/rest/v2/projects.locations.jobs.executions)に合わせる。API応答のOperation完了とJob実処理完了を区別し、ExecutionのcompletionTimeと件数も確認する。

当初、自動承認レビューがこの永続IAM変更を「具体的な権限範囲への明示承認が不足」として拒否した。2026-10-05に利用者がこの範囲を明示承認したため、上記権限のカスタムロールを新規作成・付与した。既存ロールと権限が異なる場合は上書きしない手順を使った。統一検証／Cloud Build成功のイメージで既存JobとWebを更新し、実SAでの起動・状態参照と匿名拒否・Offline維持を確認済み。`--enable-backup-controls` により `YGC_BACKUP_REGION` を明示したデプロイだけで操作を有効にする。未設定の既存デプロイでは一覧だけを提供し、保存APIを503で拒否する。

定期保存・世代保持・復元・Crawl接続は引き続き後続作業。現ステージングの保存操作を有効化済み。Adminによる実Consoleからの開始・画面再読み込み後の結果確認は利用者確認を待つ。

追加実装の統一検証はPython649件・JavaScript71件・共通ブラウザ・隔離PostgreSQLが成功。ブラウザで選択DBだけの開始、保存中のボタン無効化、再読み込み後の結果確認を検証した。PostgreSQLでは起動前の永続記録、同じUUIDの再送、DB別の未完了拒否、一般ユーザー拒否、要求UUIDと保存台帳の一致を確認した。Google APIはモックで形式と不正リソース拒否を検証した。承認後の実SAによるJob起動も下記のとおり成功。AdminのConsole操作の受入確認は別に行う。


### 手動保存接続の実行記録（2026-10-05）

- 実装コミット `67993d7` の共通CI成功後、Cloud Build `3a18cc6c-e5cd-443f-84fd-492478e306bc` が成功。
- イメージ `account-api@sha256:c91256a2a3bfdc831120360456e0bc2abf412a7dcdfe7f1f17c315e171ec05a1` を既存バックアップJobとWeb revision `ygc-staging-accounts-00011-6rb` に配置した。Webは `--enable-backup-controls` を指定。
- Job単体にカスタムロール `ygcBackupJobRunner`、プロジェクトに `ygcBackupOperationReader` を、アプリSAだけへ付与した。Jobの公開Invoker、SA鍵、別のSecret参照、Job編集権限は追加していない。
- アプリSAの一時IAM専用検証Job execution `ygc-staging-backup-control-probe-crhnn` が成功。実際にAccounts保存を起動し、OperationとExecutionを参照して完了を確認した。子execution `ygc-staging-db-backup-hs2mn` も保存・読み戻し成功。一時Jobは確認後に削除した。ユーザーのIdentity Platform資格情報は使用していない。
- 既存Jobの既定引数はChronicleの `--verify-only` のまま。検証JobからのAccounts保存は実行時上書きのみ。
- 実URLのConsole・静的資産・readyは200、匿名の保存POST／状態GET／一覧GETは401。公式SDKを使った匿名のデスクトップ・モバイル表示で保存ボタンが無効、管理領域が非表示になることを確認した。デプロイ前後ともOffline。DBの復元・初期化、Crawl、定期保存は実行していない。

この検証はアプリSAのIAM経路と匿名のHTTP拒否を確認するもの。実ユーザーのAdmin認証を代理使用したものではなく、Consoleからの保存開始・再読み込みの実受入確認は利用者に依頼する。
