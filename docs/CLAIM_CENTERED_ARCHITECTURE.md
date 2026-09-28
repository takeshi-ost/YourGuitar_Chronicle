# Claim中心のデータ構造

## 記録と現在値

- **Claim:** ギターについての意味のある主張・出来事。Listing、Ownership (Acquire / Transfer / Inherit / Release)、Identity Correction、Specification、Repair、Incident、Event、Mediaなど。ステータス、判定、作成者、日付を保持する。
- **Individual:** 物理的な一個体を識別するレコード。現在のMaker / Model / Serial、Owner / Locationなどは、有効かつ適用条件を満たすClaimをChronicle順に評価したSnapshot。意味情報をIndividualだけ直接変更しない。
- **Observation:** 外部掲載のListing ID、URL、取得日時、抽出元などのprovenance。掲載そのものの重複防止と監査に使うが、通常のOwner / Location / identityの真実源にはしない。

手動登録も外部収集も、入力正規化 → 外部Listing IDの重複確認 → Individual照合または作成 → Listing / Ownership Claimとprovenanceの保存 → `rebuild_individual_snapshot` の流れに従う。同じ外部Listingの判定と、別IDで見つけた**同一の物理個体**の判定は別の問題である。

## 承認と所有状態

- Listing Claimは掲載時点の主張として保持する。再出品が既存個体と確実に結び付く場合は新たなListing Claimを増やさずAcquire Claimで来歴を追加する。外部ListingのprovenanceはObservationに残す。
- 現時点でAcquireはOwnerとLocationを設定し、Transfer / Inherit / ReleaseはOwnerとLocationを空欄にする。ユーザーOwnerがいる個体への新たなAcquireはUnverifiedから開始する。承認によるOwner変更候補は管理画面のUnverified Acquireに表示される。
- Owner Verificationが必要な第三者のSpecification / Repair / Incident / Event / MediaなどはUnverifiedで開始する。適用対象のClaimはPositive時だけSnapshotやギャラリーに反映する。Negative / Unverifiedも表示方法を変えてChronicleに残す。管理者による強制判定は通常のOwner判定より優先される。
- Former OwnerのAcquire / Releaseは同じペアIDを持ち、まとめて判定する。Current Owner不在時の第三者申告を無条件でOwner確定に使わない。
- Claimの通常の「Delete」はinactive化。管理用ハード削除や個体のMerge / Deleteは監査記録を残す別操作。BANされた利用者のClaimもDBからは消さず、公開表示とSnapshot評価で非活性化する。

## 重複と移行

同一個体の候補判定ではメーカー、シリアル、モデルの矛盾を検討し、曖昧なら候補をreviewに保持する。管理画面のRepeatedは**同じ正規化メーカー・シリアルを持つ異なるIndividual群**で、同一性が確定した件数ではない。人が残す個体を選んでMergeまたはDeleteする。MergeしたClaimの一部は再承認待ちにする。詳細は [console-claim-administration.md](console-claim-administration.md)。

旧Observation中心DB向けの移行入口は `ygc claim-status` / `ygc migrate-claims`。収集前にはreadiness（未移行のListing Observation、Claimなし個体、不完全なIdentity Claim、未完了shellが0）を確認する。移行はバックアップを取ってから実施する。これはローカル旧DB向けであり、PostgreSQLへの移行手順とは別。後者は [GCP_BOUNDARIES.md](GCP_BOUNDARIES.md) を参照。
