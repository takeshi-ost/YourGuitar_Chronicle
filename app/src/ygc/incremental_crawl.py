"""Small, manually advanced Reverb search and public availability checks."""

from __future__ import annotations

import json
import re
import time
import httpx
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from ygc import config
from ygc.crawl_detail_cache import save_detail
from ygc.crawl_candidates import candidate_ids, defer_listing, reconcile_candidates, stage_candidate
from ygc.db.repository import Repository, utcnow
from ygc.db.source_records import MARKETPLACE_SOURCES_SQL, known_listing_ids
from ygc.reverb_adapter import is_brand_new, _category_text, to_listing_claim_data, to_provenance_observation


CATEGORY_QUERY = {"electric": "electric guitar", "acoustic": "acoustic guitar"}
CRAWL_CATEGORIES = (*CATEGORY_QUERY, "electric_acoustic")
MAX_SUMMARIES = 2000
MAX_RECHECKS = 5
MIN_REQUEST_GAP = 0.5
DETAIL_FALLBACK_FIELDS = ("year", "product_type", "categories", "category", "condition")


def _category_matches(item: dict, category: str, *, strict: bool = True) -> bool:
    if category == "electric_acoustic":
        return any(_category_matches(item, selected, strict=strict) for selected in CATEGORY_QUERY)
    value = (str(item.get("product_type") or "") + " " + _category_text(item))
    value = value.lower().replace("-", " ").replace("_", " ").strip()
    if not value.strip():
        return not strict  # Do not infer a category from a model/title.
    return (category in ("electric", "acoustic") and category in value) and "guitar" in value and not any(
        word in value for word in ("parts", "pedal", "amplifier", "case", "bass", "accessories")
    )


def _year_span(item: dict) -> tuple[int, int] | None:
    """Keep fuzzy Reverb decades within the entire selected manufacture range."""
    raw = str(item.get("year") or "").translate(str.maketrans({
        "’": "'", "‘": "'", "–": "-", "—": "-",
    }))
    abbreviated_range = re.fullmatch(
        r"\s*'?(\d{4}|\d{2})\s*(?:-|to)\s*'?(\d{2})\s*", raw, re.I,
    )
    if abbreviated_range:
        first, last = abbreviated_range.groups()
        start, end = int(first), int(last)
        if len(first) == 2:
            # Match the existing 50s–90s convention. Earlier abbreviated
            # years have an ambiguous century and remain unclassified.
            if start < 50 or end < 50:
                return None
            start, end = 1900 + start, 1900 + end
        else:
            end += (start // 100) * 100
            if end < start:
                if start % 100 < 90 or end % 100 > 10:
                    return None
                end += 100
        return (start, end) if 1800 <= start <= end <= 2100 else None
    years = [int(value) for value in re.findall(
        r"(?<!\d)(?:18|19|20)\d{2}(?!\d)", raw,
    )]
    for year in list(years):
        if re.search(rf"(?<!\d){year}\s*'?s\b", raw, flags=re.I):
            years.append(year + 9)
    if not years:
        for digit in re.findall(r"(?<!\d)([5-9])0\s*'?s\b", raw, flags=re.I):
            years.extend((1900 + int(digit) * 10,
                          1909 + int(digit) * 10))
    return (min(years), max(years)) if years else None


def _year_matches(item: dict, year_min: int, year_max: int, *, strict: bool = True) -> bool:
    span = _year_span(item)
    return (not strict if span is None else
            span[0] >= year_min and span[1] <= year_max)


def _missing_metadata(item: dict, field: str) -> bool:
    if field == "year":
        return _year_span(item) is None
    return not (item.get("product_type") or _category_text(item))


def _merge_listing(summary: dict, fetched: dict) -> dict:
    """Detail may omit fields available in the listing summary."""
    detail = {**summary, **fetched}
    for field in DETAIL_FALLBACK_FIELDS:
        if not fetched.get(field) and summary.get(field):
            detail[field] = summary[field]
    return detail


def _known_listing_ids(repository: Repository, collector: Any, summaries: list[dict]) -> set[str]:
    ids = [str(value) for item in summaries
           if (value := collector.listing_id(item))]
    found = candidate_ids(repository, ids)
    found.update(repository.active_cached_listing_ids("reverb", ids))
    with repository.connect() as con:
        found.update(known_listing_ids(con, 'reverb', ids))
    return found


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
    if category == "electric_acoustic":
        states = [program_status(repository, selected, year_min, year_max) for selected in CATEGORY_QUERY]
        return {"processed": sum(s["processed"] for s in states),
                "observations_created": sum(s["observations_created"] for s in states),
                "finished": all(s["finished"] for s in states),
                "updated_at": max((s["updated_at"] for s in states if s["updated_at"]), default=None)}
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
    if category not in CRAWL_CATEGORIES or not 1800 <= year_min <= year_max <= 2100:
        raise ValueError("Invalid category or manufacture-year range")
    if category == "electric_acoustic":
        for selected in CATEGORY_QUERY:
            restart_program(repository, selected, year_min, year_max)
        return program_status(repository, category, year_min, year_max)
    _program(repository, (category, year_min, year_max))
    _save_program(repository, (category, year_min, year_max), page_url=None,
                  pending_json=None, next_url=None, finished=0,
                  processed=0, observations_created=0)
    return program_status(repository, category, year_min, year_max)


def _recheck(repository: Repository, collector: Any, last_request: float) -> tuple[dict, float]:
    now = datetime.now(timezone.utc)
    with repository.connect() as con:
        candidates = list(con.execute(
            f"""WITH sources AS ({MARKETPLACE_SOURCES_SQL})
               SELECT o.source_listing_id, c.api_url, c.missing_since
               FROM sources o LEFT JOIN crawl_listing_checks c
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
                        COALESCE(c.checked_at, ''), o.sort_id, o.source_listing_id LIMIT ?""",
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
            counts["owners_unknown"] += int(result.get("owner_lost", False))
    return counts, last_request


def advance_program(repository: Repository, collector: Any, category: str,
                    year_min: int, year_max: int,
                    progress_callback: Callable[[dict], None] | None = None,
                    *, _summary_limit: int | None = None, _finalize: bool = True,
                    _run_category: str | None = None, _run_id: int | None = None,
                    _count_offset: dict | None = None) -> dict:
    if category not in CRAWL_CATEGORIES or year_min < 1800 or year_max > 2100 or year_min > year_max:
        raise ValueError("Invalid category or manufacture-year range")
    if category == "electric_acoustic":
        totals: dict = {}
        samples = []
        combined_run_id = repository.start_run("reverb")
        for selected in CATEGORY_QUERY:
            if selected == "acoustic":
                _pause(time.monotonic())  # Keep the request gap across both searches.
            result = advance_program(repository, collector, selected, year_min, year_max,
                progress_callback, _summary_limit=max(1, MAX_SUMMARIES // 2),
                _finalize=selected == "acoustic", _run_category=category,
                _run_id=combined_run_id, _count_offset=totals)
            samples.extend(result.get("rejected_samples", []))
            totals["rejected_samples"] = samples[:3]
            for name, value in result.items():
                if isinstance(value, int) and not isinstance(value, bool):
                    totals[name] = totals.get(name, 0) + value
        return {**totals, "rejected_samples": samples[:3],
                **program_status(repository, category, year_min, year_max)}
    key = (category, year_min, year_max)
    program = _program(repository, key)
    counts = {"listing_pages_fetched": 0, "summaries_processed": 0,
              "details_fetched": 0,
              "new_observations": 0, "skipped_existing": 0,
              "missing_identity": 0, "serial_candidates": 0,
              "skipped_category_or_year": 0,
              "skipped_new": 0, "skipped_year": 0, "skipped_category": 0,
              "missing_year": 0, "missing_category": 0,
              "detail_unavailable": 0, "detail_scope_matched": 0,
              "missing_detail_url": 0, "candidate_checked": 0,
              "new_individuals": 0, "existing_individuals_extended": 0,
              "ambiguous_matches": 0, "rechecked": 0,
              "confirmed_missing": 0, "unavailable_claims": 0,
              "owners_unknown": 0}
    rejected_samples: list[dict[str, str | None]] = []
    run_id = _run_id if _run_id is not None else repository.start_run("reverb")
    last_request = 0.0
    phase = "listing"
    def checkpoint(current_phase: str) -> None:
        nonlocal phase
        phase = current_phase
        combined_counts = {**counts, **{k: (_count_offset or {}).get(k, 0) + v
                           for k, v in counts.items() if isinstance(v, int)}}
        log_counts = {**combined_counts, "rejected_samples": (
            (_count_offset or {}).get("rejected_samples", []) + rejected_samples)[:3]}
        repository.update_crawl_run(run_id, phase, log_counts,
                                   _run_category or category, year_min, year_max)
        if progress_callback:
            progress_callback({**combined_counts, "phase": phase, "run_id": run_id})
    checkpoint(phase)
    try:
        if not program["finished"]:
            pending = json.loads(program["pending_json"]) if program["pending_json"] else []
            known_ids = _known_listing_ids(repository, collector, pending)
            while (counts["summaries_processed"] < (_summary_limit or MAX_SUMMARIES)
                   and not program["finished"]):
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
                    counts["listing_pages_fetched"] += 1
                    pending = payload.get("listings") or (payload.get("_embedded") or {}).get("listings") or []
                    known_ids = _known_listing_ids(repository, collector, pending)
                    next_href = collector._next_href(payload)
                    next_url = collector.safe_api_url(next_href) if next_href else None
                    _save_program(repository, key, pending_json=json.dumps(pending),
                                  next_url=next_url, page_url=None)
                    program["next_url"] = next_url
                    program["page_url"] = None
                    if not pending and not next_url:
                        _save_program(repository, key, pending_json=None, finished=1)
                        program["finished"] = 1
                        break
                    if not pending:
                        _save_program(repository, key, pending_json=None,
                                      page_url=next_url, next_url=None)
                        program["page_url"] = next_url
                        program["next_url"] = None
                        continue
                summary = pending[0]
                listing_id = collector.listing_id(summary)
                if not listing_id:
                    counts["skipped_category_or_year"] += 1
                else:
                    if listing_id in known_ids:
                        counts["skipped_existing"] += 1
                    elif is_brand_new(summary):
                        counts["skipped_new"] += 1
                    elif not _category_matches(summary, category, strict=False):
                        counts["skipped_category_or_year"] += 1
                        counts["skipped_category"] += 1
                    elif not _year_matches(summary, year_min, year_max, strict=False):
                        counts["skipped_category_or_year"] += 1
                        counts["skipped_year"] += 1
                    else:
                        detail_href = collector._self_href(summary)
                        if not detail_href:
                            counts["missing_detail_url"] += 1
                            counts["skipped_category_or_year"] += 1
                        else:
                            last_request = _pause(last_request)
                            detail_url = collector.safe_api_url(detail_href)
                            try:
                                detail = _merge_listing(summary, collector._get_json(detail_url))
                            except httpx.HTTPStatusError as exc:
                                if exc.response.status_code not in (404, 410):
                                    raise
                                detail = None
                            counts["details_fetched"] += 1
                            if detail is not None:
                                save_detail(repository, str(listing_id), detail)
                            if detail and (not is_brand_new(detail) and _category_matches(detail, category)
                                    and _year_matches(detail, year_min, year_max)):
                                counts["detail_scope_matched"] += 1
                                claim_data = to_listing_claim_data(detail, config.SERIAL_CONFIDENCE_THRESHOLD)
                                provenance = to_provenance_observation(detail, config.SERIAL_CONFIDENCE_THRESHOLD)
                                if stage_candidate(repository, claim_data, provenance):
                                    counts["serial_candidates"] += 1
                                    with repository.connect() as con:
                                        con.execute(
                                            "INSERT OR IGNORE INTO crawl_listing_checks "
                                            "(source_site, source_listing_id, api_url) "
                                            "VALUES ('reverb', ?, ?)", (listing_id, detail_url),
                                        )
                                else:
                                    counts["missing_identity"] += 1
                                    defer_listing(repository, listing_id, "missing_identity")
                            else:
                                counts["skipped_category_or_year"] += 1
                                if not detail:
                                    counts["detail_unavailable"] += 1
                                    reason = "detail_unavailable"
                                elif is_brand_new(detail):
                                    reason = "skipped_new"
                                    counts[reason] += 1
                                elif not _category_matches(detail, category):
                                    reason = ("missing_category" if _missing_metadata(
                                        detail, "category") else "skipped_category")
                                    counts[reason] += 1
                                else:
                                    reason = ("missing_year" if _missing_metadata(
                                        detail, "year") else "skipped_year")
                                    counts[reason] += 1
                                if len(rejected_samples) < 3:
                                    rejected_samples.append({
                                        "listing_id": str(listing_id),
                                        "reason": reason,
                                        "summary_year": str(summary.get("year") or "")[:40],
                                        "detail_year": str(detail.get("year") or "")[:40]
                                        if detail else None,
                                        "product_type": str((detail or summary).get(
                                            "product_type") or "")[:60],
                                        "category": _category_text(detail or summary)[:120],
                                    })
                counts["summaries_processed"] += 1
                pending = pending[1:]
                # A per-item checkpoint survives a process restart or failed detail.
                _save_program(repository, key, pending_json=json.dumps(pending),
                              processed=program["processed"] + counts["summaries_processed"],
                              observations_created=program["observations_created"] + counts["new_observations"])
                if counts["summaries_processed"] % 10 == 0:
                    checkpoint("listing")
                if not pending:
                    following_page = program["next_url"]
                    _save_program(repository, key, pending_json=None,
                                  page_url=following_page, next_url=None,
                                  finished=int(following_page is None))
                    program["page_url"] = following_page
                    program["next_url"] = None
                    program["finished"] = int(following_page is None)
        checkpoint("matching")
        def matching_progress(checked: int, total: int, result: dict) -> None:
            counts.update(result)
            counts["candidate_checked"] = checked
            counts["candidate_total"] = total
            checkpoint("matching")
        matches = reconcile_candidates(repository, progress_callback=matching_progress) if _finalize else {"new_observations": 0}
        counts.update(matches)
        counts["candidate_checked"] = counts.get("candidate_total", 0)
        _save_program(repository, key, observations_created=(
            program["observations_created"] + matches["new_observations"]
        ))
        checkpoint("availability")
        rechecks, last_request = (_recheck(repository, collector, last_request)
                                 if _finalize else ({"rechecked": 0}, last_request))
        counts.update(rechecks)
        checkpoint("done")
        if _finalize:
            repository.finish_run(
                run_id, pages_discovered=counts["summaries_processed"] + (_count_offset or {}).get("summaries_processed", 0),
                pages_fetched=counts["details_fetched"] + rechecks["rechecked"] + (_count_offset or {}).get("details_fetched", 0),
                observations_created=counts["new_observations"], status="ok",
            )
        return {**counts, **matches, **rechecks, "rejected_samples": rejected_samples,
                **program_status(repository, *key)}
    except Exception as exc:
        checkpoint("error")
        repository.finish_run(
            run_id, pages_discovered=counts["summaries_processed"] + (_count_offset or {}).get("summaries_processed", 0),
            pages_fetched=counts["details_fetched"] + (_count_offset or {}).get("details_fetched", 0),
            observations_created=counts["new_observations"],
            status="error", error_message=str(exc),
        )
        raise
