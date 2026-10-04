# サービス運用機能の仕様

対象：ローカルプロセス。操作場所はBrowser Console右Detail最上部のOperations。公開環境での権限・監視基盤は[GCP移行境界](../migration/GCP_BOUNDARIES.md)の別作業。

## 状態とメンテナンス

Service Statusは稼働時間、DB・画像ディレクトリ、ジョブ、審議件数などを表示する。`/health/live`はプロセス応答、`/health/ready`はメインDB読取とOffline状態を検査する。Readyは全機能の正常性を保証する検査ではない。

Normalは通常利用、Read-onlyは一般更新を停止、Offlineは一般利用を停止する。Reasonは必須ではなく、各モードのメッセージ初期値をUIで用意する。設定はバージョン比較で競合を検出する。モードとメッセージはOperations DBに保存する。復旧用Operations API、ヘルス、静的資産などは制限の例外。

重要情報領域は平常時のサービス案内を表示せず、未決着の申請・回答要求に絞る。メンテナンス時はサービス案内だけを改行ありで表示する。

## バックグラウンド処理

ReverbチェックでAuto CrawlのON / OFFを切り替える。対象・年範囲・間隔はWeb Crawlで設定する。最終実施時刻はCrawl開始時刻を基準に表示する。

ChatGPTチェックで正式Acquire / Listing審議の反映を制御する。OFFでも回答を受け取り別途保持するが、審査中データを更新しない。最終回答時刻には停止中に受け取った回答も含める。両スイッチは再起動後も保持する。実行はローカルプロセスの稼働に依存する。

## バックアップ

対象はChronicle、Accounts、Operations、Authenticationの4つ。各対象に手動保存、定期保存、保存世代数、ダウンロード、復元を提供する。保持は1〜100世代、定期間隔は1〜168時間。定期保存の初期状態はOFF。保存時に対象の保持上限を超えた最古の世代を削除する。

Crawl前の保存はChronicleだけを対象にする。その他のDBの定期頻度は個別設定。閲覧・ダウンロードはNormalでも可能。復元はRead-only / Offlineとバックグラウンドジョブ停止が必要で、復元前保存を行う。Accounts保存ではセッションを含めず、復元でもセッションを破棄する。

物理的な保存先と復元時のユーザーID保護は[DB構造](../architecture/DATABASE_STRUCTURE.md)、操作は[運用ガイド](../operations/README.md)。

## 管理者とメンテナンスの仕様整理

現行ではOperations等の例外を除き、Read-only / Offlineで管理者の更新も停止し、Reset DBも拒否される。この挙動は管理者の修復操作を妨げる仕様不整合として扱う。変更は未実装。最終仕様とローカル現状維持方針、GCP移行後の受入条件は[管理者権限とメンテナンス制御](../migration/ADMIN_AND_MAINTENANCE.md)を参照。
