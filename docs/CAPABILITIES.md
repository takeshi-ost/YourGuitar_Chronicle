# YGC Capabilities

Your Guitar Chronicle で現在できることを、**一般ユーザー**と**管理者（Browser Console）**に分けて簡潔にまとめます。

> **更新ルール**
> Project paths and identifiers are phase-neutral. Phase labels are used only in UI text, documentation prose, and comments.
> このドキュメントは現行機能の一覧です。機能の追加・削除・仕様変更を行う場合は、同じ変更セットでこの文書も更新します。

## ユーザーとしてできること

### アカウント
- User / Shop アカウントを作成する
- Display Name、Account Type、Country、Regionを編集する
- アバター画像を登録する
- 自分に紐づくギターを確認する

### ギターを探す・見る
- 登録済みIndividualを一覧・検索する
- Maker / Model / Finish / Year / Serialなどの現在値を見る
- Current Owner / Locationを見る
- 現在のSpecificationを見る
- ChronicleとしてClaim履歴を見る
- Chronicleを出来事順 / 入力順で切り替える

### 自分のギターを登録する
- 新しいギターを登録する
  - Maker / Model / Finish / Year / Serial
  - 代表画像
  - Claim memo
- 最初のListing Claimを作成し、自分を初期Ownerとして登録する
- 同一Maker / Model / SerialのIndividualが既に存在する場合は重複作成を防止する

### 既存Individualを自分のChronicleへ追加する
- 「Add to Your Chronicle」からOwnership Claimを作成する
- Ownership Tagとして Acquire / Transfer / Inherit を選択する
- 日付、以前の所有者・入手元、メモを記録する

### Claimを追加・編集する
- Specification Claimを追加する
- Repair Claimを追加する
- 自分が現在OwnerのギターをOwnership / ReleaseとしてReleaseする
- 自分が作成した編集可能なClaimを編集する
- Listing Claimを直接編集せず、Identity Correctionとして訂正する
- Identity Correction時はMaker / Model / Serialの重複を再チェックする

### Claimへの参加
- ClaimへVoteする
- ClaimのEvidenceや出典を確認する

## 管理者としてできること

管理者操作はローカルの **Phase 1 Browser Console** を前提とします。

### Reverb収集
- Reverb API Tokenを設定する
- 複数クエリをBatch Crawlする
- Year Min / Year Max / Limit / Workersを指定する
- 取得済みListing IDをスキップする
- Detail判定済みの対象外Listingを期限付きキャッシュして再取得を抑制する
- Crawl進行状況・query別結果を確認する

### Individual / Claim確認
- 全Individualを一覧・検索・ソートする
- Current Snapshot、Specification、Chronicleを確認する
- Reverb由来・ユーザー由来を同じClaim-centered構造で確認する

### 管理用削除
- Claimをハード削除する
  - 削除後はIndividual Snapshotを再構築する
  - 最後のactive Listing Claim単体は削除不可
- Individualをハード削除する
  - 関連Claim、Observation、User link、Media DB recordなども削除する
  - 実験データのSerial重複を解消できる

### DB管理
- SQLite DBをバックアップする
- バックアップからDBを復元する
- DBを初期化する
- Claim Migration / Snapshot Rebuildを実行する
- 既存Reverb Listing Claimの不足項目をBackfillする
- Claim-centered構造のreadinessを確認する
- StatisticsはClaim-centered基準で集計し、Serial Listingsはactive Listing ClaimのSerialを数える

### ユーザー管理
- アカウントを作成・選択する
- User Account情報を確認・編集する
- 所有ギターとの紐づきを確認する

## 共通のデータ構造

Reverbからの自動登録とユーザーによる手動登録は、入口だけが異なり、どちらも基本的に同じ流れを通ります。

```text
入力
  ↓
Listing Claim用データへ正規化
  ↓
Individual照合 / 作成
  ↓
Claim保存
  ↓
必要なProvenance保存
  ↓
Individual Snapshot再構築
```

- **Claim**: 履歴・意味情報のSource of Truth
  - Owner Change / Releaseは新規作成では **Ownership** Typeへ統合され、`ownership_kind`（Acquire / Transfer / Inherit / Release）で意味を区別する
  - 既存のlegacy Owner Change / Release Claimは互換性のため読み取り可能
- **Individual**: active Claimから作られる現在状態のSnapshot
- **Observation**: Reverb等の取得元・証拠・provenance

このため、入力元が増えても同じClaim-centeredパイプラインへ接続できます。


- UI表記では `Individuals` を `Product List`、`Individual Detail` を `Product Detail` とする。内部データ名・API・実装名は従来どおり `individual` / `individuals` を使用する。


- Ownership ClaimはWebUIでも単一の共通モーダルと単一のsubmit処理を使用し、Tag (`acquire` / `transfer` / `inherit` / `release`) をバックエンドの `/ownership-claim` に渡す
- Add to Your Chronicle は共通Ownership UIをAcquire固定で開く。Formerly Ownedも現在非所有として扱い、Product Detailでは通常の非所有Productと同じAdd to Your Chronicle導線を表示する
- Product Detailの Add Claim → Ownership では Transfer / Release / Inherit をTagとして選択できる
- 現時点ではAcquireだけが所有開始し、SnapshotのCurrent OwnerとLocationをUser情報で上書きする。Transfer / Release / Inheritはすべて所有終了として共通処理し、Current OwnerとLocationを空欄へ戻す。Owned Guitars / Formerly Owned Guitars の分類も操作順ではなく、Claimの日付順で再構築したSnapshotのCurrent Ownerを基準に同期する。User Location変更時はOwnership Claimを持つProductのSnapshotも再構築する。将来は譲渡先Location等を含むTag別処理や必須入力を追加する
- Chronicle上のOwnership Claimバッジは Ownership / Acquire のようにType名を重ねず、Acquire / Release等のTag名だけを表示する

- Ownership Claimカードの主文はTag別に表示する: Acquire=`A became the owner of this product.` / Release=`A released this product.` / Transfer=`B acquired this product from A.` / Inherit=`B inherited this product from A.`。AはClaim作成者、BはOwnership入力の関係者。


- Incident ClaimはProduct Detailの Add Claim → Incident から作成する
- Incident Tagは Damage / Lost / Theft。DateとDetailを記録する
- Incidentは所有状態に関係なく追加でき、Current Owner / Location / SpecificationのSnapshot値は変更しない
- Chronicle上のIncident ClaimバッジはIncidentというType名ではなくDamage / Lost / TheftのTag名を表示する


- Event ClaimはProduct Detailの Add Claim → Event から作成する
- Event Tagは Exhibition / Performance / Recording / Auction / Other。DateとDetailを記録する
- Eventは所有状態に関係なく追加でき、Current Owner / Location / SpecificationのSnapshot値は変更しない
- Chronicle上のEvent ClaimバッジはEventというType名ではなく各Tag名を表示する
- Event Claimカードは暗い紫、Tagバッジは同系統の明るい紫で表示する


- Media ClaimはProduct Detailの Add Claim → Media から作成する
- 初期版は画像のみ対応し、JPEG / PNG / WebP / GIF、最大12MBとする
- Media Claimは1 Claimにつき画像を最大10枚まで追加でき、Date / Captionを共通情報として記録する
- 画像選択欄は1枚選択すると次の欄が表示される方式とし、Chronicleカード内では全画像を小さなサムネイル列として表示する
- Media Claimは所有状態に関係なく追加でき、Current Owner / Location / SpecificationのSnapshot値は変更しない
- Media Claimカードは暗いアンバー系、Tagバッジは同系統の明るい色で表示する
- 将来の動画・音声対応を見据え、media_assetsのmedia_typeを利用して拡張可能な構造を維持する


- Product Detail上部ではアップロード済み画像をギャラリー表示し、代表画像を先頭に左右の三角ボタンで循環閲覧できる
- ギャラリー対象はYGC内に保存された画像（初期登録の代表画像およびMedia Claim画像）で、外部Listing画像は含めない
- Media Claimカード内の画像は履歴確認用の小さなサムネイル表示とする

- Product Detail上部の代表画像ギャラリーは、画像の左右に小さく控えめな三角ボタンを固定配置して切り替える


- UserがEdit可能なClaimの編集画面には Delete Claim を表示する
- Delete Claimは物理削除ではなくDeactivateであり、claims.statusをinactiveに変更する
- DeactivateされたClaimは通常のChronicle、Snapshot計算、Product ListのClaims件数から除外する
- Media ClaimをDeactivateした場合、そのClaimに紐づく画像はProduct Detail上部の画像ギャラリーからも除外する
- Listing / Identity Correctionは従来通り通常Edit対象外のため、このDelete Claim操作の対象外とする


- Add Claimは現在Owner / 非Ownerのどちらにも表示し、非Ownerは Specification/Repair / Incident / Event / Media を追加できる
- Ownership Claimは現在Ownerのみ追加できる
- Specification/Repair / Incident / Event / Media には Owner Verification を適用する
- 現在Owner本人が作成したClaimは作成時から verification_status='positive' とし、Owner Verification UIは表示しない
- 非Ownerが作成したClaimは必ず verification_status='unverified' で開始する
- 現在Ownerだけが第三者Claimを Positive / Negative / Unverified に変更できる
- Third-party Specification/RepairはPositiveのときだけSnapshot / Current Specificationへ反映する
- Third-party MediaはPositiveのときだけProduct Detail上部の画像ギャラリーへ反映する
- Negative / Unverified ClaimもChronicle上の記録としては表示する
- Listing / Ownership / Identity CorrectionはこのOwner Verificationフローの対象外とする


- Owner VerificationによるChronicle表示:
  - Positive: 通常のClaimカードを表示
  - Unverified: Claimタグだけを表示し、クリックでClaim全文をポップアップ表示
  - Negative: ◉だけを表示し、クリックでClaim全文をポップアップ表示
- ポップアップ内には通常カードと同じ内容を表示し、現在OwnerはそこでPositive / Negative / Unverifiedを変更できる


- 非OwnerのAdd Claimには Former Owner を表示する
- Former OwnerはAcquisition Date / Release Dateを必須、Detailを任意とする
- Acquisition DateはRelease Dateより前でなければならない
- Current Ownerが存在する場合、Former OwnerのRelease DateはCurrent Ownerを成立させた最新のOwner設定Claimの日付より前でなければならない
- Former Owner登録はAcquire / Releaseの2件のOwnership Claimを1トランザクションで作成する
- AcquireのDetailに入力Detailを保存し、Releaseは通常主文のみとする
- Claimのauthorは入力Userとなるため、主文の名前も入力Userになる
- 登録Userのuser_guitarsはformer_ownerとして追加・更新し、Formerly Owned Guitarsに表示する
- Former Owner ClaimはOwnership系のためOwner Verification対象外


- Former Owner由来のOwnership Claimは通常Ownershipと明示的に区別し、ownership_source='former_owner' と共通 ownership_pair_id を持つ
- Former OwnerのAcquire / Releaseペアは作成時に verification_status='unverified' とする
- Current Owner本人が作成する通常Ownership Claimは従来どおりPositive扱いで、Owner Verification UIを表示しない
- Current OwnerだけがFormer Ownerペアを Positive / Negative / Unverified に変更でき、片方を変更すると同一ownership_pair_idの2 Claimを同時更新する
- Former Owner OwnershipはPositiveの場合だけOwnership Snapshot再生に参加する
- Current Owner不在時はFormer Owner ClaimをVerificationできるUserがいないため、第三者申告だけでは最後のOwner情報を書き換えられない
- 既存DBで旧Former Ownerフローから作成済みのAcquire / Releaseペアは、former_ownerのuser_guitars日付と一致する場合にUnverifiedペアへ移行する


- Listing Claimは常に verification_status='positive' とし、Owner Verification対象外
- 既存DBのListing Claimも起動時マイグレーションでPositiveへ補正する


- User View上部のアカウントハブは本人向けのホームヘッダーとして表示する
- 実データ表示: Avatar / Display Name / You / Location / Owned / Formerly Owned / Claims
- Notifications / Messages / View Profile は将来機能へのダミー入口として表示し、現時点では無反応
- Edit Your Chronicle は既存の /user-view/edit への実動入口


## In-app Notifications
- User ViewのNotificationsはYGC内部通知として実装する
- Owned Guitarに他UserがClaimを追加した場合、Current Ownerへ claim_added 通知を作成する
- Former OwnerのAcquire/Releaseペアは1件の通知として扱う
- Owner VerificationでClaimの状態が変更された場合、Claim authorへ claim_verified 通知を作成する
- 自分自身がOwned Guitarへ追加したClaimでは通知を作成しない
- Current OwnerがYGC Userでない場合はアプリ内通知のrecipientが存在しないため通知を作成しない
- User Viewでは未読件数、通知一覧、個別既読、全件既読を提供する
- 通知クリックで対象IndividualのProduct Detailへ移動する
- Push通知は未実装。将来の外部Push配信層とは分離する


## User Profile Page
- /users/{user_id} で本人・他User共通のプロフィールページを表示する
- 実データ: Avatar / Display Name / Account Type / Location / Member Since / Owned / Formerly Owned / Claims / Owned Guitars / Formerly Owned Guitars
- Followers / Following は現時点では 0 のダミー表示
- Bio / Recent Activity は将来機能のプレースホルダー
- 他User閲覧時の Follow / Message は現時点では無反応のダミー
- 本人閲覧時は You 表示と Edit Your Chronicle への入口を表示する
- User ViewのView Profile、Claim author、YGC UserのCurrent OwnerからUser Profileへ遷移できる
- User Profileのギターカードから対象IndividualをUser Viewで直接開ける


## Top Page / Guest Mode
- 従来の /user-view は公開Top Pageとして扱う
- Guestでも Product List / Product Detail / Chronicle Claim を閲覧できる
- Guest時のアカウント欄は Sign In / Create Account の導線に差し替える
- Guestが Add to Your Chronicle / Add Claim / Good / Bad など参加操作を行うとアカウント導線へ移動する
- Guestには User Profileへのリンクを表示せず、Current Owner / Claim authorは名前のみ表示する
- User ProfileはYGCメンバーのみ閲覧可能とし、Guestが直接URLへアクセスした場合はMembers only表示にする
- Logged-in Userでは従来どおりNotifications / Messages / View Profile / Edit Your Chronicle等を表示する
- 開発中の互換性のためURLは当面 /user-view のまま維持する
