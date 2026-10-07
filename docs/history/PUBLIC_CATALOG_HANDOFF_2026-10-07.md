# 公開カタログ checkpoint 引継ぎ（2026-10-07）

## 基準と状態

- 基準main：`9506c3d5909df0ba39d1b95c94dd72a8744e33d3`（PR #53統合後）。
- 作業ブランチ：`feat/public-guitar-catalog`。
- 変更は未コミット。commit／push／PR作成／merge／deployは行っていない。
- 既存の別checkoutを破棄・上書きせず、新規checkoutで実装した。
- 本番のOffline／Review OFF、実データ、審議実行、Owner承認、認証、IAM、DBスキーマを変更していない。

## 実装した単位

1. Guest用のTop／検索／4種ソート／ページ送りとProduct Detail。
2. 固定公開項目のサーバー投影。基本仕様、承認済み構造化Specification、状態別Chronicle、正規掲載元リンク。
3. `/account?acquire={id}` の対象保持。ログイン・登録・メール確認を跨ぎ、最新の対象確認と書込権限確認後に利用者が明示的に下書きを作成する。
4. API／サービス／Python／Nodeの回帰と、実PostgreSQL・ブラウザの使い捨て検証スイート。

公開範囲・意図的な非表示・API契約は[公開カタログ移植仕様](../migration/CLOUD_PUBLIC_CATALOG.md)を正本とする。既存Owner VerificationやObservationの実装は変更していない。

## 検証

統一コマンドの最終結果はcheckpointのvalidation記録で照合する。Python／JavaScript、依存固定／導入済み依存、PostgreSQLスキーマ生成物、diffの空白検査を対象にしている。独立レビューで公開境界、source URL、履歴状態、認証を跨ぐAcquire、古い非同期応答を確認し、指摘した既存形式のSpecification互換・Admin Onlyでの選択再取得・検索ラベルを修正済み。

実PostgreSQLと実Chromiumはこの環境では未実行。過去に判明している実行許可制約を別経路で回避しない。準備した試験の構文確認は、実DB／ブラウザの合格ではない。CSSの実表示・モバイル描画はMac／通常CIでの確認が残る。

## Macへの安全な引継ぎ

1. 指定された実行環境の接続と対象checkoutを確認する。既存の未コミット変更を保存し、基準mainから別の作業ブランチを作る。別環境のパスがそのまま存在するとは扱わない。
2. checkpointのbase SHA、patch SHA-256、変更ファイルのSHA-256を確認する。基準が異なる場合に強制上書き・reset・自動commitはしない。
3. 基準から `git apply --check public-catalog.patch` を通してから適用し、manifestの全ファイルと一致することを検証する。patchには追加ファイルも含める。
4. READMEの固定依存を持つ環境で次を実行する（PostgreSQL 18と許可されたChromeの実パスを使う）。実データ・GCP・Reverbの環境変数を継承する個別起動は使わない。

   `python scripts/check_dependencies.py`

   `python scripts/build_postgres_schema.py --check`

   `python scripts/run_tests.py --browser --browser-executable /実際のChromeパス --postgres-bin /実際のPostgreSQL18/bin`

   runnerは専用一時DB／サーバーを生成し、終了時に後片付けする。既存の利用者DB、起動中のWebUI、Cloud SQLへ接続しない。
5. 新しい `browser_cloud_public_catalog` と `postgres_public_catalog_checks` に加えて、更新済みAccount・申請フローと既存Owner／Admin審議の全回帰が通ることを確認する。失敗した場合は同じfixture内で診断し、本番操作へ置き換えない。
6. 公開の承認を受けた場合だけcommit／Draft PRを作り、リモート上の正確なhead SHAと必須CI成功を確認する。merge／deploy／Normalへの変更はそれぞれ承認範囲を確認する。

## 別途残る決定

- Reverb由来データを一般公開する利用条件と許諾。
- 写真の公開同意、対象写真・派生画像、配信、撤回、保存期間。今は全写真がプレースホルダーで、代表画像や私的Evidenceを公開しない。
- 公開プロフィール／Owner表示／自由記述の公開条件。今回の固定投影から除外する。
- 実写真を使う審議と実Owner承認の受入。このカタログcheckpointやfixtureの合格では代替しない。
