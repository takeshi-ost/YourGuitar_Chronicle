# Authentication Test — GPT連携

この文書はClaimを変更しない実験用キューの仕様。正式な登録・所有申請は[Listing / Acquire申請](OWNERSHIP_REQUESTS.md)を参照。

Browser Console → **Authentication Test → 実験用キュー** holds multiple test submissions. Each addition
gets an immutable revision, even when an application ID is reused. An identical
pending/processing upload is deduplicated. Completed submissions are never overwritten.
This remains an experiment: actual Claim/Evidence/ownership records are not updated.

### Setup and storage

Submissions and the connection key are stored separately at
`YGC_DATA_DIR/direct-review/queue.sqlite3` (default `app/data/direct-review`).
Existing queue records and keys are preserved when upgrading to the GPT-only UI.
The first connection setup creates a key only if one does not already exist.
The key survives page reloads and server restarts and has no automatic expiry. **接続キーを失効** revokes it explicitly,
releases in-flight leases and preserves all submissions/results. **保存済み接続設定を
表示／接続を有効化** retrieves the same key, or creates one after revocation.
The store directory has mode 0700 and its SQLite file mode 0600; the key is stored
inside that file, not encrypted. Keep this local experimental store private.

1. Restart WebUI, reload the Console, and select three images plus expected text.
2. Click **① テスト申請を追加** for each test. Previous submissions stay in the queue.
3. Configure the generated stdio MCP command in the desktop client, substituting the
   experiment key for `PASTE_TOKEN`. Preserve existing client configuration. Do not
   paste the key into a chat. Local Codex configuration is normally
   `~/.codex/config.toml`; see the [official MCP setup](https://learn.chatgpt.com/docs/extend/mcp).
4. Reconnect/restart the desktop client to load the **new tool schemas**. Image fetch,
   failure and result submission now require `lease_token` returned by the pending
   tool. Old tool calls without this value fail safely. Refresh the scheduled task's
   saved instructions with the generated prompt, including the snapshot continuation
   through `remaining_revisions`. Existing one-item instructions process only one item per run
   if the caller honors the updated schema.
5. Keep the Mac awake and desktop app and YGC running for local scheduled execution.
   No schedule is created or modified by YGC. Check the scheduler's tool permissions:
   acquiring a job now writes queue state and is correctly marked as a write tool.
6. The Console displays pending/processing/completed/error/cancelled records and
   UTC receipt/start/completion timestamps. It refreshes every 15 seconds while the
   page is visible, when the checkbox is enabled. **③** also refreshes manually.
7. Select a row to view observations, the report and structured result. Download JSON
   or text before deleting records. Retry errors or cancel unwanted submissions.
   Only completed/error/cancelled records may be deleted (with UI confirmation).

**② ローカル接続診断** initializes MCP, lists tools and pings only. It does NOT
claim a job or fetch its images. Actual image visibility must be checked in the client.
The existing stdio bridge and local endpoint are unchanged:
`python -m ygc.direct_mcp_bridge --url http://127.0.0.1:8000/api/experiments/direct/mcp`
(use the actual WebUI port). The bridge reads `YGC_EXPERIMENT_TOKEN`, disables HTTP
redirects and proxy environment variables, and never calls an inference API.

### Queue and retry semantics

- `ygc_pending_test` atomically claims ONE oldest pending row (`BEGIN IMMEDIATE`),
  sets processing, increments attempts, and returns application ID, revision and a
  random per-attempt lease token. Empty queues return `jobs: []`, including when all
  records are currently processing. This is a mutating, non-idempotent tool.
- `ygc_test_image` requires that lease and returns actual EXIF-stripped JPEG image
  blocks. Expected text is not exposed. Source and prepared-image SHA256 hashes are
  saved along with sent dimensions.
- `ygc_submit_test_review` strictly validates the claimed ID/revision/lease and saves
  structured observations, deterministic text checks, the provisional decision,
  reason codes, human-readable report, prompt/rule versions and UTC completion time.
  `reviewer_model` is optional self-reported metadata, not attestation; unknown is null.
  The receipt contains no expected text. Identical completed submissions are safe to
  retry with the same lease; conflicting or stale submissions are rejected.
- `ygc_fail_test` records an operational error without generating a False decision.
  It stops automatic processing of that row until an operator requests retry.
- A lease lasts two hours from claim and survives server restart. Expired leases
  become pending on the next queue access, until three timed-out attempts have been
  made; then they become error. Manual retry preserves attempt history and permits
  another attempt. No heartbeat or lease extension is implemented. Late submissions
  after expiry/reassignment/cancellation/revocation are rejected.
- The first pending call omits `remaining_revisions` and snapshots current pending
  revisions. It claims one row and returns the rest as `remaining_revisions`. After
  submitting successfully, pass that exact returned list to the next pending call;
  keep updating it from responses until empty. An empty list never starts a new
  snapshot. Processing/completed/cancelled/deleted rows are skipped. New submissions
  cannot enter this continuation list. Each row is leased only when it is its turn,
  so waiting for earlier rows does not consume its two-hour lease.
- There is no three-item limit. Instructions request all initially pending items,
  sequentially, stopping on errors or runtime/usage limits. Unclaimed rows remain
  pending for a later run. Concurrent runs claim distinct rows. Snapshot continuation
  is carried by the caller (not an authenticated server-side batch); clients must not
  start another snapshot in the same run or add revisions to the returned list.
  The prompt version is `direct-queue-v3-gpt-only`.

Maximum retained storage is 100 submissions and 256 MB of encoded image payloads.
Each input image is at most 12 MB; preparation uses the existing 3000px limit and
rejects encoded images over 8 MB. There is no automatic retention deletion. Remove
unneeded terminal records in the Console when full. SQLite may retain free pages
for reuse after deletion; this is not a secure-erasure feature.

This separate SQLite store is not the main Chronicle DB. Its backup/restore must be
managed separately; do not assume the normal application DB backup includes it.
A key holder can submit observations; these are not cryptographically attested AI
outputs. Within one model chat, image context is shared despite instructions to
transcribe separately. Human review/calibration remains separate. Formal applications use their own
Evidence workflow described in [Ownership Requests](OWNERSHIP_REQUESTS.md).

The local HTTP endpoint remains a minimal stateless MCP 2025-03-26 tools transport
(JSON replies, no SSE, sampling or MCP session persistence). Request bodies are
bounded to 100 KB; GET/DELETE return 405. Loopback client/Host checks, Origin checks
and bearer authentication remain mandatory. This does not provide a public/cloud
endpoint, OAuth integration, or changes to the actual Claim/ownership database.

### 判定と構成

認証テストはGPTのMCP連携のみです。OpenAI/Gemini推論API、ローカルOCR・
特徴点・CLIPSeg、Google Sheets実験のコード・画面・専用エンドポイントは削除しました。
古いブラウザー保存APIキーはConsole読込時に当該2項目だけ削除します。
サーバー環境変数のAPIキーは使用しません。既存の画像やDB、モデル保存ファイルは削除しません。

`authentication_evidence.py` が画像前処理・厳密な結果スキーマ・読取指示・文字照合、
`authentication_decision.py` が暫定採否、`direct_experiment.py` がMCPとレポート、
`direct_queue.py` が永続保存を担当します。

近接画像のSerial、両画像のChallengeが期待値と一致し、個体比較に明確な矛盾がなければTrueとします。
一致根拠の不足、uncertain、比較材料不足だけでは不採用にしません。曖昧な反射・付着物は
一致・矛盾の根拠から除外します。写真間のつながりや撮影再利用は採否条件に含めません。
文字照合は空白・ハイフン・大小文字のみ正規化し、I/1やO/0は区別します。
運用エラーはFalseとせずerrorとして記録します。一致確率は作成しません。
