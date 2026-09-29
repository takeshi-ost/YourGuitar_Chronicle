# Your Guitar Chronicle — 現行ドキュメント

このディレクトリは `feature/observation-redesign` のローカル試作の**現行実装**を説明する。実行方法は [app/README.md](../app/README.md)。過去の設計案と実装の差分はGit履歴で参照できる。

| 読む目的 | 文書 |
| --- | --- |
| 企画の目的と将来像 | [PROJECT_VISION.md](PROJECT_VISION.md) |
| 画面・機能・未実装範囲 | [CAPABILITIES.md](CAPABILITIES.md) |
| Claimと個体Snapshotの規則、所有権と判定権限の不変条件 | [CLAIM_CENTERED_ARCHITECTURE.md](CLAIM_CENTERED_ARCHITECTURE.md) |
| 収集・再判定・統計 | [incremental-crawl.md](incremental-crawl.md) |
| 管理者操作とBAN | [console-claim-administration.md](console-claim-administration.md) |
| テーマ・ロゴ | [USER_THEMES.md](USER_THEMES.md) |
| GCP移行時の交換箇所 | [GCP_BOUNDARIES.md](GCP_BOUNDARIES.md) |
| ローカル画像認証テストの導入と制約 | [AUTHENTICATION_TEST.md](AUTHENTICATION_TEST.md) |
| **一時作業計画（未実装の改修案）** | [TEMP_OBSERVATION_MIGRATION_PLAN.md](TEMP_OBSERVATION_MIGRATION_PLAN.md) |

`docs/Your_Guitar_Chronicle_実装仕様書.md`、`BROWSER_GUI.md`、`REVERB_SETUP.md`、`DATABASE_UPDATE_POLICY.md` は初期のObservation中心・Phase 1向け資料だったため削除した。初期企画書も現行の企画概要に集約した。これらの履歴はGitに残る。現行仕様の根拠は実装とテストであり、本書群はその案内である。

**公開前の重要な境界:** 利用者IDの指定は本人確認ではない。管理トークンもlocalhost専用である。公開サーバーへ移す際は [GCP_BOUNDARIES.md](GCP_BOUNDARIES.md) の認証・認可・永続化を実装する。
