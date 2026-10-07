# Cloud 通知Inbox 引き継ぎ

## 基点・範囲

- Repository：`takeshi-ost/YourGuitar_Chronicle`
- 正式な適用基点／Cloud checkoutのHEAD：`fdd3917d3936da1b7a0fb84c5fac2cda3bfc8429`（PR59統合済みmain）
- 基点tree：`746507e72e209290cbb411fe68bced61ff1da6ef`
- 作業ブランチ：`feat/cloud-notification-inbox`
- 以前のcheckoutを保持し、正式なmainと同じtreeを確認した別checkoutで実装。
- commit／push／PR／merge／deploy未実施。実アカウント・実データ・ステージング、認証設定、schema、runtime grantsの変更なし。

本人宛てのアプリ内通知一覧、未読件数、ページ送り、個別／全件既読、現在権限を再確認する既存Owner／Transfer画面への入口を追加した。Cloudの通常Owner Verificationが欠いていた作者通知を、判定と同じtransactionへ接続した。通知は既存の型と本文を維持し、メール・push・新しい通知方針を追加しない。[実装範囲](../migration/CLOUD_NOTIFICATIONS.md)を参照。

通知は過去の情報であり、現在の操作権限ではない。通知の閲覧・既読化はTransferの合意、所有権Declineの了承、Claim承認、係争処理を代行しない。最初の既読時刻は個別／全件既読・Transfer終了のいずれでも保持する。

## 検証状態

CloudでPython 1,675件（基点比112件追加）、JavaScript 678件（基点比88件追加）が成功。依存固定・PostgreSQL生成schema照合・diff検査、追加受入スクリプトのcompile／importも成功。既存の非致命的なPython deprecation警告2件は残る。同梱の`manifest.json`と`validation.log`で照合する。実PostgreSQLとChromiumをCloudで実行したと扱わない。

独立レビューでnullable本文、既存Transfer結果の型名、既読失敗後の古い画面操作の再生成を確認・修正し、回帰試験を追加した。本人宛て通知の正本／投影フェンス、型付き移動先の現在権限再確認、既読の副作用分離、Owner通知のatomicity・同時刻再送防止を検証し、未解決の実装指摘なし。PG／Chromium受入コードも別担当が静的にレビューした。

合成PostgreSQLは使い捨てループバックDBで、fixtureと故障注入だけDB ownerを使い、サービス操作は変更していないrestricted runtime roleを使う。通知以外のChronicleテーブルに既読処理の副作用がないこと、schema／grantsが同じことも照合する。ブラウザ受入はproduction assetsと合成レスポンスを使い、実認証や写真へ接続しない。

このCloudでは以前に拒否されたPostgreSQL導入／Chromium起動を再試行していない。既知のPlaywright終了処理TargetClosed警告の整理も別作業。

## 適用・受入ゲート

許可されたMacまたは通常CIのクリーンな上記baseに、`notifications.patch`を適用し、全変更ファイルのSHA256を`manifest.json`と照合する。既存の未確定変更、DB、画像、設定を上書きしない。このCloudでもbaseのarchiveへpatchを適用し直し、ファイルハッシュを照合する。

```sh
python scripts/check_dependencies.py
python scripts/build_postgres_schema.py --check
python scripts/run_tests.py --browser --postgres-bin /path/to/postgresql18/bin
```

通常CIのループバックPostgreSQLサービスは`--postgres-port 5432`を使う。同じ最終treeで全Python／JavaScriptと実PostgreSQL／Chromiumを成功させる。recipientの隔離、正本／投影・BAN／Silent BAN・非active Claim、BIGINTとページ送り、既読の同時実行・再送・未知結果、Read Only／Offline／Admin Only、保守排他、Owner通知のtransaction rollbackと二重保存防止、SignOut／アカウント切替／遅延応答／古い移動先を含む。

commit、push、PR、merge、deployはそれぞれ別承認。実データでの所有審議E2Eは合成通知受入と分離したrelease／beta gateとして残る。係争workflow、Profileの公開制御・Favorites／Follow、公開写真は後続単位。ステージングのOffline v13・Review OFF・Crawl OFF、50個体／67 Claimsはこのcheckpointの検証に使わず変更しない。
