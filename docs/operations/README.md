# Browser Console 管理操作ガイド

対象：現行ローカル版の管理担当者。英語ラベルを目印に、操作場所・手順・結果を記す。一般利用者の操作は[ユーザーガイド](../user-guide/README.md)、判定の詳細は[Claim管理仕様](console-claim-administration.md)。Consoleの資格はlocalhostとページが発行する管理トークンによるもので、公開環境のAdmin認証ではない。

## 画面と対象の選択

左MainにWeb Crawl、Guitar DB Management、User DB Management、Ownershipを配置し、右DetailにOperations、Product Detail、User Detailを配置する。左右は独立してスクロールする。ヘッダーの位置リンクはWeb CrawlならOperations、Guitar DB／OwnershipならProduct Detail、User DBならUser Detailにもジャンプする。その後のスクロールは連動しない。

Product Listの行を選ぶと右Product Detailに対象個体を表示する。メーカー・モデル・Finish・年式・シリアルで絞り込み、列見出しで並べ替えられる。Usersの行を選ぶと右User Detailに表示する。主要リストは行選択後の上下キー移動、デスクトップでの列幅変更に対応する。

申請・係争一覧のApplicant / OwnerからUser Detail、GuitarからProduct Detailへ対象を表示できる。表示中のユーザー・ギターを確認してから管理操作を行う。

## Web Crawl

### 接続と手動実行

1. Reverb API Tokenにトークンを入力してSaveし、Token OKを確認する。入力値はブラウザに保存する。Deleteはブラウザ保存値を消す操作で、環境変数のトークンは消さない。
2. Incremental CrawlでYear Min / Year Maxを設定する。FieldはElectric + Acoustic Guitarsの一括対象。
3. Crawl Nowを押し、Crawl Run Logで実行中の進捗と終了結果を確認する。両カテゴリ合計で最大2,000掲載を処理し、カテゴリ別の検索位置を保持する。
4. 例外的なクエリ指定の収集はManual Crawlを開き、検索語・件数上限・並列数・年範囲を設定してStart Crawlを押す。開始後はモーダルが閉じ、ログへ移動する。

Crawl前にChronicleのバックアップを保存する。ログはRefreshで再取得できる。ウィンドウを閉じる操作は開始済みジョブの取消ではない。対象・新品除外・ログの数値は[Crawl仕様](../features/incremental-crawl.md)を参照。

### Auto Crawl

Web CrawlのAuto Crawl interval (hours)を1〜168時間で設定し、Save intervalで保存する。右Operations → Background jobsのReverbチェックでON / OFFを切り替える。年範囲などもWeb Crawlの設定を使う。最終実施時間とログを確認する。スイッチは再起動後も残るが、サーバープロセス停止中には実行されない。

## Operations

最上部の大きな状態表示でNormal / Read-only / Offlineを確認する。Refresh every 15 secondsは表示の自動更新であり、Crawl実行間隔ではない。

| タブ | 確認・操作すること |
| --- | --- |
| Service status | 稼働時間、DB、画像保存先などの状態 |
| Maintenance | モード・利用者向けメッセージを変更して保存 |
| Background jobs | Crawl / backfillの実行状態、Reverb自動収集、ChatGPT審議反映、最終実施・回答時刻 |
| Operation history | モード・スイッチ変更などの運用履歴 |
| Version and deployment | アプリのバージョンとローカル環境表示 |

メンテナンスはRead-only（一般更新停止）またはOffline（一般利用停止）を選び、定型の初期メッセージを必要に応じて修正して保存する。Reasonの入力は必須ではない。復旧時はNormalへ戻す。設定競合が出たらRefreshし、最新状態を確認して操作し直す。

Acquire / Listing reviewのChatGPTチェックをOFFにすると、GPTからの回答受信・保持は続くが審査中データへの反映を停止する。これは提出済み申請の取消や実験キューの削除ではない。ON / OFFは再起動後も保存される。[運用仕様](../features/SERVICE_OPERATIONS.md)を参照。

## バックアップの保存・復元

Guitar DB ManagementのBackupsを開く。Targetは次の4種類で、保存・周期・保持世代を個別に管理する。

| Target | 主な内容 | 復元の影響 |
| --- | --- | --- |
| Guitar / Chronicle | 個体、Claim、正式申請、係争、収集情報、コンテンツ画像 | ギターと来歴を戻す。現在のアカウント正本は維持する |
| User Accounts | Profile、認証ID対応、Follow、DM、Avatar | ユーザー情報・交流を戻す。バックアップ後の登録アカウントはIDを保持して無効化する |
| Operations | モード、スイッチ、周期設定、運用履歴 | 運用設定も保存時点へ戻る |
| Authentication experiment | 実験キュー、画像、接続設定、結果 | 正式Claimと独立した実験データを戻す |

### 保存と定期設定

1. Targetを選び、Save backup nowで現在の状態を保存する。バックグラウンドジョブ実行中は終了を待つ。
2. 定期保存はPeriodic backupをONにし、Interval (hours)を1〜168、Keep lastを1〜100に設定してSaveする。
3. 保存一覧と実施結果を確認する。保持数は対象別で、上限超過時に最古の世代を削除する。Chronicleでは手動・定期・Crawl前・復元前保存が同じ保持枠を使う。
4. 必要な保存済みバックアップをDownloadして手元へ取得できる。閲覧・ダウンロードはNormalでも可能。

### 復元

1. Target、保存日時、ファイル名を確認する。保存済み一覧のRestore、またはRestore from fileで手元のバックアップを選ぶ。
2. 復元にはメンテナンスが必要。Read-onlyへ切り替え、バックグラウンドジョブ終了後に実行する。Offlineは一般APIも停止するため、Consoleの復元操作ではRead-onlyを使う。
3. 画面の置換範囲と確認内容を読み、復元を確定する。復元前には現在状態のバックアップを作る。
4. 完了後、対象一覧・Detail・Operationsの状態を再確認し、利用再開時はNormalへ戻す。

Chronicle復元は登録ユーザーを巻き戻さないが、未知のユーザーIDやUUID衝突を含むデータは拒否する。Accounts復元ではセッションを破棄する。旧Chronicleの `.db` ファイルは画像を含まない。[DB構造と復元境界](../architecture/DATABASE_STRUCTURE.md)を参照。

## Guitar DB Management：既存DBの修正

DB Maintenanceを開き、目的に合う操作を選ぶ。Crawl Nowと異なり、既存記録の移行・補完・再処理を行う。

| ボタン | 手順・結果 |
| --- | --- |
| Claim Migration | 旧DBの未移行件数を確認し、移行を確定。Claim化とSnapshot再構築の結果・Ready状態を確認する。移行済みならその旨を表示する |
| Backfill existing DB (one time) | 既存Reverb掲載を再取得して不足するListing情報を補完する。開始後はCrawl Run Logで結果を確認する |
| Clean and add Specifications | 確認後、誤った自動抽出・重複Finishを整理し、保存済み詳細からユーザーOwnerのいない個体へ仕様を補う。修正・作成・除外件数を結果表示で確認する |
| Reprocess saved details | Web Crawlの両カテゴリ・年範囲を使って保存済み詳細を再判定する。Reverbへの再アクセスは行わない。結果はCrawl Run Logに表示する |
| Show candidates for review | 照合保留候補を表示する。この一覧から候補を承認する操作は未実装 |
| Inspect duplicate guitars | 重複候補群を開き、残す個体を指定してMerge / Deleteする（下記） |
| Reset DB | 確認ダイアログ後にRESETを入力するとChronicleとコンテンツ画像を削除・再初期化する。自動復元は行わない |

Reset DBはAccounts、Operations、実験キューの全消去ではない。Accountsからユーザー・交流の投影を再作成するため、アカウントは残る。画面の「Deletes guitar and user data」は実際の削除範囲を正確に示していない。所有履歴・お気に入り・コンテンツ通知などChronicle内情報は失われる。

現在のReset DBはNormalモードで実行する。Read-only / Offlineでは管理者のReset DBも停止する（バックアップ復元とは条件が異なる）。再クロールのために初期化するときは、ReverbのAuto CrawlとChatGPT審議反映をOFFにし、実行中Crawlの終了を待ち、Guitar / Chronicleの手動バックアップを保存・必要ならDownloadする。その後NormalでReset DBを実行し、Incremental Crawlの年範囲を設定してCrawl Nowを押す。初期化前に始まった審議の遅延回答には注意し、古い申請がある場合はその反映を再開する前に確認する。

Statisticsボタンは集計モーダルを開く。Refreshで集計を再取得する。統計表示自体はDBを書き換えない。

### 重複候補のMerge / Delete

1. Inspect duplicate guitarsで同じ正規化メーカー・シリアルの候補群を開く。この一致だけで同一個体とは確定しない。
2. 個体IDをクリックして詳細を確認し、Keepのラジオボタンで残す個体を一つ選ぶ。
3. Mergeは他個体の履歴を残す個体へ統合する。一部のPositive ClaimはUnverifiedへ戻り、再確認が必要になる。
4. DeleteはKeep以外の個体と関連記録を削除する。確認後にDELETEを入力する。履歴は統合されない。
5. 更新された候補一覧、残した個体のChronicle・Snapshot・Ownerを確認する。候補群が変更されている場合は拒否されるため、再取得して選び直す。

## Product Detail：Claimの管理と個体削除

### 現在値の採用理由を調べる

Product Detail → Chronicle最上部のObservation decisionを開く。Claimごとの候補値、採用項目、最下段の保存済みSnapshotを比較する。これは読み取り専用で、ここから値を書き換える操作はない。

### Verificationの強制変更・Claim削除

1. 対象個体を選び、Chronicleの対象Claimを確認する。UnverifiedのタグやNegativeの点もクリックして詳細を開ける。
2. 管理欄でPositive / Negative / Unverifiedを選び、確認する。Snapshotを再評価し、所有状態やProfile分類も変わり得る。
3. 管理用DeleteはClaimをハード削除する。通常ユーザーのinactive化とは異なり、正規のOwnershipペアも対象となる場合がある。
4. Listing削除では、最後の有効なListingなら個体と関連記録も削除されることを追加確認する。
5. 反映後のOwner、Chronicle、Observation decisionを確認する。

通常Ownerの判定は他ユーザーの対象Claimに限り、自己Claimや自身の所有根拠となるPositive Transferを変更できない。管理者の強制判定は別経路。係争ロック・裁定済みClaimの制限は管理者にも適用され、通常の強制判定で迂回せず係争の再審議を使う。

### 個体全体の削除

Product DetailのDelete Individualを押すと、対象個体と関連Claim・所有リンクなどの削除を確認する。DELETEの入力で確定する。Claim一件の削除とは範囲が異なる。係争履歴などの制約で拒否される場合がある。

## User DB Management

UsersをID・名前・種別・居住地で検索し、行を選ぶ。User DetailにはID・日時・ギター関連を表示し、編集欄は一項目ずつ並ぶ。

| 操作 | 手順・結果 |
| --- | --- |
| Create account | ローカルの新しいアカウントを作り、User Detailで必要な項目を編集する。Identity Platformへの登録ではない |
| Save User | Display Name、Account Type、BAN Status、Theme、居住地、Bio、4項目の公開範囲、Signature Guitarを編集して保存 |
| Avatar image | ファイルを選んでSave User。Profile保存後に画像を別処理で更新するため、画像だけ失敗した場合は警告を確認して再選択 |
| Open Top Page as this user | 選択ユーザーの操作用Top Pageを新しいタブで開く。既存の別タブの操作ユーザーは変更しない |
| Open Top Page as Guest | GuestのTop Pageを新しいタブで開く |
| User Profile | 選択ユーザーのProfileを開く。閲覧対象と操作ユーザーは別になり得る |

管理用Account Typeにはuser / shop / builder / repairer / organizationを選べる。公開登録フォームのUser / Shopとは選択範囲が異なる。ID・認証ID・保存パス・日時・計算値は直接編集しない。生年月日の値を編集する入力欄は現行Consoleにはなく、公開範囲のみ編集できる。Signature Guitarの変更先は所有中の個体に限る。

### BANの変更

BAN Statusを選びSave Userで反映する。Normal以外への変更は確認を挟み、公開Claim・Snapshotを再評価する。

| 状態 | 効果 |
| --- | --- |
| Normal | 通常状態。BAN解除時は保持済み記録の公開効果が復帰する |
| Silent BAN | 記録を保持したまま他人への公開効果を停止する。本人向け表示には試作上のプレビューがある |
| BAN | 公開効果と今後のClaim投稿・投票を停止する。記録の削除ではない |

## Ownership：Request

RequestはListing / Acquireの正式申請一覧。初期フィルターIncompleteは未確定案件を表示する。履歴を含めて探す場合はAll statusesまたは個別状態に切り替え、Request ID・申請者・個体・シリアルで検索する。

1. DetailでRequest Detailsを開く。
2. 申請状態とClaimのVerification、申請者・Current Owner、提出写真・比較画像、原AI審議を含むReport and historyを確認する。
3. Reason for changeを入力し、状態に応じて表示された管理ボタンを選ぶ。操作の影響と理由を確認して確定する。
4. 更新された申請状態、Claim、Ownerを確認する。競合が出たら詳細を開き直す。

| ボタン | 操作結果 |
| --- | --- |
| Override: Approve | 画像審議の採否を管理者として採用。Listingなら個体と初期所有を作成・復元。AcquireならClaimを作成・復元するが、既ユーザーOwnerの承認とは別 |
| Override: Reject | 画像審議を不採用へ変更。既存ClaimがあればNegativeにして所有状態を再評価 |
| Queue Another Review | 元の結果を履歴に残し、GPT審議を再度キューへ入れる |
| Cancel Request | 申請を取り消し、進行中審議の結果を以後反映しない |
| Verification → Positive / Negative / Unverified | 作成済みClaimのVerificationを管理者として強制変更し、所有状態を再評価 |

全ボタンが常時表示されるわけではない。画像審議の採用とOwner承認・Verificationを混同しない。理由は申請者にも表示される。原AI診断と管理者判定は別に保持する。

Other Pending Acquire Claimsは正式申請一覧とは別に、承認でCurrent Ownerが変わり得る未承認Acquireを表示する互換管理入口。行から個体を開いてClaimを確認する。場所だけ変わるものや後続Claimに覆われるものなどは対象外。

## Ownership：Disputes

1. Under dispute / Resolved / All casesで絞り、Detailを開く。
2. 各当事者のClaim、却下理由、提出ラウンド、非公開説明、添付資料、管理履歴を確認する。
3. 相手へ公開する要旨はReview summary for sharingで編集し、Publish reviewed summaryで公開する。公開済み要旨は上書きできない。
4. Decision / request reasonを入力し、次の管理操作を選ぶ。申請者支持の場合はApplicant to supportも指定する。
5. 裁定後の所有状態と係争状態を確認する。

| ボタン | 操作結果 |
| --- | --- |
| Request additional evidence | 理由付きで次の提出ラウンドを開始する。提出状況により操作できない場合がある |
| Support original owner | 元Ownerを支持して係争を決着させる |
| Support applicant | 選んだ申請者を支持して対象Claim・所有状態を更新する |
| Reopen for reconsideration | 決着済み案件を理由付きで再審議する |

裁定は資料が揃う前でも可能だが理由が必須。係争中は所有関係の変更がロックされ、決着済み対象Claimは通常管理操作から変更できない。[係争仕様](../features/OWNERSHIP_DISPUTES.md)を参照。

## Ownership：Authentication（GPT実験）

正式申請と独立した実験用キュー。ここで採用結果が出てもClaimや所有状態は変わらない。

1. 指定画像と期待文字列を入力し、①テスト申請を追加を押す。②ローカル接続診断は接続・ツール一覧の確認だけで、画像審議を開始しない。
2. 保存済み接続設定を表示／接続を有効化でMCP接続設定を取得する。接続キーは表示・コピーでき、再起動後も保持される。
3. ③一覧・結果を更新、または表示中の自動更新で状態を確認し、行を選んで結果を見る。
4. エラーのRetry、不要な申請のCancel、終了済み申請のDeleteを必要に応じて行う。Delete前にJSONや診断文章を保存できる。
5. 接続キーを失効は記録を残してキーと進行中leaseを失効させる。記録の全削除ではない。

最大100件・画像256MB。YGC自体は外部クライアントのスケジュールを作成しない。接続と再試行の詳細は[Authentication Test](../features/AUTHENTICATION_TEST.md)を参照。

## 操作失敗時と確認の範囲

競合・ロック・実行中ジョブなどで拒否された場合は、エラーを確認して最新の一覧・詳細を再取得する。モーダルの外側クリックやEscapeで閉じても、開始済み処理は取り消されない。未保存の編集は失われる場合がある。

所有状態に影響する操作の後は、Current Owner、Owned / Formerly Owned、判定権限を組み合わせて確認する。通常ユーザーの自己Claim禁止、Acquire承認前後の権限移動、Transferの独立評価、管理者の別経路は[設計上の不変条件と遷移例](../architecture/CLAIM_CENTERED_ARCHITECTURE.md)を基準にする。
