# GCP試験環境の準備状況

確認日：2026-10-04。公開前の試験環境を新規DBで構築する。実データの移送は行わない。

## 確認済み

- プロジェクトID：`your-guitar-chronicle-staging`。
- ユーザー申告：無料トライアル、請求先紐付け済み、月額5,000円の通知用予算を設定済み。
- Google Cloud CLIの専用アカウント認証とプロジェクト選択を確認済み。
- ローカルのギターDBリセット後のユーザー維持と、Electric / Acoustic限定の実収集は手動確認済み。

無料トライアルの状態と予算は今回APIから独立検証したものではない。予算は支出の強制上限ではない。

## 構成と作成状況（アプリ未配置）

| 項目 | 試験用の案 |
| --- | --- |
| リージョン | 東京 `asia-northeast1` |
| Web | Cloud Run、リクエスト課金、1 vCPU / 512 MiB、最小0・最大1インスタンスから試験 |
| DB | Cloud SQL PostgreSQL、Enterprise、単一ゾーン、共有CPUの小さい構成を候補に作成画面の価格を確認。HAなし、SSD 10 GiBを初期候補 |
| 保存単位 | AccountsとChronicleを別DBとして扱い、Operations・実験状態も責務を分離。独立復旧はアプリ側の手順を用意する。同一Cloud SQLインスタンスの通常復元だけでDB別復旧ができるとは扱わない |
| 画像 | Cloud Storage Standard、コンテンツ／アカウント／非公開根拠の参照と権限を分離。保存量・操作・配信費を計測 |
| 認証 | Identity Platform、まずメール／パスワード。管理者はUser Typeとは別権限 |
| 定期処理 | Cloud Run Jobs + Scheduler。Web内の常駐スレッドから分離 |
| その他 | Artifact Registry、Cloud Build、Secret Manager。保存世代・ログ・ビルド頻度を制御 |

最大インスタンス数は費用の絶対上限ではない。共有CPUは試験用候補で、性能・SLAを本番構成と同一視しない。Crawlやバックアップの負荷を測り、必要なら構成・予算を見直す。公開サービスはまだデプロイしていない。

## 費用確認

全体額の確定には、東京のCloud SQLインスタンス・ディスク・バックアップ、画像の保存量と外向き通信、ジョブ時間・ビルド・ログ等の前提が必要。Cloud SQLの料金ページは初期表示地域と選択地域が異なるため、初期表示のUSD単価を東京のJPY見積額として流用しない。作成前にConsoleの東京・指定構成の見積額を確認する。

メール認証は現在のTier 1料金では月間アクティブユーザー50,000まで無料。SMS等は別料金。Cloud Runは利用量に応じた課金と無料枠があるが、試験全体が無料であることを保証しない。恒常費用は無料トライアルのクレジットによる相殺前で判断する。

公式参照：[Cloud SQL料金](https://cloud.google.com/sql/pricing)、[Cloud Run料金](https://cloud.google.com/run/pricing)、[Cloud Storage料金](https://cloud.google.com/storage/pricing)、[Identity Platform料金](https://cloud.google.com/identity-platform/pricing)。

## 次の順序

1. 必要なAPIを有効にし、Cloud SQL作成画面で東京・小さい構成の月額を確認する。
2. 構成・費用を確認してリソースを作成する。単にAPIを有効にしてもDBインスタンスやバケットを作成したことにはならない。
3. PostgreSQL・認証・画像・ジョブのアダプターを実装し、隔離テストを通す。現行コードはCloud Runでローカルアダプターの起動を拒否するため、そのままデプロイできない。
4. 新規DBを初期化してステージングへ配置する。Admin・メンテナンス中のConsole編集、独立復元、リセットを再検証する。

仕様は[GCP移行境界](GCP_BOUNDARIES.md)と[管理者・メンテナンス](ADMIN_AND_MAINTENANCE.md)を参照。

## Cloud SQL作成確認（2026-10-04）

CLIで `ygc-staging-db` がRUNNABLE、POSTGRES_18、Enterprise、東京、db-f1-micro、単一ゾーン、SSD設定の容量10 GiB、自動バックアップ有効であることを確認した（SSD種別は作成時のユーザー申告）。

同じインスタンス内に `ygc_chronicle`、`ygc_accounts`、`ygc_operations`、`ygc_authentication` を新規作成し、一覧で確認済み。アプリのテーブル作成・旧データ投入・本番認証接続は未実施。この時点ではCloud Storage、Cloud Run、アプリ用DBユーザー等も未作成（後続の作成状況は以下参照）。AuthenticationはGPT実験用でありIdentity Platformのユーザー認証とは別。

ユーザーが確認した作成時見積もりは丸めた合計$0.02/時間（割引なし）。730時間なら約$14.60/月という表示単価ベースの概算で、標準バックアップ・通信費等を含まない。JPY請求額や全サービス合計の確定額ではない。

## Identity Platform設定確認（2026-10-04）

ユーザー提示の画面でEmail / Passwordが有効になっていることを確認。ユーザー申告でパスワードなしメールリンクはOFF。アプリケーション構成のauthDomainは `your-guitar-chronicle-staging.firebaseapp.com`。Web用apiKeyの提示も受けたが、本書には値を転載しない。既存の認証アダプターへの接続、ID token検証、メール確認、Admin対応、許可ドメイン確認は未実施。Consoleが提示するサンプルHTMLの直接貼付けは行わず、実装時に組み込む。

## 画像バケット作成確認（2026-10-04）

ユーザーが `your-guitar-chronicle-staging-content` と `your-guitar-chronicle-staging-accounts` を作成。CLIで両バケットの東京リージョン、公開アクセス防止enforced、均一アクセス、ソフトデリート7日を確認した。Standard・Google管理鍵等は作成時の案内に基づく設定であり、今回のCLI取得項目には含めていない。アプリ用サービスアカウントへのアクセス付与と配信・保存の実装は未実施。

GCP側のDB・認証プロバイダ・画像保存先の基礎準備はできた。次はアプリ用サービスアカウントとDB接続方法・シークレット・認証設定の受け渡しを整備し、クラウドアダプターを実装する。Cloud Runへの配置はコードの接続・隔離検証後に行う。

## 再開・実行用サービスアカウント（2026-10-04）

Cloud SQLがRUNNABLE / ALWAYSであることを再確認。アプリ実行用に `ygc-staging-app@your-guitar-chronicle-staging.iam.gserviceaccount.com` を作成した。プロジェクトで `roles/cloudsql.client`、content・accountsの各バケットで `roles/storage.objectUser` を付与し、IAM取得で確認済み。サービスアカウント鍵は作成していない。Cloud Runへ割り当てる実行用資格であり、YGCユーザーのAdmin資格とは別。

Cloud SQL Clientは接続用IAM権限であり、DB内のユーザー・SQL操作権限を作成するものではない。次にアプリ用DBユーザー、接続方式、Secret Managerへの対象別アクセスを整備する。Identity Platformの失効確認等に必要な追加権限はアダプターの実装に合わせて限定して付与する。今回Secret Managerの全シークレット読取権限やIdentity Platform管理権限は付与していない。

## DBユーザー・接続シークレット（2026-10-04）

CLIで組み込みユーザー `ygc_app`、Secret Managerの `ygc-staging-db-password` と有効なversion 1の存在を確認した。値は取得・表示していない。アプリ実行用サービスアカウントに、このシークレット単体の `roles/secretmanager.secretAccessor` を付与済み。

DBパスワードとシークレット値の一致は接続試験まで未確認。ユーザーがSQL Studioで権限制限を実施し、rolcreatedb / rolcreaterole / cloudsqlsuperuser所属がすべてfalseの結果を確認した。アプリ用テーブル権限の付与はスキーマ初期化時に行う。

[PostgreSQL接続・初期化基盤](POSTGRES_BOOTSTRAP.md)を実装ブランチに追加。使い捨てPostgreSQL 18で検証した段階であり、Cloud SQL本体のテーブル作成・実接続・WebUI移植はまだ実施していない。

## Accounts同期・所有判定の移植（実装ブランチ）

[Accounts同期・所有判定](POSTGRES_ACCOUNT_SYNC.md)を追加。正本更新と同期待ち記録、再試行可能な投影、Owner Verification・Transfer・Admin強制判定の共有処理をPostgreSQLで検証する。002移行も追加したが、Cloud SQLには001／002ともまだ適用していない。実認証・Webルート・クラウドWorkerは未接続。

## 認証検証境界の追加（2026-10-04）

PR #15のPostgreSQL基盤はmainへマージ済み。続く実装ブランチに公式SDKによるID token検証とAccounts正本への対応付けを追加した。[認証検証の仕様・前提・残作業](IDENTITY_PLATFORM_VERIFICATION.md)を参照。WebUI・実GCPとの接続はまだ行っていない。

## アプリ登録APIの追加（2026-10-04）

PR #16の認証検証はmainへ統合済み。後続ブランチにGoogle認証後のアプリ登録・ログイン確認APIを追加し、ローカル／クラウドのプロフィール入力条件を統一した。手順・再試行・同意草案・未接続範囲は[クラウド登録API](CLOUD_ACCOUNT_REGISTRATION.md)を参照。現行WebUIと実GCPへの接続はまだ行っていない。
