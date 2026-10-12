# Closed-test release candidate — 2026-10-12

## Scope

Finalize the cloud UI fidelity work against main `7ca7fd8`: catalog/detail/Chronicle,
Profile and Settings, member connections, Claim forms and owner responses,
Listing/Acquire workflows, Transfer/Release, dispute participant/admin flows,
notifications, New Discovery (global activity), statistics and country map.
Follow activity and Messages remain deferred.

Recent performance changes reduce duplicate reads, aggregate row Favorites, share
short-lived tab-local self display data after fresh identity/service checks, reuse
public/static HTTP responses, pool HTTP database connections and render photos
before unrelated list/Chronicle completion. Negative dots and compact Favorite
status layout have also been corrected. Avatar reads update their controls on
completion, including reloads with an existing image. No schema migration is introduced.

## Verification requirements

Run the standard `scripts/run_tests.py` entry point for Python, JavaScript,
Chromium and disposable PostgreSQL 18.6. PR checks also validate pinned dependency
closure and schema artifacts. PostgreSQL pool acceptance and formal Claim/dispute
browser checks are now included in the standard runner. All 21 independent
browser groups run and report failures; one failure no longer suppresses later
coverage. The CI job budget is 25 minutes for the expanded suite.

The local environment cannot perform the complete Chromium/PostgreSQL acceptance;
GitHub PR checks must pass on the exact candidate commit. Synthetic fixtures do
not use live identities, review photos or Cloud SQL. Existing evidence in the
handoff records describes the dates/versions actually tested; it is not proof of
a later candidate's CI result.

## Deployment and rollback

The pre-finalization staging reference is `ygc-staging-accounts-ui-20261012al`,
100% traffic, image digest
`sha256:06bf37d1fa75562bf2bd349e160ef42f4009c2fa112681a5b6d18c991160919b`.
Production source bytes in its submitted build package match this candidate's
source. Final deployment should use an immutable image digest labelled with the
verified Git commit. Record the final commit, CI run, build and revision together.
Rollback uses the previously deployed digest/revision. Environment variables,
service identity, IAM, job schedules and database contents are outside this change.

## Known remaining issues

- Further speed work remains: MPA document/DOM reconstruction, authentication and
  image/API latency, and sequential waiting during some navigation operations.
- Initial identity restoration can show a transient session status message.
- Short-lived self display reuse is not authorization; all writes still use the
  canonical API and fresh revision checks. Explicit refresh and identity changes
  invalidate display data.
- Closed-test access restrictions, backup/restore operating procedures and
  participant invitations are later major items ④⑤. This candidate does not by
  itself mark the closed test ready to start.

## Review boundaries

Private Evidence/Acquire review photos remain separate from public presentation.
Only accepted Listing overview or selected positive public media may be a public
representative image. Public locations use canonical Accounts visibility.
Ownership/Verification/dispute authorization and resolved-Claim locks must retain
the combined invariants in `docs/architecture/CLAIM_CENTERED_ARCHITECTURE.md`.

Working logs, browser evidence screenshots and temporary `work/` files are not
part of the release source commit. They remain available in the local workspace.
