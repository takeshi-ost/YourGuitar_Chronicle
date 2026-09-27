"""Small, manually advanced Reverb search and public availability checks."""

from __future__ import annotations

import json
import re
import time
import httpx
from datetime import datetime, timedelta, timezone
from typing import Any

from ygc import config
from ygc.db.repository import Repository, utcnow
from ygc.reverb_adapter import to_listing_claim_data, to_provenance_observation


CATEGORY_QUERY = {"electric": "electric guitar", "acoustic": "acoustic guitar"}
MAX_SUMMARIES = 5
MAX_RECHECKS = 2
MIN_REQUEST_GAP = 1.0


def _category_matches(item: dict, category: str, *, strict: bool = True) -> bool:
    values = [str(item.get("product_type") or "")]
    for entry in item.get("categories") or []:
        values.append(str(entry.get("name") or entry.get("slug") or "")
                      if isinstance(entry, dict) else str(entry))
    entry = item.get("category")
    if entry:
        values.append(str(entry.get("name") or entry.get("slug") or "")
                      if isinstance(entry, dict) else str(entry))
    value = " ".join(values).lower().replace("-", " ")
    if not value.strip():
        return not strict  # Do not infer a category from a model/title.
    return category in value and "guitar" in value and not any(
        word in value for word in ("parts", "pedal", "amplifier", "case only")
    )


def _year_matches(item: dict, year_min: int, year_max: int, *, strict: bool = True) -> bool:
    # Unknown/range years cannot establish a precise manufacture-year match.
    years = [int(year) for year in re.findall(r"(?<!\d)(?:18|19|20)\d{2}(?!\d)",
                                              str(item.get("year") or ""))]
    return (not strict if not years else
            min(years) >= year_min and max(years) <= year_max)


def _pause(last_request: float) -> float:
    remaining = MIN_REQUEST_GAP - (time.monotonic() - last_request)
    if remaining > 0:
        time.sleep(remaining)
    return time.monotonic()


def _save_program(repository: Repository, key: tuple, **fields: Any) -> None:
    fields["updated_at"] = utcnow()
    with repository.connect() as con:
        con.execute(
            "UPDATE crawl_programs SET " + ", ".join(f"{name} = ?" for name in fields)
            + " WHERE source_site = 'reverb' AND category = ? AND year_min = ? "
              "AND year_max = ?",
            (*fields.values(), *key),
        )


def _program(repository: Repository, key: tuple) -> dict:
    with repository.connect() as con:
        con.execute(
            "INSERT OR IGNORE INTO crawl_programs "
            "(source_site, category, year_min, year_max, updated_at) "
            "VALUES ('reverb', ?, ?, ?, ?)", (*key, utcnow()),
        )
        return dict(con.execute(
            "SELECT * FROM crawl_programs WHERE source_site = 'reverb' "
            "AND category = ? AND year_min = ? AND year_max = ?", key,
        ).fetchone())


def program_status(repository: Repository, category: str, year_min: int,
                   year_max: int) -> dict:
    with repository.connect() as con:
        row = con.execute(
            "SELECT * FROM crawl_programs WHERE source_site = 'reverb' "
            "AND category = ? AND year_min = ? AND year_max = ?",
            (category, year_min, year_max),
        ).fetchone()
    if not row:
        return {"processed": 0, "observations_created": 0,
                "finished": False, "updated_at": None}
    return {"processed": row["processed"],
            "observations_created": row["observations_created"],
            "finished": bool(row["finished"]), "updated_at": row["updated_at"]}


def restart_program(repository: Repository, category: str,
                    year_min: int, year_max: int) -> dict:
    if category not in CATEGORY_QUERY or not 1800 <= year_min <= year_max <= 2100:
        raise ValueError("Invalid category or manufacture-year range")
    _program(repository, (category, year_min, year_max))
    _save_program(repository, (category, year_min, year_max), page_url=None,
                  pending_json=None, next_url=None, finished=0,
                  processed=0, observations_created=0)
    return program_status(repository, category, year_min, year_max)


def _recheck(repository: Repository, collector: Any, last_request: float) -> tuple[dict, float]:
    now = datetime.now(timezone.utc)
    with repository.connect() as con:
        candidates = list(con.execute(
            """SELECT o.source_listing_id, c.api_url, c.missing_since
               FROM observations o LEFT JOIN crawl_listing_checks c
                 ON c.source_site = 'reverb'
                AND c.source_listing_id = o.source_listing_id
               WHERE o.source_site = 'reverb'
                 AND o.source_listing_id IS NOT NULL
                 AND (c.checked_at IS NULL OR
                      (c.missing_since IS NULL AND c.checked_at <= ?) OR
                      (c.missing_since IS NOT NULL AND c.status <> 'unavailable'
                       AND c.checked_at <= ?) OR
                      (c.status = 'unavailable' AND c.checked_at <= ?))
               ORDER BY CASE WHEN c.missing_since IS NOT NULL THEN 0 ELSE 1 END,
                        COALESCE(c.checked_at, ''), o.id LIMIT ?""",
            ((now - timedelta(days=7)).isoformat(),
             (now - timedelta(days=1)).isoformat(),
             (now - timedelta(days=30)).isoformat(), MAX_RECHECKS),
        ))
    counts = {"rechecked": 0, "missing_first_check": 0,
              "confirmed_missing": 0, "unavailable_claims": 0,
              "owners_unknown": 0}
    for candidate in candidates:
        last_request = _pause(last_request)
        status = collector.public_listing_status(
            str(candidate["source_listing_id"]), candidate["api_url"],
        )
        counts["rechecked"] += 1
        missing_since = candidate["missing_since"]
        if status == "missing" and not missing_since:
            missing_since = utcnow()
            counts["missing_first_check"] += 1
        confirmed = (status == "missing" and candidate["missing_since"]
                     and datetime.fromisoformat(candidate["missing_since"])
                     <= now - timedelta(days=1))
        with repository.connect() as con:
            con.execute(
                """INSERT INTO crawl_listing_checks
                   (source_site, source_listing_id, api_url, checked_at,
                    missing_since, status)
                   VALUES ('reverb', ?, ?, ?, ?, ?)
                   ON CONFLICT(source_site, source_listing_id) DO UPDATE SET
                     checked_at = excluded.checked_at,
                     missing_since = excluded.missing_since,
                     status = excluded.status""",
                (candidate["source_listing_id"], candidate["api_url"],
                 utcnow(), missing_since if status == "missing" else None,
                 "unavailable" if confirmed else status),
            )
        if confirmed:
            counts["confirmed_missing"] += 1
            result = repository.record_reverb_unavailable(
                str(candidate["source_listing_id"])
            )
            counts["unavailable_claims"] += int(result["created"])
            counts["owners_unknown"] += int(result.get("owner_released", False))
    return counts, last_request


def advance_program(repository: Repository, collector: Any, category: str,
                    year_min: int, year_max: int) -> dict:
    if category not in CATEGORY_QUERY or year_min < 1800 or year_max > 2100 or year_min > year_max:
        raise ValueError("Invalid category or manufacture-year range")
    key = (category, year_min, year_max)
    program = _program(repository, key)
    counts = {"summaries_processed": 0, "details_fetched": 0,
              "new_observations": 0, "skipped_existing": 0,
              "skipped_category_or_year": 0}
    run_id = repository.start_run("reverb")
    last_request = 0.0
    try:
        if not program["finished"]:
            pending = json.loads(program["pending_json"]) if program["pending_json"] else []
            if not pending:
                last_request = _pause(last_request)
                if program["page_url"]:
                    payload = collector._get_json(collector.safe_api_url(program["page_url"]))
                else:
                    payload = collector._get_json(
                        f"{collector.api_base}/listings",
                        params={"query": CATEGORY_QUERY[category],
                                "year_min": year_min, "year_max": year_max},
                    )
                pending = payload.get("listings") or (payload.get("_embedded") or {}).get("listings") or []
                next_href = collector._next_href(payload)
                next_url = collector.safe_api_url(next_href) if next_href else None
                _save_program(repository, key, pending_json=json.dumps(pending),
                              next_url=next_url, page_url=None)
                program["next_url"] = next_url
            for summary in pending[:MAX_SUMMARIES]:
                listing_id = collector.listing_id(summary)
                if not listing_id:
                    counts["skipped_category_or_year"] += 1
                else:
                    with repository.connect() as con:
                        exists = con.execute(
                            "SELECT 1 FROM observations WHERE source_site = 'reverb' "
                            "AND source_listing_id = ?", (listing_id,),
                        ).fetchone()
                    if exists:
                        counts["skipped_existing"] += 1
                    elif (not _category_matches(summary, category, strict=False)
                          or not _year_matches(summary, year_min, year_max, strict=False)):
                        counts["skipped_category_or_year"] += 1
                    else:
                        detail_href = collector._self_href(summary)
                        if not detail_href:
                            counts["skipped_category_or_year"] += 1
                        else:
                            last_request = _pause(last_request)
                            detail_url = collector.safe_api_url(detail_href)
                            try:
                                detail = {**summary, **collector._get_json(detail_url)}
                            except httpx.HTTPStatusError as exc:
                                if exc.response.status_code not in (404, 410):
                                    raise
                                detail = None
                            counts["details_fetched"] += 1
                            if detail and (_category_matches(detail, category)
                                    and _year_matches(detail, year_min, year_max)):
                                claim_data = to_listing_claim_data(detail, config.SERIAL_CONFIDENCE_THRESHOLD)
                                provenance = to_provenance_observation(detail, config.SERIAL_CONFIDENCE_THRESHOLD)
                                saved = repository.persist_reverb_listing_claim(claim_data, provenance)
                                counts["new_observations"] += int(saved["created"])
                                with repository.connect() as con:
                                    con.execute(
                                        "INSERT OR IGNORE INTO crawl_listing_checks "
                                        "(source_site, source_listing_id, api_url) "
                                        "VALUES ('reverb', ?, ?)", (listing_id, detail_url),
                                    )
                            else:
                                counts["skipped_category_or_year"] += 1
                counts["summaries_processed"] += 1
                pending = pending[1:]
                # A per-item checkpoint survives a process restart or failed detail.
                _save_program(repository, key, pending_json=json.dumps(pending),
                              processed=program["processed"] + counts["summaries_processed"],
                              observations_created=program["observations_created"] + counts["new_observations"])
            if not pending:
                _save_program(repository, key, pending_json=None,
                              page_url=program["next_url"], next_url=None,
                              finished=int(program["next_url"] is None))
        rechecks, last_request = _recheck(repository, collector, last_request)
        repository.finish_run(
            run_id, pages_discovered=counts["summaries_processed"],
            pages_fetched=counts["details_fetched"] + rechecks["rechecked"],
            observations_created=counts["new_observations"], status="ok",
        )
        return {**counts, **rechecks, **program_status(repository, *key)}
    except Exception as exc:
        repository.finish_run(
            run_id, pages_discovered=counts["summaries_processed"],
            pages_fetched=counts["details_fetched"],
            observations_created=counts["new_observations"],
            status="error", error_message=str(exc),
        )
        raise
