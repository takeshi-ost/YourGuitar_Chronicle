# Cloud Identity Correction 引き継ぎ

## 基点・範囲

- Repository：`takeshi-ost/YourGuitar_Chronicle`
- 正式な適用基点／Cloud checkoutのHEAD：`86ea27e0ccf3c5a6d4b6ae0fbb351d481710b117`（PR58統合済みmain）
- 基点tree：`4cf9f9e4c19d3a0697163727cc5b400a38dad866`
- 作業ブランチ：`feat/cloud-identity-correction`
- 既存Event等のcheckoutを保持し、基点から作った別checkoutで実装。
- commit／push／PR／merge／deployは未実施。実アカウント・実データ・ステージング、認証設定、runtime grants、schemaの変更なし。

本人の有効なListing一覧からEditを選び、元Listingを変更できない説明を経て、専用Identity Correctionフォームを開く。現在identityの旧値／新値と理由をrevisionに結び付けて確認し、明示的に保存する。本人用履歴、結果不明時の確認と再試行、認可／Service Mode／画面中断の保護を含む。詳細は[移植仕様](../migration/CLOUD_IDENTITY_CORRECTION.md)。

Current Ownerは条件にしない。Listing作者の訂正は既存どおりPositiveで作成し、Listingの日付を継承してObservationを再評価する。後の日付の訂正が上書きする既存の順序は変えない。Owner判定権限、元Listing、所有者・所在地、写真・Evidenceは保持する。

訂正の重複条件は正規化Maker / Serialで、Modelの違いで回避できない。入力した組と時系列評価後の最終的な組を同一トランザクション内で検査する。全体の3項目unique制約や他経路の重複記録方針を変更しない。相手の非公開IDはエラーへ出さず、自動Mergeもしない。

## 検証状態

CloudでPython 1,563件（新規112件）、JavaScript 590件（新規100件）が成功。依存固定・PostgreSQL生成schema照合・diff検査、追加受入スクリプトのcompile／importも成功。Pythonの既存の非致命的なdeprecation警告2件は残る。結果は同梱の`manifest.json`と`validation.log`で照合する。

独立レビューはPythonの追加112件、Nodeの追加100件を再確認し、未解決の指摘なし。混合identityによる最終Maker / Serial重複、旧記録の応答上限、係争中の書込可否、Unicodeコードポイントとブラウザー入力上限の整合を修正し、回帰試験を追加した。

このCloudでは、以前に拒否されたPostgreSQL導入／Chromium起動を再試行していない。合成PostgreSQL／Chromium受入を追加し、compile・import・コードレビューを行う。これらの実行成功は、Macまたは通常CIで確認するまで未検証として扱う。既知のPlaywright終了処理TargetClosed警告の整理は別タスク。

合成PostgreSQLは使い捨てループバックDBで、fixtureと故障注入だけDB ownerを使い、サービス操作は既存のrestricted runtime roleを使う。実DB／GCP／Reverb接続を必要としない。ブラウザ受入はproduction assetsと固定の合成レスポンスを使い、実認証や写真に接続しない。

## 適用・受入ゲート

許可されたMacまたは通常CIのクリーンな上記baseに、`identity-correction.patch`を適用し、全変更ファイルのSHA256を`manifest.json`と照合する。既存の未確定変更、DB、画像、設定を上書きしない。このCloudでもbaseのarchiveへpatchを再適用し、ファイルハッシュを照合する。

```sh
python scripts/check_dependencies.py
python scripts/build_postgres_schema.py --check
python scripts/run_tests.py --browser --postgres-bin /path/to/postgresql18/bin
```

通常CIのループバックPostgreSQLサービスは`--postgres-port 5432`を使う。同じ最終treeで全Python／JavaScriptと実PostgreSQL／Chromiumの成功を確認する。作者が所有者でない訂正、他Ownerの拒否、正規化Maker / Serial・Model違い・同時競合、旧Listingと後のCorrectionによる混合identity、無効対象・BAN・disabled・Service Mode、stale／結果不明／再提出／閉じる／戻る／進む／再読込／SignOut、元記録・非公開情報の維持を含む。

commit、push、PR、merge、deployはそれぞれ別承認。実データでの所有審議E2Eはこの訂正受入と分離したrelease／beta gateとして残る。ステージングのOffline・Review OFF・Crawl OFFと既存データをこのcheckpointの検証に使わない。
