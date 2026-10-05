# Reverb CrawlのPostgreSQL接続

2026-10-05。クラウド向けのCrawl DBアダプター、IAM専用Job、Admin APIとConsoleを実装した。Secret version 1の登録と有効状態を確認し、専用Job/Schedulerを配置した。DB接続とReverb認証の読取り試験は成功。Console配置後の実Crawl・データ内容の受入は未完了。

## データ保存と所有状態

既存のincremental_crawl / candidate処理とRepositoryのListing・Acquire・Lost・Specification・Observation判定を使う。PostgreSQL側では既知の4テーブルのINSERT IDをRETURNINGで返し、外部掲載の既知ID照合を明示したJSONBクエリへ切り分ける。SQLiteへ接続するフォールバックやランタイムのスキーマ初期化は行わない。ローカルでも使う2箇所の重複INSERTは双方で使えるON CONFLICT DO NOTHINGに揃えた。

対象はElectricとAcoustic Guitarsの両方。カテゴリなしをタイトルからギターと推定せず、詳細でも種類・製造年を確認する。既存の両カテゴリを一つの実行ログへ集約する処理を維持し、Jobでは1回に処理する検索結果を1〜2,000件で指定でき、初期値は2,000件。件数はElectric/Acoustic両カテゴリ合計で、1件・奇数でも超過しない。条件による除外や既知IDを含むため、新規登録数とは異なる。途中カーソル・候補・詳細・完了ログはChronicleで保持し、次回に続きから処理する。既存個体・Listing IDの重複、曖昧な個体照合、Ownerありの再掲載Acquire承認待ち、ユーザーOwnerにLostを適用しない規則を維持する。

AutomationはAccounts正本の通常の正整数ID予約とUUIDを持つsourceアカウントとして作る。disabled=1、member、Google Identityリンクなしでログインできない。metadataキー system_actor:automation を使い再実行で増殖させない。ユーザー新規登録と同じ連番を使い衝突を防ぐ。復元時も最新Accountsの再投影対象となる。CrawlはAccountsをバックアップしない。

短いDBトランザクションでAccountsをSHAREロックし、Chronicleの共通投影ロックを取る。投影receiptを一括で照合し、UUID不一致を拒否、古い版だけ更新する。Reverbとの通信中はユーザーDBのロックを保持しない。手動実行者の正本Admin資格は各トランザクションで再確認する。

## 実行前保存と重複防止

最初のコンテンツ変更前にChronicleだけを既存の保存処理で保存・ハッシュ検証・GCS読み戻し検証・台帳コミットする。保存失敗時にReverbへアクセスせず、個体を更新しない。保存のsourceはcrawl、復元前保存はpre_restoreとする。成功後にChronicleの世代保持を適用し、削除失敗なら保存を残してretention_pendingを記録する。他DBの保存周期・保持設定には触れない。

手動要求は確認済みGoogleトークンと正本Adminで受け、年範囲と要求UUIDだけを保存してから固定Jobを起動する。同じUUIDで再起動せず、他の操作主体や年範囲への使い回しを拒否する。30分の未完了期間はCrawl/復元/初期化の重複要求を拒否する。Jobでも復元と共通のsession advisory lockで直列化する。通信結果が不明でも自動で手動要求を再送しない。処理が途中までコミットされ得るため、失敗表示を「DB未変更」と扱わず、カーソル・実行ログ・保護用保存を確認する。

## Consoleと自動実行

左のWeb Crawlに製造年の範囲、件数（初期値2,000）、Auto Crawl間隔（1〜168時間）、Crawl Now、Crawl Run Logを配置する。右OperationsのBackground jobsにCrawl / Reverbのチェックボックスと実際にJobが始まった最終日時を表示する。チェックボックスでAutoのON/OFFを保存する。実行中にもOFFにでき、開始済みJobをキャンセルせず新規の自動開始を止める。左右のスクロールは独立を維持する。

自動実行はIAM Schedulerが毎時Jobを呼ぶ。Auto=ON、Normal、期限到達、未完了のCrawl/DB管理要求なしの場合だけ始まる。初回は指定間隔に最大約1時間の待ちが加わる。カーソルが完了した次の自動周期では検索を再開して新着を検出する。成功後のnext_runは設定が途中で変わっていないときだけ更新する。OFF・メンテナンス中の新規開始を止めるが、開始済み実行のキャンセルは行わない。

未配置のWebではCrawl管理APIの一覧は利用できてもavailable=falseで操作を無効にする。明示デプロイフラグ --enable-crawl-controls のときだけ固定Jobクライアントを接続する。トークン・任意Job名・API URL・実行引数をブラウザへ渡さない。実行ログには段階と件数を保存し、例外の本文は保存/公開しない。

## 利用者が行う認証情報の登録

GCPプロジェクト your-guitar-chronicle-staging のSecret Managerでシークレットを作成する。

- 名前：ygc-staging-reverb-token
- 値：取得済みのReverb APIトークン
- レプリケーション：自動
- 初回version 1を有効な状態にする。値はチャット・Git・一般設定ファイルへ貼り付けない。

実装・CI・不変イメージのビルド成功後、scripts/deploy_cloud_crawl.pyで専用SAと非公開Job/Schedulerを配置する。スクリプトはSecretの有効な版のメタデータを確認するだけで、値を読み出さない。Secretがない場合はIAM/Jobの変更前に止まる。専用SAはCloud SQL接続、DBパスワードとReverbトークンのSecret単体参照、contentバケットのObject操作だけを使用する。Accountsバケットの権限とSA鍵は追加しない。アプリとSchedulerのJob起動/引数上書き/状態参照は既存runnerロールをこのJobだけに付与する。

Jobの既定は--check-only（読取り接続確認だけ）。--probe-onlyはReverbに1件の検索を行って認証を検証するだけでDBを変更しない。認証成功後にConsoleを有効化し、利用者がCrawl Nowの受入を行う。Crawlの実要求をSQL直書きや擬似ユーザートークンで作らない。

## 検証範囲と再開時の確認

2026-10-05の統一検証はPython 683件、JavaScript 71件、Chromiumブラウザ試験と隔離PostgreSQL試験がすべて成功した。実クラウドのReverb認証・収集結果の検証とは区別する。

隔離PostgreSQLで実Collectorの応答を模したfixtureを使い、カテゴリ/年のフィルタ、Listing/Evidence/Specification、既知ID/再掲載、Lost、OwnerありAcquire承認待ち、Source IDと新規登録、永続要求再送、保存失敗時の通信停止、Chronicleだけの保護用保存、Auto OFF/メンテナンス/期限到達/再実行を検証する。通常OwnerとAdminの判定権限・自己判定禁止・A→B→Cの譲渡とOwned区分も既存共通PostgreSQL試験で確認する。ブラウザでは設定の保存/再読み込み、Crawl Now、実行中Auto OFF、ログと左右スクロール、SignOut・一般ユーザー拒否を確認する。

実クラウドではSecret登録・認証確認・配置後に、次を確認する。

1. AdminのConsoleにWeb Crawlと右Background jobs / Reverbが表示される。
2. Auto OFFのまま狭い製造年範囲でCrawl Nowを実行し、状態・ログ・保護用Chronicle保存が増える。
3. Guitar DB Managementで収集個体がギターだけであり、ListingのID重複がない。続けてCrawl Nowを押し、カーソル継続と既知個体の重複防止を確認する。
4. ON/OFFと間隔の保存・再読み込み、Normalでの期限到達の自動実行、メンテナンスで新規自動開始しないことを確認し、試験後OFFに戻す。
5. データが入った段階で[DB復旧受入](DB_OPERATIONS_ACCEPTANCE.md)の保存→変更→復元、初期化→復元、対象外DB・最新ユーザー情報の維持を確認する。

画像付きChronicle（media_assets）の復元、ユーザー向けTopPageや残るクラウド編集APIは後続。ReverbのListing画像URLはClaimの外部根拠として保持し、今回media_assetsに画像をコピーしない。

## ステージング接続確認（2026-10-05）

- 実装はPR #33でCI成功後main `7173c5d`へ統合。
- Cloud Build `d035711e-96ae-47f8-9d62-9ee2570b54de`が成功。イメージdigest `sha256:4a104e702e5f836cc5e92576dd4869bec68127295eeb513d93b525f3c26963bb`。
- 専用Jobのcheck-only実行 `ygc-staging-reverb-crawl-w4w7z`とprobe-only実行 `ygc-staging-reverb-crawl-kthqv`が成功。どちらもDB内容を変更しない。
- Backup/Scheduled Backup/Maintenance Jobも同じイメージに更新。初期化・復元・実Crawlはエージェントから実行していない。
- 初回配置でgcloudの未作成Job応答「Cannot find job」を修正し、専用Job/Schedulerの作成成功を確認。応答の回帰テストを追加。

- Consoleを同じイメージで配置し、ready revision `ygc-staging-accounts-00014-g85`を確認。公開health/ready/Console/Crawl JSは200、匿名Crawl GET/POSTとバックアップGETは401。既存Offlineモードとメッセージを維持した。Auto設定を書き換える管理者操作は行っていない。
- 管理者ブラウザでの実Crawl、定期開始、データ入り復旧は上記5項目の受入待ち。

件数設定はOperationsの管理設定イベントに保存し、Auto再開時も使用する。既存設定に件数がない場合は2,000件を使う。手動要求は件数を固定して保存し、同じ要求UUIDで違う件数への再利用を拒否する。追加DDLは不要。少数件数・設定再読み込み・Jobへの値伝達は隔離試験で確認する。実行時間の上限に達した場合は完了を前提にせず、ログ・カーソルと保護用保存を確認して再開する。
