# Observation移行の完了範囲と残作業

**2026-09-30更新。共通Observation評価器への切替は完了し、`main`へ統合済み。旧テーブルの互換処理は整理中。** この文書は残作業と撤去条件を管理する一時計画であり、現行仕様は [CLAIM_CENTERED_ARCHITECTURE.md](CLAIM_CENTERED_ARCHITECTURE.md) を参照する。初期の段階A〜Dの計画・経緯はGit履歴に残る。下記の撤去条件を満たして整理が完了した時点で、必要な運用説明を現行文書へ移し、この計画書を削除する。

## 完了していること

- Listing / 再掲載Acquireの外部掲載根拠を `claim_source_evidence` に保存し、ユーザーAcquireには明示的な取得日Evidenceを必須化した。旧記録の複写は冪等な移行CLIで行う。
- 個体Snapshotの書込経路は `_rebuild_individual_snapshot_in_connection` から共通の `evaluate_observation` を呼ぶ。ClaimとEvidenceから採用値を算出し、Individualとユーザーの所有分類に反映する。旧Snapshot評価処理との並走期間は終了した。
- 判定は発生日の日付順、同日はClaim IDの昇順。時刻や提出順だけで過去の出来事を後日の所有状態に優先させない。Claim一覧とObservationマトリクスも同日のID順を使う。
- Current Ownerだけが他ユーザーの対象Claimを判定できる。第三者Acquireは承認待ちとし、承認によってOwnerと判定権限が移る。自己判定は禁止。通常操作と管理者の強制判定は別経路としてテストしている。
- Browser ConsoleのObservation decisionは読み取り専用のClaim×項目マトリクスで、採用根拠と保存値との差を示す。
- Product Detailの掲載画像・出典はClaim Evidenceを優先する。アップロード画像はClaimに紐付くメディアから表示する。
- 使用されなくなった旧Observationカード、旧Owner表示関数、画面内の旧Observation保持変数・スタイルを撤去した。
- 個体詳細APIの旧 `observations` 返却・旧履歴オプションと、作成APIの旧Observation IDフィールドを撤去した。CLIの `ygc show ID` はClaimだけを表示し、`--legacy-observations` は廃止した。
- クロールの既知Listing判定・公開状態確認は共通のEvidence優先読取に切り替えた。未移行・未登録の旧行をフォールバックとして保持し、同じ掲載を二重計上しない。無効化・BAN済みClaimの掲載も再収集の対象に戻さない。
- 個体に登録する外部Listing／再掲載Acquireと、手動Listing・Ownership・Former Ownerの旧行への二重書込を停止した。Claim・必要なEvidence・画像・Snapshotを同一トランザクションで保存し、APIはClaim IDを返し、旧Observation IDは返さない。Repository内部の戻り値のみ、段階的整理のため空の互換値を維持する。
- 新規の未登録クロール記録は `crawl_unregistered_records` に保存する。Claim情報と出典情報の入力全体をJSONで残し、取得日時・Listing ID・URL・未登録理由も保持する。期限や自動削除は設けない。作成結果の `crawl_record_id` はこの記録のIDで、Individual・Claim・旧Observationは作成しない。
- 現行統計に `external_listing_sources`（重複を除く既知外部掲載数）、`registered_serial_listings`（有効なClaimに結び付くシリアル付き掲載数）、`serial_listing_coverage_percent`（後者÷前者）を追加した。既知掲載数には非活性Claimの出典・未登録記録も含む。この比率は全検索結果の抽出成功率ではない。CLIとAPIは新指標を使い、旧行数と旧抽出率の統計フィールドは撤去した。
- Claim編集はClaimと取得日Evidenceを更新し、旧履歴行は変更しない。新規OwnershipのPrevious owner入力は `claims.previous_owner_text` に保存する。過去の入力がある旧行は保持し、推測による自動変換や削除はしない。
- New Discovery、掲載数、未承認Acquireの出典、保存済み詳細からの仕様バックフィルをEvidence優先に変更した。旧移行形式の画像URLもEvidenceから取得する。Repeatedの `listing_count` はListingと外部再掲載Acquire（Automation／Merge由来）のClaim数とし、手動Ownershipの互換行は数えない。
- 未登録クロール記録の全列を複写する `ygc archive-unregistered-crawl` と、期限なしの `legacy_crawl_archive` を追加した。本文・画像URL・抽出結果・日時・元のIDに加え、追加列もJSONで保持し、SHA-256と元行の一致を確認する。元行の削除や上書きは行わない。保管後に内容が変わった場合は全複写をロールバックし、不一致を報告する。

## 監査結果とその範囲

| 確認 | 個体数 | 現在値の差分 | 評価エラー | 掲載Evidence欠損 | ユーザー取得日Evidence欠損 | 個体未登録の旧クロール行 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2026-09-28 切替前のユーザー報告 | 465 | 0 | 0 | 0 | 0 | 1,628 |
| 2026-09-30 手元の `app/data/chronicle.db` を読み取り専用で再監査 | 587 | 0 | 0 | 0 | 0 | 1,628 |

9月28日の移行では掲載Evidence 466件、取得日Evidence 8件を複写したとの報告がある。9月30日はデータの書換え・複写を行わず、`Repository.audit_observation_migration`で確認した。

この監査は保存済みの識別・Finish・Owner・Locationと共通評価器の結果、および所定のEvidence欠損を照合する。全画像ファイルの復元、クロール再開位置の移行、すべての表示/APIの互換性を保証するものではない。587個体はこの時点の手元DBの件数であり、Git管理の旧テストDBや将来の稼働DBの件数ではない。

検証専用のDBコピーでは、移行済み外部掲載の旧行589件を除去して、587個体のSnapshot、既知Listing 2,217件、掲載数589件、未承認Acquire、Repeated、新着表示の一致を確認した。Claimの旧参照IDが空になる点を除きClaim表示も一致し、監査差分・エラー・Evidence欠損は0だった。バックアップを別DBへ復元し、起動処理後の統計と監査も確認済み。実DBからの削除は行っていない。

未登録記録についても別のDBコピーで1,628件を保管し、全列の一致を確認した。元行がある間は重複計上しない。コピー内だけで保管済み元行を除いた後も既知Listing 2,217件は出典・日時まで一致し、残る全テーブル（候補、進捗、公開状態確認、Claim、個体等）は不変だった。587個体の監査差分・エラー・Evidence欠損は0。SQLiteバックアップからの復元と複写の再実行も確認した。

2026-09-30（JST）、手元の実DBにもスキーマ追加と未登録1,628件の保管を適用した。適用前のDBと画像4件を `app/data/migration-backups/20260929T164324Z/before-migration.zip` に保存し、アプリのバックアップ検証処理で展開・画像参照とファイルの一致を確認した。適用後も既存全テーブルの既存列・全行が不変で、587個体の監査差分・評価エラー・Evidence欠損は0。旧履歴2,235行は削除せず保持している。バックアップはGit対象外。旧API撤去後のPythonテスト206件とブラウザ確認も成功した。

手動二重書込停止後はPythonテスト205件が成功。ブラウザで手動登録・画像表示・Release後のOwned / Formerly Owned更新を確認した。DBコピーの起動時更新を2回実行し、既存587個体・647 Claimの既存列・旧履歴2,235行が不変であることを確認した。同じコピーで新規手動登録とAcquire承認による所有者移転を行っても旧行は増えず、追加後588個体の監査差分・評価エラー・Evidence欠損は0だった。

新規未登録記録の保存先切替もDBコピーで確認した。旧記録1,628件の保管後に新規未登録1件を保存し、既知掲載は2,217件から2,218件へ増えた。既存の全業務テーブルは不変で、再実行は重複せず、SQLite復元後も入力全体と統計が一致した。587個体の監査差分・評価エラー・Evidence欠損は0だった。

## 撤去済みの互換インターフェース

利用者に外部API・旧CLIの利用がないことを確認し、以下を撤去した。`start_webui.command` と `save_test_db.command` / `.bat` は維持する。保存スクリプトはSQLite全体のバックアップを使うため新テーブルも含まれる。macOS版は検証用ディレクトリで実行して全テーブル・全行の一致を確認した。Windows版はソース確認のみで、Windows実機では未検証。

| 撤去済み | 現行の代替 |
| --- | --- |
| 個体詳細APIの `observations` と `include_legacy_observations` | Claim一覧・掲載Evidence・画像 |
| 作成APIの `observation_id` / `observation_ids` | `claim_id` / `claim_ids`。未登録クロールは `crawl_record_id` |
| 統計APIの `observations` / `serial_extraction_rate` / `max_observations_per_individual` | `external_listing_sources` / `registered_serial_listings` / `serial_listing_coverage_percent`。旧指標と意味は異なる |
| `ygc show --legacy-observations` | 通常の `ygc show` によるClaim来歴 |

`serial_observations` は現行Web画面も使う互換名なので、今回の撤去に含めない。旧形式バックアップのインポート・移行CLIは、通常APIの互換廃止とは別に復元経路として維持する。API廃止の判断だけで旧行や旧テーブルを削除しない。

## 残っている依存関係

| 残存箇所 | 現行の用途 | 撤去前に必要な変更・確認 |
| --- | --- | --- |
| `persist_reverb_listing_claim` | 新規未登録記録は専用保存先へ切替済み。旧掲載の重複確認フォールバックが残る | 既存DBの保管・照合完了後に旧行参照を整理 |
| `get_individual` / `list_claims` | Repository内部の旧履歴取得と、Evidenceがない旧DBの出典フォールバック | 旧DB復元・移行経路の整理後に撤去。通常の個体詳細APIは旧履歴を返さない |
| `db/source_records.py` | Evidence、旧行、専用保管先の順に参照。既存の出典がある場合は保管行を二重計上しない | 未登録記録は全列保管・照合が可能。稼働DBの複写と旧参照の整理後にフォールバックを撤去 |
| 旧シリアル監査・インポート | 過去の抽出内容と旧形式DBの参照 | 旧データの保全と復元を維持しつつ整理 |
| Merge / Delete / バックアップ・復元 / 起動時移行 | 旧行・参照ID・Evidence・画像の保全と旧DBの読込 | 旧形式バックアップの復元、Claim ID・関係・画像保持、再実行時の冪等性を確認 |

`observations`には移行済み個体の互換行と、個体を作らなかった掲載調査の記録が混在する。1,628件の未登録行をClaimへ偽装したり、一括削除したりしない。必要なクロール記録の保持期間をこの整理作業だけで変更しない。

### 未登録記録を保管する手順

1. SQLiteと画像のバックアップを取り、まずDBコピーで `ygc archive-unregistered-crawl` を実行する。対象は個体・Claim・掲載Evidenceに紐付かない外部の旧記録。Listing IDが欠けている行も保存する。
2. 出力の `eligible` / `created` / `already_archived` / `archive_total` を確認する。再実行は一致する行を増やさず、内容やチェックサムの不一致では全件の変更を取り消す。コマンドは他の起動時移行を実行せず、存在しないDBも新設しない。
3. `payload_json` は元行全列、`payload_sha256` はそのUTF-8表現のSHA-256、`legacy_observation_id` は元ID、`archived_at` は複写日時。保管先に期限や元行の削除に連動する外部キーは設けない。期限付きの詳細キャッシュや見送り記録で代用しない。
4. 元行の撤去を検討する際は、既知Listing、再収集防止、公開状態確認、再開位置、本文・抽出情報・画像参照と復元を照合する。今回のコマンドに削除機能はない。新規の未登録記録は専用保存先へ書くが、登録済み個体・手動操作の旧履歴も残っているため、未登録記録の保管完了だけで旧テーブルを削除してはいけない。

移行監査の `archived_unregistered_crawl_rows` は専用保管先の件数を示す。`unregistered_legacy_crawl_rows` とは複写直後に重なるため、足し合わせて掲載数にしない。保管後も、手動で内容を変更せず複写コマンドの再実行でチェックサムを検証する。

## 整理の順序

1. **未使用処理と文書の整理**：呼出元のない旧表示コードを削除し、現行仕様・実装済み機能・この依存表を更新する。
2. **読取経路の切替（主要経路完了）**：個体表示・管理用読取・クロール判定をClaim Evidenceへ切替済み。未登録記録の独立保存先への移管と旧監査経路は残る。
3. **通常書込の切替（完了）**：外部登録と手動操作の旧行作成・同期を停止し、未登録記録も専用保存先へ切替済み。作成・編集・所有権移転・ペア判定・削除・管理者操作の回帰テストを実施済み。旧形式の明示的なインポート・復元処理は残る。
4. **保存・復元の確認と互換処理の撤去**：旧DBとバックアップの扱いを確定し、照合と復元検証後に不要な列・テーブル・フォールバックを除く。

後続の変更でも、通常ユーザーの所有権と判定権限の遷移例を実装とテストで確認する。管理者判定、BAN、Mergeは別経路として確認する。

## DB変更前の確認手順

1. 稼働SQLiteと画像を一緒にバックアップする。SQLiteはバックアップAPI等で一貫したコピーを作り、復元先は検証用ディレクトリにする。
2. 旧スキーマに必要なClaim移行・Evidence複写をバックアップ後に行う。`ygc claim-status` は `init_db`によるスキーマ更新を含み、完全な読み取り専用コマンドではない。必要な入口は `ygc migrate-claims`、`ygc migrate-claim-evidence`。
3. `ygc audit-observation-migration --sample-limit 20`で全個体の現在値とEvidence欠損を監査する。このコマンドは存在しないDBを新設しない。
4. 読取・書込経路の変更をDBコピー上で実行し、Claim ID、掲載ID、Owner / Location、Verification、ユーザー関係、画像、クロール候補・カーソル・件数を比較する。画像はDB内の参照と実ファイルの両方を照合する。
5. 旧形式バックアップを復元して同じ照合を行い、移行を再実行しても重複・欠落がないことを確認する。

**中止条件：** 説明できない現在値の差、同一Listingによる重複Claim、Evidence・画像・承認履歴の欠落、クロール再開位置の破損、復旧不能な変更。差がある状態でデータの上書きや旧テーブル削除へ進まない。

## 別途判断・実装すること

- 再掲載の観測日と実際の取得日は同一とは限らない。現行の再掲載Evidenceは観測日を `date_basis=observed_at` として区別する。既存の欠損日付を推測して補完しない。
- Claim種別ごとの証明資料の強度・必須条件。ユーザーAcquireで合意済みなのは取得日のEvidenceであり、他の証明書類の必須化ではない。
- 管理者の判定・削除・BANで過去Ownerへ戻る特殊ケースの自動解決。現行は診断画面と管理操作で判断する。
- 本人確認・全API認可、PostgreSQL、画像の永続化、定期ジョブは [GCP_BOUNDARIES.md](GCP_BOUNDARIES.md) に従う別作業。
