# 現行機能の一覧と実装状況

対象：2026-10-04のローカル実装。作業ブランチとmainの統合状況はGit／PRで確認する。本書は機能の有無を示す索引。操作手順・細かな判定規則・保存構造はリンク先で管理する。

| 機能 | ローカル実装 | 詳細仕様 |
| --- | --- | --- |
| ギター検索、詳細、Chronicle、統計・地図 | あり | [閲覧・プロフィール・交流](../features/BROWSING_AND_SOCIAL.md) |
| Profile、Settings、お気に入り、Follow、DM、通知 | あり | [閲覧・プロフィール・交流](../features/BROWSING_AND_SOCIAL.md) |
| Claim追加、判定、投票、Response、画像 | あり | [個体とClaim](../features/CLAIMS.md)、[Owner決定フロー](../features/OWNERSHIP_DECISION.md) |
| 新規Listing、現在所有Acquire、画像審議 | あり | [申請](../features/OWNERSHIP_REQUESTS.md) |
| ユーザー間譲渡 | あり | [Transfer](../features/TRANSFER_CLAIM.md) |
| 所有権係争と管理者裁定 | あり | [Disputes](../features/OWNERSHIP_DISPUTES.md) |
| Reverb手動・差分・自動収集 | あり | [Crawl](../features/incremental-crawl.md) |
| 管理画面、Claim管理、BAN、個体統合 | あり | [Console](../features/BROWSER_CONSOLE.md) |
| 状態確認、メンテナンス、対象別バックアップ | あり | [サービス運用](../features/SERVICE_OPERATIONS.md) |
| Claimを変更しないGPT実験キュー | あり | [Authentication Test](../features/AUTHENTICATION_TEST.md) |
| テーマ、日英UI切替 | あり | [テーマ](../features/USER_THEMES.md)、[言語切替](../features/LOCALIZATION.md) |
| 本人認証・Google認証アカウント作成 | 未実装（ローカル登録・ダミーセッションあり） | [GCP移行境界](../migration/GCP_BOUNDARIES.md) |
| PostgreSQL、Cloud Storage、クラウド定期ジョブ | 未実装 | [GCP移行境界](../migration/GCP_BOUNDARIES.md) |

ローカルのセッション・公開範囲設定は公開環境の本人確認や全API認可を保証しない。旧Observation互換処理の撤去は[移行残作業](../migration/TEMP_OBSERVATION_MIGRATION_PLAN.md)で管理する。

## クラウド移植の追加checkpoint（2026-10-07）

一般向けの検索・ソート・ページ送り・固定Specification・公開Chronicle・ログインを跨ぐAcquire導線を実装。公開専用のサーバー項目制限とService Mode制御を適用する。写真は未公開のプレースホルダー。公開プロフィール・SNS・統計／地図は未移植。実PG／Chromiumの最終確認と公開許諾・配置承認は別途必要。詳細は[クラウド公開カタログ](../migration/CLOUD_PUBLIC_CATALOG.md)。

クラウドの Specification / Repair / Incident 投稿・編集・無効化と本人の提出一覧を追加。公開詳細から対象を保持して認証し、既存Owner判定へ接続する。承認済みClaimの編集は従来どおりVerificationを維持し、改訂競合は拒否する。写真・Event・Transfer / Release・Listing訂正は後続単位。詳細は[Cloud Claim投稿・編集](../migration/CLOUD_CLAIMS.md)。


## Cloud Event（2026-10-07 checkpoint）

Eventの投稿・作者編集・無効化、任意の非公開写真と完全なOwner確認を[追加](../migration/CLOUD_EVENT_CLAIMS.md)。既存のVerification・写真の非公開範囲・Observationを維持する。Identity Correctionは後続の別単位。公開・配置は別承認。

## Cloud Identity Correction（2026-10-07 checkpoint）

本人の有効なListing一覧と専用の訂正入口、旧値／新値確認、revision競合防止、本人用訂正履歴を[追加](../migration/CLOUD_IDENTITY_CORRECTION.md)。Current OwnerでなくてもListing作者が訂正でき、元Listingを残したPositiveな訂正として扱う。訂正に限る正規化Maker / Serial重複検査を用い、全体のunique制約や自動Mergeは変更しない。実PG／Chromiumの最終受入と公開・配置は別ゲート。
