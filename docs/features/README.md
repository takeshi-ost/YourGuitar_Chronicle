# 機能仕様の索引

現行ローカル版の入力条件・表示対象・状態遷移・制限を管理する。画面操作は[ユーザーガイド](../user-guide/README.md)と[運用ガイド](../operations/README.md)、物理構造は[DB構造](../architecture/DATABASE_STRUCTURE.md)へ分ける。

| 機能領域 | 主文書 | 対象 |
| --- | --- | --- |
| 閲覧・ユーザー・交流 | [閲覧・プロフィール・交流](BROWSING_AND_SOCIAL.md) | Top Page、検索、統計、Profile、公開範囲、お気に入り、Follow、DM、通知 |
| クラウド公開カタログ | [移植範囲と公開境界](../migration/CLOUD_PUBLIC_CATALOG.md) | 固定公開項目、Guest閲覧、検索・詳細・Chronicle、Acquire引き継ぎ。未配置checkpoint |
| クラウドClaim投稿・編集 | [移植範囲と競合・公開境界](../migration/CLOUD_CLAIMS.md) | Specification / Repair / Incident、自分の一覧、Owner判定、無効化。未配置checkpoint |
| 個体・履歴 | [Claim](CLAIMS.md) | 種別、判定・有効性、画像、反応、Snapshot |
| 登録・所有申請 | [Listing / Acquire](OWNERSHIP_REQUESTS.md) | Challenge、正式画像審議、申請状態、Owner承認 |
| Owner決定 | [Ownership Decision](OWNERSHIP_DECISION.md) | 記録評価、申請・譲渡・係争、判定権限の連動フロー |
| 譲渡 | [Transfer](TRANSFER_CLAIM.md) | 相手の合意と所有状態の移動 |
| 所有権係争 | [Disputes](OWNERSHIP_DISPUTES.md) | 開始、提出ラウンド、ロック、裁定 |
| 外部収集 | [Crawl](incremental-crawl.md) | 対象、差分・手動・自動、進捗・ログ |
| 管理画面 | [Console](BROWSER_CONSOLE.md) | Main / Detail、一覧・管理機能の範囲 |
| 運用 | [サービス運用](SERVICE_OPERATIONS.md) | ステータス、メンテナンス、スイッチ、バックアップ |
| 審議実験 | [Authentication Test](AUTHENTICATION_TEST.md) | 正式Claimとは独立した実験キュー |
| 表示設定 | [テーマ](USER_THEMES.md)、[言語](LOCALIZATION.md) | 配色・壁紙・共通UI、辞書・切替・翻訳対象 |

実装していない認証・クラウド基盤は[機能一覧](../overview/CAPABILITIES.md)と[移行設計](../migration/GCP_BOUNDARIES.md)で明示する。ここでの「仕様」は法的な所有権保証や公開環境の認可保証を意味しない。
