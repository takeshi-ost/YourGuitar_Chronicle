# GCP移行前の整備状況

確認日：2026-10-04。対象：main `aa27c21`（[PR #14](https://github.com/takeshi-ost/YourGuitar_Chronicle/pull/14)統合後）。コード・テスト・CI設定・GitHub上の状態を照合した。実データを開く監査や、GCP接続・本番配置・実Reverb収集は実施していない。実装後はこの表の状態と確認根拠を更新する。

## 結論

GCP移行の実装へ着手できる状態。一般ユーザー向けの主要機能について、この確認で移行着手を妨げる新たな未実装機能は見つかっていない。開発基盤の追加整備はPR #14でmainへ統合済み。統合後のCIも成功している。初回は新規DBで開始する方針のため、既存データ移送の準備は必須ではない。公開前に繰り返せる初期化と試験データの準備は残る。「GCP移行に着手できる」と「公開サーバーで利用できる」は別で、公開には認証・認可・永続化などの移行作業が必要。

## 完了したローカル整備

| 項目 | 状態・確認根拠 |
| --- | --- |
| テスト実行の統一 | `scripts/run_tests.py` がPython・JavaScript・任意のブラウザ検証を実行 |
| 実データ・資格情報からの隔離 | conftestと共通ランナーで保存先・環境を分離。ブラウザは専用一時サーバーを起動 |
| 一時領域の後片付け | tmp_path・pytest cacheも専用領域へ集約。成功・失敗・通常中断と外部basetemp拒否のテストあり |
| 依存関係の固定 | constraints、ビルド要件、固定pip、共通インストーラー、起動スクリプトを整備 |
| PR自動チェック | Python 3.12 / Node 24 / Ubuntu 24.04 / Chromium。PRとmain pushで実行 |
| アカウント・コンテンツ分離 | Accounts正本とChronicle投影、ダミーセッション、UUID保護・独立復元のテストあり |
| バックアップ機能 | 対象別の手動・定期保存、保持、復元条件、復元前保存を実装。Accounts復元とChronicle復元の境界も検証 |
| 所有状態の回帰検証 | Acquire・Transfer・自己判定禁止・管理者別経路・係争・BAN等のテストあり |
| 文書の役割分離 | コンセプト、操作、機能仕様、DB構造、管理、開発、移行、履歴に整理 |

PR最終コミットとmain統合後の両方でCI成功。直近確認はPython435件、JavaScript55件、共通UI・27モーダル・主要ユーザー操作のブラウザ検証。件数を固定の合格条件にはしない。

- [PR #13](https://github.com/takeshi-ost/YourGuitar_Chronicle/pull/13)
- [main統合後CI](https://github.com/takeshi-ost/YourGuitar_Chronicle/actions/runs/37173242399)

## ローカル追加整備の実施状況

| 優先度 | 残作業 | 現状 | 完了条件 |
| --- | --- | --- | --- |
| 完了（main統合済み） | 依存定義と固定ファイルの整合チェック | check_dependencies.pyとCIステップを追加。固定漏れ・範囲不一致・ビルド定義差を検出する回帰テスト通過 | PR #14と統合後CIで確認済み |
| 完了（main統合済み） | 主要操作の正式ブラウザテスト | 登録・同意・資格情報破棄・ログイン／SignOut・日本語・ListingとAcquire→Owner承認を追加、ローカルChromeで通過 | GPTだけ固定観察を供給し実DB処理と画面を検証。main統合とCI成功を確認済み |
| 完了（main統合済み） | ブラウザ失敗時の診断保存 | スクリーンショット・trace・ページエラーを保存、CI artifactの7日保持を追加。ローカルで失敗時生成を確認 | main統合とCI成功を確認済み |
| 完了（GitHub適用済み） | PRと成功チェックの強制 | mainの保護を有効化。PR、最新mainに対する `Tests (Python, JavaScript, Chromium)` 成功を管理者にも必須化。強制push・削除は不可 | 他者レビュー承認は0件で単独開発可能 |
| 条件付き | Windows実機確認 | macOSとLinux CIは検証済み。Windowsは未検証 | Windowsでの開発・利用を継続する場合、起動・固定依存導入・共通テストを確認 |

追加した3項目はPR #14で検証し、main `aa27c21`への統合とCI成功を確認済み。mainの保護ルールもGitHub APIで再確認した。

追加整備のCI（コミット `5eb54e8`）：[実行結果](https://github.com/takeshi-ost/YourGuitar_Chronicle/actions/runs/37172702871)。依存検査、Python435件、JavaScript55件、Chromiumの既存UI・モーダル・新規ユーザー操作が成功。失敗時artifactもCIで実際に生成・取得を確認した。

## 新規DBでの試験開始前の準備

2026-10-04の追加方針として、初回GCP移行ではDBをリセットし、公開前にも複数回のリセットを想定する。現在のローカルDBを移送するための監査は初回の必須条件から外す。詳細は[GCP初期化・リセット方針](../migration/GCP_BOUNDARIES.md#初回移行と公開前のdbリセット方針2026-10-04)を参照。

| 残作業 | 現状・完了条件 |
| --- | --- |
| API・画像の権限表 | ローカルダミーのID照合テストはある。Guest／本人／Current Owner／管理者と非公開画像を含む全入口の一覧・許可条件を作り、本番認可の受入基準にする |
| 新規初期化と再リセット手順 | 空DBのスキーマ初期化のみ実装ブランチに追加。再リセット・試験データ準備は未実装。最新スキーマ・管理者・試験ユーザー・試験データを再作成し、コンテンツのみ／全試験データの範囲を分ける。画像・認証対応・遅延ジョブも整合させる |
| 復元リハーサル | 一時DBの自動テストはある。GCP試験データでChronicle単独復元時の最新Accounts保持、ユーザー参照・画像・履歴の整合を確認する |
| 既存データ・旧Observationの取込み | 初回は対象外。後で旧DBやバックアップを取り込む場合に監査・変換・比較を実施する。互換処理の撤去を今回の前提にはしない |
| Crawlの運用標本検証 | 一括Electric / Acoustic、重複・再開、部分失敗等の自動テストあり。2026-10-04のユーザーによる実クロール確認では、発見された全個体がエレキ／アコースティックギターで、並びも両カテゴリが適度に混在。網羅性・個体の誤照合・途中停止・429対応は引き続き未確認 |

既存テストがあることと、今回実データで試したことを区別する。監査手順は[旧Observation移行](../migration/TEMP_OBSERVATION_MIGRATION_PLAN.md)、保存単位は[DB構造](../architecture/DATABASE_STRUCTURE.md)。

## 今回の再確認と次の順序

2026-10-04、main `aa27c21`に対して次を再確認した。アプリのコード変更は行っていない。

- 統合後の[CI](https://github.com/takeshi-ost/YourGuitar_Chronicle/actions/runs/37173242399)は完了・成功。今回は同じコードの全件テストをローカルで重複実行していない。
- ローカルの固定依存環境でも `scripts/check_dependencies.py` が成功。
- mainはPRと最新mainに対する成功チェックを管理者にも要求する。他者承認の必須件数は0件。
- `platform_boundaries.py` はCloud Run環境と未接続バックエンドを拒否する。Identity Platform・Cloud Run Jobsは未接続であり、このままのコードをクラウドで起動する段階ではない。
- `test_local_identity.py` にChronicle復元時の最新アカウント・BAN・アバター保持、Accounts単独復元、ID再利用防止、認証した利用者による所有権遷移の検証がある。実データの復元リハーサルは未実施。

次の作業順序は以下とする。上の残作業を完了扱いにする際には、使用したコピー・確認日時・比較結果を記録する。

1. **本番認可の受入基準を作る。** 全API・画像配信の入口を列挙し、Guest／本人／Current Owner／管理者の許可条件と拒否ケースを定義する。Owner判定は[設計上の不変条件](../architecture/CLAIM_CENTERED_ARCHITECTURE.md)の組合せで確認する。
2. **新規DBの初期化・再リセット手順を用意する。** 最新スキーマ、管理者と試験ユーザー、繰り返し投入できる試験データを準備する。コンテンツのみとアカウントを含むリセットを分ける。
3. **GCPアダプターを実装し、ステージングで試験する。** Identity Platform・PostgreSQL・画像保存・ジョブを接続し、認可・所有権・独立復元・リセット後の再収集を確認する。実Reverbの標本検証は公開運用開始までに行う。

既存のローカルDBの移送・実データ監査は初回の前提から外す。今回、DBの削除やリセットは実行していない。旧データを後で取り込む場合は[旧データ監査手順](../migration/TEMP_OBSERVATION_MIGRATION_PLAN.md#db変更前の確認手順)を適用する。

## GCP移行そのものの作業

以下を「先にローカル版へ機能追加しなければならない項目」とは扱わない。GCP実装・検証の中で解決する。

- Identity Platform接続、実登録・メール確認、ID token検証、全API認可と管理者資格。
- PostgreSQLへの業務SQL移植（初期スキーマ基盤は実装ブランチに追加）、アカウント正本とコンテンツの同期・独立復元、同時更新とカーソル排他。
- Cloud Storageへの画像保存、非公開根拠の配信制御、シークレット管理。
- Cloud Run用コンテナ・設定・起動／ヘルス・デプロイ／切戻し手順。
- Scheduler / Run Jobs、ジョブ状態の永続化、再試行・多重実行防止、クラウドバックアップ。
- ステージング環境での新規初期化・再リセット・統合検証、正式Terms／Privacy。

Admin Onlyモードは合意済みの移行後追加項目。詳細と配置判断は[GCP移行境界](../migration/GCP_BOUNDARIES.md)へ集約する。本確認ではGoogleサービスの現行仕様・料金を再調査していない。

## 追加で確認された運用不整合

2026-10-04、Read-onlyでReset DBが拒否される実動作を確認。一般更新停止と管理者による修復操作の区別が不足している。現行のNormalでのResetは回避手順であり、最終仕様ではない。[管理者権限とメンテナンス制御](../migration/ADMIN_AND_MAINTENANCE.md)に、GCP後の最終仕様とローカル維持方針を整理した。ユーザー合意によりローカルは現状を維持し、暫定対応は実装しない。制御変更はGCP移行時にAdmin認証・認可と合わせて実装し、移行後にBrowser Consoleによるメンテナンス中の編集を再テストする。公開前の検証項目であり、ローカル整備の必須残作業には含めない。

## ローカルの手動運用確認（2026-10-04）

以下はユーザーによる操作・確認結果。自動テストやエージェントが実データを直接監査した結果とは区別する。

- Browser ConsoleからChronicleをリセットできた。ギターDBが空でもユーザー状態は維持され、所有情報・Claimは空になった。
- リセット後の実クロールで、今回発見された全個体がエレキギターまたはアコースティックギターであることを確認した。対象外の混入は報告されていない。
- 検索結果の並びは両カテゴリが適度に混在していることを確認した。

実行件数・年範囲・Run IDは本報告には含まれていない。この結果は今回の収集結果に対する対象限定と表示順の確認であり、検索の網羅性・全条件での混入防止・429や中断再開の確認完了を意味しない。GCP移行後は同じ観点を再確認する。

## PostgreSQL移行基盤（実装ブランチ）

2026-10-04：4対象のPostgreSQLスキーマ・明示的初期化・接続・制限付き実行用権限・隔離検証を追加。手順と範囲は[PostgreSQL初期化](../migration/POSTGRES_BOOTSTRAP.md)。Cloud SQLのテーブルは未作成。WebUI全体・独立復元・認証・画像・ジョブの移植とCloud Run起動制限は引き続き未完了で、公開可能という判定はしていない。

今回のローカル検証：Python441件・JavaScript55件、共通UI・27モーダル・登録／ログイン／Listing／Acquireのブラウザ操作、PostgreSQL 18の4DB統合検証が通過。ブラウザのログイン後遷移には初期読込み完了待機を追加した。依存整合・actionlint・生成物整合・配布wheel内SQL同梱も確認済み。GitHub上での今回変更のPRチェックはまだ実行していない。

Accounts正本・再試行可能な投影、Owner Verification・Transfer・Admin強制判定のDB層を追加。参加者の同期待ちを検出して書込みを拒否する。詳細・残る未移植範囲は[PostgreSQL同期と所有判定](../migration/POSTGRES_ACCOUNT_SYNC.md)。Cloud SQLやWebUIへの接続はまだ行っていない。

今回の追加検証：Python445件・JavaScript55件とブラウザ検証が通過。PostgreSQLでは同時登録・中断再試行・停止アカウント・投影待ち拒否に加え、共有処理によるOwner判定・自己判定禁止・Transfer受領・Admin別経路・A→B→C後の先行Transfer否定／無効化／削除を確認した。これらはローカルの使い捨てDBでの結果であり、Cloud SQL接続試験や今回変更のGitHub CI成功を表すものではない。

## 認証検証境界の追加（2026-10-04）

PR #15のPostgreSQL基盤はmainへマージ済み。続く実装ブランチに公式SDKによるID token検証とAccounts正本への対応付けを追加した。[認証検証の仕様・前提・残作業](../migration/IDENTITY_PLATFORM_VERIFICATION.md)を参照。WebUI・実GCPとの接続はまだ行っていない。

## アプリ登録APIの追加（2026-10-04）

PR #16の認証検証はmainへ統合済み。後続ブランチにGoogle認証後のアプリ登録・ログイン確認APIを追加し、ローカル／クラウドのプロフィール入力条件を統一した。手順・再試行・同意草案・未接続範囲は[クラウド登録API](../migration/CLOUD_ACCOUNT_REGISTRATION.md)を参照。現行WebUIと実GCPへの接続はまだ行っていない。

## ブラウザ認証の追加（2026-10-04）

PR #17のアプリ登録APIはmainへ統合済み。後続ブランチに公式Web SDKの接続部品と明示設定時のみ提供するステージング確認画面を追加した。[ブラウザ認証](../migration/CLOUD_BROWSER_AUTH.md)を参照。現行TopPageの仮認証、Cloud Runの現行WebUI起動拒否は維持し、実GCPへの配置・登録はまだ行っていない。

## Cloud SQL実接続と初期化準備（2026-10-04）

PR #18のブラウザ認証はmainへ統合済み。公式Auth ProxyとSecret Managerのversion 1でygc_appから4DBの読取り接続に成功し、空のpublicスキーマと制限付き権限を確認した。認証用にfirebaseauth.users.getのみの独自ロールを実行用サービスアカウントへ付与済み。DBテーブル初期化は未実施。migrateのCLI分岐不具合を修正し、4DBのinitializeコマンドと実CLI統合テストを後続ブランチへ追加した。[実行手順・検証と残作業](../migration/CLOUD_SQL_INITIALIZATION.md)を参照。

## Cloud SQL初期化完了（2026-10-04）

PR #19のCLI修正はmainへ統合済み。ユーザーがinitializeを実行し、エージェントが制限付きygc_appで独立確認した。Chronicleは版2／42テーブル、Accountsは版2／8、Operationsは版1／7、Authenticationは版1／3。個体・参加者・アカウントは0、Operationsはoffline、Auto Crawl・GPT反映・定期バックアップはOFF。スキーマ一致と業務テーブルの読書き権限、CREATEと版UPDATEの禁止を確認済み。詳細は[初期化結果](../migration/CLOUD_SQL_INITIALIZATION.md)を参照。Cloud Runへの配置と実Google認証は未実施。

## 2026-10-04：認証確認画面のCloud Run配置

Cloud Runへ認証確認画面だけを配置した。専用コンテナ・限定したビルド対象・実行／ビルド資格の分離・Secret Manager連携を整備。現在の構成、実URL、検証範囲、残る実ユーザー認証試験とWebUI移行は[Cloud Run認証確認画面](../migration/CLOUD_RUN_ACCOUNT_STAGING.md)を参照。上記の未配置・未初期化の記述は、その時点の履歴である。

## 2026-10-04：基本認証試験とAccounts同期

利用者が一般メールアドレスでCreate Account・再読み込み後のログイン維持・SignOut・Sign Inを確認し、基本認証試験が完了した。Accounts正本からChronicle参加者への同期を専用Cloud Run Jobへ配置。初回実行は正常終了し、登録1件／投影1件／未反映0、ID・UUID・反映版の一致を読取り専用で独立確認した。定期起動と実行結果、停止・再開、残るWebUI移行は[Accounts同期Job](../migration/ACCOUNT_PROJECTION_JOB.md)を参照。

## 2026-10-04：メール確認の操作追加

認証確認画面へ、利用者のクリックによる確認メール送信と、SDK reload・新しいJWTによる確認状態更新を追加・配置した。利用者が実メールの受信・リンク確認とメール確認済み表示を確認した。操作と実配置記録、所有権申請APIの未接続範囲は[メール確認](../migration/EMAIL_VERIFICATION.md)を参照。

## 2026-10-04：クラウド管理APIの基盤

確認済みメール・Accounts正本のAdmin資格による管理API、4モードのアクセス判定、競合検出と監査記録、IAMで実行する初回Admin付与Jobを実装。BrowserConsole・コンテンツAPI・復元／リセット・自動ジョブへの接続は残る。[実装範囲と初回Admin手順](../migration/CLOUD_OPERATIONS_ACCESS.md)を参照。

## 2026-10-04：クラウドConsoleのOperations接続

Admin認証済みのConsoleから状態確認と4モードの変更を操作する画面を追加した。左右独立スクロール、辞書参照、競合・資格解除・障害時の保存停止をブラウザで検証。データ管理・復元／リセット・ジョブ制御は未接続。[操作と検証範囲](../migration/CLOUD_BROWSER_CONSOLE.md)を参照。

2026-10-04、利用者がクラウドBrowserConsoleの実操作を確認した。実装コミットに対する共通CIも成功。詳細なモード・競合の受入とデータ管理機能の移行は残る。

## 2026-10-04：Cloud Storage接続

コンテンツ／アカウントの非公開バケットへ明示接続し、世代指定の不変な参照・作成／取得／削除、Adminによる読み取り状態表示、IAM専用の書込確認Jobを追加した。画像のDB参照・アップロード／配信・バックアップ／復元は後続。[仕様と検証範囲](../migration/CLOUD_STORAGE.md)を参照。

## 2026-10-05：クラウドConsoleのギター閲覧

Chronicleの個体一覧・検索・ページ送りと右側Product Detailの読み取りを追加。確認済みメール・正本Admin資格で全サービスモードから利用する。画像・Claim・編集・Crawl・バックアップ／復元は後続。[仕様と検証範囲](../migration/CLOUD_GUITAR_BROWSER.md)を参照。

## 2026-10-05：DB別バックアップ保存基盤

対象DBの論理スナップショット保存・読み戻し検証とConsoleの履歴を追加した。保存はIAM専用Jobで対象ごとに実行する。定期保存・世代保持・復元・Crawlへの接続は後続。[仕様と検証](../migration/CLOUD_DATABASE_BACKUPS.md)を参照。

## Console手動バックアップの接続状況（2026-10-05）

DB別保存基盤と保存履歴（PR #28）はmainへマージ、利用者の表示確認済み。「今すぐ保存」と永続要求・状態追跡を実装し、共通CI成功後にステージングへ配置済み。固定Jobへの実行・引数上書き・実行状態参照とOperation参照のIAM追加は利用者の明示承認後に実施した。アプリSAからのAccounts保存起動・完了参照、匿名保存API拒否、Offline維持を確認済み。実Consoleからの開始・再読み込みの利用者確認を待つ。詳細は [バックアップ接続](../migration/CLOUD_DATABASE_BACKUPS.md#console手動保存の接続)。定期保存・保持世代・復元・Crawlは未接続。

## DB運用の継続作業（2026-10-05）

この欄が現在の状態。上の未実施・未接続記述は各実装段階の履歴である。

- 完了：DB別の手動保存と完了状態・履歴追加の利用者確認、PR #29の統合。
- 完了：DB別の保持世代・定期保存設定、毎時IAM Schedulerと期限到達DBだけの保存。PR #30のCI成功・統合・配置。4DBの定期保存はOFFのまま。
- 実装・隔離試験済み：対象DBだけの復元と保護用保存、Accountsの登録・認証・現在権限維持、Chronicle初期化後の最新参加者再投影、Operationsのモード・台帳保持、Authentication試験DBの初期化。PR #31をCI成功後にmainへ統合し実配置済み。管理者ブラウザの操作は全項目で利用者確認済み。対象業務データが空のため、復元/初期化の内容比較は未検証。
- 残る：実クラウドのデータ入り復元・初期化での内容比較と対象外DB/最新ユーザー情報の維持確認、画像付きChronicleの復元アダプター、Reverb CrawlのPostgreSQL Job移植とCrawl前Chronicle保存、クラウドコンテンツ編集の接続。

[DBバックアップの現在仕様・復元の制約](../migration/CLOUD_DATABASE_BACKUPS.md#現在の到達点と復元初期化2026-10-05)を参照。全DB一括リセットやGoogle認証ユーザー削除は行わない。残る管理者認証・受入が必要な段階では中断し、利用者にブラウザで確認する操作を列挙する。

PR #31のWeb revision `ygc-staging-accounts-00013-5fb` とIAM専用メンテナンスJobを配置し、4DBの読み取り接続・匿名拒否・Offline維持を確認した。Computer Useのアクセシビリティ/画面収録許可待ちにより管理者ブラウザ試験で中断。再開時の[受入一覧](../migration/DB_OPERATIONS_ACCEPTANCE.md)に実操作を記載した。Reverb資格情報Secretも未作成で、Crawlは未接続。

2026-10-05、利用者が受入全項目の操作に問題がないことを確認した。Computer Use許可待ちによるエージェントの試験中断後、利用者のブラウザ確認で操作受入は完了した。項目5・6・7は対象業務データが空で、実際の復元/削除内容の比較は未検証。データ入り実復旧試験を残し、隔離PostgreSQLでの内容検証とは区別する。詳細は[受入結果](../migration/DB_OPERATIONS_ACCEPTANCE.md#受入結果2026-10-05)。

## Reverb Crawl接続の実装（2026-10-05）

PostgreSQLのCrawlアダプター、Chronicleだけの実行前保存、専用Job、Admin APIとConsoleのCrawl Now/Auto/実行ログを実装。利用者はReverbトークン取得済みと回答し、Secret Managerでygc-staging-reverb-tokenを作成する手順を案内した。実配置・認証・実CrawlはSecret登録完了後に進める。旧「未移植」記述は上記までの履歴で、現在は実装の検証と認証情報の準備段階。[仕様・Secret手順・確認一覧](../migration/CLOUD_REVERB_CRAWL.md)を参照。DB管理の操作受入は完了し、データ入りの実復旧試験は残る。


2026-10-05追記：Reverb Secret version 1の有効状態を確認し、専用Crawl Job/Schedulerを配置。check-onlyによるDB接続とprobe-onlyによるReverb認証が成功した。PR #33はCI成功後mainへ統合済み。実Crawlとデータ入り復旧受入は引き続き利用者のブラウザ確認待ち。[配置・確認記録](../migration/CLOUD_REVERB_CRAWL.md#ステージング接続確認2026-10-05)を参照。

Console ready revision `ygc-staging-accounts-00014-g85`の配置、health/ready、匿名Crawl操作拒否、既存Offline維持を確認した。実管理者によるCrawlとデータ入り復旧は未実施。


### 最新の利用者受入結果（2026-10-05）

Crawlの表示・手動実行/事前保存・ギター限定/重複防止・定期実行による重複のない増加を確認済み。データ入りChronicleについて、手動保存→追加Crawl→保存時点への復元、初期化→同じ保存からの個体復元、ユーザー登録・Admin権限・ログイン維持も全て正常完了と利用者から報告を受けた。前節の「未実施」「確認待ち」は当時の状態で、この範囲の受入は完了。他DB単独のデータ入り内容比較、画像付きChronicle復旧、残るコンテンツ編集API・画面共通化は別の後続範囲。[受入結果](../migration/DB_OPERATIONS_ACCEPTANCE.md)を参照。


次の移行範囲はUser DB Management/User DetailのAccounts正本読取り。一覧・総数・検索・ページ移動・詳細表示を追加し、変更系API、Ownership/Owned表示、画像付き復旧は後続として維持する。今回のCrawl/Chronicle復旧受入結果と併せて文書を更新する。


2026-10-05追記：User DB Management/User Detail（PR #38）はCI成功・main統合・配置を完了。利用者が一覧/総数、名前・ID検索、右Detailの1項目ずつの表示、左右独立スクロール、SignOut後の管理表示制限の5項目を全て確認済みと報告し、閲覧機能の受入は完了。[確認記録](../migration/CLOUD_BROWSER_CONSOLE.md#user-db閲覧の利用者受入2026-10-05)を参照。


User DB閲覧の受入完了に続き、Product DetailのChronicle正本読取りを追加。Claim履歴・判定/有効状態・Listing/Specificationの内容とページ移動を接続する。所有権の変更、判定・編集・投票、画像付き復旧は別の後続範囲。


2026-10-05のChronicle閲覧受入：利用者が履歴表示、展開/折畳み/Refresh、個体切替、SignOut後の表示制限を確認し、問題なし。25件超の履歴を持つ個体がないため、実クラウドでのページ移動は未確認として残す。隔離ブラウザ・PostgreSQLのページ移動試験は成功済み。[確認記録](../migration/CLOUD_BROWSER_CONSOLE.md#chronicle閲覧の利用者受入2026-10-05)を参照。

次の接続はChronicleのAdmin強制判定。Positive / Negative / Unverifiedのみとし、既存の業務トランザクション・監査・所有状態再評価を共有する。全モードのAdmin操作、表示状態の競合検出、Crawl/復元/初期化との排他を検証する。実クラウドの確認項目は[Browser Console](../migration/CLOUD_BROWSER_CONSOLE.md#chronicleの管理者判定2026-10-05)を参照。通常Owner判定・申請審議・Claim本文編集・画像付き復旧は引き続き後続範囲。

2026-10-05追記：Admin強制判定（PR #40）は必須CI成功・main統合・ステージング配置済み。利用者がモーダル、取消し・外クリック、判定保存・再読み込み、Read only / Offline中の管理者操作、2タブの競合拒否、SignOut後の制限をすべて確認し、操作対象を元の状態へ戻したと報告した。この範囲の受入は完了。[確認記録](../migration/CLOUD_BROWSER_CONSOLE.md#管理者判定の利用者受入2026-10-05)を参照。履歴25件超の実クラウドページ移動は引き続き対象データ待ち。通常Owner判定・申請審議・Claim本文編集・画像付き復旧等は後続範囲。

次の移行範囲はUser DetailのOwned / Formerly Owned閲覧。既存の所有者再評価結果と共有した過去所有の表示条件を使用し、個体リンクをProduct Detailへ接続する。現在所有・過去所有の実データがない区分は操作受入と内容比較を分けて記録する。[仕様・確認手順](../migration/CLOUD_BROWSER_CONSOLE.md#user-detailのowned--formerly-owned2026-10-05)を参照。

2026-10-05の所有一覧受入：PR #41はCI成功・main統合・配置済み。利用者が空表示、ユーザー切替・再取得・左右独立スクロール、SignOut後の制限に問題なしと報告した。所有履歴の分類・総数・個体リンク、および25件超のページ移動は対象データがなく実クラウドでは未確認。隔離試験の成功と区別してデータ待ちとして残す。[確認記録](../migration/CLOUD_BROWSER_CONSOLE.md#所有一覧の利用者受入2026-10-05)を参照。

次の移行範囲はBrowser Consoleの管理者プロフィール編集。表示名・国・地域・自己紹介をAccounts正本へ保存し、既存の投影Jobで関連Snapshotへ反映する。正本Admin/モードの保存フェンス、比較版による競合拒否、監査との原子性、Crawl/復元/初期化との排他を確認する。[仕様・受入手順](../migration/CLOUD_BROWSER_CONSOLE.md#user-detailの管理者プロフィール編集2026-10-05)を参照。権限変更・BAN・一般ユーザー編集画面は後続範囲。
