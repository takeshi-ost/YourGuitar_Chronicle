# GCP移行前の整備状況

確認日：2026-10-04。対象：main `aea72cf`（PR #13統合後）と[Draft PR #14](https://github.com/takeshi-ost/YourGuitar_Chronicle/pull/14)の追加整備。コード・テスト・CI設定・GitHub上の状態を照合した。実データを開く監査や、GCP接続・本番部署・実Reverb収集は実施していない。実装後はこの表の状態と確認根拠を更新する。

## 結論

GCP移行の実装へ着手できる状態。一般ユーザー向けの主要機能について、この確認で移行着手を妨げる新たな未実装機能は見つかっていない。開発基盤の追加整備はPR #14で実装・CI検証済み（未マージ）。移行対象データの準備は引き続き残る。「GCP移行に着手できる」と「公開サーバーで利用できる」は別で、公開には認証・認可・永続化などの移行作業が必要。

## 完了したローカル整備

| 項目 | 状態・確認根拠 |
| --- | --- |
| テスト実行の統一 | `scripts/run_tests.py` がPython・JavaScript・任意のブラウザ検証を実行 |
| 実データ・資格情報からの隔離 | conftestと共通ランナーで保存先・環境を分離。ブラウザは専用一時サーバーを起動 |
| 一時領域の後片付け | tmp_path・pytest cacheも専用領域へ集約。成功・失敗・通常中断と外部basetemp拒否のテストあり |
| 依存関係の固定 | constraints、ビルド要件、固定pip、共通インストーラー、起動スクリプトを整備 |
| PR自動チェック | Python 3.12 / Node 24 / Ubuntu 24.04 / Chromium。PRとmain pushで実行 |
| アカウント・コンテンツ分離 | Accounts正本とChronicle投影、ダミーセッション、UUID保護・独立復元のテストあり |
| バックアップ機能 | 対象別の手動・定期保存、保持、復元条件、復元前保存を実装。Accounts復元とChronicle復元の境界も検証 |
| 所有状態の回帰検証 | Acquire・Transfer・自己判定禁止・管理者別経路・係争・BAN等のテストあり |
| 文書の役割分離 | コンセプト、操作、機能仕様、DB構造、管理、開発、移行、履歴に整理 |

PR最終コミットとmain統合後の両方でCI成功。直近確認はPython433件、JavaScript55件、共通UIと27モーダルのブラウザ検証。件数を固定の合格条件にはしない。

- [PR #13](https://github.com/takeshi-ost/YourGuitar_Chronicle/pull/13)
- [main統合後CI](https://github.com/takeshi-ost/YourGuitar_Chronicle/actions/runs/37171893838)

## ローカル追加整備の実施状況

| 優先度 | 残作業 | 現状 | 完了条件 |
| --- | --- | --- | --- |
| 完了（作業ブランチ） | 依存定義と固定ファイルの整合チェック | check_dependencies.pyとCIステップを追加。固定漏れ・範囲不一致・ビルド定義差を検出する回帰テスト通過 | mainへの統合はPRで確認 |
| 完了（作業ブランチ） | 主要操作の正式ブラウザテスト | 登録・同意・資格情報破棄・ログイン／SignOut・日本語・ListingとAcquire→Owner承認を追加、ローカルChromeで通過 | GPTだけ固定観察を供給し実DB処理と画面を検証。main統合はPRで確認 |
| 完了（作業ブランチ） | ブラウザ失敗時の診断保存 | スクリーンショット・trace・ページエラーを保存、CI artifactの7日保持を追加。ローカルで失敗時生成を確認 | main統合はPRで確認 |
| 完了（GitHub適用済み） | PRと成功チェックの強制 | mainの保護を有効化。PR、最新mainに対する `Tests (Python, JavaScript, Chromium)` 成功を管理者にも必須化。強制push・削除は不可 | 他者レビュー承認は0件で単独開発可能 |
| 条件付き | Windows実機確認 | macOSとLinux CIは検証済み。Windowsは未検証 | Windowsでの開発・利用を継続する場合、起動・固定依存導入・共通テストを確認 |

追加した3項目はPR #14で検証し、mainへの統合状態はPRで確認する。mainの保護ルールはGitHubへ適用済み。

追加整備のCI（コミット `5eb54e8`）：[実行結果](https://github.com/takeshi-ost/YourGuitar_Chronicle/actions/runs/37172702871)。依存検査、Python435件、JavaScript55件、Chromiumの既存UI・モーダル・新規ユーザー操作が成功。失敗時artifactもCIで実際に生成・取得を確認した。

## データ移行前の準備

これは新しい一般機能の追加ではなく、移行対象と合格基準を確定する作業。移行先のスキーマ・権限実装と並行できるが、本データ投入前には完了させる。

| 残作業 | 現状・完了条件 |
| --- | --- |
| API・画像の権限表 | ローカルダミーのID照合テストはある。Guest／本人／Current Owner／管理者と非公開画像を含む全入口の一覧・許可条件を作り、本番認可の受入基準にする |
| 実データの移行基準スナップショット | 本確認では未実施。DB・画像のコピー上で件数、ID・UUID、Claim／Evidence、Owner、BAN、画像参照、カーソルを記録し、移行後の比較基準を残す |
| 復元リハーサル | 一時DBの自動テストはある。実データのコピーでChronicle単独復元時の最新Accounts保持、ユーザー参照・画像・履歴の整合を確認する |
| 旧Observation互換の扱い確定 | 通常書込と主要読取のClaim化は完了。旧DB import・復元・監査互換は残る。残存データの保全・移行対象を決める。移行前に旧テーブルを全部削除すること自体は必須ではない |
| Crawlの運用標本検証 | 一括Electric / Acoustic、重複・再開、部分失敗等の自動テストあり。実APIでの網羅性・誤照合・途中停止・429対応は別途標本確認が必要 |

既存テストがあることと、今回実データで試したことを区別する。監査手順は[旧Observation移行](../migration/TEMP_OBSERVATION_MIGRATION_PLAN.md)、保存単位は[DB構造](../architecture/DATABASE_STRUCTURE.md)。

## GCP移行そのものの作業

以下を「先にローカル版へ機能追加しなければならない項目」とは扱わない。GCP実装・検証の中で解決する。

- Identity Platform接続、実登録・メール確認、ID token検証、全API認可と管理者資格。
- PostgreSQLへのSQL・スキーマ移植、アカウント正本とコンテンツの同期・独立復元、同時更新とカーソル排他。
- Cloud Storageへの画像保存、非公開根拠の配信制御、シークレット管理。
- Cloud Run用コンテナ・設定・起動／ヘルス・デプロイ／切戻し手順。
- Scheduler / Run Jobs、ジョブ状態の永続化、再試行・多重実行防止、クラウドバックアップ。
- ステージング環境での移行前後比較・統合検証、正式Terms／Privacy。

Admin Onlyモードは合意済みの移行後追加項目。詳細と配置判断は[GCP移行境界](../migration/GCP_BOUNDARIES.md)へ集約する。本確認ではGoogleサービスの現行仕様・料金を再調査していない。
