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

### Incremental Crawl progress and run history

Browser Console displays the per-run stages: summary screening, detail fetching,
manufacturer and serial extraction, identity reconciliation, and Claim-backed DB
registration. Each incremental click saves stage counters to `crawl_runs` while
running and when it finishes or fails. The log shows the latest 20 runs for the
selected category and manufacturing-year range; older rows remain in SQLite.
A restarted search resets the scan cursor but preserves its run history.
The matching stage may also process previously staged pending candidates after an
interrupted run; the log's `candidate_total` is the actual reconciliation queue.
Historical runs predating these fields have no stage counters.

### User moderation and User Detail

The local administrator can edit a user's display name, account type, residence,
bio, four profile visibility settings, signature guitar, avatar upload, and BAN
status from Browser Console User Detail. Database IDs, creation timestamps,
stored image paths, and calculated counts are read-only. Signature choices must
refer to an owned Individual. The administrator endpoint validates values before
a single transaction updates the user, records BAN transitions in
`user_admin_actions`, and rebuilds affected Individuals from Claims. Existing
users migrate to `normal` without changing their data.

- `normal`: existing behavior.
- `silent_ban`: Claims remain stored and retain their original status but have no
  public effect on Individual snapshots, specification/media selections, discovery lists, or notifications. Their author sees their own Claims as
  active; their own profile and Product Detail preview the Claim-derived state
  within a rolled-back database savepoint. Their future Claims follow the same
  rule. A different viewer sees neither their Claims nor their profile's guitar
  relationships. An Individual backed only by suppressed Claims is absent from
  public product lists and detail endpoints.
- `ban`: account profile and ordinary account access are unavailable; the user
  cannot publish new Claims or vote. Past Claims and media are hidden and have no
  public effect. Good/Bad votes and existing notifications from the user are
  excluded from visible totals and feeds. Data is retained, and changing back to
  `normal` restores the prior Claim/interaction records.

The current prototype selects a user through a client-supplied ID. It has no
server-side login/authentication, so this viewer distinction is not an access
control boundary. Before exposing the service to untrusted clients, integrate
real authentication and derive the viewer ID on the server.
