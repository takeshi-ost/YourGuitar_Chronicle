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

DB内のBYTEAに格納される根拠等はDBの値として含む。Cloud Storage上の画像実体やGoogle側の認証情報はアーカイブに複写しない。DBにある画像参照は保存する。画像実体は別途保持する。アバターと管理用Media Claimは固定世代の存在を復元前に検証する。申請専用画像等を含む全画像機能の移行完了とは扱わない。

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

定期保存・世代保持・復元・Crawl接続は引き続き後続作業。現ステージングの保存操作を有効化済み。Adminによる実Consoleからの開始・画面再読み込み後の完了状態と履歴追加は利用者確認済み。PR #29をmainへマージ済み。

追加実装の統一検証はPython649件・JavaScript71件・共通ブラウザ・隔離PostgreSQLが成功。ブラウザで選択DBだけの開始、保存中のボタン無効化、再読み込み後の結果確認を検証した。PostgreSQLでは起動前の永続記録、同じUUIDの再送、DB別の未完了拒否、一般ユーザー拒否、要求UUIDと保存台帳の一致を確認した。Google APIはモックで形式と不正リソース拒否を検証した。承認後の実SAによるJob起動も下記のとおり成功。AdminのConsole操作の受入確認は別に行う。


### 手動保存接続の実行記録（2026-10-05）

- 実装コミット `67993d7` の共通CI成功後、Cloud Build `3a18cc6c-e5cd-443f-84fd-492478e306bc` が成功。
- イメージ `account-api@sha256:c91256a2a3bfdc831120360456e0bc2abf412a7dcdfe7f1f17c315e171ec05a1` を既存バックアップJobとWeb revision `ygc-staging-accounts-00011-6rb` に配置した。Webは `--enable-backup-controls` を指定。
- Job単体にカスタムロール `ygcBackupJobRunner`、プロジェクトに `ygcBackupOperationReader` を、アプリSAだけへ付与した。Jobの公開Invoker、SA鍵、別のSecret参照、Job編集権限は追加していない。
- アプリSAの一時IAM専用検証Job execution `ygc-staging-backup-control-probe-crhnn` が成功。実際にAccounts保存を起動し、OperationとExecutionを参照して完了を確認した。子execution `ygc-staging-db-backup-hs2mn` も保存・読み戻し成功。一時Jobは確認後に削除した。ユーザーのIdentity Platform資格情報は使用していない。
- 既存Jobの既定引数はChronicleの `--verify-only` のまま。検証JobからのAccounts保存は実行時上書きのみ。
- 実URLのConsole・静的資産・readyは200、匿名の保存POST／状態GET／一覧GETは401。公式SDKを使った匿名のデスクトップ・モバイル表示で保存ボタンが無効、管理領域が非表示になることを確認した。デプロイ前後ともOffline。DBの復元・初期化、Crawl、定期保存は実行していない。

この検証はアプリSAのIAM経路と匿名のHTTP拒否を確認するもの。実ユーザーのAdmin認証を代理使用したものではなく、Consoleからの保存開始・再読み込みの実受入確認はその後、利用者が完了状態と保存履歴追加を確認した。


## DB別の定期保存と保持設定（2026-10-05）

既存のbackup_schedulesを使い、対象ごとに定期保存ON/OFF、1–168時間、保持1–100件をAdmin Consoleで設定する。設定と操作主体を同じトランザクションで記録し、監査失敗では変更をロールバックする。他DBの設定は変更しない。初期値は各DBともOFF・24時間・10件を維持する。

IAM専用の定期保存Jobは毎正時に起動し、ONかつnext_runに達したDBだけ保存する。開始の粒度は1時間。設定ON／間隔変更後の初回は指定間隔より前に実行せず、次の正時まで最大約1時間待つ。その後は正時に合わせて次回を予約する。手動保存は定期予約を変更しない。Crawl前の保存は後続でChronicleだけを使用し、Accountsの定期保存と結び付けない。

保存成功後、DB別の保持数を超えた古い保存だけを整理する。対象・Archive形式・ハッシュを検証し、台帳で指定されたObjectReferenceの固定generationだけを削除する。バケット全体の列挙・画像・別DBの削除は行わない。削除後の台帳コミットが不確定だった場合、次回は同じ世代のNotFoundを確認して整理する。削除済み台帳は監査用に残し、保存一覧から除外する。保持数を下げる操作自体では削除せず、次回保存成功後に適用する。GCS Soft deleteの保管期間と料金は別に残る。

Python658件・JavaScript71件・共通ブラウザ・隔離PostgreSQLが成功。設定の対象独立性・再読み込み・一般ユーザー拒否・監査ロールバック・対象限定の古いArchive削除・画像維持・OFF時のskip・due時の保存と二重実行回避を検証した。定期Job/Schedulerの実配置記録は後続で追記する。復元・リセット・Crawlはこの変更に含めない。

## 現在の到達点と復元・初期化（2026-10-05）

PR #29のConsole手動保存は利用者が完了状態・履歴追加まで確認し、mainへ統合済み。PR #30のDB別保持・定期保存もCI成功後にmain（439b25c）へ統合した。上記の「未接続」は各時点の履歴である。

定期保存のCloud Build `52ffb2e3-daf5-4f7d-83ca-02111ecdbbe9` が成功し、イメージ `sha256:a7773102e15360f7a97fe4dddd65131bb92b04673fcb141d15fc7a1e13dca4f6` をWeb revision `ygc-staging-accounts-00012-xtk` と保存Jobへ配置した。Schedulerは毎時、専用SAからIAM専用Job `ygc-staging-backup-scheduler` を呼び、DB別設定で有効かつ期限到達した対象だけを保存する。初回 execution `ygc-staging-backup-scheduler-8fqqm` は成功した。4DBの定期保存は初期値OFFのまま、サービスもOfflineを維持した。

### 復元と初期化の境界

Consoleで対象DBを選択し、保存履歴の「復元」、または「テストデータの初期化」を操作する。モーダルで対象DB名を入力して明示確認する。キャンセル・Escape・ウィンドウ外クリックでは要求を送信しない。確認済みメールとAccounts正本の有効Admin、Normal以外のサービスモードが必須。Normalでは操作を無効化し、APIとJobも拒否する。

IAM専用 `ygc-staging-db-maintenance` の既定操作は接続確認だけ。実処理は永続要求UUIDを渡して起動する。ブラウザはクラウドJob名・資格情報・任意SQL・生アーカイブ・GCSパスを指定できない。起動前に要求を保存し、同じUUIDを再送してもJobを再起動しない。30分間はDB間でも重複実行を止める。結果未確認時に自動再実行しない。失効後の明示再試行前には台帳と保護用バックアップを確認する。

対象の既知スキーマ版・チェックサム・アーカイブハッシュを確認し、対象DBの保護用バックアップを保存してから変更する。復元対象の保存は実行待ちの間、世代削除から保護する。IDの予約を巻き戻さず、現在値・保存値・復元データの最大値まで既存USAGE権限のnextvalで前進させる。スキーマ作成・変更権限やsetval権限は追加しない。

| DB | 復元 | 初期化で消すもの | 維持するもの |
| --- | --- | --- | --- |
| Chronicle | 個体・Claim等を保存時点へ戻し、最新Accountsを再投影して所有状態を再評価 | 個体と関連コンテンツ | Accountsの登録・認証・ID予約、他DB、最新参加者情報 |
| Accounts | 保存に含まれる既存ユーザーのプロフィールとSNSデータを戻す | フォロー・DM・ローカル仮セッション | 登録・認証リンク・後から登録されたユーザー・現在のAdmin/無効化/BAN・同意・投影履歴 |
| Operations | 自動処理・保存設定を戻す | 自動処理/保存設定を初期値にし、保留GPT回答を消す | 現在のサービスモード・監査・バックアップ台帳・操作要求。自動Crawl/GPT反映/定期保存はOFFにする |
| Authentication experiment | GPT試験データを戻す | GPT試験データ | Google Identity Platformの認証アカウントには触れない。他DBを維持 |

Accountsは登録を巻き戻す完全置換ではない。Google側アカウント・パスワード・認証セッションをバックアップから復活/削除しない。所有者判定は最新のBANとプロフィールで再計算する。A→B→Cの譲渡履歴、Owned/Formerly Owned、自己Claim判定禁止、通常権限とAdmin強制判定の別経路を実PostgreSQLで確認する。

### 現段階の制約

復元は展開後32MiBまで（保存は128MiBまで）。連番の一度の前進は10万まで。Accountsのアバターは参照先の既存GCS世代の存在を確認する。画像自体をDBアーカイブに複製しない。Chronicleのmedia_assetsは対応済みのGCS画像参照を復元前に検証する（下記2026-10-05の接続）。未対応のローカル参照や欠損画像は変更前に拒否する。

4DBを跨ぐ分散トランザクションではない。対象のコミット後にAccounts再投影や操作台帳の更新が失敗した場合は、データが変更済みでも失敗/未確認表示になり得る。保護用保存を確認して整合を取る。例外本文・個人情報・資格情報をHTTPやログへ出さない。

この段階の実クラウド復元・初期化は、管理者ブラウザの受入確認まで未完了。CrawlのPostgreSQL移植、実Reverb資格情報の接続、Crawl前Chronicle保存、クラウドコンテンツ編集・画像付き復旧の確認も残る。

隔離検証はPython668件、JavaScript71件、共通Chromium、PostgreSQL18が成功。既存CRUD/sequence USAGE権限のまま4DBの復元・初期化と永続要求の再送/一般ユーザー拒否/モード変更後の拒否を確認した。実ブラウザ操作はComputer Useのアクセシビリティ・画面収録許可待ちで進められないため、クラウド側の接続検証と配置後に受入待ちとして中断する予定。復元・リセットの実要求を資格情報の代用やSQL直書きで作成しない。

### 復元・初期化の実配置記録（2026-10-05）

- PR #31のコミット `c51457e662f766118e063b447319f4fb1be5d3fc` に対する必須CI run `37219241004` が成功し、main `97418ab` へマージした。
- Cloud Build `f15e0ba2-227f-4f16-8687-dd78346788b1` が成功。イメージ `sha256:a8fd864bb58bc81fef6601d97c8f9f303e31b008408bcc5f652c91c0ae2672a0` をWeb ready revision `ygc-staging-accounts-00013-5fb`、手動保存Job、定期保存Job、メンテナンスJobへ配置した。保存Jobにも復元待ちアーカイブの世代削除保護が反映されている。
- 非公開 `ygc-staging-db-maintenance` は既存バックアップSA・DB Secret version 1・単一タスク・retry 0・900秒上限。既定引数は `--check-only`。アプリSAへ既存の `ygcBackupJobRunner` をこのJob単体で付与した。既存ロールの権限一致を確認し、権限の追加・上書き、Jobの公開Invoker、SA鍵作成は行っていない。
- execution `ygc-staging-db-maintenance-bfprr` が読み取り専用の4DB接続確認に成功した。実DBの復元・初期化は実行していない。
- 実URLでhealth/ready/Console/資産の200、匿名の保存台帳・ポリシー・操作状態・復元/初期化要求の401を確認。サービスはOfflineを保持した。
- Computer Useからのブラウザ操作はアクセシビリティ・画面収録許可待ちで利用できず、管理者としての実復旧試験を行えない。利用者の[ブラウザ受入手順](DB_OPERATIONS_ACCEPTANCE.md)を再開条件とし、ここで中断する。次のReverb実接続に必要なSecretも未作成（既存SecretはDBパスワードのみ）。

### 利用者による操作確認（2026-10-05）

利用者が[受入一覧](DB_OPERATIONS_ACCEPTANCE.md)の全項目を操作し、動作上の問題がないことを確認した。ブラウザ操作の受入は完了。項目5・6・7は対象業務データが空のため、保存時点への復元・初期化による削除・対象外DBや最新ユーザー情報の維持について、実データの内容比較は未検証。隔離PostgreSQLのデータ入り検証は成功済みだが、実クラウドでの内容検証完了とは扱わない。データ投入後の実復旧試験を残す。

## Media Claim画像を含むChronicle復旧（2026-10-05）

管理画面で追加した画像の`gcs-content-v1:`参照を保存・復元する。復元前に全media_assetsの形式・contentスコープ・固定generation・サイズ・MIMEとStorageの存在を検証し、不明なローカル参照や画像欠損があればDB変更前に中断する。DBバックアップは画像バイト列を複製せず、保持された不変オブジェクトを参照する。アーカイブの保持期間と画像回収は同時に設計する必要があるため、現段階では画像実体の自動削除を行わない。

アプリと`ygc-staging-db-maintenance` Jobの両方へ対応イメージを配置する。隔離PostgreSQLでは画像追加→保存→追加画像→復元、初期化→画像付き復元、欠損時の変更拒否、最新ユーザー・Admin維持を検証する。実クラウドのデータ入り確認は利用者の受入後に記録する。
