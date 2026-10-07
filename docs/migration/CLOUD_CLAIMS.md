# Cloud Claim 投稿・編集

2026-10-07。公開 Product Detail から選択した個体について、認証済みの投稿者が Specification / Repair と Incident を管理する移植単位。後続の非公開Media投稿は[Cloud Media Claim](CLOUD_MEDIA_CLAIMS.md)に追加。実環境への配置・Service Mode 変更はこの実装とは別に承認する。

## 操作と境界

- 公開 Product Detail の Add Claim から `/account?claim={id}` へ進み、サインイン・登録・メール確認を跨いでも対象を保持する。ページを開く、認証を完了する、対象を選ぶだけでは Claim を作らない。
- メール確認済みの有効アカウントだけが投稿する。操作主体は Bearer の検証結果と Accounts 正本から決定し、入力のユーザーID・ロール・Verification は受け付けない。
- 自分が投稿した Specification / Repair / Incident / Media の内容、作成日・更新日、Verification、有効／無効状態を個体単位で確認する。ほかの投稿者の本文や非公開情報はこの一覧へ混ぜない。Inactive も自身の管理一覧では残す。
- Specification / Repair は最大50項目、項目名120文字・値500文字、本文2000文字。既存の任意項目と複数項目を欠落させず読み戻す。Incident は Damage / Lost / Theft と必須の本文2000文字。未来日付は既存のタイムゾーン規則で拒否する。
- Incident の編集は日付・本文のみ。種別は既存ローカル編集と同じく変更できない。Specification / Repair は専用編集経路で種別・項目・日付・本文を扱う。
- Listing、Identity Correction、Ownership、Event はこの汎用編集APIへ入れない。Mediaの新規投稿は専用multipart入口、日付・キャプション編集は同じ本人編集APIを使う。Listing の訂正は既存の専用 Identity Correction 経路が必要。Transfer / Release とその承認は別の移植単位。Inherit の新規作成は既に廃止されている。
- Deactivate は通常のソフト削除。復活、ハード削除、管理者による他人の編集は提供しない。

## 既存ルールと競合

Current Owner の新規 Claim は Positive、第三者は Unverified。現在値・所有状態・Owner の判定可能範囲は共通 Repository / Observation に委譲する。Owner は既存の Owned Guitars → Owner responses から他人の Claim を確認・判定し、自己判定は禁止する。Incident / Lost は所有権を Unknown にする Automation Ownership / Lost とは異なる。

投稿者の編集は、既存ローカル実装どおり Verification を維持する。つまり、Owner が一度 Positive にした第三者 Claim も、投稿者が内容を編集しただけでは Unverified に戻らない。更新日時を表示し、判定者は現在の全文を確認して再判定できる。この振る舞いを変更する再承認ポリシーは残る製品・安全上の検討事項であり、今回の移植で暗黙に変更しない。

編集・無効化は現在の revision を必要とする。状態・Verification・管理者判定・更新日時に加え、本文・日付・種別・作成者・全 Specification 項目を含む不透明な比較トークンで、同一時刻の項目編集も検出する。Owner responses も同じ内容結合を使い、編集後の古い判定確認を409で拒否する。Inactive は新しいトークンを送っても編集・再無効化できない。判定・作成者が変わる競合は現在のトランザクション内で再検査する。

Accounts 正本、投影の一致、個体に関係する参加者、Operations モードをロックし、Claim・項目・Observation 再評価・新規Claim通知を同じ Chronicle トランザクションで確定する。保守／Crawlロックが取れなければ409。SQLiteへのフォールバック、DB初期化、オンラインschema変更は行わない。

## API

- `GET /api/auth/guitars/{id}/claims?after=&limit=25`：自分の対象ClaimをID降順で返す。最大50件、`next_after`は文字列IDまたはnull。`individual`は既存公開基本項目だけ、`can_write`は現在のモード能力。非公開であり、`private, no-store` と `Vary: Authorization` を返す。
- `POST /api/auth/guitars/{id}/claims`：型ごとの全入力で作成し、`{claim: ...}` を返す。
- `PATCH /api/auth/guitars/{id}/claims/{claim}`：型ごとの全入力とrevisionで編集し、更新後のClaimを返す。
- `POST /api/auth/guitars/{id}/claims/{claim}/deactivate`：revisionだけを受け、無効化したClaimを返す。

公開対象ではなく自分の投稿履歴もない個体を、この入口のID列挙で発見できない。IDは正のBIGINT、JSONは文字列で扱う。未知／重複クエリ、重複JSONキー、型外の項目、過大リクエストを拒否する。認証はCookieを使わずBearer限定、書込はJSON限定とし、cross-siteのOrigin／Fetch Metadataも拒否する。失敗時にSQL・アカウント・保存参照を返さない。

- Normal：メール確認済みの有効ユーザーが読取・書込可能。
- Read Only：自分の一覧を読取可能。Adminを含め新規作成・編集・無効化は停止。
- Admin Only：正本がAdminのメール確認済みアカウントのみ許可。ほかの投稿者を編集できる権限は付かない。
- Offline：この一般ユーザー用入口はAdminを含め停止。

作成の通信結果が不明な場合は下書きを保持して通常の再保存を止め、自分の最新の提出一覧を確認してから明示的に再試行を選ぶ。自動再送しない。ネットワーク越しのExactly-once作成を保証する永続的な冪等キーは、この単位では追加していない。

## 公開情報・残る作業

PR54の公開投影を変更しない。承認済みの固定 Specification 項目だけが従来の公開対象。Incident本文・任意仕様ラベル・自由記述・投稿者・所在地・Evidence・画像・revisionは公開しない。写真の公開同意や非公開Evidenceの公開再利用は導入しない。

非公開Mediaの保存・配信は[後続単位](CLOUD_MEDIA_CLAIMS.md)に実装。公開写真の同意は未決定。残る後続単位は Event、Transfer / Release と受諾・係争の統合、Listing訂正の専用導線。所有権の移転・再取得・自己判定禁止・旧Ownerの権限喪失は別々に簡略化せず、既存の遷移例をまとめて移植する。

使い捨てSQLiteのサービス／HTTP検証、Node UI検証、使い捨てPostgreSQL／Chromiumスイートを用意した。クラウド仮想環境で拒否されているPostgreSQLサーバー・Chromium実行を迂回しない。実PG・ブラウザはMacまたは通常CIの同一checkpointで確認する。実データ・実認証・写真審議・Owner承認・Service Mode・Review設定・IAM・bucketは触らない。


Transfer / Releaseの認証済みWeb移植は[Cloud Transfer / Release](CLOUD_TRANSFER_RELEASE.md)に追加。受領・履歴・係争ロックを共有し、係争管理UIと公開・配置は別の作業範囲。
