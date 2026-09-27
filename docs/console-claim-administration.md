# Browser Console のClaim管理

ローカルのBrowser Consoleで各ClaimのVerificationをPositive（許可）・Negative（不許可）・Unverified（未確認）に変更できる。著者・現所有者・Claim種別の制限を受けない。管理者判定後は通常のOwner Verificationで上書きできない。管理者は再変更できる。

- Consoleページは、接続元とHostの両方がlocalhost/loopbackの場合にのみ、プロセスごとの管理トークンを返す。管理APIはそのトークンとローカル接続を検証する。ユーザーアカウントのadminロールではなく、現在のローカル試作環境向けの管理権限。公開サーバー・リバースプロキシ構成での認証には別途対応が必要。
- 判定・削除後はClaimから個体のスナップショットを再構築する。所有履歴のペアは一緒に変更する。Identity Correction、Specification、Ownershipの適用はPositiveのものに限定する。
- Listingが不許可でも、個体を参照するための基礎識別情報（Maker/Model/Year/Serial）は維持する。Listingの所有者・ロケーション・Finishの主張は適用しない。
- 最後の有効なListing Claimを削除する場合は、個体と関連記録も削除することをUIで明示して確認する。APIでも明示的な追加フラグが必要。それ以外は対象Claim（ペアの場合はペア）だけ削除して再計算する。
- 管理操作をclaim_admin_actionsに記録する。削除後も対象ID・操作・変更前の判定・日時は残る。復元用バックアップではない。

### Pending ownership and duplicate resolution

Unverified Acquire counts only active pending acquisitions whose approval (including
paired Claims) changes the current owner. The existing chronological snapshot
reducer runs under a rolled-back savepoint, so viewing the queue persists no changes.
Location-only changes and superseded or same-owner acquisitions are excluded.

Repeated now counts **groups of multiple DB Individuals with the same normalized
manufacturer and serial**, not multiple external listings of one Individual. Model
is intentionally excluded from this candidate key. Candidates require human review;
a shared serial alone is not proof of identity.

The local-admin modal requires an explicit survivor. Merge retains observations,
Claim IDs and their responses/evidence, media, and user associations. Incoming
Listings become Acquire Claims (`merged_listing`), retaining original Listing items
as provenance. Incoming positive ownership, identity, and specification Claims
become unverified; negative Claims retain their decision. The survivor's Claim-driven
state is rebuilt, never overwritten directly. Other records retain their status.
Signature selections follow the survivor. Admins can approve incoming Claims normally.

Delete removes the other Individuals and their related DB records, clearing their
signature selections. It does not merge history and requires a destructive-operation
confirmation in the modal. Stored media files follow the existing deletion policy.
Both operations are atomic, logged, require the local admin capability, and reject
stale or mismatched group membership. Main and unrelated Individuals are unaffected.
