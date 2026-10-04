# Browser Consoleの機能仕様

対象：現行ローカル実装。管理者の操作は[管理操作ガイド](../operations/README.md)。通常ユーザー向け操作とは分離する。


- Web Crawl / Guitar DB Management / User DB Managementを固定ヘッダーから移動する。デスクトップでは左Mainと右Detailを別々にスクロールする。Operationsは右Detail層の最上部に配置する。
- User DBのUsers一覧で選んだユーザーがBrowser Consoleの操作対象になり、User Detail見出し横からそのユーザーのTop Pageを開ける。GuestでのTop Page表示は別ボタンから開く。User Detailの編集欄は1行1項目とし、アイコン横に名前・アカウント種別・BAN状態を表示する。
- モーダル内のManual CrawlとIncremental Crawl（Crawl Now）、保存済み詳細の再判定、進捗・実行ログ、Claim migration / backfill、DB統計、バックアップ・復元・初期化を操作する。
- 未承認Acquireの互換管理機能は**承認するとCurrent Ownerが変わる可能性がある**Claimだけを対象とする。通常の申請はOwnershipのRequest／Disputesで管理する。既存DB修正モーダルの重複候補は**同じ正規化メーカーとシリアルを持つ複数のDB個体**の候補を表示し、残す個体を指定してMerge／Deleteする。
- Product DetailのObservation decisionから、Claimごとの候補値・採用項目・保存済みSnapshotとの差を読み取り専用のマトリクスで確認できる。
- ClaimのVerification強制変更・削除、アカウント情報とNormal / Silent BAN / BANの管理が可能。判定・管理操作を記録し、必要に応じて個体Snapshotを再構築する。管理権限は現時点でlocalhostとプロセス内トークンに限定。詳細は [console-claim-administration.md](../operations/console-claim-administration.md)。
## Ownership管理

Request / Disputes / AuthenticationをOwnership欄に配置する。RequestとDisputesは一覧を共通形式で表示し、Detailボタンでモーダルを開く。Applicant / OwnerはUser Detail、GuitarはProduct Detailに対象を表示する。Requestの初期状態は未確定の案件を表示するIncomplete。

正式申請の審議・結果変更は[Listing / Acquire仕様](OWNERSHIP_REQUESTS.md)、係争は[Disputes](OWNERSHIP_DISPUTES.md)、Claimを更新しない実験用キューは[Authentication Test](AUTHENTICATION_TEST.md)で管理する。

Operationsのモード・状態・バックアップ条件は[サービス運用仕様](SERVICE_OPERATIONS.md)、操作手順は[管理操作ガイド](../operations/README.md)を参照。
