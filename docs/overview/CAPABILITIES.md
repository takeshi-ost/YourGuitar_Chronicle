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
| 実際の認証・アカウント作成 | ダミーのみ | [GCP移行境界](../migration/GCP_BOUNDARIES.md) |
| PostgreSQL、Cloud Storage、クラウド定期ジョブ | 未実装 | [GCP移行境界](../migration/GCP_BOUNDARIES.md) |

ローカルのセッション・公開範囲設定は公開環境の本人確認や全API認可を保証しない。旧Observation互換処理の撤去は[移行残作業](../migration/TEMP_OBSERVATION_MIGRATION_PLAN.md)で管理する。
