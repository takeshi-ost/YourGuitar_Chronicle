# Cloud Favorite / プロフィール公開範囲保存 引継ぎ

2026-10-07。実装と検証のcheckpoint。本番反映・公開プロフィール提供の完了報告ではない。

## 基準と作業範囲

- Repository: `takeshi-ost/YourGuitar_Chronicle`
- GitHub mainを読み取りで確認した基準: `dec58b498704e404e6fd8a04ad6a3f1b0e1125fd`（PR61 merge）
- 基準tree: `8c990695a5d353d994251d83f5aa66fd5b58a28e`
- ローカル実装branch: `feat/cloud-favorites-privacy`
- 別のcloud checkoutで作業し、前のOwnership Disputes成果物を維持した。ユーザーのMacは使用していない。
- commit / push / PR / merge / deploy / 本番DB・GCS操作は行っていない。

## 実装

### 本人専用Favorite

`/api/auth/favorites` と `/api/auth/favorites/{individual}` は、正規の認証済み・メール確認済み本人に限定する。別ユーザーのIDを受け付けず、公開カタログと同じ適格条件の固定個体情報だけを返す。

追加・解除はBooleanで指定する冪等な操作。公開されなくなった個体は一覧と件数の双方から除外し、存在しない／非公開／対象作成者の投影が安全に使えない個体を404で扱う。解除は本人の行のみを対象とし、未知・削除済み・非公開IDも同じ `false` で応答する。

アカウント画面は25件のkeysetページと前後移動、個体詳細へのリンクを持つ。公開個体詳細のFavoriteは本人の状態だけを読み書きする。公開Favorite件数や他人の登録者一覧は設けない。

### 公開範囲の保存

`/api/auth/profile/visibility` は既存四項目だけを読み書きする。Public / Members / Followers / Private の厳密なenum、正規Accounts行の共有revision CAS、監査、transactional outboxを使用する。

既存のPrivate / Private / Public / Publicの既定値と保存値を変えず、公開同意とは解釈しない。未知のlegacy値はnullで読み取り、明示的な選択が揃うまで保存しない。自動補正・自動公開はない。

画面は現在の公開プロフィールや私的写真の配信を開始しないことを明記する。Followersは将来用の保存設定であり、Follow機能や新しい公開認可の実装ではない。Favoriteは常に本人専用。

### ブラウザの本人切替と非同期処理

新しい私的状態は本人・対象・request世代に結び付ける。Sign Out、SDK本人切替、履歴移動、pagehideで破棄する。不確実な更新結果は自動再送せずRefreshで確認する。

認証adapterはキャッシュ済み正規アカウントをSDKの本人に結び付け、本人の切替を跨いだtoken取得・応答の適用を拒否する。既存の権限や認証grantを追加しない。

公開カタログの読込は本人Favoriteの応答を待たず完了できる。アカウントのBFCache復元は正規認証を再確認して私的データを再読込する。

## 検証

最終実行値はcheckpointの `manifest.json` と添付のvalidationログを正とする。

- Python aggregate: 2,331 passed（既存のdeprecation warning 2件）
- Node aggregate: 845 passed、failed / skipped 0
- 依存定義・exact pins・installed closure: 成功
- PostgreSQL schema artifacts: 成功、schema/migrationファイル変更なし
- Python/JavaScript構文・diff whitespace: 成功
- 基準mainへのパッチ再適用と全ファイルSHA256一致: checkpoint生成時に確認
- 独立レビュー: 確認した範囲で未解決のblocking findingなし。独立実行したPython438件・Node148件成功。詳細はcheckpointの独立レビュー結果を参照。

新規の実PostgreSQL受入は `postgres_favorite_checks.py` と `postgres_profile_visibility_checks.py`、実Chromium受入は `browser_cloud_favorites_visibility.py` を統一runnerに登録した。既存のブラウザfixtureも新しい本人専用APIを架空データで返すよう更新した。

このcloud環境で実PostgreSQL／Chromiumは実行していない。既知の実行制約を別手段で回避せず、PG追加導入・socket起動・ブラウザ起動を再試行していない。compile・unit成功を実DB／実ブラウザ成功として数えない。実画面スクリーンショットも未取得。

後続の承認済みCIまたはMacでの統一検証:

`python scripts/run_tests.py --browser --browser-artifacts test-artifacts --postgres-port 5432`

ローカルの使い捨てPostgreSQLを使用する場合は `--postgres-port` の代わりに `--postgres-bin` で承認済みの実行ファイルディレクトリを指定する。本番接続情報を渡さない。

## 公開／反映前の判定

1. このcheckpointの確認とcommit / push / draft PR作成への承認を得る。
2. 正確な公開commitに対してPython・Node・実PostgreSQL・Chromiumの統一CIを成功させる。必要なMac検証は別途承認を得る。
3. mergeとdeployは別の承認段階。現段階の作業を根拠にService ModeをNormalへ変更しない。
4. 公開プロフィール、写真公開同意・配信・撤回、Follow公開機能は今回の成果に含めず、別設計・承認で扱う。

詳細仕様は [CLOUD_PRIVATE_FAVORITES.md](../migration/CLOUD_PRIVATE_FAVORITES.md)。既存のOwnership、Claim、Evidence、Notification、schema、runtime grants、Scheduler、Review／Crawl設定を変更する移植ではない。
