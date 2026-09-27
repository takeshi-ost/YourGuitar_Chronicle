"""Shared Reverb collection pipeline for the browser console and CLI."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from ygc import config
from ygc.db.repository import Repository
from ygc.reverb_adapter import (
    classify_vintage_listing,
    to_listing_claim_data,
    to_provenance_observation,
)


def existing_listing_ids(repository: Repository, ids: list[str]) -> set[str]:
    ids = [value for value in ids if value]
    found: set[str] = set()
    with repository.connect() as con:
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            marks = ",".join("?" for _ in chunk)
            rows = con.execute(
                "SELECT source_listing_id FROM observations "
                f"WHERE source_site=? AND source_listing_id IN ({marks})",
                ["reverb", *chunk],
            )
            found.update(str(row[0]) for row in rows)
    found.update(repository.active_cached_listing_ids("reverb", ids))
    return found


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
        "skipped_modern", "skipped_non_target", "skipped_unknown",
        "skipped_existing", "new_observations",
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
            status = classify_vintage_listing(item)["status"]
            if status in ("vintage", "unknown"):
                candidates.append(item)
            elif status == "modern":
                counts["skipped_modern"] += 1
            else:
                counts["skipped_non_target"] += 1
        counts["detail_candidates"] = len(candidates)

        for item in collector.fetch_listing_details(candidates):
            counts["details_fetched"] += 1
            claim_data = to_listing_claim_data(
                item, config.SERIAL_CONFIDENCE_THRESHOLD,
            )
            status = str(claim_data.get("vintage_status", "unknown"))
            if status != "vintage":
                key = ("skipped_modern" if status == "modern" else
                       "skipped_non_target" if status == "non_target" else
                       "skipped_unknown")
                counts[key] += 1
                listing_id = collector.listing_id(item)
                if listing_id:
                    ttl = 1 if status == "unknown" else 30
                    repository.cache_listing_rejection(
                        "reverb", str(listing_id), status,
                        recheck_after=(datetime.now(timezone.utc) +
                                       timedelta(days=ttl)).isoformat(),
                    )
                continue
            provenance = to_provenance_observation(
                item, config.SERIAL_CONFIDENCE_THRESHOLD,
            )
            if repository.persist_reverb_listing_claim(
                claim_data, provenance,
            )["created"]:
                counts["new_observations"] += 1
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
