# YGC Web UI ローカル版再現作業・Codex引き継ぎ

> **最新再開ガイド:** [YGC_MODEL_HANDOFF_2026-10-11.md](YGC_MODEL_HANDOFF_2026-10-11.md)。冒頭の運用・未deploy記述は初期時点の記録です。現在状態は最新ガイドと末尾25節を優先してください。

更新：2026-10-11 16:43 JST

## 1. 作業目的

Your Guitar Chronicle（YGC）のWeb版について、既に移行した画面・機能を、ローカル版（オフライン版）の表示と動作に細部まで合わせる。

ユーザーの指示：
「実装箇所の多くがローカル版と表示や動作が異なっています。ローカル版の状態を細部まで再現し、WEB版固有の問題でそれが難しい箇所は報告してください」

単なる未実装、APIの情報不足、公開範囲の設計差を「Web固有の技術的制約」と混同しないこと。

## 2. 作業場所

- リポジトリ：takeshi-ost/YourGuitar_Chronicle
- 作業ディレクトリ：`/Users/t_oshita/Documents/Codex/2026-10-08/task-7/ygc-ui-fidelity`
- 作業ブランチ：`fix/local-ui-fidelity`
- 今回の変更は保存済み・未コミット・未push・未deploy
- 元のローカルリポジトリ：`/Users/t_oshita/Documents/GitHub/YourGuitar_Chronicle`

最初に現在のブランチと `git status` を確認すること。既存の未コミット変更を保全し、reset・checkoutによる破棄・作り直しをしないこと。

### 最初に読む資料

- `docs/development/FORMAL_UI_FIDELITY.md`
  - 比較基準、差分、修正内容、検証記録
- `docs/development/FIDELITY_PAUSE.md`
  - 10月8日の一時停止時点の再開メモ。以後の修正があるため、最新状態は前者と実ファイルを優先
- リポジトリの `AGENTS.md`、関連する開発・テスト手順

## 3. 比較基準とデプロイ状態

10月8日の確認では、元リポジトリの `6e2d901` にあるローカル版Top/ProfileのHTML・JS・CSSと共通ProductDetailは、当時のmain `7ca7fd8` の対応ファイルと一致していた。

このローカル版を基準として、Web版独自のフォーム・DOM・CSSによる差を解消している。作業再開時に、ユーザーがその後変更した箇所がないかは確認すること。

最後に確認したWeb反映済み状態：

- main：`7ca7fd87fc3612c473d2ad7e6ad6eb3c47761854`（PR #64）
- GCPプロジェクト：`your-guitar-chronicle-staging`
- リージョン：`asia-northeast1`
- Cloud Runサービス：`ygc-staging-accounts`
- リビジョン：`ygc-staging-accounts-00042-ctx`
- URL：https://ygc-staging-accounts-rgmjxrs5kq-an.a.run.app/ui
- アプリ動作モード：Offline v15、Review OFF、Crawl OFF

上記は最後に確認した値であり、現在値の再検証ではない。
今回のUI修正はWebに反映されていない。

## 4. 修正・保存済みの内容

以下は作業担当の完了報告に基づく。細部と対象ファイルは差分・検証記録で確認すること。

### 共通表示・一覧

- Web独自のProductDetailを共通コンポーネントに寄せた
- 画像枠・代替画像、三角アコーディオン、狭幅時の詳細を閉じる操作を調整
- 検索、列ソート、選択維持、一覧の列構成と寸法を調整
- 旧 `/account` 系CSSによる上書きを除去
- 一覧内に追加されていた管理操作の配置を整理
- ヘッダーの余白・SignOut・通知再描画を修正

### プロフィール・Settings

- 名前・所在地・Bioの構成、Owned／Formerly Owned／Favorite一覧を調整
- Favorite同期、一覧の全件読み込みを修正
- Chronicleのページ単位で並び順が途切れる問題を修正
- 初期選択をSignature Guitar優先、なければOwned → Formerly Owned → Favoriteの順に調整
- Settingsを独立ページ化
- 本人限定の保存、テーマの試着・Cancel・保存後の再表示、Signature選択等を実装・検証

### Claim・申請・所有権操作

- Claim入力フォーム・モーダルをローカル版と共用する方向へ修正
- 申請のKeep・再読み込み・取消の確認表示を共用
- 未保存Challengeを本人限定で扱い、Keep時に申請を作成する処理を実装
- Transfer／Release入力欄・文言を調整
- 読み込み中に作られた所有権操作ボタンが無効のまま残る不具合を修正
- Owner Verificationの選択欄とClaim編集入口を各Claim内へ統合
- 認可・写真確認・競合防止は維持

### Follow

- 一覧の寸法・文言・件数表示を調整
- 既存仕様を維持：会員は他会員のFollowing／Followers人数・一覧を閲覧できる
- 会員検索は表示名検索
- 検索／一覧は表示名とアイコン。クリックは相手ユーザーページへの移動のみ
- フォローボタンは相手ユーザーページに配置
- アイコンなどの公開範囲判定を維持すること

## 5. 検証済み範囲

各検証は実施時点のコードに対する結果。後続編集を含めて全件が再通過したという意味ではない。

- 10月8日の途中段階：Python 2,446件、JS 916件、自動ブラウザ1440／390／320pxが通過
- Claim 4フォーム、Transfer／Release、Followダイアログ：3幅の比較で寸法・文言一致の報告あり
- 所有権処理：隔離PostgreSQLで競合・参加者限定・過去日付等を検証
- 10月11日：ヘッダー対象箇所のPC／390／320px比較、申請6ケースの比較を確認
- 最新のVerification／Claim編集修正：対象JS 196件、認可7件、画像管理37件、ブラウザ操作確認が通過。PC／390px比較も実施

通常Chrome拡張による最終確認と実ファイルアップロード確認は未完了。

## 6. 未完了・判断が必要な項目

### A. 公開APIの情報不足による表示差

作業担当の調査では、現行の公開APIは以下を返していない。

- 所有者名・所在地
- Claim投稿者・本文・投票数
- 代表写真

会員APIも表示名・許可されたアイコン・Follow関係などに限定されている。

これはWebで表示不可能という意味ではなく、現在の公開データ設計との差。非公開Evidence等から情報を流用して公開しないこと。必要な項目・対象ユーザー・公開範囲を整理し、変更前にユーザーに確認する。

### B. 編集導線の扱い

最新報告では「ローカル正本にも未実装の編集導線」が別判断事項として残っている。具体的な対象は `FORMAL_UI_FIDELITY.md` と実装差分を確認すること。

既に修正したClaim内の編集入口と、この未実装項目を混同しない。ローカル版に存在しない機能を、再現作業の名目で勝手に追加しない。

### C. 最終表示・実操作確認

- 通常Chromeでの最終表示確認
- 実ファイルアップロード確認
- 既知の公開データ差を除いた、全体の残差の確認

主要修正は進んでいるが、全体の忠実再現完了とはまだ宣言していない。

### 今回追加移行を求められていない機能

User Chronicleの横断表示、New Discovery、統計、地図等の未移行はユーザー了承済み。今回の再現作業に便乗して範囲を広げない。

## 7. 消費を抑える方針【重要】

ユーザーは前回のクレジット消費が速すぎ、テストの項目・回数・複雑性が過大だったと指摘している。

- 原則1担当で進める。並列作業や独立レビューを安易に追加しない
- 既存の保存済み成果・検証記録を再利用する
- 変更箇所に絞ったテストをまとめて実施する
- 影響のない通過済みテストを繰り返さない
- 全件テスト・多画面幅の総当たりは、必要な仕上げ時にまとめる
- 失敗後の再検証は、修正が影響する範囲に絞る
- 検証用の仕組み自体を過剰に作り込まない
- 認可・公開範囲・データ破損防止など重大な検証は省略しない
- 作業中は長い無報告を避け、意味のある進捗・阻害要因・完了を短く報告する

## 8. 操作・環境上の制約

- Cloud SQLはユーザーが停止中。ローカル修正に不要なので停止維持と案内済み
- Cloud SQLを勝手に起動しない。Web接続確認が必要になった時点で相談する
- push・PR作成・merge・deploy・実DB変更・公開モード変更は、この作業では未承認
- 現在のWeb設定をOfflineから変更しない
- ユーザーの未コミット変更や元リポジトリを破壊しない
- OSの画面・ロック・電源・ネットワーク・権限設定を勝手に変更しない

### ブラウザ／アップロードの注意

以前、Browser Useで `http://127.0.0.1:8764/ui/profile?claim=1` へのアップロード承認が繰り返し表示され、ユーザーが拒否した。

- 同じアップロードを再試行・別経路で迂回しない
- 実アップロードが必要なら、ファイル・送信先・目的を明示して改めて相談する
- Pythonのローカルネットワーク許可も以前拒否されている。設定を変更しない
- Computer Useの接続問題は先送り済み。再調査を勝手に始めない
- 通常Chrome拡張が使えない場合も、繰り返し再接続に時間を使わない
- Macの画面オフと作業停止を同一視しない。コード修正とヘッドレス検証は進行できた実績がある

## 9. 次に行うこと

1. 作業ブランチ・未コミット差分・最新の検証記録を確認する
2. 修正済み部分を作り直さず、残差と判断事項を短く整理する
3. 公開範囲の拡大や新機能追加なしで直せる差だけをまとめて修正する
4. 変更箇所の対象テストと必要最小限の最終表示確認を行う
5. 「修正済み」「確認済み」「未確認」「設計判断待ち」を区別して報告する
6. Web反映を行う場合は、別途ユーザーの承認を得る

直近の実装ターンは完了しており、この申し送り作成時点で新しい開発処理は開始していない。

## 10. Codex引継ぎ後の追記（2026-10-11）

- 引継ぎ先の保存済み変更を保全して作業を再開。
- 会員ヘッダーで追加情報取得開始時に表示済みの名前・件数欄を消してしまう処理順を修正。
- Avatar取得中のユーザー切替後、古い通知件数が新ユーザーの状態へ混入しないよう応答の有効性を再確認。
- `test_cloud_account_hub.cjs`を追加し、既存通知テストと合計91件成功。全体テスト・ブラウザ再接続・アップロードは繰り返していない。
- 通常Chromeの全体比較、実アップロード、公開データ差、Messages／Former Ownerの判断待ちは引き続き残る。Top通知がProfileへ遷移する差も残る。
- 変更は引き続き未コミット・未Push・未デプロイ。Cloud SQLとOffline設定は変更していない。

## 11. ステージング反映（2026-10-11、ユーザー承認済み）

- 今回のユーザー依頼で保存済み変更をCloud Runへデプロイ。上記の「未デプロイ」「Cloud SQL停止維持」はこの時点で更新。Gitの未コミット・未Push状態は維持。
- Cloud SQL起動と確認後の稼働継続は明示承認済み。`ygc-staging-db`はactivationPolicy=ALWAYS、起動操作完了。
- Cloud Build: `a525ca1b-5702-4247-985c-5351ce968895`（SUCCESS）。アップロード対象220ファイルを確認し、DB・画像保管領域・認証情報を除外。
- 配信リビジョン: `ygc-staging-accounts-ui-20261011b`、トラフィック100%。
- イメージdigest: `sha256:aeb1389fd0b4af09afdeb15b0f63641ef767d6e41e10808b45d36b3a3f3d3e96`。
- Cloud Runはイメージのみ更新。maxScale=3など既存構成を維持。DB起動完了前の2回のデプロイは接続チェックで失敗し、起動操作完了後に同じイメージで成功。
- `/health`・`/ready`はHTTP 200。未認証の管理APIは401。`/api/service/status`はoffline。Review/Crawl設定は変更していない。
- デプロイ前検証: JavaScript 919件、Python関連218件成功。
- Codex内ブラウザで新版Top Page、Offline案内、Sign Inモーダルを目視確認。コンソールエラーなし。会員専用画面はユーザーログイン待ち。
- 元のGitHub作業ディレクトリの変更や、実データ作成・画像アップロード・公開モード変更は行っていない。

### ログイン後のブラウザ確認

- ユーザーによるサインイン後、Topのアカウント名・画像表示とUser Profileへの遷移を確認。
- Offlineのためuser_readも遮断され、Profileの件数は未取得、Settingsはアクセス制限表示。これは`PostgresOperations._access`の現行仕様と一致。認証成功と会員データの取得成功は別。
- Top / Profile / Settingsで観測したブラウザJavaScriptエラーなし。実データ入りの配置・件数・編集フォームは未検証。
- 表示検証のための一時Read-only化（確認後Offlineへ復帰）をユーザーに提案し承認待ち。サービスモードは未変更。

### 一時Read-onlyでの実画面確認（2026-10-11）

- ユーザー承認後、管理者がサインインしたCodex内ブラウザのConsoleから一時Read-onlyへ変更。
- Topの実データ50件表示、Product DetailのSpecificationと公開Listing Chronicleを確認。ProfileでOwned 0 / Formerly Owned 0 / Claims 2と通知0の取得を確認。
- 商品代表画像・公開Owner/Locationの不足や、User Chronicle未接続は既知の残差として表示にも残る。
- SettingsはRead-onlyでも制限表示のためフォーム未確認。通常モードでの編集・保存・申請・アップロードは未実施。閲覧確認中のJavaScriptエラーは観測なし。
- 確認後にOfflineへ戻し、元の案内文「現在メンテナンス中です。 / The service is currently offline for maintenance.」も復元。公開status APIで両方確認済み。Review OFFを確認、Review/Crawl設定は未変更。
- Cloud SQLはユーザー指定どおり稼働継続。

## 12. 公開表示・初回認証・通知・履歴の補完（2026-10-11）

### 今回の承認と変更

- ゲスト向けCurrent Owner表示名/Profileリンク、公開Claimの投稿者・本文・投票数、明示的な公開代表画像の表示はユーザー承認済み。所在地はPublicのみ公開DTOへ含め、Members/Followers/PrivateはこのAPIで返さない。会員ディレクトリ自体の匿名公開は追加していない。
- SettingsとTop Catalogで、初回SDK復元通知をユーザー切替と誤認する初期化順序を修正。以後のアカウント切替は従来通り応答破棄・表示クリア。
- Top通知を同じページのモーダルへ変更。通知先は既存Profile側の認可付き処理を利用。
- User Chronicleは本人の参加/プロフィール更新/Claim/投票・応答/ギター登録履歴（最新100件）へ接続。
- 代表画像は、明示選択されていて有効なPositive Listing/Media Claimへ紐づくJPEGのみ。非公開Evidence・審議画像・legacy保存パスから代用しない。
- 実画面で一覧50件のFavorite同時取得に503を検出。最大3件ずつに制限し、ユーザー切替時は待機中の旧ユーザー要求を破棄。

### 最終反映

- Cloud Build `f962cc95-7bc2-42d2-a626-8d4a4a0ab934` SUCCESS。221ファイルのソースのみ。DB・アップロード画像・秘密情報はビルド対象外。
- 最終配信 `ygc-staging-accounts-ui-20261011d`、100%。digest `sha256:86c0b3b5d1e4cf320e27f3e740c55094be98702863c2a469479f110074f42770`。
- 一つ前の`ui-20261011c`も表示検証済みだが、Top初回認証修正・Favorite並列制御はdで反映。
- Python関連126件、最終JS関連128件成功。`git diff --check`成功。実PostgreSQL fixture全体、実画像アップロード、保存・申請送信は行っていない。

### Admin Onlyでのブラウザ確認（ユーザー明示承認済み）

- Settings全入力欄の初期読込と現在値、User Profileの件数、User Chronicle4件を確認。
- Listingフォームの写真2欄・Challenge生成導線を表示確認。生成/Submit/Keepは押していない。
- Acquire #51フォームの写真2欄・Challenge表示・Not savedを確認しCancelで終了。フォーム表示用の期限付きpreview handleは発行されるが、申請は作成/送信していない。
- Topで50件の一覧、非ユーザーCurrent Owner名、Listingの仕様と公開投票数を確認。Media #68のコンパクトポップアップで投稿者Profileリンクを確認。
- Top通知がProfileへ遷移せずモーダルで開き、0件/No notificationsを表示。既読化・他の通知操作なし。
- 既存Media #67/#68はUnverifiedのため代表画像としては使用されずプレースホルダー。Positiveの公開画像が実際にあるレコードでの配信目視確認は未実施。legacy/Reverb画像移行はこの変更に含めない。
- API取得を含む実データ表示には待ち時間がある。Profileの既存初期取得は直列が多く、表示高速化は今後の候補。
- 未移植のNew Discovery/統計/地図、Messages、Former Owner導線の扱い、実書込み/実アップロード、通常Chromeでの全体比較は引き続き別途。UI全体の完全一致・サービスイン完了は宣言しない。
- Gitは未コミット・未Pushのまま。元のGitHub checkoutには変更していない。
- 最終dリビジョンの新規Top遷移で、手動Refreshなしに50件表示。Favorite50件全ての取得完了（disabled 0、取得失敗0）を確認し、dのHTTP 5xxログも確認時点で0。修正前cではFavoritesの503を10件観測していた。
- `/health`と`/ready`は200。観測したブラウザJavaScriptエラーなし。

- 確認終了後、Offlineと元の案内文「現在メンテナンス中です。 / The service is currently offline for maintenance.」への復元を公開status APIで確認済み。Review OFF、Auto Crawl unchecked。Cloud SQLは承認どおり稼働継続。
- 表示記録: `fidelity-evidence/staging-settings-20261011.jpg`、`staging-notifications-20261011.jpg`。申請・Claim・所有権・プロフィール保存・画像アップロードは行っていない。

## 13. 代表画像の実配信確認前の調査（2026-10-11）

- 次の①代表画像実表示確認を開始したが、クラウド版には`representative_media_asset_id`を明示設定する公開指定UI/APIが未接続と判明。前節の公開配信は、選択済みの適格画像が存在する場合の読取り側まで。
- `ReviewRepository.create_initial_listing_claim`は審議写真の一般Media化を抑止するため生成Mediaを取り除く。審議通過だけで公開代表画像が用意されるとは考えない。管理者Media uploadも代表画像指定は行わない。
- 新設したインメモリSQLiteの実SQL/配信サービス結合テストで、選択済みPositive Mediaの正しいオブジェクト世代だけを読むこと、未選択/他個体/不正形式/非Positive/無効Claim/BAN/リンク欠損/旧保存パス/モード制限ではStorageを読まないことを確認。判定取消後の再取得でも拒否。`test_cloud_public_presentation.py`25件成功（今回17件追加）。GCS・実PostgreSQLでの成功配信を確認したという意味ではない。
- 公開指定をまずBrowserConsoleの管理者操作で追加するか、Current Owner操作も含めるかをユーザーへ質問。申請実テストの対象・新しいChallenge付き写真準備についても質問中。回答前に既存画像を公開したり既存ClaimをPositiveへ変更したりしない。
- このターンのAdmin Only設定保存直後の画面遷移では変更は反映されず、公開status APIで元のOffline・メンテナンス文を確認。デプロイや申請作成/送信/画像アップロード/所有権変更はなし。Cloud SQL稼働継続、Review/Crawlは変更なし。


## 14. 初期代表画像ルールの訂正と反映（2026-10-11）

ユーザー指定により、前節の管理者用公開指定UIの提案は保留し、初期代表画像を以下へ訂正した。前節の「審議画像は一律非公開」「Listingは別途公開指定が必要」という説明を上書きする。

- Crawl由来はReverb画像リンク。公開Listing / source-account Automation Acquireの画像情報を参照し、HTTPSのReverb画像CDN（images.reverb.com / photos.reverb.com / rvb-img.reverb.com）のみ許可する。
- ユーザーListingは採用済み申請に紐づくoverview。関連Listingが有効・Positive、投稿者がnormalの場合だけ公開用photo endpointで返す。保存オブジェクト参照は外部へ返さない。
- closeup・審議レポート・Acquire申請写真は公開対象外。明示選択済みの適格な代表画像があれば優先。既存採用済みListingにも読取り時に適用し、DB移行やClaim判定変更は不要。
- Listingフォームの全体画像公開に関する既存案内を復元した。
- Python関連148件、JS関連90件成功。git diff --check成功。実画像の新規アップロードや申請送信は行っていない。
- Build db9b718a-5e3c-4176-a755-2962f9c5a84d SUCCESS。配信リビジョン ygc-staging-accounts-ui-20261011e、100%。digest sha256:5b2e0e606c1ff1386b595b113a972eca7fd4c6d9965b54d9104627cd36075b85。
- Admin Onlyで商品#2のReverb画像が800×800で読み込まれることを確認。ユーザーListingの実ストレージ画像配信は未目視（SQL/配信サービスのテストで検証）。
- ブラウザ確認中、Favorite取得失敗が再発。今回の初期画像修正とは分けた未解決課題。狭い画面で商品名が極端に折り返される表示も残る。UI全面完了とは扱わない。
- 前節のモード保存不成立という判断は確定ではない。同一URLのstatus取得で古い応答を観測したため、以後は一意のcheck queryとno-cacheで確認する。
- コミット・Push・Mergeは未実施。従来の作業中差分を保持。

- 終了時にOfflineと元のメンテナンス文へ復元し、一意query付きstatusで確認済み。Review OFFを画面確認、Crawl設定は変更なし。Cloud SQLは承認通り稼働継続。表示記録: `fidelity-evidence/staging-initial-photo-20261011.jpg`。


## 15. Favorite取得失敗・商品名の折返し修正（2026-10-11）

- Cloud SQLログでFavorite/settingsの503と同時刻の接続枠枯渇を確認。一覧3並列だけでは他の画面部品の取得を抑制できなかった。
- Identity Platformアダプターにページ共通の認証付きAPI上限2を追加。待機要求は送信直前にアカウント変更とAbortSignalを再確認。通信失敗でも枠を解放。自動再試行・DB設定変更・認可変更はなし。これはページ単位の制限であり、複数端末・ユーザーの総接続容量は別途負荷検証が必要。
- Favoriteの操作/失敗メッセージをProduct Detailタイトルの横から下へ分離。狭い画面でも商品名が数pxへ圧縮されない。
- 関連JS166件成功。Build 7f646c14-b759-4158-897f-bb97c4d412d2 SUCCESS。配信ui-20261011fに100%。digest sha256:78bf32000d9913c7e5cff91b0e9f97ea475a0467c3e469ddfe06a7a400bca5f3。

- 実ブラウザで一覧50件のFavorite取得完了、disabled 0・失敗表示0、詳細Favorite正常を確認。狭いパネルの商品名は幅262pxで3行に収まり、縦1文字状態を解消。新リビジョンのHTTP5xxログは確認時点0。表示記録: `fidelity-evidence/staging-favorite-layout-fixed-20261011.jpg`。
- 確認終了後はOffline・元のメンテナンス文へ復元。Review OFF・Crawl設定変更なし、Cloud SQLは稼働継続。申請/保存/所有権変更/画像アップロード、Git commit/push/mergeは未実施。


## 16. 申請フローの提出前確認（2026-10-11）

- 既存cloud_review_bridgeのygc_review_connection_check成功: google_oidc / queues_connected=true / data_changed=false。キュー取得・画像取得・結果提出は行っていない。本チャットにygcツールの直接定義はなく、接続診断だけ既存CLIブリッジで実施。
- Review OFFを維持。Admin OnlyでListingフォームの仕様・日付・Generate Challenge・写真2欄・公開全体画像の案内を確認。空欄のままCancel。実ギター情報と新しいChallenge付き写真の準備をユーザーに依頼中。
- Top Product Detail #51のAcquireクリックでモーダルが開き、Serial・Challenge・期限・Not saved・取得日・写真2欄を確認。Cancelで終了。Submit/Keepは未実行、Claim/所有権は変更なし。写真提出以降と実審議は未検証。
- /ui/profile?acquire=51への直接遷移ではモーダルは自動表示されない（formal側intent欄非表示）。Topの実際のonAcquire経路は動作する。直接URL/サインイン後の意図引継ぎは今後の改善候補。
- 関連Python132件、JS120件成功。これは実PostgreSQLの端から端までの審議検証ではない。新しいコード変更やデプロイなし。
- 商品#51でClaim actionの取得失敗表示も観測。今回のフォームは開くが、取得失敗の原因は未特定で残課題。審議接続成功と全UI経路成功を混同しない。
- 表示記録: fidelity-evidence/staging-listing-form-20261011.jpg、staging-acquire-form-20261011.jpg。
- 終了時はOffline・元のメンテナンス文へ復元確認済み。Review OFF、Crawl変更なし。Cloud SQL稼働継続。


## 17. 実Listing撮影待ち下書き（2026-10-11）

ユーザー提供情報で初めて実下書きをKeep Requestした（前節までの未保存確認とは異なる）。Makerはユーザー確認でSquireからSquierへ訂正。Model Classic Vibe '50s Telecaster / Finish Butterscotch Blonde / Serial ISSB25003873 / 取得日2025-04-15 / 年式空欄。

- 申請revision: 29ba7342a2c915adb4fbfef1225e9840。ログイン中のYour Guitar ChronicleアカウントのListing draft。
- Challenge: WREBEXJF、写真提出期限2026-10-12 19:57:48 JST。保存後Detailを再度開いて同じコード・期限を確認。
- 写真未提出、Review OFF、個体・Claim・所有権の作成/変更なし。ユーザーが新しいコード付き近接・全体写真を準備する段階。期限切れ時は古いコードを再使用しない。
- 表示記録: fidelity-evidence/staging-squier-challenge-20261011.jpg。

## 18. 実Listingの写真提出・回復検証（2026-10-11、登録確認完了）

- ユーザーからIMG_6246.jpg（closeup）、IMG_6247.jpg（overview）を受領。overviewの800万画素超過に対して、元を保持した長辺2048pxコピー作成を明示承認。対象Listing 1件のみReviewを一時ONにして審議・登録し、完了後OFFへ戻すことも承認済み。
- エージェントのsips縮小操作が黒一色JPEGを生成した。目視せず提出したことが原因。サーバー取得時に発見し、採否は提出せずygc_fail_listingでerrorにした。Claim未作成。元画像は正常。Pillowで作り直したコピーは目視確認済み。これは利用者の写真不備ではない。
- 期限内のエラーListingだけ、本人がReplace photosでdraftに戻せる回復経路を追加。Challenge・期限・申請情報は維持、両写真を再提出必須、古い審議結果・leaseは失効。採否決定済み、進行中、Acquire、他人の申請は対象外。通常の認証・モード制限を維持し、所有権判定は変更しない。
- 回復API/公開画像関連Python90件、既存関連JS120件と追加JS2件成功。ビルド/登録確認結果は以下に追記する。

- Build da26fb5f-3dc6-4e53-a61c-78a1b2428c6c SUCCESS、ui-20261011gへ100%配信。digest sha256:728545cc3979d69001bde0361ebc087a0b14822bfd859cb97b6aadf611d9dc20。
- ブラウザでReplace photos→確認→同じChallenge/期限のAwaiting photos→両写真再提出→Awaiting reviewを確認。既存review bridgeから対象revisionだけを取得し、サーバー保存の近接・全体画像を別々に目視。両画像は正常。
- 近接Serial ISSB25003873、両Challenge WREBEXJF。Maker/Modelは画像のみでブランド・シリーズ確定できずuncertain、Finish consistent、identity=nullで提出。サーバーは2026-10-11T11:15:53Zにaccepted、Guitar ID52 / Claim ID71 / positiveを返した。管理画面で同じ状態・採否True・photo recoveryと再審議履歴を確認。Admin強制採用は未使用。
- これはユーザー提供仕様を既に知る同一チャットによる実フロー検証であり、期待値を知らない独立セッションでの認識精度検証ではない。後者は別途実施する。
- 審議完了直後にReview OFFへ戻し画面確認済み。他申請を審議しなかった。ブラウザのOwned/代表画像確認とOffline復元は下に追記する。

- User ProfileのOwned Guitarsが1件、Current OwnerがYour Guitar Chronicle、Listing公開カードが2025-04-15で表示。代表画像はアップロードoverviewを1536×2048のblobとして正常読込、ブラウザ画素も確認。表示記録: fidelity-evidence/staging-listing-registered-20261011.jpg。
- 終了時にOffline・元のメンテナンス文へ復元し、一意query付き/api/service/statusで保存確認。Review OFF、Crawl設定変更なし。Cloud SQLは承認通り稼働継続。今回作成したGuitar52・Positive Listing71は保持。Git commit/push/mergeは未実施。


## 19. 実装済みUI差分の追加監査（2026-10-11）

- ユーザー回答によりNew Discovery・統計・地図・Messagesの新規移植は対象外。今回の変更と検証範囲はFORMAL_UI_FIDELITY.md Unit20参照。
- 一覧Claim件数、OwnershipのOwner別導線と警告、Profile query intent、Topの未回答/係争パネル、係争共通モーダル、代表画像拡大、Favorite/Claim footer/検索欄配置を修正。
- 関連Python358件、JS934件成功。架空データのブラウザーで警告と未保存フォームの遷移・390px横はみ出しなしを確認。実申請・裁定・所有権変更なし。
- ステージングのブラウザログイン状態が失われていたため、ユーザーへ再サインイン依頼。Offline・Review OFF・Crawl OFFは変更していない。Cloud SQL稼働継続。
- ビルド中。初回の出力先誤記ビルド33235af0は中止。最終検索文字サイズを含まない59b35a21も未配信のまま中止を要求。最終ビルドc24910df-e854-4d99-a0f9-ceca91714842。完了結果は後追記。

- Build c24910df-e854-4d99-a0f9-ceca91714842 SUCCESS、ui-20261011hへ100%配信。digest sha256:37dd3d9305824440fc8d709a1822d19f825aeadd49ee77fd815821916effe250。
- 利用制限後の再開でユーザーの認証済みタブからAdmin Onlyへ変更。Owned Guitar52のClaim件数1、所有者向けOwnership→Transfer/Release、通知モーダルを実画面確認。保存・申請・所有権変更は行わない。Profile初期表示は複数APIの直列読込で待ち時間がある。
- 実画像拡大で共通アルバムと追加モーダルが二重表示される問題を発見。独自拡大処理とCSSを削除し既存YGCImageAlbumへ統一。関連JS36件成功。最終Build 58bb741e-098e-45b8-8f44-f42a6ff2339dの結果は後追記。

- 最終Build 58bb741e-098e-45b8-8f44-f42a6ff2339d SUCCESS。ui-20261011iへ100%配信。digest sha256:36c40bcb4dbbb458106994882b511784742c2a587b29f24de406245040d2ea50。

- 最終配信版のTop Guitar52で代表画像クリック→dialog数1、拡大正常を確認。記録: fidelity-evidence/staging-photo-album-20261011.png。Owned/Profileの記録: staging-ui-owned-20261011.png。

- 終了時はOffline・元のメンテナンス文へ復元し、固有queryの公開statusと管理画面で確認済み。Review OFF維持、Crawl変更なし、Cloud SQL稼働継続。実申請・Claim/所有権変更なし。今回のGit commit/push/mergeなし。架空fixture停止・一時タブ削除・viewport解除済み。
- 次回候補: Profileの直列初期化とページ内アンカー遷移時の再取得による待ち時間の改善。実際の係争案件を作成した画面検証、全スタイル全画面の完全一致は今回の確認範囲外。

## 20. Profileの初期読込改善（2026-10-11）

- Unit21参照。主要Profile/Owned/Formerly/Favoriteを優先して取得、通知・申請履歴等を後続段階で並行取得。送信上限2を維持。account/session変更時は後続処理を開始しない。
- 見出しリンクは全体再取得せずスクロールだけ。未取得のリスト件数は「—」、成功した空結果のみ0件。
- JS938件成功。Build dad00357-a892-49f2-be44-40a65dfbd031 SUCCESS、ui-20261011jへ100%配信。digest sha256:ff3407d2c8fc3d5f05e2481ccf8cebf22e50c68be258a480bbb4deff4eecceed。

- Admin Onlyで実画面検証。後続処理中でもProfile/Owned1件が先に表示、Chronicleは未取得「—」→6 items。Owned/Formerlyの見出し移動後もSignOutがenabledでOwnedデータを保持し、従来の全体再取得・disabled化なし。処理時間の厳密な比較計測はしていない。記録: fidelity-evidence/staging-profile-loading-20261011.png。

- 終了時Offline・元のメンテナンス文へ復元し公開statusで確認。Review OFF、Crawl変更なし。Cloud SQL稼働継続。新規申請/Claim/所有権の変更なし。Git commit/push/merge未実施。

## 21. TakeshiOstによるSquier Acquireテスト下書き（2026-10-11）

- 対象Guitar52、申請者TakeshiOst（ID1）、現Owner Your Guitar Chronicle（ID2）、取得日2026-10-11をユーザー承認。検証中Normal、終了時Offline復元も明示承認済み。
- TakeshiOst本人サインイン後、Top Add Claim > Ownershipの警告をConfirmしKeep Request。管理画面でDraft/Claimなしを確認。申請revision 2d86a4f1fd152021d74af64b4633ca60、Challenge R4MHJPA5、写真期限2026-10-12 21:00:28 JST。写真未提出、Review OFF、所有権未変更。
- Topで保存後のDetailが開かず、再読込後に申請欄が表示されない挙動を観測。管理画面には下書きが残っている。重複作成はせず、次回写真提出前に申請者側の再表示経路を確認・修正する。
- 写真待ちのためOffline・元の案内文へ復元。管理者タブ7と申請者タブ8を保持。

- 写真IMG_6248(closeup) / IMG_6249(overview)を受領。両方2268×3024のJPEGで800万画素以下。申請一覧のclearとrefresh開始時に現在アカウントを同期する修正を追加。初回ログインでrenderが進行中の取得を無効化する競合を防止し、古いアカウント結果を排除する既存ガードを維持。回帰を含むJS941件成功、git diff --check成功。Build ebad0212-2f0a-4c37-95d0-88c88dd68cd8 SUCCESS、digest sha256:2c15e75242b2d783ec1a68504e6d5a6753a5afc5c72d9bcf0d204d470f476b11。配信/実写真提出の結果は後追記。

- ui-20261011kへ100%配信。再読込後に保存済みDraftが表示され、Detailのキーボード操作で同一revision/Challengeのフォームを開けた。写真原本2枚を提出しAwaiting reviewを確認。
- ユーザーがこのAcquire1件のみのReview ONを承認。既存審議ブリッジでremaining_revisionsを当該revisionだけに限定し、保存済みcloseup/overview/referenceを取得して表示確認。文字読取:近接ISSB25003873、両Challenge R4MHJPA5。木目対応2点でidentity supported、Maker/Model uncertain、Finish consistent。ygc_submit_acquire_reviewがaccepted/claim_id72を返した。Admin強制承認なし。Review OFFへ復元確認済み。
- 今回も事前情報を知る同一チャットでの実フロー確認であり、独立した認識精度検証ではない。現Ownerの回答・所有権移転はまだ実施していない。

- 再表示後もクリックが効かないように見えた原因は、幅441pxのブラウザでProduct Detailが申請行のボタンを覆っていたため。Product Detailを閉じた後はDetailの通常クリックで開くことを確認。これは初期アカウント読込競合とは別。申請者画面でAwaiting owner approval / Claim #72: Unverified / 採用理由を確認。Owned0件、Current OwnerはYour Guitar Chronicleのまま。記録:fidelity-evidence/staging-acquire-accepted-20261011.png。

- 終了時Offline・元のメンテナンス文へ復元し、管理画面でOffline/Review OFFを確認。Cloud SQL稼働継続、Crawl変更なし。次は現Ownerの通常回答→所有権/判定権限移動の実画面確認。Git commit/push/merge未実施。

## 22. Acquire通常承認による所有移行の実確認（2026-10-11）

- ユーザーの継続指示でNormalへ一時切替、Review OFF維持。旧Owner Your Guitar Chronicle（ID2）の通常TopPageで通知2件を確認。
- 通知Acquire awaiting approvalをクリックするとPOST /api/auth/notifications/4/readが403（12:18:37Z）。公開service/statusはnormal。通知導線は未完了。cloud_notification_routes.pyのOrigin比較はrequest.base_urlを直接使用しており、Cloud Runプロキシ環境での不一致も調査候補。未確定なので保護を解除せず残す。
- TopPageの未回答欄にAcquireが出ていない。cloud-account-ownership.jsのinboxはownership-transfersのみ取得している。申請者自身の申請欄とは別に、現OwnerのAcquire未回答一覧を補完する必要がある。
- 代替の正規導線Product Detail > Acquire #72 > Claim decision Positiveから通常Owner判定を実行。管理者強制判定は使用しない。2026-10-11 21:19:28 JST頃に所有者がTakeshiOst（ID1）へ移行。旧Owner画面の判定欄が消えた。
- 旧Owner ProfileはOwned0/Formerly Owned1、新OwnerはOwned1/Formerly Owned0。Guitar52のClaim件数2、Current Owner TakeshiOst。新Owner画面で自分のAcquireに判定欄がないことを確認。Listingは通常判定対象外なので、他者Claimへの新Owner判定の追加実操作はしていない。
- 関連test_cloud_ownership.py / test_cloud_verification_notifications.py / test_claim_verification.pyは73 passed（既存設定/依存のwarning2件）。これは実画面検証を補う回帰確認。新しいコード変更は本ターンなし。
- 記録:fidelity-evidence/staging-new-owner-profile-20261011.png。次の修正候補は通知403と現Owner向けAcquire未回答欄。Transfer/係争の実サーバー確認は未実施。

- 終了時Offline・元の文面へ復元し公開statusで確認。Review OFF維持、Cloud SQL稼働継続。Guitar52の所有移行結果は保持。Git commit/push/merge未実施。


## 23. 通知403・OwnerのAcquire未回答欄の修正（2026-10-11）

- Cloud RunのHTTPS終端後に内部HTTPとなるため、通知POSTのOriginとrequest.base_urlが不一致になる問題を再現。Cloud Run専用起動経路（K_SERVICEがある場合）だけASGI schemeをhttpsに補正。Hostや送信元IPをForwardedヘッダーから取り込まず、別Origin／cross-site拒否は維持。ローカルHTTPは変更しない。
- GET /api/auth/owner-acquire-requestsを追加。認証済みの正規actorからCurrent Ownerの未回答・有効・審議通過Acquireを取得し、既存Owner判定／係争適格性の評価で再確認。自己Claim、過去の取得、回答済み、BANされた申請者等は除外。画像・Evidenceは返さない。50件＋継続cursor。
- Top／Profile最上部のUnanswered RequestsにAcquireを表示。Accept／Declineは既存openOwnerの再取得・revision確認を経由し、回答後に一覧を再取得。両画面の通知枠をローカルと同じunanswered-requests共通配色へ修正。
- 内蔵ブラウザがprompt()非対応のため、正式UIのAcquire辞退は既存textareaへ理由を入力→Review decision→Apply decisionへ変更。理由なし送信は不可。Positiveは従来の通常Owner判定経路。
- Python303件（所有者遷移、自己Claim、元Owner権限、通知、係争、HTTPS／Origin回帰）、JavaScript945件成功。既存pytest設定・Starletteのwarning2件。合成データを使った内蔵ブラウザでTop Accept／Profile理由付きDeclineと回答後の未回答欄消去を確認。実DBの所有権はこの修正検証では変更しない。
- 画面記録: fidelity-evidence/ygc-acquire-inbox-fixture-top.png、ygc-acquire-inbox-fixture-profile.png、ygc-acquire-decline-fixture.png（すべて合成データ）。配信と実サーバー通知確認結果は以下に追記。

- 最終Build 9abc2ec5-5b97-4fac-918d-102fb1289867 SUCCESS。digest sha256:cbff8bb4d0da123a9aee6fddf016841f857ccd6098b12c9367ede7f607c8c03f、ui-20261011lへ100%配信。公開JSとローカルファイルの一致も確認。
- Normalへ一時切替してTakeshiOstのProfileを再読込。新規Acquire inbox GETは200（12:35:10Z）。現在未回答Acquireなしなので実サーバー上のpending行のクリックは未実施。既存の所有移行結果は維持。
- 通知Claim Verification: Positiveをクリック。POST /api/auth/notifications/5/readは200（12:35:41Z）、未読数2→1、URL /ui/profile/guitars/52へ遷移。再表示した通知モーダルで既読／未読の表示差を確認。記録:fidelity-evidence/staging-notifications-fixed-20261011.png。今回の実データ変更は既読1件と運用モードの一時切替のみ。Git commit/push/merge未実施。

- 終了時に管理画面の実ステータスOffline、Review OFFを確認。元のメンテナンス文面を維持。Cloud SQLは稼働継続、Crawl設定は変更なし。


## 24. Transfer実確認と再取得準備（2026-10-11）

- ユーザー指示によりNormalへ一時切替、Review OFF維持。Guitar52のTakeshiOst（ID1）からYour Guitar Chronicle（ID2）へTransfer #73を22:01:02 JSTに作成。受取人のTopとProfileに未回答Transferが表示され、確認モーダル経由で22:02:09 JSTにAccept成功。
- Current OwnerはID2へ移動。元OwnerはOwned0/Formerly1、受取人は再読込後Owned1/Formerly0。受取人のPositive Transferに通常判定欄はなく、旧Acquire #72には他者Claimとして判定欄が現れる。通常Owner経路で検証し管理者強制判定は使用していない。
- 受諾直後のProfileヘッダー集計・Chronicleの更新漏れを発見。ownership/identity/disputeのupdatedコールバックを、Owned/Formerly再取得後に正式Profile（詳細・ヘッダー・Chronicle）も再取得する経路へ統一。session変更/画面離脱後の再取得を防止。
- 再取得フォームで採用済みAcquireのpreviewが残り、旧Challenge R4MHJPA5を再表示する問題を発見。未保存でCancelし送信しなかった。CloudApplications.previewの再利用不可revisionにacceptedを追加。未回答Acquireを再表示する既存経路は維持。新申請は新revision/token/Challengeを発行する。
- JavaScript関連144件、Python関連104件成功。隔離PostgreSQLでProfile/preview/新規Keep、所有者移転・自己判定禁止・受取Transfer保護・連鎖Transfer・管理者別経路・競合・rollback・権限を検証。旧Transfer/Release fixtureが公開本文をPRIVATEとして扱っていたため失敗したが、公開本文専用のダミー文字列に分離し、非公開情報漏洩検査を維持して再実行成功。
- 記録: fidelity-evidence/ygc-transfer-pending-top.png、ygc-transfer-accepted.png、ygc-transfer-new-owner.png。後者のヘッダー集計は更新漏れ修正前。次は新Acquire→審議→現Owner理由付きDecline→申請者の異議→管理者裁定。旧Acquire72はTransfer73より過去のため係争に転用しない。

- Build fe72b8ef-01b8-429b-be5b-9a89097dc0e8 SUCCESS、digest sha256:8c17ba4068d62a73d9b6a1b35abb981099b3d8d481f31d45f1be69ea7f99e5eb。ui-20261011mへ100%配信。公開/assets/cloud-account-page.jsはローカル修正版と一致。追加のProfile/intent JS41件も成功（今回JS計185件）。
- 実サーバーで再取得previewが新Challenge Y65UX7LC（提出期限2026-10-12 22:10:24 JST）になったことを確認。シリアルISSB25003873、取得日2026-10-11。写真未提出でKeep Request。係争テスト続行にはこのChallengeを写した近接・全体写真が必要。

- 保存後Detailでrevision 6495b7c44437e192587bf0b7158c91e7、Challenge Y65UX7LCが維持されることを確認。画面記録fidelity-evidence/ygc-dispute-acquire-challenge.png。写真・審議・新Claim作成は未実施。次のユーザー提供写真待ち。今回の修正後にもう一度Transferを作成・受諾してはいない（更新処理は回帰テストと配信一致で確認）。

- 終了時管理画面でOffline／元のメンテナンス文面／Review OFFを確認。Cloud SQL稼働継続、Crawl変更なし。Git commit/push/merge未実施。


## 25. Acquire再申請・Decline・係争Round 1・原Owner支持の実確認（2026-10-11）

- 提供写真IMG_6250（近接）/IMG_6251（全体）を保存済みrevision 6495b7c44437e192587bf0b7158c91e7へ通常ブラウザ経路で提出。両画像2268×3024、申請保存画像は1536×2048。Challenge Y65UX7LC、Serial ISSB25003873。
- Normalへ一時切替。このAcquire1件に限定してReview ON、既存Cloud review bridgeで保存済み近接・全体・referenceを実表示して審議。文字照合一致、木目対応2点でidentity supported、Maker/Model uncertain、Finish consistent。accepted、Acquire Claim74が22:20:50 JSTに作成。Review OFFへ復元。今回も期待値を知る同一チャットの実フロー検証であり、独立した精度検証ではない。
- 現Owner ID2のTop未回答欄から通常Decline。検証用の意図的なDeclineであり虚偽の断定ではないことを理由に明記。未回答欄から消え、ID1のProfile最上部に異議申立て候補と理由が表示された。
- ID1が説明・相手用要旨・IMG_6251の再利用添付で申立て。実取引や法的紛争の主張ではなく動作検証と明記。22:25:09 JSTにRound1申請者Submitted、提出フォーム消去、Owner維持を確認。
- ID2の通常Profileで申請者の非公開説明・未公開要旨が見えないことを確認。検証用説明・要旨（添付なし）を提出し、22:27:56 JSTにUnder review。両者の提出フォームが消え、申請者側はRefreshで更新された。
- BrowserConsoleの係争一覧は初期読込で空欄だったが、Refresh後に1件表示。管理者は双方の非公開説明を表示でき、Download private attachmentでevidence-2.jpgを取得し、実画像が提出写真であることを確認。
- 管理者のSupport original Ownerを理由付きでReview decision→Confirm。Resolved / Original owner supported / Current Owner Your Guitar Chronicleを確認。申請者側のRefreshでもResolvedと裁定理由を確認。新しいTransferや再審議は作成していない。
- 記録: fidelity-evidence/ygc-dispute-under-review.png、ygc-dispute-resolved-applicant.png。非公開要旨の管理者公開、追加ラウンド、申請者支持、解決後Claimロックの実クリックは今回未検証。
- 残るUI差分: Product Detailに当事者用Under dispute表示がなく、Ownershipメニューは有効に見える。CLOUD_OWNERSHIP_DISPUTES.mdでauthenticated hint未移植とされている箇所。公開DTOへ係争情報を混ぜず、認証済み当事者用の表示・導線・操作無効化を補完する必要がある。今回サーバー側ロックを破る更新は試していない。
- Profile/Consoleの多数の認証済み初期取得が完了するまで操作disabledが長く続く。ログイン切れではなかった。直近HTTPログは200、API応答は概ね数秒で、画面全体の待ち時間は集約取得の影響がある。管理者係争一覧の初回空欄も要再現確認。
- 今回コード変更・再デプロイ・Git commit/push/mergeなし。配信はui-20261011mのまま。終了時の運用状態は後追記。

- 終了時BrowserConsoleでOffline、元のメンテナンス文面、Review OFFを確認済み。Cloud SQLは稼働継続、Crawl変更なし。


## 26. 引継ぎ後の係争Product Detailと初回一覧修正（2026-10-11）

- ユーザーが元チャットの許可継続と作業再開を明示。既存未コミット変更を保全。Git commit/push/mergeは実施していない。
- 既存participant/Admin private dispute一覧APIにindividual絞込みを追加。canonical account、participant scope、Admin別経路、mode/projection fence、private/no-storeとDTOを維持。公開catalog DTO・DB schema・所有権評価器を変更していない。nullable SQL parameterはCAST AS BIGINTでPostgreSQL型を明示。
- 新しいcloud-detail-dispute.jsがTop/Profileで選択個体だけを照会。認証済み当事者・AdminにUnder disputeを表示。participantは既存共通詳細モーダル、Adminは/console?dispute=IDへ移動して認証済みAdmin詳細を開く。管理者のリンク実クリックは今回ブラウザ未確認。
- 所有権メニュー・Acquireを係争中／確認中／確認失敗時に無効化。Specification/Repair・Incident・Event・Mediaは維持。取得失敗は画面に案内と明示再取得導線を表示。選択・identity・pagehide・epochで古い応答と入口を無効化。Profileの所有者専用差替えメニューにも同じガードを適用。
- 係争一覧取得前にrenderで復元済みidentityを同期。Admin初回取得結果が後続renderのidentity切替clearで消える競合を回帰テストで再現・修正。
- 対象Python133件、JavaScript225件成功、git diff --check成功。全件テストの繰返しは実施していない。
- headless ChromeはsandboxのSIGABRTで起動不可。一時PostgreSQL18はshmget Operation not permittedでinitdb失敗。制限の迂回・再試行をしていない。今回追加の実PG filter回帰は実行未完了。これらを成功と記録しない。
- 内蔵ブラウザ＋loopback合成SDK/架空データでTop/ProfileのUnder dispute→共通詳細、Ownership disabled、Event enabledを実確認。1440px表示とProfile390px表示／詳細操作、横はみ出しなしを確認。fixtureのround/rounds不一致を修正してから成功。実案件作成・所有移転・審議・裁定なし。通常Chrome完全比較や追加係争ラウンドは未確認。
- 画面記録: /Users/t_oshita/Documents/Codex/2026-10-11/new-chat/outputs/dispute-ui-check.png（合成Top画面）。検証サーバー停止、検証タブ閉鎖、viewport解除済み。
- Build7c7dc166-4973-43b5-9e24-61af841e1369 SUCCESS。223ファイル／3.7MiBのアプリ許可リストだけを送信。ui-20261011nへ100%配信。image digest sha256:e549dc14b6daf1cde8d57f87ab4620ab2ea6080d70738ceb8f2e6bb035cd4e66。公開cloud-detail-dispute.jsとローカル修正版の一致、/ready正常、未認証private一覧401を確認。
- /api/service/statusはOffline、元メンテナンス文を実確認。Cloud SQL RUNNABLE/ALWAYSを実確認。Review/Crawlは一切操作しておらず前回OFFを維持（今回Admin画面での再確認はしていない）。実サーバー認証済みの絞込API・新Admin導線の動作確認は残る。新チャットのブラウザには元チャットの認証済みタブが引き継がれていない。
- 次: Profile/Console全体busyが多数の初期読込完了まで続く待ち時間の改善。PG実engine回帰と認証済みstaging read、追加証拠round/要旨公開/申請者支持/解決後Claim変更拒否の実検証。今回の初回一覧修正は全体待ち時間の解消ではない。


## 27. Profile/Consoleの初期取得ロック分離（2026-10-11）

- ユーザーの継続指示を受け、初期読み取りを操作用の全体busyから分離。Profileは基本profile/Owned/Formerly/Favoritesを先行し、関連パネル取得中でも取得済みUser SettingsやSignOutを利用可能。ログイン/再認証/BFCache復元も認証処理後にbusyを解除して読み取りを続行。更新操作のbusyは維持。
- Consoleは認証済みAdmin確認後に各一覧を並行取得。サービス設定とReview設定は各取得完了時に利用可能になり、未取得の設定は操作不可。診断は後続読み取りへ分離。係争deep-linkは係争一覧取得後に開き、他の一覧を待たない。Review取得失敗でも取得済みサービス設定を保持。
- shared authorizedFetchの同時上限2は維持。Consoleにidentity通知とsessionEpochを追加し、古い設定応答/診断/deep-linkを破棄。Profileのactor/session/pagehideガードも維持。
- 関連JavaScript185件成功。Consoleの遅延パネル/診断・部分失敗・identity切替、Profileの通知待機/古い失敗破棄、既存認証上限・BFCache・所有権/係争を検証。両変更JSのsyntax checkとgit diff --check成功。Python処理は変更していないため前節の検証を再実行していない。
- 内蔵ブラウザで合成通知APIを未完了のまま保持（pending2）、ProfileのUser Settings/SignOut enabledとUser Settingsへの実遷移成功を確認。画面記録outputs/loading-profile-check.png。合成検証サーバー停止、合成タブ閉鎖。
- Build1b73bbfd-8434-4291-87fa-bfbce6e9cedf SUCCESS。223ファイル/3.7MiBの許可リストのみ送信。ui-20261011oへ100%配信。digest sha256:72c7a986f3cfa96a3ac2ef7145f8e5518c7b980a5e5fd130a7de6430481e9b91。公開cloud-account-page.js/cloud-console-page.jsのローカル一致、/ready200、/api/service/status Offline/元文面を確認。
- ユーザーが内蔵ブラウザで管理者ID2に再サインイン。実Consoleの初回一覧を確認。初期open filterは解決済みなので0件が正常。All cases選択でCase2（Guitar52/Acquire74）1件を確認。/console?dispute=2へ遷移すると自動で詳細が開き、Resolved/Original owner supported/Current Owner ID2とRound1提出済みが表示された。詳細読取だけで裁定/再審議/公開操作なし。
- 実ConsoleでOffline/元メンテナンス文/Review OFFを確認。Crawl設定・SQL稼働・サービスモードを変更していない。Git commit/push/mergeなし。認証済み確認用タブは次回作業へ保持。画面記録outputs/loading-console-check.png。
- 通常Profileの実APIはOfflineにより拒否される。今回Normalへ切り替えていないので、実データProfileの読み込み時間・当事者Product Detailは未確認。実PG filter回帰は26節記載のsandbox制限が継続、追加証拠round/要旨公開/申請者支持/解決後Claim変更拒否の実検証も残る。


## 28. クローズドテスト準備・ターン1の途中確認（未完了）

- ユーザーが①②の残作業を基本6ターンで進め、各ターン完了を確認する方針を承認。今回ターン1（通常主要画面、PC/スマホ、検索/ページ送り/履歴/通知）。ターン2以降へ進まない。
- 継続済み検証許可に基づきNormalへ一時変更、Review OFFのまま。終了時Offline/元メンテナンス文へ復元し、公開statusとConsole表示で実確認。Crawl/SQL/所有権/Claim/申請/係争状態の変更なし。通知クリックでOwner ID2の通知1件を既読化した。
- 公開正式Top51件、シリアルISSB25003873で1件、Guitar52詳細/代表画像/Current Owner/公開Chronicleを確認。戻る/進むで検索条件と詳細URLが維持。1440x900と390x844で実幅とdocument scrollWidth一致、横はみ出しなし。スマホ詳細を閉じると一覧表示へ戻る（選択URLは維持する設計）。正式Topは全件集約表示でページ送りなし。
- 既存公開カタログ/はPage1 of3→2→1とURLのpage遷移を実確認。
- 既存ログインID2の通常Profileで本人名/Owned1/Formerly0/Claims3、本人情報読取後User Settings/SignOut enabledを確認。User Settingsへ移動、現在値取得、保存せずCancel。Profile通知7件を取得し、最新通知から本人用Case2詳細が開きResolved/Original owner supported/Current Owner ID2を確認。相手の未公開説明は表示されず本人提出説明は表示された（本ターンの目的は導線、権限全面確認はターン2以降）。Top/通知検証でJS errorログなし。
- 既存tab3はviewport設定の対象にならず実幅491pxだった。ProfileのPC1440/スマホ390確認と扱わない。撮影名をturn1-profile-default-pc/mobileへ修正。Top幅確認は対象tab5で実測成功。既存タブを対象にするviewport手順の確認も残る。
- 関連JS140件成功。アプリコード変更/再deploy/Git commit/push/mergeなし。配信ui-20261011o維持。
- 通常ユーザーID1へのサインインをユーザーへ依頼したが、完了回答は今回まだない。新しいProfile tab4は未ログイン。既存Admin tab3とtab4をhandoff保持、公開検証tab5を閉鎖、viewport解除。ID2の確認を一般member権限の確認と混同しない。
- **ターン1は未完了**。残るのはID1でProfile/Settings/Members/Top/通知のPC/スマホ確認、会員検索/会員詳細と履歴、必要な表示修正。ID1ログイン後に検証時間だけNormalへ切替、終了時Admin tab3でOfflineへ復元する。認証はsessionタブごとで、新規タブのログインは継承されない。
- outputs/turn1-top-pc.png、turn1-top-mobile.png、turn1-notification-detail.png、turn1-offline-restored.pngを記録。完了判定前にターン2を開始しない。


## 29. クローズドテスト準備・ターン1完了（ID1実確認）

- ユーザーがID1サインイン完了を連絡。tab4のTakeshiOstを確認。既存Admin tab3で検証中だけNormal、終了時Offline/元メンテナンス文へ復元。公開statusと実Console Offline/Review OFFを確認。SQL/Crawl/Review設定は変更なし。
- ID1 ProfileはOwned0/Formerly1/Claims3、Location JP/Kyoto、User Chronicle6件、Guitar52の公開詳細を表示。本人情報取得後User Settings/SignOut enabled。SettingsはuserId1/name TakeshiOstでSave enabled、保存せずCancel。PC1440x900/スマホ390x844でProfile/Settingsを実測確認、document scrollWidth=innerWidth。Profile mobileの最初の撮影はresize直後の古いフレームだったため、再撮影して画像を確認済み。
- ID1通知9件、未読8件。最新の裁定通知1件をクリックして既読化、未読7件。本人用Case2詳細が開きResolved/Current Owner ID2/Original owner supportedを確認。本人提出内容を表示、相手の未公開説明なし。詳細を閉じてProfileに復帰。所有権/裁定/申請/Claim/Follow/設定変更なし。
- Members2会員、Your Guitar Chronicle検索で1会員、会員詳細の名前/Followers/Following/Follow入口を確認（Follow送信なし）。スマホ390/PC1440で横はみ出しなし。戻るで検索query維持、進む/再読込で会員2を維持。実会員2件なのでMembersの次pageは存在しない。公開旧catalogのページ送りは28節で確認済み、正式Topは全件集約。
- ID1 Topは51件、シリアル検索で1件、Guitar52詳細/代表画像/公開Chronicle確認。検索付きURLを戻る/進むで維持。PC/スマホ画像を実確認。JS errorログなし。
- 取得前のraw Top HTMLで検索を入力した最初の操作はscript初期化で上書きされたため、取得後に同じ検索を行い1件を確認。初期の入力可能状態、通知件数0→取得値への表示はターン2の読込状態確認対象として明記。ターン1の取得後の通常導線は完了。
- viewportは選択中のtab4へ適用できた。28節のtab3幅変更不能は別タブが選択されていたことが原因。実幅を各確認で検証し、終了時override解除。
- アプリコード変更/再deploy/Git commit/push/mergeなし。配信ui-20261011o。28節で成功した関連JS140件の同一ソースを使用し、再実行していない。doc diff check成功。
- 画像outputs/turn1-id1-profile-pc.png、profile-mobile.png、settings-pc/mobile.png、members-pc/mobile.png、top-pc/mobile.png、notification-mobile.png（全てturn1-id1-接頭辞）。PC/スマホの要所をvisual QA。認証済みAdmin tab3/一般member tab4を次回へ保持。
- **ターン1完了**。ユーザーの完了確認を待ってターン2（係争中詳細、取得中/失敗/再取得、logout/identity/BFCache）へ進む。ターン2以降の係争新規作成・追加ラウンド・裁定・Transferは未実施。


## 30. クローズドテスト準備・ターン2完了

- ユーザーの指示でターン2（係争中詳細・取得中/失敗/再取得・logout/identity/画面復元）を実施。実Case2は解決済みのため、未解決状態と通信障害はloopback合成SDK/架空ケースで再現。実係争の再審議/新規作成/証拠提出/所有移転は行っていない。
- 初期HTMLの検索/Sort/Submitをdisabledにし、canonical routeの値反映と全handlerの登録後に有効化。初期API取得を待たず検索可能で、古い初期応答は既存epochで破棄。catalog headingのcountPendingを未取得/取得中/取得失敗に連動。正式通知headingもunreadCount未取得ならcountPending=true。未知件数は—、取得成功の空配列は0件と区別。
- JS270件成功。新規回帰は初期API保留中の検索と古い応答の破棄、catalogのpending/failure/empty、notificationのpending/failure/empty/identity消去。既存cap2、係争read/mutation/attachment失権、BFCache persisted=trueと不確定結果markerの保護も通過。Python17件成功（既存警告1）。JS syntax/diff check成功。
- 内蔵ブラウザで合成cloud-ui.js配信を保留し、検索disabled/一覧件数—を確認。通知GET保留で件数—。未解決個体1のUnder dispute→共通詳細を確認、Ownership disabled、Specification/Repair/Incident/Event/Media enabled。private case API503時に明示エラー/再取得入口、Ownership disabledを維持。fault復旧後に再取得すると係争なし個体2は入口消去、個体1はUnder disputeへ復帰。
- Aliceの係争フォームへ架空の非公開下書きを入力（送信なし）、別ページへの全遷移→Backでモーダル非表示/下書き空。logoutで係争私的入口消去、Bobへ通常signIn後に詳細を開いて説明/要旨が空で旧draft不在を確認。実ブラウザのBack復元がBFCacheだったかは判別していない。BFCacheのpersisted通知は上記VM回帰で明示検証。
- 合成通知503で件数—/エラー/Refreshを確認。復旧後の明示Refreshで正常な0件/No notificationsを確認。合成fixture scriptはwork/turn2_preview.py。server停止/tab6閉鎖。実ID1/Adminはlogoutせず保持した。ログアウト・identity切替のブラウザ確認は合成環境であり、実ID1で実施したと記載しない。
- Build2a9390ff-d6b9-4592-98e9-aba7b426839f SUCCESS、223ファイル/3.7MiBの許可リストのみ送信。ui-20261011pへ100%配信。digest sha256:099ed8b8115edfc4c54800dd6d78d51b736f97da311dce4e8795ce29d81454a0。公開変更JS2件はローカル一致、/uiの初期disabled/countPendingあり、/ready200。
- 配信後の実ID1確認のため一時Normal（Review OFFのまま）。Topの初期件数—、検索入力SquierとURLquery保持、取得完了で1件。ID1通知の初期—→取得完了9件を確認（今回実通知の既読化なし）。実server障害を発生させていない。終了時Offline/元メンテナンス文/Review OFFを公開statusと実Consoleで確認。Crawl/SQL設定変更なし。
- 記録outputs/turn2-private-state-failure.png（合成のOwnership disabled）、turn2-notification-recovered-empty.png（合成正常0件）、turn2-live-notifications.png（実ID1正常9件）。Admin tab3/ID1 tab4をhandoff保持。Git commit/push/mergeなし。
- **ターン2完了**。ユーザーの完了確認を待ってターン3（追加証拠round→再提出→管理者確認→要旨公開）へ進む。実PG検証はターン6、残る裁定/Transfer分岐はターン4〜5で未実施。


## 31. クローズドテスト準備・ターン3完了（実ケース追加証拠・要旨公開）

- ユーザーのターン3開始指示、および利用制限後の継続指示で実施。既存Guitar52/Acquire74/Case2をAdmin UIから再開しRound2を作成。記録上のCurrent OwnerはID2のまま。検証中だけNormal、Review OFFを維持。
- Round2にID1 applicantとID2 original Ownerが説明・要旨を1回ずつ再提出（証拠ID4/5、追加round添付は任意のため省略）。双方Submitted→Under reviewを確認。AdminのRequest additional evidenceをReview/Confirmで実行しRound3作成、Round1/2履歴保持、双方の説明・要旨フォーム空を確認。
- Round3はID1が23:42:20 JSTに提出済み（証拠ID6）。利用制限後は保存結果を確認し二重送信なし。ID2のprepare時はID1提出によるversion更新を検出し「case changed」で送信保留、最新状態でReviewし直して23:43:48に提出（証拠ID7）。23:43:49双方Submitted/Under reviewへ。説明はT3-APPLICANT-PRIVATE-R3/T3-OWNER-PRIVATE-R3、原要旨はT3-*-UNPUBLISHED-R3という無害な検証マーカー。
- 当事者UIは双方とも公開前に相手の説明/未公開要旨/原本導線を表示しない。Admin UIでは双方のPrivate evidence detailsを展開して実際の説明を確認。Round3の双方要旨をT3-PUBLISHED-APPLICANT-R3 / T3-PUBLISHED-OWNER-R3へ編集し、それぞれReview/Confirmで公開（23:44:29/23:44:47）。当事者の双方で両公開要旨あり、相手のPRIVATE/UNPUBLISHEDマーカーはDOM textContentにも不在。本人の元要旨は保持。
- Admin兼OwnerのProduct DetailのUnder disputeはConsoleへ遷移する設計。Ownerとしての提出/閲覧には通常ProfileのselfDisputes一覧Detailを使用。認証途中の一時表示は最終的に本人データへ復帰、再ログイン要求やcredential操作なし。
- 関連JS ownership-disputes82件成功、双方ブラウザーerrorログなし。新たなアプリ修正・deploy・Git commit/push/mergeなし、配信ui-20261011p維持。実PG追加回帰はターン6の残項目。
- 終了時Console Offline/Review OFF、公開/api/service/statusのOffline/元メンテナンス文を確認。SQL/Crawl設定変更なし。Case2はRound3 Under review、Current Owner ID2、Acquire74 Negativeのまま。申請者支持裁定/所有移転は未実施（ターン4）。
- outputs/turn3-admin-published.png、turn3-applicant-published.png、turn3-owner-published.pngを保存し画像確認。Admin tab3/ID1 tab4をhandoff保持。ターン3完了、ユーザーの指示後にターン4へ。


## 32. クローズドテスト準備・ターン4完了（申請者支持・解決済みClaim制限）

- ユーザーのターン4指示で、最新Case2 Round3 Under review/Owner ID2/Acquire74を確認。Adminが理由付きSupport applicant/Acquire74をReview→Confirm。実Case2 Resolved/Applicant supported、Current Owner TakeshiOst(ID1)へ移行。Acquire74 Positive、author ID1維持。追加のTransfer/Release/Acquire作成なし。
- 検証中のみNormal、Review OFF。実ID1 Profile Owned1/Formerly0/Claims3、実ID2 Profile Owned0/Formerly1/Claims3、各区分のGuitar52を確認。双方Product Detail Current Owner ID1、公開Chronicle4件、Acquire74 Positiveカード、係争hint消去。ID1のOwnership Transfer/Releaseフォームが開き、Your Guitar Chronicle(ID2)を検索できる。送信せずCancel。旧OwnerのOwnershipは新規Acquireの警告へ進み、Backで中止。
- 実通常Admin VerificationでAcquire74 Negative変更を試すと、旧配信pではDBの保護で変更を防止したがHTTP503/結果不明表示だった（14:52:36 UTCのRun request log）。正本再読込でPositive/Owner1維持を確認。誤解を避ける修正を実施。
- PostgresOwnership通常Admin adapter内でownership_dispute_claimsのリンクを検査し、既存DB triggerの前にDisputeClaimLockedを返す。係争裁定は別経路なので影響なし。Admin routeは409/detail.code=dispute_claim_lockedへ変換、Consoleに英日「係争の再審議が必要」という専用表示を追加。所有アルゴリズム/DB schema/通常ユーザー権限は変更なし。
- 新規回帰はリンクありでは通常moderationに入らない/なしは通常処理、HTTP409コード/no-storeを検証。Python181件（cloud_guitars/disputes/cloud_disputes/cloud_ownership）成功、既存警告1。関連JS58件成功、syntax/diff check/locale英日key一致成功。編集・削除拒否、自己判定/旧Owner失権などの組合せは合成SQLite/service回帰で確認。実UIのAcquireに通常編集・削除入口はなく、実環境でそれらのPOST/DELETEを直接送信したとは扱わない。実PG追加回帰はターン6の残項目。
- 223files/3.7MiBの許可リストのみCloud Buildへ送信。Build6f70bb33-3486-4a56-bdf3-8288ee073e9f SUCCESS。digest sha256:1a3bed9196fc820fa624730720061eb9e20ca3d928f948e06970c55203abfae1、revision ygc-staging-accounts-ui-20261011qへ100%。image updateのみで既存service/env/IAM設定保持。配信Console JS一致/新locale keyあり/ready200。
- 配信qの実Adminで同じNegative変更を再確認し、409（14:58:31 UTC Run request log）、専用ロック文表示。Chronicleを再取得してAcquire74 Positive/Owner1維持。通常の強制判定でも裁定を変更できない。再審議は実行しない。
- Normalを終了してOffline/元メンテナンス文/Review OFF復元。公開statusとConsoleで確認、再配信後もOffline維持。SQL/Crawl設定変更なし。Git commit/push/mergeなし。outputs/turn4-new-owner-profile.png、turn4-resolved-claim-locked.png画像確認。Admin3/ID1 tab4 handoff保持。
- ターン4完了。次はユーザー指示でターン5（新所有者からTransfer、受領後の分類/判定権限/集計/Chronicle）。Guitar52は現Owner ID1、Case2 Round3 Resolved/Applicant supported、Acquire74 Positiveを開始条件とする。


## 33. クローズドテスト準備・ターン5完了（Transfer受領・分類と権限）

- ユーザーのターン5指示でGuitar52の新所有者ID1からID2へTransferを実施。検証中のみNormal、Review OFFを維持。実テストデータのワークフローであり、実物の法的所有移転を判断するものではない。
- ID1が明示的にYour Guitar Chronicle(ID2)を選択してAdd Claim。Transfer75を2026-10-12 00:04:30 JSTに1回作成（UTC2026-10-11T15:04:30.044994）。pending/Unverifiedの間はCurrent Owner ID1維持。正式UIはAdd Claimで保存まで進むため、追加確認ボタンを探した際にも保存済み状態を先に確認し再送信なし。
- ID2 ProfileのAccept Transfer→確認ダイアログConfirmで承諾。受領時刻2026-10-12 00:07:20.477615 JST、保存結果acceptedとOwnership action recordedを実確認。Admin ChronicleはTransfer75 Positive、occurred_at=2026-10-11T15:07:20.477615+00:00、owner_user_id=2。作成時刻と受領時刻を区別する。現在Owner ID2へ切替。
- 双方を再取得してID1 Owned0/Formerly1/Claims4/User Chronicle7、ID2 Owned1/Formerly0/Claims3/User Chronicle6。Guitar52はID1のFormerly、ID2のOwnedに入り、両一覧の個体Claims5、公開Chronicle5件。Transfer75はID1の投稿履歴に追加され、受取側の投稿Claim数は増えない。pending inboxは承諾後に消去。
- 実Product Detailで旧Owner ID1にはClaim decision欄なし。新Owner ID2には過去Acquire72のPositive/Negative/Unverified欄あり、裁定済みAcquire74・受領済みTransfer75/73・自身Listing71には通常判定欄なし。判定値は変更していない。ID2 Ownership入口はTransfer/Releaseフォーム、ID1は既存OwnerのあるAcquire警告へ進む。前者Cancel、後者Backで終了し、新規Transfer/Release/Acquireは追加しない。API拒否の組合せはターン4で成功済みの同一ソース回帰に基づき、今回直接POSTで試したとは扱わない。
- AdminのCase2詳細はRound1〜3/公開要旨/最新Applicant supported(Acquire74)を保持、Resolved、現在Owner ID2。後続Transferによりcase winner ID1と現Ownerが異なるためAction選択肢空、decision disabled、再開不可。古い裁定による巻戻し操作なし。Acquire74はPositive/author ID1を保持。
- アプリコード変更・新規deploy・Git commit/push/mergeなし、ui-20261011q維持。既に通過した同一コードの回帰を再実行していない。双方ブラウザーerrorログなし、git diff --check成功。実PG追加回帰はターン6の残項目。
- 終了時Offline/元メンテナンス文をConsoleと公開statusで確認、Settings saved/Review OFF。SQL/Crawl設定変更なし。outputs/turn5-new-owner-profile.png、turn5-former-owner-profile.pngを保存して画像確認（既定幅491px、PC1440やスマホ390検証とは扱わない）。Admin tab3/ID1 tab4をhandoff保持。
- ターン5完了。ターン6はユーザーの指示後に開始。残る実PG回帰は既存sandbox制限（ローカルinitdb shmget拒否）を無断回避しない。最終確認と制限の解消・代替可能な実PG検証経路の確認を行う。


## 34. クローズドテスト準備・ターン6完了（隔離実PG・最終回帰）

- ユーザーのターン6指示で実施。前回sandboxで拒否されたローカルinitdb/shmgetとheadless Chromiumは再試行せず、既存Cloud Build内の使い捨てDocker PostgreSQL18.6を使用。接続はテストコンテナと共有する127.0.0.1:5432のみ、架空ユーザー/個体/写真/Storage、UUID付きテストDB/runtime role。Cloud SQL/実ステージングの破壊的回帰ではない。worker内PGは終了時trapで削除、DB/roleは各fixtureのfinallyで回収。設定はwork/turn6-cloudbuild-pg.yaml、集約runnerはwork/turn6_pg_runner.py。
- 旧PG fixturesに公開Claim件数・presentation未対応の期待値と、公開本文/表示名へPRIVATEマーカーを使用した箇所が残っていた。公開/非公開データを分離し、PRIVATEの非公開仕様値・EXIF・保存参照・本人用プロフィール・無効Claim等の検査を保持。Public Catalog件数を実際の公開Chronicle全件と比較し、Favoriteもdecimal件数を検査。JSの旧Console模型にlocation.search/get account/getAttributeを補完し、Review変更の既存確認/CAS検査を復旧。
- Listing訂正理由は既存の本人用訂正履歴仕様に従い保護する。共通enrich_claimsでidentity_correctionのpresentation.bodyだけNoneにし、本人用の元bodyや他種別の公開本文/投稿者/投票数は維持。qとの差分はapp/src/ygc/cloud_public_presentation.pyの1ファイルのみ。新unit回帰と実PG Identity Correctionで、公開理由の不在・本人履歴/現在identity/検索結果の保持を確認。
- PG dispute fixtureでは裁定済みClaimへの普通Admin操作を汎用DBエラーではなくDisputeClaimLockedで検査。実PG+実FastAPI Admin routeでPositive/Negative/Unverified全てHTTP409/dispute_claim_locked/private,no-storeとデータ不変を確認。両裁定分岐、個体絞込みのparticipant/Admin scopeとnullable BIGINT型、追加round/公開要旨/私的原本/容量制限、Transfer後の再開拒否、競合・rollback等も通過。
- 最終PG Build631c8b33-4596-4f10-9fa3-139909942dd5 SUCCESS、17/17検査群、失敗0（PostgreSQL18.6 Debian）。全体runnerのinitialize/bootstrap、dispute storage、accounts、operations、Admin applications、public catalog、claims、media、event、identity correction、notifications、ownership workflow、disputes、favorites、profile visibility、followsを検査。account検査内のbackup/maintenance/crawl/review等も架空環境で通過。PG schema/runtime grants不変。先行ジョブは旧期待値失敗2回、一時DB起動待ち失敗1回、データ補正中に中止1回。原因を補正して全体17/17成功を確認し、失敗を成功扱いにしていない。Favoriteの補助単独Build38542e38-80c6-4a3e-bc2a-45d35221b488も1/1成功。
- アプリ修正後の全Python2535件成功、既存非推奨警告3件。全JS960件成功、失敗0。関連Python271件・Favorite関連130件も成功（全体件数へ重複加算しない）。schema artifact/依存定義・pin/ビルド要件検査/git diff --check成功。ブラウザー通常導線はターン1〜5のIAB実確認を継承し、新たにローカルChromium全体チェックを実行したとは扱わない。
- 配信Buildabb97d3b-6fe3-4a33-bbf6-1ee821eec18f SUCCESS。223ファイル/3.7MiBのアプリ許可リストのみ、テスト/資料/秘密情報なし。digest sha256:f06431d7ff918e17039cc24b4970556bfb1d2f24e08329111af437efa527d1b5。ygc-staging-accounts-ui-20261012rへimage updateのみで100%配信、service/env/IAM設定保持。
- 配信後ready正常、公開status Offline/元メンテナンス文、再取得Console Offline/Review OFFを確認。今回はNormal切替なし。実Claim/裁定/所有権/SQL/Crawlの設定変更なし。Guitar52 Owner ID2、Transfer75 accepted/Positive、Acquire74 Positive、Case2 Round3 Resolved/Applicant supportedはターン5終了条件を維持。Git commit/push/mergeなし。
- outputs/turn6-results.txt、turn6-postgres-results.log、turn6-staging-offline.pngを保存。画像確認済み、Admin tab3/ID1 tab4をhandoff保持。基本6ターンの修正・確認は全て完了。次工程はユーザーの指示を待ち、参加者招待・開始のモード変更等を自動で開始しない。


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


## 38. パフォーマンス改善・第1段階完了（2026-10-12）

- ユーザーは一覧/ソート/Detail、ページ間のデータ再取得、サインイン画面の一瞬表示の改善を希望し、段階的な動作検証を承認。今回は第1段階の重複取得と通常GETの強制JWT更新を削減。新着/統計/地図の機能は継続。元の大項目③、Follow活動、Messagesは未開始。
- 通常GETはSDKの有効なtokenを使い、変更操作/メール確認の強制更新、APIごとのcanonical認可、no-store、同一origin、共有2通信枠は維持。同じ一覧の個体選択では一覧を再使用、検索/ソートで選択ID不変ならDetail/Chronicle/写真を維持。更新中も旧行/count/Detailを保持、明示Refreshは正本再取得。両方を完全キャッシュする経路は作らず、各操作で新しい一覧またはDetail APIによる認可確認を残す。Offline/Admin Onlyのstatus制限やAPI401/403/503は保持データも破棄。
- Account/Profile初期HTMLの認証フォームとauthActionsをhiddenにし、認証復元が確定するまで表示しない。ID1実Profile移動直後は両hidden/Loading authentication、復元後TakeshiOst/Owned0/Formerly1/Claims4を確認。ページ跨ぎの完全再読込やBFCache復元時の追加調整は次段階に残る。
- JS984件成功（追加7件:51件3ページの一覧再利用、ソート中表示保持/Detail再利用、401/403/503消去、Offline/Admin Only消去）。既存GET強制refresh=trueの期待値だけをfalseへ変更、mutation期待値/認可・遅延・非公開消去検証は保持。Console requestのoptions未指定に対応するdefault={}も修正。Formal配信Python2件成功/既存Starlette警告1件、diff --check成功。backend/SQL不変なので実PGとPython全体は前回同一source検証を継承、再実行した扱いにしない。
- 実staging変更前makerソートの公開catalog取得は一覧3+Detail1+Chronicle1+写真1=6回、変更後3回（Detail/Chronicle/写真0）。変更前は操作直後一覧0/Detail非表示、変更後一覧51/Detail維持/aria-busy=true、完了後ascending確認。変更後個体16選択は一覧0/Detail1/Chronicle1、一覧51維持しAmpeg表示。単発server latency約0.5〜0.6秒は未改善。初期行Favorite取得が共有枠を使うため、変更後ソートでも一覧ページ間に秒単位待ちが残る。通信削減を全体体感速度の改善完了と誤認しない。
- Build a3546819-8c94-4e04-989e-8cca65693427 SUCCESS、227files許可リスト。digest sha256:88b27c6900abee37c68e8aafb0a62609ed672702ca9ae323ff7dd8ca50b8b2bf、revision ygc-staging-accounts-ui-20261012u100%。image/revision/client metadata以外のservice template一致、ready200、変更asset配信byte一致/no-store。
- 実画面Normalで検証後、今回開始時に再取得して確認したOffline/「サービスはメンテナンスのため一時的に停止しています。しばらくしてから再度お試しください。」へ復元。以前の英日messageへ戻さない。Console/public status/会員の保持データ消去を確認。Review OFF維持。SQL/Crawl/Jobs/IAM/env/所有権/Claim/プロフィール等に変更なし。commit/push/mergeなし。tab3/4handoff、viewport解除。
- outputs/performance-stage1-results.txt、baseline/new-sort/selection-requests.json、sort-retained.png、profile-restoration.png。第2段階はFavorite等の背景取得と操作通信の優先順位、ページ共有state/期限/破棄、不要な初期panel取得。第3段階はDB接続/SQL/静的配信と実測比較。全パフォーマンス工程完了ではない。


## 39. パフォーマンス第2段階・通信整理の反映（2026-10-12、全体最適化は未完了）

- ユーザーの「続けて」で第2段階を継続。共有2通信枠を維持し、行Favorite/member-avatarの背景GETを同時1件に制限。canonical me/変更操作/一覧・選択Detailを待ち列で優先。vの実測で統計/地図まで高優先度だったことを確認し、wで新着/統計/地図を補助取得へ変更。実行中の通信を強制中断する優先度ではない。
- 同じSDK principal・URL・headersの同時GETだけを1通信へ共有しResponse.cloneで各部品が独立読取。完了responseは保存せず、後続GETは正本取得。signal/force/body/非GET/meは共有対象外。write/identity変更で共有Mapを消し、遅い共有Responseはprincipal不一致なら拒否。queued Abortは直ちに待ち列から除去。HTTP no-store/同origin/各API認可/変更時refreshを保持。私的データをStorageに追加しない。
- Profileの親が復元した同一objectのcanonical accountを埋込Detailが初回共有し、2度目のauth.restoreを省略。明示Refreshは復元を維持。初期terms読取とrestoreを並列化。Account Hubはin-flightを共有し初回Profile側はreadyを待ち、2度目の初期refreshを省略。Catalog Back/Forwardは一覧/同sessionを保持し、新Detail/Chronicleによる認可確認を維持。BFCacheは依然正本復元が必要、復元中/停止中のloginフォームをhidden。
- JS995件成功/0失敗。追加11件で背景枠/操作vs統計優先/独立consume/後続fresh/headers・force・signal分離/write・identity無効化/prompt abort/同じProfile account/違うobjectの復元/Back拒否/Hub sharingを検証。既存BFCacheテストにlogin非表示を追加。配信Python2成功/既存Starlette警告1、diff --check成功。Ownership不変条件を確認し、判定/Owned projection/PG/schemaは変更なし。backend sourceは前回同一sourceの実PG検証を継承、今回PG全体実行と扱わない。
- vの実Profile（最終wと同一Profile実装）でme1/settings1/summary1/public Detail1/Chronicle1、Owned0/Formerly1/Claims4/Squier52を確認。avatar2/notifications2はまだ残り、除去済みと誤記しない。w実選択16→Back52で一覧51保持、各Detail+Chronicle新規読取、対象区間のlist/me0をログ確認。PC1440/390のDetail、狭幅横はみ出しなしを確認。
- ソート操作開始から3ページ目API応答完了までの個別測定: u13.338秒、v速い回2.506秒（DOM2.535秒）、v再測定17.571秒（実API latency1.5〜6.7秒）、w4.904秒（API単体0.47〜0.51秒）。全て3一覧page200/Detail保持。制御されたbenchmarkではなく、安定した速度改善の保証としない。通信待ちの整理を全体完了と誤認しない。
- v Build70735d55-f29b-478f-812e-df10ecabdacf成功後、w Build5e59d914-34a6-4ffe-b210-5a8f6311d1e4 SUCCESS。最終digest sha256:a1958bddd9cc4a30e594d95f2c44a4c68be0760849c868cb310c2dbe5d7bc6ac、ui-20261012w100%。227files、stage1に対しJS5点のみ。asset bytes一致/ready200、image/revision/client metadata以外のservice template保持。
- Normal実測後は今回開始時のOffline/「サービスはメンテナンスのため一時的に停止しています。しばらくしてから再度お試しください。」/Review OFFへ復元。SQL/Crawl/Jobs/IAM/env/所有権/Claim/profileに変更なし、Git未commit/push/merge。tab3/4handoff、viewport解除。
- outputs/performance-stage2-results.txt、measurements.json、各requests.json、catalog-pc.png、detail-mobile.png。**残る作業**: 行Favorite N+1/一覧全ページの逐次取得/補助Profile取得の重複、全ページ移動/静的assetsの再読込と共有state、backend connection/token認可/SQL処理時間。今回は通信整理のcheckpointで、元の第2段階にあったpersistent cross-page cache/SPA化や全体目標の完了を宣言しない。次は残る取得量/ページ遷移とbackend側を確認。元大項目③/Follow/Messagesは延期を維持。


## 40. パフォーマンス第2段階・行Favorite N+1の削減（2026-10-12）

- ユーザーの「進めて」で残作業を継続。変更はcloud-account-favorites.js/cloud-public-catalog.jsの2点。既存本人用list API（limit50）を同時に描画する全行の初期selectで共有。完了snapshotは保存しない。本人collectionが50超なら降順cursorで最後まで取得し、total一致/全件数/strict DTO/順序/cursor/重複を検証。部分取得からfalseを推測しない。大きいcollectionでは複数取得が必要、常に1通信とは保証しない。
- canonical account object/principal/active verified状態をread前後で確認。Favorite書込開始/終了のrevision変更・pending書込・identity変更は遅いsnapshotを拒否。行/Detailの既存observerとepochは保持。明示RefreshとDetailは個体GET、PUTは既存サーバー認可/強制token更新/no-store。私的永続cache/Storage/API/DB/schema追加なし。取得エラー時はheart disabledと再取得入口を維持。
- JS1005成功/失敗0。10件追加で全51heart利用可/ソート再取得なし、完全collectionの共有と次回fresh、exact BIGINT/false/複数page、不完全・重複・不正cursor・余分field・403拒否、identity/書込競合、初期snapshotと明示個体refreshの分離。従来queue3件テストは新共有とold-account消去へ更新。配信Python2成功/既存warning1、diff check成功。backend/SQLは不変、PG/Python全体を今回再実行したとは扱わない。
- Build904333c6-7b3f-4f49-89fa-8c7732f5fdea SUCCESS、227files/3.9MiB許可リスト。digest sha256:57de90ab5b1c22e8c6eb09941675921f8cc6a9449d27e1bb380c166818668acc、ui-20261012x100%。image/revision/client metadata以外のservice template一致、ready200/変更asset2点byte一致/no-store。先行static確認は誤った/static URLで404、正式/assetsで確認成功、配信不具合とは扱わない。
- 実ID1/Normalでw初期favorite GET52（行51+Detail1）→x2（本人collection1+Detail1）、全200をRun logで確認。x全51heart enabled/false、PC見出しクリックとkeyboardメーカー昇降順で一覧/Detail/全heart保持、favorite再取得0。狭幅ではDetail面が一覧面を覆うため先行見出しclickは無効、keyboard/PCでsortを確認。390幅overflowなし。本人favorite0のためライブpositive変更は行わず、positive・更新同期は合成テストで検証。所要時間の安定改善率を測定したとは扱わない。
- 終了時Offline/「サービスはメンテナンスのため一時的に停止しています。しばらくしてから再度お試しください。」/Review OFF復元。SQL/Crawl/Jobs/IAM/env/Claim/所有権/profile/favorite書込みなし（運用modeだけ一時Normal）。未commit/push/merge、viewport解除/tab3/4handoff。
- outputs/performance-stage2-favorites-results.txt、baseline/new-requests.json、favorites-pc.png。行Favorite取得集約は完了、段階②/全体完了は未宣言。残るページ共有state/全document・静的assets再読込、一覧の逐次page、補助Profile重複、backendconnection/token/SQLを次に進める。大項目③/Follow/Messagesは延期。


## 41. パフォーマンス段階②・取得と再利用の最適化完了（2026-10-12）

- checkpoint39/40の残りを完了。公開DTOの条件付きHTTP再利用、static ETag、一覧の残り2page単位の要求、Profile avatar/通知重複と隠れvisibility初期取得の除去、Profile行Favoriteも本人collectionの同時共有へ統一、Top初期/BFCache認証pending中の旧private表示とSignInを抑止。
- 公開成功JSONのみprivate/no-cache/max-age0/must-revalidate、staticのみpublic/no-cache/max-age0/must-revalidate。公開APIは毎回actor/service認可とDTO再計算後に本文SHA256で304を判定。private API/HTML/config/写真/errorはno-store。従来の「全API/assetがno-store」の記述はこの限定変更で置換。private永続cache/Storage/schemaなし。
- checkpoint39のcross-page reuseは標準HTTP cacheで実装。独自persistent cache/SPA化は採用せずMPAを維持。全document遷移/DOM再構築は残る。この選択とbackend待ち時間を全体最適化の完了と混同しない。
- Python全体2597成功/既存warning3、最終JS1020成功/失敗0（補助module1含む）、最終Formal配信Python4成功/既存warning1、diffcheck成功。隔離CloudBuild PostgreSQL18.6のpublic catalog1/1group成功（Build482f0d4e-eef8-426c-b4b2-83f4942cc0ae）、readonly role/DTO/検索page/insights/304/actor・mode拒否を確認。今回全17PG group実行とは扱わない。live DB破壊なし。
- 最終ab ID1実画面で51行/51heart、NewDiscovery51/地図177path、ProfileOwned0/Formerly1/Claims4/通知17/Detail52、戻る・進む直後の認証待ちとフォームhidden、復元後同じ会員を確認。Profile me/settings/summary/avatar/notifications各1、visibility0、Favorite collection1+Detail個体1。Top→Profile公開Detail/Chronicle304、static48件304。先行yの「静的40件」というcommentaryは全304件の混同であり、yはstatic38/全40、最終abはstatic48/全50。
- PCメーカーsort中も51行/全heart/Detail維持、降順完了。公開list3GET/Detail・Chronicle・photo0。残りpage要求を2単位にしたが、実serverログでは2/3page開始のoverlapを確認できず約0.5秒ずつのAPI待ちが残る。queue/認可/server原因を未計測のまま断定しない。unitでは逆順完了/epoch中断/不完全aggregate拒否を確認。単発観察ready時刻をロード時間と扱わない。390幅overflowなし。
- Build13068119-e8a7-4fdb-a5e9-a18921d400bd SUCCESS、227許可files、digest sha256:b8ce90fa69616245e65e0c76dd1a09e22049c920e2de56cd81217da098595255、ygc-staging-accounts-ui-20261012ab100%。9変更JS配信byte/ETag/header一致、ready200、service templateはimage/revision/client metadata以外一致。y中間検証、z未配信、aa中止未配信。
- 元Offline/日本語message「サービスはメンテナンスのため一時的に停止しています。しばらくしてから再度お試しください。」/ReviewOFF復元。以前のcached ETagでも公開6APIは403/no-store/ETagなし、会員画面の行/Detail/新着/統計/地図を破棄。SQL/Crawl/Jobs/IAM/Claim/所有権/profile/favorite書込なし（modeの一時変更のみ）。未commit/push/merge。tab3/4handoff、viewport解除。
- outputs/performance-stage2-complete-results.txt、complete-requests.json、events.json、pc/profile/offline画像。段階②の取得・再利用は完了、次は性能段階③backend接続/token認可/SQL/配信待ちの実測改善。全速度改善完了/SPA化済みとは言わない。元クローズドテスト大項目③/Follow/Messages未開始。


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
