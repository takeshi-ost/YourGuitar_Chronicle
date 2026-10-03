from __future__ import annotations

import argparse
import os
import ipaddress
import secrets
import json
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import uuid
import webbrowser
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response, JSONResponse
from pydantic import BaseModel, Field
from ygc.claim_dates import ClaimDateRequest, validate_claim_date, viewer_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from ygc import config

CONSOLE_ADMIN_TOKEN = secrets.token_urlsafe(32)


def _local_console_request(request: Request) -> bool:
    try:
        return bool(request.client and ipaddress.ip_address(request.client.host).is_loopback
                    and (request.url.hostname == "localhost" or
                         ipaddress.ip_address(request.url.hostname or "").is_loopback))
    except ValueError:
        return False


def _console_admin_authorized(request: Request) -> bool:
    token = request.headers.get("X-YGC-Console-Admin", "")
    return bool(_local_console_request(request) and secrets.compare_digest(token, CONSOLE_ADMIN_TOKEN))


def _require_console_admin(request: Request) -> None:
    if not _console_admin_authorized(request):
        raise HTTPException(status_code=403, detail="Local Browser Console administrator access required")
from ygc.collectors.reverb import ReverbAPICollector
from ygc.crawl_service import crawl_query
from ygc.crawl_detail_cache import reprocess_details
from ygc.incremental_crawl import advance_program, program_status, restart_program
from ygc.db.repository import Repository
from ygc.db.source_records import MARKETPLACE_SOURCES_SQL
from ygc.theme_catalog import THEMES
from ygc.platform_boundaries import (CrawlStep, LocalCrawlRunner, PrototypeIdentity,
                                     local_repository, require_local_platform,
                                     PlatformAdapterRequired)
from ygc.extractors.serial import extract_serial_candidates
from ygc.reverb_adapter import (
    classify_vintage_listing,
    to_listing_claim_data,
    to_provenance_observation,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    require_local_platform()
    local_repository(config.DB_PATH).init_db()
    stop_auto=threading.Event()
    worker=threading.Thread(target=_auto_crawl_loop,args=(stop_auto,),daemon=True)
    worker.start()
    backup_worker=threading.Thread(target=_backup_loop,args=(stop_auto,),daemon=True)
    backup_worker.start()
    try:
        yield
    finally:
        stop_auto.set()
        worker.join(timeout=2)
        backup_worker.join(timeout=2)


app = FastAPI(title="Your Guitar Chronicle Phase 1", lifespan=lifespan)

_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()
_active_job_id: str | None = None


MEDIA_DIR = config.DATA_DIR / "media"
MAX_IMAGE_BYTES = 12 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


@app.post("/api/admin/direct-experiment/prepare")
async def api_direct_prepare(request: Request, application_id: str = Form(..., max_length=80),
    serial: str = Form(..., max_length=160), challenge: str = Form(..., max_length=40),
    closeup: UploadFile = File(...), overview: UploadFile = File(...), reference: UploadFile = File(...)):
    _require_console_admin(request)
    from ygc.direct_experiment import prepare
    contents = []
    for upload in (closeup, overview, reference):
        content = await upload.read(MAX_IMAGE_BYTES + 1)
        if not content or len(content) > MAX_IMAGE_BYTES:
            raise HTTPException(400, '各画像は空でなく12MB以下にしてください。')
        contents.append(content)
    try:
        return await run_in_threadpool(prepare, application_id, serial, challenge, contents)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/admin/direct-experiment")
def api_direct_status(request: Request, revision: str | None = Query(None, max_length=64)):
    _require_console_admin(request)
    from ygc.direct_experiment import status
    try:
        return status(revision)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.delete("/api/admin/direct-experiment")
def api_direct_revoke(request: Request):
    _require_console_admin(request)
    from ygc.direct_experiment import revoke
    return revoke()


@app.post("/api/admin/direct-experiment/connection")
def api_direct_connection(request: Request):
    _require_console_admin(request)
    from ygc.direct_experiment import connection
    return JSONResponse(connection(), headers={'Cache-Control':'no-store'})


@app.post("/api/admin/direct-experiment/jobs/{revision}/{action}")
def api_direct_manage(request: Request, revision: str, action: str):
    _require_console_admin(request)
    from ygc.direct_experiment import manage
    try:
        return manage(revision, action)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.api_route("/api/experiments/direct/mcp", methods=['POST', 'GET', 'DELETE'])
async def api_direct_mcp(request: Request):
    from ygc import direct_experiment as direct
    # Local desktop experiment only; never expose the full Browser Console remotely.
    if not _local_console_request(request):
        raise HTTPException(403, 'Local experiment only')
    origin = request.headers.get('origin')
    if origin and origin != str(request.base_url).rstrip('/'):
        raise HTTPException(403, 'Origin not allowed')
    authorization = request.headers.get('authorization', '')
    token = authorization[7:] if authorization.startswith('Bearer ') else ''
    if not direct.authorized(token):
        raise HTTPException(401, 'Invalid or expired experiment token')
    if request.method != 'POST':
        return Response(status_code=405, headers={'Allow':'POST'})
    if request.headers.get('content-type', '').split(';')[0] != 'application/json':
        raise HTTPException(415, 'application/json required')
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 100_000:
            raise HTTPException(413, 'MCP request too large')
    try:
        message = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return JSONResponse({'jsonrpc':'2.0', 'id':None, 'error':{'code':-32700,'message':'Parse error'}})
    # Recheck inside the job lock so replacement/revocation cannot race a call.
    with direct.LOCK:
        if not direct.authorized(token):
            raise HTTPException(401, 'Invalid or expired experiment token')
        result = direct.rpc(message)
    if result is None:
        return Response(status_code=202)
    return JSONResponse(result, headers={'Cache-Control':'no-store'})


NO_PICTURE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 360" role="img" aria-label="No picture">
<rect width="640" height="360" rx="24" fill="#14171a"/>
<rect x="18" y="18" width="604" height="324" rx="18" fill="none" stroke="#343b43" stroke-width="4"/>
<g fill="none" stroke="#8b949e" stroke-width="14" stroke-linecap="round" stroke-linejoin="round" opacity=".9">
<path d="M204 221c34-55 75-75 112-54 26 15 43 10 66-11 27-24 62-7 57 25-4 28-35 38-63 25-29-13-44-11-66 13-31 34-78 37-106 2z"/>
<path d="M383 171l94-94"/>
<path d="M464 91l38-38"/>
<path d="M487 66l24 24"/>
</g>
<text x="320" y="300" text-anchor="middle" fill="#8b949e" font-family="Arial, sans-serif" font-size="28" font-weight="700" letter-spacing="3">NO PICTURE</text>
</svg>"""

NO_ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" role="img" aria-label="No user icon">
<rect width="256" height="256" rx="36" fill="#14171a"/>
<circle cx="128" cy="92" r="42" fill="#59636d"/>
<path d="M51 218c7-47 36-76 77-76s70 29 77 76" fill="#59636d"/>
<rect x="12" y="12" width="232" height="232" rx="30" fill="none" stroke="#343b43" stroke-width="4"/>
</svg>"""


def repo() -> Repository:
    return local_repository(config.DB_PATH)


def prototype_viewer(request: Request, claimed_id: int | None) -> int | None:
    if os.getenv('YGC_IDENTITY_BACKEND', 'prototype') == 'local_dummy':
        actor = getattr(request.state, 'local_actor', None)
        if claimed_id is not None and (not actor or actor['id'] != claimed_id):
            if not _console_admin_authorized(request):
                raise HTTPException(status_code=403, detail='The requested user does not match the signed-in account.')
            return claimed_id
        return actor['id'] if actor else None
    bearer = request.headers.get("Authorization", "")
    try:
        actor = PrototypeIdentity().resolve(
            bearer_token=bearer if bearer else None, prototype_user_id=claimed_id)
    except PlatformAdapterRequired as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return actor.user_id


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


class CrawlAdvanceRequest(BaseModel):
    category: str = Field(pattern="^(electric|acoustic|electric_acoustic)$")
    year_min: int = Field(ge=1800, le=2100)
    year_max: int = Field(ge=1800, le=2100)


class VintageAuditRequest(BaseModel):
    query: str
    limit: int = Field(default=100, ge=1, le=500)
    year_min: int | None = Field(default=None, ge=1800, le=2100)
    year_max: int | None = Field(default=1980, ge=1800, le=2100)


class ResetDatabaseRequest(BaseModel):
    confirm: str


class UserUpdateRequest(BaseModel):
    display_name: str = Field(
        min_length=1,
        max_length=120,
    )
    account_type: str = Field(
        default="user",
        max_length=20,
    )
    location_country: str | None = Field(
        default=None,
        max_length=80,
    )
    location_region: str | None = Field(
        default=None,
        max_length=120,
    )
    bio: str | None = Field(default=None, max_length=2000)
    date_of_birth: str | None = None
    birth_visibility: str | None = None
    residence_visibility: str | None = None
    bio_visibility: str | None = None
    avatar_visibility: str | None = None
    signature_individual_id: int | None = None
    theme: str | None = None


class AdminUserUpdateRequest(BaseModel):
    display_name: str = Field(min_length=1,max_length=120)
    account_type: str
    location_country: str | None = Field(default=None,max_length=80)
    location_region: str | None = Field(default=None,max_length=120)
    bio: str | None = Field(default=None,max_length=2000)
    birth_visibility: str
    residence_visibility: str
    bio_visibility: str
    avatar_visibility: str
    signature_individual_id: int | None = None
    ban_status: str
    theme: str = 'dark_default'


class UserGuitarLinkRequest(ClaimDateRequest):
    ownership_status: str = Field(
        default="current_owner",
        max_length=30,
    )
    acquired_at: str | None = Field(
        default=None,
        max_length=40,
    )
    released_at: str | None = Field(
        default=None,
        max_length=40,
    )


class UserGuitarOrderRequest(BaseModel):
    individual_ids: list[int] = Field(
        min_length=0,
        max_length=500,
    )


class SpecificationItemRequest(BaseModel):
    field_name: str = Field(
        min_length=1,
        max_length=120,
    )
    value_text: str = Field(
        min_length=1,
        max_length=500,
    )


class SpecificationClaimRequest(ClaimDateRequest):
    user_id: int = Field(ge=1)
    specification_kind: str = Field(
        default="specification",
        max_length=20,
    )
    items: list[SpecificationItemRequest] = Field(
        min_length=1,
        max_length=50,
    )
    occurred_at: str | None = Field(
        default=None,
        max_length=40,
    )
    body: str | None = Field(
        default=None,
        max_length=2000,
    )


class EventClaimRequest(ClaimDateRequest):
    user_id: int = Field(ge=1)
    event_kind: str = Field(max_length=30)
    occurred_at: str | None = Field(default=None, max_length=40)
    detail: str = Field(min_length=1, max_length=2000)


class IncidentClaimRequest(ClaimDateRequest):
    user_id: int = Field(ge=1)
    incident_kind: str = Field(max_length=20)
    occurred_at: str | None = Field(default=None, max_length=40)
    detail: str = Field(min_length=1, max_length=2000)


class OwnershipClaimRequest(ClaimDateRequest):
    user_id: int = Field(ge=1)
    ownership_kind: str = Field(
        default="acquire",
        max_length=20,
    )
    occurred_at: str | None = Field(
        default=None,
        max_length=40,
    )
    previous_owner_text: str | None = Field(
        default=None,
        max_length=160,
    )
    body: str | None = Field(
        default=None,
        max_length=2000,
    )


class FormerOwnerClaimRequest(ClaimDateRequest):
    user_id: int = Field(ge=1)
    acquisition_date: str = Field(min_length=10, max_length=10)
    release_date: str = Field(min_length=10, max_length=10)
    detail: str | None = Field(
        default=None,
        max_length=2000,
    )



class ClaimResponseRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=4000)
    responder_user_id: int = Field(ge=1)
    stance: str = Field(max_length=20)


class ClaimVoteRequest(BaseModel):
    user_id: int = Field(ge=1)
    vote: str = Field(max_length=10)


class ClaimEditRequest(ClaimDateRequest):
    user_id: int = Field(ge=1)
    occurred_at: str | None = Field(
        default=None,
        max_length=40,
    )
    body: str | None = Field(
        default=None,
        max_length=2000,
    )


class ClaimDeactivateRequest(BaseModel):
    user_id: int = Field(ge=1)


class IdentityCorrectionRequest(BaseModel):
    user_id: int = Field(ge=1)
    manufacturer: str = Field(
        min_length=1,
        max_length=120,
    )
    model: str | None = Field(
        default=None,
        max_length=160,
    )
    year: str | None = Field(
        default=None,
        max_length=40,
    )
    serial_number: str = Field(
        min_length=1,
        max_length=160,
    )
    reason: str | None = Field(
        default=None,
        max_length=2000,
    )


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
        "skipped_non_target": 0,
        "skipped_existing": 0,
        "new_observations": 0,
        "missing_identity": 0,
        "serial_candidates": 0,
        "new_individuals": 0,
        "existing_individuals_extended": 0,
        "ambiguous_matches": 0,
        "detail_unavailable": 0,
    }

    try:
        from ygc import crawl_backups
        crawl_backups.create(api_export_db)
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

                result = crawl_query(
                    repository, collector, query, request.limit,
                    year_min=request.year_min, year_max=request.year_max,
                )
                _append_job_result(job_id, result)

                for key in aggregate:
                    aggregate[key] += int(result[key])

        _set_job(
            job_id,
            status="done",
            message="Complete",
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
        .list_listing_claims_for_backfill()
    )
    total = len(rows)
    run_id = repository.start_run("reverb")
    counts = {"target_claims": total, "claims_updated": 0, "processed": 0}
    def checkpoint(phase):
        repository.update_crawl_run(run_id, phase, counts, "metadata_backfill", None, None)
    try:
        checkpoint("details")
        if total == 0:
            checkpoint("done")
            repository.finish_run(run_id, status="ok")
            _set_job(
                job_id,
                status="done",
                message=(
                    "No Claims need backfilling"
                ),
                progress=1.0,
                aggregate={
                    "target_claims": 0,
                    "claims_updated": 0,
                },
                finished_at=time.time(),
            )
            return

        row_by_listing = {
            str(
                row["source_listing_id"]
            ): row
            for row in rows
            if row["source_listing_id"]
        }

        claims_updated = 0
        processed = 0

        with ReverbAPICollector(
            token=token,
            api_base=config.REVERB_API_BASE,
            timeout=config.REQUEST_TIMEOUT,
            delay=0.15,
            max_workers=6,
        ) as collector:
            for start_index in range(
                0,
                total,
                100,
            ):
                chunk = rows[
                    start_index:
                    start_index + 100
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
                    if row["source_listing_id"]
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

                    claim_data = (
                        to_listing_claim_data(
                            detail,
                            config.SERIAL_CONFIDENCE_THRESHOLD,
                        )
                    )

                    if repository.supplement_listing_claim(
                        int(
                            row["claim_id"]
                        ),
                        claim_data,
                    ):
                        claims_updated += 1

                    processed += 1

                    counts.update(claims_updated=claims_updated, processed=processed)
                    checkpoint("details")
                    _set_job(
                        job_id,
                        message=(
                            "Backfilling Listing Claims "
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

        counts.update(claims_updated=claims_updated, processed=processed)
        checkpoint("done")
        repository.finish_run(run_id, pages_fetched=processed, status="ok")
        _set_job(
            job_id,
            status="done",
            message=(
                "Listing Claim backfill complete"
            ),
            progress=1.0,
            aggregate={
                "target_claims": total,
                "claims_updated": (
                    claims_updated
                ),
            },
            finished_at=time.time(),
        )

    except Exception as exc:
        checkpoint("error")
        repository.finish_run(run_id, status="error", error_message=str(exc))
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


def _backup_manifest(
    media_count: int,
) -> dict[str, Any]:
    return {
        "format": "your-guitar-chronicle-backup",
        "version": 1,
        "exported_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "database": "chronicle.db",
        "media_root": "media",
        "media_count": media_count,
    }


def _safe_backup_member(
    name: str,
) -> PurePosixPath:
    path = PurePosixPath(
        name
    )
    if (
        path.is_absolute()
        or ".." in path.parts
        or not path.parts
    ):
        raise ValueError(
            "Backup contains an unsafe path"
        )

    allowed = (
        name == "chronicle.db"
        or name == "manifest.json"
        or (
            path.parts[0] == "media"
            and len(path.parts) >= 2
        )
    )
    if not allowed:
        raise ValueError(
            f"Unexpected backup entry: {name}"
        )

    return path


def _validate_backup_archive(
    archive_path: Path,
    extract_root: Path,
) -> tuple[Path, Path, dict[str, Any]]:
    max_uncompressed = (
        1024
        * 1024
        * 1024
    )
    total_uncompressed = 0

    try:
        with zipfile.ZipFile(
            archive_path,
            "r",
        ) as archive:
            infos = archive.infolist()
            names = {
                info.filename
                for info in infos
            }
            if "chronicle.db" not in names:
                raise ValueError(
                    "Backup does not contain chronicle.db"
                )

            for info in infos:
                if info.is_dir():
                    continue

                member = _safe_backup_member(
                    info.filename
                )
                total_uncompressed += (
                    info.file_size
                )
                if (
                    total_uncompressed
                    > max_uncompressed
                ):
                    raise ValueError(
                        "Backup expands beyond the 1 GB safety limit"
                    )

                destination = (
                    extract_root
                    / Path(
                        *member.parts
                    )
                )
                destination.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                with archive.open(
                    info,
                    "r",
                ) as source:
                    with destination.open(
                        "wb",
                    ) as output:
                        shutil.copyfileobj(
                            source,
                            output,
                            length=1024 * 1024,
                        )

    except zipfile.BadZipFile as exc:
        raise ValueError(
            "Selected file is not a valid YGC backup ZIP"
        ) from exc

    manifest_path = (
        extract_root
        / "manifest.json"
    )
    manifest: dict[str, Any] = {}
    if manifest_path.is_file():
        try:
            manifest = json.loads(
                manifest_path.read_text(
                    encoding="utf-8"
                )
            )
        except (
            json.JSONDecodeError,
            OSError,
        ) as exc:
            raise ValueError(
                "Backup manifest is invalid"
            ) from exc

        if (
            manifest.get("format")
            != "your-guitar-chronicle-backup"
        ):
            raise ValueError(
                "Backup manifest format is not supported"
            )
        if int(
            manifest.get(
                "version",
                0,
            )
        ) != 1:
            raise ValueError(
                "Backup version is not supported"
            )

    db_path = (
        extract_root
        / "chronicle.db"
    )
    media_root = (
        extract_root
        / "media"
    )

    return (
        db_path,
        media_root,
        manifest,
    )


def _validate_backup_media_references(
    db_path: Path,
    media_root: Path,
) -> int:
    with sqlite3.connect(
        db_path
    ) as con:
        tables = {
            str(row[0])
            for row in con.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            )
        }
        if "media_assets" not in tables:
            return 0

        rows = list(
            con.execute(
                """
                SELECT storage_path
                FROM media_assets
                WHERE media_type = 'image'
                  AND storage_path IS NOT NULL
                  AND TRIM(storage_path) <> ''
                """
            )
        )

    checked = 0
    for row in rows:
        raw = str(
            row[0]
        ).strip()
        rel = PurePosixPath(
            raw
        )
        if (
            rel.is_absolute()
            or ".." in rel.parts
            or not rel.parts
            or rel.parts[0] != "media"
        ):
            raise ValueError(
                f"Invalid media path in backup database: {raw}"
            )

        file_path = (
            media_root.parent
            / Path(
                *rel.parts
            )
        )
        if not file_path.is_file():
            raise ValueError(
                "Backup is missing a media file "
                f"referenced by the database: {raw}"
            )
        checked += 1

    return checked


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    token = CONSOLE_ADMIN_TOKEN if _local_console_request(request) else ""
    return HTMLResponse((Path(__file__).with_name("static") / "index_html.html").read_text(encoding="utf-8").replace('const CONSOLE_ADMIN_TOKEN="";',
                        'const CONSOLE_ADMIN_TOKEN=' + json.dumps(token) + ';'),
                        headers={"Cache-Control": "no-store"})


@app.get("/user-view", response_class=HTMLResponse)
def user_view() -> HTMLResponse:
    return HTMLResponse((Path(__file__).with_name("static") / "user_view_html.html").read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


@app.get("/assets/themes.css")
def theme_stylesheet() -> FileResponse:
    return FileResponse(Path(__file__).with_name("static") / "themes.css", media_type="text/css", headers={"Cache-Control": "no-store"})


@app.get("/assets/list-navigation.js")
def list_navigation_script() -> FileResponse:
    return FileResponse(Path(__file__).with_name("static") / "list-navigation.js", media_type="text/javascript", headers={"Cache-Control": "no-store"})


@app.get("/assets/overlays.js")
def overlays_script() -> FileResponse:
    return FileResponse(Path(__file__).with_name("static") / "overlays.js", media_type="text/javascript", headers={"Cache-Control": "no-store"})


@app.get("/assets/ui-components.css")
def ui_components_stylesheet() -> FileResponse:
    return FileResponse(Path(__file__).with_name("static") / "ui-components.css", media_type="text/css", headers={"Cache-Control": "no-store"})


@app.get("/assets/i18n.js")
def localization_script() -> Response:
    from .localization import ui_resources
    resources = json.dumps(ui_resources(), ensure_ascii=True)
    script = (Path(__file__).with_name("static") / "i18n.js").read_text(encoding="utf-8")
    return Response("globalThis.YGCI18nResources=" + resources + ";\n" + script,
                    media_type="text/javascript", headers={"Cache-Control": "no-store"})


@app.get("/assets/pages/{filename}")
def page_asset(filename: str) -> FileResponse:
    allowed = {f'{page}.{extension}' for page in ('console', 'user-view', 'user-edit')
               for extension in ('js', 'css')}
    if filename not in allowed:
        raise HTTPException(status_code=404, detail="Asset not found")
    return FileResponse(Path(__file__).with_name("static") / "pages" / filename,
                        media_type="text/javascript" if filename.endswith('.js') else "text/css",
                        headers={"Cache-Control": "no-store"})


@app.get("/assets/product-detail.js")
def product_detail_script() -> FileResponse:
    return FileResponse(
        Path(__file__).with_name("static") / "product-detail.js",
        media_type="text/javascript",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/assets/logos/{filename}")
def theme_logo(filename: str) -> FileResponse:
    if filename not in {"script.png", "block.png", "badge.png"}:
        raise HTTPException(status_code=404, detail="Logo asset not found")
    return FileResponse(Path(__file__).with_name("static") / "logos" / filename, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.get("/assets/sunburst-wood.webp")
def sunburst_background() -> FileResponse:
    return FileResponse(Path(__file__).with_name("static") / "sunburst-wood.webp", media_type="image/webp")


@app.get("/assets/theme-textures/{filename}")
def theme_texture(filename: str) -> FileResponse:
    if filename not in {"butterscotch-wood.webp", "cherry-wood.webp", "white-pearl.webp", "rellic-black-wood.webp"}:
        raise HTTPException(status_code=404, detail="Theme asset not found")
    return FileResponse(Path(__file__).with_name("static") / filename, media_type="image/webp")


@app.get("/api/themes")
def api_themes() -> list[dict[str, str]]:
    return [{"id": key, "label": label} for key, label in THEMES]


@app.get("/user-view/edit", response_class=HTMLResponse)
def user_edit() -> HTMLResponse:
    return HTMLResponse(USER_EDIT_HTML, headers={"Cache-Control": "no-store"})


@app.get("/users/{user_id}", response_class=HTMLResponse)
def user_profile(
    user_id: int,
) -> HTMLResponse:
    return HTMLResponse((Path(__file__).with_name("static") / "user_view_html.html").read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


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


@app.get("/api/statistics")
def api_statistics() -> dict[str, Any]:
    return repo().statistics()


@app.get("/api/claims/unverified-acquires")
def api_unverified_acquires(limit: int = 100, offset: int = 0, without_request: bool = False) -> dict:
    if not 1 <= limit <= 200 or offset < 0:
        raise HTTPException(status_code=400, detail="Invalid pagination")
    return repo().unverified_acquires(limit, offset, without_request=without_request)


@app.get("/api/top-page-charts")
def api_top_page_charts() -> dict[str, Any]:
    repository = repo()
    today = datetime.now(timezone.utc).date()
    start_date = today - timedelta(days=29)

    with repository.connect() as con:
        model_rows = con.execute(
            """
            SELECT
                COALESCE(NULLIF(TRIM(model), ''), 'Unknown') AS label,
                COUNT(*) AS count
            FROM individuals
            GROUP BY COALESCE(NULLIF(TRIM(model), ''), 'Unknown')
            ORDER BY count DESC, label ASC
            """
        ).fetchall()

        year_rows = con.execute(
            """
            SELECT
                CAST(year AS TEXT) AS label,
                COUNT(*) AS count
            FROM individuals
            WHERE year IS NOT NULL
              AND TRIM(CAST(year AS TEXT)) <> ''
            GROUP BY CAST(year AS TEXT)
            ORDER BY CAST(year AS INTEGER) ASC, label ASC
            """
        ).fetchall()

        listing_rows = con.execute(
            """
            SELECT
                SUBSTR(created_at, 1, 10) AS day,
                COUNT(*) AS count
            FROM claims
            WHERE status = 'active'
              AND claim_type = 'listing'
              AND SUBSTR(created_at, 1, 10) >= ?
              AND SUBSTR(created_at, 1, 10) <= ?
            GROUP BY SUBSTR(created_at, 1, 10)
            ORDER BY day ASC
            """,
            (
                start_date.isoformat(),
                today.isoformat(),
            ),
        ).fetchall()

    models = [
        {
            "label": str(row["label"]),
            "count": int(row["count"] or 0),
        }
        for row in model_rows
    ]
    if len(models) > 10:
        other_count = sum(
            item["count"]
            for item in models[10:]
        )
        models = models[:10] + [
            {
                "label": "Other",
                "count": other_count,
            }
        ]

    year_counts = {}
    for row in year_rows:
        # Only a single year is chartable; do not extract a year from a range.
        label = re.sub(r"circa|c\.ha", "", str(row["label"]), flags=re.IGNORECASE).strip()
        if re.fullmatch(r"[0-9]{4}", label):
            year_counts[label] = year_counts.get(label, 0) + int(row["count"] or 0)
    years = [{"label": label, "count": year_counts[label]} for label in sorted(year_counts)]

    listing_map = {
        str(row["day"]): int(row["count"] or 0)
        for row in listing_rows
    }
    listings_30d = []
    for offset in range(30):
        day = start_date + timedelta(days=offset)
        key = day.isoformat()
        listings_30d.append(
            {
                "date": key,
                "count": listing_map.get(key, 0),
            }
        )

    return {
        "models": models,
        "years": years,
        "listings_30d": listings_30d,
    }


@app.get("/api/world-map")
def api_world_map() -> dict[str, Any]:
    repository = repo()
    with repository.connect() as con:
        rows = con.execute(
            """
            SELECT
                TRIM(location_country) AS country,
                COUNT(*) AS count
            FROM individuals
            WHERE location_country IS NOT NULL
              AND TRIM(location_country) <> ''
            GROUP BY TRIM(location_country)
            ORDER BY count DESC, country ASC
            """
        ).fetchall()

    return {
        "countries": [
            {
                "country": str(row["country"]),
                "count": int(row["count"] or 0),
            }
            for row in rows
        ]
    }


@app.get("/api/export-db")
def api_export_db() -> FileResponse:
    repository = repo()
    timestamp = datetime.now(
        timezone.utc
    ).strftime(
        "%Y%m%d_%H%M%S"
    )
    download_name = (
        f"ygc_backup_{timestamp}.zip"
    )

    temp_dir = Path(
        tempfile.mkdtemp(
            prefix="ygc_backup_",
        )
    )
    db_snapshot = (
        temp_dir
        / "chronicle.db"
    )
    archive_path = (
        temp_dir
        / "backup.zip"
    )

    try:
        with repository.connect() as source:
            with sqlite3.connect(
                db_snapshot
            ) as destination:
                source.backup(
                    destination
                )

        # Social data belongs to the independent account backup.
        if repository.account_db_path:
            with sqlite3.connect(db_snapshot) as snapshot:
                snapshot.execute('DELETE FROM user_follows')
                snapshot.execute('DELETE FROM direct_messages')

        media_files = (
            [
                path
                for path
                in MEDIA_DIR.rglob("*")
                if path.is_file() and (not repository.account_db_path or not path.is_relative_to(MEDIA_DIR / 'users'))
            ]
            if MEDIA_DIR.is_dir()
            else []
        )

        with zipfile.ZipFile(
            archive_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as archive:
            archive.write(
                db_snapshot,
                "chronicle.db",
            )

            for media_path in media_files:
                relative = (
                    media_path
                    .relative_to(
                        MEDIA_DIR
                    )
                )
                archive.write(
                    media_path,
                    (
                        Path("media")
                        / relative
                    ).as_posix(),
                )

            archive.writestr(
                "manifest.json",
                json.dumps(
                    _backup_manifest(
                        len(
                            media_files
                        )
                    ),
                    ensure_ascii=False,
                    indent=2,
                ),
            )

        return FileResponse(
            path=archive_path,
            filename=download_name,
            media_type="application/zip",
            background=BackgroundTask(
                shutil.rmtree,
                temp_dir,
                True,
            ),
        )
    except Exception:
        shutil.rmtree(
            temp_dir,
            ignore_errors=True,
        )
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
                    "Cannot import a backup "
                    "while a background job is running"
                ),
            )

    content_length = (
        request.headers.get(
            "content-length"
        )
    )

    max_size = (
        512
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
                        "Backup file is too large "
                        "(maximum 512 MB)"
                    ),
                )
        except ValueError:
            pass

    payload = await request.body()

    if not payload:
        raise HTTPException(
            status_code=400,
            detail=(
                "No backup file was uploaded"
            ),
        )

    if len(payload) > max_size:
        raise HTTPException(
            status_code=413,
            detail=(
                "Backup file is too large "
                "(maximum 512 MB)"
            ),
        )

    db_path = Path(
        config.DB_PATH
    )
    db_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    work_root = Path(
        tempfile.mkdtemp(
            prefix="ygc_import_",
            dir=db_path.parent,
        )
    )
    upload_path = (
        work_root
        / "upload.bin"
    )
    upload_path.write_bytes(
        payload
    )

    is_zip = zipfile.is_zipfile(
        upload_path
    )
    imported_media_count = 0
    legacy_database = not is_zip

    try:
        if is_zip:
            extract_root = (
                work_root
                / "extracted"
            )
            extract_root.mkdir(
                parents=True,
                exist_ok=True,
            )
            try:
                (
                    imported_db,
                    imported_media_root,
                    _manifest,
                ) = _validate_backup_archive(
                    upload_path,
                    extract_root,
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=str(exc),
                ) from exc
        else:
            imported_db = upload_path
            imported_media_root = (
                work_root
                / "empty_media"
            )
            imported_media_root.mkdir(
                parents=True,
                exist_ok=True,
            )

        try:
            imported_counts = (
                _validate_import_database(
                    imported_db
                )
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=str(exc),
            ) from exc

        if not legacy_database:
            try:
                imported_media_count = (
                    _validate_backup_media_references(
                        imported_db,
                        imported_media_root,
                    )
                )
            except (
                ValueError,
                sqlite3.Error,
            ) as exc:
                raise HTTPException(
                    status_code=400,
                    detail=str(exc),
                ) from exc

        rollback_db = (
            work_root
            / "rollback.db"
        )
        repository = repo()
        repository.init_db()
        with repository.connect() as source:
            with sqlite3.connect(
                rollback_db
            ) as destination:
                source.backup(
                    destination
                )

        rollback_media = (
            work_root
            / "rollback_media"
        )
        had_media = (
            MEDIA_DIR.is_dir()
        )
        if had_media:
            shutil.copytree(
                MEDIA_DIR,
                rollback_media,
            )

        try:
            with sqlite3.connect(
                imported_db
            ) as source:
                with sqlite3.connect(
                    db_path
                ) as destination:
                    source.backup(
                        destination
                    )
                    destination.execute(
                        "PRAGMA wal_checkpoint(TRUNCATE)"
                    )

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

            if MEDIA_DIR.exists():
                shutil.rmtree(
                    MEDIA_DIR
                )

            if (
                not legacy_database
                and imported_media_root.is_dir()
            ):
                shutil.copytree(
                    imported_media_root,
                    MEDIA_DIR,
                )
            else:
                MEDIA_DIR.mkdir(
                    parents=True,
                    exist_ok=True,
                )

            repository = repo()
            repository.init_db()

        except Exception as exc:
            try:
                with sqlite3.connect(
                    rollback_db
                ) as source:
                    with sqlite3.connect(
                        db_path
                    ) as destination:
                        source.backup(
                            destination
                        )

                if MEDIA_DIR.exists():
                    shutil.rmtree(
                        MEDIA_DIR
                    )

                if (
                    had_media
                    and rollback_media.is_dir()
                ):
                    shutil.copytree(
                        rollback_media,
                        MEDIA_DIR,
                    )
                else:
                    MEDIA_DIR.mkdir(
                        parents=True,
                        exist_ok=True,
                    )
            except Exception:
                pass

            if isinstance(
                exc,
                HTTPException,
            ):
                raise
            raise HTTPException(
                status_code=500,
                detail=(
                    "Could not install imported "
                    f"backup: {exc}"
                ),
            ) from exc

        return {
            "ok": True,
            "db_path": str(
                db_path
            ),
            "imported_counts": (
                imported_counts
            ),
            "imported_media_count": (
                imported_media_count
            ),
            "legacy_database": (
                legacy_database
            ),
            "stats": (
                repository.stats()
            ),
        }

    finally:
        shutil.rmtree(
            work_root,
            ignore_errors=True,
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

    if MEDIA_DIR.exists():
        try:
            shutil.rmtree(
                MEDIA_DIR
            )
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail=(
                    "Could not remove Media files: "
                    f"{exc}"
                ),
            ) from exc

    MEDIA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    repository = repo()
    repository.init_db()

    return {
        "ok": True,
        "db_path": str(
            config.DB_PATH
        ),
        "stats": repository.stats(),
    }


@app.get("/assets/no-picture.svg")
def no_picture_asset() -> Response:
    return Response(
        NO_PICTURE_SVG,
        media_type="image/svg+xml",
    )


@app.get("/assets/no-icon.svg")
def no_icon_asset() -> Response:
    return Response(
        NO_ICON_SVG,
        media_type="image/svg+xml",
    )


@app.get("/api/users/{user_id}/avatar")
def api_user_avatar(
    user_id: int, request: Request, viewer_id: int | None = None,
):
    viewer_id = prototype_viewer(request, viewer_id)
    repository = repo()
    user, _guitars = repository.get_user(
        user_id
    )
    if not user or user["ban_status"] == "ban":
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    if not repository.profile_field_visible(user, user_id, viewer_id, "avatar_visibility"):
        return Response(NO_ICON_SVG, media_type="image/svg+xml")

    raw_path = str(
        user["avatar_storage_path"]
        or ""
    ).strip()
    if raw_path:
        data_root = config.DATA_DIR.resolve()
        path = (
            config.DATA_DIR
            / raw_path
        ).resolve()
        if (
            path.is_relative_to(data_root)
            and path.is_file()
        ):
            return FileResponse(
                path,
                media_type=(
                    user["avatar_mime_type"]
                    or "application/octet-stream"
                ),
            )

    return Response(
        NO_ICON_SVG,
        media_type="image/svg+xml",
    )


@app.post("/api/users/{user_id}/avatar")
async def api_update_user_avatar(
    user_id: int,
    avatar: UploadFile = File(...),
) -> dict[str, Any]:
    repository = repo()
    user, _guitars = repository.get_user(
        user_id
    )
    if not user or user["ban_status"] == "ban":
        raise HTTPException(status_code=403, detail="Account is banned")

    content_type = (
        avatar.content_type
        or ""
    ).lower()
    extension = ALLOWED_IMAGE_TYPES.get(
        content_type
    )
    if not extension:
        raise HTTPException(
            status_code=400,
            detail=(
                "User image must be JPEG, PNG, "
                "WebP, or GIF"
            ),
        )

    image_bytes = await avatar.read(
        MAX_IMAGE_BYTES + 1
    )
    if not image_bytes:
        raise HTTPException(
            status_code=400,
            detail="User image is empty",
        )
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                "User image must be "
                "12 MB or smaller"
            ),
        )

    avatar_root = 'account_media' if repository.account_db_path else 'media'
    avatar_dir = config.DATA_DIR / avatar_root / "users"
    avatar_dir.mkdir(
        parents=True,
        exist_ok=True,
        mode=0o700,
    )
    stored_name = (
        uuid.uuid4().hex
        + extension
    )
    stored_path = (
        avatar_dir
        / stored_name
    )
    relative_storage_path = (
        Path(avatar_root)
        / "users"
        / stored_name
    ).as_posix()

    try:
        stored_path.write_bytes(
            image_bytes
        )
        stored_path.chmod(0o600)
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not save user image",
        ) from exc

    old_path = str(
        user["avatar_storage_path"]
        or ""
    ).strip()

    try:
        updated = repository.update_user_avatar(
            user_id,
            storage_path=(
                relative_storage_path
            ),
            original_filename=avatar.filename,
            mime_type=content_type,
        )
    except Exception:
        _safe_unlink(stored_path)
        raise

    if not updated:
        _safe_unlink(stored_path)
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    if old_path:
        old_file = (
            config.DATA_DIR
            / old_path
        ).resolve()
        media_root = MEDIA_DIR.resolve()
        if (
            old_file.is_relative_to(media_root)
            and old_file != stored_path.resolve()
        ):
            _safe_unlink(old_file)

    return {
        "ok": True,
        "avatar_url": (
            f"/api/users/{user_id}/avatar"
        ),
    }


@app.get("/api/individuals")
def api_individuals(request: Request) -> list[dict[str, Any]]:
    rows = repo().list_individuals()
    return [_row_dict(row) for row in rows
            if _console_admin_authorized(request) or row["claim_count"] > 0]


@app.get("/api/new-discoveries")
def api_new_discoveries(request: Request, viewer_id: int | None = None) -> list[dict[str, Any]]:
    viewer_id = prototype_viewer(request, viewer_id)
    repository = repo()
    with repository.connect() as con:
        rows = con.execute(
            f"""
            WITH sources AS ({MARKETPLACE_SOURCES_SQL}), visible_claims AS (
                SELECT c.* FROM claims c JOIN users u ON u.id=c.author_user_id
                WHERE c.status='active' AND u.ban_status='normal'
            ), source_activity AS (
                SELECT s.individual_id, MAX(s.observed_at) AS observed_at
                FROM sources s WHERE EXISTS (
                    SELECT 1 FROM visible_claims c WHERE c.individual_id=s.individual_id
                    AND (c.id=s.claim_id OR (s.claim_id IS NULL
                         AND c.observation_id=s.legacy_observation_id))
                ) GROUP BY s.individual_id
            )
            SELECT i.id,i.manufacturer,i.model,i.year,i.finish,i.serial_number,
                (SELECT c.id FROM visible_claims c WHERE c.individual_id=i.id
                 ORDER BY c.created_at DESC,c.id DESC LIMIT 1) AS latest_claim_id,
                (SELECT MAX(c.created_at) FROM visible_claims c
                 WHERE c.individual_id=i.id) AS latest_claim_at,
                (SELECT c.claim_type FROM visible_claims c WHERE c.individual_id=i.id
                 ORDER BY c.created_at DESC,c.id DESC LIMIT 1) AS latest_claim_type,
                s.observed_at AS latest_observation_at
            FROM individuals i LEFT JOIN source_activity s ON s.individual_id=i.id
            WHERE EXISTS (SELECT 1 FROM visible_claims c WHERE c.individual_id=i.id)
            ORDER BY MAX(
                COALESCE((SELECT MAX(c.created_at) FROM visible_claims c
                          WHERE c.individual_id=i.id),''),
                COALESCE(s.observed_at,'')
            ) DESC,i.id DESC LIMIT 200
            """
        ).fetchall()

    result: list[dict[str, Any]] = []
    for row in rows:
        item = _row_dict(row)
        claim_at = str(item.get("latest_claim_at") or "")
        observation_at = str(item.get("latest_observation_at") or "")
        if claim_at >= observation_at and claim_at:
            activity_at = claim_at
            activity_type = "claim"
            claim_type = item.get("latest_claim_type")
        else:
            activity_at = observation_at
            activity_type = "discovery"
            claim_type = None
        if not activity_at:
            continue
        item["activity_at"] = activity_at
        item["activity_type"] = activity_type
        item["claim_type"] = claim_type
        result.append(item)

    followed = repository.list_following_activity(viewer_id)
    # Describe a matching newest Claim once as the followed user's action.
    followed_claim_ids = {item["claim_id"] for item in followed if item["action_kind"] == "claim"}
    result = [item for item in result if not (
        item["activity_type"] == "claim" and item.get("latest_claim_id") in followed_claim_ids)]
    result.extend(followed)
    result.sort(key=lambda item: (str(item.get("activity_at") or ""),
                                int(item.get("action_id") or item.get("latest_claim_id") or 0),
                                int(item["id"]), str(item.get("action_kind") or "")), reverse=True)
    return result


@app.get("/api/individuals/{individual_id}")
def api_individual(individual_id: int, request: Request,
                   viewer_user_id: int | None = None) -> dict[str, Any]:
    viewer_user_id = prototype_viewer(request, viewer_user_id)
    repository = repo()
    individual, _ = repository.get_individual(
        individual_id, include_legacy_observations=False)
    if not individual:
        raise HTTPException(status_code=404, detail="Individual not found")
    admin = _console_admin_authorized(request)
    with repository.connect() as con:
        visible = con.execute("SELECT 1 FROM claims c JOIN users author ON author.id=c.author_user_id "
                              "WHERE c.individual_id=? AND c.status='active' AND "
                              "(author.ban_status='normal' OR "
                              "(author.ban_status='silent_ban' AND author.id=?)) LIMIT 1",
                              (individual_id, viewer_user_id)).fetchone()
        if not admin and not visible:
            raise HTTPException(status_code=404, detail="Individual not found")
    individual_data = _row_dict(individual)
    if viewer_user_id is not None:
        individual_data.update(repo().preview_silent_profile(viewer_user_id, individual_id))
    representative_media_id = (
        individual_data.get(
            "representative_media_asset_id"
        )
    )
    individual_data[
        "representative_image_url"
    ] = (
        f"/api/media/{representative_media_id}"
        if representative_media_id
        else None
    )

    if viewer_user_id is not None:
        with repository.connect() as con:
            pending=con.execute("SELECT a.revision,a.status,c.verification_status FROM acquire_applications a LEFT JOIN claims c ON c.id=a.claim_id WHERE a.individual_id=? AND a.applicant_id=? AND (a.status IN ('draft','pending','processing','error') OR (a.status='accepted' AND c.status='active' AND c.verification_status='unverified')) ORDER BY a.created_at DESC LIMIT 1",(individual_id,viewer_user_id)).fetchone()
            individual_data['acquire_application']=dict(pending) if pending else None
            from ygc import disputes
            case=disputes.active(con,individual_id)
            if case and viewer_user_id in disputes.participants(con,case):
                individual_data['ownership_dispute_id']=case['id']
    gallery_images = []
    for row in repo().list_media_assets(individual_id):
        item = _row_dict(row)
        media_id = int(item["id"])
        claim_type = str(item.get("claim_type") or "")
        gallery_images.append({
            "id": media_id,
            "url": f"/api/media/{media_id}",
            "label": (
                "Representative Image"
                if representative_media_id and media_id == int(representative_media_id)
                else ("Media Claim" if claim_type == "media" else "Uploaded Image")
            ),
            "caption": item.get("claim_caption") or "",
            "occurred_at": item.get("claim_occurred_at") or item.get("captured_at") or "",
            "is_representative": bool(
                representative_media_id and media_id == int(representative_media_id)
            ),
        })
    if representative_media_id and not any(img["id"] == representative_media_id for img in gallery_images):
        individual_data["representative_image_url"] = None
    gallery_images.sort(key=lambda item: (
        0 if item["is_representative"] else 1,
        str(item["occurred_at"]),
        int(item["id"]),
    ))

    visible_claims = [_row_dict(row) for row in repository.list_claims(
        individual_id, viewer_user_id=viewer_user_id)]
    listing_claims = [row for row in visible_claims
                      if row['claim_type'] == 'listing' and row['effective_status'] == 'active']
    current_listing = (
        listing_claims[-1]
        if listing_claims
        else None
    )
    image_sources = [row for row in visible_claims
                     if row['claim_type'] in ('listing', 'ownership')
                     and row['effective_status'] == 'active'
                     and row['verification_status'] == 'positive'
                     and row['image_url']]

    with repository.connect() as con:
        from ygc.acquire_review import visible
        acquire_evidence=[dict(revision=r['revision'],claim_id=r['claim_id']) for r in con.execute(
            "SELECT a.* FROM acquire_applications a JOIN claims c ON c.id=a.claim_id WHERE c.individual_id=? AND a.status='accepted'",(individual_id,))
            if visible(con,r,viewer_user_id,admin)]
    return {
        "individual": individual_data,
        "acquire_evidence": acquire_evidence,
        "current_listing": current_listing,
        "current_source": image_sources[-1] if image_sources else None,
        "gallery_images": gallery_images,
    }


@app.get("/api/individuals/{individual_id}/claims")
def api_individual_claims(
    individual_id: int, request: Request,
    viewer_user_id: int | None = None,
) -> list[dict[str, Any]]:
    viewer_user_id = prototype_viewer(request, viewer_user_id)
    repository = repo()
    claims = [
        {**_row_dict(row), "status": row["effective_status"]}
        for row
        in repository.list_claims(
            individual_id,
            viewer_user_id=viewer_user_id,
        )
        if row["effective_status"] == "active"
    ]
    verifiable_ids = repository.owner_verifiable_claim_ids(individual_id, viewer_user_id)
    transfers = repository.transfer_details(individual_id=individual_id)
    for claim in claims:
        claim['can_verify'] = int(claim['id']) in verifiable_ids
        if claim['ownership_source'] == 'user_transfer':
            claim['transfer'] = transfers.get(int(claim['id']))

    items_by_claim: dict[
        int,
        list[dict[str, Any]],
    ] = {}
    for row in repository.list_specification_items(
        individual_id
    ):
        item = _row_dict(
            row
        )
        items_by_claim.setdefault(
            int(
                item["claim_id"]
            ),
            [],
        ).append(
            item
        )

    identity_items_by_claim: dict[
        int,
        list[dict[str, Any]],
    ] = {}
    for row in repository.list_identity_correction_items(
        individual_id
    ):
        item = _row_dict(
            row
        )
        identity_items_by_claim.setdefault(
            int(
                item["claim_id"]
            ),
            [],
        ).append(
            item
        )

    media_images_by_claim: dict[
        int,
        list[dict[str, Any]],
    ] = {}
    for row in repository.list_claim_media_assets(
        individual_id
    ):
        item = _row_dict(row)
        claim_id = int(item["claim_id"])
        media_images_by_claim.setdefault(
            claim_id,
            [],
        ).append(
            {
                "id": int(item["id"]),
                "url": f"/api/media/{int(item['id'])}" + (f"?viewer_user_id={viewer_user_id}" if viewer_user_id is not None else ""),
                "original_filename": item.get("original_filename"),
            }
        )

    for claim in claims:
        claim["spec_items"] = (
            items_by_claim.get(
                int(
                    claim["id"]
                ),
                [],
            )
        )
        claim["identity_items"] = (
            identity_items_by_claim.get(
                int(
                    claim["id"]
                ),
                [],
            )
        )
        claim["media_images"] = (
            media_images_by_claim.get(
                int(claim["id"]),
                [],
            )
        )

    return claims


@app.post("/api/users/{user_id}/new-guitar")
def api_create_new_guitar(user_id: int):
    raise HTTPException(status_code=409,detail='新規登録にはListing画像審議が必要です。Listing申請から開始してください。')


@app.delete("/api/claims/{claim_id}")
def api_delete_claim(
    claim_id: int,
    request: Request,
) -> dict[str, Any]:
    _require_console_admin(request)
    repository = repo()
    try:
        result = repository.delete_claim(
            claim_id
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Claim not found",
        )
    return result


class ResolveRepeatedRequest(BaseModel):
    keep_id: int
    member_ids: list[int]
    action: str = Field(pattern="^(merge|delete)$")


@app.get("/api/admin/repeated")
def api_repeated(request: Request) -> dict:
    _require_console_admin(request)
    return repo().repeated_groups()


@app.get("/api/admin/individuals/{individual_id}/observation-diagnostic")
def api_observation_diagnostic(individual_id: int, request: Request) -> dict:
    _require_console_admin(request)
    try:
        return repo().observation_diagnostic(individual_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/admin/repeated/resolve")
def api_resolve_repeated(body: ResolveRepeatedRequest, request: Request) -> dict:
    _require_console_admin(request)
    try:
        return repo().resolve_repeated(body.keep_id, body.member_ids, body.action)
    except (ValueError, sqlite3.IntegrityError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


class AdminClaimRequest(BaseModel):
    action: str = Field(pattern="^(positive|negative|unverified|delete)$")
    confirm_individual_delete: bool = False


@app.post("/api/admin/claims/{claim_id}/moderate")
def api_admin_moderate_claim(claim_id: int, body: AdminClaimRequest, request: Request) -> dict:
    _require_console_admin(request)
    try:
        result = repo().admin_moderate_claim(
            claim_id, body.action, confirm_individual_delete=body.confirm_individual_delete)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    return result


@app.delete("/api/individuals/{individual_id}")
def api_delete_individual(
    individual_id: int,
    request: Request,
) -> dict[str, Any]:
    _require_console_admin(request)
    deleted = repo().delete_individual(
        individual_id
    )
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="Individual not found",
        )
    return {
        "deleted": True,
        "individual_id": individual_id,
    }


@app.get("/api/media/{media_asset_id}")
def api_media(
    media_asset_id: int, viewer_user_id: int | None = None,
) -> FileResponse:
    media = repo().get_media_asset(media_asset_id, viewer_user_id)
    if not media:
        raise HTTPException(
            status_code=404,
            detail="Media asset not found",
        )

    if str(media['storage_path']).startswith('review-listing/'):
        import base64
        from fastapi.responses import Response
        revision=str(media['storage_path']).split('/',1)[1]
        with repo().connect() as con:
            row=con.execute("SELECT a.images FROM acquire_applications a JOIN claim_evidence e ON e.claim_id=a.claim_id JOIN claims c ON c.id=a.claim_id WHERE a.revision=? AND a.request_kind='listing' AND a.status='accepted' AND e.media_asset_id=? AND c.status='active' AND c.verification_status='positive'",(revision,media_asset_id)).fetchone()
        if not row:raise HTTPException(status_code=404,detail='Listing image is not published')
        return Response(base64.b64decode(json.loads(row['images'])['overview']),media_type='image/jpeg',headers={'Cache-Control':'no-store'})

    data_root = config.DATA_DIR.resolve()
    path = (
        config.DATA_DIR
        / str(media["storage_path"])
    ).resolve()

    if not path.is_relative_to(
        data_root
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid media path",
        )
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Media file not found",
        )

    return FileResponse(
        path,
        media_type=(
            media["mime_type"]
            or "application/octet-stream"
        ),
    )


@app.post("/api/individuals/{individual_id}/media-claim")
async def api_media_claim(
    individual_id: int,
    user_id: int = Form(...),
    images: list[UploadFile] = File(...),
    occurred_at: str | None = Form(None),
    caption: str | None = Form(None),
) -> dict[str, Any]:
    try:occurred_at=validate_claim_date(occurred_at)
    except ValueError as exc:raise HTTPException(400,detail=str(exc)) from exc
    repository = repo()

    if not images:
        raise HTTPException(
            status_code=400,
            detail="At least one Media image is required",
        )
    if len(images) > 10:
        raise HTTPException(
            status_code=400,
            detail="A Media Claim can contain up to 10 images",
        )

    MEDIA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )
    stored_paths: list[Path] = []
    media_items: list[dict[str, str | None]] = []

    try:
        for image in images:
            content_type = (
                image.content_type
                or ""
            ).lower()
            extension = ALLOWED_IMAGE_TYPES.get(
                content_type
            )
            if not extension:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Media images must be JPEG, PNG, WebP, or GIF"
                    ),
                )

            image_bytes = await image.read(
                MAX_IMAGE_BYTES + 1
            )
            if not image_bytes:
                raise HTTPException(
                    status_code=400,
                    detail="Media image is empty",
                )
            if len(image_bytes) > MAX_IMAGE_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail="Each Media image must be 12 MB or smaller",
                )

            stored_name = uuid.uuid4().hex + extension
            stored_path = MEDIA_DIR / stored_name
            relative_storage_path = (
                Path("media")
                / stored_name
            ).as_posix()

            try:
                stored_path.write_bytes(
                    image_bytes
                )
            except OSError as exc:
                raise HTTPException(
                    status_code=500,
                    detail="Could not save Media image",
                ) from exc

            stored_paths.append(stored_path)
            media_items.append(
                {
                    "storage_path": relative_storage_path,
                    "original_filename": image.filename,
                    "mime_type": content_type,
                }
            )

        claim_id, media_asset_ids = (
            repository.create_media_claim_group(
                user_id,
                individual_id,
                media_items=media_items,
                occurred_at=occurred_at,
                caption=caption,
            )
        )
    except ValueError as exc:
        for path in stored_paths:
            _safe_unlink(path)
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except HTTPException:
        for path in stored_paths:
            _safe_unlink(path)
        raise
    except Exception:
        for path in stored_paths:
            _safe_unlink(path)
        raise

    repository.create_claim_notification(claim_id)
    return {
        "claim_id": claim_id,
        "media_asset_ids": media_asset_ids,
    }


@app.post("/api/individuals/{individual_id}/event-claim")
def api_event_claim(
    individual_id: int,
    request: EventClaimRequest,
) -> dict[str, Any]:
    repository = repo()
    try:
        claim_id = repository.create_event_claim(
            request.user_id,
            individual_id,
            event_kind=request.event_kind,
            occurred_at=request.occurred_at,
            detail=request.detail,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    repository.create_claim_notification(claim_id)
    return {"claim_id": claim_id}


@app.post("/api/individuals/{individual_id}/event-claim-with-media")
async def api_event_claim_with_media(
    individual_id: int,
    user_id: int = Form(...),
    event_kind: str = Form(...),
    occurred_at: str | None = Form(None),
    detail: str = Form(...),
    images: list[UploadFile] = File(...),
) -> dict[str, Any]:
    try:occurred_at=validate_claim_date(occurred_at)
    except ValueError as exc:raise HTTPException(400,detail=str(exc)) from exc
    if not images or len(images) > 10:
        raise HTTPException(status_code=400, detail="Select 1 to 10 images")
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    stored_paths: list[Path] = []
    media_items: list[dict[str, str | None]] = []
    try:
        for image in images:
            content_type = (image.content_type or "").lower()
            extension = ALLOWED_IMAGE_TYPES.get(content_type)
            if not extension:
                raise HTTPException(status_code=400, detail="Images must be JPEG, PNG, WebP, or GIF")
            image_bytes = await image.read(MAX_IMAGE_BYTES + 1)
            if not image_bytes:
                raise HTTPException(status_code=400, detail="Image is empty")
            if len(image_bytes) > MAX_IMAGE_BYTES:
                raise HTTPException(status_code=413, detail="Each image must be 12 MB or smaller")
            stored_name = uuid.uuid4().hex + extension
            stored_path = MEDIA_DIR / stored_name
            try:
                stored_path.write_bytes(image_bytes)
            except OSError as exc:
                raise HTTPException(status_code=500, detail="Could not save image") from exc
            stored_paths.append(stored_path)
            media_items.append({
                "storage_path": (Path("media") / stored_name).as_posix(),
                "original_filename": image.filename,
                "mime_type": content_type,
            })
        repository = repo()
        claim_id = repository.create_event_claim(
            user_id, individual_id, event_kind=event_kind,
            occurred_at=occurred_at, detail=detail, media_items=media_items,
        )
        repository.create_claim_notification(claim_id)
    except ValueError as exc:
        for path in stored_paths:
            _safe_unlink(path)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        for path in stored_paths:
            _safe_unlink(path)
        raise
    return {"claim_id": claim_id}


@app.post("/api/individuals/{individual_id}/incident-claim")
def api_incident_claim(
    individual_id: int,
    request: IncidentClaimRequest,
) -> dict[str, Any]:
    repository = repo()
    try:
        claim_id = repository.create_incident_claim(
            request.user_id,
            individual_id,
            incident_kind=request.incident_kind,
            occurred_at=request.occurred_at,
            detail=request.detail,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    repository.create_claim_notification(claim_id)
    return {"claim_id": claim_id}


@app.post("/api/individuals/{individual_id}/specification-claim")
def api_specification_claim(
    individual_id: int,
    request: SpecificationClaimRequest,
) -> dict[str, Any]:
    repository = repo()

    try:
        claim_id = (
            repository.create_specification_claim_group(
                request.user_id,
                individual_id,
                specification_kind=(
                    request.specification_kind
                ),
                items=[
                    {
                        "field_name": item.field_name,
                        "value_text": item.value_text,
                    }
                    for item in request.items
                ],
                occurred_at=request.occurred_at,
                body=request.body,
            )
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    repository.create_claim_notification(claim_id)
    return {
        "claim_id": claim_id,
    }


@app.patch("/api/claims/{claim_id}/specification")
def api_update_specification_claim(
    claim_id: int,
    request: SpecificationClaimRequest,
) -> dict[str, bool]:
    repository = repo()

    try:
        updated = (
            repository.update_specification_claim_group(
                claim_id,
                request.user_id,
                specification_kind=(
                    request.specification_kind
                ),
                items=[
                    {
                        "field_name": item.field_name,
                        "value_text": item.value_text,
                    }
                    for item in request.items
                ],
                occurred_at=request.occurred_at,
                body=request.body,
            )
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=403
            if "author" in str(exc).lower()
            else 400,
            detail=str(exc),
        ) from exc

    if not updated:
        raise HTTPException(
            status_code=404,
            detail="Specification Claim not found",
        )

    return {"ok": True}


@app.patch("/api/claims/{claim_id}")
def api_update_claim(
    claim_id: int,
    request: ClaimEditRequest,
) -> dict[str, bool]:
    repository = repo()

    try:
        updated = repository.update_claim(
            claim_id,
            request.user_id,
            occurred_at=request.occurred_at,
            body=request.body,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=403
            if "author" in str(exc).lower()
            else 400,
            detail=str(exc),
        ) from exc

    if not updated:
        raise HTTPException(
            status_code=404,
            detail="Claim not found",
        )

    return {"ok": True}


@app.post("/api/claims/{claim_id}/deactivate")
def api_deactivate_claim(
    claim_id: int,
    request: ClaimDeactivateRequest,
) -> dict[str, Any]:
    repository = repo()
    try:
        result = repository.deactivate_claim(
            claim_id,
            request.user_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=403
            if "author" in str(exc).lower()
            else 400,
            detail=str(exc),
        ) from exc

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Active Claim not found",
        )
    return result


@app.post("/api/claims/{listing_claim_id}/identity-correction")
def api_identity_correction(
    listing_claim_id: int,
    request: IdentityCorrectionRequest,
) -> dict[str, Any]:
    repository = repo()

    try:
        claim_id = repository.create_identity_correction(
            request.user_id,
            listing_claim_id,
            manufacturer=request.manufacturer,
            model=request.model,
            year=request.year,
            serial_number=request.serial_number,
            reason=request.reason,
        )
    except ValueError as exc:
        message = str(exc)
        raise HTTPException(
            status_code=409
            if "duplicate" in message.lower()
            else 400,
            detail=message,
        ) from exc

    return {
        "claim_id": claim_id,
    }


@app.get("/api/individuals/{individual_id}/current-specifications")
def api_current_specifications(
    individual_id: int,
) -> list[dict[str, Any]]:
    return [
        _row_dict(row)
        for row
        in repo().list_current_specifications(
            individual_id
        )
    ]


@app.post("/api/individuals/{individual_id}/ownership-claim")
def api_ownership_claim(
    individual_id: int,
    request: OwnershipClaimRequest,
) -> dict[str, Any]:
    if request.ownership_kind.strip().lower() == 'acquire':
        raise HTTPException(status_code=409, detail='Acquireは画像Evidenceを提出する申請入口から作成してください。')
    repository = repo()

    try:
        observation_id, claim_id = repository.create_ownership_claim(
            request.user_id,
            individual_id,
            ownership_kind=request.ownership_kind,
            occurred_at=request.occurred_at,
            previous_owner_text=request.previous_owner_text,
            body=request.body,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    user, guitars = repository.get_user(request.user_id)
    return {
        "claim_id": claim_id,
        "user": _row_dict(user),
        "guitars": [_row_dict(row) for row in guitars],
    }


@app.post("/api/individuals/{individual_id}/former-owner-claim")
def api_former_owner_claim(
    individual_id: int,
    request: FormerOwnerClaimRequest,
) -> dict[str, Any]:
    repository = repo()
    try:
        result = repository.create_former_owner_claims(
            request.user_id,
            individual_id,
            acquisition_date=request.acquisition_date,
            release_date=request.release_date,
            detail=request.detail,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    if result.get("claim_ids"):
        repository.create_claim_notification(
            int(result["claim_ids"][0])
        )
    user, guitars = repository.get_user(request.user_id)
    return {
        "claim_ids": result["claim_ids"],
        "snapshot": result["snapshot"],
        "user": _row_dict(user),
        "guitars": [_row_dict(row) for row in guitars],
    }



@app.post("/api/claims/{claim_id}/response")
def api_claim_response(
    claim_id: int,
    request: ClaimResponseRequest,
) -> dict[str, bool]:
    repository = repo()
    try:
        ok = repository.set_claim_response(
            claim_id,
            request.responder_user_id,
            request.stance,
            reason=request.reason,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    if not ok:
        raise HTTPException(
            status_code=404,
            detail="Claim or User not found",
        )

    repository.create_verification_notification(
        claim_id,
        request.responder_user_id,
        request.stance,
    )
    return {"ok": True}


@app.post("/api/claims/{claim_id}/vote")
def api_claim_vote(
    claim_id: int,
    request: ClaimVoteRequest,
) -> dict[str, bool]:
    repository = repo()
    try:
        ok = repository.set_claim_vote(
            claim_id,
            request.user_id,
            request.vote,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    if not ok:
        raise HTTPException(
            status_code=404,
            detail="Claim or User not found",
        )

    return {"ok": True}


class TransferProposalRequest(BaseModel):
    to_user_id: int = Field(ge=1)


class TransferActionRequest(BaseModel):
    action: str


def transfer_actor(request: Request, viewer_id: int | None) -> int:
    actor = prototype_viewer(request, viewer_id)
    if actor is None:
        raise HTTPException(status_code=401, detail="Sign in to use Transfer")
    return actor


def transfer_error(exc: ValueError):
    reason = str(exc)
    return HTTPException(status_code=403 if reason.startswith('Only ') else
                         404 if reason in ('Transfer not found','Individual not found','User not available for Transfer') else 409,
                         detail=reason)


@app.get("/api/ownership-requests/unanswered")
def api_unanswered_ownership_requests(request: Request, viewer_id: int | None = None):
    actor = transfer_actor(request, viewer_id)
    try:
        return JSONResponse(repo().unanswered_ownership_requests(actor), headers={"Cache-Control": "no-store"})
    except ValueError as exc:
        raise transfer_error(exc) from exc


@app.get("/api/transfer-users")
def api_transfer_users(request: Request, viewer_id: int | None = None, q: str = Query('', max_length=160),
                       offset: int = Query(0,ge=0), limit: int = Query(20,ge=1,le=50)):
    actor = transfer_actor(request, viewer_id)
    try:
        return repo().search_transfer_users(actor,q,limit,offset)
    except ValueError as exc:
        raise transfer_error(exc) from exc


@app.post("/api/individuals/{individual_id}/transfers")
def api_create_transfer(individual_id: int, body: TransferProposalRequest, request: Request, viewer_id: int | None = None):
    actor = transfer_actor(request, viewer_id)
    try:
        cid = repo().create_transfer(actor,individual_id,body.to_user_id)
        return {'claim_id':cid,'state':'pending'}
    except ValueError as exc:
        raise transfer_error(exc) from exc


@app.get("/api/transfers/{claim_id}")
def api_transfer_details(claim_id: int, request: Request, viewer_id: int | None = None):
    actor = transfer_actor(request, viewer_id)
    repository = repo()
    record = repository.transfer_details(claim_id)
    if record is None:
        raise HTTPException(404,detail='Transfer not found')
    if actor not in (record['from_user_id'],record['to_user_id']):
        raise HTTPException(403,detail='Only Transfer participants can open this request')
    try:
        with repository.connect() as con:
            repository._transfer_user(con,actor)
            claim = con.execute('SELECT c.individual_id,c.status,i.manufacturer,i.model,i.serial_number FROM claims c JOIN individuals i ON i.id=c.individual_id WHERE c.id=?',(claim_id,)).fetchone()
        return {**record,'individual_id':claim['individual_id'],'claim_active':claim['status']=='active',
                'guitar':{field:claim[field] for field in ('manufacturer','model','serial_number')}}
    except ValueError as exc:
        raise transfer_error(exc) from exc


@app.post("/api/transfers/{claim_id}/resolve")
def api_resolve_transfer(claim_id: int, body: TransferActionRequest, request: Request, viewer_id: int | None = None):
    actor = transfer_actor(request, viewer_id)
    try:
        return repo().resolve_transfer(claim_id,actor,body.action)
    except ValueError as exc:
        raise transfer_error(exc) from exc


class DirectMessageRequest(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class DirectMessageReadRequest(BaseModel):
    through_id: int = Field(ge=1)


def direct_message_actor(request: Request, viewer_id: int | None) -> int:
    actor_id = prototype_viewer(request, viewer_id)
    if actor_id is None:
        raise HTTPException(status_code=401, detail="Sign in to use messages")
    return actor_id


def direct_message_error(exc: ValueError):
    return HTTPException(status_code=404 if str(exc)=="User not found" else 400, detail=str(exc))


@app.get("/api/dm")
def api_dm_inbox(request: Request, viewer_id: int | None = None,
                 limit: int = Query(50, ge=1, le=100), before_id: int | None = Query(None, ge=1)):
    actor = direct_message_actor(request, viewer_id)
    try:
        return repo().direct_message_inbox(actor, limit, before_id)
    except ValueError as exc:
        raise direct_message_error(exc) from exc


@app.get("/api/dm/users/{peer_id}/messages")
def api_dm_history(peer_id: int, request: Request, viewer_id: int | None = None,
                   limit: int = Query(50, ge=1, le=100), before_id: int | None = Query(None, ge=1)):
    actor = direct_message_actor(request, viewer_id)
    try:
        return repo().direct_message_history(actor, peer_id, limit, before_id)
    except ValueError as exc:
        raise direct_message_error(exc) from exc


@app.post("/api/dm/users/{peer_id}/messages")
def api_dm_send(peer_id: int, body: DirectMessageRequest, request: Request, viewer_id: int | None = None):
    actor = direct_message_actor(request, viewer_id)
    try:
        return repo().send_direct_message(actor, peer_id, body.body)
    except ValueError as exc:
        raise direct_message_error(exc) from exc


@app.post("/api/dm/users/{peer_id}/read")
def api_dm_read(peer_id: int, body: DirectMessageReadRequest, request: Request, viewer_id: int | None = None):
    actor = direct_message_actor(request, viewer_id)
    try:
        return {"updated": repo().read_direct_messages(actor, peer_id, body.through_id)}
    except ValueError as exc:
        raise direct_message_error(exc) from exc


@app.get("/api/users/{user_id}/notifications")
def api_user_notifications(
    user_id: int,
) -> dict[str, Any]:
    repository = repo()
    user, _guitars = repository.get_user(user_id)
    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )
    return {
        "unread_count": repository.unread_notification_count(user_id),
        "notifications": [
            _row_dict(row)
            for row in repository.list_notifications(user_id)
        ],
    }


@app.post("/api/users/{user_id}/notifications/read-all")
def api_read_all_notifications(
    user_id: int,
) -> dict[str, int]:
    count = repo().mark_all_notifications_read(user_id)
    return {"updated": count}


@app.post("/api/users/{user_id}/notifications/{notification_id}/read")
def api_read_notification(
    user_id: int,
    notification_id: int,
) -> dict[str, bool]:
    if not repo().mark_notification_read(notification_id, user_id):
        raise HTTPException(
            status_code=404,
            detail="Notification not found",
        )
    return {"ok": True}


@app.get("/api/users")
def api_users(request: Request) -> list[dict[str, Any]]:
    admin = _console_admin_authorized(request)
    if os.getenv('YGC_IDENTITY_BACKEND', 'prototype') == 'local_dummy':
        repository = repo()
        with repository.connect() as con:
            disabled = {row['id']:bool(row['disabled']) for row in con.execute('SELECT id,disabled FROM account_records')}
        rows = repository.list_users()
        if not admin:
            return [{key: row[key] for key in ('id','display_name','account_type','theme')}
                    for row in rows if row['ban_status'] != 'ban' and not disabled[row['id']]]
        return [{**_row_dict(row), 'account_disabled':disabled[row['id']]} for row in rows]
    return [{**{key: value for key, value in _row_dict(row).items() if key != "date_of_birth" or admin},
             "ban_status": row["ban_status"] if admin else "normal"}
            for row in repo().list_users() if row["ban_status"] != "ban" or admin]


@app.post("/api/users")
def api_create_user() -> dict[str, Any]:
    repository = repo()
    user_id = repository.create_user()
    user, guitars = repository.get_user(
        user_id
    )

    return {
        "user": _row_dict(user),
        "guitars": [
            _row_dict(row)
            for row
            in guitars
        ],
    }


@app.patch("/api/admin/users/{user_id}")
def api_admin_update_user(user_id: int, body: AdminUserUpdateRequest, request: Request) -> dict:
    _require_console_admin(request)
    repository = repo()
    try:
        updated = repository.admin_update_user(user_id, body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    user, guitars = repository.get_user(user_id)
    return {"user": _row_dict(user), "guitars": [_row_dict(row) for row in guitars],
            "summary": repository.get_user_summary(user_id)}


@app.get("/api/users/{user_id}")
def api_user(
    user_id: int, request: Request,
) -> dict[str, Any]:
    user, guitars = repo().get_user(
        user_id
    )

    if not user or (user["ban_status"] == "ban" and not _console_admin_authorized(request)):
        raise HTTPException(status_code=404, detail="User not found")

    account_state = {}
    if _console_admin_authorized(request) and os.getenv('YGC_IDENTITY_BACKEND', 'prototype') == 'local_dummy':
        with repo().connect() as con:
            account_state = {'account_disabled':bool(con.execute('SELECT disabled FROM account_records WHERE id=?',(user_id,)).fetchone()[0])}
    return {
        "user": {**_row_dict(user), **account_state, "ban_status": user["ban_status"] if _console_admin_authorized(request) else "normal"},
        "guitars": [_row_dict(row) for row in guitars],
        "summary": repo().get_user_summary(user_id),
    }


@app.get("/api/users/{user_id}/profile")
def api_user_profile(user_id: int, request: Request, viewer_id: int | None = None) -> dict[str, Any]:
    viewer_id = prototype_viewer(request, viewer_id)
    repository = repo()
    user, guitars = repository.get_user(user_id)
    if not user or user["account_type"] == "source" or user["ban_status"] == "ban":
        raise HTTPException(status_code=404, detail="User not found")
    own = viewer_id == user_id
    if user["ban_status"] == 'silent_ban' and not own:
        guitars = []
    if own and user["ban_status"] == 'silent_ban':
        ownership = repository.preview_silent_profile(user_id)
        guitars = [{**_row_dict(g), "ownership_status": ownership.get(g["individual_id"], g["ownership_status"])}
                   for g in guitars]
    owned_ids = {int(g['individual_id']) for g in guitars}
    favorites = ([] if user['ban_status'] == 'silent_ban' and not own else
                 [_row_dict(g) for g in repository.get_user_favorites(user_id)
                  if int(g['individual_id']) not in owned_ids])
    def visible(setting: str) -> bool:
        return repository.profile_field_visible(user, user_id, viewer_id, setting)

    public_user = _row_dict(user)
    public_user["ban_status"] = "normal"
    if not visible("birth_visibility"):
        public_user["date_of_birth"] = None
    if not visible("residence_visibility"):
        public_user["location_country"] = None
        public_user["location_region"] = None
    if not visible("bio_visibility"):
        public_user["bio"] = None
    public_user["avatar_visible"] = visible("avatar_visibility")
    for field in ("avatar_storage_path", "avatar_original_filename", "avatar_mime_type"):
        public_user.pop(field, None)
    return {
        "user": public_user,
        "guitars": [_row_dict(row) for row in guitars],
        "favorites": favorites,
        "social": repository.user_social_summary(user_id, viewer_id),
        "summary": ({**repository.get_user_summary(user_id, viewer_id),
                     "owned_count": sum(g["ownership_status"] == 'current_owner' for g in guitars),
                     "former_count": sum(g["ownership_status"] == 'former_owner' for g in guitars)}
                    if user["ban_status"] == 'silent_ban'
                    else repository.get_user_summary(user_id, viewer_id)),
    }


@app.get("/api/users/{user_id}/connections/{direction}")
def api_user_connections(user_id: int, direction: str, limit: int = Query(50, ge=1, le=100),
                         offset: int = Query(0, ge=0)):
    try:
        return repo().list_user_connections(user_id, direction, limit, offset)
    except ValueError as exc:
        raise HTTPException(status_code=404 if str(exc) == "User not found" else 400, detail=str(exc)) from exc


@app.put("/api/users/{user_id}/following/{target_id}")
@app.delete("/api/users/{user_id}/following/{target_id}")
def api_set_user_follow(user_id: int, target_id: int, request: Request, viewer_id: int | None = None):
    actor_id = prototype_viewer(request, viewer_id)
    if actor_id is None:
        raise HTTPException(status_code=401, detail="Sign in to follow users")
    if actor_id != user_id:
        raise HTTPException(status_code=403, detail="You can only change your own follows")
    try:
        return {"following": repo().set_user_follow(actor_id, target_id, request.method == "PUT")}
    except ValueError as exc:
        raise HTTPException(status_code=404 if str(exc) == "User not found" else 400, detail=str(exc)) from exc


@app.get("/api/users/{user_id}/favorites")
def api_user_favorites(user_id: int) -> list[int]:
    user, _ = repo().get_user(user_id)
    if not user or user['account_type'] == 'source' or user['ban_status'] == 'ban':
        raise HTTPException(status_code=404, detail="User not found")
    return [int(row['individual_id']) for row in repo().get_user_favorites(user_id)]


@app.put("/api/users/{user_id}/favorites/{individual_id}")
def api_add_user_favorite(user_id: int, individual_id: int) -> dict[str, bool]:
    try:
        return {"favorite": repo().set_user_favorite(user_id, individual_id, True)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/users/{user_id}/favorites/{individual_id}")
def api_remove_user_favorite(user_id: int, individual_id: int) -> dict[str, bool]:
    try:
        return {"favorite": repo().set_user_favorite(user_id, individual_id, False)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/users/{user_id}/chronicle")
def api_user_chronicle(user_id: int, request: Request, viewer_id: int | None = None) -> list[dict[str, Any]]:
    viewer_id = prototype_viewer(request, viewer_id)
    repository = repo()
    user, _guitars = repository.get_user(user_id)
    if not user or user["account_type"] == "source" or user["ban_status"] == "ban":
        raise HTTPException(status_code=404, detail="User not found")
    return repository.list_user_chronicle(user_id, viewer_user_id=viewer_id)


@app.patch("/api/users/{user_id}")
def api_update_user(
    user_id: int,
    request: UserUpdateRequest,
) -> dict[str, Any]:
    repository = repo()
    existing, _ = repository.get_user(user_id)
    if existing and existing["ban_status"] == "ban":
        raise HTTPException(status_code=403, detail="Account is banned")

    try:
        updated = repository.update_user(
            user_id,
            display_name=(
                request.display_name
            ),
            account_type=(
                request.account_type
            ),
            location_country=(
                request.location_country
            ),
            location_region=(
                request.location_region
            ),
            bio=request.bio,
            date_of_birth=request.date_of_birth,
            update_date_of_birth="date_of_birth" in request.model_fields_set,
            visibility={
                name: value for name, value in {
                    "birth": request.birth_visibility,
                    "residence": request.residence_visibility,
                    "bio": request.bio_visibility,
                    "avatar": request.avatar_visibility,
                }.items() if value is not None
            },
            signature_individual_id=request.signature_individual_id,
            update_signature="signature_individual_id" in request.model_fields_set,
            theme=request.theme,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    if not updated:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    user, guitars = repository.get_user(
        user_id
    )

    return {
        "user": _row_dict(user),
        "guitars": [
            _row_dict(row)
            for row
            in guitars
        ],
    }


@app.post(
    "/api/users/{user_id}/guitars/{individual_id}"
)
def api_link_user_guitar(
    user_id: int,
    individual_id: int,
    request: UserGuitarLinkRequest,
) -> dict[str, Any]:
    if request.ownership_status == 'current_owner':
        individual,_=repo().get_individual(individual_id)
        if not individual or individual['current_owner_user_id'] != user_id:
            raise HTTPException(status_code=409,detail='現在の所有申請はAcquireの画像審議を利用してください。')
    repository = repo()

    try:
        linked = repository.link_user_guitar(
            user_id,
            individual_id,
            ownership_status=(
                request.ownership_status
            ),
            acquired_at=(
                request.acquired_at
            ),
            released_at=(
                request.released_at
            ),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    if not linked:
        raise HTTPException(
            status_code=404,
            detail=(
                "User or Individual not found"
            ),
        )

    user, guitars = repository.get_user(
        user_id
    )

    return {
        "user": _row_dict(user),
        "guitars": [
            _row_dict(row)
            for row
            in guitars
        ],
    }


@app.post("/api/users/{user_id}/guitar-order")
def api_reorder_user_guitars(
    user_id: int,
    request: UserGuitarOrderRequest,
) -> dict[str, Any]:
    repository = repo()

    reordered = repository.reorder_user_guitars(
        user_id,
        request.individual_ids,
    )

    if not reordered:
        raise HTTPException(
            status_code=400,
            detail=(
                "Owned guitar order does not match "
                "the user's current guitars"
            ),
        )

    user, guitars = repository.get_user(
        user_id
    )

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    return {
        "user": _row_dict(user),
        "guitars": [
            _row_dict(row)
            for row
            in guitars
        ],
    }


@app.delete(
    "/api/users/{user_id}/guitars/{individual_id}"
)
def api_unlink_user_guitar(
    user_id: int,
    individual_id: int,
) -> dict[str, Any]:
    repository = repo()
    removed = repository.unlink_user_guitar(
        user_id,
        individual_id,
    )

    if not removed:
        raise HTTPException(
            status_code=404,
            detail="Ownership link not found",
        )

    user, guitars = repository.get_user(
        user_id
    )

    return {
        "user": _row_dict(user),
        "guitars": [
            _row_dict(row)
            for row
            in guitars
        ],
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


@app.get("/api/claim-architecture-status")
def api_claim_architecture_status() -> dict[str, Any]:
    repository = repo()
    return repository.claim_architecture_status()


@app.post("/api/migrate-claims")
def api_migrate_claims() -> dict[str, Any]:
    repository = repo()
    before = repository.claim_architecture_status()
    result = repository.migrate_legacy_observations_to_claims()
    rebuild = repository.rebuild_all_individual_snapshots()
    after = repository.claim_architecture_status()
    return {
        "before": before,
        "migration": result,
        "rebuild": rebuild,
        "after": after,
    }


@app.post("/api/admin/backfill-cached-specifications")
def api_backfill_cached_specifications(request: Request) -> dict[str, int]:
    _require_console_admin(request)
    return repo().backfill_cached_specifications()


def _run_incremental(job_id: str, request: CrawlAdvanceRequest, token: str) -> None:
    global _active_job_id
    try:
        from ygc import crawl_backups
        crawl_backups.create(api_export_db)
        with ReverbAPICollector(
            token=token, api_base=config.REVERB_API_BASE,
            timeout=config.REQUEST_TIMEOUT, delay=0.5,
            max_workers=1,
        ) as collector:
            result = LocalCrawlRunner().run(
                CrawlStep(request.category, request.year_min, request.year_max),
                repo(), collector,
                progress_callback=lambda counts: _set_job(
                    job_id,
                    message={"listing": "Reviewing listings and fetching details",
                             "matching": "Matching candidates and registering guitars",
                             "availability": "Checking existing listing availability",
                             "done": "Processing complete", "error": "Processing failed"}.get(
                                 counts["phase"], counts["phase"]),
                    progress=min(0.95, counts["summaries_processed"] / 2000),
                    stage_counts=counts,
                ),
            )
        _set_job(job_id, status="done", message="This crawl run is complete",
                 progress=1.0, aggregate=result, finished_at=time.time())
    except Exception as exc:
        _set_job(job_id, status="error", message=str(exc), error=str(exc),
                 finished_at=time.time())
    finally:
        with _jobs_lock:
            if _active_job_id == job_id:
                _active_job_id = None


@app.get("/api/crawl/program")
def api_crawl_program(category: str, year_min: int, year_max: int) -> dict:
    if category not in ("electric", "acoustic", "electric_acoustic") or not 1800 <= year_min <= year_max <= 2100:
        raise HTTPException(status_code=400, detail="Invalid category or year range")
    return program_status(repo(), category, year_min, year_max)


@app.get("/api/crawl/program/runs")
def api_crawl_program_runs(category: str | None = None, year_min: int | None = None,
                           year_max: int | None = None) -> list[dict]:
    if category is None:
        return repo().crawl_run_log()
    if category not in ("electric", "acoustic", "electric_acoustic") or year_min is None or year_max is None or not 1800 <= year_min <= year_max <= 2100:
        raise HTTPException(status_code=400, detail="Invalid category or year range")
    return repo().crawl_run_log(category, year_min, year_max)


@app.get("/api/crawl/candidates/review")
def api_crawl_candidates_review() -> list[dict]:
    with repo().connect() as con:
        rows = con.execute(
            "SELECT source_listing_id, claim_json, reason FROM crawl_candidates "
            "WHERE source_site='reverb' AND status='review' ORDER BY updated_at DESC LIMIT 100"
        ).fetchall()
    return [{"listing_id": row["source_listing_id"],
             "manufacturer": json.loads(row["claim_json"]).get("manufacturer"),
             "model": json.loads(row["claim_json"]).get("model"),
             "serial_number": json.loads(row["claim_json"]).get("serial_number"),
             "reason": row["reason"]} for row in rows]


@app.post("/api/crawl/program/restart")
def api_crawl_program_restart(request: CrawlAdvanceRequest) -> dict:
    with _jobs_lock:
        if _active_job_id and _jobs.get(_active_job_id, {}).get("status") == "running":
            raise HTTPException(status_code=409, detail="A crawl job is already running")
        try:
            return restart_program(repo(), request.category,
                                   request.year_min, request.year_max)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/crawl/advance")
def api_crawl_advance(request: CrawlAdvanceRequest, http_request: Request) -> dict:
    global _active_job_id
    if request.category not in ("electric", "acoustic", "electric_acoustic") or request.year_min > request.year_max:
        raise HTTPException(status_code=400, detail="Invalid category or year range")
    token, _source = _request_token(http_request)
    if not token:
        raise HTTPException(status_code=400, detail="Reverb API Token is not configured")
    if not repo().claim_architecture_status()["ready"]:
        raise HTTPException(status_code=409, detail="Run Claim migration before crawling")
    with _jobs_lock:
        if _active_job_id and _jobs.get(_active_job_id, {}).get("status") == "running":
            raise HTTPException(status_code=409, detail="A crawl job is already running")
        job_id = uuid.uuid4().hex[:12]
        _jobs[job_id] = {"id": job_id, "status": "running",
                         "message": "Running incremental crawl", "progress": 0.0,
                         "query_results": [], "started_at": time.time()}
        _active_job_id = job_id
    threading.Thread(target=_run_incremental,
                     args=(job_id, request, token), daemon=True).start()
    return {"job_id": job_id}


def _run_cached_reprocess(job_id: str, request: CrawlAdvanceRequest) -> None:
    global _active_job_id
    repository = repo()
    run_id = repository.start_run("reverb")
    counts = {}
    def checkpoint(current, phase="matching"):
        counts.update(current)
        repository.update_crawl_run(run_id, phase, counts, "cache_reprocess", request.year_min, request.year_max)
    try:
        checkpoint({}, "backup")
        from ygc import crawl_backups
        crawl_backups.create(api_export_db)
        result = reprocess_details(
            repository, request.category, request.year_min, request.year_max,
            progress_callback=lambda current: (checkpoint(current), _set_job(
                job_id, message=f"Reprocessing saved details {current['cached_processed']}/{current['cached_total']}",
                progress=min(0.95, current["cached_processed"] / max(current["cached_total"], 1)),
                stage_counts=current,
            )),
        )
        checkpoint(result, "done")
        repository.finish_run(run_id, pages_discovered=result["cached_processed"],
                              observations_created=result["new_observations"], status="ok")
        _set_job(job_id, status="done", message="Saved details reprocessed",
                 progress=1.0, aggregate=result, finished_at=time.time())
    except Exception as exc:
        checkpoint({}, "error")
        repository.finish_run(run_id, status="error", error_message=str(exc))
        _set_job(job_id, status="error", error=str(exc), message=str(exc), finished_at=time.time())
    finally:
        with _jobs_lock:
            if _active_job_id == job_id:
                _active_job_id = None


@app.post("/api/crawl/cache/reprocess")
def api_reprocess_cached_details(request: CrawlAdvanceRequest) -> dict:
    global _active_job_id
    if request.category not in ("electric", "acoustic", "electric_acoustic") or request.year_min > request.year_max:
        raise HTTPException(status_code=400, detail="Invalid category or year range")
    if not repo().claim_architecture_status()["ready"]:
        raise HTTPException(status_code=409, detail="Run Claim migration before reprocessing")
    with _jobs_lock:
        if _active_job_id and _jobs.get(_active_job_id, {}).get("status") == "running":
            raise HTTPException(status_code=409, detail="A crawl job is already running")
        job_id = uuid.uuid4().hex[:12]
        _jobs[job_id] = {"id": job_id, "status": "running", "progress": 0.0,
                         "message": "Reprocessing saved details", "started_at": time.time()}
        _active_job_id = job_id
    threading.Thread(target=_run_cached_reprocess, args=(job_id, request), daemon=True).start()
    return {"job_id": job_id}


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

    architecture = repo().claim_architecture_status()
    if not architecture["ready"]:
        raise HTTPException(
            status_code=409,
            detail=(
                "Database is not ready for Claim-centered crawling. "
                "Run Claim migration and resolve any incomplete identities first."
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
            "message": "Starting",
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
                "Starting existing DB backfill"
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


INDEX_HTML = (Path(__file__).with_name("static") / "index_html.html").read_text(encoding="utf-8")





USER_VIEW_HTML = (Path(__file__).with_name("static") / "user_view_html.html").read_text(encoding="utf-8")


USER_EDIT_HTML = (Path(__file__).with_name("static") / "user_edit_html.html").read_text(encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Your Guitar Chronicle Phase 1 browser GUI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument('--identity-backend', choices=('local_dummy','prototype'),
                        default=os.getenv('YGC_IDENTITY_BACKEND','local_dummy'))
    args = parser.parse_args()
    os.environ['YGC_IDENTITY_BACKEND'] = args.identity_backend

    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://{args.host}:{args.port}")).start()

    uvicorn.run(app, host=args.host, port=args.port)




@app.middleware('http')
async def private_acquire_cache_control(request: Request, call_next):
    try:
        zone=ZoneInfo(request.headers.get('X-YGC-Timezone') or 'UTC')
    except (ZoneInfoNotFoundError, ValueError):
        return JSONResponse({'detail':'Invalid timezone.'}, status_code=400)
    token=viewer_timezone.set(zone)
    try:
        response=await call_next(request)
    finally:
        viewer_timezone.reset(token)
    if request.url.path.startswith(('/api/acquire-applications','/api/admin/acquire-applications','/api/listing-applications','/api/ownership-drafts','/api/ownership-dispute','/api/admin/ownership-dispute')):
        response.headers['Cache-Control']='private, no-store'
    return response


# Production Acquire applications. Images are never mounted as public media.
def acquire_actor(request: Request, viewer_id: int | None):
    actor=prototype_viewer(request,viewer_id)
    if actor is None: raise HTTPException(status_code=401,detail='Sign in to apply for Acquire')
    return actor


def acquire_error(exc):
    from ygc.acquire_review import ui_message
    return HTTPException(status_code=403 if isinstance(exc,PermissionError) else 409,detail=ui_message(str(exc)))


@app.post('/api/ownership-drafts/acquire/{individual_id}')
def api_preview_acquire(individual_id: int, request: Request, viewer_id: int | None = None):
    from ygc import acquire_review
    actor=acquire_actor(request,viewer_id)
    try:return acquire_review.start(repo(),actor,individual_id,preview=True)
    except (ValueError,PermissionError) as exc:raise acquire_error(exc) from exc


@app.post('/api/ownership-drafts/listing')
def api_preview_listing(request: Request, body: dict, viewer_id: int | None = None):
    from ygc import listing_review
    from pydantic import ValidationError
    actor=acquire_actor(request,viewer_id)
    try:return listing_review.start(repo(),actor,body,preview=True)
    except ValidationError as exc:raise HTTPException(status_code=422,detail='Check the Listing fields.') from exc
    except (ValueError,PermissionError) as exc:raise acquire_error(exc) from exc


class KeepOwnershipDraft(ClaimDateRequest):
    draft_token: str | None = Field(default=None,max_length=64000)
    revision: str | None = Field(default=None,max_length=64)
    acquisition_date: str = Field(default='',max_length=10)
    body: str = Field(default='',max_length=4000)


@app.post('/api/ownership-drafts/keep')
def api_keep_ownership_draft(request: Request, body: KeepOwnershipDraft, viewer_id: int | None = None):
    from ygc import request_drafts
    actor=acquire_actor(request,viewer_id)
    try:
        if bool(body.draft_token)==bool(body.revision):raise ValueError('Specify one request.')
        if body.acquisition_date:
            from datetime import date
            date.fromisoformat(body.acquisition_date)
        repository=repo()
        revision=request_drafts.keep(repository,actor,body.draft_token)['revision'] if body.draft_token else body.revision
        return request_drafts.save_inputs(repository,actor,revision,body.acquisition_date,body.body)
    except (ValueError,PermissionError) as exc:raise acquire_error(exc) from exc


@app.post('/api/ownership-drafts/submit')
async def api_submit_ownership_draft(request: Request, viewer_id: int | None = None,
    draft_token: str = Form(...), acquisition_date: str = Form(...), body: str = Form(''),
    closeup: UploadFile = File(...), overview: UploadFile = File(...)):
    from ygc import acquire_review as review, request_drafts
    from datetime import date
    actor=acquire_actor(request,viewer_id)
    try:
        validate_claim_date(acquisition_date)
        date.fromisoformat(acquisition_date)
        if len(body)>4000:raise ValueError('The description must be 4,000 characters or fewer.')
        contents=[]
        for upload in (closeup,overview):
            content=await upload.read(12*1024*1024+1)
            review.pack(content)  # Invalid photos must not create a saved request.
            contents.append(content)
        repository=repo()
        row=request_drafts.keep(repository,actor,draft_token)
        return await run_in_threadpool(review.submit,repository,actor,row['revision'],acquisition_date,body,*contents)
    except (ValueError,PermissionError) as exc:raise acquire_error(exc) from exc


@app.post('/api/listing-applications')
def api_start_listing(request: Request, body: dict, viewer_id: int | None = None):
    from pydantic import ValidationError
    from ygc import listing_review
    actor=acquire_actor(request,viewer_id)
    try:return listing_review.start(repo(),actor,body)
    except ValidationError as exc:raise HTTPException(status_code=422,detail='Check the Listing fields.') from exc
    except (ValueError,PermissionError) as exc:raise acquire_error(exc) from exc


@app.post('/api/individuals/{individual_id}/acquire-applications')
def api_start_acquire(individual_id: int, request: Request, viewer_id: int | None = None):
    from ygc import acquire_review as review
    actor=acquire_actor(request,viewer_id)
    try:return review.start(repo(),actor,individual_id)
    except (ValueError,PermissionError) as exc:raise acquire_error(exc) from exc


@app.get('/api/acquire-applications')
def api_my_acquires(request: Request, viewer_id: int | None = None):
    from ygc import acquire_review as review
    actor=acquire_actor(request,viewer_id)
    try:return review.list_for(repo(),actor)
    except (ValueError,PermissionError) as exc:raise acquire_error(exc) from exc


@app.get('/api/admin/acquire-applications')
def api_admin_acquires(request: Request):
    _require_console_admin(request)
    from ygc import acquire_review as review
    from ygc.listing_review import SCHEDULE_PROMPT
    return {'applications':review.list_for(repo(),None,admin=True),'prompt':SCHEDULE_PROMPT}


class AdminAcquireRequest(BaseModel):
    operation: str = Field(pattern='^(cancel|retry|accept|reject|positive|negative|unverified)$')
    reason: str = Field(min_length=1,max_length=2000)
    expected_version: str = Field(pattern='^[a-f0-9]{64}$')


@app.post('/api/admin/acquire-applications/{revision}/manage')
def api_manage_acquire(revision: str, body: AdminAcquireRequest, request: Request):
    _require_console_admin(request)
    from ygc import acquire_review as review
    try:return review.administer(repo(),revision,body.operation,body.reason,body.expected_version)
    except (ValueError,PermissionError) as exc:raise acquire_error(exc) from exc


@app.get('/api/acquire-applications/attention')
def api_acquire_attention(request: Request, viewer_id: int | None = None):
    from ygc import acquire_review as review
    actor=acquire_actor(request,viewer_id)
    try:return review.attention(repo(),actor)
    except (ValueError,PermissionError) as exc:raise acquire_error(exc) from exc


class AcquireSeenRequest(BaseModel):
    event_id: int = Field(ge=0)


@app.post('/api/acquire-applications/{revision}/seen')
def api_acquire_seen(revision: str, body: AcquireSeenRequest, request: Request, viewer_id: int | None = None):
    from ygc import acquire_review as review
    actor=acquire_actor(request,viewer_id)
    try:return review.mark_seen(repo(),actor,revision,body.event_id)
    except (ValueError,PermissionError) as exc:raise acquire_error(exc) from exc


@app.get('/api/acquire-applications/{revision}')
def api_acquire_detail(revision: str, request: Request, viewer_id: int | None = None):
    from ygc import acquire_review as review
    actor=prototype_viewer(request,viewer_id)
    try:
        with review.transaction(repo()) as con:
            review.expire(con)
            return review.detail(con,revision,actor,_console_admin_authorized(request))
    except (ValueError,PermissionError) as exc:raise acquire_error(exc) from exc


@app.get('/api/acquire-applications/{revision}/images/{role}')
def api_acquire_image(revision: str, role: str, request: Request, viewer_id: int | None = None):
    import base64
    from fastapi.responses import Response
    from ygc import acquire_review as review
    actor=prototype_viewer(request,viewer_id)
    try:
        with review.transaction(repo()) as con:
            review.detail(con,revision,actor,_console_admin_authorized(request))
            data=json.loads(review.find(con,revision)['images'] or '{}').get(role)
            if not data:raise ValueError('画像がありません。')
            return Response(base64.b64decode(data),media_type='image/jpeg',headers={'Cache-Control':'private, no-store'})
    except (ValueError,PermissionError) as exc:raise acquire_error(exc) from exc


@app.post('/api/acquire-applications/{revision}/submit')
async def api_submit_acquire(revision: str, request: Request, viewer_id: int | None = None,
    acquisition_date: str = Form(...), body: str = Form(''), closeup: UploadFile = File(...), overview: UploadFile = File(...)):
    from ygc import acquire_review as review
    actor=acquire_actor(request,viewer_id)
    contents=[]
    for upload in (closeup,overview):
        data=await upload.read(12*1024*1024+1)
        if len(data)>12*1024*1024:raise HTTPException(status_code=413,detail='画像は12MB以下です。')
        contents.append(data)
    try:return await run_in_threadpool(review.submit,repo(),actor,revision,acquisition_date,body,*contents)
    except (ValueError,PermissionError) as exc:raise acquire_error(exc) from exc


@app.post('/api/acquire-applications/{revision}/{operation}')
def api_acquire_action(revision: str, operation: str, request: Request, viewer_id: int | None = None):
    from ygc import acquire_review as review
    actor=prototype_viewer(request,viewer_id)
    try:return review.action(repo(),actor,revision,operation,_console_admin_authorized(request))
    except (ValueError,PermissionError) as exc:raise acquire_error(exc) from exc




from ygc.dispute_routes import router as dispute_router
app.include_router(dispute_router)

from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.exception_handlers import http_exception_handler


@app.exception_handler(StarletteHTTPException)
async def localized_http_error(request: Request, exc: StarletteHTTPException):
    from .localization import error_message_keys
    key = error_message_keys().get(exc.detail) if isinstance(exc.detail, str) else None
    if key and exc.status_code not in (204, 304) and exc.status_code >= 200:
        return JSONResponse({'detail': exc.detail, 'message_key': key},
                            status_code=exc.status_code, headers=exc.headers)
    return await http_exception_handler(request, exc)


@app.exception_handler(sqlite3.IntegrityError)
async def dispute_integrity_error(request: Request, exc: sqlite3.IntegrityError):
    if str(exc).startswith('Ownership dispute lock:'):
        return JSONResponse({'detail':str(exc)},status_code=409)
    return JSONResponse({'detail':'The operation conflicts with existing records.'},status_code=409)

@app.get('/assets/disputes.js')
def dispute_script():
    return FileResponse(Path(__file__).with_name('static')/'disputes.js',media_type='text/javascript',headers={'Cache-Control':'no-store'})



# Local operations: the console authentication boundary remains unchanged.
_OPERATIONS_STARTED = time.monotonic()

class OperationsSettingsRequest(BaseModel):
    mode: str = Field(pattern="^(normal|read_only|offline)$")
    message: str = Field(default="", max_length=1000)
    reason: str = Field(default="", max_length=2000)
    expected_version: int = Field(ge=0)


@app.get('/health/live')
def operations_live():
    return {'status': 'alive'}


@app.get('/health/ready')
def operations_ready():
    from ygc import operations
    try:
        with sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True, timeout=2) as con:
            con.execute('SELECT 1 FROM individuals LIMIT 1').fetchone()
        available = operations.state()['mode'] != 'offline'
    except (sqlite3.Error, OSError):
        available = False
    return JSONResponse({'status': 'ready' if available else 'unavailable'}, status_code=200 if available else 503)


@app.get('/api/admin/operations')
def operations_status(request: Request):
    _require_console_admin(request)
    from ygc import operations
    database = 'available'
    reviews = {}
    last_crawl = None
    last_gpt_answer = None
    try:
        with sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True, timeout=2) as con:
            con.execute('SELECT 1 FROM individuals LIMIT 1').fetchone()
            reviews = dict(con.execute('SELECT status,COUNT(*) FROM acquire_applications GROUP BY status'))
            last_gpt_answer = con.execute("SELECT MAX(at) FROM (SELECT at FROM acquire_application_events WHERE kind='chatgpt_answer_received' UNION ALL SELECT json_extract(result,'$.completed_at') AS at FROM acquire_applications WHERE json_valid(result))").fetchone()[0]
            last_crawl = con.execute("SELECT MAX(started_at) FROM crawl_runs WHERE source_site='reverb'").fetchone()[0]
    except (sqlite3.Error, OSError):
        database = 'unavailable'
    with _jobs_lock:
        jobs = [{k: j.get(k) for k in ('id','status','message','progress','started_at')} for j in list(_jobs.values())[-50:]]
    return {'settings': operations.state(), 'history': operations.history(),
            'checked_at': datetime.now(timezone.utc).isoformat(),
            'uptime_seconds': int(time.monotonic()-_OPERATIONS_STARTED),
            'database': database, 'media_directory': 'available' if MEDIA_DIR.is_dir() else 'not_created',
            'jobs': jobs, 'reviews': reviews, 'chatgpt_review':operations.chatgpt_review(), 'last_gpt_answer_at':max(filter(None,[last_gpt_answer,operations.last_paused_answer()]),default=None), 'auto_crawl':operations.auto_crawl(), 'last_crawl_at':last_crawl, 'auto_crawl_message':_AUTO_CRAWL_MESSAGE, 'version': '0.2.0', 'deployment': 'local prototype'}


@app.put('/api/admin/operations')
def operations_save(body: OperationsSettingsRequest, request: Request):
    _require_console_admin(request)
    from ygc import operations
    try:
        return operations.update(body.mode, body.message.strip(), body.reason.strip() or 'Service mode set to '+body.mode, body.expected_version)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.middleware('http')
async def operations_maintenance(request: Request, call_next):
    path = request.url.path
    # Keep the authenticated settings endpoint reachable to recover from maintenance.
    exempt = path.startswith(('/health/', '/assets/')) or path.startswith('/api/admin/operations') or path in ('/', '/api/service-notice')
    if not exempt:
        from ygc import operations
        try:
            settings = await run_in_threadpool(operations.state)
        except (sqlite3.Error, OSError):
            return JSONResponse({'detail': 'Operations settings unavailable'}, status_code=503, headers={'Retry-After':'60','Cache-Control':'no-store'})
        blocked = settings['mode'] == 'offline' or (settings['mode'] == 'read_only' and request.method not in ('GET','HEAD','OPTIONS'))
        if blocked:
            message = settings['message'] or 'The service is undergoing maintenance. Please try again later.'
            if path.startswith('/api/'):
                response = JSONResponse({'detail':message}, status_code=503)
            else:
                import html
                response = HTMLResponse('<!doctype html><html lang="en"><meta name="viewport" content="width=device-width"><title>Maintenance</title><h1>Maintenance</h1><p>'+html.escape(message)+'</p></html>', status_code=503)
            response.headers.update({'Retry-After':'60','Cache-Control':'no-store'})
            return response
    response = await call_next(request)
    if path == '/api/admin/operations' or path.startswith('/health/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/api/service-notice')
def api_service_notice():
    from ygc import operations
    state = operations.state()
    return JSONResponse({'mode':state['mode'], 'message':state['message'], 'version':state['version']}, headers={'Cache-Control':'no-store'})


@app.get('/api/important-information')
def api_important_information(request: Request, viewer_id: int | None = None):
    from ygc import important_information
    actor = acquire_actor(request, viewer_id)
    try:
        result = important_information.for_user(repo(), actor)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return JSONResponse(result, headers={'Cache-Control':'private, no-store'})


@app.get("/assets/table-columns.js")
def table_columns_asset():
    return FileResponse(Path(__file__).with_name("static") / "table-columns.js", media_type="text/javascript", headers={"Cache-Control":"no-store"})


_AUTO_CRAWL_TOKEN = ''
_AUTO_CRAWL_MESSAGE = ''

class AutoCrawlRequest(BaseModel):
    enabled: bool
    category: str = Field(pattern='^(electric|acoustic|electric_acoustic)$')
    year_min: int = Field(ge=1800,le=2100)
    year_max: int = Field(ge=1800,le=2100)
    interval_seconds: int = Field(default=3600,ge=60,le=604800)

@app.put('/api/admin/operations/auto-crawl')
def operations_auto_crawl(body: AutoCrawlRequest, request: Request):
    global _AUTO_CRAWL_TOKEN, _AUTO_CRAWL_MESSAGE
    _require_console_admin(request)
    from ygc import operations
    if body.year_min>body.year_max:
        raise HTTPException(422,'Invalid year range')
    token,_ = _request_token(request)
    if body.enabled and not token:
        raise HTTPException(400,'Reverb API Token is not configured')
    if body.enabled:
        _AUTO_CRAWL_TOKEN=token
    _AUTO_CRAWL_MESSAGE=''
    return operations.set_auto_crawl(body.enabled,body.category,body.year_min,body.year_max,body.interval_seconds)


def _auto_crawl_tick():
    global _active_job_id, _AUTO_CRAWL_MESSAGE
    from ygc import operations
    settings=operations.auto_crawl()
    if settings['category'] not in ('electric','acoustic','electric_acoustic'):
        _AUTO_CRAWL_MESSAGE='Paused: save the Electric + Acoustic Guitars Auto Crawl settings.'
        return
    if not settings['enabled'] or operations.state()['mode']!='normal':return
    token=_AUTO_CRAWL_TOKEN or config.REVERB_API_TOKEN
    if not token:
        _AUTO_CRAWL_MESSAGE='Paused: configure the server Reverb token or enable Auto Crawl again.'
        return
    if not repo().claim_architecture_status()['ready']:
        _AUTO_CRAWL_MESSAGE='Paused: Claim migration is required.'
        return
    with _jobs_lock:
        if _active_job_id and _jobs.get(_active_job_id,{}).get('status')=='running':return
        if not operations.reserve_auto_crawl(time.time()):return
        job_id=uuid.uuid4().hex[:12]
        _jobs[job_id]={'id':job_id,'status':'running','message':'Auto Crawl: Reverb','progress':0.0,'started_at':time.time(),'query_results':[]}
        _active_job_id=job_id
    _AUTO_CRAWL_MESSAGE=''
    request=CrawlAdvanceRequest(category=settings['category'],year_min=settings['year_min'],year_max=settings['year_max'])
    threading.Thread(target=_run_incremental,args=(job_id,request,token),daemon=True).start()


def _auto_crawl_loop(stop):
    while not stop.wait(5):
        try:
            _auto_crawl_tick()
        except Exception:
            global _AUTO_CRAWL_MESSAGE
            _AUTO_CRAWL_MESSAGE='Auto Crawl could not start. Check database and service settings.'


class ChatGPTReviewRequest(BaseModel):
    enabled: bool

@app.put('/api/admin/operations/chatgpt-review')
def operations_chatgpt_review(body: ChatGPTReviewRequest, request: Request):
    _require_console_admin(request)
    from ygc import operations
    return operations.chatgpt_review(body.enabled)


class BackupRetentionRequest(BaseModel):
    target: str = Field(default='chronicle', pattern='^(chronicle|operations|authentication|accounts)$')
    generations: int = Field(ge=1, le=100)
    enabled: bool | None = None
    interval_hours: int | None = Field(default=None, ge=1, le=168)

class BackupSaveRequest(BaseModel):
    target: str = Field(default='chronicle', pattern='^(chronicle|operations|authentication|accounts)$')

@app.get('/api/admin/operations/backups')
def saved_crawl_backups(request: Request):
    _require_console_admin(request)
    from ygc import crawl_backups
    return {'generations': crawl_backups.retention(), 'policies': crawl_backups.policies(), 'backups': crawl_backups.listing()}

@app.put('/api/admin/operations/backups')
def save_crawl_backup_retention(body: BackupRetentionRequest, request: Request):
    _require_console_admin(request)
    from ygc import crawl_backups
    policy = crawl_backups.configure(body.target, generations=body.generations, enabled=body.enabled, interval_hours=body.interval_hours)
    return {'generations': policy['generations'], 'policy': policy}

@app.post('/api/admin/operations/backups/save')
def save_manual_backup(body: BackupSaveRequest, request: Request):
    _require_console_admin(request)
    from ygc import crawl_backups
    if not _CRAWL_RESTORE_LOCK.acquire(blocking=False):
        raise HTTPException(409, 'A backup or restore is already running.')
    try:
        with _jobs_lock:
            if any(j.get('status') == 'running' for j in _jobs.values()):
                raise HTTPException(409, 'Wait for background jobs to finish before saving a backup.')
        return {'name': crawl_backups.create(api_export_db, body.target, 'manual')}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        _CRAWL_RESTORE_LOCK.release()

@app.get('/api/admin/operations/backups/{name}/download')
def download_saved_backup(name: str, request: Request):
    _require_console_admin(request)
    from ygc import crawl_backups
    try:
        path = crawl_backups.selected(name)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    folder = Path(tempfile.mkdtemp(prefix='ygc_backup_download_'))
    try:
        with crawl_backups._lock:
            shutil.copyfile(path, folder / name)
        return FileResponse(folder / name, filename=name, media_type='application/zip',
                            headers={'Cache-Control':'private, no-store'},
                            background=BackgroundTask(shutil.rmtree, folder, True))
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise


def _require_restore_ready():
    from ygc import operations
    if operations.state()['mode'] == 'normal':
        raise HTTPException(409, 'Enable read-only or offline maintenance before restoring a backup.')
    with _jobs_lock:
        if any(job.get('status') == 'running' for job in _jobs.values()):
            raise HTTPException(409, 'Wait for background jobs to finish before restoring.')

def _record_backup_restore(target):
    from ygc import operations
    con = operations.connect()
    try:
        with con:
            mode = con.execute('SELECT mode FROM settings WHERE id=1').fetchone()[0]
            con.execute('INSERT INTO events(occurred_at,mode,reason) VALUES (?,?,?)',
                        (datetime.now(timezone.utc).isoformat(), mode, 'Backup restored: ' + target))
    finally:
        con.close()

async def _restore_backup_payload(payload: bytes, target: str):
    from ygc import crawl_backups, direct_experiment
    _require_restore_ready()
    if len(payload) > crawl_backups.MAX_BYTES:
        raise HTTPException(413, 'Backup exceeds 512 MB.')
    if target not in crawl_backups.TARGETS:
        raise HTTPException(400, 'Invalid backup target.')
    # Both targets and reasons are explicit; rotation applies only to this target.
    try:
        if crawl_backups.database_path(target).is_file():
            await run_in_threadpool(crawl_backups.create, api_export_db, target, 'before_restore')
        if target != 'chronicle':
            def restore_aux():
                with direct_experiment.LOCK, crawl_backups._lock:
                    crawl_backups.restore_auxiliary(payload, target)
            await run_in_threadpool(restore_aux)
            _record_backup_restore(target)
            return {'restored': True, 'target': target}
        delivered = False
        async def receive():
            nonlocal delivered
            if delivered:
                return {'type': 'http.disconnect'}
            delivered = True
            return {'type': 'http.request', 'body': payload, 'more_body': False}
        upload = Request({'type':'http', 'method':'POST', 'path':'/api/import-db', 'headers':[(b'content-length', str(len(payload)).encode())]}, receive)
        result = await api_import_db(upload)
        _record_backup_restore(target)
        return {**result, 'target': target}
    except (ValueError, sqlite3.Error, zipfile.BadZipFile) as exc:
        raise HTTPException(400, str(exc)) from exc

async def _restore_saved_crawl_backup(name: str, request: Request):
    _require_console_admin(request)
    from ygc import crawl_backups
    _require_restore_ready()
    try:
        path = crawl_backups.selected(name)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    if path.stat().st_size > crawl_backups.MAX_BYTES:
        raise HTTPException(413, 'Backup exceeds 512 MB.')
    payload = await run_in_threadpool(path.read_bytes)
    return await _restore_backup_payload(payload, crawl_backups.metadata(path)['target'])

_CRAWL_RESTORE_LOCK = threading.Lock()

@app.post('/api/admin/operations/backups/import')
async def restore_uploaded_backup(request: Request, target: str = 'chronicle'):
    _require_console_admin(request)
    _require_restore_ready()
    if not _CRAWL_RESTORE_LOCK.acquire(blocking=False):
        raise HTTPException(409, 'A backup or restore is already running.')
    try:
        from ygc import crawl_backups
        payload = bytearray()
        async for chunk in request.stream():
            payload.extend(chunk)
            if len(payload) > crawl_backups.MAX_BYTES:
                raise HTTPException(413, 'Backup exceeds 512 MB.')
        return await _restore_backup_payload(bytes(payload), target)
    finally:
        _CRAWL_RESTORE_LOCK.release()

@app.post('/api/admin/operations/backups/{name}/restore')
async def restore_saved_crawl_backup(name: str, request: Request):
    _require_console_admin(request)
    if not _CRAWL_RESTORE_LOCK.acquire(blocking=False):
        raise HTTPException(409, 'A backup or restore is already running.')
    try:
        return await _restore_saved_crawl_backup(name, request)
    finally:
        _CRAWL_RESTORE_LOCK.release()


def _backup_tick():
    if not _CRAWL_RESTORE_LOCK.acquire(blocking=False):
        return
    try:
        with _jobs_lock:
            if any(j.get('status') == 'running' for j in _jobs.values()):
                return
        from ygc import crawl_backups
        crawl_backups.scheduled_tick(api_export_db)
    finally:
        _CRAWL_RESTORE_LOCK.release()


def _backup_loop(stop):
    while not stop.wait(10):
        try:
            _backup_tick()
        except Exception:
            # Per-target failures are recorded by create; retry on the next tick.
            pass

from ygc.local_identity import install as install_local_identity
install_local_identity(app, repo, _local_console_request, _console_admin_authorized)

@app.get('/assets/important-information.js')
def important_information_script():
    return FileResponse(Path(__file__).with_name('static') / 'important-information.js', media_type='text/javascript', headers={'Cache-Control':'no-store'})


@app.get('/assets/local-auth.js')
def local_auth_script():
    return FileResponse(Path(__file__).with_name('static') / 'local-auth.js', media_type='text/javascript', headers={'Cache-Control':'no-store'})

if __name__ == '__main__':
    main()
