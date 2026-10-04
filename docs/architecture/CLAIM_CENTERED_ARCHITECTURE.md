# Claim中心のデータ構造

## 記録と現在値

- **Claim:** ギターについての意味のある主張・出来事。Listing、Ownership (Acquire / Transfer / Release / Lost)、Identity Correction、Specification、Repair、Incident、Event、Mediaなど。ステータス、判定、作成者、日付を保持する。
- **Individual:** 物理的な一個体を識別するレコード。現在のMaker / Model / Serial、Owner / LocationなどはObservationの判定結果を保存したSnapshot。意味情報をIndividualだけ直接変更しない。
- **Observation:** 一個体につき一つの論理的なClaim調停機構。Claimの発生日・同日のClaim ID、承認・BAN、必須Evidenceから候補値と採否理由を計算し、Individualに現在値を反映する。過去の判定結果そのものは保存しない。
- **Evidence:** Claimに紐付く根拠。外部掲載のListing ID、URL、取得日時、Owner / LocationなどはListingまたは再掲載AcquireのEvidence。ユーザーAcquireには取得日Evidenceを必須とする。旧`observations`テーブルは移行中のクロール記録・互換参照として残るが、現在値の判定元ではない。

共通評価器への切替は`main`に統合済み。個体に登録する外部掲載と手動Listing・Ownership・Former OwnerはClaimと必要なEvidence・画像を保存し、旧行を新設しない。Claim編集も旧行へ同期しない。新しい未登録クロール記録は `crawl_unregistered_records` に入力全体を保持する。旧テーブルはAPI、移行・復元処理の互換参照として残る。残存箇所と撤去条件は [Observation移行の残作業](../migration/TEMP_OBSERVATION_MIGRATION_PLAN.md) を参照。

手動登録も外部収集も、入力正規化 → 外部Listing IDの重複確認 → Individual照合または作成 → ClaimとEvidenceの保存 → 個体単位Observationの判定 → Individual Snapshotへの反映の流れに従う。同じ外部Listingの判定と、別IDで見つけた**同一の物理個体**の判定は別の問題である。

Browser Consoleの「Observation判定」は読み取り専用のClaim×項目マトリクスで、発生日・同日のClaim ID順にClaimを並べる。各セルにはClaimが提案した値を示し、現在採用中の項目だけ明るく表示する。最下段は保存済みIndividual Snapshotで、Specification列のみProduct Detailで現在表示する仕様値を示す。採用元は共通Observation評価器（Specification列は現行仕様表示の判定）を参照し、マトリクス自体はSnapshotを書き換えない。

## 承認と所有状態

- Listing Claimは掲載時点の主張として保持する。再出品が既存個体と確実に結び付く場合は新たなListing Claimを増やさずAcquire Claimで来歴を追加する。それぞれの外部掲載根拠はClaim Evidenceに保存する。
- 現時点でAcquireはOwnerとLocationを設定し、Release / Lostと旧TransferはOwnerとLocationをUnknownにする。新規ユーザー間TransferはFrom＝Current Ownerの申請とToのAccept Evidenceにより、ObservationがToへOwnerとLocationを移す。合意とVerificationは独立し、成立済みTransferは承認時のEvidenceを根拠にそれぞれ独立して時系列順（同日はClaim ID順）に適用し、過去のTransferの再評価結果へ依存させない。移転後Toは、自身を譲受人とするPositiveなTransferを通常Verificationで変更できない。詳細は [TRANSFER_CLAIM.md](../features/TRANSFER_CLAIM.md)。LostはAutomation専用のOwnership Claimで、確認済みの外部掲載が現在値の唯一の根拠だったときだけ作る。意味は掲載由来の現在値が追跡不能になったことであり、所有放棄ではない。ユーザー操作ではLostを作成・Verification・編集・無効化できない。ユーザーが作るIncident / Lostとは区別する。旧Automation Releaseは履歴として残し、同じSnapshot効果で評価する。ユーザーOwnerがいる個体への新たなAcquireはUnverifiedから開始する。承認によるOwner変更候補は管理画面のUnverified Acquireに表示される。
- Owner Verificationが必要な第三者のSpecification / Repair / Incident / Event / MediaなどはUnverifiedで開始する。適用対象のClaimはPositive時だけSnapshotやギャラリーに反映する。Negative / Unverifiedも表示方法を変えてChronicleに残す。現在のOwnerは管理者判定後も再判定できる。
- 通常のOwner VerificationはCurrent Ownerが他ユーザーのClaimに対して行う。自分のClaimは判定できず、Listing、Identity Correction、AutomationのLostなどは通常ユーザーの判定対象外。管理者は別の強制判定操作で全種類のClaimを判定できる。
- Former OwnerのAcquire / Releaseは同じペアIDを持ち、まとめて判定する。ユーザーAcquireは明示的な取得日と日付Evidenceを要する。Current Ownerがいないときは日付Evidenceを持つ新しいAcquireを自動でPositiveにし、Ownerがいる場合の第三者AcquireはOwner承認待ちにする。同日の競合は小さいClaim IDを先に評価する。
- Claimの通常の「Delete」はinactive化。管理用ハード削除や個体のMerge / Deleteは監査記録を残す別操作。BANされた利用者のClaimもDBからは消さず、公開表示とSnapshot評価で非活性化する。

### 所有権と判定権限の相互作用（設計上の不変条件）

**通常のユーザー操作では、Current Ownerが自分の所有根拠となるClaimのVerificationを変更して、自分自身の判定権限を崩すことはできない。** これは独立した「所有権のロック」機構ではなく、次の規則を同時に適用した結果である。

1. Current Ownerは、IndividualのObservationが有効なClaimとEvidenceを時系列で評価した結果として決まる。プロフィール上のOwned / Formerly Ownedも、この結果に合わせる。
2. 通常のVerificationは**その時点のCurrent Ownerだけ**が、**他ユーザーのClaimだけ**に対して行える。自分のClaimは、Positive / Negative / Unverifiedのどれにも自分で変更できない。自身を譲受人とするPositiveなユーザー間Transferも判定対象外とし、他人作成であっても自分の所有根拠を崩せないようにする。ListingやIdentity Correctionなどは通常ユーザーの判定対象外。
3. Ownerがいる個体への第三者AcquireはUnverifiedで始まり、承認されるまでOwnershipを移さない。Current Owner不在の場合は、必須の日付Evidenceを満たすAcquireを既定の調停規則に従って扱う。
4. 他ユーザーのAcquireをPositiveにしてCurrent OwnerがAからBに移ると、Aは判定権限を失う。Bは自分のAcquireを自己判定できない。Aが再取得を主張する場合は新しいAcquireを出し、その時点のCurrent Owner Bによる判定を受ける。

この性質は、**Claimの作成者・Verification・Evidence・発生日・Observationの現在値・判定権限の連動**に依存する。単独の権限チェックを通しただけでは確認できない。受理済みの自己Acquireの通常Deactivateにも個別の防止処理があるが、それだけをこの性質の根拠としない。管理者の全Claim強制判定、BAN、Merge、Claim削除は通常のユーザー操作とは別の経路であり、Snapshotを再評価して管理画面で判定経路を確認する。

Verificationの操作欄と更新APIは、IndividualのCurrent Owner、Claimの作成者・種類・有効性を同じ条件で判断する。Chronicle上の表示形式は判定権限から独立させ、Positiveはカード、Unverifiedはタグのみ、Negativeは点のみとする。タグや点を開いたポップアップでは、Current Ownerが判定できるClaimにVerification操作欄を表示する。Former OwnerのAcquire / Releaseを一括判定するのは、同時作成された正規のペアだけとし、過去の独立したClaimを`user_guitars`の日付だけからペア化しない。旧データ移行で付与済みの誤ったペアIDや失われたVerificationは自動的に元の判定を推測できないため、対象DBを個別に調査して修正する。

ローカル試作の操作ユーザーはブラウザのタブ単位で保持する。User Profileの表示対象者と操作ユーザーは異なり得るため、プロフィールのOwned / Formerly OwnedとProduct Detailの`Your Guitar`やVerificationの権限を混同しない。Browser Consoleから「このユーザーでTopPageを開く」は新しいタブだけに操作ユーザーを渡し、開いている別タブの操作ユーザーを変更しない。これは将来Identity Platformに置き換える仮の認証境界である。

Ownership、Verification、Claimの無効化、BAN、Merge、Observation、プロフィール分類のいずれかを変更する際は、次を回帰確認する。

| 場面 | 維持する条件 |
| --- | --- |
| Aが所有中にBがAcquireを申請 | BのClaimは未承認で、AはCurrent Ownerのまま。BのOwned / Formerly Ownedへ誤登録しない |
| AがBのAcquireをPositive | BへCurrent Ownerと判定権限が移り、AはFormerly Ownedへ移る |
| 移行前後の自己Claim | A・Bとも自分のClaimをVerificationできず、元Ownerも譲渡後に他人のClaimを判定できない |
| AからBへのTransferが成立 | Bへ所有権と判定権限が移る。Bは受領したPositiveなTransferを変更できず、Aは自己Claimを判定できない。管理者は別経路で強制判定できる |
| A→B→Cの後でA→Bを否定・無効化・削除 | B→Cが自身の適用条件を満たす限り、Cの所有権・Owned区分・判定権限を維持する。Fromの所有者確認は承認時に行い、そのEvidenceを再評価でも使う |
| Aの再取得申請 | AはAcquireを提出できるが自己承認できず、Bの判定を待つ |
| 過去Claimの判定変更・管理者操作 | 変更後のObservation、Individual Snapshot、プロフィール分類と判定権限が整合する |

## 画像審議付きAcquire申請

新規の現在所有申請は、Claimとは別の申請記録から始める。24時間以内の写真提出後にGPT審議を行い、
通過した申請だけAcquireと専用Evidenceを作成する。シリアル不明は申請不可。
画像審議はシリアル・両Challenge一致と、個体比較に明確な矛盾がないことを条件とする。
個体特徴不足やuncertainだけでは不採用にせず、未確認という観察と条件通過の理由をEvidenceへ残す。
Product DetailのMaker・Model・Finishも照合し、登録情報との明確な矛盾がある場合のみ追加の不採用条件とする。
登録値は提出時に固定し、画像だけの観察を記録してから開示する。確認不能や登録値なしは不採用理由にしない。
Former Ownerの履歴登録、Automation Acquire、Transfer、既存Claimはこの追加条件の対象外。

専用EvidenceはメインDBの`acquire_applications.claim_id`でClaimに結び付く。
近接・全体・比較画像、チャレンジ、固定された比較元、診断JSON・文章、ルール版、審議日時を保持する。
一般ギャラリーに画像を公開しない。申請中・不採用は申請者と管理者、通過後はこれらに現在Ownerを加えた閲覧範囲。

結果反映時のOwnerがユーザーならUnverified、非ユーザー／不明ならPositiveでClaimを作成する。
Acquire作成・Evidence紐付け・既存Observation再評価・結果保存を同一トランザクションで行う。
画像審議通過がOwner承認を代替することはない。過去日付のAcquireがFormerly Ownedになる既存規則を維持する。
Transfer等で申請者がすでにCurrent Ownerになった場合は追加せず終了する。
申請の重複送信・古いlease・取消後の提出からClaimを作らない。
詳細は [正式Acquire申請](../features/OWNERSHIP_REQUESTS.md)を参照。

## 重複と移行

同一個体の候補判定ではメーカー、シリアル、モデルの矛盾を検討し、曖昧なら候補をreviewに保持する。管理画面のRepeatedは**同じ正規化メーカー・シリアルを持つ異なるIndividual群**で、同一性が確定した件数ではない。人が残す個体を選んでMergeまたはDeleteする。MergeしたClaimの一部は再承認待ちにする。詳細は [console-claim-administration.md](../operations/console-claim-administration.md)。

旧Observation中心DB向けの移行入口は `ygc claim-status` / `ygc migrate-claims`。Evidenceへの複写は `ygc migrate-claim-evidence`、現在値の全件照合は読み取り専用の `ygc audit-observation-migration`。収集前にはreadiness（Claim未登録の旧Listing Observation、Claimなし個体、不完全なIdentity Claim、未完了shellが0）を確認する。再掲載に紐付くAutomation Acquireは有効な記録であり、Listing未移行件数に含めず、Listingへ移行しない。移行はバックアップを取ってから実施する。これはローカル旧DB向けであり、PostgreSQLへの移行手順とは別。後者は [GCP_BOUNDARIES.md](../migration/GCP_BOUNDARIES.md) を参照。

### Ownership Requestの管理者変更

Browser ConsoleのOwnership Requestでは、画像審議の採否を管理者が理由付きで上書きできる。
元のAI診断と管理者採否は別に保存し、画像審議の採用だけでは既ユーザーOwnerの承認を代替しない。
採用済みAcquireを画像審議で不採用へ変更すると、そのClaimをNegativeにしてObservationを再評価する。
Verificationを強制変更する操作はこれとは別に提供し、従来の管理者Claim操作と同じ処理を使う。
申請状態・Claim・管理履歴・通知の更新は同一トランザクションで処理する。


### 新規Listingの審議

新規登録も申請記録を先行させ、Serial・両Challenge・申請仕様の審議通過後に初めてIndividualとPositiveのListingを作成する。
初期Ownerは申請者。比較個体がないため個体一致は審議対象外とし、その後のAcquireの比較元にListingの全体写真を使う。
同じ正規化Maker・Serialが既存なら、Modelが異なっても新規登録を止めて既存個体のAcquireへ案内する。
同時審議でも重複確認と作成を同一トランザクションに含め、二重登録を防ぐ。
外部掲載クロールのListingとAutomation Acquireはこのユーザー申請フローへ置き換えない。

### ユーザー入力の日付上限

Claimの新規入力・編集とAcquire / Listingの申請日付は未来を受け付けない。
基準時刻はUTC。ブラウザはIANAタイムゾーンを`X-YGC-Timezone`で送り、サーバーはその地域の「今日」と日付を照合する。未指定のAPIクライアントはUTC、不正なタイムゾーンは拒否する。
日時付き入力はUTCの時点と比較しUTCへ正規化する。日付のみのClaimはユーザーの暦日として保持し、UTC午前0時に変換して日付をずらさない。
画面の日付上限・初期日はローカル日付。日時付きClaimの表示はローカルへ変換する。既存デバッグ日付、クロール履歴、内部移行データはこの入力制約で自動修正・削除しない。

### 廃止したOwnership種別

Inheritは廃止し、新規作成APIと入力UIから除外する。移転にはTransferを使用する。過去DBのInheritは自動削除・Transfer変換せず、旧履歴の再評価で所有状態が変わらないよう読取互換のみ維持する。

### 係争決定の例外

現在所有を置き換えるAcquireのDecline・長期無回答に対する係争を実装する。係争中は対象個体の所有関係の変更を停止し、管理者の係争決定だけが同一トランザクション内で対象Claimを判定する。決定済みClaimは通常Ownerおよび通常の管理者強制判定から変更できず、理由付き再審議を経由する。Claim作成者は維持する。後のOwnerが過去の係争を通常Verificationで変更することもできない。詳細は[Ownership Disputes](../features/OWNERSHIP_DISPUTES.md)。
