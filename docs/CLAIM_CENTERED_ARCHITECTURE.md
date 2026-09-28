# Claim中心のデータ構造

## 記録と現在値

- **Claim:** ギターについての意味のある主張・出来事。Listing、Ownership (Acquire / Transfer / Inherit / Release)、Identity Correction、Specification、Repair、Incident、Event、Mediaなど。ステータス、判定、作成者、日付を保持する。
- **Individual:** 物理的な一個体を識別するレコード。現在のMaker / Model / Serial、Owner / LocationなどはObservationの判定結果を保存したSnapshot。意味情報をIndividualだけ直接変更しない。
- **Observation:** 一個体につき一つの論理的なClaim調停機構。Claimの発生日・同日のClaim ID、承認・BAN、必須Evidenceから候補値と採否理由を計算し、Individualに現在値を反映する。過去の判定結果そのものは保存しない。
- **Evidence:** Claimに紐付く根拠。外部掲載のListing ID、URL、取得日時、Owner / LocationなどはListingまたは再掲載AcquireのEvidence。ユーザーAcquireには取得日Evidenceを必須とする。旧`observations`テーブルは移行中のクロール記録・互換参照として残るが、現在値の判定元ではない。

手動登録も外部収集も、入力正規化 → 外部Listing IDの重複確認 → Individual照合または作成 → ClaimとEvidenceの保存 → 個体単位Observationの判定 → Individual Snapshotへの反映の流れに従う。同じ外部Listingの判定と、別IDで見つけた**同一の物理個体**の判定は別の問題である。

## 承認と所有状態

- Listing Claimは掲載時点の主張として保持する。再出品が既存個体と確実に結び付く場合は新たなListing Claimを増やさずAcquire Claimで来歴を追加する。それぞれの外部掲載根拠はClaim Evidenceに保存する。
- 現時点でAcquireはOwnerとLocationを設定し、Transfer / Inherit / ReleaseはOwnerとLocationを空欄にする。ユーザーOwnerがいる個体への新たなAcquireはUnverifiedから開始する。承認によるOwner変更候補は管理画面のUnverified Acquireに表示される。
- Owner Verificationが必要な第三者のSpecification / Repair / Incident / Event / MediaなどはUnverifiedで開始する。適用対象のClaimはPositive時だけSnapshotやギャラリーに反映する。Negative / Unverifiedも表示方法を変えてChronicleに残す。現在のOwnerは管理者判定後も再判定できる。
- Former OwnerのAcquire / Releaseは同じペアIDを持ち、まとめて判定する。ユーザーAcquireは明示的な取得日と日付Evidenceを要する。Current Ownerがいないときは日付Evidenceを持つ新しいAcquireを自動でPositiveにし、Ownerがいる場合の第三者AcquireはOwner承認待ちにする。同日の競合は小さいClaim IDを先に評価する。
- Claimの通常の「Delete」はinactive化。管理用ハード削除や個体のMerge / Deleteは監査記録を残す別操作。BANされた利用者のClaimもDBからは消さず、公開表示とSnapshot評価で非活性化する。

## 重複と移行

同一個体の候補判定ではメーカー、シリアル、モデルの矛盾を検討し、曖昧なら候補をreviewに保持する。管理画面のRepeatedは**同じ正規化メーカー・シリアルを持つ異なるIndividual群**で、同一性が確定した件数ではない。人が残す個体を選んでMergeまたはDeleteする。MergeしたClaimの一部は再承認待ちにする。詳細は [console-claim-administration.md](console-claim-administration.md)。

旧Observation中心DB向けの移行入口は `ygc claim-status` / `ygc migrate-claims`。Evidenceへの複写は `ygc migrate-claim-evidence`、現在値の全件照合は読み取り専用の `ygc audit-observation-migration`。収集前にはreadiness（未移行のListing Observation、Claimなし個体、不完全なIdentity Claim、未完了shellが0）を確認する。移行はバックアップを取ってから実施する。これはローカル旧DB向けであり、PostgreSQLへの移行手順とは別。後者は [GCP_BOUNDARIES.md](GCP_BOUNDARIES.md) を参照。
