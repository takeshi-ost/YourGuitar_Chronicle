# YGC Database Update Policy

This document records the current policy for how **Your Guitar Chronicle (YGC)** should update its database as new marketplace observations are discovered.

The goal is to preserve a guitar's long-term provenance without turning every minor marketplace edit into a new historical event.

## Core model

YGC separates three concepts:

- **Individual**
  - The guitar itself.
  - Represents the persistent identity of one physical instrument.
  - Keeps the YGC-side identity stable over time.
- **Observation**
  - A record that the Individual was observed at a particular time and source.
  - A new marketplace listing, shop occurrence, or future user registration can each become a new Observation.
- **External Listing ID**
  - A source-specific identifier such as a Reverb Listing ID.
  - Belongs to the Observation, not to the Individual.

In short:

```text
Individual = the guitar
Observation = one occurrence in its history
Reverb Listing ID = external ID for that occurrence
```

## Basic rule for Reverb imports

A Reverb Listing ID is treated as one Observation.

Changes inside the same Reverb Listing should not normally create additional Observations.

For example, changes to:

- price
- description wording
- photos
- shipping terms
- minor title edits

are generally not important enough to create separate Chronicle events.

If useful metadata was missing at first and later becomes available, the existing Observation may be supplemented rather than duplicated.

## Incremental crawl flow

The intended long-term flow is:

```text
1. Fetch a lightweight listing index
2. Compare source_listing_id with the YGC database
3. Ignore already-known Listing IDs
4. Fetch detail only for unknown Listing IDs
5. Extract serial and metadata
6. Match against an existing Individual
7. Add a new Observation
```

The primary purpose of the incremental crawl is therefore **discovering new listings**, not monitoring every edit made to existing listings.

## First crawl vs. ongoing crawl

The crawler should eventually have two operating modes.

### Initial / coverage crawl

The initial crawl should gradually cover the target market:

```text
Product type: Guitar
Year: <= 1980
```

This should be divided into manageable segments rather than completed in one large run.

Possible segmentation axes include:

- category
- instrument type
- year range
- paging range

The crawl should keep track of which segments have already been completed so processing can resume safely on a later day.

### Incremental crawl

After broad coverage has been established, regular crawling should focus on newly appearing Listing IDs.

If the listing index API can expose only the information needed for discovery, the ideal lightweight index data is approximately:

```text
source_listing_id
source_updated_at   # optional, only if useful
```

However, YGC does not currently require tracking every `source_updated_at` change. If the same Listing ID is already known, it can usually be skipped.

## Same Listing ID

If the same Reverb Listing ID is encountered again:

```text
known source_listing_id
    -> do not create another Observation
    -> normally do not fetch full detail again
```

Possible exceptions include maintenance or metadata repair, such as filling fields that were previously missing.

The existing Observation remains the record for that listing.

## New Listing ID for an existing guitar

A guitar that was sold and later listed again should create a **new Observation**, even when it is the same physical guitar.

Example:

```text
Individual #42
  Observation A
    Reverb Listing ID: 111
    Owner: Shop A
    Date: 2026

  Observation B
    Reverb Listing ID: 987
    Owner: Shop B
    Date: 2028
```

The old Observation must not be overwritten with the newer Reverb Listing ID.

This preserves the historical chain.

## Individual duplicate matching

The primary key for identifying a previously known guitar is the serial number, together with manufacturer context.

Current matching policy:

### Strong match

```text
Manufacturer + Serial Number match
```

This is the main basis for linking a new Observation to an existing Individual.

### Stronger supporting evidence

Additional agreement increases confidence:

- Model
- Year
- Finish
- distinctive modifications
- distinctive wear or damage
- future image-based visual features

### Conflict handling

If the serial matches but major metadata conflicts, for example:

```text
same Maker + Serial
but completely different Model
```

the system should avoid silently merging with full confidence.

A future matcher should distinguish states such as:

```text
auto_match
possible_match
no_match
```

### Missing serial

If a reliable serial number is unavailable, YGC should generally avoid automatic merging.

Such records may later become merge candidates if additional evidence becomes available.

## Observation ownership

An Observation records the owner or holder associated with that occurrence.

Current fields:

```text
owner_name
owner_type
```

Current Reverb behavior:

```text
owner_name = Reverb shop name
owner_type = shop
```

Future user-generated Observation:

```text
owner_name = user name
owner_type = user
```

The legacy/source-specific `seller` field remains separate because it represents marketplace seller metadata rather than the general ownership concept.

## Current Owner

The Individual Detail UI currently derives **Current Owner** from the latest Observation.

The database does not need to rewrite a permanent owner field every time a new Observation is added.

The source of truth remains the Observation history.

If performance later requires it, fields such as these may be introduced as derived/cache values:

```text
latest_observation_id
current_owner
last_seen_at
```

but they should not replace the Observation history as the authoritative record.

## Do not overwrite provenance

The central rule is:

> New evidence should extend the Chronicle rather than erase the previous record.

Therefore:

- do not replace an old Reverb Listing ID with a new one
- do not collapse separate marketplace appearances into one Observation
- do not create duplicate Observations for minor edits within one Listing ID
- do preserve each distinct occurrence of the same guitar over time

## API-efficiency principle

The crawler should minimize expensive detail fetches.

Preferred sequence:

```text
broad lightweight listing scan
        ↓
unknown Listing IDs only
        ↓
detail fetch
        ↓
serial / metadata extraction
        ↓
Individual matching
        ↓
Observation creation
```

This supports large-scale crawling while keeping API usage controlled.

## Current implementation status

The current Phase 0 implementation already has several parts of this model:

- `source_listing_id` is unique per source Observation
- existing Listing IDs are skipped during crawl
- Reverb details are fetched only for selected candidates
- Individual and Observation are stored separately
- a new Observation can point to an existing Individual
- Observation ownership fields are available
- Detail UI derives Current Owner from the latest Observation

The large-scale crawl scheduler and full duplicate-confidence workflow are not yet implemented.

## Working principle

For future implementation decisions, prefer this interpretation:

```text
Individual identity is persistent.
Observation history is append-oriented.
External Listing IDs are immutable provenance for each Observation.
Marketplace edits are not Chronicle events unless they materially improve missing metadata.
```
