# Cloud 通知Inbox

2026-10-07。PR59統合済みmainを基点とする、認証済み本人のアプリ内通知。公開・配置と実データの変更は別承認。

## 範囲と既存の意味

- アカウント画面で本人宛ての通知一覧、未読件数、ページ送り、個別既読、全件既読を扱う。既存の`notifications`テーブルを使い、メール・push・定期送信や通知ポリシーは追加しない。
- Claim追加、Acquire審議、Transfer申請／結果、所有権Decline等の既存保存内容を表示する。旧通知を再生成したり、推測で送付先を変更したりしない。
- Cloudの通常Owner Verificationにも、ローカルと同じ`claim_verified`作者通知を追加する。Claim判定、Observation再評価、既存のDecline記録、新しい通知は同じfenced Chronicle transactionで確定し、途中失敗は全部rollbackする。
- 通知保存は明示的な`INSERT ... RETURNING id`を使い、PostgreSQL adapterに存在しない`lastrowid`へ依存しない。
- 判定revisionは既存の完全なClaim内容に加え、最新のVerification通知IDにも結び付ける。同じ時刻・同じstanceの応答でも確認を消費し、同じ古い確認の再送で通知を重複しない。Former Ownerの連動ペアは双方の確認を失効させる。既読操作では判定revisionを変更しない。

## 認可と表示

通知のrecipientは、検証済みBearerとAccounts正本からサーバーが決める。URL、query、JSONの利用者IDを受け付けない。他人宛ての通知IDを知っていても読む／既読にすることはできない。

actorのBAN・Silent BAN、Claimの非active、Claim作者のBAN・Silent BANによる除外は、ローカル通知一覧と同じ規則を使う。一覧・件数・既読対象で同じ可視条件を使う。関係するアカウントの正本とChronicle投影を確認し、未同期や不一致を表示で迂回しない。プロフィールや画像の新しい公開範囲は作らない。

IDと件数は十進文字列。レスポンスは固定のallowlistで、本文はプレーンテキストとして表示する。保存内容や通信応答にも形・長さの上限を適用する。レスポンスはprivate / no-storeとAuthorizationのVaryを持つ。未知／重複パラメーター、ID範囲外、余分なJSONキー、過大・圧縮本文、cross-site書込等を拒否する。

Read Onlyでは一覧と件数の閲覧だけを許す。書込は既存のAccounts、Operationsモード、保守・Crawl排他の内側で処理する。Offline／Admin Onlyも既存のユーザー権限規則に従う。

## API

- `GET /api/auth/notifications`：本人宛て一覧、未読件数、書込可否。`after` / `limit`のID cursorで新しいIDからページ送りする。既定25、最大50件。
- `GET /api/auth/notifications/unread-count`：同じ可視条件の未読件数と書込可否。
- `POST /api/auth/notifications/{id}/read`：空JSON `{}`だけを受け付け、本人の可視通知を既読にする。
- `POST /api/auth/notifications/read-all`：空JSON `{}`だけを受け付け、本人の可視未読通知を既読にする。

一覧は通知本文・型・日時・既読状態・最小actor表示・型付きの画面移動hintだけを返す。通知行全体、recipient ID、Account内部情報、自由なURL、Claim本文、Evidence、画像参照は返さない。表示可能な通知が大量にあっても、履歴総件数の任意上限で一覧や未読件数を切り捨てない。

## 通知と現在の操作権限

通知は過去の出来事であり、現在の閲覧・判定権限ではない。対応済みのOwner審議やTransfer画面を開く場合も、その画面のAPIで現在の権限と状態を取得する。Ownerが移った、対象が無効になった、Transferが既に終了した等の古い通知で以前の操作を復活させない。Cloud未接続の係争画面等へはリンクしない。

通知を読んだり既読にしても、TransferのAccept／Decline、所有権Declineのacknowledgement、Claim承認、係争開始／解決を実行しない。既読更新は`is_read`と`read_at`だけ。最初の既読時刻は繰返しや全件既読で上書きせず、Transfer終了による既読化でも保持する。

SignOut・アカウント切替時は一覧と件数を直ちに破棄する。遅れて返った旧アカウント／旧ページの応答で復活させない。既読POSTの結果が不明なら自動再送せず、最新状態を読み直して確認する。閉じる、戻る／進む、画面遷移はサーバーで確定済みの処理を取り消さない。

## 検証・受入

SQLite／HTTPとNodeの合成試験に加え、使い捨てPostgreSQLの実transactionと実Chromium用の受入を登録する。recipient隔離、BAN・投影不整合、同一可視条件、BIGINT、ページ送り、読込競合、最初の既読時刻、Service Mode、保守排他、Owner通知のatomicity／同時応答／再送／rollback、過去の通知と現在権限の分離を確認する。

このCloudでは以前に拒否されたPostgreSQL導入やChromium起動を再試行しない。Macまたは通常CIで同一checkpointの実PostgreSQLとChromiumを含む総合検証を行う。実データの所有審議E2E、係争workflow、公開写真、公開Profile／Favorites／Followは別ゲート。詳細は[適用・検証の引き継ぎ](../history/CLOUD_NOTIFICATIONS_HANDOFF_2026-10-07.md)。
