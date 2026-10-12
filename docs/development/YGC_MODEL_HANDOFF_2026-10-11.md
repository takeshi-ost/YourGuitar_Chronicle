# YGC モデル切替用・最新再開ガイド

更新日: 2026-10-12（追加③完了・新着/統計/国別地図配信後）

## 最初に読むこと

この文書を最新の入口とする。詳細ログ37節と末尾の追加③結果を優先。New Discovery新着個体・統計・国別地図を③の前に追加する。Follow先活動とMessagesは延期。追加①②③は実装・実PG検証・ステージング配信・実画面確認まで完了。新着51/統計51/6か国、JS977成功、Python2585既存結果と同じbackend。ui-20261012tへ100%配信。次はユーザーの指示で元の大項目③へ。基本6ターンの修正・確認は全て完了。隔離実PostgreSQL18.6で17/17検査群、Python2535/JS960成功。Listing訂正理由の公開混入を保護しui-20261012rへ100%配信。Guitar52 Owner ID2、Transfer75 accepted/Positive、Acquire74 Positive、Case2 Round3申請者支持Resolvedを保持。Offline/元メンテナンス文/Review OFF。次工程はユーザー指示後に開始する。Git commit/push/mergeは未実施、Admin tab3/ID1 tab4の認証を保持。

## 1. 作業場所とGit

- 実作業リポジトリ: `/Users/t_oshita/Documents/Codex/2026-10-08/task-7/ygc-ui-fidelity`
- ブランチ: `fix/local-ui-fidelity`
- HEAD: `7ca7fd8`（PR #64、feat/cloud-formal-ui-shellのマージ）
- 元のローカルリポジトリ: `/Users/t_oshita/Documents/GitHub/YourGuitar_Chronicle`
- セッションの既定cwdが元リポジトリでも、実作業は上記Codex配下で行う。
- UI一致作業の多数の変更・新規ファイルが未コミット。docs/developmentの引き継ぎ資料・画像も未追跡。基本6ターンのコードはステージング配置済み。追加①②③のAPI・UIはui-20261012tへ配信済み。Git commit/push/mergeは未実施。
- 最初にgit statusとブランチを再確認。既存変更をreset/discard/checkoutで失わない。
- 実作業ディレクトリがsandbox書込許可外なら、正規の権限昇格を使う。別リポジトリへ作業を取り違えない。

## 2. 目的と合意済み範囲

公開サーバーへ移行済みの画面・機能をローカル版のUI・動作に合わせ、実ブラウザで申請・所有移転・係争を検証している。

基本6ターンのUI一致範囲は「実装済み機能」だったが、現在はNew Discovery新着個体・統計・国別地図の追加移植が許可された。Follow活動とMessagesは後回し。未移植やAPI情報不足をWeb固有の制約として扱わない。

公開情報として、Current Owner名/Profileリンク、公開Claim投稿者・本文・投票数、公開用代表画像を許可。所在地はプロフィール公開設定に従う。非公開Evidence、審議用近接画像、係争原本を公開DTOに混ぜない。

代表画像はCrawl由来ならReverb画像リンク、ユーザーListingなら審議全体画像を初期代表画像にする。

## 3. 現在のステージング運用状態

以下は直前の実確認時点。次の変更前には再確認する。

- GCP project: `your-guitar-chronicle-staging`
- region: `asia-northeast1`
- Cloud Run: `ygc-staging-accounts`
- URL: https://ygc-staging-accounts-rgmjxrs5kq-an.a.run.app
- 配信revision: `ygc-staging-accounts-ui-20261012t`、100%
- image digest: `sha256:8ff53ca575b7d1cf19405313b1eedab39c2607ad1dc2788605b7adb1c268c942`
- Cloud Build: `69b5dbff-4f17-446e-ab11-5beed054cb10`
- Artifact Registry: `asia-northeast1-docker.pkg.dev/your-guitar-chronicle-staging/ygc-staging/account-api`
- **Service Offline、Review OFFへ復元確認済み**。
- メンテナンス文: `現在メンテナンス中です。 / The service is currently offline for maintenance.`
- Cloud SQL `ygc-staging-db` はユーザー承認により稼働継続。停止しない。
- Crawl設定は今回変更していない。

過去のNormal/Review ON承認はSquierの指定検証に対する一時許可。未指定の申請をまとめて審議したり恒久Normalにしない。Review ONはワーカー実行許可であり、AIを自動起動する操作ではない。

## 4. 実データと検証到達点

### 使用個体・アカウント

- Guitar ID52: Squier / Classic Vibe '50s Telecaster / Butterscotch Blonde / ISSB25003873
- ID1: TakeshiOst（一般ユーザー）
- ID2: Your Guitar Chronicle（通常Ownerとしても、BrowserConsole管理者としても使用）
- 現在のCurrent Owner: **ID2 Your Guitar Chronicle**

### Claim履歴

| Claim | 内容 | 検証結果 |
| --- | --- | --- |
| 71 | Listing、取得日2025-04-15 | 写真審議で登録。Positive、全体写真を代表画像に使用 |
| 72 | ID1のAcquire、2026-10-11 | 審議通過後にID2が通常Positive。Owner ID1へ移行 |
| 73 | ID1→ID2 Transfer | ID2が通常Accept。Owner ID2へ移行。受取人のPositive変更禁止を確認 |
| 74 | ID1の再Acquire、2026-10-11 | 審議通過→ID2が理由付きDecline→異議申立て→双方提出→管理者原Owner支持でResolved |

Acquire74のrevision: `6495b7c44437e192587bf0b7158c91e7`。Challenge `Y65UX7LC`。これは完了済みで、新規申請に再利用しない。

### 直近の係争実確認

1. IMG_6250（近接）/IMG_6251（全体）を通常フォームから提出。
2. 当該Acquire1件に限定してReview ON。サーバー保存画像3枚（近接・全体・reference）を取得し実表示。文字完全一致、木目対応で審議通過、Claim74作成。
3. Review OFFへ復元。
4. 現OwnerのTop未回答欄から通常Decline。検証上の意図的Declineであり虚偽の断定ではないと理由に記載。
5. 申請者Profile最上部から説明・要旨・画像添付で異議申立て。Round1提出済みになりフォーム消去。
6. 現Ownerは申請者の非公開説明・未公開要旨を閲覧できない。Ownerが説明・要旨を提出し、双方提出済みでUnder review。
7. BrowserConsoleで双方の非公開説明を表示。添付ダウンロードが成功し、実画像も確認。
8. 管理者がSupport original Ownerを理由付きで確定。Resolved、Current Owner ID2。申請者側Refreshでも裁定表示を確認。
9. Offlineと元メンテナンス文、Review OFFを確認して終了。

説明・要旨・裁定理由はすべて動作検証であり、実取引や法的紛争、虚偽申請を主張しない文章を使用。実画像審議も期待値を知る同一チャットのフロー検証で、独立した認識精度評価ではない。

## 5. 次の作業候補（優先順）

### A. 係争中Product DetailのUI差分（26節で修正・配信済み、以下は修正前の記録）

- 当事者用Under dispute表示と詳細への導線がない。
- Ownershipメニューが選択可能に見える。
- `CLOUD_OWNERSHIP_DISPUTES.md` にauthenticated hint未移植として記録済み。公開DTOへ係争有無を混ぜず、認証済み参加者向けに状態を取得して表示・無効化する。
- サーバー側所有権ロックは既存実装で維持されている設計。今回UIからロックを破る更新は試していないので、実環境での拒否確認と混同しない。
- 通常の非所有投稿まで一律停止しない。係争仕様に従いOwnership/Listing/Identity Correctionなどの所有変更を対象にする。

### B. 初期取得・再表示（26〜27節で修正・配信済み）

- 初回一覧のidentity競合修正済み。Admin実サーバー一覧/deep-link読取成功。open filterの0件は解決済みCase2を除外する正常な表示。
- Profile/Consoleの初期読み取りを全体busyから分離。取得済み部分から操作可能。合成Profileと実Console確認済み。通常ProfileはOffline制限により実API待ち時間の確認が残る。
- 既存の同時リクエスト上限2、session/actor/epochガードを安易に解除しない。

### C. 残る検証

- 追加証拠ラウンド、要旨の管理者公開、申請者支持の裁定、解決後Claimロックの実操作は今回未確認。
- Transfer受諾後の集計更新修正は回帰テスト済みだが、修正配信後にもう一度Transferを作って再確認したわけではない。
- 最終差分レビュー、必要な回帰検証、ドキュメント整理、ユーザー指示に応じたcommit/push/merge。

## 6. 守るべき仕様

変更前にAGENTS.mdと `docs/architecture/CLAIM_CENTERED_ARCHITECTURE.md` の「所有権と判定権限の相互作用（設計上の不変条件）」および遷移例を読む。

- Current Ownerによる他者Claim判定、自己Claim判定禁止、Acquire前後のOwner、Transfer後の権限移動は組合せで検証。
- 同日ClaimはID順。将来日時禁止。UTC保存・ユーザーローカル表示。
- 画像審議通過と現OwnerのAcceptは別。ユーザー所有Acquireは審議通過だけでOwnerを変えない。
- 過去AcquireでFormerly Ownedにしかならないものは係争対象外。旧Claim72を今回係争へ転用しない。
- 係争中はOwner維持。非公開証拠は本人と管理者のみ。相手へは管理者が確認した要旨だけ。
- 各Round各当事者1回提出。全員提出済みがUnder review。管理者裁定は提出状況にかかわらず可能。
- 解決後は新所有操作を再開するが対象Claimの通常変更はロック。Claim作者は変更しない（昔の会話案より現仕様を優先）。
- 管理者強制判定と通常Owner判定を別経路として扱う。

## 7. 主要ファイル・資料

- 詳細作業ログ: `docs/development/YGC_CODEX_HANDOFF_2026-10-11.md`（22〜25節）
- UI差分・検証台帳: `docs/development/FORMAL_UI_FIDELITY.md`（Unit21〜24）
- 係争仕様: `docs/features/OWNERSHIP_DISPUTES.md`
- Cloud境界: `docs/migration/CLOUD_OWNERSHIP_DISPUTES.md`
- 原本保存: `docs/migration/CLOUD_DISPUTE_STORAGE_ROLLOUT.md`
- 審議接続: `docs/migration/CLOUD_OWNERSHIP_REVIEW.md`
- UI: `app/src/ygc/static/cloud-public-catalog.js`、`cloud-account-disputes.js`、`cloud-account-page.js`、`cloud-ui-profile.js`、`cloud-ui.js`
- Owner UI: `cloud-owner-acquire-inbox.js`、`cloud-account-guitars.js`、`cloud-account-ownership.js`
- 審議bridge: `app/src/ygc/cloud_review_bridge.py`
- 記録画像: `docs/development/fidelity-evidence/ygc-dispute-resolved-applicant.png`、`ygc-dispute-under-review.png`等。

## 8. 直近のコード修正・検証

- Cloud RunのTLS終端に対応するHTTPS scheme補正（Cloud Run専用経路のみ）。通知の厳密Origin検証を維持し、実サーバーの通知既読POST 200を確認。
- Current OwnerのAcquire未回答一覧を追加。Declineの必須理由はブラウザ内フォーム→Review/Applyに統一。
- 所有関連操作後にProfile集計・ヘッダー・Chronicleも再取得。session変更・離脱後の更新を防止。
- accepted applicationをpreview再利用対象から外して、新Acquireに新Challengeを発行。
- 直近修正に関連するJS185件/Python104件、隔離PostgreSQLプロフィール・所有移転テスト成功。さらに前の通知/inbox修正ではPython303件/JS945件成功。
- 上記は各変更時点の検証で、現在差分全件を一括再実行済みという意味ではない。直近係争実確認ターンはコード変更なし。

## 9. 実行環境・再開手順

- Python: `/Users/t_oshita/Documents/GitHub/YourGuitar_Chronicle/app/.venv/bin/python`
- Node: `/Users/t_oshita/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node`
- gcloud: `/opt/homebrew/bin/gcloud`
- ブラウザ操作はcua_replの文書を読み、現在のtab一覧・アカウントを確認してから進める。古いハンドル・ログイン状態を仮定しない。
- 前回のIAB ID2、tab7がID2管理者/Owner、tab8がID1申請者。現時点でも同じとは限らない。
- 幅441pxではProduct Detailがメイン欄を覆う。背後のボタンを無理に押さず、Close Product Detailで閉じる。
- 一時helperは `/private/tmp/ygc_dispute_review.py` と `/private/tmp/ygc-dispute-52/` にあるが永続手順ではない。lease等を含み得るため内容を公開・Git追加しない。完了済み審議を再送しない。
- Review bridgeの既存SA: `ygc-staging-review@your-guitar-chronicle-staging.iam.gserviceaccount.com`。既存接続を使い、新しい鍵やIAM権限を作らない。

推奨開始: 実作業repoのgit status確認 → 本書と詳細25節 → 不変条件 → 係争Product Detailの認証済み表示設計/実装・回帰検証。実サーバーの書込み検証を再開する際は対象とモードを限定し、終了時にOffline/Review OFFへ戻す。


## 直近の進行状態

基本6ターンで①②を順番に確認する合意。ターン1は途中で、ID1サインイン待ち。公開TopのPC1440/スマホ390、検索/履歴、公開カタログページ送りと既存Owner ID2のProfile/Settings/通知導線は確認済み。一般memberとしての実確認とMembers確認は未完了。Offline/元メンテナンス文/Review OFFへ復元済み。認証済みAdmin tab3とID1サインイン用Profile tab4を保持。コード変更・再配信なし、ui-20261011o。ターン1完了前にターン2へ進まない。詳細は28節。


## ターン1の完了結果（29節を優先）

ユーザーがID1にサインインし、一般memberのProfile/Settings/Top/Members/通知をPC1440・スマホ390で実確認。検索/会員詳細/履歴/再読込/通知Case2導線成功。コード修正・再配信なし、ui-20261011o。Offline/元文面/Review OFF復元済み。一般member tab4とAdmin tab3保持、viewport解除。初期HTMLの検索入力上書きと通知取得途中件数0はターン2の読み込み状態確認対象。ターン1完了を報告し、ユーザー確認後にターン2へ進む。


## ターン2の完了結果（30節を優先）

ターン2完了。初期検索入力喪失と未取得件数0表示を修正しui-20261011pへ配信。JS270/Python17成功。係争中/通信失敗/再取得/logout/identity切替は合成IAB、persisted BFCacheはVM回帰で検証。実ID1の初期—→取得件数、検索、通知取得成功を確認。Offline/元文面/Review OFF復元。実係争状態・所有権変更なし。Admin3/ID1のtab4認証保持。ユーザー完了確認後にターン3へ。


## ターン3の完了結果（31節を優先）

実Case2再開Round2双方提出→Admin追加証拠要求→Round3双方再提出→Admin双方の説明閲覧/要旨編集公開を完了。証拠6/7公開済み、双方参加者画面で相手説明/元要旨不在を確認。JS82成功、コード/配信変更なしui-20261011p。Offline/元文面/Review OFF復元済み。Case2 Round3 Under review、Owner ID2、Acquire74 Negativeを維持。Admin tab3/ID1 tab4認証保持。次はユーザー指示でターン4の申請者支持と所有権・Claim制限の実確認。


## ターン4の完了結果（32節を優先）

Case2 Round3を実Admin UIで申請者支持→Resolved、Acquire74 Positive/Current Owner ID1。双方Profile ID1 Owned1/Formerly0、ID2 Owned0/Formerly1。新Owner Transfer/Release再開・検索を確認し未送信。旧Owner新Acquire警告は中止。通常Admin変更がDB保護で503になっていたため事前チェックと409専用エラー表示を追加。Python181/JS58成功、ui-20261011qへ配信し実操作409とPositive/Owner1維持を確認。編集/削除拒否と通常判定権限の組合せは回帰テスト、直接実HTTP送信なし。Offline/元文面/Review OFF確認、SQL/Crawl維持。次はターン5Transfer。


## ターン5完了・最新開始条件（2026-10-12）

Transfer75 ID1→ID2 accepted/Positive、受領00:07:20 JST。Guitar52 Current Owner ID2。ID1 Owned0/Formerly1/Claims4/Chronicle7、ID2 Owned1/Formerly0/Claims3/Chronicle6、個体Claims/公開Chronicle5。Case2 Round3 Resolved/Applicant supportedとAcquire74 Positiveを保持し、後続Transferで再開不可。判定権限の表示とOwnershipフォームの新旧切替を実確認、追加操作はCancel/Back。アプリ修正・配信なし、ui-20261011q。Offline/元メンテナンス文/Review OFF復元済み。次はユーザー指示後のターン6。詳細はログ33節。

## ターン6完了・最新状態（2026-10-12）

詳細ログ34節。隔離Cloud Build PG18.6全17群成功、個体絞込み・裁定後409・係争容量/競合・権限/分類を含む。公開用本文/名前とPRIVATEを旧fixturesで分離し件数/presentationへ追随。Listing訂正理由のみ公開presentationから除外、本人用履歴維持。Python2535/JS960成功。PG Build631c8b33-4596-4f10-9fa3-139909942dd5、配信Buildabb97d3b-6fe3-4a33-bbf6-1ee821eec18f、ui-20261012r100%。Offline/元文面/Review OFF、Owner2/Transfer75/Acquire74/Case2維持。ローカルinitdb/Chromium制限を無断回避せず、新たな使い捨てCI環境でPGを検証した。6ターン完了、次工程待ち。


## 35. 追加実装①完了（New Discovery・統計・国別地図のAPI、2026-10-12）

- ユーザーは大項目③の前にNew Discovery・統計・地図の追加実装を希望。確認回答は「まず新着個体・統計・国別地図のみ（Follow先の活動は後回し）」。Messagesも延期。既存①②の基本6ターン完了を取り消すものではなく、追加範囲。
- 追加① API・集計 → 追加② 画面接続 → 追加③ 隔離実PostgreSQL・ステージング配信/実画面確認の3ターン。各完了後に次のユーザー指示を待つ。今回は追加①だけ。元の大項目③はまだ開始しない。
- cloud_catalog_insights.pyを追加しCloudPublicCatalogの既存_read/public_readガードを再利用。GET /api/public/guitars/discoveries、/statistics、/world-mapを専用DTOで追加。認証提示時のGuest降格禁止、全query拒否、private/no-store、汎用エラー、GET専用を保持。
- New Discoveryはローカル版の全体新着部分を移植。公開カタログのactive/normal作者・許可Claim種別/判定状態の個体を、最新Claim作成/対応掲載Evidence取得日時で並べ、1個体1行・最大200件。Follow活動を混ぜない。写真/private Evidence/自由記述/Owner情報を新着DTOに追加しない。
- 統計は同じ可視個体のモデル上位10＋Other、正規化単一年の分布、UTC本日を含む30日間の公開Listing Claim作成件数。Circa/C.haを除去し、4桁のみ年式集計。年範囲/年代/Unknownは除外。数値は既存クラウド形式と同じdecimal string。
- 地図は国別件数のみ。登録OwnerありはChronicleの古い所在地を使わず、Accounts正本の有効/normalアカウントのresidence_visibility=Public国を集計。Members/Followers/PrivateはAdmin含め除外。登録Ownerなしは個体Snapshotの国のみ。個人名/Owner ID/個体ID/地域/座標を返さない。実所在地や所有権は変更しない。
- 新規Python50件、既存public catalogと合わせ159件、Python全体2585件成功（既存警告3）。SQL出力artifactチェック、py_compile、git diff --check成功。SQLの本物の実行確認は追加③で行う。postgres_public_catalog_checks.pyに新着の可視集合/国公開設定変更/全モード/GET専用の実PGチェックを追加したが、現時点では未実行。UI・JSは今回変更していない。
- ステージングに今回のAPIは未配信。既存ui-20261012r、Offline/元メンテナンス文/Review OFFは今回変更なし。ライブDB/CloudSQL/Jobs/IAM/所有権/Claimに書込みなし。commit/push/mergeなし。
- 成果物 outputs/catalog-addition-1-results.txt。次はユーザーの指示で追加②（正式TopのNew Discovery、統計グラフ、国別地図、日英・PC/狭幅・エラー/再読込/サインアウト表示破棄）。外部地図データや描画依存を利用する場合は仕様/ライセンスと安全なアセット配信を確認する。


## 36. 追加実装②完了（正式Top画面への接続、2026-10-12）

- 正式/uiのNew Discoveryを新着APIへ接続。個体リンクは既存詳細表示/検索状態/履歴へ接続し、修飾クリックも保持。Follow先活動とMessagesは追加していない。
- 統計をnative SVGのモデル円グラフ・年式棒グラフ・UTC直近30日掲載数折線へ接続。各グラフに件数表を付け、英日切替・整数軸・空状態に対応。
- 国別地図はNatural Earth v5.1.2のpublic-domain 110mデータを固定タグから取得し177国のパスをローカルJSへ前処理。実行時外部取得なし。国名別名を集約し、地図にない小国も件数表に残す。日本17/米国11/シンガポール2の合成データで確認。個人の座標等は表示しない。出典 https://www.naturalearthdata.com/about/terms-of-use/ 、元GeoJSON SHA256 6866c877d39cba9c357620878839b336d569f8c662d3cfab4cb1dbe2d39c977f。
- アセットはcloud_account_pageの専用許可リスト/no-storeで配信。DTO検証/textContent、安全なリンク、AbortController/revisionによる古い応答排除、サインアウト/identity変更/Offline/認証拒否時の表示破棄を実装。単独項目の通信失敗は正常な他項目を保持し更新で再試行。401/403では全追加表示を破棄しGuest自動再試行なし。
- hashの節移動で不要な認証再初期化を行っていた既存popstateを修正。同じ正規化routeのhash履歴では再読込せず、実route変更は従来通り認証を再確認。
- Python全体2585成功（既存警告3）、最終JS全体975成功/失敗0/取消0。関連Python67成功、関連JS52成功は全体と重複。最初のdeferredテスト停止は制限状態syncの戻りPromiseを修正し解消、後続成功のみを結果に採用。
- IABのloopback合成fixtureで1440/390/320幅、英日、空状態、統計単独エラー、更新による回復、サインイン/サインアウト、New Discovery→Fixture30詳細、地図/件数表キーボード操作を確認。スマホ横はみ出しなし。実データ/実PG/ステージング確認ではない。証跡はoutputs/catalog-addition-2-statistics-pc.png、catalog-addition-2-map-pc.png、catalog-addition-2-statistics-mobile-ja.png。ローカルfixtureは終了時停止。
- ステージング未配信、ui-20261012r/Offline/元メンテナンス文/Review OFF保持。Cloud Build・Cloud SQL・ライブ所有権/Claimへの操作なし。Git commit/push/mergeなし。
- 追加②完了。次はユーザー指示で追加③（隔離実PGに追加集計チェック、ステージング配信、実画面/認証/モード/国公開設定確認）。元の大項目③は未開始。


## 37. 追加実装③完了（隔離実PG・ステージング配信・実画面、2026-10-12）

- 追加①②に続き、ユーザーの「追加③に進み、追加作業を完了」指示で実施。Follow先活動とMessagesは延期のまま。元の大項目③は自動開始しない。
- 既存の使い捨てCloud Build PostgreSQL18.6経路を使用。検査コンテナはPGコンテナの127.0.0.1を共有し、架空データ/UUID付きDB・roleを使用。Cloud SQLの破壊的回帰ではない。終了時trap/finallyでコンテナ/DB/roleを回収。ローカルinitdb/shmget・headless Chromiumの制限回避なし。
- PG Build80105434-6207-4284-abce-352724ef60fe SUCCESS、postgres_public_catalog_checks 1/1群、失敗0。追加新着/モデル合計/正規化年式/UTC30日/国別専用DTO、可視個体集合、Public国集計、Members/Followers/Privateに変更した際のAdmin含む非表示、全サービスモード、query拒否、GET専用を実PG・FastAPIで実行。最終配信の全PythonソースがPG検査パッケージと一致。
- 最初の画像ビルド梱包で既存背景/ロゴ8点の不足を配信前照合で検出。画像を含む227ファイル/3.9MiBに修正。a3b3dee0-1789-40fe-b70f-635f7e329668の成果物は配信していない。7c7efedc-961f-4248-8d15-dac2354609d2 SUCCESSでui-20261012sへ配信し実画面確認。
- 実データの390pxで末尾年式/日付ラベルの近接と凡例行間を検出。SVGは末尾との間隔が1目盛未満のラベルを省略し、凡例行間21へ調整。件数表の全データは保持。末尾間隔とcanonical Admin Only復元の2回帰追加、JS全体977成功/失敗0/取消0、関連新規16成功（全体と重複）。Python全体2585成功は追加②時点と同じPythonソースに対する既存結果。今回は実PG検証、JS全体を実行し、Python全体を重複再実行していない。
- 最終Build69b5dbff-4f17-446e-ab11-5beed054cb10 SUCCESS。digest sha256:8ff53ca575b7d1cf19405313b1eedab39c2607ad1dc2788605b7adb1c268c942、revision ygc-staging-accounts-ui-20261012tへ100%。image-only update、env/service account/scaling等を変更前specと比較し保持。ready200、追加3assets/正式UI/catalog JS/背景のソース一致とno-store確認。
- ステージングNormalとRead onlyの匿名3 APIが200/no-store。新着51個体、統計対象51、モデル合計51、30日Listing作成件数51。年式範囲/Unknownは仕様通り除外。地図US42/JP3/GB2/AU1/CO1/NL1、国判明計50。Guitar52は非公開/国不明で除外され得るため総個体数51との一致は要求しない。
- IAB既存ID1で新着51/3統計/177地図パス、New Discovery→Guitar52の正式詳細とCurrent Owner Your Guitar Chronicle、国別件数表、英日・1440/390幅、横はみ出しなしを実確認。最終tで末尾1978と日付ラベルの重なり解消、PC/スマホ画像保存。空状態/通信エラー/サインアウト・セッション遅延は追加②合成UI/回帰の検証を引き継ぎ、ライブで意図的な破壊/ログアウトはしていない。
- 確定したAdmin OnlyでID2管理者は新着51/統計3/地図177を表示、ID1会員は追加表示0と制限メッセージ、匿名3 APIは403/no-store。モード保存と読み込みの途中で見えた0/旧modeを最終結果と誤認せず、public service statusと完了表示で再確認。管理者の表示消去不具合は再現せず、取得中の状態だった。権限の変更・認証のGuest降格なし。
- 終了時Offline/元メンテナンス文/Review OFFをConsole保存結果と公開service statusで復元確認。最終tの匿名3 API403/no-store、会員画面も新着/統計/地図を破棄。SQL/Crawl/Jobs/IAM/所有権/Claim/プロフィール所在地には変更なし。Guitar52 Owner ID2、Transfer75/Acquire74/Case2のワークフローに書込みなし。Git commit/push/mergeなし。既存tab3/4はhandoff保持、viewport解除。
- 成果物 outputs/catalog-addition-3-results.txt、catalog-addition-3-discovery-pc.png、catalog-addition-3-statistics-pc.png、catalog-addition-3-map-pc.png、catalog-addition-3-statistics-mobile-ja.png。追加①②③の新着個体・統計・国別地図は実装/配信/確認まで完了。次はユーザー指示後に元の大項目③へ。


## 最新パフォーマンス作業・第1段階（2026-10-12）

第1段階の重複取得/通常GET強制JWT更新削減と初期認証フォーム非表示を配信/実確認。JS984/配信Python2成功、backend不変。実makerソート6→3 catalog requests、個体選択list0、更新中51行/同じDetail維持。全体速度改善完了ではなく、初期Favoriteが共有2通信枠を使いsortページ間待ちが残る。次は第2段階通信優先順位/ページ共有state/不要panel取得、第3段階DB/SQL/静的配信実測。詳細はCODEX handoff38とoutputs/performance-stage1-results.txt。revision ui-20261012u100%、Build a3546819、digest88b27c69。Offline/今回開始時の日本語message/Review OFF復元、前回messageを上書きしない。所有権/Claim/SQL/IAM/env等変更なし、Git未commit。元の大項目③/Follow活動/Messages未開始。


## 最新パフォーマンス通信整理checkpoint（2026-10-12）

CODEX handoff39を優先。最終ui-20261012w100%、Build5e59d914、digest a1958bdd。JS995/配信Python2成功、backend不変。共有2枠内で背景1、操作/認証/変更/list/Detail優先、同時GETだけ共有（完了cacheなし）、Profile二重restore/Hub初期refresh削減、Top Back一覧保持+fresh Detail、BFCache login非表示。w選択16→Back52でlist/me0、Profileme/settings/summary各1（avatar/notifications各2残る）。実測には2.5秒の速い回と17.6秒のAPI遅延回、最終w4.9秒があり安定改善完了ではない。元Stage2のcross-page cache/全page遷移は残り、次はN+1/逐次page/静的assets/共有state/backend接続・認可・SQL。Offline/current日本語message/Review OFF復元、所有権/Claim/SQL/IAM/env等不変、Git未commit、tab3/4handoff/viewport解除。元大項目③/Follow/Messages未開始。成果物performance-stage2-results.txtと測定JSON/画像。


Latest performance checkpoint: handoff40. ui-20261012x100%; private row Favorite snapshot shares existing personal paginated list only while in-flight, no completed cache. Live52→2 initial favorite GETs and no sort repeat; 51 enabled hearts, PC/390 checked. JS1005/delivery Python2 passed. Offline/current Japanese message/Review OFF restored. Full-page navigation/shared state/serial catalog pages/backend remain. Do not declare all Stage2 complete.


## パフォーマンス段階②完了・最新状態（2026-10-12）

CODEX handoff41を優先。最終ui-20261012ab100%、Build13068119、digest b8ce90fa。公開DTOは認可・modeと内容を毎回再検証後304、staticは内容ETag再利用。private/HTML/config/写真/errorはno-store。独自private persistent cache/SPA化は採用せずMPAを維持。残りpage2単位/順序完全性、Profile avatar・通知各1/visibility初期0、Top/Profile rowFavorite集約、auth pending中フォーム・旧private非表示を実装。Top→Profile publicDetail/Chronicle304、static48件304、51heart/分類0・1・4/戻る進む/390幅確認。Python2597・最終JS1020・FormalPython4、隔離PG publicCatalog1/1成功。Offline/current日本語message/ReviewOFF復元、cachedETag403と公開表示消去確認。運用mode以外のDB/権限/Claim/所有/Profile/Favorite書込なし、未commit/push/merge、tab3/4handoff/viewport解除。取得・再利用の段階②完了。全HTML遷移/DOM再構築/API約0.5秒と実通信の連続待ちは残る。次は性能段階③backend接続/token認可/SQL/配信待ちの測定改善。全速度改善完了とは扱わない。元クローズドテスト大項目③/Follow/Messages未開始。成果物performance-stage2-complete-results.txtと検証JSON/画像。


## 42. パフォーマンス段階③・DB接続と静的配信の改善完了（2026-10-12）

- HTTP lifespan限定DB pool、request別Server-Timing/JSON計測、SHA256版付きstatic immutable配信を実装。raw query/path/token/SQL/個人情報を計測logに含めない。HTML/private API/config/photo/error no-store、公開DTO毎回認可・計算後ETag/304、legacy static no-cacheを維持。版付きは起動時bytes固定・生成i18n/ownershipをhashに含む。既存route allowlist以外公開しない。
- pool各DB max4/min0、nestedはidle leaseを非blocking取得、満杯なら旧方式の独立connectionでwait cycle回避。fallbackはpool上限外。commit/rollback・DISCARD ALL/session isolation/prepared無効化、切断時write replayなし、lifespan close。CLI/migrationはfresh。SQL定義/index/migration/schema・Ownership/Claim判定不変。Google check_revoked=Trueは各API継続、認可result/cacheなし。
- 同条件匿名GET7回（warmup2除外）中央値app183.70→121.58ms約34%、DB114.66→69.05ms、client267.66→196.16ms。会員各6件app539.60→427.59ms約21%、DB159.55→77.18ms、identity274.18→275.41ms。小標本staging比較で全pageの速度/安定改善率は保証しない。countは非blocking取得試行も含む。
- 最終Python全体2604passed/既存warning3、JS1020passed/0failed。全体後の追加module graphはtarget7passed（全体2605再実行とは扱わない）。最終source隔離PG18/18群(Build6bc5ac61-bf40-4586-ba83-f2e23997d164)、別DB飽和追加1/1群(Build814d3e89-9b36-4a0e-b561-af9c70f52011)成功。取引分離/並列write/rollback/reset/切断lease/closeを確認。live DB破壊なし。
- ad Normal実ID1一覧51/新着51/地図177/Detail52・6entries・Nut Bone、ProfileOwned0/Former1/Claims4/通知17。me/settings/summary/avatar/notifications各1/visibility0。Top→Profile 00:28:54–00:29:47Z static12GET（初見専用JS/CSS10件200、placeholder2件304）、Top取得済み共有JS/CSS GET0。後続no-iconの304は残り、static全部0としない。Back直後認証待ち/フォーム非表示、復元後同会員、Forward Top51。今回sort入力はbrowser dispatch timeoutで成功扱いなし、昇順URLを検証、UIsort/390幅は不変で段階②証拠継承。初回Profile復元中session_changed一時文言を観察、後続me200/本人表示正常。文言改善は残課題、原因・修正済みと断定しない。
- revision ygc-staging-accounts-ui-20261012ad100%、Build653ba6b8-3acd-4eba-9b5f-db5b99819fa8 SUCCESS、digest sha256:236c5b454827829ee3d90d75f13dbb44354f67df000b3d229bcc99f7c30eb5f9。229許可files/4.0MiB、production byte一致、ready200、template image/revision/clientmetadata以外一致。env/SA/scaling/IAM保持。
- Offline/元日本語message「サービスはメンテナンスのため一時的に停止しています。しばらくしてから再度お試しください。」/Review OFF復元。Console入力後保存clickが制御timeout、復元だけ既存app SA/DB secret reference/最終imageの一時jobを使用、canonical Admin ID2有効確認・version fence・既存set_mode監査event維持。ygc-staging-perf3-mode-restore execution rl6fj成功、job削除済み、既存jobs不変/secret本文読出なし。公開status/6API cached validator403/no-store/noETag、会員データ破棄とConsoleOffline確認。viewport解除/tab3/4handoff、未commit/push/merge。
- outputs/performance-stage3-complete-results.txt、measurements.json、baseline/final匿名・server JSON、top-profile requests、pc/profile/offline画像。段階③backend/配信完了。MPA document/DOM再構築、Google失効照合とSQL計算、初期復元文言は残る。全待ち時間解消/SPA化は未実装。元クローズドテスト③/Follow/Messages未開始。


## 43. ユーザー別表示データの連続操作共有完了（2026-10-12）

- ユーザー承認で同じタブ/同じcanonicalユーザーの短期display cacheを追加。identity-platform-auth内のsessionStorage+memory、origin/SDKuid/tenant/canonical app_user_id/role/statusで分離。Cookie/localStorage private保存追加なし。各documentでfresh /me後のみ利用、canonical identity/token/権限/Claim/所有権/申請はcacheしない。
- 設定30秒、summary15秒、通知/完全Favorite collection10秒。明示opt-inのみ、64entry/512KiB/各JSON64KiB。通常fresh/force/signal/customheaderはreuseなし。partial Favorite不保存。各cachehitでfresh service status（同時inflightのみ共有）、Offline破棄403、AdminOnly通常認可API、ReadOnly通知can_write=false。mutation開始/終了・logout・identity・拒否・Refreshで破棄、旧応答再publish防止。pagehideは完了済み有効cache保持/遅延publish拒否。初期SDK復元session_changed誤表示とservice停止の認証誤文言を修正。
- JS1044passed/0failed、servedUI/runtime Python22passed/既存warning1、diffcheck成功。別ユーザー/logout/TTL/書込競合/失敗/403/service/Storage/ReadOnly/不完全Favorite/初期SDK/BFCacheを合成テスト。backend/SQL不変、今回fullPython/PG再実行とはしない。
- af実ID1の短いProfile→Top→Profileで各me1/settings0/summary0（service確認保持）。これら2APIのみ0、全通信0やページ時間改善率ではない。ah実画面51行/TakeshiOst/通知17/ProfileOwned0Former1Claims4/Detail52NutBone。明示NewDiscovery Refreshでme/settings/summary各1をRun log確認。私有業務更新、実別account/logout/positiveFavoriteは未実行（合成で検証）。
- 最終ai100%、Build7b875e9c-a14e-42ee-a045-a2fcc798e7e0 SUCCESS、digest sha256:51ac7a4d9d6d3b7a195638c6452270920f34aaffa340719b81a315a71221d86f、229許可files/4.0MiB。template image/revision/clientmetadata以外一致、配信10JS versionedasset置換後一致、ready200。最終aiはahからNewDiscovery等の停止文言1箇所のみ変更。ae/ag未配信。
- Offline/元日本語「サービスはメンテナンスのため一時的に停止しています。しばらくしてから再度お試しください。」/Review OFF復元。ai画面旧会員/一覧/新着/統計/地図破棄、制限表示、SignIn hidden。viewport解除/tab3/4handoff、SQL/Crawl/既存Jobs/IAM/env/SA/Claim所有権業務更新なし、未commit/push/merge。
- currentchat outputs/user-data-sharing-results.txt、live-counts.json、refresh-counts.json、final-server.json、deployment.json、profile-final.png/offline-final.png。MPA document/DOM構築/fresh認証、avatar/Owned一覧/Claim/申請state取得は残る。元クローズドテスト③/Follow活動/Messages未開始。以前の「private persistentcacheなし」はこのユーザー承認のtab-scoped短期display保存で限定置換、権限やcanonical保存を許す変更ではない。


### 43追記：ユーザー自身の速度確認（2026-10-12）

ユーザー「実行速度を確認しても良いですか？」に対応し、Consoleで一時Normalへ切替。公開service/status normal、ID1 Top51行/aria-busy false確認。Review OFF保持、元メンテナンスmessage保持、業務データ変更なし。現在Normalのままユーザー確認待ち。確認終了後Offlineへ戻す。tab3/4handoff、viewport overrideなし。outputs/speed-check-normal.png。


## 44. 代表画像の先行表示・Claim判定更新の表示保持（2026-10-12）

- ユーザー速度確認後「代表画像がReverbより遅い、Posi/Nega切替で一覧再読込/表示崩れ」に対応。画像はfresh Detail DTO+service check後に先行表示、Chronicle/全list待ちを除去。Chronicle到着時に画像DOMを再構築せず、route AbortSignalと既存identity/photoEpochで旧応答破棄。画像no-store・サーバー公開/actor認可保持、private画像cache/GCS公開URL/認証省略なし。
- Top/Profile判定後はfresh Detail/Chronicleを表示保持して更新、同じtable projection（5項目+Claimcount）なら一覧GET0/同一DOM、変化時はfilter/sort/count反映のため全list再取得。不要な/me再復元を抑止しserver read/write認可保持、insightsは完了後fresh。Owner分類更新は維持。Consoleは判定のfresh Detail/Chronicle中に旧表示を保ち、一覧4項目変化時のみlist更新、Verificationで変化しないAdmin media_assetsは再取得しない。認可拒否/停止時は従来通り破棄。
- JS1054passed/0failed（10追加）、関連Python214passed/既存warning1、diffcheck成功。photo先行/旧応答、same list DOM/get0、Snapshot/Claimcount変更時のfreshlist、401/403/503消去、Console拒否を合成で確認。backend/SQL不変、今回fullPG/Python再実行とはしない。AGENTS所有権不変条件/遷移表を確認、Ownershipや判定ルールを変更しない。
- AJ実ID1 Normalでphoto1536px/51行/Chronicle6/TakeshiOst。1440/390overflowなし、Maker昇順待機中51行/Detail維持、完了image src同一/追加photoGET0。Run log photo03:27:02.445Z/0.736s、最後listpage3開始03:27:03.220Z/0.437sでphoto先行完了。Guest単独0.325sは条件が異なるため速度比較に使わない。実業務Posi/Nega変更なし、該当発生画面の補足未受領、Top/Profile・Console両経路の処理を修正したが特定実Claimの再現済みとはしない。
- AJ100%、Build1349d202-d3b1-4cfb-bf1d-c664245d5b49 SUCCESS、digest sha256:c16d6ea9b3f46049310cbecdbd256057d7315f3abf12a764bded8290e3f8770d、229許可files/4.0MiB、5変更JS配信期待一致（versionedasset置換後）、ready200/template image/revision/clientmetadata以外一致。既存Jobs/Crawl/IAM/env/SA/業務データ変更なし、未commit/push/merge。
- 現在Normal/Review OFF。ユーザー速度確認の続きとしてNormalを保持、確認終了後にOffline/元日本語案内へ戻す（このターンのOffline復元は未実施）。viewport解除/tab3/4handoff。outputs/photo-claim-results.txt、deployment.json、requests.json/public-requests.json、events.json、detail-pc.png/detail-mobile.png。画像API自体の認証/DB/GCS時間、MPAは残る。クローズドテスト③/Follow活動/Messages未開始。


## Checkpoint 45 — Claim Negative / compact Favorite layout (2026-10-12)

- User report: Negative ◉ offset and transient “Changes…” text in Favorite column after Verification operations.
- `#detail .claim-compact-row` now uses the same full-width/no-inline-margin center as Positive cards. Claim rules, ownership, permissions and write endpoints unchanged.
- Compact Favorite separates unrelated operation `busy` from write restriction. Heart remains disabled while busy and retains the known value; initial reads still finish during another operation.
- Compact notices remain an accessible live status/description and button tooltip, outside layout flow. Retry uses an accessible ↻ icon; heart/retry area remains 36px.
- Final JS suite: 1057 passed; related Python UI/Favorites suite: 134 passed, one existing Starlette deprecation warning. Fake public-catalog DOM updated to support classList.add.
- Real browser synthetic fixture (no live writes): Positive/Negative/Positive centers all 220px (390px viewport:195px); Favorite column 57.5546875px unchanged through normal/busy/restricted/uncertain failure/recovery; no overflow.
- Staging deployment: build 6fb24ec1-de25-4411-9ff7-659c8038804f SUCCESS; revision ygc-staging-accounts-ui-20261012al; 100% traffic; digest sha256:06bf37d1fa75562bf2bd349e160ef42f4009c2fa112681a5b6d18c991160919b. Superseded AK build was never deployed.
- /ready ok; mode normal. Template comparison: image/revision/client metadata only; env, SA, scaling and security settings unchanged. Review remains OFF.
- Live member Top/Profile read-only checks: updated versioned CSS; compact Favorite cells 36px at narrow width / 43.15625px at PC width (inner control fixed at 36px); no long in-flow notices or page overflow. No live Claim/Favorite/ownership write was made for testing. User can retest Negative transition after reloading.
- Evidence: current chat outputs/claim-favorite-layout-fixture.png, claim-favorite-layout-measurements.json, claim-favorite-layout-staging.png. Original closed-test item ③ remains pending.
