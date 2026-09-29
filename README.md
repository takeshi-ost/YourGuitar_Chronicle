# Your Guitar Chronicle

ギター個体の履歴を、掲載・所有・仕様・出来事などのClaimから構築するローカル試作です。現在の実装はFastAPI + SQLiteで動き、Reverb公式APIを使った収集と、Top Page・User Profile・Browser Consoleを含みます。公開サービス向けの本人確認と管理権限は未実装です。

- [ローカルでのセットアップと起動](app/README.md)
- [現行ドキュメントの目次](docs/README.md)
- [企画概要](docs/PROJECT_VISION.md)
- [機能と未完成範囲](docs/CAPABILITIES.md)
- [GCPへの移行境界](docs/GCP_BOUNDARIES.md)

開発は `feature/user-profile-top-page` で進行中です。`main` にこのブランチの機能がすべて入っているとは限りません。
