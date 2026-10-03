# UIの構造

ページのDOM、共通部品、ページ固有の処理を分離する。フレームワークは追加せず、既存のHTMLとJavaScriptを使う。

| 層 | ファイル | 担当 |
| --- | --- | --- |
| ページ構造 | `static/*_html.html` | DOM、フォーム、アセットの読込。TopとProfileは同じテンプレート |
| ページ別処理・スタイル | `static/pages/{console,user-view,user-edit}.{js,css}` | API通信、権限に応じた操作、ページ状態、ページレイアウト |
| オーバーレイ管理 | `static/overlays.js` | 独自モーダル、Consoleのnative dialog、画像アルバムの開閉とフォーカス |
| 個体詳細 | `static/product-detail.js` | Specification・Chronicleの基本レイアウト、Claim順、ギャラリー、アルバム、アコーディオン |
| 共通部品CSS | `static/ui-components.css` | モーダル、画像アルバム、共通操作色、ボタン・入力欄。ダーク／ライトのCSS変数で指定 |
| テーマ | `static/themes.css` | テーマ色・背景・ブランド表示 |
| リスト操作 | `static/list-navigation.js` | 選択リストの上下移動、表示行数、日付入力の上限。オーバーレイ表示中は背景を操作しない |

## モーダルを追加・変更するとき

`YGCOverlays.open(elementOrId, options)` / `close(elementOrId)` を使い、各画面から直接 `classList` で開閉しない。フォームの初期値・送信・権限判定はページ側に置く。`options` には `opener`、`initialFocus`、`onClose` を指定できる。

- Escapeは最前面だけを閉じる。モバイルの背後のProduct Detailへ同じEscapeを伝えない。
- モーダル外側のクリックは最前面だけを閉じる。内容領域内のクリックでは閉じない。確認モーダルではキャンセル扱いとなる。閉じても送信済みのサーバー処理は中止しない。
- Tab / Shift+Tabとプログラムによるフォーカス移動を表示中のダイアログ内に限定する。
- 開く前のフォーカスとbodyのoverflowを保持し、最後のモーダルを閉じたときに復帰する。
- 重ねて開いたモーダルの親を閉じる場合は子も閉じる。個別の後処理は`onClose`へ置く。
- ダイアログには見出しに対応する`aria-labelledby`または`aria-label`を付ける。未指定の場合は見出しからラベルを補う。
- フォームの業務処理や所有者の判定権限を共通モーダル管理に持ち込まない。

Console用トークンの埋込みだけは従来どおりサーバー生成HTML内に置く。公開されるページJSにはトークン値を埋め込まない。`/assets/pages/{filename}` は6ファイルだけを許可し、パッケージ設定にも含める。

## 検証

既存のJavaScriptテストは `app/tests/page_source.cjs` でページ固有アセットを読み込み、表示・操作の回帰を確認する。Pythonテストはアセットの配信と許可リストも確認する。

`app/tests/browser_ui_components.py` は明示実行するPlaywrightテスト。実行先はuser ID 1と画像付きindividual ID 1のある検証専用サーバーを使う。既存レコードは変更しない。`YGC_BROWSER_URL`、`YGC_BROWSER_EXECUTABLE` で接続先とChromium実行ファイルを指定できる。フォーカス、Tab移動、重ね合わせ、Escape、スクロール復帰、モバイルのアルバム、native dialogを検証する。

## 残る整理

ヘッダー・アカウント操作、フォーム送信と画像検証、フォーム固有のレイアウトにはページ間の重複が残る。今回の分離によって共通化が全て完了したわけではない。権限や送信先の違いを維持し、操作上の共通部分を順次抽出する。

## 共通配色とレイアウト

操作部品はテーマのサブウィンドウの明暗に合わせたダーク／ライトの共通配色を使う。ボタンの役割は`data-ui-action`（primary / close / neutral / danger）で指定する。テーマ追加時は共通パレットも選択する。詳細は [USER_THEMES.md](USER_THEMES.md)。

- Notificationsは共通モーダル。確認済みの行はモーダル背景色、未確認は別の面色と左線で区別する。
- User ProfileのOwnership RequestsとヘッダーのCheck Requestsボタンは削除済み。申請の詳細は重要情報領域・通常通知・管理画面から開く。
- Unanswered RequestsはTop Page / Profileの先頭。コンパクトな青緑背景・白太字・明るいミント色の枠を全テーマで共用する。
- 追加を促す所有申請・Claim追加・新規ギター追加の操作には二重線の共通枠を付ける。
- Product Detail内の所有申請・Claim追加ボタンとClaimカードは同幅・同位置とし、左右の余白を揃える。
- Top PageのStatisticsはModel Distributionから始める。デスクトップのページ内リンク移動では、そのカード上端を固定Product Detail上端に合わせる。
- `data-count-items`付きの一覧見出しには、表示中の行数を小さな`N items`として下端を揃えて表示する。空状態の行は数えない。
- 画像アルバムは1枚でも中央の画像列を使用し、前後ボタン非表示時に画像が狭いナビゲーション列へ入らないようにする。

## 2026-10: viewport-based panel heights

- Top Page and User Profile guitar lists use their unfiltered item counts to determine content height, capped at Product Detail height (`100dvh - header height - 28px`) on widths above 900px. Filtering does not change the outer height. Resizing and toolbar changes trigger measurement; table rows currently use a single-line layout.
- New discovery → Product List spacing is 16px.
- User Chronicle grows naturally with its contents and uses the same desktop height cap, with internal scrolling. It currently has no filter. Compact layouts retain their independent sizing.
- Browser Console Product Detail and User Detail have viewport-based heights and internal scrolling, while remaining in the page grid. Backup and User DB actions sit in the left column above their lists. On desktop, each Detail starts level with the action panel and gains its height plus bottom margin, preserving its prior bottom position. The resulting desktop height can exceed the viewport; the enclosing page also scrolls. Compact layouts stack the columns without this extra height.

## Server Operations / Console scrolling

Browser ConsoleのOperationsは右Detail層にまとめ、上部にOperationsの状態・更新操作、その下にService status等のタブ、続いて選択中の詳細を表示する。稼働状況（DB、画像ディレクトリ、プロセス起動時間）、メンテナンス、プロセス内ジョブ、Acquire / Listing審議件数、設定変更履歴、アプリ版を表示する。外部サービスの接続・ワーカー稼働はこの表示だけでは保証しない。

幅901px以上ではConsole全体を左Main層と右Detail層に分け、それぞれ独立してスクロールする。Web Crawl、Guitar DB Management、User DB Managementはタイトルを含め左Main層に配置し、Operations・Product Detail・User Detailは右Detail層に配置する。ヘッダーは固定し、ページ全体のスクロールは使わない。ヘッダーのページ位置リンクはMain用とDetail用に分け、指定した層だけをスクロールする。狭い画面では上下に並ぶ独立したスクロール領域とする。

運用APIは既存のlocalhost Console管理トークンで保護する。`YGC_DATA_DIR/operations.sqlite`に設定と直近100件表示用の変更履歴を保存し、Chronicle DBのリセット・復元とは独立させる。メンテナンス設定更新はReason入力不要・version一致必須。操作履歴にはモード変更を自動記録する。通常／閲覧のみ／全面停止を選択でき、閲覧のみでは新規の変更HTTPリクエスト（管理操作・MCPも含む）を拒否する。全面停止では通常閲覧も拒否する。Console HTML・アセット・運用設定API・healthは復旧のため到達可能に保つ。拒否は503とRetry-Afterを返し、全面停止の通常ページには案内を表示する。受付済み処理・既存ジョブは完了まで継続する。CLI等のHTTP外操作は停止しない。

`/health/live`はWebプロセスの応答、`/health/ready`は読取専用のDB接続・必要テーブルの参照と全面停止でないことを確認する。外部監視・通知・バックアップ自動化・本番認証・GCP永続化は別途実装する。運用DBも本番移行時に共有永続ストアへ交換する。

Product DetailとUser Detailは選択状態にかかわらず表示領域相当の高さを保持し、内容は内部でスクロールする。User Detailの表示項目・編集項目は1行1項目とする。OwnershipにはRequest、Disputes、Authentication（GPT連携）をこの順で小項目として配置し、ヘッダーからはOwnershipへ移動する。

Ownership Requestの初期フィルタはIncomplete。写真待ち・審議待ち・審議中・処理エラーと、画像審議承認済みでもOwner承認待ち（Unverified）の申請を表示する。採否・Verificationが確定した申請、取消・終了・期限切れは含めない。

OwnershipのRequest／Disputesは共通のpanel・toolbar・table-wrapを使った7列の一覧とし、末尾のView request／View disputeボタンから詳細モーダルを開く。Requestの画像・管理操作・報告・履歴・審議指示はメインから除き、共通Overlay管理によるnative dialogへ移す。モーダルを閉じたら画像URLを解放し、未完了の詳細読み込み結果は反映しない。

## 仮登録とログアウト

Guest Top PageのCreate Accountは仮登録モーダルを開く。Identity Platformのメール／パスワード方式に合わせたEmail address・Passwordを入力できるが、入力値はサーバー送信・アプリ保存・形式／重複チェックの対象としない。Display Name（1〜120文字、ニックネーム・重複可）とTerms／Privacyへの個別同意を必須とする。文面はlocal-draft-2026-10-03のローカル試作用暫定版で、登録画面から閲覧できる。表示名と同意の版・サーバー日時をユーザーDBへ同一トランザクションで保存し、共通認証結果でログインしてTop Pageを表示する。既存ユーザーに同意を捏造しない。Browser Consoleのテストユーザー作成は別経路で同意を記録しない。キャンセル・登録完了で入力欄を消去する。登録中の重複送信を防ぐ。

ログイン後のTop Page／User Profile／User Settingsのヘッダーには「SignOut」を表示する。サーバーのローカルセッションを失効させ、操作ユーザーとタブ内認証情報を消去し、Guest Top Pageへ戻る。他タブの別セッションは維持する。

GuestのSign Inも仮フォームを開き、Email address／Passwordを任意入力できる。local_dummyでは入力値を送信・保存せず通す。フォーム最下部のTest userプルダウンで既存ユーザーを指定し、そのユーザーでログインする。既存ユーザーがいなければ登録を案内する。共通YGCAuthアダプターを通し、localId／idToken／expiresIn等を含む認証結果を正規化して保持する。詳細はGCP_BOUNDARIESの仮サインイン契約を参照。

## Desktop table column widths

`static/table-columns.js`をConsoleとTop／Profileで共有する。幅901px以上の単一見出し行・列結合のない表に、各見出し右端のドラッグハンドルを追加する。左右矢印キーでも10pxずつ変更できる。列幅は48〜4000pxで、初回操作後は固定幅のcolgroupを使い、表の横幅を列幅の合計にする。保存先はブラウザlocalStorageでページ・表・見出し別。列幅リセットボタンは表示しない。幅900px以下では保存値を保持したまま無効化する。カード一覧・結合見出しの診断マトリクスは対象外。サーバーへの同期は行わない。

Product／User Detailの固定高さは右Detail層の実際の表示領域をResizeObserverで測定して設定し、ヘッダー折返し・ウィンドウ変更による高さの差を吸収する。

ConsoleのMain内のリストは高さ上限（520pxまたは表示領域から操作欄分110pxを引いた高さ）を持ち、少数時は自然な高さ、多数時は表の内部スクロールとする。Main層の独立スクロールはセクション間の移動に使用する。

Main側のヘッダーリンクをクリックした時だけ対応Detailへもジャンプする：Web Crawl→Operations、Guitar DB／Ownership→Product Detail、User DB→User Detail。以後のスクロールは左右独立で、追従・固定しない。Detail側リンクとOwnership内の小項目リンクは対象層だけを移動する。

Request／DisputesのApplicant・Ownerは対応するUser Detail、GuitarはProduct Detailを開く。新規Listingの未登録個体やUnknown OwnerなどIDがない項目はリンクにしない。RequestにはOwner列を追加する。User選択による既選択Productの更新は右層をProductへ移動させない。

OperationsのBackground jobsにはCrawl見出し、ReverbのAuto Crawlチェックボックス、その下にReverb最終開始日時を表示する。既定OFF、対象はElectric + Acoustic Guitarsの両方。ON時のIncremental Crawl製造年条件を保存し、Web CrawlのAuto Crawl interval (hours)で指定した間隔（1〜168時間、初期1時間）ごとに1ステップ進める。Save intervalで保存する。ON操作・間隔変更後は指定間隔後から実行。設定はoperations.sqliteに保持する。Webプロセスのlifespanでローカルスケジューラを起動し、ブラウザ閉鎖後も継続する。OFF・メンテナンスは新規実行を止め、実行中処理は完了する。手動ジョブと同じロックで重複開始を防止する。ブラウザから渡されたトークンはプロセスのメモリのみで保持し、再起動後は環境変数REVERB_API_TOKENがなければ再ON操作を待つ。クラウドの複数プロセス運用はGCP Jobs／Schedulerへの移行が必要。

Acquire / Listing reviewにはChatGPTのチェックボックスとLast answerを表示する。初期ONで従来の審議動作を維持し、OFFは正式Acquire／Listingのpending MCPによる新規lease取得を停止する。OFF中も画像参照・回答提出は受け付けるが、審査中の申請・Claim・所有状態は更新しない。回答・失敗報告・画像観察はoperations.sqliteのpaused_review_answersに別保存し、処理中leaseの時間切れ更新もOFF中は停止する。ONに戻しても保留回答は自動適用せず、通常の審議再開で扱う。スイッチ自体はChatGPTの外部スケジュールを作成・削除しない。設定はoperations.sqliteへ保存。最終回答時間は受理済みGPT回答の専用イベント（既存データはAI result.completed_at）から取得し、管理者判断・取消の時間を含めない。

Operationsの現在モードは24pxの太字で表示し、確認日時は別の小さい行に表示する。Maintenanceはモード変更時に対応する定型メッセージを入力欄に設定する（編集可能）。保存済みメッセージがある場合、フォーム初期表示ではそれを使用する。Crawl backupsの一覧閲覧・保持数保存は通常モードでも可能。復元のみメンテナンス必須。

## Browser Consoleの操作整理（2026-10-03）

Web CrawlのRegistered Guitars／Serial Listings／Repeated指標とRestart Scanボタンを削除。通常操作はCrawl NowとAuto Crawl設定、例外的なクエリ入力はManual Crawlボタンからモーダルを開く。モーダルを閉じても実行中処理は継続する。進捗と結果はCrawl Run Logに集約し、分野・製造年に依存せず全体の最新20回を表示する。Manual Crawl、詳細キャッシュ再処理、既存Listingのbackfillも永続ログへ記録する。各行は簡潔な集計と折り畳みDetailsで構成し、旧ログも表示する。

Guitar DB ManagementのメインにはBackups、DB Maintenance、StatisticsのボタンとProduct Listを置く。Backupsモーダルにファイルの保存／復元、Crawl前バックアップの世代数・保存済み一覧・復元をまとめる。DB MaintenanceモーダルにはClaim Migration、Listing backfill、重複ギターの確認、Specificationの修正、保存済み詳細の再処理、確認待ち候補、Reset DBをまとめる。Statisticsはモーダル内だけに表示する。

Unverified Acquireの独立リストはGuitar DBから外す。Ownership Requestは申請記録付きAcquire／Listingのみを扱い、Automation／旧Claimを網羅しないため、OwnershipのOther Pending Acquire Claimsボタンから申請記録のない未承認Claimをモーダルで確認できるようにする。Requestと紐付いたClaimはこの補助一覧から除く。行の選択でモーダルを閉じ、右のProduct Detailへ移る。所有権の評価・通常／管理者Verificationの規則は既存のまま。左右の独立スクロールを維持する。

## Backupsの一元管理（2026-10-03）

BackupsモーダルでGuitar / Chronicle（ギター・Claim・正式申請・係争・Crawl記録とコンテンツ画像）、User Accounts（プロフィール・固定ID・認証対応・Follow・DM・アバター）、Operations（設定・運用履歴）、Authentication実験（キュー・画像・審議結果）を選択する。分離モードではChronicle復元時に現在のユーザーDBを反映し、新規ユーザー・BAN・プロフィール・アバター・Follow・DMを維持する。互換prototypeでは従来Chronicle全体の保存／復元を維持する。Authentication画像はqueue.sqlite3内のJSONに含まれる。Save backup nowは選択対象をサーバー内へ保存し、一覧からDownload／Restoreできる。Restore from fileも選択対象のみを復元する。

対象ごとに定期保存ON／OFF・1〜168時間の間隔・1〜100世代を保存する。初期はOFF、24時間間隔、10世代（既存Chronicleの保持数を引き継ぐ）。ON／間隔変更時は指定間隔後に実行する。ブラウザを閉じてもWebプロセス稼働中は継続する。停止中の期限超過は再起動後に1回実行する。Crawl・backfill等または保存・復元中の場合は待つ。複数Cloud Runインスタンスでの実行はScheduler／Jobs移行が必要。

一覧には手動・定期・Crawl前・復元前の保存理由と日時を表示し、最終保存の成功／失敗と次回予定も表示する。Chronicleの保持数は全理由で共通。Operations／Authenticationは独立して保持する。Crawl前はChronicleだけを保存する。既存Crawl ZIPも引き続き利用可能。

復元は管理トークン・メンテナンス・実行中ジョブなしが必須。対象の現在状態がある場合は復元前に保存する。Chronicle復元は既存のDB／media検証・失敗時ロールバックを使う。補助DBはターゲット付きZIPとSQLite整合性を検証し、SQLite backup APIで対象のみ置き換える。Operations復元は現メンテナンス・メッセージ・バックアップポリシーを保持し、Auto Crawl／GPT審議をOFFにする。Authentication復元は接続キーを失効し、処理中leaseを破棄してpendingへ戻す。保存先は既存YGC_DATA_DIR/crawl_backups。512 MB上限と非公開ファイル権限を適用する。

## 申請一覧

User ProfileのOwnership RequestsボタンとヘッダーのCheck Requestsボタンは表示しない。一覧はdraft／pending／processing／errorと、acceptedでもVerificationがunverifiedのOwner承認待ちだけを表示する。確定済み・取消・終了・期限切れは表示せず、該当なしはNo incomplete requestsと表示する。管理画面の全履歴や通知からの個別結果閲覧は維持する。

Create AccountでもAccount Typeを選択できる（User／Shop／Builder／Repairer／Organization）。Userが初期選択で、登録時に選択値をユーザーDBへ保存する。

User SettingsではDisplay Nameのみ必須。User IDは自動・変更不可、Account TypeはUserが初期値。UserName、未実装のEmail編集・Preferred Language欄は削除する。メールは将来の認証管理に属し、現在のUI言語はEnglish、Themeは既存初期値を使う。その他のプロフィール項目・公開範囲は任意。

## 重要情報表示領域

Top Page／User Profileのメイン先頭に青緑色の重要情報領域を置く。表題・小見出しは表示せず、種類・対象・状態・操作ボタンを各案件の1行にまとめる。狭い画面では折り返す。子項目がすべて非表示なら領域自体を非表示にする。対象は操作ユーザーで、閲覧中プロフィールのユーザーではない。

- 受信Acquire／Transferと未決着の係争・Owner応答待ちは既存の対応・詳細ボタンを維持する。Owner拒否済みのAcquireの異議申立て案内はこの領域に出さず、既存のDisputesモーダルから操作する。
- 自分のAcquire／Listingは写真提出待ち・審査待ち・審査中・Owner承認待ち・再試行可能なエラーのみ表示する。写真提出期限と、残り1時間未満の案内を同じ行に表示する。
- 確定したAcquire／Listing・解決済みDisputeは未確認でも重要情報には表示しない。申請履歴・通常通知の既読状態は変更しない。
- 送信Transferは受領待ちの間のみ表示。確定結果は従来の通常通知欄で確認する。
- サーバー状態は公開`/api/service-notice`でGuestにも表示する。normalならMessageがあっても非表示。read_only／offline中は他の案件・アカウント案内を隠してサーバー情報だけ表示する。状態とメッセージを改行で分け、メッセージ内の改行も保持する。normalに戻れば未決着案件を再表示する。offline中もこのAPIは利用可能だが、新規ページアクセスは従来の503メンテナンスページを維持する。
- セッション失効／利用不可は同じ領域で再サインインを案内する。Silent BANは既存設計に合わせて開示しない。再認証成功・ログアウトで案内を消去する。

30秒間隔・タブ再表示・申請操作で更新する。通信失敗時に既知の進行状況を消さない。一般のDM／フォロー通知は追加しない。メール確認未完了の案内はIdentity Platform導入時に接続する（現在のダミー認証にはメール確認状態がない）。

ヘッダーのCheck Requestsとユーザー名横のYou表示は削除し、ログアウトボタンはSignOut表記。Acquire RequestのRefleshボタンは表示しない（Listingフォームは維持）。重要情報はTop Pageと自分のUser Profileに限定し、他ユーザーのUser Profileではメンテナンス情報を含めて表示しない。Guestの初期テーマはSunburst & White（sunburst_3ply）とする。

## 壁紙の木目とレリック

Butterscotch & Black／Cherry Red & Blackは既存壁紙レイヤーだけをCSSで90度回転し、木目を縦方向にする。Black & Pearlは保存済みテーマID `black_pearl`を維持し、表示名をユーザー指定の`Rellic Black & Pearl`に変更する。新しい壁紙は`static/rellic-black-wood.webp`。参考画像の黒塗装が大きく剥がれた質感を内蔵image_genで生成し、WebPに変換して配置した。

生成プロンプト:

> Use case: photorealistic-natural. Asset type: website wallpaper texture. Generate one flat rectangular texture of heavily relic-worn BLACK guitar lacquer over natural brown ash wood, inspired by the attached black Strat-style guitar reference (NOT the golden wood texture image). Full-bleed texture only: no guitar silhouette, no neck, pickups, hardware, pickguard, borders, text, or watermark. Straight-on macro surface, evenly lit, matte black worn nitrocellulose finish with very large irregular chipped/abraded bare brown wood patches especially along both side edges and several smaller patches across the center; heavy scratches, tiny nicks, authentic jagged paint boundaries. Predominantly black, about 30-40 percent exposed warm brown wood. Exposed ash grain runs VERTICALLY. Natural age wear, not flames or decorative crackle. Landscape wallpaper around 1536x1024. Center somewhat darker for website panels but visibly heavily relic-worn throughout. Save generated output and return its local file path for integration into this repository.

Butterscotchの壁紙は1672×941pxの元画像倍率、Cherryは1254×705.75px、Rellic Blackは1152×768px（後者2つは元画像の75%）で表示する。画面の縦横比による非等方な引き伸ばしを避け、広い画面では背景を繰り返して細部の密度を保つ。Sunburst & White自体の絵柄は変更しない。

## UI language resources (2026-10-03)

- English remains the default; Japanese is available as an automatically generated draft. Top Page, User Profile, User Settings and Browser Console have one header language selector, independent of authentication and account type. The selection uses browser-local `ygc_ui_language`; the browser's preferred language does not change the default English UI. On narrow screens the selector precedes the horizontally scrolling position links.
- `static/locales/manifest.json` defines the default language and available BCP 47 codes, native labels and `ltr` / `rtl` directions. Add a `<code>.json` dictionary and a manifest entry to enable another language. Missing translations fall back to English. The selector waits for initial page loading to finish. A switch reloads the page so page-owned charts, menus and dialogs use the selected dictionary too; cancelled requests during that navigation do not clear the tab login. Save open forms before switching.
- `/assets/i18n.js` bundles registered dictionaries with the shared `YGCI18n` runtime. There is no separate fetch race before page renderers run. Locale JSON files are included in the installed Python package.
- Static UI text uses `data-i18n`; placeholder, accessible label, title and image alternative text use the corresponding `data-i18n-*` attributes. Nested labels keep their input elements. Dynamic renderers use `t(key, parameters, fallback)` for text and `html(...)` for escaped HTML text. Translation strings are plain text, never HTML or executable handlers. Keys remain stable when English wording changes; existing `ui.*` keys have a descriptive stem plus a disambiguating suffix.
- Parameterized messages allow translators to reorder values. Plural entries use `Intl.PluralRules`; number/date formatting uses the selected locale. ISO dates for form inputs and protocol values keep their existing formats. List count wording preserves the current English display, including `1 items`.
- User display names, guitar names, Claims, Evidence, descriptions, operator-authored maintenance messages, stored activity messages, raw logs and AI output retain their authored content. DB/API identifiers and authorization values are separate from translated labels. In particular visibility option values (`Public`, `Members`, `Followers`, `Private`) and connection directions (`followers`, `following`) are never translated.
- Known API errors keep their existing status, headers and `detail`, adding `message_key` for localization. `error-keys.json` also maps known diagnostics returned directly by middleware; unmapped external/dynamic diagnostics retain their original detail. New user-facing API errors should register a stable key and use `message_params` when values are needed. Framework validation diagnostics remain raw unless a dedicated application message is provided.
- Existing Japanese diagnostic wording in the local Console remains unchanged in the base dictionary; this change adds localization infrastructure, not a new translation or an editorial rewrite of existing diagnostic text.

### 日本語辞書の編集

- `app/src/ygc/static/locales/ja.json` は英語辞書を元にした自動翻訳の初稿です。人による確認・修正を前提とし、自動的に再生成して上書きする処理はありません。
- 左側のキーは変更せず、右側の日本語だけを書き換えてください。例：`"header.notifications": "通知"`。英語は `en.json` で同じキーを確認できます。
- `{count}`、`{time}`、`{formattedCount}` などの差し込み名は維持してください。複数形の項目は `one` / `other` の構造を残し、日本語の文言を修正します。改行は `\n`、引用符はJSONの規則で記述します。HTMLタグは入れません。
- 保存後にページを再読み込みすると修正を反映します。ヘッダーの「日本語」で切り替え、Englishへ戻すこともできます。プロフィールなどの保存内容は翻訳しません。
- ClaimとObservationはYGC内の固有概念として名称を残しています。Acquireは「取得」、Transferは「譲渡」、Disputeは「係争」、Positive / Negative / Unverifiedは「肯定 / 否定 / 未検証」を初稿の基本用語としています。
