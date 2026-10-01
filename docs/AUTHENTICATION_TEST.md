# Authentication Test — GPT連携

正式Acquireの手順は下記「正式Acquire申請」、新規登録は「Listing申請（新規個体の登録）」を参照。以下の先頭部分は、Claimを変更しない実験用キューの説明です。

Browser Console → **Authentication Test → 実験用キュー** holds multiple test submissions. Each addition
gets an immutable revision, even when an application ID is reused. An identical
pending/processing upload is deduplicated. Completed submissions are never overwritten.
This remains an experiment: actual Claim/Evidence/ownership records are not updated.

### Setup and storage

Submissions and the connection key are stored separately at
`YGC_DATA_DIR/direct-review/queue.sqlite3` (default `app/data/direct-review`).
Existing queue records and keys are preserved when upgrading to the GPT-only UI.
The first connection setup creates a key only if one does not already exist.
The key survives page reloads and server restarts and has no automatic expiry. **接続キーを失効** revokes it explicitly,
releases in-flight leases and preserves all submissions/results. **保存済み接続設定を
表示／接続を有効化** retrieves the same key, or creates one after revocation.
The store directory has mode 0700 and its SQLite file mode 0600; the key is stored
inside that file, not encrypted. Keep this local experimental store private.

1. Restart WebUI, reload the Console, and select three images plus expected text.
2. Click **① テスト申請を追加** for each test. Previous submissions stay in the queue.
3. Configure the generated stdio MCP command in the desktop client, substituting the
   experiment key for `PASTE_TOKEN`. Preserve existing client configuration. Do not
   paste the key into a chat. Local Codex configuration is normally
   `~/.codex/config.toml`; see the [official MCP setup](https://learn.chatgpt.com/docs/extend/mcp).
4. Reconnect/restart the desktop client to load the **new tool schemas**. Image fetch,
   failure and result submission now require `lease_token` returned by the pending
   tool. Old tool calls without this value fail safely. Refresh the scheduled task's
   saved instructions with the generated prompt, including the snapshot continuation
   through `remaining_revisions`. Existing one-item instructions process only one item per run
   if the caller honors the updated schema.
5. Keep the Mac awake and desktop app and YGC running for local scheduled execution.
   No schedule is created or modified by YGC. Check the scheduler's tool permissions:
   acquiring a job now writes queue state and is correctly marked as a write tool.
6. The Console displays pending/processing/completed/error/cancelled records and
   UTC receipt/start/completion timestamps. It refreshes every 15 seconds while the
   page is visible, when the checkbox is enabled. **③** also refreshes manually.
7. Select a row to view observations, the report and structured result. Download JSON
   or text before deleting records. Retry errors or cancel unwanted submissions.
   Only completed/error/cancelled records may be deleted (with UI confirmation).

**② ローカル接続診断** initializes MCP, lists tools and pings only. It does NOT
claim a job or fetch its images. Actual image visibility must be checked in the client.
The existing stdio bridge and local endpoint are unchanged:
`python -m ygc.direct_mcp_bridge --url http://127.0.0.1:8000/api/experiments/direct/mcp`
(use the actual WebUI port). The bridge reads `YGC_EXPERIMENT_TOKEN`, disables HTTP
redirects and proxy environment variables, and never calls an inference API.

### Queue and retry semantics

- `ygc_pending_test` atomically claims ONE oldest pending row (`BEGIN IMMEDIATE`),
  sets processing, increments attempts, and returns application ID, revision and a
  random per-attempt lease token. Empty queues return `jobs: []`, including when all
  records are currently processing. This is a mutating, non-idempotent tool.
- `ygc_test_image` requires that lease and returns actual EXIF-stripped JPEG image
  blocks. Expected text is not exposed. Source and prepared-image SHA256 hashes are
  saved along with sent dimensions.
- `ygc_submit_test_review` strictly validates the claimed ID/revision/lease and saves
  structured observations, deterministic text checks, the provisional decision,
  reason codes, human-readable report, prompt/rule versions and UTC completion time.
  `reviewer_model` is optional self-reported metadata, not attestation; unknown is null.
  The receipt contains no expected text. Identical completed submissions are safe to
  retry with the same lease; conflicting or stale submissions are rejected.
- `ygc_fail_test` records an operational error without generating a False decision.
  It stops automatic processing of that row until an operator requests retry.
- A lease lasts two hours from claim and survives server restart. Expired leases
  become pending on the next queue access, until three timed-out attempts have been
  made; then they become error. Manual retry preserves attempt history and permits
  another attempt. No heartbeat or lease extension is implemented. Late submissions
  after expiry/reassignment/cancellation/revocation are rejected.
- The first pending call omits `remaining_revisions` and snapshots current pending
  revisions. It claims one row and returns the rest as `remaining_revisions`. After
  submitting successfully, pass that exact returned list to the next pending call;
  keep updating it from responses until empty. An empty list never starts a new
  snapshot. Processing/completed/cancelled/deleted rows are skipped. New submissions
  cannot enter this continuation list. Each row is leased only when it is its turn,
  so waiting for earlier rows does not consume its two-hour lease.
- There is no three-item limit. Instructions request all initially pending items,
  sequentially, stopping on errors or runtime/usage limits. Unclaimed rows remain
  pending for a later run. Concurrent runs claim distinct rows. Snapshot continuation
  is carried by the caller (not an authenticated server-side batch); clients must not
  start another snapshot in the same run or add revisions to the returned list.
  The prompt version is `direct-queue-v3-gpt-only`.

Maximum retained storage is 100 submissions and 256 MB of encoded image payloads.
Each input image is at most 12 MB; preparation uses the existing 3000px limit and
rejects encoded images over 8 MB. There is no automatic retention deletion. Remove
unneeded terminal records in the Console when full. SQLite may retain free pages
for reuse after deletion; this is not a secure-erasure feature.

This separate SQLite store is not the main Chronicle DB. Its backup/restore must be
managed separately; do not assume the normal application DB backup includes it.
A key holder can submit observations; these are not cryptographically attested AI
outputs. Within one model chat, image context is shared despite instructions to
transcribe separately. Human review/calibration and formal Evidence integration are
still separate future work.

The local HTTP endpoint remains a minimal stateless MCP 2025-03-26 tools transport
(JSON replies, no SSE, sampling or MCP session persistence). Request bodies are
bounded to 100 KB; GET/DELETE return 405. Loopback client/Host checks, Origin checks
and bearer authentication remain mandatory. This does not provide a public/cloud
endpoint, OAuth integration, or changes to the actual Claim/ownership database.

### 判定と構成

認証テストはGPTのMCP連携のみです。OpenAI/Gemini推論API、ローカルOCR・
特徴点・CLIPSeg、Google Sheets実験のコード・画面・専用エンドポイントは削除しました。
古いブラウザー保存APIキーはConsole読込時に当該2項目だけ削除します。
サーバー環境変数のAPIキーは使用しません。既存の画像やDB、モデル保存ファイルは削除しません。

`authentication_evidence.py` が画像前処理・厳密な結果スキーマ・読取指示・文字照合、
`authentication_decision.py` が暫定採否、`direct_experiment.py` がMCPとレポート、
`direct_queue.py` が永続保存を担当します。

近接画像のSerial、両画像のChallengeが期待値と一致し、個体比較に明確な矛盾がなければTrueとします。
一致根拠の不足、uncertain、比較材料不足だけでは不採用にしません。曖昧な反射・付着物は
一致・矛盾の根拠から除外します。写真間のつながりや撮影再利用は採否条件に含めません。
文字照合は空白・ハイフン・大小文字のみ正規化し、I/1やO/0は区別します。
運用エラーはFalseとせずerrorとして記録します。一致確率は作成しません。

## 正式Acquire申請（2026-10-01）

画像審議を必要とするのは、ユーザーが現在の所有を主張する新規Acquireのみ。
Former Ownerの過去来歴、Automation Acquire、Transferは対象外。Listingの審議は別ルールで未実装。
既存Claimへ遡及して新しい画像審議を要求しない。

### 申請から反映まで

1. Product Detailの “If you are the rightful owner of this, you can claim it by providing some evidence!”
   から申請する。Current Owner本人には入口を出さず、サーバーも拒否する。
   シリアル不明はサイトポリシーとして申請不可。
2. YGCが申請者・対象個体に紐付く8文字のChallengeを発行する。提出期限は発行から24時間。
   下書きは再表示可能で、同じユーザー・個体の処理中申請およびOwner承認待ちAcquireは重複作成しない。
3. 取得日、近接写真、全体写真を提出する。両写真にChallengeを写す。
   提出済みなら審議待ちで24時間を超えても失効しない。画面には「Acquire申請中」を表示する。
   この時点ではClaimを作成しない。
4. GPTの独立文字読み取りと個体比較をYGCが照合する。審議通過時だけAcquireと日付Evidenceを作る。
   診断・画像・JSONは`acquire_applications.claim_id`で紐付く専用Evidenceとして同一トランザクションで保存する。
5. 結果反映時のCurrent OwnerがユーザーならUnverifiedで追加し、現OwnerのPositiveを待つ。
   非ユーザー／不明ならPositiveで追加する。その後の所有者、Formerly Owned、判定権限は既存Observationに従う。
   過去の取得日は既存の発生日・同日Claim ID順で扱い、画像審議で所有者を直接上書きしない。

画像審議不採用は申請履歴に残すがNegative Claimを自動作成しない。通信・閲覧失敗はerrorでありFalseではない。
取消後の再申請は新しいChallengeとrevisionを使用する。提出済み画像の上書きはできない。
審議中にTransfer等で申請者がCurrent Ownerになった場合は、Claimを作らず申請終了とする。
BAN、個体削除／Merge、シリアル変更、比較元Claimの無効化も反映前に再確認する。
結果の同一再送ではClaim・通知を二重作成せず、異なる結果や古いleaseを拒否する。

### 比較画像

- ユーザー所有：直近の有効なPositiveのAcquire／Listingを発生日・Claim ID順で選び、
  正式Acquireの全体写真、またはそのClaimの画像Evidenceを利用する。
- 非ユーザー／不明：有効な掲載由来ClaimのReverb画像を利用する。
- 提出時に比較元と画像を固定し、画像ハッシュ・送信寸法を保存する。
- 登録画像が存在しない場合だけ、個体比較条件をルール上通過させる。シリアルと両Challenge照合は必須。
  診断には「比較画像なし：ルールにより個体比較条件を通過。同一個体の確認は行っていません」と記録する。
- URLが存在するのに取得不能な場合、ファイル欠落、判読不能は画像なし扱いにしない。
  Reverb画像取得はHTTPSの`images.reverb.com`と`photos.reverb.com`のみ、リダイレクト・環境プロキシ無効、12MB上限。
  別の配信先に変わった場合は取得エラーとして運用者が確認する。

### 保存・公開範囲

正式申請はメインChronicle DBの`acquire_applications`、履歴は`acquire_application_events`に保存する。
画像はEXIF除去・最大3000pxのJPEGとしてDB内に保存し、公開media/galleryには登録しない。
通常のDBバックアップに含まれる。実験キューの削除・再初期化では消えない。
保持期限や自動削除は設けていないため、DB容量を監視する。原寸・EXIFを保持する仕組みではない。

申請中・不採用の写真と診断は申請者と管理者だけに公開する。
通過後は申請者・その時点のCurrent Owner・管理者が閲覧できる。旧Ownerには権限を残さない。
Chronicleには通常のAcquire情報だけを表示する。Evidenceの画像配信とJSONはprivate/no-store。
申請者は **My Acquire申請・審議結果** で確認・取消・エラー再開できる。
開いている申請の審議中表示は15秒ごとに更新し、結果とOwner承認待ちは通知にも記録する。
Ownerの拒否や承認放置による自動移転はしない。係争解決は別機能として未実装。

### MCPの接続と定期実行

接続先・永続接続キー・stdio bridgeは実験と共通。キーの再発行は不要。
WebUIとCodexを再起動して新しいツール定義を読み込み、Browser Consoleの
**Acquire正式申請の審議 → 正式申請一覧・定期実行の指示文を取得** に表示される指示で定期タスクを更新する。
実験用`ygc_pending_test`の指示だけでは正式申請を審議しない。

- `ygc_pending_acquire`：開始時点のpendingを列挙し、1件ずつ確保。後続呼出はremaining_revisionsを引き継ぐ。
- `ygc_acquire_image`：確保した申請の画像を取得。期待値は渡さない。
- `ygc_acquire_product_details`：提出画像だけからのMaker・Model・Finish観察を保存してから登録情報を開示。Serial・Challenge期待値は返さない。
- `ygc_submit_acquire_review`：観察を提出。YGC側で採否とClaim反映を同時に処理する。
- `ygc_fail_acquire`：未完了をerrorとして保存し、自動で不採用にしない。

比較画像なしは`reference_available=false`となり、reference取得を行わずidentity=nullで提出する。
2時間のlease、3回の時間切れ後のerror停止、手動再開を実装する。
正式審議の指示版は`acquire-evidence-v2-product-details`、採否ルール版は`acquire-acceptance-v3-product-details`。
管理者はConsoleから一覧・診断を確認し、errorを再開できる。

### 公開サーバーへの移行境界

これは正式Acquireの業務フローを既存ローカル環境へ接続した実装であり、GCP公開運用の認証実装ではない。
本人識別は既存PrototypeIdentityのまま。MCPもloopback＋共有キーの運用で、AI実行主体の暗号学的証明はない。
公開前にIdentity Platform等で本人と審議担当を検証し、画像・申請・更新API全体を認可する必要がある。
クラウドDB／オブジェクト保存、運用監視、係争解決は [GCP_BOUNDARIES.md](GCP_BOUNDARIES.md) に沿って別途進める。

### 個体比較の採否緩和（2026-10-01）

個体比較で「同一と確認できない」ことと「明確な矛盾がある」ことを分離する。
実験・正式Acquireとも、文字照合が通り、個体比較に明確な矛盾がなければ採用条件を満たす。
uncertain、支持特徴なし、比較範囲insufficient、反射などの曖昧な差だけでは不採用にしない。
contradictedまたはdifferencesがある場合は引き続き不採用。シリアル・両Challengeの未読／不一致、
不完全な結果スキーマ、画像取得失敗も従来どおり通過させない。

AIの観察は変更せず、uncertainをsupportedへ書き換えない。通過理由には
「明確な矛盾がないため条件通過。同一個体の確証は得られていません」と明示する。
これは同一性の確率や真正性の保証ではない。Owner承認・Observationの時系列規則は変更しない。
実験の採否ルール版は`evidence-acceptance-v2-no-contradiction`、現在の正式版は下記の仕様照合を加えた`acquire-acceptance-v3-product-details`。
個体比較の緩和のみではツール変更は不要だったが、以下の仕様照合追加では新ツールの読み込みが必要。
保存済みの旧判定は変更せず、WebUI再起動後に新しく受信する結果から適用する。


### Maker・Model・Finishの仕様照合（2026-10-01）

正式Acquireでは、提出時点のProduct DetailのMaker・Model・Finishを固定する。
Finishは画面と同じく最新の有効な仕様Claimを優先する。改修前から待機している申請は最初の審議確保時に固定する。
審議中に現在の表示値が変わった場合はClaimを作らず終了し、再申請を求める。

1. closeupとoverviewを独立して読み、提出画像から見えるロゴ・形状・塗装を、画像名と場所付きで記録する。
2. `ygc_acquire_product_details`へ`observations`（maker/model/finish）を送信する。登録情報の開示後にこの観察を変更できない。
3. 返された登録情報と照合し、`product_consistency`の各項目へstatus（consistent/uncertain/contradicted）とnoteを提出する。
4. YGCが採否に反映し、登録値・開示前の観察・照合結果を診断JSONと文章へ保存する。

登録済み項目との**明確な矛盾だけ**を不採用理由に追加する。確認不能・照明による色差・表記揺れ・交換部品等の曖昧な相違だけでは不採用にしない。
登録値が空の項目はサーバーがnot_registeredとし、採否を妨げない。
共通のMaker・Model・Finishは同一個体を証明せず、個体固有の一致根拠に流用しない。
比較画像なしでも提出写真による仕様照合は必要。写真自体の省略はできない。
観察や照合結果の未提出は処理エラーであり、不採用結果を作らない。

MCPは実験4件＋Acquire5件＋Listing5件の計14ツール。WebUIを再起動し、Codexで新ツール定義を読み込む。
定期タスクの指示も上記の順序へ更新する。既存の接続キーはそのまま使用する。
旧結果の書き換え・再審議はしない。Listingは下記の別ルールで審議する。

### Browser Console: Ownership Request

正式申請の一覧はAuthentication Testから独立したOwnership Request欄で確認する。
申請者・個体・シリアル・審議状態・Verificationで状況を確認し、検索／状態絞り込み、
選択した申請の画像・元診断JSON・管理履歴を表示できる。一覧は画面起動時と更新ボタンで取得する。

管理者専用操作は変更理由と、表示時の状態バージョンを必要とする。
審議・Owner操作が先に進んだ場合は変更を拒否し、更新後の再確認を求める。

- 取消：未決着の申請を停止し、実行中のGPTのleaseを失効させる。
- 再審議：Claim未作成で写真提出済みの申請をpendingへ戻す。旧診断はイベント履歴に保存する。
- 審議を採用：Acquireを作成／復帰する。現OwnerがユーザーならUnverified、それ以外はPositive。
- 審議を不採用：元のAI診断は保持する。既に作成されたAcquireはNegativeとしてObservationを再評価する。
- Verification変更：採用済みClaimのPositive／Negative／Unverifiedを管理者経路で変更する。

採否上書きは元のAI結果を改変せず、現在の申請statusとadmin_reviewを別に記録する。
審議の採用とClaimのVerificationは別々に表示する。変更理由・日時・local-console-adminを記録し、申請者へ通知する。
再採用は既存Claimを再利用し、二重作成しない。期限切れ／無効化済み申請の採用や、別申請との競合は許可しない。
DBの申請を削除する管理操作は設けない。既存の個体・Claim削除は従来の管理画面を利用する。


## Listing申請（新規個体の登録）

プロフィールのAdd Guitarは即時登録ではなく、Listing申請とChallenge発行を開始する。
Acquireと共通の申請モーダルを使い、最初からChallenge・近接写真・全体写真の欄を表示する。
個体情報と日付を入力してChallengeを発行すると、同じモーダル内で写真欄が有効になり提出できる。
Maker・既知のSerial・Listing日付は必須。Maker・Model・Finish等の入力を申請時に固定し、
24時間以内に近接と全体の2枚を提出する。審議前はIndividual・Claim・公開画像・Ownedを作らない。

審議条件は近接写真のSerial一致、両写真のChallenge一致、申請したMaker・Model・Finishとの明確な矛盾がないこと。
画像を独立して読み、仕様の画像観察を保存してから申請情報を開示する。
比較画像と個体一致判定は対象外であり、identityはnull。未読・不一致は不採用、取得失敗は処理エラーとして区別する。
採用時に個体、PositiveのListing Claim、Evidence、初期Ownerを同一トランザクションで作成する。
採用後の全体写真は代表画像として公開することを提出画面に表示する。近接・診断は従来の審議閲覧権限を適用する。
公開画像もDB内の審議画像を参照し、採用・有効・PositiveのListingに限って配信する。
将来のAcquireはそのListing Evidenceの全体写真を比較対象として取得する。

同じ正規化Maker・Serialが既存Individualにあれば、Modelの入力差に関係なく既存個体のAcquireへ案内する。
申請開始・写真提出・審議確保・採用直前に確認する。同時申請で先に登録された場合も後続を終了し、
個体を重複作成しない。候補が複数ある場合は候補IDを表示し、勝手に1件へ結び付けない。
従来の`POST /api/users/{id}/new-guitar`による審議の迂回は409で停止する。
内部のListing作成処理と外部掲載クロールは引き続き既存の経路を使用する。

- `ygc_pending_listing`：Listingキューを確保。Acquireとは別のremaining_revisionsを使う。
- `ygc_listing_image`：closeup／overviewの実画像を取得。
- `ygc_listing_product_details`：観察を保存してから申請仕様を開示。
- `ygc_submit_listing_review`：観察と仕様照合を提出。採否と個体作成はYGCが行う。
- `ygc_fail_listing`：通信・画像取得等の失敗を記録。

定期タスクはAcquireとListingの両キューを順に処理する。Ownership RequestとMy Ownership申請履歴も両種別を表示する。
管理者の理由付き取消・再審議・採否変更・Verification変更は既存の管理機構を共用する。
審議指示版`listing-evidence-v1`、ルール版`listing-acceptance-v1`。

保存先は既存acquire_applicationsを共用し、request_kindで区別、listing_payloadに申請項目を保存する。
登録前のindividual_idはNULL。従来のNOT NULL列original_individual_idは内部的に0を置き、APIではNULLとして返す。
採用時に両IDを実際に作成した個体IDへ設定する。0をIndividualとして作成・公開することはない。

### JPEGのMPF/MPO対応

JPEGの内部MPF情報によりPillowがMPOと認識する画像も、主画像（先頭画像）だけを通常JPEGに変換して受け付ける。
補助画像の選別や合成は行わず、EXIFの回転適用・メタデータ除去・12MB／20MPの制限を維持する。
GIF・WebP等のアニメーションは従来どおり拒否する。未対応形式のエラーには、実際に検出した形式名も表示する。

## 実機確認と最終検証（2026-10-01）

ユーザーによるローカル環境での確認結果：

- Acquire：画像審議通過後にClaimを作成し、現OwnerのPositive判定後に所有権が移行した。不適切な画像による申請の却下も確認した。
- Listing：Add Guitarから写真を提出し、新規ギターの登録とListingのPositiveを確認した。
- 同じMaker・Serialで再登録すると、既存ギターへの申請に案内されることを確認した。
- 拡張子が.jpgでも内部がMPOの実ファイルを主画像のJPEGへ変換でき、修正後のListing申請が完了した。

最終回帰検証は実データとは別の一時DBで実施。Pythonは313件と別実行のローカルMCP接続1件、JavaScriptは34件が通過した。
所有権・判定権限の遷移、Transferの独立性、Listingの同時重複申請、管理者上書き、画像アクセス権、取消後の古い審議結果を含む。
共通モーダル移行前のHTMLを期待していたプロフィールテスト1件を更新した。
StarletteのTestClient依存に関する非推奨警告が1種類残るが、検証失敗はない。

この確認はローカル運用を対象とする。公開サーバー向け本人認証・外部接続と係争解決は別途設計する。
コミット時は実データ、接続キー、ローカル定期タスク設定を含めない。

### main統合後の検証

mainの旧Observation整理とページ別アセット・共通オーバーレイを保持して統合した。
Acquireの比較画像はListing項目・marketplace Evidenceを優先し、旧Observationは既存データの互換読取だけに使用する。
新規Listing／Acquireは旧Observationへ二重書込しない。未登録クロール記録の保全・移行テストも継続する。
統合後はPython330件（ローカルMCP接続を含む）・JavaScript34件が通過。
一時DBの実ブラウザーでもListing登録・重複案内、Acquireの承認待ち、管理者採否変更と所有権再評価を確認した。
