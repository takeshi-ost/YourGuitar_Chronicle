# クラウドDB管理のブラウザ受入

2026-10-05。保存・保持・定期保存・復元・初期化の実装はmainへ統合し、ステージングへ配置済み。隔離試験と実クラウドの読み取り接続・匿名拒否は成功。管理者ブラウザでの復元・初期化は未実施。Computer Useのアクセシビリティ・画面収録許可待ちで中断している。

## 操作する画面

[Account](https://ygc-staging-accounts-rgmjxrs5kq-an.a.run.app/account)から認証済みの運営用YGCアカウントでSign Inし、[BrowserConsole](https://ygc-staging-accounts-rgmjxrs5kq-an.a.run.app/console)を開く。Google Cloud IAMのログインだけではYGC Admin操作を認証しない。

## 確認順序

1. **対象ごとの保存設定**：Databaseを切り替え、Periodic save・Interval・Keep snapshotsが独立していること、Save settings後の再読み込みで維持されることを確認する。初期値はOFF／24時間／10世代。
2. **世代保持**：Authentication experimentだけKeep snapshotsを2にし、Save nowを3回、各回の完了を待って実行する。最新2件になり、他DBの履歴が減らないことを確認する。設定は確認後に元へ戻す。GCSのsoft-delete保存期間と台帳の監査記録は別管理である。
3. **定期保存**：Authentication experimentだけPeriodic saveをON、Intervalを1時間にする。毎時起動なので初回は指定間隔に最大約1時間を加えた待ち時間がある。履歴が増え、他のOFF対象が定期保存されないことを確認し、試験後OFFへ戻す。短時間で完了する試験とは分けて扱う。
4. **確認モーダル**：現在のOffline等のメンテナンス状態で最新Chronicle行のRestoreを押す。外側クリック・Escape・Cancelが閉じるだけで操作を開始しないこと、異なるDB名では実行できないことを確認する。
5. **Chronicle復元**：ChronicleをSave nowで保存してから、その最新行をRestoreする。`chronicle`を入力して実行する。再読み込み後も状態を確認でき、完了後に個体一覧と保存履歴（保護用保存追加）を確認する。登録ユーザー、Admin、Google Sign Inを維持する。
6. **Chronicle初期化**：復元可能な最新保存を確認してからReset test dataを実行する。個体と関連コンテンツが空になり、Accountsの登録とAdminが維持されることを確認する。必要なら手順5の保存から戻す。
7. **他DBの独立操作**：Accountsは最新保存から復元して登録/認証/Admin維持を確認し、初期化がSNS・仮セッションのみであることを確認する。Operationsは最新保存から復元して現在モード・保存台帳を維持し、自動処理がOFFになることを確認する。Authentication experimentの復元・初期化がGoogle認証に影響しないことを確認する。各操作を完了してから次へ進む。
8. **資格とモード**：NormalでRestore/Resetが無効、保存一覧・Save nowは利用可能であることを確認し、元のOfflineへ戻す。一般ユーザーやSignOut後に管理操作が利用できないことも確認する。

## 結果未確認・失敗の場合

連打せず、画面再読み込みで永続要求の状態と保存履歴を確認する。対象データのコミット後に投影/監査が失敗する可能性があり、失敗表示だけで「未変更」と判断しない。対象、表示状態、時刻を記録して共有する。パスワードやトークンをチャットへ貼り付けない。

## 後続

この受入が済んでから実復旧試験の結果を記録し、Reverb認証情報をSecret Managerへ接続してCrawlのPostgreSQL移植・Crawl前Chronicle保存を進める。現在はCrawlを実行する画面/Jobをクラウドに接続していない。画像付きChronicle（media_assets）の復元も未移植のため、変更前に拒否する。詳細は[保存・復元仕様](CLOUD_DATABASE_BACKUPS.md#現在の到達点と復元初期化2026-10-05)。
