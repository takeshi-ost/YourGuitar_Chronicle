# Claim-Centered Architecture

## Purpose

This document fixes the current architectural contract for the Claim-centered migration of Your Guitar Chronicle.

The migration must preserve existing data while replacing the legacy Observation-centered write path.

## Source of truth

### Claims

Claims are the semantic source of truth.

A Claim represents a meaningful statement or event in an Individual's Chronicle, including:

- Listing
- Owner Change
- Release
- Specification
- Repair
- Identity Correction

Meaningful guitar state must not be derived directly from Observation fields during normal operation.

### Individuals

`individuals` is a materialized snapshot of the accumulated active Claims for one physical guitar.

It is not the authoritative history.

Its purpose is:

- fast listing and search
- Individual matching
- normalized identity lookup
- current-state display
- caching the evaluated Claim state

Any field that can be reconstructed from Claims is a projection/cache.

Direct semantic edits to an Individual are prohibited. A semantic change must be expressed as a Claim change followed by snapshot rebuild.

### Observations

Observations are provenance / ingestion records.

They may retain:

- source site
- external Listing ID
- source URL
- fetched/observed timestamp
- raw source data
- extraction metadata
- source image URL

Observation data must not be used as the normal semantic source for Current Owner, Location, identity, specification, or other Individual state.

Legacy Observation fields may temporarily remain for migration compatibility.

## Unified creation pipeline

Both Reverb ingestion and user-created guitars must converge on the same pipeline:

1. Parse input into structured Listing Claim data.
2. Determine whether the Claim belongs to an existing Individual using the Individual snapshot/index.
3. If no Individual matches, create an empty Individual shell.
4. Persist the Listing Claim.
5. Persist provenance separately when applicable.
6. Rebuild the Individual snapshot from its active Claims.

The two routes may differ only in input adapter and provenance source.

## Individual snapshot rebuild

A single operation should become authoritative:

`rebuild_individual_snapshot(individual_id)`

It evaluates active Claims in Chronicle order and writes the resulting current state into `individuals`.

The rebuild must eventually cover at least:

- manufacturer
- model
- finish
- year
- serial number
- normalized identity fields
- current owner
- current location
- representative media selection where appropriate

Identity Correction must affect the snapshot through Claim evaluation, not by directly becoming a second source of truth.

## Matching and duplicate checks

Two different duplicate checks exist:

1. External occurrence duplicate
   - Example: same Reverb Listing ID.
   - Checked against provenance/Observation records.

2. Physical Individual duplicate
   - Checked against the current Individual snapshot/index.
   - Uses normalized identity fields.

These concerns must remain separate.

## Listing Claim structure

A Listing Claim must own the semantic values asserted by the Listing.

Expected structured fields include:

- manufacturer
- model
- finish
- year
- serial_number
- owner
- owner_type
- seller
- location_country
- location_region
- listing_title
- listing_date

Source URL and external Listing ID may be exposed through provenance, but normal Listing Claim rendering must not depend on Observation semantic fields.

## Migration rule

Legacy Observation -> Claim conversion is permitted only as a compatibility migration.

After migration:

- normal reads use Claims
- normal writes create/update Claims
- snapshot rebuild reads Claims
- Observation semantic fields are not consulted for current state

Migration must be idempotent and safe to re-run.

## Safety requirements

During this architecture migration:

- keep `feature/db-import` unchanged as the comparison baseline
- perform all work on `feature/claim-centered-architecture`
- make one conceptual change per commit
- do not delete legacy Observation fields until Claim parity is verified
- prefer additive schema changes before destructive cleanup
- keep migration paths idempotent
- compare rebuilt snapshots against the existing database before switching reads
- switch user-created flow before Reverb ingestion
- switch Reverb ingestion only after snapshot rebuild and Claim storage are verified
- remove legacy Observation synchronization last

## Migration stages

1. Architecture contract and baseline.
2. Add and test `rebuild_individual_snapshot()`.
3. Complete structured Listing Claim storage.
4. Add idempotent legacy Observation -> Listing Claim migration.
5. Switch user-created guitar creation to the unified Claim pipeline.
6. Add Reverb -> Listing Claim adapter.
7. Switch Reverb persistence to the unified Claim pipeline.
8. Switch current-state reads to Claims/snapshot.
9. Remove legacy Observation-derived state synchronization.
10. Final parity and regression verification.

## Current baseline

Migration branch:

`feature/claim-centered-architecture`

Baseline branch:

`feature/db-import`

Baseline commit:

`e3cfd238926bb8de1e92d39d8fb6c1dce3f3455b`

No architectural migration code should be backported to the baseline branch until the new pipeline passes parity and regression checks.
