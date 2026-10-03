"""Retain fetched listing evidence independently of extraction success."""

import json

from ygc import config
from ygc.crawl_candidates import reconcile_candidates, stage_candidate
from ygc.db.repository import Repository, utcnow
from ygc.db.source_records import known_listing_ids
from ygc.reverb_adapter import to_listing_claim_data, to_provenance_observation


def save_detail(repository: Repository, listing_id: str, detail: dict) -> None:
    if not listing_id or detail.get("_ygc_detail_unavailable"):
        return
    # Retain the identity even when the detail endpoint omits its own ID.
    payload = dict(detail)
    if not payload.get("id"):
        payload["id"] = listing_id
    with repository.connect() as con:
        con.execute(
            """INSERT INTO crawl_detail_cache
               (source_site, source_listing_id, payload_json, fetched_at)
               VALUES ('reverb', ?, ?, ?)
               ON CONFLICT(source_site, source_listing_id) DO UPDATE SET
               payload_json=excluded.payload_json, fetched_at=excluded.fetched_at""",
            (str(listing_id), json.dumps(payload), utcnow()),
        )


def reprocess_details(repository: Repository, category: str, year_min: int,
                      year_max: int, progress_callback=None) -> dict:
    # Local import keeps the network crawler and offline processor independent.
    from ygc.reverb_adapter import is_brand_new
    from ygc.incremental_crawl import CRAWL_CATEGORIES, _category_matches, _year_matches

    if category not in CRAWL_CATEGORIES or not 1800 <= year_min <= year_max <= 2100:
        raise ValueError("Invalid category or manufacture-year range")
    counts = {"cached_processed": 0, "cached_total": 0, "skipped_existing": 0,
              "skipped_new": 0, "skipped_scope": 0, "missing_identity": 0, "serial_candidates": 0}
    with repository.connect() as con:
        counts["cached_total"] = con.execute(
            "SELECT COUNT(*) FROM crawl_detail_cache WHERE source_site='reverb'"
        ).fetchone()[0]
    last_id = ""
    while True:
        with repository.connect() as con:
            rows = con.execute(
                """SELECT d.* FROM crawl_detail_cache d WHERE d.source_site='reverb'
                   AND d.source_listing_id > ? ORDER BY d.source_listing_id LIMIT 200""",
                (last_id,),
            ).fetchall()
            registered = known_listing_ids(con, 'reverb', [row['source_listing_id'] for row in rows])
        if not rows:
            break
        for row in rows:
            counts["cached_processed"] += 1
            last_id = row["source_listing_id"]
            if row['source_listing_id'] in registered:
                counts["skipped_existing"] += 1
                continue
            detail = json.loads(row["payload_json"])
            if is_brand_new(detail):
                counts["skipped_new"] += 1
                continue
            if not (_category_matches(detail, category) and
                    _year_matches(detail, year_min, year_max)):
                counts["skipped_scope"] += 1
                continue
            claim = to_listing_claim_data(detail, config.SERIAL_CONFIDENCE_THRESHOLD)
            provenance = to_provenance_observation(detail, config.SERIAL_CONFIDENCE_THRESHOLD)
            provenance["observed_at"] = row["fetched_at"]
            if stage_candidate(repository, claim, provenance):
                counts["serial_candidates"] += 1
            else:
                counts["missing_identity"] += 1
        if progress_callback:
            progress_callback(dict(counts))
    counts.update(reconcile_candidates(repository))
    return counts
