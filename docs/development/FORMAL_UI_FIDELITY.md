# Formal UI fidelity audit — 2026-10-08

## Current status — 2026-10-11 resume

**Header/application and per-Claim action alignment are implemented locally. Whole-page equality is not claimed: the explicitly retained projection differences and accepted unported scope remain.** The original audit table below is historical, not the current completion checklist. Units9–15 at the end supersede corresponding earlier open items; unit15 closes the former Owner Verification / authored-edit placement items. All changes are preserved, uncommitted, on `fix/local-ui-fidelity`.

On resumption, saved passing tests were reused. Only the changed header/profile button styles were measured again in a single targeted headless run. No new agent/reviewer, Chrome reconnect, full regression, Cloud SQL connection/start, upload or remote publication was performed. Public/member information scope remains unchanged by explicit instruction; its remaining omissions are current design differences, not inherent Web limitations.


## Baseline and protection

Acceptance source: existing `/user-view` TopPage/UserProfile and shared ProductDetail, not the previous formal shell. Original checkout `/Users/t_oshita/Documents/GitHub/YourGuitar_Chronicle` is clean at `6e2d90138cfadb42e638272ca7c990021465242d`. task-2 is clean at `aaf07c94161afd8a086f30b081d84e529c95e2dc`. task-3 is clean at `7ca7fd87fc3612c473d2ad7e6ad6eb3c47761854`. Checked git status including untracked files. No tracked local UI changes between original and integration baseline in user_view_html.html, pages/user-view.js, pages/user-view.css, product-detail.js or themes.css.

Isolated clone: task-7/ygc-ui-fidelity, branch `fix/local-ui-fidelity`, based on 7ca7fd8. Original checkouts untouched. No push, PR, merge, deployment, real database/settings or infrastructure changes authorized. AGENTS.md, UI_STRUCTURE.md, DEVELOPMENT_WORKFLOW.md and Claim architecture invariants read. No .agents directory in task-3; no relevant skill found in original .agents.

## Initial source comparison (screen/interaction checks pending)

| Area | Local acceptance source / behavior | PR64 discrepancy | Status |
|---|---|---|---|
| Header/logo/theme | user_view_html + renderAccountHub, shared themes | logo assets shared but account hierarchy, guest copy and actions differ; cloud saved theme not connected | open |
| Placement/width/height/spacing/font | user-view.css, content-frame, #detail, viewport cap | custom overrides and absent #detail bypass canonical spacing and image rules | open |
| Wording | shared i18n and local page labels | independent dictionary says Guitar catalog / Choose a guitar / Latest recorded first | open |
| List/search/order | one toolbar input, live filtering incl finish/year, sortable headings, favorite/Claim columns | separate form + submit + 4-way select, 24-row API paging, absent columns | open; API wiring work, not a Web constraint |
| Selection/history/scroll | selection persists through filtering, local list navigation and table resizing | search clears selected guitar, no shared list/table scripts | open |
| Product image/title/actions | shared ProductDetail and #detail image frame, local action menus | independent placeholder/header/link stack, no shared renderer | open |
| Specification accordion | shared section/header/body, triangle button | native details/summary with distinct margins | open |
| Chronicle tags/order/cards | orderedClaims by occurrence and ID, corrections beneath targets; positive cards, unverified tags, negative dots | independent details cards, ID cursor ordering, inert tags/points | open |
| Modal/focus | YGCOverlays, focus/scroll restore; compact × close | overlays shared; detail back link differs and Escape only tests native dialogs | open |
| Login | local dummy form/Test user vs real credentials | real Identity Platform is required; account registration leaves shell | real auth difference; layout still fixable |
| Profile hero | profile-name/meta/bio/stats/actions | definition list including editing fields; duplicate account controls | open |
| Owned/Formerly/Favorite | profile sections with same toolbar/table/selection | self-account controller tables lack canonical layout/filter/order | open |
| Settings | dedicated User Settings view | profile editing, visibility and avatar forms stacked in profile | open |
| Claim input/edit | per-kind forms and Claim actions in Product Detail | selfClaims/account intent forms | open; not a Web constraint |
| Applications | important-information rows and local request modals | account application sections | open |
| Notifications | header opens shared notification modal; read/unread styles | profile section anchor and inline list | open |
| Follow/member search | local profile follow/connections; member naming and authorized icons | separate members page has own layout; authorization to preserve | open |
| Responsive | canonical <=900 compact overlay, horizontal position links, 390/320 | shell overrides nav to wrap and member header to static | open |

## Explicit exclusions and decisions

Accepted unported scope: cross-guitar UserChronicle, NewDiscovery/statistics/map, upload interactive QA. Do not retry previously rejected uploads through any path.

Other unresolved differences must not be silently labeled accepted exclusions. Public profile/Owned/Formerly/photo exposure must not expand. `cloud-public-catalog.js` validates a public DTO with specifications and public Chronicle only; public DTO does not supply owner/location/photo. Preserve this boundary; private Evidence is not a replacement image. Existing self APIs and authorized member icons/Follow stay unchanged. Authentication is demonstrably Identity Platform via cloud-auth-loader/identity-platform-auth; dummy actor selection cannot become production auth. Missing API connections and implementation effort are work remaining, not inherent Web limitations.

## Verification

Functional tests and visual/behavior parity are separate gates. No parity claim until matching synthetic records, identity, locale, theme and viewport are compared. Required widths: desktop, 390, 320. Browser comparison uses the Mac Chrome extension; no Computer Use getApp diagnostic. Automated regressions may use isolated fixtures. Initial audit above is source evidence, not screen verification.


## Implemented corrections and evidence

This is a partial fidelity correction, **not acceptance of full parity**. All changes are uncommitted on the isolated branch. Initial table above is the before-change audit.

| Local baseline → discrepancy | Correction | Verification / remaining difference |
|---|---|---|
| Shared ProductDetail → bespoke HTML and native details | Reuse `YGCProductDetail.render`, canonical `#detail`, title/specification/Chronicle accordion and no-picture SVG; allowlist only shared display scripts | Automated accordion/XSS/asset checks; Chrome extension geometry below. Public fields only; owner/photo/author data still absent |
| Shared tag/dot/card presentation → independent cards | Positive claim-card, interactive nonpositive metadata overlays, shared loaded-claim ordering; lossless bigint IDs | JS ordering/correction tests and browser regression. Full cross-page order and omitted correction target still unresolved |
| Local compact close keeps selected guitar → deselection/navigation | ×, Escape and outside close retain selection; shared list keyboard navigation/table resizing | JS close/URL preservation + browser navigation; full manual history matrix not complete |
| Live search incl finish/year and sortable headings → submitted form/select | Debounced live search, raw trailing-space preservation, selection retained; heading sorting through public field SQL allowlist | Real isolated Postgres ten sort directions and cross-field search; browser search and sort arrows. Still 24-row paging, Refresh, missing Favorite/Claim columns |
| Local title heart → independent Favorite section | Compact authorized Favorite control with canonical title row | Existing Favorite visibility regression; no new public/private scope |
| Profile name/meta/bio → definition list | Canonical hero classes, avatar sizes, stats and edit action | Automated profile-name check; remaining sections are still account-oriented |
| Notification overlay → inline section anchor | Existing authenticated notification controller in shared modal with focus restoration | Automated open/Escape/focus check. Detailed per-notification layout not manually matched |
| Guest account header → different copy/order/spacing | Local guest title, Sign In/Create Account ordering and palette; empty middle grid slot, rounded close; ceil header measurement | Chrome extension same-theme guest header height 171.945px at390/320; local detail top186px. Long translated profile titles can wrap to prevent320px overflow; this exception still needs local-profile visual comparison |

### Chrome extension comparison conditions

One dedicated Chrome extension tab; local-only synthetic fixture `app/tests/manual_fidelity_fixture.py`. Both servers use the same external-network-blocking CSP, English, Sunburst, guest, fixture guitar29. No uploaded image bytes, production data, account/settings changes or external network used. Local fixture seeds temporary SQLite; formal fixture uses synthetic DTO/SDK. Local owner/claim content is intentionally NOT fully equivalent to public DTO, so geometry observations do not establish full content parity.

- PC1440×1000 before equalizing CSP: both detail x1044.8047/y124/w373.1953/h862; image x1100.8047/y172.6484/w261.1953/h195.8906; title16px. Font network conditions differed, therefore typography was not accepted on this observation.
- Same-CSP390×844: local header171.9453; detail x76/y186/w300/h644; image x132/y240/w188/h141. Web initially8px higher; guest grid slot fixed, then observed header171.9453, detail x76/y185.9453/w300/h644.0547. Measurement rounding subsequently aligned to local Math.ceil; 320px post-rounding Chrome extension check confirmed exact detail x14/y186/w292/h644 and image x70/y240/w180/h135 equality;390px was not remeasured after rounding.
- Same-CSP320×844: local detail x14/y186/w292/h644; image x70/y240/w180/h135. Web before rounding x14/y185.9453/w292/h644.0547, image x70/y239.9453/w180/h135. Widths match; rounding corrected in source.
- Screen inspection shows remaining list/Chronicle/action differences. No claim of full screenshot equality. Profile/member screen and operation matrix remains incomplete.

### Remaining work within requested scope

1. Reuse local profile section/table layout for Owned/Formerly/Favorite, including filter/order/selection and scroll heights. Top list paging/count/Refresh and missing columns still differ.
2. Replace stacked account settings/Claim/application forms with canonical per-kind local components and dialogs, retaining authorized APIs. Add Claim currently navigates to account intent instead of local action menu. This is missing implementation, not a Web-specific constraint.
3. Match member search/Follow presentation, signed header stats/icon/location and saved-theme behavior; preserve name/icon/Follow authorization.
4. Complete matching-data/manual interaction comparisons for settings, Claim editing/application, all modals, history, scroll and responsive profile/member pages.
5. Public Chronicle lacks correction target/author/body/vote/photo and public guitar DTO lacks owner/location/photo. Evidence: fixed response projection/validators in cloud_public_catalog.py and cloud-public-catalog.js. Do not expose private self/Evidence data. A parity-preserving authorized projection or deliberate unavailable presentation requires product/API scope judgment; missing wiring alone is not a security limitation. Real Identity Platform login cannot reproduce local dummy actor selection; visual login layout can still be aligned.

Accepted unported scope remains only the exclusions listed above. No new approval is pending; no upload or getApp diagnostic attempted.


### Final functional validation

- Full Python: **2,432 passed**,3 warnings. Final JS/CSS-only refinements followed this run.
- Full JavaScript: **911 passed**,0 failed, after final refinements.
- Relevant browser suites: formal UI, public catalog, Favorites/visibility all passed after final refinements. Formal header test covers1440/390/320 and three themes; an actual320px translated-title overflow was found and fixed. This is functional/responsive regression evidence, not full local parity.
- Isolated PostgreSQL catalog suite passed, including public-field privacy, modes, read-only reads, escaped multi-field search,10 added sort keys and deterministic pagination. This was the catalog suite, not every PostgreSQL suite.
- `git diff --check` passed. Manual fixture servers stopped; dedicated extension tab closed and viewport override reset.

Logs and automated fixture screenshots: [evidence directory](fidelity-evidence/). Screenshots are automated formal fixture outputs, not a paired Chrome extension visual acceptance set. Remaining differences above mean the requested overall fidelity task is **unfinished**.


## User-requested pause after unit2

See [FIDELITY_PAUSE.md](FIDELITY_PAUSE.md) for the saved changes, validation, precise remaining work and safe shutdown state. Unit2 supersedes some unit1 list differences but has not completed same-condition visual acceptance.


## Resumed work: units 3–4 (local only)

The earlier pause was lifted. Settings and list work below supersedes the corresponding remaining entries above; all other entries remain unfinished.

| Local baseline → difference | Correction | Evidence / acceptance limit |
|---|---|---|
| Separate User Settings with Save/Cancel, type, DOB, theme, signature → profile modal and stacked account forms | `/ui/settings` serves canonical `user_edit_html.html` and `pages/user-edit.css`, with a new authenticated transport adapter; formal profile User Settings button navigates there. Hidden duplicate avatar/visibility sections no longer clutter the profile | Headless Chrome1440/390/320: no page overflow, Cancel performs no mutation, theme preview, explicit synthetic Save and reload preserve name/type/DOB/theme/signature. Chrome extension paired visual comparison remains unavailable |
| Local settings fields were disconnected → only four profile fields saved | Added self-only settings and signature GET/PUT. Settings use canonical Accounts revision CAS/maintenance+service fences and projection outbox; signature uses actor-matched Chronicle row/current-owner checks/CAS. No schema/grants or public field expansion | Python validators/routes; isolated PostgreSQL settings/signature/visibility and Accounts suites pass. No real account changed |
| TopPage full list/fixed unfiltered height →24-item pager/custom widths/Refresh | Formal adapter aggregates validated24-row public API pages, rejects duplicate/incomplete/changing pages and stale identity results. Restored shared8-column geometry and canonical `profile-list.js` height measurement. Pager removed from ordinary successful formal display; Refresh retained for errors. Original standalone catalog keeps pagination | Browser30-row fixture, combined-field search and unfiltered desktop height, signed identity/revocation/Offline/history regressions. Claims count remains blank rather than fabricated because current DTO omits it |
| Favorite in row/detail shares state → independent stale hearts | Added compact row hearts using existing authorized API; same-identity/guitar controls serialize mutations, invalidate older reads, synchronize confirmed/unknown state; confirmed updates reload private Favorite collection | JS peer mutation, concurrent-click guard, delayed-read and unknown-result recovery checks. Full post-change browser suite passes (no uploads) |

### Concrete Web boundaries / decisions still needed

- Settings avatar input keeps the existing Web safe-image pipeline (JPEG/PNG/WebP,8MiB), unlike local GIF/12MB. Source: existing cloud avatar/media validators. No upload was attempted. Supporting identical limits/formats requires a deliberate safe-pipeline decision, not merely label changes.
- Settings account fields and signature live in separate canonical databases. The UI reports partial saves if a later signature/avatar request fails; it does not silently retry an uncertain write. Accounts fields+visibility are one CAS transaction. Successful flows match, failure atomicity does not yet match the local attached-DB path. This difference is recorded for design review; it is not evidence that equivalent transaction semantics are impossible.
- No new public profile/Owned/photo projection was added. Missing public owner/location/photo/author/body/correction target remains unresolved under existing privacy boundaries.

### Resumed verification and environment

- Full Python invocation:2445 passed; one existing loopback-bind test failed solely because the sandbox denied bind. That exact test passed with authorized local-loopback execution (see separate log). Combined result:2446 passing tests across the two runs, not a single clean full-run result.
- Full JS run:914 passed. Targeted Favorite/catalog checks after synchronization tests added also pass; final full count should be regenerated after the next implementation unit.
- Settings/visibility isolated PostgreSQL suite passed after correcting synthetic fixture required fields and test drain ordering. Accounts suite passed in preceding run; its combined log contains the superseded settings fixture failure and must not be described as entirely green.
- Chrome extension reconnect returned `Browser unavailable`; browser inventory returned `[]`. No evidence establishes screen-off as the cause. No OS settings/permissions/getApp diagnostics were changed. Continue code and automated verification; final manual parity gate remains open.
- All changes remain uncommitted on `fix/local-ui-fidelity`; no push/PR/merge/deploy/Offline change. Prior manual loopback fixture stopped. Automated fixtures clean up their servers/temp data.

Remaining requested implementation: per-kind Claim forms/actions/editing, ownership/application presentation, notifications detail, member search/Follow presentation, signed header/stats, default selection, authorized Claims counts, all-page Chronicle order, and paired PC/390/320 visual/interaction acceptance. Accepted unported scope has not expanded. This is an implementation checkpoint, not completion.


## Unit5 saved checkpoint

- Formal Chronicle now aggregates all authorized public25-row cursor pages before the existing shared occurrence/ID ordering runs. Duplicate/repeated cursors and stale identities fail closed. Standalone `/` pagination behavior is unchanged. This fixes page-boundary ordering only; omitted correction targets/author/private content remain unresolved.
- Compact Favorite controls no longer show routine working/success paragraphs inside table cells. Errors/unknown outcomes keep their recovery path. Stale mutation completion unlocks peer controls into an explicit unknown state instead of leaving them permanently disabled.
- Profile metadata now follows the local account-type/member-since/location/DOB order.
- Final full JavaScript:916 passed. Final formal automated browser passes, including two explicit synthetic Favorite mutations proving Owned-row heart, detail heart and30→29→30 Favorite rows synchronize. Settings Cancel/Save/reload and1440/390/320 checks also pass. No upload tested or attempted.
- Final `git diff --check` passed. Automated browser servers stopped normally. Chrome extension/manual same-condition acceptance is still pending. No deployment or repository publication performed.

This checkpoint does not close the overall fidelity task. In particular, Claim input/editing/ownership/application forms and member search/Follow still need the canonical local presentation; they must not be marked as Web limitations. See remaining requested implementation above.


## Units6–8: canonical Claim, applications, Follow and notifications (saved, local only)

| Local baseline → difference | Correction | Verification / remaining difference |
|---|---|---|
| Four separate Claim forms → generic kind/field editor | Serve inert canonical modal HTML directly from `user_view_html.html`; retain existing private API, CAS, permission, stale identity and unknown-result guards. Per-kind Add Claim menu, specification/repair toggles, canonical field picker, exact incident/event labels and media slots | Paired same-CSP/Sunburst local and formal headless Chrome: all4 forms ×1440/390/320, x/y/width/height and visible text match. Functional create/edit for Specification/Incident/Event pass; no file selected or uploaded. Media editing/upload QA remains explicitly unverified |
| Acquire/Listing canonical modal and unsaved Challenge → early persisted request and generic account form | Reuse local pure form/status formatters from source. Actor-scoped expiring random preview handles use existing private Accounts metadata; opening creates no application or Claim. Keep creates the draft and Acquire text/date atomically; stable revision supports idempotent retry. Local Keep/Reflesh/Cancel/Submit confirmation markup reused | Isolated PG: actor/tamper/expiry/mode fences, cancellation replay rejection and new preview after cancellation, same-token retry, Acquire text/date save tested. Formal browser PC/390/320: unsaved open/Cancel, Keep/reopen, Listing Challenge/read-only fields, no upload. Shared layout measured, remaining photo notice difference below |
| Follow button “Following”, canonical profile identity and connections dialog → custom typography, Unfollow label and600px dialog | Formal member page uses canonical profile classes and exact extracted local connections dialog; Follow/Following and count order restored, permitted-icon pipeline retained, local no-icon SVG fallback. Separate general search has no local standalone counterpart | Headless formal PC/390/320, two explicit synthetic Follow changes, modal Escape/focus, search and Back retention pass. General directory scope and private profile projection are unchanged |
| Notification card opens/marks read → list with several separate operations | Canonical notification card classes, text/date, empty state and footer. Explicit activation performs existing recipient-only mark-read then opens existing canonical destination. Unknown read result does not fabricate a read state | Synthetic notification card activation/read result, PC/390/320 and open-without-write pass. Existing API permission/uncertain-result tests retained |
| Profile initial selection prioritizes signature → empty Product Detail | Read existing self signature endpoint; validate against loaded Owned IDs, then fall back to first Owned/Formerly/Favorite. Preserve explicit guitar URLs and avoid a new Back entry; guard against identity/navigation changes | Formal regression passes after change. Paired full-profile screenshot acceptance remains pending |

Validation recorded at this saved checkpoint: full Python2448 passed (single clean run), full JS917 passed, formal browser passed including Claim/application/Follow/notification checks, isolated PG settings/visibility/application-preview suite passed. Some final presentation changes followed the full Python run; it must not be described as a final full task acceptance. The earlier ambiguous `#importantInformation button` test failure is resolved by selecting the row's Detail button; a later list-height check required waiting for ResizeObserver after viewport resize, without relaxing the height assertion.

### Concrete differences/decisions

- Local Listing claims its approved overview image becomes publicly representative; current Web application photos are private evidence and public catalog `photo` remains null. The Web form does not make that false promise or expose private photos. Same-field geometry is tested separately; Listing explanatory text and total scroll length are **not** identical. A safe public representative-image projection requires a scoped design decision. Existing private evidence cannot be substituted.
- The local `/user-view` contains no standalone general member-search page. The precise local search is Transfer recipient selection; general `/ui/members` has no one-to-one baseline. Follow/profile components have a baseline and were aligned. Local connections may show account type; current member DTO intentionally supplies name, permitted icon and Follow only. No additional member field exposed.
- Existing Web safe-image formats/limits and real authentication differ from the dummy prototype as documented above. New nonces are private metadata writes, not “no database write”; no application/Claim/ownership transition occurs on preview.
- Ownership Release's related-person input, Transfer/Release entry modal, owner verification presentation, signed header metadata/statistics, absent Claims counts and omitted public Chronicle fields remain in the audit. Missing API wiring is not a Web limitation. These are not added to the accepted unported exclusions.
- Normal Chrome extension same-condition final review remains unavailable/unconfirmed. Headless paired results are evidence for the measured components only, not a declaration that the entire page or every workflow matches.

No push, PR, merge, deploy, Offline/Review/Crawl change, real DB/settings mutation, new infrastructure or upload operation. All code remains on the isolated uncommitted `fix/local-ui-fidelity` branch. Work continues beyond this checkpoint.


## Units9–14: ownership entry, self header, connections and final focused header check

| Local baseline → difference | Saved correction | Evidence / limit |
|---|---|---|
| Transfer/Release canonical fields → generic ownership form, required Release date, missing related person | Shared local modal HTML; local optional date (existing repository defaults to today), related-person input, recipient selection, confirmation. Existing owner revision/identity/mode/unknown-result guards retained | Transfer/Release ×1440/390/320 paired geometry and text match; synthetic Release, Transfer Cancel, received Transfer Decline and confirmation cancellation pass. Isolated PostgreSQL ownership suite passes; ownership/verification evaluator unchanged |
| Incoming Transfer action row vs outgoing status → same generic list | Correct incoming sender/guitar links, Accept/Decline confirmation; outgoing View transfer. Formal inbox aggregates validated cursor pages, rejects duplicate/cyclic continuation and stale identities; empty account panels hidden | Saved formal browser verifies synthetic receiver sees Alice offer, cancel makes no write, explicit Decline updates state. Transfer agreement remains separate from Claim Verification |
| Signed account hub name/location/3 counts → shell identity and unrelated links | Self-only settings/avatar/summary reads; new authenticated GET summary for current actor only; canonical name/location/count classes and notification badge | Self summary actor matching/verified identity/query rejection tests and isolated PG actor separation pass. No other member fields or public projection added |
| Self profile Followers/Following and 50-row connections → absent counts and25-row pages | Existing member API read, canonical local dialog, two validated25-row pages per display batch, stale identity/modal fences; mobile detail-dismiss does not replace a button during its click | Saved formal browser: self Following/Followers, focus/Escape and3 widths; member31-row fixture now displays in one batch. Account type remains absent under current member DTO scope |
| Claim compact popup/date/tag/spec rows → generic dialog/created-date fallback/dl | Reuse local positioning and date formatter, canonical popup HTML/type classes, specification strong rows. Unknown event date stays “Date unknown” | Saved formal browser3 widths/Escape/focus. This verifies the shell only: public body/author/votes/photos remain omitted, not invented |
| Account hub CSS overrides, profile SignOut default button, extra button margins → local layout mismatch | Removed duplicate grid overrides; restored `account-hub-action` on SignOut; removed profile-wide3px button margin; notification rerender replaces text rather than accumulating whitespace; avatar alt matches self name | **Focused resume check:** same-CSP/Sunburst paired local/formal1440/390/320. Account hub, avatar, identity and summary x/y/w/h match in recorded results. Notification and Following open/Escape/focus pass. No whole-page equality claim |
| Acquire/Listing comparison had inconsistent fixture ownership | Formal fixture now gives the30 synthetic Owned guitars only to Alice; paired application test uses Bob on both sides and closes compact detail before Listing | Saved6 paired cases pass outer geometry and date/body/photo-field bounds. Dynamic challenge values differ normally. Listing public-photo promise is intentionally absent, so explanatory text/scroll length remains unequal |

### Reused and focused validation evidence

- Saved complete Python run: **2452 passed**,3 warnings. Saved complete JavaScript run: **917 passed**. These precede the last header-only CSS/DOM adjustments; they were not repeated on resumption.
- Saved formal browser run includes Claim input/edit, applications, connections, notification read, Transfer/Release, incoming Decline, identity/revocation/Offline and PC/390/320 checks.
- Saved isolated PostgreSQL ownership and profile/settings/application-preview checks pass. Cloud SQL was not contacted.
- Paired component logs: Claim12 cases, ownership6 cases, empty Follow3 cases, application6 cases. Application text limitation is explicit above.
- Resume-only targeted header log: [unit14-header-targeted.log](fidelity-evidence/unit14-header-targeted.log), with the small replay script alongside it. In both implementations the hub is47px high at1440px and108px at390/320px; avatar28px; summary30px. This proves those measured parts, not all header actions or full profile layout.

### Precise remaining work / design differences

1. **Code/presentation work, not a Web limitation:** Owner Verification still uses a separate private review dialog instead of the local per-Claim select/card flow. Its existing authorized evidence-read gate, current-owner-only policy, own-Claim exclusion and revision checks must be preserved when aligning presentation. Authored Claim editing still has an account list entry not found as an equivalent edit entry in the local source; inputs themselves are aligned. These are not marked complete.
2. **Current design omissions, explicitly kept on2026-10-11:** public owner/location, Claim author/body/votes/correction target/counts and representative photos; member account type/full profile/Owned collections. Do not widen DTOs or reuse private evidence as public media. Local Listing's public-photo promise cannot be copied truthfully under this design. This is a design boundary, not proof that the Web cannot implement it.
3. **Other visible differences needing a scoped implementation decision:** local header Messages action has no connected formal counterpart; Top notifications navigate to profile before opening, while profile opens its modal. Non-owner Former Owner Claim entry and full local per-Claim actions are not yet faithfully reproduced. These are not silently added to the user's accepted unported exclusions.
4. **Acceptance still pending:** complete same-data pages/scroll/back-forward/action matrix in normal Chrome; paired full-profile/whole-page images. Chrome reconnect was not retried. Headless component measurements and functional regression do not close this gate.
5. Accepted unported scope remains exactly cross-guitar User Chronicle, New Discovery/statistics/maps, and actual upload QA. No file was selected/uploaded. Image format/size and authentication differences remain documented above.

No push/PR/merge/deploy, real DB/user settings change, Offline/Review/Crawl change, infrastructure/IAM/cost change or data deletion. Original working trees remain untouched.


## Unit15 — per-Claim Verification and editing (2026-10-11)

This supersedes remaining-work item1 in units9–14. No public DTO, authorization policy, ownership evaluator, database schema or image permission changed.

| Local baseline → difference | Final change | Targeted evidence |
|---|---|---|
| `claimHeaderHtml` puts Verification beside the Claim badge; compact Claims open their own popup → one unrelated “Owner Verification” button in Product Detail header and a multi-Claim account dialog | In both `/ui` and `/ui/profile`, current-owner authorized rows decorate the matching Claim head with the canonical `claim-response-select`. Compact Claims expose it inside their canonical popup. Header-wide review button removed. A fresh owner read/revision precedes the existing mutation; ordinary text decisions apply from the selector. Existing photo-read gate opens the selected private Claim in the same popup surface and keeps decisions disabled until evidence is read | Existing owner/content + posting + catalog JS:196 passed. Owner route authorization tests:7 passed. Focused browser verifies fresh revision, Positive/Negative, own-Claim exclusion, no media write before evidence read, read-only mode, identity switch. No photo load/upload attempted |
| Existing Web authored editor is reached through a detached account list → no per-Claim entry | Own Claim footer now opens the existing per-kind editor through a fresh self-only read (validated pagination for later Claims). Non-positive Claims expose Edit inside their popup; private/inactive own rows omitted from public history retain a private View/Edit entry. Generic selfClaims account panel no longer crowds the profile | Focused browser: own Claim popup → editor → CAS save; own Claim never gets a Verification selector; another identity has neither edit nor verification control. A separate Top Page entry test verifies the same shared controller is wired there |
| Local popup body/head styles and locale field names → generic concatenated review summary | Authorized selected-Claim review uses shared Claim card/head/body/footer CSS, local popup-position/date/specification-label formatters; existing error, revision-conflict and evidence recovery remain | PC1440 and390px paired screenshots; Verification control is108×26px,11px text and identical three option labels on both sides. These measurements concern the changed control, not missing public body/vote fields |
| Comparison revealed missing avatar collapses the profile identity into the avatar grid column | A missing/revoked private avatar now restores `/assets/no-icon.svg` on the formal profile while revoking old blobs; it does not remove the image slot. Existing Owned/Formerly sections now retain the local14px separation | Missing-photo paired capture rechecked; profile identity width stays usable at PC/390. Existing avatar lifecycle tests37 passed, including identity/URL cleanup; no uploaded image used |

### Scope and verification accounting

- Initial target batch:196 JS +7 Python +focused profile browser, all passed. No full regression rerun, agent or independent review.
- Comparison found the no-avatar grid collapse; only that presentation state and avatar lifecycle were checked after fixing it. Narrow local comparison initially needed the compact Product Detail explicitly opened; that was a test-state mismatch, not a production failure.
- Top Page wiring initially raced its auth-state render against the permission read. Permission loading now starts after that render; only the failed Top entry test was rerun and passed.
- Recorded representative full-page captures: `unit15-paired-local/formal-1440.png` and `unit15-paired-local/formal-390.png`. The later14px Owned/Formerly gap correction is source-aligned; those captures predate that final spacing-only adjustment. Full-page equality is **not** asserted: public projection omissions, local User Chronicle, Messages, and synthetic profile metadata/content differ. Existing full-combination tests were not repeated.
- Functional logs and the paired dimensions are in `fidelity-evidence/unit15-*`. `git diff --check` passes. All fixture servers exit in `finally` and only temporary synthetic databases were used.

### Remaining interpretation / external acceptance

- The local source declares/resets `editingSpecificationClaimId` but has no implemented authored-Claim edit entry/handler equivalent to the existing Web editor. The requested editing capability is preserved through a Claim-footer action using the existing form and permissions; exact one-to-one local editing navigation cannot be certified from that source. No extra account editor or new design page was created.
- Existing Web evidence reads and revision/unknown-result recovery remain mandatory. They are retained behavior/policy, not an assertion that Web technology inherently requires a different design.
- Public owner/location/Claim body-author-votes/counts/correction target/representative-photo omissions remain the explicitly retained current projection design. No inferred zero, invented author, or private-photo substitution was added.
- Real upload QA and unavailable normal-Chrome comparison were not retried. Accepted unported User Chronicle/New Discovery/statistics/maps remain separate from these changes. Messages and Former Owner workflow need their own scoped migration decision as previously recorded; they are not silently counted as accepted exclusions.

Changes remain uncommitted on `fix/local-ui-fidelity`. No Cloud SQL start/connection, push, PR, merge, deploy, real DB/user setting, Offline/Review/Crawl, infrastructure or IAM operation occurred.

## Unit16 — handoff audit and account-hub async state (2026-10-11)

The new Codex session confirmed the saved branch and uncommitted work at task-7 without changing the original checkout. No full-suite rerun or external connection was used.

- Fixed the account hub clearing/hiding the newly rendered identity when supplemental settings/count/avatar requests started. Known name and placeholder counts now remain visible while those requests are pending or unavailable.
- Added a second identity/epoch check after awaiting avatar bytes. A previous user's delayed avatar read can no longer overwrite the new user's notification count in component state.
- Added `test_cloud_account_hub.cjs`: pending/failed supplemental reads, account switch during avatar read, and signout with outstanding requests. Together with `test_cloud_notifications.cjs`, **91 tests passed**, without network, DB, upload or browser permission changes.

Remaining gates are unchanged: normal-Chrome whole-page comparison and real upload QA are unverified; public/member projection expansion, Messages and Former Owner migration require separate scope decisions. Top Page's Notifications link still navigates to the profile before opening its modal; that remaining presentation difference has not been fixed by this unit. No parity-completion claim, push, merge, deploy, Cloud SQL start or Offline-mode change.

## Unit17 — approved public presentation and staging acceptance (2026-10-11)

The user approved public Current Owner names/profile links, public Claim author/prose/vote totals and explicitly selected public representative images. Residence follows visibility; the anonymous public DTO emits only Public residence. Members/Followers/Private residence remains omitted on this endpoint even for a signed-in caller. Private Evidence/review images are excluded. This supersedes earlier projection-omission statements; it does not make the member directory anonymous.

- Settings: restore the initial SDK session before subscribing to subsequent identity changes. The initial null-to-user notification no longer clears the settings request; later identity changes still discard private fields and late responses.
- Top Notifications: use the shared modal directly on Top; selected destinations still revalidate on Profile. No notification-read mutation was performed in staging QA.
- Public projection: canonical Accounts names and public residence, bounded Claim prose/vote totals, and a no-store photo endpoint. Only the selected JPEG attached to an active Positive Listing/Media Claim by a normal author is eligible. GCS content references remain internal; legacy paths and review-only images are not public-photo fallbacks.
- User Chronicle: self-only chronological join/profile/Claim/vote/response/guitar events (latest 100), without dispute/application Evidence. Rendering uses text nodes and rejects late results after identity changes.
- Staging exposed the same initial-restoration issue on Top; catalog subscription order was corrected with a regression test. Subsequent identity changes continue to cancel public reads.
- Staging also exposed failures during 50 simultaneous per-row favorite reads. The initial row reads now run at most three concurrently; account changes drop queued old-account work. No retries or credential downgrades were added.
- Targeted checks: Python public/settings/presentation 126 passed; final catalog JS 35 passed, including the initial-session and bounded-queue regression cases. Settings initialization 2 passed. Earlier cloud-JS batch 866 passed before the final two catalog regressions. Full PostgreSQL fixture validation and uploads were not rerun.

See the handoff's latest staging section for the deployed revision, actual browser acceptance and remaining limitations. Existing uncommitted work is preserved; no commit/push/merge was requested.


## Unit18 — initial representative photos (2026-10-11)

This supersedes Unit17's blanket exclusion of review photos. The user clarified that Crawl records initially use Reverb image links, and accepted user Listings initially use the submitted overview photo. Close-ups, review reports and Acquire review images remain private.

The public resolver prefers eligible explicitly selected media, then resolves accepted Listing overview storage references or validated Reverb CDN links. Eligibility is checked on each read; no data migration or approval mutation is involved. The Listing form again explains overview publication. Python148 / JS90 targeted checks passed. Staging revision ui-20261011e displays Guitar2's Reverb image (800×800). Actual user Listing storage-photo delivery is covered by tests but has not been visually verified in staging. No uploads/applications were submitted.

Browser QA also observed recurring Favorite read failures and severe product-name wrapping in the narrow panel. These remain open; this unit does not certify complete responsive fidelity or all API reliability.


## Unit19 — shared request budget and detail-title width (2026-10-11)

Staging request logs showed Favorite/settings HTTP503 at the same timestamps as Cloud SQL FATAL remaining connection slots reserved errors (including 10:38 UTC). Limiting only catalog rows to three requests did not cover concurrent detail/profile/settings reads. The shared Identity Platform adapter now allows two authenticated API requests in flight, queues the rest without automatic retries, and rechecks identity and AbortSignal before dispatch. Network/token failures release the slot. Backend authorization/ownership locks are unchanged. This controls a single page's demand; it is not a global multi-client server capacity guarantee.

Favorite controls/recovery messages are now below the Product Detail title row, with wrapped status text using its own full-width line. A failed Favorite read can no longer squeeze a long product title into a few pixels.

Targeted auth/catalog/favorite tests:166 passed, including mixed-component request limits, network-failure slot release, cancelled queued requests and identity changes before queued mutations. Existing dirty work is preserved. No user content writes or uploads were used.


## Unit20 — implemented UI parity audit (2026-10-11)

Scope confirmed by user: existing server functionality only. New Discovery, statistics, map, and Messages remain deferred. No new voting/gallery collection API is implied by presentation alignment.

- Restored visible Claim counts in public, Favorite, and Owned/Formerly tables. Counts use the same active, normal-author, supported type/status visibility as public Chronicle; IDs/counts remain decimal strings.
- Fixed Top Claim action discovery: an ownership probe's expected404 means no owner controls, while401/403/503 still surface failures. No permission rules changed.
- User-owned guitars hide the standalone Acquire banner and expose Ownership inside Add Claim. The canonical owner opens Transfer/Release; other users must confirm the existing ownership-dispute warning before an Acquire preview. Canonical numeric user ID is compared, not the opaque authentication ID.
- Formal profile consumes valid Acquire/Claim/Ownership query intents after account loading. It opens the appropriate form/menu without automatically saving a request, checks identity/navigation, and does not reopen the consumed intent after a refresh.
- Top now uses the existing ownership inbox and participant-dispute controllers. Profile disputes move to the same top information section. Participant dispute details use the common modal and compact round timeline; Admin actions and authorization remain unchanged.
- Representative photo opens at useful size in a common modal; only the already-authorized public image is reused. Navigation/identity changes close it. Favorite sits beside the product title, with error/retry text on a full-width separate row. Public author/date/vote totals use Claim footer layout; vote totals are display-only because no cloud voting mutation API is connected.
- Product search font matches local14px; list ID links retain keyboard/link behavior without extra underlines.

Validation: related Python358 passed; JS934 passed; git diff --check passed. Synthetic browser checks: matching dark theme at1280×720 for Product List/Detail, owner warning, Back, direct query→warning→unsaved Acquire, Claim query→menu,390px Acquire with one open modal and no horizontal overflow. Local and formal fixture metadata intentionally differ; full-page pixel equality is not asserted. Actual remote browser requires renewed administrator sign-in.

Deployment/status will be recorded in handoff section19. No real application submission, review, Claim mutation, ownership change, or Git merge belongs to this unit.

### Unit20 実サーバー確認での補正

代表画像の独自拡大モーダルは共通YGCImageAlbumのcaptureハンドラーと競合して二重表示されたため削除。クリック・キーボードは共通アルバムを使用し、詳細破棄時に閉じる。関連JS36件成功。実ステージングでOwnedのClaim件数、Owner自身のTransfer/Release導線、通知モーダル確認済み。

実画面記録: `fidelity-evidence/staging-ui-owned-20261011.png`。Profileは読込中に0件表示や操作disabledが長く続き、ページ内リンクでも再取得される。初期化性能とloading表示の改善は残課題。実際に係争中の案件を作成する検証は今回行っていない。

## Unit21: プロフィール初期取得とページ内移動（2026-10-11）

- 初期取得をプロフィール・Owned/Formerly Owned・Favoriteの優先段階と、それ以外の段階に分割。各段階はPromise.allSettledで並行進行するが、認証APIアダプターの同時送信上限2は維持する。一部失敗でも他パネルを取得し、account/sessionが変化した場合は次段階を開始しない。
- Profile見出しリンクはscrollIntoViewとhashのreplaceStateだけを行い、popstateによる全プロフィール再取得を起こさない。別タブ用修飾クリックは維持。
- Owned/Formerly Owned/Favorite/Chronicleの未取得件数は「—」。完了して空だった場合だけ0 items。
- JS938件成功（追加4件: 優先取得・部分失敗、identity/suspensionガード、ページ内移動、未取得件数）。権限・Owned判定・申請APIは変更なし。


## Unit22 — Current Owner Acquire inbox and notification HTTPS boundary

- Formal Top/Profile now share a private Acquire inbox and the existing local teal unanswered-request surface. Only pending owner decisions appear; responding re-reads canonical permission and revision. Decline uses an in-page reason and explicit review/apply buttons, replacing unsupported native prompt.
- Cloud Run-only HTTPS scope correction preserves exact notification Origin validation after TLS termination; local HTTP and cross-site rejection remain unchanged.
- Python303 / JS945 tests passed. Synthetic CUA verification: Top acceptance; Profile decline with reason; both remove the answered row. Screenshots: fidelity-evidence/ygc-acquire-inbox-fixture-{top,profile}.png and ygc-acquire-decline-fixture.png. Live staging results are recorded in handoff section23.


## Unit23 — Transfer live test and mutation refresh

- Live guitar52 Transfer73 accepted by recipientID2 after senderID1 created it. Pending inbox, confirmation, current-owner transition, Formerly/Owned split and recipient Transfer decision lock verified.
- Refresh formal Profile summary/header/Chronicle/detail after ownership-related mutations; fence follow-up by session epoch and actor.
- Exclude completed accepted application revisions from draft-preview reuse so reacquisition gets a fresh Challenge and revision. Pending owner-review applications retain their existing reopen path.
- Related JS144 / Python104 passed; isolated PostgreSQL profile-preview and ownership workflow suites passed. Live deployment and follow-up application are in handoff section24.


## Unit24 — Live Acquire decline and ownership dispute

- Guitar52 Acquire74 passed image review; current Owner declined with a required test reason. Applicant appealed with a private image, Owner submitted once, and Round1 became Under review. Admin downloaded the actual private attachment, reviewed both explanations, and resolved in favor of the original Owner. Applicant confirmed Resolved after refresh.
- Counterparty private explanation/unpublished summary remained hidden; submitted parties lost their input forms. No fabricated purchase or legal dispute was asserted.
- Remaining UI gap: authenticated participant Under dispute hint / detail link / Ownership disabling on Product Detail. Public DTO must not expose private case state. Console initial case list required Refresh; investigate initialization separately. Additional rounds, summary publication and applicant-support live branches remain untested.
- Live identifiers, images, boundaries and operating-mode restoration are recorded in handoff section25.


## Unit25 — Private Product Detail dispute state and restored-identity inbox

Selected-guitar private participant/Admin list filtering preserves canonical access and all transaction/projection fences; no public case field or schema change. Top/Profile add the shared Under dispute card and existing detail entry, suppress Ownership/Acquire during an active case or unresolved state read, keep ordinary Claim posts available, and invalidate late identity/navigation responses. Admin destination uses the existing Console/detail authentication. Failed reads offer explicit recovery.

Synchronize restored identity before loading dispute lists so the first Admin result survives render. Targeted Python133 / JS225 passed. Actual IAB synthetic Top/Profile shared-modal and menu checks passed, PC1440 plus Profile390px without horizontal overflow. No live Claim/dispute mutation. Headless Chrome launch and temporary PostgreSQL initdb were blocked by sandbox; actual PG filter acceptance is unrun. Admin deep-link actual click and authenticated staging reads remain unverified. Deployment and operational-state evidence: handoff26. Whole-page initialization busy delays remain separate follow-up work.


## Unit26 — Independent initial hydration and Console read verification

Profile releases the global mutation lock before initial/private-panel hydration, including sign-in, verification and BFCache restore. Console enables each loaded service/review setting independently, loads panels concurrently within the existing shared two-request cap, and opens the dispute deep-link after its own list read. Late diagnostics and settings are fenced by identity/epoch; unloaded controls stay disabled and successful service settings survive a failed Review read.

Related JS185 passed; syntax/diff checks passed. IAB synthetic Profile showed User Settings and SignOut enabled while notification requests remained held; actual Settings navigation succeeded. Deployed ui-20261011o; assets match and ready200. User reauthenticated Admin2: real Console list and Case2 deep-link detail read succeeded, Resolved/original Owner retained. Offline/message/Review OFF confirmed, no live mutations or operation-setting changes. Actual normal Profile remains mode-blocked; PG and further dispute branches remain pending. See handoff27.


## Unit27 — Turn2 initial state and session-bound private UI

Initial catalog search/sort/submit are disabled until route values and handlers are installed; reads can remain pending while new searches supersede stale initial results. Catalog and notification counters distinguish unknown/pending/failure (—) from a successful empty result (0). JS270/Python17 passed, including existing cap/session/BFCache regression. IAB synthetic stalled modules/private reads, case503/retry, active-case Ownership guards with ordinary posts preserved, navigation/private-draft clearing, logout and Alice→Bob switch passed. Actual ID1 deployed initial counters/search and notification reads passed. Actual pending case/session-switch browser checks were synthetic; persisted BFCache path was VM-tested. Deployed ui-20261011p, ready200/asset match, Offline/message/Review OFF restored. See handoff30.


## Unit28 — Turn3 live additional evidence and reviewed publication

Live staging Case2 was reopened for Round2. Both participants submitted; Admin requested additional evidence and Round3 preserved history with fresh empty forms. Both resubmitted, Admin inspected private explanations and edited/published evidence6/7 summaries. Both participant views contain reviewed summaries without counterpart private explanations or original summaries. A stale prepare detected concurrent applicant submission and required renewed review; no automatic resend. JS82 passed; no application changes or deploy. Case remains Round3 Under review/Owner2; applicant-support decision reserved for Turn4. Offline/message/Review OFF restored. See handoff31.


## Unit29 — Turn4 applicant decision and resolved Claim denial

Live Case2 Round3 resolved for applicant Acquire74: Current Owner ID1, applicant Owned1/Formerly0 and original Owner Owned0/Formerly1. New Owner Transfer/Release form and recipient search reopen; no new ownership request submitted. Ordinary Admin moderation of the decided Claim was safely blocked but surfaced as503. Added fenced dispute-link precheck with409/dispute_claim_locked and explicit EN/JA UI explanation. Python181/JS58 passed. Deployed ui-20261011q; live repeat returned409 and refreshed Claim remained Positive/Owner1. Editing/deletion and coupled normal verification restrictions are regression-tested, not direct live HTTP tests. Offline/message/Review OFF preserved. See handoff32.


## Unit30 — Turn5 live Transfer acceptance and owner transition

ID1 proposed Transfer75 to explicitly selected ID2; pending kept Owner1. ID2 confirmed acceptance at 2026-10-12 00:07:20 JST: accepted/Positive, Current Owner2. Refreshed ID1 Owned0/Formerly1/Claims4/Chronicle7; ID2 Owned1/Formerly0/Claims3/Chronicle6; guitar Claims/public Chronicle5. Former owner has no normal decision control; new owner can decide eligible prior Acquire72 while resolved Acquire74, accepted Transfers and self Listing remain excluded. Ownership opens Transfer/Release for ID2 and an Acquire warning for ID1; canceled without extra writes. Case2 preserves Round3 applicant decision and resolved state; later owner change disables reopening. No code changes or redeploy; previous same-source regression remains valid, direct denial API mutation tests were not repeated. Offline/message/Review OFF restored, browser error logs empty. Actual PG regression remains Turn6. See handoff33.


## Unit31 — Turn6 isolated PostgreSQL and final regression

Cloud Build disposable PostgreSQL18.6 completed all17 groups, including individual dispute filtering, settled Claim HTTP409/no-store, private originals/rounds/publication/quotas, successor Transfer/reopen and ownership/profile coupling. Corrected outdated public-count/presentation fixtures and separated public Claim prose/names from private test markers. Corrected legacy Console test model. Preserved Identity Correction reasons as private: public presentation body is null, author history and ordinary public Claim prose remain intact. Python2535/JS960 passed; dependency/schema/diff checks passed. Deployed ui-20261012r100%, ready normal, Offline/message/Review OFF retained. No live ownership/Claim/dispute mutations; Owner2/Transfer75/Acquire74/Case2 retained. Local restricted initdb/Chromium were not retried. Six-turn verification completed; next workflow waits for user direction. See handoff34.


## Unit32 — Public discovery/statistics/map API checkpoint (2026-10-12)

User expanded scope before major item ③: global New Discovery, model/year/30-day Listing statistics, country map. Following activity and Messages remain deferred. Additional turn 1 adds public read-only APIs and DTOs; UI and staging deployment remain pending for turns 2 and 3. Python full regression: 2585 passed, 3 existing warnings; new insights tests: 50 passed. PostgreSQL checks are prepared, not executed in this turn. No browser/cloud mutation or deployment. See handoff section 35 for contracts and privacy constraints.


## Unit33 — Discovery/statistics/country map formal Top connection (2026-10-12)

Additional turn 2 connects global discoveries, native SVG model/year/UTC 30-day Listing charts with count tables, and a bundled Natural Earth country map with accessible country counts. EN/JA, empty/error/retry, identity clearing, abort/late-response guards and hash-navigation stability are covered. IAB local synthetic fixture confirmed 1440/390/320 widths, sign-in/out, discovery detail, small-country table and keyboard access. Python2585 and final JS975 passed; related Python67/JS52 overlap. API/UI remain undeployed; actual PostgreSQL and staging verification are additional turn 3, awaiting user direction. Follow activity/Messages deferred. See handoff36.


## Unit34 — Additional insights PostgreSQL and staging completion (2026-10-12)

Isolated PostgreSQL18.6 public catalog group passed all prepared insights contracts, visibility withdrawal and mode checks (Build80105434). Deployed final ui-20261012t100% after real 390px labels exposed adjacent end ticks; kept a full tick interval and expanded legend row spacing. JS977 passed; deployed Python exactly matches PG-tested source. Live anonymous/member/Admin mode checks, discoveries51, statistics51, six-country counts and discovery→guitar52 passed. Final PC/390 EN/JA proofs saved. Offline/original maintenance text/Review OFF restored; no live ownership/Claim/profile location mutation or IAM/env changes. Additional turns1–3 complete, Follow/Messages deferred; await direction for original major item③. See handoff37.


## Unit35 — Performance stage1 (2026-10-12)

Authenticated GETs reuse valid SDK tokens; mutations/verification retain refresh policy and all server authorization/no-store boundaries. Same-list guitar selection keeps list; sorting with same selected ID keeps Detail/Chronicle/photo. Preserve rows/count while updating; initial Account/Profile login forms stay hidden during auth restore. JS984 and formal delivery Python2 passed, backend unchanged. Real staging maker sort catalog requests6→3; selection lists0; pending DOM51 rows/Detail retained. Initial row Favorite traffic still delays foreground list pages; no overall latency improvement claim. Deployed ui-20261012u100%, Offline/current Japanese maintenance message/Review OFF restored. Stage2 scheduling/cross-page state and stage3 DB/query/static optimization remain. See handoff38.


## Unit36 — Performance communication scheduling checkpoint (2026-10-12)

Shared authenticated budget2 with background row concurrency1, foreground catalog/auth/writes before supplemental requests. Share only simultaneous same-principal GET responses; no stored/private persistent response cache. Signals/forced reads/writes separate, identity/mutation invalidate, queued abort prompt. Profile shares parent canonical object initially and initial Hub hydration; Back reuses list with fresh authorized Detail, BFCache still restores and hides login forms. JS995 and delivery Python2 passed, backend unchanged. Real w selection16→Back52 list/me0, Profile me/settings/summary1 but avatar/notifications2 remain. Individual operation-to-final-list samples u13.338s/v2.506s/v17.571s/w4.904s demonstrate variability, not a benchmark guarantee. Deployed w100%, Offline/current Japanese message/Review OFF restored. N+1/serial pages/full-document navigation/shared state and backend optimization remain; do not declare all Stage2/overall performance complete. See handoff39.


## Unit37 — Personal Favorite row read aggregation (2026-10-12)

Same-render row controls share one fully validated personal paginated collection in-flight; no completed snapshot cache. Explicit Refresh/Detail/write retain existing APIs and authorization. Identity/canonical object and write revision reject stale results. JS1005/delivery Python2 passed; real w52→x2 favorite GETs, all51 row hearts enabled, sort retains hearts without reads. PC/390 verified. Deployed x100%, Offline/current Japanese message/Review OFF restored. Full-page reuse/serial list pagination/backend remain; not overall Stage2 complete. See handoff40.


## パフォーマンス段階②完了・最新状態（2026-10-12）

CODEX handoff41を優先。最終ui-20261012ab100%、Build13068119、digest b8ce90fa。公開DTOは認可・modeと内容を毎回再検証後304、staticは内容ETag再利用。private/HTML/config/写真/errorはno-store。独自private persistent cache/SPA化は採用せずMPAを維持。残りpage2単位/順序完全性、Profile avatar・通知各1/visibility初期0、Top/Profile rowFavorite集約、auth pending中フォーム・旧private非表示を実装。Top→Profile publicDetail/Chronicle304、static48件304、51heart/分類0・1・4/戻る進む/390幅確認。Python2597・最終JS1020・FormalPython4、隔離PG publicCatalog1/1成功。Offline/current日本語message/ReviewOFF復元、cachedETag403と公開表示消去確認。運用mode以外のDB/権限/Claim/所有/Profile/Favorite書込なし、未commit/push/merge、tab3/4handoff/viewport解除。取得・再利用の段階②完了。全HTML遷移/DOM再構築/API約0.5秒と実通信の連続待ちは残る。次は性能段階③backend接続/token認可/SQL/配信待ちの測定改善。全速度改善完了とは扱わない。元クローズドテスト大項目③/Follow/Messages未開始。成果物performance-stage2-complete-results.txtと検証JSON/画像。


## 42. パフォーマンス段階③・DB接続と静的配信の改善完了（2026-10-12）

- HTTP lifespan限定DB pool、request別Server-Timing/JSON計測、SHA256版付きstatic immutable配信を実装。raw query/path/token/SQL/個人情報を計測logに含めない。HTML/private API/config/photo/error no-store、公開DTO毎回認可・計算後ETag/304、legacy static no-cacheを維持。版付きは起動時bytes固定・生成i18n/ownershipをhashに含む。既存route allowlist以外公開しない。
- pool各DB max4/min0、nestedはidle leaseを非blocking取得、満杯なら旧方式の独立connectionでwait cycle回避。fallbackはpool上限外。commit/rollback・DISCARD ALL/session isolation/prepared無効化、切断時write replayなし、lifespan close。CLI/migrationはfresh。SQL定義/index/migration/schema・Ownership/Claim判定不変。Google check_revoked=Trueは各API継続、認可result/cacheなし。
- 同条件匿名GET7回（warmup2除外）中央値app183.70→121.58ms約34%、DB114.66→69.05ms、client267.66→196.16ms。会員各6件app539.60→427.59ms約21%、DB159.55→77.18ms、identity274.18→275.41ms。小標本staging比較で全pageの速度/安定改善率は保証しない。countは非blocking取得試行も含む。
- 最終Python全体2604passed/既存warning3、JS1020passed/0failed。全体後の追加module graphはtarget7passed（全体2605再実行とは扱わない）。最終source隔離PG18/18群(Build6bc5ac61-bf40-4586-ba83-f2e23997d164)、別DB飽和追加1/1群(Build814d3e89-9b36-4a0e-b561-af9c70f52011)成功。取引分離/並列write/rollback/reset/切断lease/closeを確認。live DB破壊なし。
- ad Normal実ID1一覧51/新着51/地図177/Detail52・6entries・Nut Bone、ProfileOwned0/Former1/Claims4/通知17。me/settings/summary/avatar/notifications各1/visibility0。Top→Profile 00:28:54–00:29:47Z static12GET（初見専用JS/CSS10件200、placeholder2件304）、Top取得済み共有JS/CSS GET0。後続no-iconの304は残り、static全部0としない。Back直後認証待ち/フォーム非表示、復元後同会員、Forward Top51。今回sort入力はbrowser dispatch timeoutで成功扱いなし、昇順URLを検証、UIsort/390幅は不変で段階②証拠継承。初回Profile復元中session_changed一時文言を観察、後続me200/本人表示正常。文言改善は残課題、原因・修正済みと断定しない。
- revision ygc-staging-accounts-ui-20261012ad100%、Build653ba6b8-3acd-4eba-9b5f-db5b99819fa8 SUCCESS、digest sha256:236c5b454827829ee3d90d75f13dbb44354f67df000b3d229bcc99f7c30eb5f9。229許可files/4.0MiB、production byte一致、ready200、template image/revision/clientmetadata以外一致。env/SA/scaling/IAM保持。
- Offline/元日本語message「サービスはメンテナンスのため一時的に停止しています。しばらくしてから再度お試しください。」/Review OFF復元。Console入力後保存clickが制御timeout、復元だけ既存app SA/DB secret reference/最終imageの一時jobを使用、canonical Admin ID2有効確認・version fence・既存set_mode監査event維持。ygc-staging-perf3-mode-restore execution rl6fj成功、job削除済み、既存jobs不変/secret本文読出なし。公開status/6API cached validator403/no-store/noETag、会員データ破棄とConsoleOffline確認。viewport解除/tab3/4handoff、未commit/push/merge。
- outputs/performance-stage3-complete-results.txt、measurements.json、baseline/final匿名・server JSON、top-profile requests、pc/profile/offline画像。段階③backend/配信完了。MPA document/DOM再構築、Google失効照合とSQL計算、初期復元文言は残る。全待ち時間解消/SPA化は未実装。元クローズドテスト③/Follow/Messages未開始。


## 43. ユーザー別表示データの連続操作共有完了（2026-10-12）

- ユーザー承認で同じタブ/同じcanonicalユーザーの短期display cacheを追加。identity-platform-auth内のsessionStorage+memory、origin/SDKuid/tenant/canonical app_user_id/role/statusで分離。Cookie/localStorage private保存追加なし。各documentでfresh /me後のみ利用、canonical identity/token/権限/Claim/所有権/申請はcacheしない。
- 設定30秒、summary15秒、通知/完全Favorite collection10秒。明示opt-inのみ、64entry/512KiB/各JSON64KiB。通常fresh/force/signal/customheaderはreuseなし。partial Favorite不保存。各cachehitでfresh service status（同時inflightのみ共有）、Offline破棄403、AdminOnly通常認可API、ReadOnly通知can_write=false。mutation開始/終了・logout・identity・拒否・Refreshで破棄、旧応答再publish防止。pagehideは完了済み有効cache保持/遅延publish拒否。初期SDK復元session_changed誤表示とservice停止の認証誤文言を修正。
- JS1044passed/0failed、servedUI/runtime Python22passed/既存warning1、diffcheck成功。別ユーザー/logout/TTL/書込競合/失敗/403/service/Storage/ReadOnly/不完全Favorite/初期SDK/BFCacheを合成テスト。backend/SQL不変、今回fullPython/PG再実行とはしない。
- af実ID1の短いProfile→Top→Profileで各me1/settings0/summary0（service確認保持）。これら2APIのみ0、全通信0やページ時間改善率ではない。ah実画面51行/TakeshiOst/通知17/ProfileOwned0Former1Claims4/Detail52NutBone。明示NewDiscovery Refreshでme/settings/summary各1をRun log確認。私有業務更新、実別account/logout/positiveFavoriteは未実行（合成で検証）。
- 最終ai100%、Build7b875e9c-a14e-42ee-a045-a2fcc798e7e0 SUCCESS、digest sha256:51ac7a4d9d6d3b7a195638c6452270920f34aaffa340719b81a315a71221d86f、229許可files/4.0MiB。template image/revision/clientmetadata以外一致、配信10JS versionedasset置換後一致、ready200。最終aiはahからNewDiscovery等の停止文言1箇所のみ変更。ae/ag未配信。
- Offline/元日本語「サービスはメンテナンスのため一時的に停止しています。しばらくしてから再度お試しください。」/Review OFF復元。ai画面旧会員/一覧/新着/統計/地図破棄、制限表示、SignIn hidden。viewport解除/tab3/4handoff、SQL/Crawl/既存Jobs/IAM/env/SA/Claim所有権業務更新なし、未commit/push/merge。
- currentchat outputs/user-data-sharing-results.txt、live-counts.json、refresh-counts.json、final-server.json、deployment.json、profile-final.png/offline-final.png。MPA document/DOM構築/fresh認証、avatar/Owned一覧/Claim/申請state取得は残る。元クローズドテスト③/Follow活動/Messages未開始。以前の「private persistentcacheなし」はこのユーザー承認のtab-scoped短期display保存で限定置換、権限やcanonical保存を許す変更ではない。


### 43追記：ユーザー自身の速度確認（2026-10-12）

ユーザー「実行速度を確認しても良いですか？」に対応し、Consoleで一時Normalへ切替。公開service/status normal、ID1 Top51行/aria-busy false確認。Review OFF保持、元メンテナンスmessage保持、業務データ変更なし。現在Normalのままユーザー確認待ち。確認終了後Offlineへ戻す。tab3/4handoff、viewport overrideなし。outputs/speed-check-normal.png。


## 44. 代表画像の先行表示・Claim判定更新の表示保持（2026-10-12）

- ユーザー速度確認後「代表画像がReverbより遅い、Posi/Nega切替で一覧再読込/表示崩れ」に対応。画像はfresh Detail DTO+service check後に先行表示、Chronicle/全list待ちを除去。Chronicle到着時に画像DOMを再構築せず、route AbortSignalと既存identity/photoEpochで旧応答破棄。画像no-store・サーバー公開/actor認可保持、private画像cache/GCS公開URL/認証省略なし。
- Top/Profile判定後はfresh Detail/Chronicleを表示保持して更新、同じtable projection（5項目+Claimcount）なら一覧GET0/同一DOM、変化時はfilter/sort/count反映のため全list再取得。不要な/me再復元を抑止しserver read/write認可保持、insightsは完了後fresh。Owner分類更新は維持。Consoleは判定のfresh Detail/Chronicle中に旧表示を保ち、一覧4項目変化時のみlist更新、Verificationで変化しないAdmin media_assetsは再取得しない。認可拒否/停止時は従来通り破棄。
- JS1054passed/0failed（10追加）、関連Python214passed/既存warning1、diffcheck成功。photo先行/旧応答、same list DOM/get0、Snapshot/Claimcount変更時のfreshlist、401/403/503消去、Console拒否を合成で確認。backend/SQL不変、今回fullPG/Python再実行とはしない。AGENTS所有権不変条件/遷移表を確認、Ownershipや判定ルールを変更しない。
- AJ実ID1 Normalでphoto1536px/51行/Chronicle6/TakeshiOst。1440/390overflowなし、Maker昇順待機中51行/Detail維持、完了image src同一/追加photoGET0。Run log photo03:27:02.445Z/0.736s、最後listpage3開始03:27:03.220Z/0.437sでphoto先行完了。Guest単独0.325sは条件が異なるため速度比較に使わない。実業務Posi/Nega変更なし、該当発生画面の補足未受領、Top/Profile・Console両経路の処理を修正したが特定実Claimの再現済みとはしない。
- AJ100%、Build1349d202-d3b1-4cfb-bf1d-c664245d5b49 SUCCESS、digest sha256:c16d6ea9b3f46049310cbecdbd256057d7315f3abf12a764bded8290e3f8770d、229許可files/4.0MiB、5変更JS配信期待一致（versionedasset置換後）、ready200/template image/revision/clientmetadata以外一致。既存Jobs/Crawl/IAM/env/SA/業務データ変更なし、未commit/push/merge。
- 現在Normal/Review OFF。ユーザー速度確認の続きとしてNormalを保持、確認終了後にOffline/元日本語案内へ戻す（このターンのOffline復元は未実施）。viewport解除/tab3/4handoff。outputs/photo-claim-results.txt、deployment.json、requests.json/public-requests.json、events.json、detail-pc.png/detail-mobile.png。画像API自体の認証/DB/GCS時間、MPAは残る。クローズドテスト③/Follow活動/Messages未開始。


## Checkpoint 45 — Claim Negative / compact Favorite layout (2026-10-12)

- User report: Negative ◉ offset and transient “Changes…” text in Favorite column after Verification operations.
- `#detail .claim-compact-row` now uses the same full-width/no-inline-margin center as Positive cards. Claim rules, ownership, permissions and write endpoints unchanged.
- Compact Favorite separates unrelated operation `busy` from write restriction. Heart remains disabled while busy and retains the known value; initial reads still finish during another operation.
- Compact notices remain an accessible live status/description and button tooltip, outside layout flow. Retry uses an accessible ↻ icon; heart/retry area remains 36px.
- Final JS suite: 1057 passed; related Python UI/Favorites suite: 134 passed, one existing Starlette deprecation warning. Fake public-catalog DOM updated to support classList.add.
- Real browser synthetic fixture (no live writes): Positive/Negative/Positive centers all 220px (390px viewport:195px); Favorite column 57.5546875px unchanged through normal/busy/restricted/uncertain failure/recovery; no overflow.
- Staging deployment: build 6fb24ec1-de25-4411-9ff7-659c8038804f SUCCESS; revision ygc-staging-accounts-ui-20261012al; 100% traffic; digest sha256:06bf37d1fa75562bf2bd349e160ef42f4009c2fa112681a5b6d18c991160919b. Superseded AK build was never deployed.
- /ready ok; mode normal. Template comparison: image/revision/client metadata only; env, SA, scaling and security settings unchanged. Review remains OFF.
- Live member Top/Profile read-only checks: updated versioned CSS; compact Favorite cells 36px at narrow width / 43.15625px at PC width (inner control fixed at 36px); no long in-flow notices or page overflow. No live Claim/Favorite/ownership write was made for testing. User can retest Negative transition after reloading.
- Evidence: current chat outputs/claim-favorite-layout-fixture.png, claim-favorite-layout-measurements.json, claim-favorite-layout-staging.png. Original closed-test item ③ remains pending.
