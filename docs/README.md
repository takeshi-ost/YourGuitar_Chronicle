# Your Guitar Chronicle — 文書目次

対象：現行ローカル版。実装の根拠はコードとテスト、mainへの統合状況はGit／PRで確認する。整理日：2026-10-04。セットアップ・起動は[app/README.md](../app/README.md)。

## 読みたい内容から選ぶ

| 読者・目的 | 入口 | 記載する粒度 |
| --- | --- | --- |
| サービスの目的を知る | [企画・コンセプト](overview/PROJECT_VISION.md) | なぜ作るか、扱う概念、目指す体験 |
| 何が使えるかを知る | [機能一覧と実装状況](overview/CAPABILITIES.md) | 機能単位の有無、試作・未実装範囲 |
| 一般ユーザーとして操作する | [ユーザー向け操作](user-guide/README.md) | 画面の入口、操作順、結果、閉じる・保存する意味 |
| 機能の振る舞いを確認する | [機能仕様一覧](features/README.md) | 入力条件、表示対象、状態遷移、制限・例外 |
| データの意味・保存構造を知る | [Claim設計](architecture/CLAIM_CENTERED_ARCHITECTURE.md)、[DB構造](architecture/DATABASE_STRUCTURE.md) | 不変条件と評価規則／物理DB・テーブル・正本・復元境界 |
| 管理者として運用する | [運用ガイド](operations/README.md)、[Claim管理](operations/console-claim-administration.md) | 管理画面の操作と実施条件 |
| 実装・検証する | [UI構造](development/UI_STRUCTURE.md)、[開発手順](development/DEVELOPMENT_WORKFLOW.md)、[GCP移行前の整備状況](development/GCP_PREPARATION_STATUS.md) | ファイル責務、共通部品、テスト・依存・CI |
| GCP・旧DBから移行する | [GCP境界](migration/GCP_BOUNDARIES.md)、[構築状況](migration/GCP_STAGING_SETUP.md)、[PostgreSQL初期化](migration/POSTGRES_BOOTSTRAP.md)、[Cloud SQL初期化手順](migration/CLOUD_SQL_INITIALIZATION.md)、[Accounts同期・所有判定](migration/POSTGRES_ACCOUNT_SYNC.md)、[認証検証](migration/IDENTITY_PLATFORM_VERIFICATION.md)、[クラウド登録API](migration/CLOUD_ACCOUNT_REGISTRATION.md)、[ブラウザ認証](migration/CLOUD_BROWSER_AUTH.md)、[Cloud Run認証画面](migration/CLOUD_RUN_ACCOUNT_STAGING.md)、[Accounts同期Job](migration/ACCOUNT_PROJECTION_JOB.md)、[メール確認](migration/EMAIL_VERIFICATION.md)、[クラウド管理API](migration/CLOUD_OPERATIONS_ACCESS.md)、[クラウドConsole](migration/CLOUD_BROWSER_CONSOLE.md)、[Cloud Storage接続](migration/CLOUD_STORAGE.md)、[本人アカウント画像](migration/CLOUD_ACCOUNT_AVATAR.md)、[Observation移行](migration/TEMP_OBSERVATION_MIGRATION_PLAN.md) | 現行との差、未実装、移行条件 |
| 過去の判断・検証をたどる | [引継ぎ](history/HANDOFF_2026-10-03.md)、[SNS記録](history/SNS_IMPLEMENTATION_LOG.md)、[審議検証](history/OWNERSHIP_REVIEW_VALIDATION.md)、[壁紙生成](history/WALLPAPER_GENERATION.md) | 当時の日付・件数・判断。現行仕様ではない |

## 文書を更新するとき

操作ガイドにはAPI・テーブル・内部ファイルを持ち込まず、利用者が画面で行うことを書く。featuresは操作の逐語的な繰返しを避け、機能の条件と結果を管理する。architectureは機能横断の規則と保存構造、developmentは実装方法を扱う。コンセプトには実装完了状況やテスト件数を混ぜない。

同じ仕様の詳細を複数の文書へ複写せず、主文書へリンクする。例外は所有権・判定権限の不変条件で、関連機能は設計文書の条件を満たすことを明示する。新機能は機能一覧とfeatures索引を更新し、操作入口・保存先が増えた場合は各ガイドとDB構造も更新する。

過去の実装・検証記録はhistoryへ置く。公開環境でのIdentity Platform認証、管理者権限、PostgreSQL、Cloud Storage、クラウドジョブはmigrationで実装段階と未接続範囲を管理する。ローカル版と将来案を同じ確定仕様として記述しない。
