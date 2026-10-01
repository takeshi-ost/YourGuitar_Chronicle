# Your Guitar Chronicle

ギター個体の履歴を、掲載・所有・仕様・出来事などのClaimから構築するローカル試作です。現在の実装はFastAPI + SQLiteで動き、Reverb公式APIを使った収集と、Top Page・User Profile・Browser Consoleを含みます。公開サービス向けの本人確認と管理権限は未実装です。

- [ローカルでのセットアップと起動](app/README.md)
- [現行ドキュメントの目次](docs/README.md)
- [企画概要](docs/PROJECT_VISION.md)
- [機能と未完成範囲](docs/CAPABILITIES.md)
- [GCPへの移行境界](docs/GCP_BOUNDARIES.md)

現行の開発基準は `main` です。プロフィール・収集・管理画面の拡張とClaim Evidenceを使うObservation評価器は、2026年9月30日に統合済みです。旧DBの互換処理の整理状況は [Observation移行の残作業](docs/TEMP_OBSERVATION_MIGRATION_PLAN.md) を参照してください。
