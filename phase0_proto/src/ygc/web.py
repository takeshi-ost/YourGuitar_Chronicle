from __future__ import annotations

import argparse
import re
import sqlite3
import tempfile
import threading
import time
import uuid
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from ygc import config
from ygc.collectors.reverb import ReverbAPICollector
from ygc.db.repository import Repository
from ygc.extractors.serial import extract_serial_candidates
from ygc.matching.individual_matcher import match_or_create
from ygc.reverb_adapter import classify_vintage_listing, to_observation


app = FastAPI(title="Your Guitar Chronicle Phase 0")

_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()
_active_job_id: str | None = None


def repo() -> Repository:
    repository = Repository(config.DB_PATH)
    repository.init_db()
    return repository


def _row_dict(row: Any) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _validate_import_database(
    path: Path,
) -> dict[str, int]:
    try:
        with path.open("rb") as file:
            header = file.read(16)
    except OSError as exc:
        raise ValueError(
            f"Could not read uploaded DB: {exc}"
        ) from exc

    if header != b"SQLite format 3\x00":
        raise ValueError(
            "Selected file is not a SQLite 3 database"
        )

    required_tables = {
        "individuals",
        "observations",
        "crawl_runs",
    }

    required_columns = {
        "individuals": {
            "id",
            "manufacturer",
            "normalized_manufacturer",
            "normalized_serial",
        },
        "observations": {
            "id",
            "source_site",
            "source_url",
            "source_listing_id",
            "observed_at",
        },
        "crawl_runs": {
            "id",
            "source_site",
            "status",
        },
    }

    try:
        with sqlite3.connect(path) as con:
            quick_check = con.execute(
                "PRAGMA quick_check"
            ).fetchone()

            if (
                not quick_check
                or str(
                    quick_check[0]
                ).lower()
                != "ok"
            ):
                raise ValueError(
                    "SQLite integrity check failed"
                )

            tables = {
                str(row[0])
                for row
                in con.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type='table'
                    """
                )
            }

            missing_tables = (
                required_tables
                - tables
            )

            if missing_tables:
                raise ValueError(
                    "Not a YGC database. "
                    "Missing tables: "
                    + ", ".join(
                        sorted(
                            missing_tables
                        )
                    )
                )

            for (
                table,
                expected,
            ) in required_columns.items():
                columns = {
                    str(row[1])
                    for row
                    in con.execute(
                        f"PRAGMA table_info({table})"
                    )
                }

                missing_columns = (
                    expected
                    - columns
                )

                if missing_columns:
                    raise ValueError(
                        "Not a compatible YGC database. "
                        f"{table} is missing: "
                        + ", ".join(
                            sorted(
                                missing_columns
                            )
                        )
                    )

            counts = {
                "observations": int(
                    con.execute(
                        """
                        SELECT COUNT(*)
                        FROM observations
                        """
                    ).fetchone()[0]
                ),
                "individuals": int(
                    con.execute(
                        """
                        SELECT COUNT(*)
                        FROM individuals
                        """
                    ).fetchone()[0]
                ),
                "crawl_runs": int(
                    con.execute(
                        """
                        SELECT COUNT(*)
                        FROM crawl_runs
                        """
                    ).fetchone()[0]
                ),
            }

    except sqlite3.Error as exc:
        raise ValueError(
            f"Could not open SQLite database: {exc}"
        ) from exc

    return counts


def _request_token(
    request: Request,
) -> tuple[str, str]:
    browser_token = (
        request.headers.get(
            "X-Reverb-Token",
            "",
        ).strip()
    )

    if browser_token:
        return (
            browser_token,
            "browser",
        )

    if config.REVERB_API_TOKEN:
        return (
            config.REVERB_API_TOKEN,
            "environment",
        )

    return (
        "",
        "none",
    )


def _existing_listing_ids(repository: Repository, listing_ids: list[str]) -> set[str]:
    ids = [value for value in listing_ids if value]
    if not ids:
        return set()

    result: set[str] = set()
    with repository.connect() as con:
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            placeholders = ",".join("?" for _ in chunk)
            rows = con.execute(
                "SELECT source_listing_id FROM observations "
                "WHERE source_site=? AND source_listing_id IN (" + placeholders + ")",
                ["reverb", *chunk],
            )
            result.update(str(row["source_listing_id"]) for row in rows)
    return result


def _remove_temporary_fields(observation: dict[str, Any]) -> tuple[str, str, int | None]:
    status = str(observation.pop("vintage_status", "unknown"))
    reason = str(observation.pop("vintage_reason", ""))
    year = observation.pop("estimated_year", None)
    observation.pop("is_vintage_listing", None)
    return status, reason, year


def _set_job(job_id: str, **values: Any) -> None:
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].update(values)


def _append_job_result(job_id: str, result: dict[str, Any]) -> None:
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].setdefault("query_results", []).append(result)


class CrawlRequest(BaseModel):
    queries: list[str] = Field(min_length=1, max_length=30)
    limit: int = Field(default=500, ge=1, le=5000)
    workers: int = Field(default=6, ge=1, le=12)
    year_min: int | None = Field(default=None, ge=1800, le=2100)
    year_max: int | None = Field(default=1980, ge=1800, le=2100)


class VintageAuditRequest(BaseModel):
    query: str
    limit: int = Field(default=100, ge=1, le=500)
    year_min: int | None = Field(default=None, ge=1800, le=2100)
    year_max: int | None = Field(default=1980, ge=1800, le=2100)


class ResetDatabaseRequest(BaseModel):
    confirm: str


def _run_batch(
    job_id: str,
    request: CrawlRequest,
    token: str,
) -> None:
    global _active_job_id

    repository = repo()
    total_queries = len(request.queries)
    aggregate = {
        "summaries_fetched": 0,
        "detail_candidates": 0,
        "details_fetched": 0,
        "skipped_modern": 0,
        "skipped_non_target": 0,
        "skipped_unknown": 0,
        "skipped_existing": 0,
        "new_observations": 0,
    }

    try:
        with ReverbAPICollector(
            token=token,
            api_base=config.REVERB_API_BASE,
            timeout=config.REQUEST_TIMEOUT,
            delay=0.15,
            max_workers=request.workers,
        ) as collector:
            for query_index, raw_query in enumerate(request.queries, start=1):
                query = raw_query.strip()
                if not query:
                    continue

                _set_job(
                    job_id,
                    message=f"{query_index}/{total_queries}: {query}",
                    current_query=query,
                    progress=(query_index - 1) / max(total_queries, 1),
                )

                run_id = repository.start_run("reverb")
                fetched = detailed = created = 0
                skipped_modern = skipped_non_target = skipped_unknown = skipped_existing = 0

                try:
                    summaries = list(
                        collector.iter_listing_summaries(
                            query=query,
                            limit=request.limit,
                            year_min=request.year_min,
                            year_max=request.year_max,
                        )
                    )
                    fetched = len(summaries)

                    listing_ids = [
                        collector.listing_id(item)
                        for item in summaries
                        if collector.listing_id(item)
                    ]
                    existing_ids = _existing_listing_ids(repository, listing_ids)

                    candidates: list[dict[str, Any]] = []
                    for item in summaries:
                        listing_id = collector.listing_id(item)
                        if listing_id and listing_id in existing_ids:
                            skipped_existing += 1
                            continue

                        status = classify_vintage_listing(item)["status"]
                        if status in ("vintage", "unknown"):
                            candidates.append(item)
                        elif status == "modern":
                            skipped_modern += 1
                        else:
                            skipped_non_target += 1

                    candidate_count = len(candidates)

                    for item in collector.fetch_listing_details(candidates):
                        detailed += 1
                        obs = to_observation(item, config.SERIAL_CONFIDENCE_THRESHOLD)
                        status, _reason, _year = _remove_temporary_fields(obs)

                        if status == "modern":
                            skipped_modern += 1
                            continue
                        if status == "non_target":
                            skipped_non_target += 1
                            continue
                        if status != "vintage":
                            skipped_unknown += 1
                            continue

                        if obs["manufacturer"] and obs["serial_number"]:
                            obs["individual_id"] = match_or_create(
                                repository,
                                obs["manufacturer"],
                                obs["model"],
                                obs["serial_number"],
                                finish=obs.get("finish"),
                                year=obs.get("year"),
                            )
                        else:
                            obs["individual_id"] = None

                        _, was_created = repository.upsert_observation(obs)
                        if was_created:
                            created += 1

                    repository.finish_run(
                        run_id,
                        pages_discovered=fetched,
                        pages_fetched=detailed,
                        observations_created=created,
                        status="ok",
                    )
                except Exception as exc:
                    repository.finish_run(
                        run_id,
                        pages_discovered=fetched,
                        pages_fetched=detailed,
                        observations_created=created,
                        status="error",
                        error_message=str(exc),
                    )
                    raise

                result = {
                    "query": query,
                    "summaries_fetched": fetched,
                    "detail_candidates": candidate_count,
                    "details_fetched": detailed,
                    "skipped_modern": skipped_modern,
                    "skipped_non_target": skipped_non_target,
                    "skipped_unknown": skipped_unknown,
                    "skipped_existing": skipped_existing,
                    "new_observations": created,
                }
                _append_job_result(job_id, result)

                for key in aggregate:
                    aggregate[key] += int(result[key])

        _set_job(
            job_id,
            status="done",
            message="完了",
            progress=1.0,
            aggregate=aggregate,
            finished_at=time.time(),
        )
    except Exception as exc:
        _set_job(
            job_id,
            status="error",
            message=str(exc),
            error=str(exc),
            finished_at=time.time(),
        )
    finally:
        with _jobs_lock:
            if _active_job_id == job_id:
                _active_job_id = None


def _run_metadata_backfill(
    job_id: str,
    token: str,
) -> None:
    global _active_job_id

    repository = repo()
    rows = (
        repository
        .list_observations_for_backfill()
    )
    total = len(rows)

    try:
        if total == 0:
            synced = (
                repository
                .sync_individual_metadata_from_observations()
            )
            _set_job(
                job_id,
                status="done",
                message=(
                    "バックフィル対象はありません"
                ),
                progress=1.0,
                aggregate={
                    "target_observations": 0,
                    "metadata_updated": 0,
                    "individuals_synced": synced,
                },
                finished_at=time.time(),
            )
            return

        row_by_listing = {
            str(
                row[
                    "source_listing_id"
                ]
            ): row
            for row in rows
        }

        metadata_updated = 0
        processed = 0

        with ReverbAPICollector(
            token=token,
            api_base=config.REVERB_API_BASE,
            timeout=config.REQUEST_TIMEOUT,
            delay=0.15,
            max_workers=6,
        ) as collector:
            for start in range(
                0,
                total,
                100,
            ):
                chunk = rows[
                    start:
                    start + 100
                ]

                items = [
                    {
                        "id": str(
                            row[
                                "source_listing_id"
                            ]
                        ),
                        "_links": {
                            "self": {
                                "href": (
                                    f"{config.REVERB_API_BASE.rstrip('/')}"
                                    "/listings/"
                                    f"{row['source_listing_id']}"
                                )
                            }
                        },
                    }
                    for row in chunk
                ]

                for detail in (
                    collector
                    .fetch_listing_details(
                        items
                    )
                ):
                    listing_id = (
                        collector
                        .listing_id(
                            detail
                        )
                    )

                    if not listing_id:
                        processed += 1
                        continue

                    row = (
                        row_by_listing
                        .get(
                            str(
                                listing_id
                            )
                        )
                    )

                    if row is None:
                        processed += 1
                        continue

                    model = str(
                        detail.get(
                            "model"
                        )
                        or ""
                    ).strip() or None

                    finish = str(
                        detail.get(
                            "finish"
                        )
                        or ""
                    ).strip() or None

                    year = str(
                        detail.get(
                            "year"
                        )
                        or ""
                    ).strip() or None

                    repository.update_observation_metadata(
                        int(
                            row["id"]
                        ),
                        model=model,
                        finish=finish,
                        year=year,
                    )

                    if (
                        model
                        or finish
                        or year
                    ):
                        metadata_updated += 1

                    processed += 1

                    _set_job(
                        job_id,
                        message=(
                            "既存DBをバックフィル中 "
                            f"{processed}/{total}"
                        ),
                        progress=(
                            processed
                            / max(
                                total,
                                1,
                            )
                        ),
                    )

        synced = (
            repository
            .sync_individual_metadata_from_observations()
        )

        _set_job(
            job_id,
            status="done",
            message=(
                "model / finish / year "
                "バックフィル完了"
            ),
            progress=1.0,
            aggregate={
                "target_observations": total,
                "metadata_updated": (
                    metadata_updated
                ),
                "individuals_synced": (
                    synced
                ),
            },
            finished_at=time.time(),
        )

    except Exception as exc:
        _set_job(
            job_id,
            status="error",
            message=str(exc),
            error=str(exc),
            finished_at=time.time(),
        )
    finally:
        with _jobs_lock:
            if (
                _active_job_id
                == job_id
            ):
                _active_job_id = None


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(INDEX_HTML)


@app.get("/api/status")
def api_status(
    request: Request,
) -> dict[str, Any]:
    repository = repo()
    token, token_source = (
        _request_token(
            request
        )
    )

    return {
        "token_configured": bool(
            token
        ),
        "token_source": (
            token_source
        ),
        "db_path": str(
            config.DB_PATH
        ),
        "stats": repository.stats(),
        "active_job_id": (
            _active_job_id
        ),
    }


@app.get("/api/export-db")
def api_export_db() -> FileResponse:
    repository = repo()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    download_name = f"ygc_chronicle_{timestamp}.db"

    temp_file = tempfile.NamedTemporaryFile(
        prefix="ygc_export_",
        suffix=".db",
        delete=False,
    )
    temp_path = Path(temp_file.name)
    temp_file.close()

    try:
        with repository.connect() as source:
            with sqlite3.connect(temp_path) as destination:
                source.backup(destination)

        return FileResponse(
            path=temp_path,
            filename=download_name,
            media_type="application/vnd.sqlite3",
            background=BackgroundTask(_safe_unlink, temp_path),
        )
    except Exception:
        _safe_unlink(temp_path)
        raise


@app.post("/api/import-db")
async def api_import_db(
    request: Request,
) -> dict[str, Any]:
    with _jobs_lock:
        if (
            _active_job_id
            and _jobs.get(
                _active_job_id,
                {},
            ).get("status")
            == "running"
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Cannot import a database "
                    "while a background job is running"
                ),
            )

    content_length = (
        request.headers.get(
            "content-length"
        )
    )

    max_size = (
        100
        * 1024
        * 1024
    )

    if content_length:
        try:
            if (
                int(
                    content_length
                )
                > max_size
            ):
                raise HTTPException(
                    status_code=413,
                    detail=(
                        "Database file is too large "
                        "(maximum 100 MB)"
                    ),
                )
        except ValueError:
            pass

    payload = await request.body()

    if not payload:
        raise HTTPException(
            status_code=400,
            detail=(
                "No database file was uploaded"
            ),
        )

    if len(payload) > max_size:
        raise HTTPException(
            status_code=413,
            detail=(
                "Database file is too large "
                "(maximum 100 MB)"
            ),
        )

    db_path = Path(
        config.DB_PATH
    )
    db_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_file = (
        tempfile
        .NamedTemporaryFile(
            prefix="ygc_import_",
            suffix=".db",
            dir=db_path.parent,
            delete=False,
        )
    )

    temp_path = Path(
        temp_file.name
    )

    try:
        temp_file.write(
            payload
        )
        temp_file.flush()
        temp_file.close()

        try:
            imported_counts = (
                _validate_import_database(
                    temp_path
                )
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=str(exc),
            ) from exc

        for sidecar in (
            Path(
                str(db_path)
                + "-wal"
            ),
            Path(
                str(db_path)
                + "-shm"
            ),
        ):
            _safe_unlink(
                sidecar
            )

        temp_path.replace(
            db_path
        )

        repository = Repository(
            db_path
        )
        repository.init_db()

        return {
            "ok": True,
            "db_path": str(
                db_path
            ),
            "imported_counts": (
                imported_counts
            ),
            "stats": (
                repository.stats()
            ),
        }

    finally:
        try:
            temp_file.close()
        except OSError:
            pass

        _safe_unlink(
            temp_path
        )


@app.post("/api/reset-db")
def api_reset_db(request: ResetDatabaseRequest) -> dict[str, Any]:
    if request.confirm != "RESET":
        raise HTTPException(
            status_code=400,
            detail="Confirmation text must be RESET",
        )

    with _jobs_lock:
        if (
            _active_job_id
            and _jobs.get(
                _active_job_id,
                {},
            ).get("status")
            == "running"
        ):
            raise HTTPException(
                status_code=409,
                detail="Cannot reset the database while a crawl is running",
            )

    db_path = Path(config.DB_PATH)

    for path in (
        db_path,
        Path(str(db_path) + "-wal"),
        Path(str(db_path) + "-shm"),
    ):
        try:
            path.unlink(
                missing_ok=True
            )
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail=(
                    "Could not remove "
                    f"{path}: {exc}"
                ),
            ) from exc

    repository = Repository(
        config.DB_PATH
    )
    repository.init_db()

    return {
        "ok": True,
        "db_path": str(
            config.DB_PATH
        ),
        "stats": repository.stats(),
    }


@app.get("/api/individuals")
def api_individuals() -> list[dict[str, Any]]:
    return [_row_dict(row) for row in repo().list_individuals()]


@app.get("/api/individuals/{individual_id}")
def api_individual(individual_id: int) -> dict[str, Any]:
    individual, observations = repo().get_individual(individual_id)
    if not individual:
        raise HTTPException(status_code=404, detail="Individual not found")
    return {
        "individual": _row_dict(individual),
        "observations": [_row_dict(row) for row in observations],
    }


@app.get("/api/serial-audit")
def api_serial_audit(limit: int = 100) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 500))
    repository = repo()

    with repository.connect() as con:
        rows = con.execute(
            """
            SELECT id, individual_id, manufacturer, model, serial_number,
                   title, raw_text, serial_confidence, source_url
            FROM observations
            WHERE serial_number IS NOT NULL AND TRIM(serial_number) <> ''
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    result: list[dict[str, Any]] = []
    for row in rows:
        candidates = extract_serial_candidates(row["raw_text"] or "")
        best = candidates[0] if candidates else None
        stored = str(row["serial_number"] or "")
        extracted = best.value if best else ""
        context = re.sub(r"\s+", " ", best.context).strip() if best else ""
        if len(context) > 220:
            context = context[:217] + "..."

        suspicious = bool(
            re.search(
                r"(XXXX|\?\?\?|THAT|DATES?TO|DATEBACK|--|YOUR)",
                stored,
                re.I,
            )
        )

        result.append(
            {
                "id": row["id"],
                "individual_id": row["individual_id"],
                "manufacturer": row["manufacturer"],
                "model": row["model"],
                "stored": stored,
                "extracted": extracted,
                "confidence": best.confidence if best else row["serial_confidence"],
                "match": bool(best and extracted.upper() == stored.upper()),
                "suspicious": suspicious,
                "context": context,
                "source_url": row["source_url"],
            }
        )
    return result


@app.post("/api/vintage-audit")
def api_vintage_audit(
    request: VintageAuditRequest,
    http_request: Request,
) -> dict[str, Any]:
    token, _token_source = (
        _request_token(
            http_request
        )
    )

    if not token:
        raise HTTPException(
            status_code=400,
            detail=(
                "Reverb API Token is not configured"
            ),
        )

    counts = {"vintage": 0, "modern": 0, "unknown": 0, "non_target": 0}
    rows: list[dict[str, Any]] = []

    with ReverbAPICollector(
        token=token,
        api_base=config.REVERB_API_BASE,
        timeout=config.REQUEST_TIMEOUT,
        delay=0.15,
        max_workers=6,
    ) as collector:
        for item in collector.iter_listing_summaries(
            request.query,
            request.limit,
            year_min=request.year_min,
            year_max=request.year_max,
        ):
            classification = classify_vintage_listing(item)
            status = classification["status"]
            counts[status] = counts.get(status, 0) + 1
            rows.append(
                {
                    "id": item.get("id"),
                    "status": status,
                    "estimated_year": classification["estimated_year"],
                    "reason": classification["reason"],
                    "title": item.get("title") or "",
                }
            )
    return {"counts": counts, "rows": rows}


@app.post("/api/crawl")
def api_crawl(
    request: CrawlRequest,
    http_request: Request,
) -> dict[str, str]:
    global _active_job_id

    token, _token_source = (
        _request_token(
            http_request
        )
    )

    if not token:
        raise HTTPException(
            status_code=400,
            detail=(
                "Reverb API Token is not configured"
            ),
        )

    queries = [query.strip() for query in request.queries if query.strip()]
    if not queries:
        raise HTTPException(status_code=400, detail="At least one query is required")

    with _jobs_lock:
        if _active_job_id and _jobs.get(_active_job_id, {}).get("status") == "running":
            raise HTTPException(status_code=409, detail="A crawl job is already running")

        job_id = uuid.uuid4().hex[:12]
        _jobs[job_id] = {
            "id": job_id,
            "status": "running",
            "message": "開始しています",
            "progress": 0.0,
            "queries": queries,
            "query_results": [],
            "started_at": time.time(),
        }
        _active_job_id = job_id

    actual = CrawlRequest(
        queries=queries,
        limit=request.limit,
        workers=request.workers,
        year_min=request.year_min,
        year_max=request.year_max,
    )
    threading.Thread(
        target=_run_batch,
        args=(
            job_id,
            actual,
            token,
        ),
        daemon=True,
    ).start()
    return {"job_id": job_id}


@app.post("/api/backfill-metadata")
def api_backfill_metadata(
    http_request: Request,
) -> dict[str, str]:
    global _active_job_id

    token, _token_source = (
        _request_token(
            http_request
        )
    )

    if not token:
        raise HTTPException(
            status_code=400,
            detail=(
                "Reverb API Token is not configured"
            ),
        )

    with _jobs_lock:
        if (
            _active_job_id
            and _jobs.get(
                _active_job_id,
                {},
            ).get("status")
            == "running"
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Another background job "
                    "is already running"
                ),
            )

        job_id = (
            uuid.uuid4()
            .hex[:12]
        )

        _jobs[job_id] = {
            "id": job_id,
            "status": "running",
            "message": (
                "既存DBのバックフィルを開始します"
            ),
            "progress": 0.0,
            "query_results": [],
            "started_at": time.time(),
        }

        _active_job_id = (
            job_id
        )

    threading.Thread(
        target=(
            _run_metadata_backfill
        ),
        args=(
            job_id,
            token,
        ),
        daemon=True,
    ).start()

    return {
        "job_id": job_id
    }


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str) -> dict[str, Any]:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return dict(job)


INDEX_HTML = r"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Your Guitar Chronicle — Phase 0</title>
<style>
:root{color-scheme:dark;--bg:#101214;--panel:#181b1f;--line:#2a2f35;--text:#edf0f3;--muted:#9ba6b0;--accent:#d0a45d;--good:#66c58a;--warn:#e0b65f;--bad:#e07171}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
header{padding:24px 28px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:20px}
h1{font-size:22px;margin:0}h2{font-size:17px;margin:0 0 14px}.sub{color:var(--muted);font-size:12px}
main{padding:22px;max-width:1500px;margin:auto}.grid{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(360px,.85fr);gap:18px;align-items:start}.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px;margin-bottom:18px}.crawl-query{margin-bottom:12px}.crawl-controls{display:grid;grid-template-columns:110px 110px 130px 110px auto;gap:10px;align-items:end}.crawl-controls button{white-space:nowrap}
.cards{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:18px}.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}.num{font-size:24px;font-weight:700}.label{font-size:11px;color:var(--muted)}
input,textarea,select,button{font:inherit}input,textarea,select{width:100%;background:#111418;color:var(--text);border:1px solid #343b43;border-radius:8px;padding:9px 10px}textarea{min-height:145px;resize:vertical}
button{border:0;border-radius:8px;padding:9px 13px;background:var(--accent);color:#18130c;font-weight:700;cursor:pointer}button.secondary{background:#2a3036;color:var(--text)}button:disabled{opacity:.45;cursor:not-allowed}
.row{display:grid;grid-template-columns:1fr 90px 90px 110px 90px auto;gap:10px;align-items:end}
table{width:100%;border-collapse:collapse;font-size:12px}th,td{text-align:left;border-bottom:1px solid var(--line);padding:8px 7px;vertical-align:top}th{color:var(--muted);font-weight:600;position:sticky;top:0;background:var(--panel)}th.sortable{cursor:pointer;user-select:none}th.sortable:hover{color:var(--text)}th.sortable .sort-indicator{font-size:10px;margin-left:4px}
.table-wrap{max-height:520px;overflow:auto;border:1px solid var(--line);border-radius:8px}.status{display:inline-block;padding:3px 7px;border-radius:999px;font-size:11px;background:#2b3035}.good{color:var(--good)}.warn{color:var(--warn)}.bad{color:var(--bad)}
.progress{height:8px;background:#252b31;border-radius:99px;overflow:hidden;margin:10px 0}.bar{height:100%;background:var(--accent);width:0;transition:width .25s}
.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px}.toolbar input{max-width:300px}.clickable{cursor:pointer}.clickable:hover{background:#20252a}.mono{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
#detail{white-space:pre-wrap}.pill{display:inline-block;padding:2px 6px;border:1px solid var(--line);border-radius:10px;margin-right:5px;color:var(--muted)}
.modal-backdrop{display:none;position:fixed;inset:0;background:rgba(0,0,0,.65);align-items:center;justify-content:center;z-index:1000}.modal-backdrop.open{display:flex}.modal{width:min(520px,calc(100vw - 32px));background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px;box-shadow:0 18px 60px rgba(0,0,0,.45)}.modal-actions{display:flex;gap:8px;justify-content:flex-end;margin-top:14px}
@media(max-width:900px){.grid{grid-template-columns:1fr}.cards{grid-template-columns:repeat(2,1fr)}.crawl-controls{grid-template-columns:repeat(2,minmax(0,1fr))}.crawl-controls>div:last-child{grid-column:1/-1}.crawl-controls button{width:100%}}
</style>
</head>
<body>
<header><div><h1>Your Guitar Chronicle <span class="sub">Phase 0 Browser Console</span></h1><div class="sub">Reverb収集・Individual確認をブラウザから操作</div></div><div class="toolbar" style="margin:0"><div id="tokenState"></div><button class="secondary" onclick="openTokenSettings()">Token設定</button><button class="secondary" onclick="exportDatabase()">DBエクスポート</button><button class="secondary" onclick="openDatabaseImport()">DBインポート</button><button class="secondary bad" onclick="resetDatabase()">DB初期化</button></div></header>
<main>
<div class="cards" id="cards"></div>
<div class="panel">
<h2>Batch Crawl</h2>
<div class="crawl-query">
<div class="sub">1行につき1クエリ</div>
<textarea id="queries">Fender Stratocaster
Fender Telecaster
Fender Jazzmaster
Fender Jaguar
Gibson Les Paul
Gibson SG
Gibson ES-335</textarea>
</div>
<div class="crawl-controls">
<div><div class="sub">Year Min</div><input id="yearMin" type="number" placeholder="なし" min="1800" max="2100"></div>
<div><div class="sub">Year Max</div><input id="yearMax" type="number" value="1980" min="1800" max="2100"></div>
<div><div class="sub">Limit / query</div><input id="limit" type="number" value="500" min="1" max="5000"></div>
<div><div class="sub">Workers</div><input id="workers" type="number" value="6" min="1" max="12"></div>
<div><button id="crawlBtn" onclick="startCrawl()">Start Crawl</button></div>
</div>
<div class="progress"><div class="bar" id="jobBar"></div></div>
<div id="jobMessage" class="sub">待機中</div>
<div id="jobResults" style="margin-top:12px"></div>
</div>

<div class="grid">
<section>
<div class="panel">
<div class="toolbar"><h2 style="margin:0;flex:1">Individuals</h2><input id="individualFilter" placeholder="maker / model / finish / year / serial" oninput="renderIndividuals()"><button class="secondary" onclick="startBackfill()">既存DBバックフィル（今回のみ）</button><button class="secondary" onclick="loadIndividuals()">更新</button></div>
<div class="table-wrap"><table><thead><tr><th class="sortable" onclick="setIndividualSort('id')">ID<span class="sort-indicator" id="sort-id"></span></th><th class="sortable" onclick="setIndividualSort('manufacturer')">Maker<span class="sort-indicator" id="sort-manufacturer"></span></th><th class="sortable" onclick="setIndividualSort('model')">Model<span class="sort-indicator" id="sort-model"></span></th><th class="sortable" onclick="setIndividualSort('finish')">Finish<span class="sort-indicator" id="sort-finish"></span></th><th class="sortable" onclick="setIndividualSort('year')">Year<span class="sort-indicator" id="sort-year"></span></th><th class="sortable" onclick="setIndividualSort('serial_number')">Serial<span class="sort-indicator" id="sort-serial_number"></span></th><th class="sortable" onclick="setIndividualSort('observation_count')">Obs<span class="sort-indicator" id="sort-observation_count"></span></th></tr></thead><tbody id="individualBody"></tbody></table></div>
</div>
</section>

<section>
<div class="panel">
<h2>Individual Detail</h2>
<div id="detail" class="sub">Individuals の行をクリックすると履歴を表示します。</div>
</div>
</section>
</div>
</main>
<input id="dbImportInput" type="file" accept=".db,application/vnd.sqlite3,application/x-sqlite3" style="display:none" onchange="importDatabaseFile(this)">
<div class="modal-backdrop" id="tokenModal" onclick="closeTokenSettings(event)">
  <div class="modal" onclick="event.stopPropagation()">
    <h2>Reverb API Token</h2>
    <div class="sub" style="margin-bottom:10px">TokenはこのブラウザのlocalStorageに保存されます。SQLite DBやGitHubには保存しません。</div>
    <input id="tokenInput" type="password" autocomplete="off" placeholder="Reverb Personal Access Token">
    <div class="modal-actions">
      <button class="secondary bad" onclick="clearToken()">削除</button>
      <button class="secondary" onclick="closeTokenSettings()">キャンセル</button>
      <button onclick="saveToken()">保存</button>
    </div>
  </div>
</div>
<script>
let individuals=[];
let individualSortKey='id';
let individualSortDirection=1;
const TOKEN_KEY='ygc_reverb_api_token';
const esc=s=>String(s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[m]));
function storedToken(){return (localStorage.getItem(TOKEN_KEY)||'').trim()}
async function jfetch(url,opt={}){const headers=new Headers(opt.headers||{});const token=storedToken();if(token)headers.set('X-Reverb-Token',token);const r=await fetch(url,{...opt,headers});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||r.statusText);return d}
function statCard(label,value){return '<div class="card"><div class="num">'+esc(value)+'</div><div class="label">'+esc(label)+'</div></div>'}
async function refreshStatus(){const d=await jfetch('/api/status');const s=d.stats;document.getElementById('cards').innerHTML=[
statCard('Observations',s.observations),statCard('Serial Observations',s.serial_observations),statCard('Serial Rate',s.serial_extraction_rate.toFixed(1)+'%'),statCard('Individuals',s.individuals),statCard('Repeated',s.repeated_individuals)
].join('');const source=d.token_source==='browser'?'WebUI保存':(d.token_source==='environment'?'環境変数':'');document.getElementById('tokenState').innerHTML=d.token_configured?'<span class="status good">Reverb Token OK'+(source?' / '+source:'')+'</span>':'<span class="status bad">Reverb Token 未設定</span>'}
function openTokenSettings(){document.getElementById('tokenInput').value=storedToken();document.getElementById('tokenModal').classList.add('open');setTimeout(()=>document.getElementById('tokenInput').focus(),0)}
function closeTokenSettings(event){if(event&&event.target&&event.target.id!=='tokenModal')return;document.getElementById('tokenModal').classList.remove('open');document.getElementById('tokenInput').value=''}
async function saveToken(){const token=document.getElementById('tokenInput').value.trim();if(!token){alert('Tokenを入力してください。');return}localStorage.setItem(TOKEN_KEY,token);closeTokenSettings();await refreshStatus()}
async function clearToken(){localStorage.removeItem(TOKEN_KEY);closeTokenSettings();await refreshStatus()}
function exportDatabase(){window.location.href='/api/export-db'}
function openDatabaseImport(){const input=document.getElementById('dbImportInput');input.value='';input.click()}
async function importDatabaseFile(input){
  const file=input.files&&input.files[0];
  if(!file)return;
  const message='現在のDBを選択したエクスポートDBで置き換えます。\n\n'+file.name+'\n\n実行前に必要であれば現在のDBをエクスポートしてください。続行しますか？';
  if(!confirm(message)){input.value='';return}
  try{
    const d=await jfetch('/api/import-db',{
      method:'POST',
      headers:{'Content-Type':'application/octet-stream'},
      body:file
    });
    individuals=[];
    document.getElementById('detail').textContent='Individuals の行をクリックすると履歴を表示します。';
    document.getElementById('jobResults').innerHTML='';
    document.getElementById('jobMessage').textContent='DBをインポートしました';
    document.getElementById('jobBar').style.width='0%';
    await refreshStatus();
    await loadIndividuals();
    const imported=d.imported_counts||{};
    alert('DBをインポートしました。\nObservations: '+(imported.observations??'')+'\nIndividuals: '+(imported.individuals??'')+'\nCrawl Runs: '+(imported.crawl_runs??''));
  }catch(e){
    alert('DBインポートに失敗しました。\n'+e.message);
  }finally{
    input.value='';
  }
}
async function resetDatabase(){
  const message='現在のObservation / Individual / Crawl履歴をすべて削除し、空のDBを作り直します。\n\nこの操作は元に戻せません。実行しますか？';
  if(!confirm(message))return;
  const typed=prompt('確認のため RESET と入力してください。');
  if(typed!=='RESET'){
    if(typed!==null)alert('入力が一致しないため中止しました。');
    return;
  }
  try{
    await jfetch('/api/reset-db',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({confirm:'RESET'})
    });
    individuals=[];
    document.getElementById('individualBody').innerHTML='';
    document.getElementById('detail').textContent='Individuals の行をクリックすると履歴を表示します。';
    document.getElementById('jobResults').innerHTML='';
    document.getElementById('jobMessage').textContent='DBを初期化しました';
    document.getElementById('jobBar').style.width='0%';
    await refreshStatus();
    await loadIndividuals();
    alert('DBを初期化しました。');
  }catch(e){
    alert(e.message);
  }
}
async function loadIndividuals(){individuals=await jfetch('/api/individuals');renderIndividuals()}
function normalizeSortValue(value,key){if(key==='id'||key==='observation_count')return Number(value||0);return String(value??'').toLowerCase()}
function setIndividualSort(key){if(individualSortKey===key){individualSortDirection*=-1}else{individualSortKey=key;individualSortDirection=1}renderIndividuals()}
function updateSortIndicators(){for(const key of ['id','manufacturer','model','finish','year','serial_number','observation_count']){const el=document.getElementById('sort-'+key);if(el)el.textContent=individualSortKey===key?(individualSortDirection===1?'▲':'▼'):''}}
function renderIndividuals(){const q=document.getElementById('individualFilter').value.toLowerCase();const rows=individuals.filter(x=>[x.manufacturer,x.model,x.finish,x.year,x.serial_number].join(' ').toLowerCase().includes(q)).slice().sort((a,b)=>{const av=normalizeSortValue(a[individualSortKey],individualSortKey);const bv=normalizeSortValue(b[individualSortKey],individualSortKey);if(av<bv)return-1*individualSortDirection;if(av>bv)return 1*individualSortDirection;return Number(a.id)-Number(b.id)});updateSortIndicators();document.getElementById('individualBody').innerHTML=rows.map(x=>'<tr class="clickable" onclick="showIndividual('+x.id+')"><td>'+x.id+'</td><td>'+esc(x.manufacturer)+'</td><td>'+esc(x.model)+'</td><td>'+esc(x.finish||'')+'</td><td>'+esc(x.year||'')+'</td><td class="mono">'+esc(x.serial_number)+'</td><td>'+x.observation_count+'</td></tr>').join('')}
async function showIndividual(id){const d=await jfetch('/api/individuals/'+id);const i=d.individual;let out='<b>#'+i.id+' '+esc(i.manufacturer)+'</b>\nModel: '+esc(i.model||'')+'\nFinish: '+esc(i.finish||'')+'\nYear: '+esc(i.year||'')+'\nSerial: '+esc(i.serial_number||'')+'\n\n';const observations=d.observations||[];const latestIndex=observations.length-1;for(let index=0;index<observations.length;index++){const o=observations[index];out+=esc(o.listing_date||o.observed_at)+'\nModel: '+esc(o.model||'')+'\nFinish: '+esc(o.finish||'')+'\nYear: '+esc(o.year||'')+'\n'+esc(o.seller||'')+'\n'+esc(o.title||'')+'\n';const url=String(o.source_url||'');if(url&&index===latestIndex){out+='<a href="'+esc(url)+'" target="_blank" rel="noopener noreferrer">'+esc(url)+'</a>\n\n'}else{out+=esc(url)+'\n\n'}}document.getElementById('detail').innerHTML=out}
async function startBackfill(){if(!confirm('既存Reverb Listingを再取得して model / finish / year をバックフィルします。初回移行用の処理です。実行しますか？'))return;try{const d=await jfetch('/api/backfill-metadata',{method:'POST'});pollJob(d.job_id)}catch(e){alert(e.message)}}
async function startCrawl(){const queries=document.getElementById('queries').value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);const minValue=document.getElementById('yearMin').value;const maxValue=document.getElementById('yearMax').value;const body={queries,limit:Number(document.getElementById('limit').value),workers:Number(document.getElementById('workers').value),year_min:minValue?Number(minValue):null,year_max:maxValue?Number(maxValue):null};const btn=document.getElementById('crawlBtn');btn.disabled=true;try{const d=await jfetch('/api/crawl',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});pollJob(d.job_id)}catch(e){alert(e.message);btn.disabled=false}}
async function pollJob(id){try{const d=await jfetch('/api/jobs/'+id);document.getElementById('jobBar').style.width=((d.progress||0)*100)+'%';document.getElementById('jobMessage').textContent=d.message||d.status;let resultHtml=(d.query_results||[]).map(x=>'<div class="sub">'+esc(x.query)+' — new '+x.new_observations+', detail '+x.details_fetched+', existing '+x.skipped_existing+'</div>').join('');if(d.aggregate&&d.aggregate.target_observations!==undefined){resultHtml+='<div class="sub">Backfill — target '+d.aggregate.target_observations+', updated '+d.aggregate.metadata_updated+', individuals '+d.aggregate.individuals_synced+'</div>'}document.getElementById('jobResults').innerHTML=resultHtml;if(d.status==='running'){setTimeout(()=>pollJob(id),1000)}else{document.getElementById('crawlBtn').disabled=false;await refreshStatus();await loadIndividuals();if(d.status==='error')alert(d.error||'crawl error')}}catch(e){document.getElementById('crawlBtn').disabled=false;alert(e.message)}}
(async()=>{await refreshStatus();await loadIndividuals()})()
</script>
</body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Your Guitar Chronicle Phase 0 browser GUI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://{args.host}:{args.port}")).start()

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
