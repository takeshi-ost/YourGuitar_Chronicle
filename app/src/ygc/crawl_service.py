"""Shared Reverb collection pipeline for the browser console and CLI."""

from __future__ import annotations

from typing import Any

from ygc import config
from ygc.crawl_detail_cache import save_detail
from ygc.crawl_candidates import candidate_ids, defer_listing, reconcile_candidates, stage_candidate
from ygc.db.repository import Repository
from ygc.db.source_records import known_listing_ids
from ygc.incremental_crawl import _year_matches
from ygc.reverb_adapter import (
    _guitar_category_state,
    to_listing_claim_data,
    to_provenance_observation,
)


def existing_listing_ids(repository: Repository, ids: list[str]) -> set[str]:
    with repository.connect() as con:
        found = known_listing_ids(con, 'reverb', ids)
    found.update(repository.active_cached_listing_ids("reverb", ids))
    found.update(candidate_ids(repository, ids))
    return found


def _guitar_scope(item: dict) -> bool:
    product_type = str(item.get("product_type") or "").lower()
    if any(word in product_type for word in ("amp", "pedal", "parts", "case", "bass")):
        return False
    return _guitar_category_state(item) is not False


def crawl_query(
    repository: Repository,
    collector: Any,
    query: str,
    limit: int,
    *,
    year_min: int | None = None,
    year_max: int | None = None,
) -> dict[str, int | str]:
    """Collect one query and record one durable run, including failures."""
    run_id = repository.start_run("reverb")
    counts = dict.fromkeys((
        "summaries_fetched", "detail_candidates", "details_fetched",
        "skipped_non_target",
        "skipped_existing", "new_observations", "missing_identity",
        "serial_candidates", "new_individuals", "existing_individuals_extended",
        "ambiguous_matches",
        "detail_unavailable",
    ), 0)
    try:
        summaries = list(collector.iter_listing_summaries(
            query=query, limit=limit, year_min=year_min, year_max=year_max,
        ))
        counts["summaries_fetched"] = len(summaries)
        ids = [collector.listing_id(item) for item in summaries]
        existing = existing_listing_ids(repository, ids)
        candidates = []
        for item in summaries:
            listing_id = collector.listing_id(item)
            if listing_id and listing_id in existing:
                counts["skipped_existing"] += 1
                continue
            if (_guitar_scope(item) and
                    (year_min is None or year_max is None or
                     _year_matches(item, year_min, year_max, strict=False))):
                candidates.append(item)
            else:
                counts["skipped_non_target"] += 1
        counts["detail_candidates"] = len(candidates)

        for item in collector.fetch_listing_details(candidates):
            counts["details_fetched"] += 1
            if item.get("_ygc_detail_unavailable"):
                counts["detail_unavailable"] += 1
                continue
            listing_id = collector.listing_id(item)
            if listing_id:
                save_detail(repository, str(listing_id), item)
            claim_data = to_listing_claim_data(
                item, config.SERIAL_CONFIDENCE_THRESHOLD,
            )
            if (not _guitar_scope(item) or
                    (year_min is not None and year_max is not None and
                     not _year_matches(item, year_min, year_max))):
                counts["skipped_non_target"] += 1
                listing_id = collector.listing_id(item)
                if listing_id:
                    defer_listing(repository, str(listing_id), "out_of_scope", 30)
                continue
            provenance = to_provenance_observation(
                item, config.SERIAL_CONFIDENCE_THRESHOLD,
            )
            if stage_candidate(repository, claim_data, provenance):
                counts["serial_candidates"] += 1
            else:
                counts["missing_identity"] += 1
                listing_id = collector.listing_id(item)
                if listing_id:
                    defer_listing(repository, str(listing_id), "missing_identity")
        counts.update(reconcile_candidates(repository))
        repository.finish_run(
            run_id, pages_discovered=counts["summaries_fetched"],
            pages_fetched=counts["details_fetched"],
            observations_created=counts["new_observations"], status="ok",
        )
        return {"query": query, **counts}
    except Exception as exc:
        repository.finish_run(
            run_id, pages_discovered=counts["summaries_fetched"],
            pages_fetched=counts["details_fetched"],
            observations_created=counts["new_observations"],
            status="error", error_message=str(exc),
        )
        raise
