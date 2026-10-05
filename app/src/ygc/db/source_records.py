"""Marketplace provenance reads during the legacy crawl-record transition.

Evidence owns registered sources. Legacy rows remain a fallback for listings
not yet migrated and for crawl records that never produced an Individual.
Full-row archives preserve the latter if their original rows are later removed.
Never filter by Claim visibility here: an inactive or banned Claim still marks
its external listing as already processed. Public reads apply their own filter.
"""

MARKETPLACE_SOURCES_SQL = """
    SELECT e.source_site, e.source_listing_id, e.source_url,
           e.captured_at AS observed_at, c.individual_id, c.id AS claim_id,
           e.legacy_observation_id, COALESCE(e.legacy_observation_id, e.id) AS sort_id
    FROM claim_source_evidence e JOIN claims c ON c.id=e.claim_id
    WHERE e.evidence_type='marketplace_listing'
      AND e.source_site IS NOT NULL AND e.source_site<>'user'
      AND e.source_listing_id IS NOT NULL
    UNION ALL
    SELECT o.source_site, o.source_listing_id, o.source_url, o.observed_at,
           o.individual_id, NULL AS claim_id, o.id AS legacy_observation_id,
           o.id AS sort_id
    FROM observations o
    WHERE o.source_site IS NOT NULL AND o.source_site<>'user'
      AND o.source_listing_id IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM claim_source_evidence e
          WHERE e.evidence_type='marketplace_listing'
            AND e.source_site=o.source_site AND e.source_listing_id=o.source_listing_id
      )
    UNION ALL
    SELECT json_extract(a.payload_json, '$.source_site'),
           json_extract(a.payload_json, '$.source_listing_id'),
           json_extract(a.payload_json, '$.source_url'),
           json_extract(a.payload_json, '$.observed_at'),
           NULL AS individual_id, NULL AS claim_id,
           a.legacy_observation_id, a.legacy_observation_id AS sort_id
    FROM legacy_crawl_archive a
    WHERE json_extract(a.payload_json, '$.source_site') <> 'user'
      AND json_extract(a.payload_json, '$.source_listing_id') IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM observations o
          WHERE o.id=a.legacy_observation_id OR
                (o.source_site=json_extract(a.payload_json, '$.source_site')
                 AND o.source_listing_id=json_extract(a.payload_json, '$.source_listing_id'))
      )
      AND NOT EXISTS (
          SELECT 1 FROM claim_source_evidence e
          WHERE e.evidence_type='marketplace_listing'
            AND e.source_site=json_extract(a.payload_json, '$.source_site')
            AND e.source_listing_id=json_extract(a.payload_json, '$.source_listing_id')
      )
    UNION ALL
    SELECT r.source_site, r.source_listing_id, r.source_url, r.observed_at,
           NULL AS individual_id, NULL AS claim_id,
           NULL AS legacy_observation_id, r.id AS sort_id
    FROM crawl_unregistered_records r
    WHERE r.source_site<>'user'
      AND NOT EXISTS (SELECT 1 FROM claim_source_evidence e
                      WHERE e.evidence_type='marketplace_listing'
                        AND e.source_site=r.source_site AND e.source_listing_id=r.source_listing_id)
      AND NOT EXISTS (SELECT 1 FROM observations o WHERE o.source_site=r.source_site
                      AND o.source_listing_id=r.source_listing_id)
      AND NOT EXISTS (SELECT 1 FROM legacy_crawl_archive a
                      WHERE json_extract(a.payload_json,'$.source_site')=r.source_site
                        AND json_extract(a.payload_json,'$.source_listing_id')=r.source_listing_id)
"""


def source_records_sql(con):
    return getattr(con, "marketplace_sources_sql", MARKETPLACE_SOURCES_SQL)


def known_listing_ids(con, source_site: str, ids: list[str]) -> set[str]:
    """Find persisted sources, including unregistered legacy crawl records."""
    ids = [str(value) for value in ids if value]
    found = set()
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        marks = ','.join('?' for _ in chunk)
        found.update(str(row[0]) for row in con.execute(
            f"WITH sources AS ({source_records_sql(con)}) "
            "SELECT source_listing_id FROM sources WHERE source_site=? "
            f"AND source_listing_id IN ({marks})", [source_site, *chunk]))
    return found
