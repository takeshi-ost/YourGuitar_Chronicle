# 現行機能と試作上の制約

対象は現在のローカル試作 (`feature/user-profile-top-page`)。UIとAPIの機能を分けて記載する。新機能を追加・削除するときは本書も更新する。実際の本人確認や公開サーバー運用の保証は [GCP_BOUNDARIES.md](GCP_BOUNDARIES.md) に記した通り未実装。

## Top PageとUser Profile

- `/user-view` はGuestも閲覧できるTop Page。Product Listの検索・ソート、Product Detail、Specification、Claim Chronicle、新着順のNew Discovery（最大200個体）、統計と地図を表示する。GuestはClaimや投票など参加操作を利用できない。
- Top Page、User Profile、Browser Consoleのクリック可能な一覧では、行をクリックした後に上下キーで同じ一覧の前後項目を選べる。入力欄やモーダルのキー操作は優先し、一覧以外をクリックすると解除する。
- ローカル操作用ユーザーはアカウント欄から選択する。本人の通知一覧、既読操作、プロフィール、Claim参加を使える。通知はアプリ内のみ。Messages、Sign In / Create Accountの実際の認証処理は未実装。
- `/users/{user_id}` のUser ProfileはUser Profile、Owned Guitars、Formerly Owned Guitars、Favorite Guitars、User Chronicleを表示する。リストはProduct List形式。Owned / Formerly Owned / Favoriteには表示高さの上限があり、超えた部分は枠内をスクロールする。所有・過去所有の個体はFavorite欄より前者を優先する。
- Product ListとProduct Detailの♡／♥からお気に入りを追加・解除し、DBに保存する。User ChronicleはUser / Social / Product / Claim / Otherのタグ付き時系列表示。プロフィールの初期Product Detailには本人が指定したSignature Guitarを使用する。
- Guestにはプロフィール画面でMembers onlyを表示する。これは現段階の画面上の挙動で、公開サーバー上での情報保護はまだ保証しない。
- User SettingsはDisplay Name、Account Type、Residence、Bio、Avatar、Signature Guitar、Themeと項目別公開範囲を保存する。Display NameとAccount TypeはPublic固定、UserName、Email、Date of Birth、Preferred Languageは表示用のダミー欄で保存されない。試作中は入力の必須制約を課さない。
- 項目別公開範囲はPublic / Members / Followers / Private。Followersはフォロー関係未実装のためPrivateと同じ表示範囲。選択した公開範囲はDBに保存するが、ブラウザ指定の閲覧者IDと一部直接API・画像URLの制約があるため機密情報のアクセス制御とは扱えない。
- 運営提供の13種類のテーマを設定できる。Top Page / Settingsには操作用ユーザー、User Profileにはプロフィールの持ち主のテーマを使う。管理用Browser Consoleはコンパクトな文字ヘッダー。詳細は [USER_THEMES.md](USER_THEMES.md)。

## IndividualとClaim

- 新しいギターを登録できる。手動登録も外部収集も、Listing Claimを起点とする同じ個体作成パイプラインを通る。個体の現在のMaker / Model / Finish / Year / Serial、Owner / LocationはClaimから作るSnapshotを表示する。
- OwnershipはAcquire / Transfer / Inherit / Releaseというタグを持つ一つのClaim種別。現時点ではAcquireがOwnerとLocationを設定し、Transfer / Inherit / ReleaseはOwnerとLocationを空欄に戻す。関係者への所有権移転を自動で確定する処理はない。
- Specification / Repair / Incident（Damage / Lost / Theft）/ Event（Exhibition / Performance / Recording / Auction / Other）/ Media（画像）Claimを追加できる。本人が現在Ownerなら本人のClaimをPositiveにし、第三者の対象ClaimはUnverifiedから開始する。OwnerはPositive / Negative / Unverifiedに変更できる。Identity CorrectionはListingの訂正入口から作り、重複を検査する。
- 元Ownerを主張するFormer Owner操作はAcquire / Releaseのペアを作り、Owner Verificationに従う。Claimの無効化は来歴を残すソフト削除。通常の表示とSnapshot評価から除外する。Listingは通常編集しない。
- ClaimにGood / Bad投票とResponseを記録できる。画像Media Claimは一つに最大10枚、JPEG / PNG / WebP / GIF、画像ごと最大12MB。ギャラリーに反映する条件はClaimの有効性と承認状態に従う。
- 所有権や個体照合に争いがある場合、現在値が履歴そのものを消すことはない。詳しい規則は [CLAIM_CENTERED_ARCHITECTURE.md](CLAIM_CENTERED_ARCHITECTURE.md)。

## Browser Console（ローカル管理）

- Web Crawl / Guitar DB Management / User DB Managementを固定ヘッダーから移動する。Product DetailとUser Detailはページとともにスクロールする。
- Batch CrawlとIncremental Crawl、保存済み詳細の再判定、進捗・実行ログ、Claim migration / backfill、DB統計、バックアップ・復元・初期化を操作する。
- 未承認Acquire欄は**承認するとCurrent Ownerが変わる可能性がある**Claimだけを列挙する。Repeated欄は**同じ正規化メーカーとシリアルを持つ複数のDB個体**の候補を表示し、残す個体を指定してMerge／Deleteする。
- ClaimのVerification強制変更・削除、アカウント情報とNormal / Silent BAN / BANの管理が可能。判定・管理操作を記録し、必要に応じて個体Snapshotを再構築する。管理権限は現時点でlocalhostとプロセス内トークンに限定。詳細は [console-claim-administration.md](console-claim-administration.md)。

## 未完成・サーバー移行前の要件

- Identity Platformへの接続、サーバー側の本人確認、全APIの認可、管理者ロール、実際のログイン・アカウント作成。
- SQLiteからPostgreSQLへの移植、複数インスタンス間のClaim更新とCrawlカーソル排他、画像の永続保存、トークンの安全な保管、再試行可能なジョブ実行。
- フォロー関係、ユーザー間メッセージ、日英UI切替、生年月日の保存・検証、定期自動クロール。収集の実データでの網羅性・誤照合検証も継続課題。
