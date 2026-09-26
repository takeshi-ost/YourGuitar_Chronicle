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
