# GCP 移行のための境界（現在はローカル試作）

この文書は将来の Cloud Run + Cloud SQL (PostgreSQL) + Identity Platform + Cloud Scheduler / Cloud Run Jobs への移行契約を示す。現在のアプリはローカル試作であり、クラウド認証・PostgreSQL・定期実行を実装したものではない。`ygc.platform_boundaries` は接続前後の型とローカル実装を定義し、未接続のクラウド側は明示的にエラーにする。

| 責務 | 現在 | 将来の差し替え点 |
| --- | --- | --- |
| HTTP 実行 | FastAPI をローカルで起動 | Cloud Run に配置し、起動時に本番アダプターを必須とする |
| 利用者の本人確認 | `PrototypeIdentity` は画面が渡す利用者 ID を未検証の `ActorContext` として扱う | Identity Platform の ID token をサーバーで検証し、発行者と subject を `users.id` に対応付ける。クライアント指定 ID を本人確認に使用しない |
| 永続データ | `local_repository` が SQLite `Repository` を返す | PostgreSQL リポジトリと移行スキーマへ交換する。Claim とその承認・履歴の意味を保持する |
| クロール | `LocalCrawlRunner` が既存の `advance_program` を１ステップ実行する | Scheduler が権限付きで Cloud Run Job を起動し、ジョブが永続カーソルから１ステップ実行する |
| 画像等のファイル | ローカルファイル | 永続オブジェクトストレージへ移し、DB には参照を保存する |

## 認証境界

現在の画面から届く `viewer_id` などは **本人の証明ではない**。例えば `PrototypeIdentity.resolve(prototype_user_id=12)` は `ActorContext(user_id=12, provider="prototype", subject=None, verified=False)` を返す。Bearer token が送られた場合は未検証のまま採用せず拒否する。プロフィールと個体・Claim の閲覧エンドポイントではこの境界を通すが、既存の更新 API、管理操作、表示権限は依然としてローカル試作の信頼モデルにある。公開サーバーとして運用する前に **すべての** 利用者指定パラメータ・投稿・Claim・投票・管理 API を検証済み `ActorContext` に置き換え、権限検査をサーバー側で統一する必要がある。

将来の受け渡し順序は、クライアントが Identity Platform で取得した ID token → HTTPS リクエストの Bearer token → サーバーが署名・発行者・対象・有効期限等を検証 → `(identity_provider, identity_subject)` で `users.id` を解決 → `verified=True` のコンテキストを業務処理へ渡す、となる。`users` に nullable な対応付け列と一意インデックスを用意した。既存利用者との対応付け・移行時の重複解消は後で明示的に行う。プロトタイプ ID や表示名から自動的に同一人物とみなさない。

## DB・ジョブ境界

SQLite 固有の SQL・マイグレーション・同時書き込み処理は PostgreSQL 向けに移植する必要がある。特に Claim の派生状態、クロールのカーソルとログ、重複防止を維持し、複数インスタンスで同じステップを同時処理しないよう DB のトランザクションとロックを設計する。Cloud SQL への接続管理と機密情報の保管も移行時に実装する。

ローカルの `ygc crawl-step --category electric --year-min 1950 --year-max 1980` は既存の保存済みカーソルを使い、一度の呼び出しで１ステップだけ進める同期実行の入口である。定期起動やクラウドジョブの模倣は行わない。将来は Cloud Scheduler が Cloud Run Job を起動し、Job 側がカテゴリーと製造年範囲を受け取って同じ業務処理を呼ぶ。手動実行と定期実行は `CrawlStep.origin` で区別できるが、実行の重複・再試行・失敗時再開は永続ストアで制御する。今の Web のバックグラウンドスレッドとメモリ内 `_jobs` は複数インスタンスや再起動をまたげないため、移行時にジョブ状態の保存先も交換する。

`K_SERVICE` / `CLOUD_RUN_JOB` が設定された環境、または `YGC_PLATFORM_TARGET` 等で未実装のバックエンドを指定した環境では、ローカル DB を開く前に `PlatformAdapterRequired` で停止する。クラウド上でローカル SQLite や未検証の利用者 ID をそのまま運用しないためのガードであり、デプロイ可能になったという意味ではない。

## 移行時に残る作業

- Identity Platform のトークン検証と利用者対応付け、全エンドポイントの認可と管理権限の検証。
- PostgreSQL スキーマ・データ移行・接続プール・Claim の同時更新とカーソル排他。
- 画像の永続化、Reverb API トークンやその他のシークレットの安全な管理。
- Cloud Run Job の実装・ジョブ状態の永続化・Cloud Scheduler の認証付き起動と再試行設計。
- 実環境での統合テスト、移行後のローカル依存の撤去。
