"""Durable serial-bearing candidates shared by both Reverb crawl entry points."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from ygc.db.repository import Repository, utcnow
from ygc.extractors.normalization import (
    normalize_manufacturer, normalize_model, normalize_serial,
)


def stage_candidate(repository: Repository, claim: dict, provenance: dict) -> bool:
    """Checkpoint extraction before advancing a search cursor."""
    listing_id = str(provenance.get("source_listing_id") or "")
    maker = normalize_manufacturer(claim.get("manufacturer"))
    if (not listing_id or maker in ("", "unknown", "n/a", "unbranded") or
            not normalize_serial(claim.get("serial_number"))):
        return False
    with repository.connect() as con:
        if con.execute("SELECT 1 FROM observations WHERE source_site='reverb' AND source_listing_id=?",
                       (listing_id,)).fetchone():
            return False
        con.execute(
            """INSERT INTO crawl_candidates
               (source_site, source_listing_id, claim_json, provenance_json, status, reason, updated_at)
               VALUES ('reverb', ?, ?, ?, 'pending', NULL, ?)
               ON CONFLICT(source_site, source_listing_id) DO UPDATE SET
               claim_json=excluded.claim_json, provenance_json=excluded.provenance_json,
               status='pending', reason=NULL, updated_at=excluded.updated_at""",
            (listing_id, json.dumps(claim), json.dumps(provenance), utcnow()),
        )
    return True


def candidate_ids(repository: Repository, ids: list[str]) -> set[str]:
    found = set()
    with repository.connect() as con:
        for start in range(0, len(ids), 500):
            chunk = [str(item) for item in ids[start:start + 500] if item]
            if chunk:
                marks = ",".join("?" for _ in chunk)
                found.update(str(row[0]) for row in con.execute(
                    "SELECT source_listing_id FROM crawl_candidates WHERE source_site='reverb' "
                    f"AND source_listing_id IN ({marks})", chunk))
    return found


def reconcile_candidates(repository: Repository, progress_callback=None) -> dict[str, int]:
    """Read identity keys in bulk, then process durable candidates idempotently."""
    counts = {"new_individuals": 0, "existing_individuals_extended": 0,
              "ambiguous_matches": 0, "new_observations": 0}
    with repository.connect() as con:
        rows = list(con.execute(
            "SELECT * FROM crawl_candidates WHERE source_site='reverb' AND status='pending' "
            "ORDER BY source_listing_id"))
        identities = {}
        identity_counts = {}
    batch_models: dict[tuple[str, str], set[str | None]] = {}
    for row in rows:
        claim = json.loads(row["claim_json"])
        key = (normalize_manufacturer(claim.get("manufacturer")),
               normalize_serial(claim.get("serial_number")))
        batch_models.setdefault(key, set()).add(normalize_model(claim.get("model")))
    keys = list(batch_models)
    with repository.connect() as con:
        for start in range(0, len(keys), 400):
            chunk = keys[start:start + 400]
            marks = ",".join("(?,?)" for _ in chunk)
            for individual in con.execute(
                "SELECT normalized_manufacturer, normalized_serial, normalized_model "
                "FROM individuals WHERE (normalized_manufacturer, normalized_serial) IN "
                f"({marks})", [part for key in chunk for part in key]):
                key = (individual["normalized_manufacturer"], individual["normalized_serial"])
                identities.setdefault(key, set()).add(individual["normalized_model"])
                identity_counts[key] = identity_counts.get(key, 0) + 1
    for index, row in enumerate(rows, 1):
        claim = json.loads(row["claim_json"])
        provenance = json.loads(row["provenance_json"])
        key = (normalize_manufacturer(claim.get("manufacturer")),
               normalize_serial(claim.get("serial_number")))
        model = normalize_model(claim.get("model"))
        known = identities.get(key, set())
        ambiguous = (identity_counts.get(key, 0) > 1 or len(batch_models[key]) > 1 or
                     (known and (model is None or None in known or model not in known)))
        if ambiguous:
            counts["ambiguous_matches"] += 1
            with repository.connect() as con:
                con.execute("UPDATE crawl_candidates SET status='review', reason='identity_conflict', "
                            "updated_at=? WHERE source_site='reverb' AND source_listing_id=?",
                            (utcnow(), row["source_listing_id"]))
            if progress_callback and index % 10 == 0:
                progress_callback(index, len(rows), dict(counts))
            continue
        # persist_reverb_listing_claim performs a final duplicate check and writes
        # the Observation and Claim atomically. A crash before status update is safe.
        try:
            result = repository.persist_reverb_listing_claim(claim, provenance)
        except ValueError as exc:
            if "no active Listing Claim" not in str(exc):
                raise
            counts["ambiguous_matches"] += 1
            with repository.connect() as con:
                con.execute("UPDATE crawl_candidates SET status='review', reason='legacy_identity', "
                            "updated_at=? WHERE source_site='reverb' AND source_listing_id=?",
                            (utcnow(), row["source_listing_id"]))
            continue
        with repository.connect() as con:
            con.execute("UPDATE crawl_candidates SET status='stored', updated_at=? "
                        "WHERE source_site='reverb' AND source_listing_id=?",
                        (utcnow(), row["source_listing_id"]))
        if result["created"]:
            counts["new_observations"] += 1
            if known:
                counts["existing_individuals_extended"] += 1
            else:
                counts["new_individuals"] += 1
                identities.setdefault(key, set()).add(model)
                identity_counts[key] = 1
        if progress_callback and index % 10 == 0:
            progress_callback(index, len(rows), dict(counts))
    if progress_callback:
        progress_callback(len(rows), len(rows), dict(counts))
    return counts


def defer_listing(repository: Repository, listing_id: str, reason: str, days: int = 7) -> None:
    repository.cache_listing_rejection(
        "reverb", listing_id, reason,
        recheck_after=(datetime.now(timezone.utc) + timedelta(days=days)).isoformat(),
    )
