# Cloud Event Claim 引き継ぎ

## 基点と作業範囲

- Repository：`takeshi-ost/YourGuitar_Chronicle`
- 正式な適用基点／Cloud checkoutのHEAD：`20fe59eff6a2756c1a0caec372d2ea96c87acfba`（PR57統合済みmain）
- 基点tree：`9e68892943d8207d583473c536e3a6045b373b71`
- 作業ブランチ：`feat/cloud-event-claims`

基点をGitで取得し、そのexact commitから新しいcheckoutを作った。過去のTransfer / Releaseその他のcheckoutは変更していない。このcheckpointは未commit・未push・未PR・未merge・未deploy。

実ステージングの個体50件／Claim67件、Offline v13、Review OFF、autoCrawl OFFの境界を維持し、実DB・実写真・実受領・メール・認証・IAM・bucketへ操作していない。ローカルMacへの直接アクセスも行っていない。

## 実装内容

- 認証済みEventの投稿、本人のページ付き履歴、本文／日付編集、soft Deactivate。
- Exhibition / Performance / Recording / Auction / Other、必須本文／日付、任意の写真0〜10枚。
- Mediaと共有のサイズ制限・JPEG正規化・private固定generation参照・補償削除・commit結果不明時の保持。
- 同じClaimに属する全添付と全文を使うCurrent Owner確認。本文・写真の改訂、Owner移転、BAN、無効化のアクセス再検査。
- 写真なしEventの明示的な空配列と、欠落／取得不能写真を区別したfail-closed UI。旧ローカル写真のコピーや公開はしない。
- 確定前・不明結果・再読込・Read Only / Offline・閉じる・戻る／進む・SignOutの中断処理。
- 既存schemaとruntime role、Accounts正本／Chronicle投影のフェンス、共有Repository／Observationを再利用。

詳細：[Cloud Event](../migration/CLOUD_EVENT_CLAIMS.md)。公開カタログはEvent本文・作者・写真・Evidenceを返さず、Adminの既存画像入口は別の権限経路のまま。

編集で種類・写真・Verificationを変更しない。第三者EventはUnverified、Owner作成はPositive。Eventはidentity・所有者・所在地を変更しない。新たな同意・公開ギャラリー・Verification方針、Identity Correction、重複ルールの変更は含めていない。

## 検証結果

最終portable検証はPython **1,451件**、JavaScript **490件**が成功（新規Event Python84件、Event／Owner関連Node69件を含む）。依存固定整合、PostgreSQL schema生成整合、diffチェックも成功。Pythonには既存の非致命的な非推奨警告2件がある。結果はcheckpointの`manifest.json`と`validation.log`に記録する。追加した実PostgreSQL／Chromiumスイートも統一runnerへ登録するが、このCloudでは実行していない。過去に拒否されたPostgreSQLインストール／Chromium起動を再試行せず、compile/import・コードレビューで確認する。単体試験を実PG／ブラウザ合格と表現しない。

独立レビューは関連Python252件・Node186件を再確認し、未解決の指摘なし。Owner subtypeのDTO／表示整合、既存PG期待フィールド、合成Snapshot／プロフィール比較、ブラウザ文言の不一致を修正した。追加PGには同一revisionでの作者編集対Owner判定の競合と、実Transfer受領による写真権限移動を含む。

合成PostgreSQLはDB ownerだけがfixture・sequence・故障注入を設定し、サービス操作には既存runtime roleを使う。実DB・実GCP接続先を受け付けない。合成ブラウザはproduction assetsを読み、外部通信をfixtureで遮断する。実認証・メール・実写真は不要。既知のPlaywright終了処理TargetClosed警告の整理は別タスクであり、今回の機能へ混在させない。

## 適用・受入・公開ゲート

許可されたMacまたは通常CIのクリーンな上記baseへ、同梱の`event-claims.patch`を適用し、変更ファイルのSHA256を`manifest.json`と照合する。既存の未確定変更、DB、写真、環境設定を上書きしない。patch適用とハッシュ照合はこのCloudで基点archiveへ再適用して検証する。

```sh
python scripts/check_dependencies.py
python scripts/build_postgres_schema.py --check
python scripts/run_tests.py --browser --postgres-bin /path/to/postgresql18/bin
```

通常CIのループバックPostgreSQLサービスでは`--postgres-port 5432`を使う。同じ最終treeで全Python／JavaScriptと実Chromium／PostgreSQLの成功を確認する。写真なし／あり、第三者投稿→Owner全写真確認→判定、作者編集でのVerification維持、Owner移転後の旧Owner画像拒否、stale revision、Service Mode、結果不明、閉じる／戻る／進む／SignOutを確認する。

commit、push、PR、merge、deploy、実データでの所有審議受入はそれぞれ別承認。今回のcheckpointはこれらを実行する許可を含まない。Identity Correctionは次の独立単位、実所有審議E2Eは別のrelease／beta gateとして残す。
