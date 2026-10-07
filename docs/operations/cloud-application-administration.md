# Cloud Console: Ownership applications

実装基準: main `7e47c3fc921f1a76e8515aa037f5f5d080afbcdf`（PR #52）からの追加。
この文書は管理画面・APIの仕様であり、実サービスのReview ON、審議、採否、配置の実施記録ではない。

## 画面と閲覧範囲

`/console` のOwnership applicationsでListing / Acquireを検索し、状態・種別で絞り込み、履歴をページ送りできる。
申請者、対象ギター、Serial、申請状態、ClaimとVerification、試行回数、lease期限、Review OFF中に保留した回答の種類・受信時刻を表示する。
詳細は提出日・説明・Challenge、近接／全体／固定比較写真、AIの独立観察・診断JSON・レポート、管理採否とイベント履歴を分けて表示する。

確認済みIdentity Platform本人認証と、Accounts正本の有効なAdminを毎回必要とする。本人用申請APIの権限を拡張しない。
写真は認証付きバイナリ配信で、`private, no-store`・`nosniff`。Storageの参照・署名付きURL・lease tokenを画面へ渡さない。
履歴・JSON中のStorage参照は配信時だけ除外し、原本のAI観察や診断をDB内で書き換えない。ブラウザは写真をBlob URLとして保持し、終了・SignOut・別申請への移動時に破棄する。
写真参照が不正でも履歴の確認と取消／不採用の検討を妨げない。採用と再審議の確定前には必要な固定generation画像の取得・デコードを検証する。

一覧・詳細・写真のGETは申請失効・既読・キュー確保・保留回答反映を行わない。期限を過ぎた下書きは表示上expiredとなる。
管理用表示もCrawl／maintenance mutex・Accounts正本とChronicle投影を確認した一貫した読取とするため、処理中は409または投影待ちの応答になる場合がある。

## 理由付き管理操作

理由は前後の空白を除いた1～2,000文字。操作内容・理由・対象・表示時の状態versionを確認して送信する。
理由編集・対象変更時には確認をやり直す。Claim／Owner／AI観察／保留回答／管理履歴が進んだ古い画面からは確定できず、最新状態の確認が必要。

- 採用: 既存ルールでListingのIndividualとPositive Claim、またはAcquireを作成する。ユーザーOwnerがいるAcquireはUnverifiedとし、Ownerの承認を待つ。再採用では同じClaimを再使用する。
- 不採用: 未作成ならClaimを作らず終了。既存Claimがある場合はNegativeにしてObservationを再評価する。元のAI診断を保存したまま、管理者の採否と理由を別イベントとして追加する。
- 再審議: 写真提出済み・Claim未作成の対象をpendingへ戻す。旧診断・途中の独立観察・レポート・エラーをイベントへ保存し、旧leaseと試行回数をリセットする。審議担当を起動する操作ではない。
- 取消: 未決着の申請を停止し、旧leaseを失効させる。写真や申請記録を削除しない。

管理者IDは`identity-platform:<app_user_id>`として履歴へ記録する。理由は申請者への通知と本人の申請結果にも表示する。
申請・Claim・Evidence・Snapshot・通知・管理履歴は一つのChronicleトランザクションで確定し、一部だけ成功させない。
重複送信は古いversionとして拒否し、同じ操作からClaimや通知を二重作成しない。

申請採否とClaim Verificationの強制変更は別操作。後者は既存Guitar詳細のClaim管理を使う。
自己Claimの通常Owner判定禁止、譲渡後の判定権限移動、係争中の停止と係争決定済みClaimの保護を維持する。
不活性化・削除・Merge済みClaim、無効アカウント、変更された個体・比較元・登録仕様、重複Listingは採用時に再確認する。

## Review OFFと手動操作

Review ON/OFFは審議担当のキュー確保・画像取得・回答反映を制御する。
既存ローカル仕様と同じく、Adminが明示して確定する上記操作はReview OFF中も有効であり、採否は即時反映する。
確認画面でもこの違いを表示する。再審議はOFF中にはpendingのまま待つ。

全管理操作で古いleaseを失効させる。Operationsに保留したそのleaseの回答は、lease tokenを除いた診断内容を管理履歴へ保存してから保留領域から削除する。
Chronicleコミット後にOperationsの削除が失敗しても、古いleaseの回答で採否を上書きできない。
失敗応答で確定状態が不明な場合は再送前に再読込し、最新versionから再確認する。

## 一回限りの外部MCP審議

このConsoleはモデル・Mac・Cloudタスクを起動しない。モデル/API/課金契約や新しい恒久認証も作らない。
既存のMac側`ygc_staging_review`接続を、別の許可済み審議セッションで手動利用する。
新しい環境・Cloud単独審議・定期起動はこの実装の対象外。

1. 対象と実審議の承認を確認してから、既存MCPの`ygc_review_connection_check`を実行する。接続診断の成功は実審議の完了ではない。
2. Review ONへの変更は別の明示操作。ONだけでは審議担当が起動せず、Admin資格をworker資格へ流用もしない。
3. 特定の申請だけを審議する場合は、そのrevisionだけを`remaining_revisions`へ指定して該当する`ygc_pending_listing`または`ygc_pending_acquire`を呼ぶ。
4. 承認済みの開始時点のキューを一回処理する場合は両キューをそれぞれ一度開始し、以降は戻された`remaining_revisions`だけを引き継ぐ。新着キューを自動的に拾い続けない。
5. 各返却指示に従い実際の写真を確認する。画像だけの独立観察を保存してから登録仕様を取得し、観察を提出する。Admin画面のSerial／Challengeを事前に観察へコピーしない。採否はYGCが既存ルールで決める。
6. 写真を確認できない、通信・ツールが利用できない場合は観察や所有の証明を作らず、可能なら対応する`ygc_fail_*`で未完了理由を記録する。leaseは2時間、3回timeoutでerror停止する。
7. Consoleを更新し、processing・OFF保留・error・accepted/rejected、Owner承認待ち、Claimを確認する。必要なOwner応答は本人の`/account`から行う。

資格情報、OIDC token、gcloud認証キャッシュ、実写真、実DBをソースアーカイブへ含めない。

## API

- `GET /api/admin/applications`: `q`（200文字以下）、`status`、`kind`、`after`（revision cursor）、`limit`（1～50）
- `GET /api/admin/applications/{revision}`
- `GET /api/admin/applications/{revision}/photos/{closeup|overview|reference}`
- `POST /api/admin/applications/{revision}/decision`: `{operation, reason, expected_version}`だけを受け付ける

更新はbearer認証付きJSONのみ。cookie認証、cross-originのOrigin、cross-site fetch、未知項目、重複JSONキー、content encoding、32 KiB超の本文を受け付けない。
IDはJavaScriptへ10進文字列、versionは不透明なSHA-256、申請revisionは32文字の小文字hexで返す。

## 検証

実サービスやモデルに接続しないPython/JavaScript検証と、別環境で実行する一時PostgreSQL・実ブラウザの検証を区別する。
`test_cloud_admin_application_routes.py`は認証・CSRF・入力・private配信、`test_cloud_admin_applications.py`は既存ルールでの一連の状態遷移と原子性を確認する。
`postgres_admin_application_checks.py`は実PostgreSQLの正本権限・投影・mutex・並行Listingを検証し、`run_postgres_checks.py`に接続する。
`browser_cloud_admin_applications.py`は実ブラウザの確認／終了／SignOut／応答遅延を含む。実行結果は個別の引き継ぎ記録へ記載する。
