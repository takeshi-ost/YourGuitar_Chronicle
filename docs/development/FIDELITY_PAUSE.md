# UI fidelity pause — 2026-10-08

Paused at the explicit user request to close the Mac. All edits were made through filesystem writes, not unsaved editor buffers. Everything is saved, uncommitted, in `/Users/t_oshita/Documents/Codex/2026-10-08/task-7/ygc-ui-fidelity`, branch `fix/local-ui-fidelity`, base7ca7fd8. No push/deploy/real DB/settings/Offline change. No upload attempted.

## Safe pause state

- JS unit2:911 passed. Formal browser unit2 passed, including30-row own/favorite cursor aggregation, live search, sorting, cross-list selection, fixed unfiltered desktop height,1440/390/320 and three-theme headers.
- Full Python unit2 completed with exit0; exact summary in `fidelity-evidence/python-unit2.log`.
- Comparison loopback fixture (ports63730/63731) stopped with Ctrl-C, exit130; finally block closes both Uvicorn servers and cleans synthetic temporary DB. Earlier63618/63619 also stopped. No deployment involved.
- No active test sessions remain. Pytest completed naturally before the attempted SIGINT; kill reported no such process, then execution session confirmed exit0.
- Dedicated Chrome extension tab752165001 is left open on the local User Settings page. Its server has stopped. Viewport override reset; tab marked for handoff. User apps/tabs were not closed. No User Settings field was edited or saved; only navigation occurred.
- `git diff --check` clean. No editor buffer used by this agent.

## Changes since unit1 report

- `profile-list.js`: extracted canonical local column definitions and unfiltered height measurement. Local user-view.js now calls this common implementation; HTML and explicit local/cloud asset routes added.
- `cloud-profile-list.js`: authenticated DOM adapter using those columns, canonical CSS/toolbar, immediate combined-field filter, exact bigint sorting, selection preservation and shared row navigation. Compact Favorite uses existing guarded controller with unique IDs.
- Own and Favorite formal lists now aggregate25-item cursor pages with identity/epoch checks, duplicate/cursor rejection. Legacy/account view remains paginated. Added finish to the existing self-owned SQL projection without changing ownership predicates.
- Per-row ownership actions moved out of the table into selected Product Detail through `selectedActions`; current labels/presentation still differ from the local Claim menu and must be reconciled next.
- Removed cloud-account.css from formal profile because its global input/button rules overrode canonical dimensions. Moved local profile section links into the header, hid extra Refresh controls, restored profile heading and canonical Owned/Formerly/Favorite names.
- Formal fixture and browser regression now support30-row own/favorite collections and test cross-page filtering/selection.

## Verification limits / next work

1. Unit2 is not complete visual acceptance. Initial Chrome PC comparison observed local profile in Dark Default versus Web in Sunburst, so do not treat those as same-condition typography/color evidence. The first formal screenshot also preceded removal of account CSS and extra action column. Latest automated regression passes, but fresh same-theme Chrome PC/390/320 comparisons are still required. Local profile's extracted script route initially404ed; explicit route was added, server restarted, local profile then rendered30 rows correctly.
2. Keep original baseline source unchanged in original checkouts; current isolated local source has the shared extraction. Compare extracted behavior against the original7ca source when reviewing.
3. Claims count cells are currently empty because current own/favorite DTO lacks counts; do not invent zero. Need authorized count projection preserving privacy. Cross-list Favorite changes and refresh coordination need explicit regression beyond basic toggle guards.
4. User Settings currently still uses old Web profile modal/stacked visibility/avatar controls. Local canonical is a separate `/user-view/edit` page with display name, numeric user ID, account type, DOB, residence, bio, avatar, signature guitar, theme and visibility, Save/Cancel. No settings implementation was started in unit2.
5. Cloud account_records already has DOB/account_type/theme/theme_override. Existing self profile API currently allows only display_name/location_country/location_region/bio. Signature belongs to Chronicle users, excluded from accounts projection; design transactional updates carefully. This is missing API work, not automatically a Web constraint. Never broaden public profile/photo exposure.
6. Claim input/edit/applications, member/Follow presentation, Top catalog paging and remaining header/profile metadata/stats still require fidelity corrections. Accepted unported scope has NOT expanded.
7. Unit2 SQL Finish addition still needs isolated PostgreSQL account/ownership regression (`postgres_account_checks.py`); unit1 catalog Postgres suite had passed. Full new Python/JS and formal browser logs are saved; only relevant formal browser was rerun after unit2, not public/Favorites standalone browser suites.
8. Resume fixture with existing venv Python `app/tests/manual_fidelity_fixture.py`; prints new localhost ports and seeds only synthetic data. One Chrome extension tab is enough. No getApp diagnostics, uploads, real DB, push or deploy.

See FORMAL_UI_FIDELITY.md for baseline audit/unit1 evidence. Overall task remains unfinished; pause is user requested, not a parity-completion claim.


## Resume update

The user-requested pause above has ended. Units3–5 have since been saved and tested; see `FORMAL_UI_FIDELITY.md` for current status. The historical statements that Settings is unimplemented and SQL Finish validation is pending are superseded. No manual server is running; automated fixtures exited normally. The extension browser remained unavailable (inventory empty), so manual comparison is pending. Final full JS916 passed; Python2446 passed across full+single loopback rerun; final formal browser passed. Work remains uncommitted in the same isolated branch.
