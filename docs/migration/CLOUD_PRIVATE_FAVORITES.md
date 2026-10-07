# Cloud の本人専用 Favorite とプロフィール公開範囲の保存

2026-10-07 実装 checkpoint。公開・本番反映は別承認。既存の公開カタログより広い情報を公開しない。

## 利用範囲

- Favorite は認証済み・メール確認済みの本人だけが一覧、状態確認、追加、解除できる。別人の一覧、件数、ユーザーIDを指定する入口は設けない。
- `/account` に本人の Favorite 一覧と設定を置き、公開 Product Detail から本人の Favorite 操作へ進む。Favorite 一覧の個体リンクは既存の公開詳細へ戻る。
- Favorite の対象・一覧表示は [公開カタログ](CLOUD_PUBLIC_CATALOG.md) の `VISIBLE_GUITAR` に従う。適格な active Claim がなくなった個体は一覧と total の双方から除外する。非公開／存在しない対象の状態確認・追加は同一の404とする。
- 解除は正しい形式のIDに対する本人の行だけを削除し、存在・公開状態・他人の登録の有無によらず `favorite:false` を返す。これにより非公開化した保存行も安全に取り除ける。未知のIDの状態を調べる入口にはしない。
- 返す個体情報は文字列ID、manufacturer、model、finish、year、serial_number、`photo:null` の固定項目だけ。Owner、他人の個人情報、Claim本文、Evidence、写真、保存パス、bucketや署名URLを返さない。
- 既存の公開設定が Public でも Favorite は本人専用。他人のプロフィール、Follow、DM、公開画像配信を追加しない。

## API

すべて Bearer 認証の正規本人を使用する。ユーザー／操作主体の指定は受け付けない。

- `GET /api/auth/favorites?after=&limit=25`: 個体ID降順のkeysetページ。`limit` は1〜50、`after` は前の `next_after`。返却は `{items,total,next_after}`、totalとIDは十進文字列。
- `GET /api/auth/favorites/{individual}`: 公開対象の本人の登録状態 `{individual_id,favorite}`。
- `PUT /api/auth/favorites/{individual}`: 本文は厳密に `{favorite:boolean}`。明示した最終状態を保存するため繰り返しても反転しない。
- `GET /api/auth/profile/visibility`: 本人の `{profile_revision,fields}`。fieldsはbirth_visibility、residence_visibility、bio_visibility、avatar_visibilityだけ。
- `PUT /api/auth/profile/visibility`: 本文は `{revision,fields}`。四項目を Public / Members / Followers / Private のいずれかとして明示し、既存プロフィールと共有するrevisionによるCASで保存する。

未知／重複キー、重複・異常な認証ヘッダー、想定外のクエリ／本文、数値範囲外、過大なリクエストは拒否する。IDはPostgreSQL BIGINTの正数範囲。レスポンスは `private, no-store` と `Vary: Authorization`。エラーに生DB行・内部例外を含めない。

本人の状態はAccountsを正とし、アクティブ・BAN・source・停止状態を再確認する。FavoriteはChronicleの本人投影とのID／UUID／revision整合も確認し、未反映時に別人の行や古い権限を使わない。読み取りページ内の一覧とtotalは同じcontent fence内・同じ公開条件で取得する。ページ間の変更はRefreshで再取得する。

既存Operations gateを保持する。Normalは通常操作、Read Onlyは読取のみ、Admin Onlyは正規Adminのみ、OfflineはAdminも本人APIを使えない。更新は既存のmaintenance fenceと競合する。FavoriteはOwnership／Verification／Claim／通知を変更しない。

## 公開範囲設定は公開開始の同意ではない

Accounts001に四つの既存列があり、Accounts002の新規行既定値は次のとおり。

- birth_visibility / residence_visibility: Private
- bio_visibility / avatar_visibility: Public

既定値や移行済み値は公開への同意記録ではない。このcheckpointは既定値・既存値・ダミー由来データを自動で書き換えず、現在の公開範囲も拡張しない。Publicの保存済み値があるだけで写真やプロフィールを公開しない。

GETは未知のlegacy値を `null` として返す。生の未知文字列を公開せず、読取で修正もしない。設定画面は未選択とし、四項目の明示的な選択が揃うまで保存できない。保存による変更は利用者の操作に限る。

画面には「今後のプロフィール公開に向けた保存設定で、この版はプロフィールや私的な写真を公開しない」「Favoriteは本人だけに表示」を明記する。公開API、Followersの実アクセス制御、代表写真の公開同意・配信・撤回は将来の別設計。ローカル試作の表示制御をサーバーの認可に流用しない。

設定更新はAccountsの正規行に対して行い、既存projection_version、監査metadata、transactional outboxを同じトランザクションで更新する。Chronicleへの反映は既存の投影Jobで再試行できる。プロフィール内容の編集と競合した場合は409で再取得を求め、黙って上書きしない。

## 検証・運用上の境界

DB schema、migration checksum、IAM、権限grant、公開bucket、通知配信を変更しない。実装中のテストは架空の使い捨てデータに限定する。

Python・Nodeのaggregate、依存定義、PostgreSQL schema artifacts、パッチ再適用をcheckpointで確認する。実PostgreSQLとChromiumの新しい受入テストも統一runnerへ登録するが、このcloud環境では既知の実行制約を回避せず未実行とする。承認後のCIまたは別途承認したMac検証で、同じ最終ソースに対する実DB／実ブラウザの成功を確認してからリリースを判断する。
