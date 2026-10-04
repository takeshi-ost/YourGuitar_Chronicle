# Your Guitar Chronicle

ギター個体の履歴を、掲載・所有・仕様・出来事などのClaimから構築するローカル試作です。現在の実装はFastAPI + SQLiteで動き、Reverb公式APIを使った収集と、Top Page・User Profile・Browser Consoleを含みます。公開サービス向けの本人確認と管理権限は未実装です。

- [ローカルでのセットアップと起動](app/README.md)
- [現行ドキュメントの目次](docs/README.md)
- [企画概要](docs/overview/PROJECT_VISION.md)
- [機能と未完成範囲](docs/overview/CAPABILITIES.md)
- [GCPへの移行境界](docs/migration/GCP_BOUNDARIES.md)

現行の開発基準は `main`。未マージの変更は作業ブランチとPRで確認する。開発・テスト・依存固定・PRチェックは[開発手順](docs/development/DEVELOPMENT_WORKFLOW.md)、旧DBの互換処理は[Observation移行の残作業](docs/migration/TEMP_OBSERVATION_MIGRATION_PLAN.md)を参照。
