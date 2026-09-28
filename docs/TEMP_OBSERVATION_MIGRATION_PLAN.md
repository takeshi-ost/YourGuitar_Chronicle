# 一時作業計画：Observationを個体単位の調停層に改修する

> **状態：段階B完了、段階C並走中。旧Snapshotが引き続き正規値。** この文書は現行コードの説明ではなく、合意済みの目標、実装順序、検証条件、残る判断をまとめる。改修完了と検証後に削除する。現行動作は [CLAIM_CENTERED_ARCHITECTURE.md](CLAIM_CENTERED_ARCHITECTURE.md) とコードを参照。作業中に決定が変わった場合はこの計画を先に更新する。

2026-09-28 時点：Claimに紐付く掲載Evidenceテーブル、既存掲載の冪等な複写CLI、新規掲載と再掲載の同時保存、読み取り専用の個体単位評価器・管理画面診断を実装した。付属旧テストDBの316個体で、旧Claimの項目を補完した後に新評価と保存値が一致。稼働DB全体の照合、各入口の切替、旧Observation参照の撤去は未実施。再掲載の観測日を実際の取得日として扱うべきかは未決定で、現在のEvidenceは `date_basis=observed_at` と明記している。

## 1. 目標と変更しない原則

```text
Guitar Individual (1) ── (1) Observation [個体のClaim調停機構]
                                  └── (N) Claim ── (0..N) Evidence

Crawl records [一覧・詳細の取得と調査済み履歴] → 該当するClaimのEvidence
```

- Guitar Individualは個体の親レコード。Current Ownerを含む検索・表示用の現在値はObservationの調停結果から作り、直接の意味情報更新は行わない。
- 新Observationは個体と一対一（または個体内部の評価機構）で、複数Claimの優先順・採否から現在値を算出する。**掲載やユーザー操作ごとにObservationを増やさない**。過去の調停結果を履歴テーブルへ蓄積しない。
- Claimが変更の主張を表し、Evidenceがその根拠を表す。Listingと再掲載によるAcquireの掲載ID、URL、取得日時、元データは**それぞれのClaimのEvidence**。Claim・承認状態・管理操作の既存履歴は保持する。
- 初回掲載はListing Claim。別IDで再掲載された同一個体は既存の同一個体判定に従ってAcquire Claimを追加し、掲載Evidenceを付ける。曖昧な一致は自動統合せずreviewに保持する。
- Current Ownerは独立した管理設定ではない。Observationが採用したClaimから決まる。Current Ownerに他ユーザーのClaimを判定する権限が伴う。現Ownerがいる場合、他ユーザーのAcquireはそのOwnerがPositiveとするまで所有者を変更しない。
- Owner不在のAcquireは必要なEvidenceがあれば自動でPositive。現段階でAcquireに必須とするEvidence条件は**取得日の記載**。証明資料の要否・強度は後日設計する。
- 取得日を持たないAcquireは新規作成させない。取得日を古い順に、同日のClaimは**Claim IDの小さい順**に評価する。先に提出され自動承認されたOwner不在のAcquireがOwnerを確立したら、後続の他ユーザーのAcquireは新Ownerの判定対象になる。
- 取得日と提出日時は別。後から追加した過去日付のAcquireは全Claimを同じ評価器で再評価し、後日に有効な所有イベントを登録順だけで覆さない。
- Owner本人による自己のOwner設定ClaimのNegative／inactive化は通常操作では認めない。管理者の削除・強制判定・BANによる特殊ケースは今回の通常フローの確定範囲外とし、Browser Consoleの診断・管理方針で別途扱う。管理者の判定後もOwnerの再判定を許す方針。

## 2. 現行コードとの差分と影響点

| 現行 | 改修後に必要な扱い | 主な場所 |
| --- | --- | --- |
| `observations` は掲載等ごとに1行、`claims.observation_id` はnullable | 旧テーブルを当面残し、掲載出典をEvidenceへ移す。新Observationは個体一対一の評価器／評価結果とする | `db/schema.sql`, `db/repository.py` |
| Claimを直接走査してIndividual Snapshotを再構築 | 共通のObservation評価器が候補状態と採否理由を返し、その結果をIndividualへ反映 | `_rebuild_individual_snapshot_in_connection` と全呼出元 |
| Automation AcquireのOwner・Locationは旧Observationの列を直接参照 | Claimと掲載Evidenceだけから再現できるよう移す。旧データの値を失わない | `persist_reverb_listing_claim`, Owner評価, `record_reverb_unavailable` |
| `claim_evidence` は主に画像との紐付け | 画像Evidenceを保持しつつ、外部掲載・取得日のEvidenceを追加。URLやListing IDの一意性も担保 | `media_assets`, Evidenceスキーマ、API |
| クロールの既知Listing、公開確認、統計は旧 `observations` を参照 | Evidence／クロール記録の適切な保存先に移す。初回・再掲載双方を同じsource + Listing IDで重複防止 | `crawl_service.py`, `crawl_candidates.py`, `crawl_detail_cache.py`, `incremental_crawl.py`, `Repository.stats` |
| Profile / Console / Claim APIがClaimと旧Observationの両方を表示に利用 | 表示契約を維持して読取元を段階的に交換。管理画面に判定経路を追加 | `web.py`, `static/*.html`, Repositoryの読取処理 |
| Mergeと旧DB互換移行が旧Observationを参照 | 旧参照の保存・Evidenceの再紐付け、再承認状態を維持 | `resolve_repeated`, `migrate_legacy_observations_to_claims`, DB import/export |

リポジトリ付属のテスト用DBには個体未紐付けの旧Observationが多数ある。これは**開発者の稼働DBの件数ではない**。旧Observationを一括削除・一対一制約へ直接変更しない。

## 3. データ構造の追加案（命名は実装時に確定）

- `claim_source_evidence` のような構造化されたEvidence：`claim_id`、種類、`source_site`、`source_listing_id`、`source_url`、取得時刻、掲載／取得日、元データまたは保存先、抽出メタデータ、作成時刻。既存 `claim_evidence` と `media_assets` は画像用として当面維持する。外部掲載IDに対し、出典サイトとの組に一意性を設ける。過去の掲載IDや画像参照を失わない。
- 新Observationは、まず**個体IDを入力とする純粋な評価処理**で実装する案を優先する。新たな一対一テーブルを設ける場合も `individual_id UNIQUE NOT NULL` とし、調停結果を二重の真実源にしない。Individualには必要なSnapshotと根拠Claim ID等、診断・検索に有用な最小限の派生値を保持する。具体的な永続化形式は新旧比較の実装前に決める。
- `crawl_detail_cache`、`crawl_candidates`、`crawl_listing_cache`、`crawl_runs`、`crawl_programs`、`crawl_listing_checks` は収集・再実行の状態として維持し、個体のObservationと区別する。個体に結び付かなかった旧掲載調査行も**クロール記録にのみ**残し、新Observation／Individualへ投影しない。削除・保持期間は今回の改修で勝手に変えない。
- 既存Claim ID、ユーザー、投票、Response、添付メディア、署名ギター参照は保持。旧データのEvidence移行はsource + Listing ID、Claim ID等で冪等にする。

## 4. 評価器の入出力と更新の流れ

評価器は個体IDと有効なClaim群、Evidence、判定、利用者状態を受け取り、**候補となる現在値**と項目別の根拠Claim ID、採用／不採用理由を返す。読み取りだけで再計算でき、呼び出しごとに過去の評価結果を保存しない。同じ入力から常に同じ結果を返す。発生日、Claim IDのタイブレーク、Positive / Unverified / Negative、inactive、Owner資格を一か所で処理する。

1. ClaimとEvidenceの必須項目を検査し、外部掲載IDの重複と物理個体の一致を別々に確認する。
2. 既存状態とClaim追加後の**一時評価結果**を作る。旧ObservationやIndividualの実レコードを仮上書きしない。差分はOwner / Location / identity / specification等の項目別に示す。
3. 他ユーザーのAcquireがCurrent Ownerを変え得るならOwner判定を待つ。保留ClaimのEvidenceは残すが、現在値は変えない。Owner不在時は必須日付を確認し、先に提出された取得日順・同日Claim ID順のClaimを適用する。
4. 採用可能なClaim、Evidence、承認状態、必要ならIndividual Snapshotを**同一DBトランザクション**で確定する。Claimが後から承認・否定された場合も同じ評価器で再計算する。
5. Browser Consoleは現在の入力から評価器を再実行し、採否理由と保存済みSnapshotとの差分を読み取り表示する。診断画面の表示自体はDBを変更しない。

所有者の権限を現在値から判断する際は、判定対象のClaimを採用する**前の有効Owner**を基準にする。未承認Claim自身で自分に承認権限を与えない。管理者判定とOwner判定の変更履歴は既存の監査記録を維持する。

## 5. 段階的な実装と切替ゲート

### 段階A：基準データと仕様の固定

- コード・テスト・手元稼働DBのバックアップを取得（SQLiteと画像をセットで保全）。クロールreadiness、Claim ID、現Owner／Location、個体ごとのSnapshot、掲載ID、承認状態、添付と候補・カーソルの件数を比較用に記録する。Git管理のテスト用DBだけを稼働DBの代わりにしない。
- 新Observationが保存されるか評価器のみか、Owner不在時の詳細な判定、既存の日付不明Acquireの移行方針、再掲載由来Acquireの日付の意味を決める。**Reverb掲載日・再発見日は実際の取得日の証明とは限らない**。既存方針の「再発見日」を観測上の有効日として使うなら、実際の取得日と区別して記録する仕様を先に定める。
- 同じClaimとEvidenceから期待される現在値・判定経路の固定フィクスチャを作る。現Ownerあり／なし、同日・過去日付、再掲載、BAN／管理者の特殊例を含める。

### 段階B：Evidence追加と無停止の複写

- アプリがまだ旧構造を読む間にEvidence用テーブル／列と移行処理を追加する。登録済み個体のListing / Acquireに紐づく旧Observationの掲載ID・URL・日付・Owner / Location・元データを複写し、移行前後のsource + Listing ID、Claim ID、画像の対応を照合する。
- 個体未登録の旧Observationはクロール履歴の領域に保存し、ClaimのEvidenceに偽装しない。調査済み判定・スキップ／再確認の既存動作を維持する。繰り返し実行で重複を作らない。

### 段階C：新Observation評価器を並走

- Claim作成・承認・無効化後の候補状態を評価するが、最初は**旧Snapshotを正規の表示値として維持**。新旧のOwner / Location / 個体識別／仕様／メディアと根拠を比較して差分を分類する。差がある場合に旧データを新結果で上書きしない。
- 自動収集に実際の投稿日・取得日が不足する旧Claimは欠損を明示する。適当な日付を捏造せず、移行ルールが定まるまで確認待ち／比較除外として扱う。

### 段階D：書込経路と読取経路の切替

- 手動登録、Ownership（Former Ownerのペア含む）、その他のClaim、判定変更、Reverb初回・再掲載・非公開確認、Merge、BAN、管理者操作の順にEvidenceと共通評価器へ移す。各入口の保存はトランザクションで完結させる。
- 読取API、統計、プロフィール、Product Detail、New Discovery、クロール既知Listing判定を段階的に切替。Browser Consoleに個体ごとの判定経路・現在Snapshotとの差分を追加する。既存URLと操作結果を必要な間維持する。
- 並走比較で意図しない差分がなく、実データからOwner / Locationを正しく再計算できることを切替条件とする。切替前のDB+メディアへ復旧できる手順を確認する。

### 段階E：整理

- 旧 `observations` を参照する個体情報の読取／更新をなくし、必要なクロール記録だけを保持する。二重書込や移行用の互換処理はデータ照合と復旧検証が済んでから除去。現行の主要文書を新仕様で更新し、**この一時計画書を削除**する。

## 6. 必須の検証と中止条件

| 検証ケース | 期待する性質 |
| --- | --- |
| 初回Listingと別IDの再掲載 | 1個体のまま、初回Listingと再掲載Acquireにそれぞれ掲載Evidence。既知Listingの再実行は冪等 |
| Ownerがいる再掲載・第三者Acquire | Positive前は現OwnerとLocation不変。承認後にだけ所有者変更。自身のClaimで自分を承認できない |
| Owner不在・競合Acquire | 取得日必須。同日ならClaim ID順、先行ClaimでOwnerが成立した後は後続にOwner確認が必要 |
| 後から登録した過去日のAcquire | 後日有効なClaimを登録日時だけで覆さない。Chronicleと現在値の両方が整合 |
| Listing公開終了 | 所有根拠が当該掲載だけなら規定の確認後にUnknownへ。ユーザーOwnerなど別の根拠があれば維持 |
| Claim判定変更／無効化、Former Ownerペア | 同じ評価器で再計算。通常ユーザーが自身のOwner設定Claimを無効化できない |
| 管理者Merge、BAN／Silent BAN | 記録・根拠・ユーザーからの参照が失われない。未定の異常ケースは判定経路を表示して手動判断し、勝手に正常化しない |
| 旧DB・バックアップ復元 | 旧掲載記録の件数・Listing ID・Claim ID・画像を保持。マイグレーションを再実行しても増殖・欠落しない |
| Browser Console診断 | 採用／不採用と理由、根拠Claim／Evidence、保存済みSnapshotとの違いを表示するだけでDBは変わらない |

**中止条件：** Owner / Locationの説明できない差異、同じListing IDによる重複Claim、Evidenceの欠落、クロール再開位置の破損、画像・承認履歴の消失、ロールバック不能なスキーマ変更。差分が出た状態で既存データの上書きや旧テーブルの削除に進まない。

## 7. 今回の範囲外・残る判断

- Claim種別ごとのEvidenceの強度・証明書類の必須化。現在合意したのはAcquireに取得日が必要なことだけ。ほかのClaimの既存入力条件はこの計画だけでは変更しない。
- 再掲載の**観測日**と実際の**取得日**を同じ日にできるか、既存Claimの欠損日付をどう移行するかは段階Aで明示的に決める。決まるまで取得日の自動補完を実装しない。
- 管理者のClaim削除・強制判定、BAN後にOwnerが巻き戻る特殊ケースの自動解決は後回し。Browser Consoleで判定経路を見て対処できる状態にする。
- 外部公開向けの本人確認・認可とPostgreSQL移行は別案件。本計画はローカル試作の意味構造を正す作業であり、認証されていないブラウザ指定IDを権限の証明にしない。
