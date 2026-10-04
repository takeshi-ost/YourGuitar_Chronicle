# クラウド管理APIと初回Admin

2026-10-04。管理者権限とメンテナンスの基盤を実装した。[最終仕様](ADMIN_AND_MAINTENANCE.md)の一部であり、BrowserConsoleや一般コンテンツAPIへの接続はまだ含まない。

## 管理資格とAPI

Identity PlatformのBearerトークンを検証し、Googleのメール確認済みフラグ、Accounts正本の固定ID、有効なAdmin資格を確認する。メール文字列、自己申告のID・role、ローカルConsoleヘッダーでは許可しない。操作中はAccounts行をロックし、権限解除・無効化との競合を防ぐ。

| 入口 | 条件・応答 |
| --- | --- |
| GET `/api/service/status` | 公開。modeとmessageのみ。Normalではmessageは空 |
| GET `/api/admin/operations` | 確認済みメールの有効なAdmin。mode/message/version |
| PUT `/api/admin/operations/mode` | 同じ資格。mode/message/versionだけを受け取る。Reasonは不要 |

モードは `normal` / `read_only` / `offline` / `admin_only`。明示的な管理経路は全モードで利用可能。一般経路はNormalで閲覧・更新、Read-onlyで閲覧のみ、Offlineで停止、Admin OnlyでAdminのみ許可する。この判定は今後のコンテンツ処理のトランザクションを包むための基盤であり、未接続のAPIを保護済みとは扱わない。認証・メール確認・復旧入口は維持する。

変更時は表示時のversionを送り、競合は409で再取得を要求する。Operationsのモード変更とeventsへの監査保存を同じトランザクションで実施する。監査には操作者の固定ID、変更前後、時刻、versionを記録。既存テーブルを使い、スキーマ変更は不要。DB権限そのものは監査表の更新・削除を禁止する構成ではなく、改ざん不能な監査基盤ではない。

## 初回Admin

運営用メールで別のYGCアカウントを作り、メール確認を完了してから付与する。Google側だけのアカウントでは足りず、Accounts正本へのYGC登録が必要。

`python -m ygc.admin_bootstrap_job` はHTTPへ公開しない専用Job用の入口。IAMのJob実行権限と、実行サービスアカウントのCloud SQL・DB Secret・`firebaseauth.users.get`が必要。サービスアカウント鍵、Schedulerへの実行権限、公開Invokerは不要。

必須引数は `--email`、`--operator`、`--confirm-project`。`--dry-run`ではGoogle側の有効・メール確認済みとYGC登録の対応だけを確認し、付与しない。実行時は単一タスク・自動再試行なしとする。GCP/PostgreSQLの明示設定、プロジェクト確認が必須。Auth EmulatorとHTTPサービス内実行は拒否する。

実付与はAccounts内のトランザクションとロックで初回に限定し、別の有効Adminがいる場合は拒否する。同じAdminへの再実行は無変更。権限付与とaccount_metadataの監査を同時に保存し、既存outbox経由でChronicleへ投影する。メールで既存コンテンツユーザーを自動結合しない。operatorは指定したラベルであり、IAM上の実行者はCloud Audit Logsで照合する。ログは結果だけで、メール・ID・資格情報を出さない。

## 検証と残作業

共通検証：Python554件、JavaScript71件、ブラウザの認証・既存操作・27モーダル、実PostgreSQLの4DBが通過。管理APIの不正資格・偽装入力、全モード／利用者の組合せ、初回付与の反復・拒否、version競合、監査失敗時のロールバック、権限解除のロックを確認。所有権・BAN・Transfer等の既存遷移検証も通過した。

残るのはBrowserConsoleへの接続、コンテンツ・画像の全入口への認可、バックアップ・復元／リセット・Crawl・審議反映・各ジョブの停止と排他、実Adminのブラウザ操作試験。API配置だけでメンテナンス中のDBリセットを可能にしたとは扱わない。ローカル仕様は維持する。

## ステージング配置

ビルド `c825522d-f44d-4025-afab-731f21148641` が成功。イメージ `account-api@sha256:40ec9052fce6b92ea90b3a5de5ec5c3a8a2ab860e216740b3d26b0134bbf41d8` を認証サービスのリビジョン `ygc-staging-accounts-00004-6sz` へ配置した。実URLでhealth・3DB ready・公開状態が200、管理APIへの無認証・不正Bearer・偽装Console資格が401。OperationsはOfflineを維持した。

初回Admin用Job `ygc-staging-admin-bootstrap` も同じイメージで配置。既存 `ygc-staging-app` の限定権限を利用し、個別IAMポリシーに公開Invokerなし、単一タスク・retry 0・300秒。初期設定はdry-run。既存Accounts同期Job・Schedulerの設定は変更していない。

初回dry-run実行 `ygc-staging-admin-bootstrap-lk2g8` は失敗。追加の読み取り確認で、選択された運営用メールのIdentity Platformユーザーが未登録であることを確認した。利用者によるCreate Accountとメール確認を待つ。Admin権限はまだ付与していない。
