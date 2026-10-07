# 公開ギターカタログ（実装 checkpoint）

2026-10-07。Cloud Run アプリに Guest 向けの読み取り専用 Top Page と Product Detail を実装した。公開開始・本番配置は別の承認段階。Reverb のデータ利用許諾は未解決であり、検証は架空のローカル fixture だけを使用する。本番を Normal に切り替える根拠にはしない。

## 画面と参加導線

- `/`：All Discovered Guitars。Maker・Model・Serial の文字列検索、新しい順／古い順／Maker／Model、24件ずつのページ送り。
- `/guitars/{id}`：基本情報、承認済みの固定 Specification、公開 Chronicle、適格な掲載元リンク。デスクトップは左右の一覧／詳細、幅900px以下は詳細へ切り替える。検索条件とページはURLに保持し、戻る／進むで復元する。
- Chronicle は記録IDの降順。発生日を表示するが、発生日順の再配列ではない。Positive は公開項目のカード、Unverified はタグ、Negative は点。後二者から本文・構造化内容・リンクを開くことはできない。
- 写真は常にプレースホルダー。既存の提出写真、審議根拠、代表画像、Cloud Storage参照から公開画像を生成しない。
- Acquire は `/account?acquire={id}` へ進む。サインイン／登録／メール確認を経ても対象を保持し、個体IDの手入力は廃止する。選択したギターを再確認してから利用者が明示的に下書きを作成する。ページを開く・ログインする・写真を選ぶだけでは申請を作成／提出しない。
- 元の `/account` と `/console` は継続する。ローカル試作の `/user-view`、公開プロフィール、Follow、DM、統計・地図、New Discovery はこの移植の対象外。後続の [本人専用 Favorite](CLOUD_PRIVATE_FAVORITES.md) は別の認証APIで扱い、公開一覧や他人の登録情報を公開APIに追加しない。

## 公開データ境界

公開APIとサービスの二重の固定項目投影を使用する。Adminが呼んでも公開APIの返却項目は増えない。

返す項目：

- 個体：文字列ID、manufacturer、model、finish、year、serial_number、`photo: null`。
- 現在Specification：承認済み・active・正常な作成者の `body`（ボディ材などの構造化仕様）、bridge、fingerboard、frets、neck、nut、pickups、pickguard、potentiometers、tuners、wiring、weight、finish。旧単一項目形式と `claim_spec_items` の双方を扱い、発生日（欠損時は作成日）・Claim ID順で最新を選ぶ。同一Claim・同一項目が両形式にある場合は構造化項目を優先する。
- Chronicle：Claim ID、既知の種類、既知のOwnership種別、発生日・作成日時、Verification状態。PositiveのListingには上記の個体基本項目、PositiveのSpecificationには固定仕様項目を付ける。
- 掲載元：PositiveのListingまたはAutomation Ownershipにある `marketplace_listing` 根拠のうち、`reverb` と一致する数値掲載IDおよびHTTPSの正規Reverb item URLだけを使用する。slugは削り `https://reverb.com/item/{id}` に正規化する。クエリ、fragment、認証情報、他ホスト、HTTP、内部保存参照は拒否する。外部への取得リクエストは行わない。

返さない項目：

- Current Owner／作成者の名前・ID・種別、所在地、プロフィール、非公開設定、アカウント情報。
- Claimの自由記述本文、所有者を格納し得る一般の `value_text`、任意仕様ラベル、編集revision、判定権限。
- 申請、チャレンジ、提出写真、AI診断、管理者審議、Evidence本文・JSON、保存パス、bucket名、署名URL、元画像。

Claimがあるだけでは公開を認めない。active・作成者の `ban_status=normal`・既知のClaim種類・既知のVerification状態の全条件を必須とする。Inactive／BAN／Silent BANは完全に除外する。適格なClaimがない個体は一覧に出さず詳細も404。Unverified／Negativeは最小限の種類・日付・状態だけで、内容や根拠は返さない。

自由記述の公開同意、プロフィールの公開範囲、代表写真の明示的な公開同意と配信・撤回のモデルは後続設計。今回、既存の私的Evidenceを自動で公開対象に変える同意フラグや公開bucketは設けない。

## APIと運用モード

- `GET /api/public/guitars?q=&sort=newest&page=1&limit=24`：検索120文字、pageは1〜1,000,000、limitは1〜50。ソートはnewest／oldest／maker／model固定。全ソートにIDの決定的な順序を含める。検索の `%`、`_`、`\\` はリテラルとして扱う。totalは検索後の件数を文字列で返す。
- `GET /api/public/guitars/{id}`：固定個体情報とSpecification。
- `GET /api/public/guitars/{id}/chronicle?after=&limit=25`：Claim ID降順のkeysetページ。`after`は直前ページの`next_after`を使う。

不明・重複クエリ、制御文字、範囲外ID、書込メソッドは拒否する。BIGINTはJSONで十進文字列として保持する。SQLはパラメーター化し、REPEATABLE READ／READ ONLY、実行5秒・ロック待ち2秒制限。ページ間の全体Snapshotは固定しないので、同時追加／削除後はRefreshで更新する。大量データ向けの索引最適化は実測後に検討する。

Operationsの`public_read`をDB読取全体に保持する：

- Normal：Guestと有効な利用者が閲覧可能。
- Read Only：閲覧可能。申請の作成・提出は従来の権限で停止。
- Admin Only：正規の有効なメール確認済みAdminだけが閲覧可能。
- Offline：公開APIはAdminも含め停止。Admin専用Consoleの読み取り入口は従来どおり。

Bearerを送らない場合だけGuestとして扱う。提示された無効トークン・停止アカウントはGuestへ降格して再試行しない。登録済みで未確認メールの一般利用者は公開情報だけ閲覧できる。登録未完了アカウントは登録の完了が必要。Adminロールのメール未確認は、Admin Onlyの例外を誤って得ないよう公開APIでも拒否する。

レスポンスは `private, no-store` と `Vary: Authorization`。故障時に生のSQL・認証情報・DB行を返さない。フロントも古い非同期応答・戻る／進む・対象変更・認証エラー時に以前の一覧／詳細を残さない。ブラウザ上の表示制限はサーバーのアクセス制御の代わりではない。

## 検証と残る承認

Python／Nodeの単体・既存回帰に加え、使い捨てPostgreSQLと実Chromiumの専用スイートを統一runnerへ追加した。PostgreSQLとChromiumは、この仮想環境での実行許可制約を回避して動かしていない。Macまたは通常CIで実行する。

本番データ、認証情報、審議の実行、Owner承認、Service Mode／Review設定、IAM、bucket、DBスキーマを変更していない。公開前には同じsource checkpointで実PG／ブラウザ、モバイル実表示、検索・履歴移動・認証を跨ぐAcquireを確認し、公開データ許諾・写真同意の範囲を別途決定する。
