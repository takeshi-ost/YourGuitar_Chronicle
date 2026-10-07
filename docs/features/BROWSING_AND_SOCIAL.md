# 閲覧・プロフィール・交流の機能仕様

対象：現行ローカル実装。操作手順は[ユーザーガイド](../user-guide/README.md)。以下は表示範囲・制限・更新規則を記す。

Cloud Run向けの読み取り専用Top／Product Detailは別の安全な投影として実装した。ローカルAPIやプロフィールの公開制約をそのまま移植せず、[公開カタログの範囲・固定項目・未公開条件](../migration/CLOUD_PUBLIC_CATALOG.md)を適用する。写真・自由記述・Owner個人情報は今回の公開対象外。実装checkpointは本番公開済みを意味しない。


Cloud の本人専用 Favorite と公開範囲設定の保存は、[専用の認証・非公開境界](../migration/CLOUD_PRIVATE_FAVORITES.md)に従う。Favorite は本人だけに表示し、既存の Public 設定を公開への同意と解釈しない。この段階では公開プロフィールや私的写真の公開を追加しない。実装checkpointと本番反映を区別する。

- `/user-view` はGuestも閲覧できるTop Page。All Discovered Guitars（旧Product List）の検索・ソート、Product Detail、Specification、Claim Chronicle、新着順のNew Discovery（最大200個体）、統計と地図を表示する。GuestはClaimや投票など参加操作を利用できない。
- 画面の操作ラベルは英語が既定で、日本語へ切り替えられる。Product DetailはTop Page / User Profile / Browser Consoleで共通の描画部品を使う。Top Page / User Profileでは幅900px以下で一覧から開閉可能なオーバーレイとして表示する。
- Top Page、User Profile、Browser Consoleのクリック可能な一覧では、行をクリックした後に上下キーで同じ一覧の前後項目を選べる。入力欄やモーダルのキー操作は優先し、一覧以外をクリックすると解除する。
- ローカル操作用ユーザーはアカウント欄から選択する。本人の通知一覧、既読操作、プロフィール、Claim参加を使える。通知は共通モーダルで表示し、確認済みの行はウィンドウと同じ背景にする。通知はアプリ内のみ。Sign In / Create Accountの実際の認証処理は未実装。
- `/users/{user_id}` のUser ProfileはUser Profile、Owned Guitars、Formerly Owned Guitars、Favorite Guitars、User Chronicleを表示する。リストはProduct List形式。Owned / Formerly Owned / Favoriteには表示高さの上限があり、超えた部分は枠内をスクロールする。所有・過去所有の個体はFavorite欄より前者を優先する。
- Product ListとProduct Detailの♡／♥からお気に入りを追加・解除し、DBに保存する。User ChronicleはUser / Social / Product / Claim / Otherのタグ付き時系列表示。プロフィールの初期Product Detailには本人が指定したSignature Guitarを使用する。
- User ProfileでClaimの追加・判定・投票を行うと、選択中のギターを維持してプロフィールの件数、Owned / Formerly Ownedなどの一覧、User Chronicleも再取得する。
- Guestにはプロフィール画面でMembers onlyを表示する。これは現段階の画面上の挙動で、公開サーバー上での情報保護はまだ保証しない。
- User SettingsはDisplay Name、Account Type、Date of Birth、Residence、Bio、Avatar、Signature Guitar、Themeと項目別公開範囲を保存する。Date of Birthは有効な過去・当日の日付を受け付け、公開範囲に従ってProfileとUser Chronicleへ表示する。Display NameとAccount TypeはPublic固定、旧UserName、Email、Preferred Languageの表示用ダミー欄は整理済み。言語選択はヘッダーからブラウザ単位で保持する。Save成功時とCancel操作時はProfileに戻る。ギター追加は本人ProfileのOwned Guitars直下から行う。
- New Discoveryは全体の新着200個体にFollow先のClaim追加・Good / Bad投票（直近最大200件）を混ぜて最新順に表示する。活動行は実行者名からUser ProfileへリンクしFollowingを表示する。Current OwnerをFollow判定の基準にはしない。
- テキストDM（1対1・1通2000文字まで）をUser Profileから開始し、TopPage / User ProfileヘッダーのMessagesで会話一覧・未読数・過去本文を確認できる。手動更新、既読管理、ページ付き読込に対応。FollowやClaim権限とは独立し、本人確認は引き続きローカル試作。
- Follow / Unfollow、Followers / Followingの人数とページ付き一覧をUser Profileに表示する。自己Follow、Guest、BAN・sourceユーザーの更新は禁止。所有権・Claim・Verificationには影響しない。設計と検証履歴は [SNS_IMPLEMENTATION_LOG.md](../history/SNS_IMPLEMENTATION_LOG.md)。
- 項目別公開範囲はPublic / Members / Followers / Private。Followersはプロフィール本人をFollowしている閲覧者に表示する。選択した公開範囲はDBに保存するが、ブラウザ指定の閲覧者IDと一部直接API・画像URLの制約があるため機密情報のアクセス制御とは扱えない。
- 運営提供の13種類のテーマを設定できる。Top Page / Settingsには操作用ユーザー、User Profileにはプロフィールの持ち主のテーマを使う。管理用Browser Consoleはコンパクトな文字ヘッダー。詳細は [USER_THEMES.md](../features/USER_THEMES.md)。


## 年式統計

Year DistributionはSnapshotの年式から`Circa`と`C.ha`を大文字小文字を区別せず除去し、前後空白を除いた値が4桁の数字だけの場合に集計する。同じ年は合算し、年の昇順で表示する。`1960-1962`などの範囲、年代、Unknownは集計しない。元の年式データは変更しない。
