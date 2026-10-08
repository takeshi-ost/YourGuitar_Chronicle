# Cloud Follow・会員アイコン

2026-10-08、main `c7007c7` 基準の `feat/cloud-follow-foundation`。
会員API・検索・ユーザーページ・関係一覧・保存済みアイコンの配信まで接続済み。
ユーザーが04:02 UTCに承認したアイコン公開範囲を実装している。
この文書は実装・検証時点の記録。リリース状態は対応PRと配置記録で管理する。

## 画面と公開範囲

- 確認済みメールを持つ有効な会員は、他会員のFollowing／Followers人数・一覧を閲覧できる。
- `/members` は表示名の部分一致検索。メール・UUIDでは検索しない。
- 検索結果・関係一覧は表示名とアイコンだけ。内部IDはリンクとページングに使い、人物ラベルにはしない。同名の会員も別の対象に遷移する。
- 項目から `/members/{id}` へ遷移する。Follow／Unfollowは相手ページだけに置き、本人には表示しない。
- 検索は1ページ25件。関係一覧の追加読み込み、履歴移動、モーダル終了、日本語／英語、390px幅に対応する。
- Guestには会員データ・画像を返さず、画面ではサインインを案内する。

| 保存済みアイコン設定 | 今回の閲覧許可 |
| --- | --- |
| Public / Members | 有効なログイン会員 |
| Followers | 閲覧者が対象本人をフォローしている場合 |
| Private | 本人のみ |
| 未知・未設定の公開設定 | 本人以外には配信しない |

本人は設定に関係なく自分の画像を取得できる。画像未設定・権限なし・取得失敗は標準アイコン。
PublicもGuest配信は含めない。他のプロフィール項目、私的Evidence、所有ギター、DM、通知の公開範囲は広げない。
既存の公開設定画面は、アイコンだけ今回の設定が有効になることを日本語・英語で説明するよう更新した。

## HTTP・保存形式・キャッシュ境界

| Method | Path | 用途 |
| --- | --- | --- |
| GET | `/api/auth/members?q=...&after=...&limit=25` | 表示名検索 |
| GET | `/api/auth/members/{id}` | 名前・本人判定・関係状態・人数 |
| GET | `/api/auth/members/{id}/connections/{followers,following}` | 関係一覧 |
| PUT | `/api/auth/members/{id}/following` | following真偽値による登録／解除 |
| GET | `/api/auth/members/{id}/avatar` | 認証・認可したJPEGバイト列 |

既存Identity verifierとAccounts正本から本人UUIDを解決し、毎回会員状態とサービスモードを確認する。
クライアント指定actor、query token、Cookieだけの認証、画像の公開URL・署名URLは使わない。
重複ヘッダー／JSONキー、余分な項目、不正ID・ページング、サイズ超過、cross-origin更新を拒否する。
応答はprivate/no-store・Vary Authorization・nosniff・Cross-Origin-Resource-Policy: same-origin。
画像APIはETag・304・リダイレクトを使わず、同じURLでも毎回現在の認可を検証する。
リストの `icon: null` は標準代替を表し、画像の有無やストレージ参照をDTOへ露出しない。UIはIDから固定APIを認証付きで取得する。

保存は既存CloudAvatarの正規化済みJPEGと `gcs-avatar-v1:` 参照を再利用する。
Accounts scope・オブジェクト世代・サイズ・MIMEを検証する既存CloudStorage.getを使い、バケットは非公開のまま。
旧ローカルパス・外部URL・壊れた参照を任意ファイル／URLとして解決しない。これらは標準アイコンへフォールバックする。
既存アップロード処理によるメタデータ除去・サイズ制限を維持し、今回再アップロードや移行は行わない。

画像取得中はAccounts本人・対象の共有ロックを保持し、Followersの場合は該当関係行もロックする。
これにより画像取得の途中で認可条件だけが更新される競合を防ぐ。取得完了後に確定した解除・設定変更は次の取得を拒否する。
管理者によるPrivate画像の迂回閲覧は追加しない。

## 画面上の失効

- Bearer付きfetchで取得した画像だけを短命のblob URLにして表示する。token／storage URLをimg.srcに置かない。
- Follow操作、画面移動、モーダル終了、SignOut、本人切替で該当画像を消去しURLをrevokeする。進行中の取得も中止し、遅い応答を破棄する。
- 同一originの別タブでの公開設定・画像変更は、個人情報を含まないBroadcastChannel通知で再確認する。不確実な更新結果でも古い表示を失効させる。
- ウィンドウが非アクティブ／ページが非表示になると画像を消し、復帰時に再認可する。表示中も30秒ごとに消去して再取得する。
- 別端末にすでに送った画像や閲覧者の保存物を遠隔消去する仕組みではない。別端末の変更は次回取得・画面復帰・表示中30秒ごとの確認で反映する。
- 画像取得は同時4件に制限する。失敗時は標準代替で、認可失敗を画像URL変更等で迂回しない。

## データ境界

自己Follow、不在・disabled・BAN・source対象は禁止。検索・人数・一覧でも無効会員を除外する。
Normal／Read Only／Admin Only／Offlineは既存user_read／user_writeに従い、Silent BANは既存方針を維持する。
Followは一方向・冪等。maintenance advisory lockとAccounts行ロックで、関係変更と監査を同一transactionにする。
変更のない再送は監査を増やさず、競合や不確実な更新を自動再送しない。
関係の更新先は既存account_user_followsとaccount_metadata。画像閲覧はread-only。
追加インフラ／schema／migration／runtime grant変更なし。Chronicle・所有権・Review・Crawlは変更しない。

## 検証と証跡

- Python: 認証、入力、固定DTO、画像HTTP・Cookie/Guest拒否、no-store、非リダイレクト。
- JavaScript: DTO、画像取得同時数、blob破棄、失効後の遅い応答、本人切替、非表示・再取得、MIME拒否。
- 実PostgreSQL: 既存制限付きruntime権限、一時DB、非個人生成画像を使用。全公開設定、Follow解除、実際の設定保存、役割・BAN・モード、HTTP境界、取得中ロック、旧参照拒否、schema/grant不変を検証。
- 自動ブラウザ: 本番HTML／JS／HTTP routesと架空SDK・会員を使用。実画像／標準代替、設定失効、画像の認証ヘッダー、検索・履歴・モーダル・本人切替・Guest・日本語・390pxを検証。
- Chrome拡張Browser Use: 127.0.0.1:8763の架空データを実操作。Public/Members、FollowersのFollow／解除、Privateの本人／別会員、同名検索での実画像・標準代替混在、390px、SignOut消去を目視確認。通常幅へ戻しQAタブを保持。

画像はすべて色付き図形で、実ユーザー写真は取得していない。外部Identity Platform・実DB・クラウド設定には接続していない。
作業ディレクトリの `follow-avatar-followers-allowed.jpg`、`follow-avatar-unfollow-denied.jpg`、
`follow-avatar-private-self.jpg`、`follow-avatar-private-other.jpg`、`follow-avatar-mobile-mixed.jpg`、`follow-avatar-guest.jpg` が目視証跡。
統一ログは `/tmp/ygc-follow-avatar-full.log`、単独ログは `/tmp/ygc-follow-avatar-postgres.log` と `/tmp/ygc-follow-avatar-browser.log`。

### 最終結果

- 統一runner: Python 2,420件、JavaScript 901件、全ブラウザ・全PostgreSQL検証成功。終了コード0、一時保存先削除済み。
- 追加機能単独: 関連Python 105件、関連JavaScript 88件、Follow/アイコンブラウザ、実PostgreSQL成功。
- PostgreSQLスキーマ生成物整合、git diff --check成功。
- Starlette等の非推奨警告と、一部既存ブラウザの終了時にPlaywright非同期Target closed例外がログにあるが、全runnerは最後まで成功。
- 追加インフラ・移行・権限変更の必要なし。実装・検証のブロッカーなし。
