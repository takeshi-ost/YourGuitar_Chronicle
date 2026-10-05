# クラウドBrowserConsoleのOperations接続

2026-10-04。認証確認サービスに `/console` を追加し、[管理API](CLOUD_OPERATIONS_ACCESS.md)へ接続した。これは段階的なクラウド移行用Consoleであり、ローカル版のデータ管理機能をすべて配置したものではない。

## 管理者の操作

1. 同じタブの[アカウント画面](https://ygc-staging-accounts-rgmjxrs5kq-an.a.run.app/account)で、メール確認済みの運営用YGCアカウントにSign Inする。
2. 表示されたBrowser Consoleリンクから `/console` を開く。URLを直接開くことも可能。未認証・未確認・非Adminの場合は案内のみで操作できない。
3. 右Detail層最上部のOperationsで現在のモードを確認する。Service statusタブでWeb応答・Accounts / Chronicle / Operations DB接続・対象別Storage読み取り・確認時刻を表示する。
4. MaintenanceタブでNormal / Read only / Offline / Admin Onlyを選び、必要に応じて案内メッセージを編集して保存する。Reasonは要求しない。モード変更時は日英の定型文を設定し、Normalは空とする。
5. 他の管理操作で設定が更新されていた場合は保存を拒否し、Refresh後に再編集する。Refreshは未保存入力を現在のサーバー設定で置き換える。自動更新は行わない。

左右に位置リンクを持ち、デスクトップでは左Mainと右Detailが独立してスクロールする。狭い画面では縦に並べる。言語変更・再読み込み後もSDKのタブ内セッションを使い、保存済みのモードを再取得する。ConsoleにもSignOutを設けた。

## 認証と保存の境界

Consoleの静的な外枠は公開されるが、管理データや操作者の情報をHTMLへ埋め込まない。操作欄の表示はサーバーの認証結果を使い、各管理APIは新しいGoogle ID tokenとAccounts正本の資格を再検証する。ブラウザが申告したrole・user_id・Consoleトークンは送らない。表示名・メッセージはテキスト／textareaとして表示し、HTMLとして解釈しない。

保存は現在のversionを送る。409では未保存入力を維持して再取得を促し、Saveを停止する。401 / 403では管理表示を消す。DB障害等でも保存を停止し、Refreshで再取得する。モード変更によるAdminの入口封鎖は行わない。監査と権限解除の競合制御は管理API側の責務であり、[管理API仕様](CLOUD_OPERATIONS_ACCESS.md)を参照。

## 実装・確認範囲

ローカル版の巨大なConsoleスクリプトを読み込まず、専用HTML・CSS・モジュールを使う。Google SDK・認証アダプター・辞書は認証画面と共有し、アセットは明示許可リストで配信する。

ブラウザ試験でGuest・一般ユーザー・未確認Adminの拒否、Adminによるモード保存と再読込み、同時更新の409、DB障害からの再取得、資格解除後の403、SignOut、タブのキーボード操作、表示内容のHTML非解釈、左右独立スクロール、日英・モバイル表示を確認した。Google操作とDBは当該ブラウザ試験内だけの代替であり、実ユーザーによる操作試験とは区別する。

残るのはコンテンツ・画像・Crawl・審議・バックアップ・復元／リセット等のAPIと画面の移行、ジョブ排他、全モード・権限解除・ジョブ競合を含む実環境の詳細受入試験。Service statusはDB接続とCloud Storageの対象別読み取り確認を行う。Reverb・GPTや全テーブルの健全性は確認しない。Storageの書き込み検証と移行範囲は[Storage接続](CLOUD_STORAGE.md)を参照。これらの未接続操作をクラウド画面へボタンだけ追加しない。

検証結果：Python555件、JavaScript71件、共通ブラウザ操作と新Consoleの操作検証、実PostgreSQLの4DB・権限／所有判定・Operations検証が通過した。辞書の空キーを検出して修正し、Python全体と関連ブラウザを再確認した。

## 配置記録

Cloud Build `6f72c649-1e98-4700-8abc-5115a8b9eacb` が成功。イメージ `account-api@sha256:22e39fc80ee8ae36a7ec0a60b110f5700d84e11bb14bf40a8db9e5662cffb19e` を `ygc-staging-accounts-00005-j25` へ配置した。DBスキーマとモード、初回Admin・同期Jobの配置は変更していない。

実URLのConsole・許可アセット・readyが200、無認証の管理APIが401。公式SDKが初期化された匿名ブラウザで管理欄が非表示になり、認証画面が利用可能であることとデスクトップ／モバイル表示を確認した。OperationsのOfflineを維持。続いて利用者が実環境のBrowserConsole操作を確認した（2026-10-04）。これは利用者による確認結果であり、エージェントによる代理ログインではない。個々のモード・競合等の詳細受入試験をすべて完了したとは扱わない。

GitHub Actionsの共通CIも成功した（run `37208270805`、実装コミット `16e102e`）。mainへの統合状況はPR #22 / #23 / #24とGit履歴で確認する。

## ギター閲覧の追加（2026-10-05）

左のGuitar DB Managementと右のProduct Detailに、Admin用の一覧・検索・ページ送り・基本情報閲覧を追加した。Operationsと取得障害を分離し、左右独立スクロールを維持する。編集・画像・Chronicleは未接続。[仕様と確認範囲](CLOUD_GUITAR_BROWSER.md)を参照。

## DB別バックアップ一覧（2026-10-05）

Database backupsで対象を選び、保存時刻・版・テーブル／行数を閲覧する。現段階の保存はIAM専用Jobで、Console保存ボタン・定期保存・保持・復元は未接続。[保存基盤と検証](CLOUD_DATABASE_BACKUPS.md)を参照。

## 手動保存の追加（2026-10-05）

DB選択と「今すぐ保存」、開始／保存中／成功／失敗／結果未確認の表示を追加した。保存要求は永続化し、画面再読み込みでも状態確認を再開する。固定Job単体の起動・引数上書き・実行状態参照とOperation参照に必要なIAM変更を利用者が承認し、ステージングの保存操作を有効化した。アプリSAからのAccounts保存と状態参照、匿名拒否、Offline維持は確認済み。実AdminのConsoleからの開始・再読み込みは利用者確認を待つ。[接続仕様と確認範囲](CLOUD_DATABASE_BACKUPS.md#console手動保存の接続)を参照。

## DB別の保存設定と復元・初期化（2026-10-05）

手動保存（PR #29）は利用者の実操作確認済み。DB別の定期保存・間隔・保持世代（PR #30）はmainへ統合し、毎時IAM Schedulerを配置した。定期保存の初期値はOFF。以降、バックアップ一覧の各行から復元し、選択DBのテストデータを初期化する確認モーダルを追加・配置済み。DB名入力、メンテナンスモードと正本Adminの確認、保護用バックアップ、要求の永続化、再読込後の結果確認を必須とする。Accountsの登録・認証・現在の権限、Operationsのモード・監査・保存履歴を保持する。詳しい範囲と制約は[DBバックアップ](CLOUD_DATABASE_BACKUPS.md#現在の到達点と復元初期化2026-10-05)を参照。

PR #31の必須CI成功・main統合・実配置、非公開Jobの4DB読取り接続と匿名管理API拒否を確認済み。実管理者ブラウザの受入はComputer Use許可待ちで中断し、[確認する操作一覧](DB_OPERATIONS_ACCEPTANCE.md)を記録した。

### 利用者による操作確認（2026-10-05）

利用者が[受入一覧](DB_OPERATIONS_ACCEPTANCE.md)の全項目を操作し、動作上の問題がないことを確認した。ブラウザ操作の受入は完了。項目5・6・7は対象業務データが空のため、保存時点への復元・初期化による削除・対象外DBや最新ユーザー情報の維持について、実データの内容比較は未検証。隔離PostgreSQLのデータ入り検証は成功済みだが、実クラウドでの内容検証完了とは扱わない。データ投入後の実復旧試験を残す。

### Reverb Crawlの接続準備（2026-10-05）

左Web Crawlの年範囲・間隔・Crawl Now・実行ログ、右Operations/Background jobsのReverb Autoチェックと最終開始時刻を実装。PostgreSQLと専用Jobへ接続する。現在はSecret登録と実配置が未完了で、実ステージングの画面にはまだ追加していない。[仕様と再開時確認](CLOUD_REVERB_CRAWL.md)を参照。


2026-10-05の件数表示修正：Guitar DB Managementのページ件数へ翻訳パラメーターを渡す。1ページ25件で、先頭ページのPreviousと次ページがない場合のNextは無効。表示にページサイズを明記し、28件の往復移動と1件検索で件数・ボタン状態をブラウザ検証する。


個体総数表示：ページ内件数を廃止し、Chronicleのindividuals全体をCOUNTして総数を表示する。検索・ページ移動で総数を絞り込まず、一覧と総数を同じ読取りスナップショットで取得する。Refreshで最新状態を再取得し、Crawlや復元・初期化前後の差分を確認する。


## User DB ManagementとUser Detail

Accounts正本の読取りを接続。左Mainにユーザー一覧・総数・名前/ID検索・25件単位のPrevious/Next、右DetailにUser Detailを配置する。ヘッダーUser DBの位置リンクは左右それぞれの該当領域へジャンプし、ジャンプ後もスクロールは独立。未選択時も右パネルは画面高に合わせ、詳細は1項目ずつ表示する。

Adminの確認済みIdentity Platform認証とAccounts正本の現在権限を各APIで確認する。全メンテナンスモードで閲覧可能。一般ユーザー・無効化ユーザー・未確認メール・SignOut後は管理APIで拒否する。数値IDと件数は文字列で返してBIGINT精度を保ち、取得SQLの対象列を固定する。表示項目はID/UUID、名前、アカウント種別、権限、ログイン有効状態、BAN状態、国/地域、自己紹介、登録/更新日時。Identity資格情報・生トークン・Storageパスは返さない。

Automation等のログインできないsourceアカウントも一覧と総数に含む。編集、権限変更、BAN操作、Owned/Formerly Owned、SNS表示は別の後続範囲。Accountsの変更やGoogle認証ユーザーの追加/削除は今回行わない。

配置後の確認：Adminで再読み込みし、User DBの表示、既存登録ユーザーとsourceアカウント、検索・総数・Detailの該当表示、左右独立スクロールを確認する。SignOut/一般ユーザーでは管理表示が利用できないことも確認する。


### User DB閲覧の利用者受入（2026-10-05）

PR #38は必須CI成功後mainへ統合し、ステージングへ配置済み。利用者が案内した5項目すべてを確認したと報告した。

| 確認項目 | 状態 |
| --- | --- |
| 左User DB Managementの一覧・総数 | 確認済み |
| 名前またはIDによる検索 | 確認済み |
| Detailで右に該当ユーザーを1項目ずつ表示 | 確認済み |
| 左右の独立スクロール | 確認済み |
| SignOut後の管理表示制限 | 確認済み |

閲覧機能の受入は完了。一般ユーザーのAPI拒否・全モードでのAdmin閲覧は隔離試験で検証済みであり、今回の利用者報告に含まれない実ブラウザ操作まで確認済みとは扱わない。編集・BAN・Ownership表示は後続。


## Product DetailのChronicle読取り

Chronicle正本のClaim履歴をProduct Detail内へ接続する。初期25件、IDの降順カーソルでPrevious/Nextを使い、個体ごとの履歴総数を表示する。Refreshで選択中個体の最新履歴を再取得する。Positiveは展開カード、Unverifiedはタグ、Negativeは点から詳細を展開する。非活性ClaimとBANによる非活性状態は管理履歴として明示する。

表示対象はClaim種類・判定状態・有効状態・投稿者名・日時・本文/値と、固定したListing項目・最大20個のSpecification項目。画像・Storage参照・申請の非公開説明・Evidence payload・GPT診断は取得しない。テキストはDOMのtextContentで表示する。名前や値の長さを制限し、Adminの現在資格を毎回確認する。追加の編集・判定・投票操作は提供しない。所有権、Claimの判定状態、Snapshotには書込みしない。

隔離PostgreSQLではListing/Specification/Ownershipの取得、個体単位のページング、除外フィールド、所有者不変を確認し、既存の自己判定禁止・Acquire承認待ち・譲渡後の権限移動・管理者別経路も共通回帰試験で確認する。

配置後の確認：収集済み個体のDetailを開き、ChronicleのListing/Specificationなどと履歴総数、展開/折畳み、Refresh、複数履歴のPrevious/Next、別個体へ切り替えた際の該当履歴表示を確認する。SignOut後は履歴を閲覧できないことも確認する。


### Chronicle閲覧の利用者受入（2026-10-05）

PR #39は必須CI成功後main統合・ステージング配置済み。利用者報告を以下の通り記録する。

| 確認項目 | 状態 |
| --- | --- |
| 1. 収集済み個体のDetailにListingなどの履歴を表示 | 確認済み。問題なし |
| 2. 展開・折畳み・Refresh | 確認済み。問題なし |
| 3. 別個体を選んだ際の該当履歴への切替 | 確認済み。問題なし |
| 4. 履歴25件超でのPrevious/Next | 対象個体がないため実クラウドでは未確認 |
| 5. SignOut後の管理履歴表示制限 | 確認済み。問題なし |

ページ移動は28件の隔離ブラウザfixtureで往復を、隔離PostgreSQLで降順カーソルを検証済み。実クラウドの利用者受入完了とは扱わず、25件超の個体ができた段階で項目4を確認する。テストのために実Claimを追加・改変していない。

## Chronicleの管理者判定（2026-10-05）

各Claimの展開欄に「管理者による判定」を追加する。確認モーダルにはClaim ID・現在の判定・所有者と個体情報の再評価への影響を表示し、Positive / Negative / Unverifiedを選んで適用する。取消し・Escape・モーダル外クリックでは更新しない。適用後は一覧、Product Detail、Chronicleを再取得する。削除、Claim本文編集、通常Ownerによる判定、Acquire画像審議は今回の対象外。

認証済みメールとAccounts正本の現在Admin資格を毎回確認し、全モードで管理者の修復操作を許可する。通常ユーザーの自己判定禁止・Ownerの判定権限とは別経路。既存PostgresOwnership / Repositoryの業務処理で判定、監査履歴、Observation・Snapshot・Owned分類の再評価を同一トランザクションで行う。正規のFormer Ownerペアは既存仕様どおり同時判定する。

表示時のClaim状態から生成した比較トークンを、書込みトランザクション内の状態と照合する。古い表示は409で拒否する。Crawl・復元・初期化と同じOperationsの排他ロックを、正本Account・モード・Chronicleのロックより先に取得する。同時実行中は更新を拒否し、画面から自動再送しない。応答が失われた場合も、履歴を再取得して結果を確認してから再操作する。IAMやDBスキーマの追加変更は不要。

配置後のブラウザ確認：

1. Chronicleを手動保存し、Auto CrawlをOFFにしてテスト用個体のSpecificationを選ぶ。
2. 管理者判定モーダルの取消し・Escape・外クリックで判定が変わらないことを確認する。
3. 元の判定を記録してNegative、Unverified、元の判定へ変更し、Refresh・再読み込み後も結果が一致することを確認する。
4. Read only / Offlineでも同じ操作が可能であることを確認し、試験後は元の判定とサービスモードへ戻す。
5. 2タブで同じClaimを開き、片方で変更した後、古い表示からの変更が競合として拒否されることを確認する。もう一方をRefreshし、元の判定へ戻す。
6. SignOut後は判定操作が利用できないことを確認する。

所有状態を変更するAcquire / Transfer / Listingを最初の操作対象にする必要はない。実クラウドでの利用者受入は配置後に記録する。

隔離検証：Python743件・JavaScript71件、共通ブラウザ試験、実PostgreSQL試験が成功。今回の追加では確認・取消し・Escape・外クリック、適用後の再取得、競合拒否、全4モードの管理者更新、非Admin拒否、Crawl/メンテナンス排他、監査actorを検証した。所有権の自己判定禁止・Acquire承認待ち・譲渡後の権限移動・A→B→C継続・管理者別経路は既存共通回帰も成功。
