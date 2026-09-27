from __future__ import annotations

import argparse
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
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from ygc import config
from ygc.collectors.reverb import ReverbAPICollector
from ygc.crawl_service import crawl_query
from ygc.db.repository import Repository
from ygc.extractors.serial import extract_serial_candidates
from ygc.reverb_adapter import (
    classify_vintage_listing,
    to_listing_claim_data,
    to_provenance_observation,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Repository(config.DB_PATH).init_db()
    yield


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
    repository = Repository(config.DB_PATH)
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


class UserGuitarLinkRequest(BaseModel):
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


class SpecificationClaimRequest(BaseModel):
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


class EventClaimRequest(BaseModel):
    user_id: int = Field(ge=1)
    event_kind: str = Field(max_length=30)
    occurred_at: str | None = Field(default=None, max_length=40)
    detail: str = Field(min_length=1, max_length=2000)


class IncidentClaimRequest(BaseModel):
    user_id: int = Field(ge=1)
    incident_kind: str = Field(max_length=20)
    occurred_at: str | None = Field(default=None, max_length=40)
    detail: str = Field(min_length=1, max_length=2000)


class OwnershipClaimRequest(BaseModel):
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


class FormerOwnerClaimRequest(BaseModel):
    user_id: int = Field(ge=1)
    acquisition_date: str = Field(min_length=10, max_length=10)
    release_date: str = Field(min_length=10, max_length=10)
    detail: str | None = Field(
        default=None,
        max_length=2000,
    )



class ClaimResponseRequest(BaseModel):
    responder_user_id: int = Field(ge=1)
    stance: str = Field(max_length=20)


class ClaimVoteRequest(BaseModel):
    user_id: int = Field(ge=1)
    vote: str = Field(max_length=10)


class ClaimEditRequest(BaseModel):
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
        .list_listing_claims_for_backfill()
    )
    total = len(rows)

    try:
        if total == 0:
            _set_job(
                job_id,
                status="done",
                message=(
                    "バックフィル対象はありません"
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

                    _set_job(
                        job_id,
                        message=(
                            "Listing Claimをバックフィル中 "
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

        _set_job(
            job_id,
            status="done",
            message=(
                "Listing Claimバックフィル完了"
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
def index() -> HTMLResponse:
    return HTMLResponse(INDEX_HTML)


@app.get("/user-view", response_class=HTMLResponse)
def user_view() -> HTMLResponse:
    return HTMLResponse(USER_VIEW_HTML)


@app.get("/user-view/edit", response_class=HTMLResponse)
def user_edit() -> HTMLResponse:
    return HTMLResponse(USER_EDIT_HTML)


@app.get("/users/{user_id}", response_class=HTMLResponse)
def user_profile(
    user_id: int,
) -> HTMLResponse:
    return HTMLResponse(USER_PROFILE_HTML)


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

    years = [
        {
            "label": str(row["label"]),
            "count": int(row["count"] or 0),
        }
        for row in year_rows
    ]

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

        media_files = (
            [
                path
                for path
                in MEDIA_DIR.rglob("*")
                if path.is_file()
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
        repository = Repository(
            db_path
        )
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

            repository = Repository(
                db_path
            )
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
    user_id: int,
):
    repository = repo()
    user, _guitars = repository.get_user(
        user_id
    )
    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

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
    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

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

    avatar_dir = MEDIA_DIR / "users"
    avatar_dir.mkdir(
        parents=True,
        exist_ok=True,
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
        Path("media")
        / "users"
        / stored_name
    ).as_posix()

    try:
        stored_path.write_bytes(
            image_bytes
        )
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
def api_individuals() -> list[dict[str, Any]]:
    return [_row_dict(row) for row in repo().list_individuals()]


@app.get("/api/new-discoveries")
def api_new_discoveries() -> list[dict[str, Any]]:
    repository = repo()
    with repository.connect() as con:
        rows = con.execute(
            """
            SELECT
                i.id,
                i.manufacturer,
                i.model,
                i.year,
                i.finish,
                i.serial_number,
                (
                    SELECT MAX(c.created_at)
                    FROM claims c
                    WHERE c.individual_id = i.id
                      AND c.status = 'active'
                ) AS latest_claim_at,
                (
                    SELECT c2.claim_type
                    FROM claims c2
                    WHERE c2.individual_id = i.id
                      AND c2.status = 'active'
                    ORDER BY c2.created_at DESC, c2.id DESC
                    LIMIT 1
                ) AS latest_claim_type,
                (
                    SELECT MAX(o.observed_at)
                    FROM observations o
                    WHERE o.individual_id = i.id
                ) AS latest_observation_at
            FROM individuals i
            ORDER BY MAX(
                COALESCE((SELECT MAX(c.created_at) FROM claims c
                          WHERE c.individual_id = i.id AND c.status = 'active'), ''),
                COALESCE((SELECT MAX(o.observed_at) FROM observations o
                          WHERE o.individual_id = i.id), '')
            ) DESC, i.id DESC
            LIMIT 24
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

    result.sort(
        key=lambda item: (
            str(item.get("activity_at") or ""),
            int(item.get("id") or 0),
        ),
        reverse=True,
    )
    return result


@app.get("/api/individuals/{individual_id}")
def api_individual(individual_id: int) -> dict[str, Any]:
    individual, observations = repo().get_individual(individual_id)
    if not individual:
        raise HTTPException(status_code=404, detail="Individual not found")
    individual_data = _row_dict(
        individual
    )
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
    gallery_images.sort(key=lambda item: (
        0 if item["is_representative"] else 1,
        str(item["occurred_at"]),
        int(item["id"]),
    ))

    listing_claims = [
        _row_dict(row)
        for row
        in repo().list_claims(
            individual_id
        )
        if row["claim_type"] == "listing"
        and row["status"] == "active"
    ]
    current_listing = (
        listing_claims[-1]
        if listing_claims
        else None
    )

    return {
        "individual": individual_data,
        "observations": [_row_dict(row) for row in observations],
        "current_listing": current_listing,
        "gallery_images": gallery_images,
    }


@app.get("/api/individuals/{individual_id}/claims")
def api_individual_claims(
    individual_id: int,
    viewer_user_id: int | None = None,
) -> list[dict[str, Any]]:
    repository = repo()
    claims = [
        _row_dict(row)
        for row
        in repository.list_claims(
            individual_id,
            viewer_user_id=viewer_user_id,
        )
        if row["status"] == "active"
    ]

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
                "url": f"/api/media/{int(item['id'])}",
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
async def api_create_new_guitar(
    user_id: int,
    manufacturer: str = Form(...),
    serial_number: str = Form(...),
    representative_image: UploadFile = File(...),
    model: str | None = Form(None),
    finish: str | None = Form(None),
    year: str | None = Form(None),
    occurred_at: str | None = Form(None),
    body: str | None = Form(None),
) -> dict[str, Any]:
    repository = repo()

    content_type = (
        representative_image.content_type
        or ""
    ).lower()
    extension = ALLOWED_IMAGE_TYPES.get(
        content_type
    )
    if not extension:
        raise HTTPException(
            status_code=400,
            detail=(
                "Representative image must be "
                "JPEG, PNG, WebP, or GIF"
            ),
        )

    image_bytes = await representative_image.read(
        MAX_IMAGE_BYTES + 1
    )
    if not image_bytes:
        raise HTTPException(
            status_code=400,
            detail="Representative image is empty",
        )
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                "Representative image must be "
                "12 MB or smaller"
            ),
        )

    MEDIA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )
    stored_name = (
        uuid.uuid4().hex
        + extension
    )
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
            detail=(
                "Could not save representative image"
            ),
        ) from exc

    try:
        (
            individual_id,
            observation_id,
            claim_id,
            media_asset_id,
        ) = repository.create_initial_listing_claim(
            user_id,
            manufacturer=manufacturer,
            model=model,
            finish=finish,
            year=year,
            serial_number=serial_number,
            occurred_at=occurred_at,
            body=body,
            media_storage_path=(
                relative_storage_path
            ),
            media_original_filename=(
                representative_image.filename
            ),
            media_mime_type=content_type,
            media_captured_at=occurred_at,
        )
    except ValueError as exc:
        _safe_unlink(stored_path)
        message = str(exc)
        status_code = (
            409
            if "already exists" in message
            else 400
        )
        raise HTTPException(
            status_code=status_code,
            detail=message,
        ) from exc
    except Exception:
        _safe_unlink(stored_path)
        raise

    user, guitars = repository.get_user(
        user_id
    )

    return {
        "individual_id": individual_id,
        "observation_id": observation_id,
        "claim_id": claim_id,
        "media_asset_id": media_asset_id,
        "user": _row_dict(user),
        "guitars": [
            _row_dict(row)
            for row in guitars
        ],
    }


@app.delete("/api/claims/{claim_id}")
def api_delete_claim(
    claim_id: int,
) -> dict[str, Any]:
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


@app.delete("/api/individuals/{individual_id}")
def api_delete_individual(
    individual_id: int,
) -> dict[str, Any]:
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
    media_asset_id: int,
) -> FileResponse:
    media = repo().get_media_asset(
        media_asset_id
    )
    if not media:
        raise HTTPException(
            status_code=404,
            detail="Media asset not found",
        )

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
        "observation_id": observation_id,
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
        **result,
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
def api_users() -> list[dict[str, Any]]:
    return [
        _row_dict(row)
        for row
        in repo().list_users()
    ]


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


@app.get("/api/users/{user_id}")
def api_user(
    user_id: int,
) -> dict[str, Any]:
    user, guitars = repo().get_user(
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
        "summary": repo().get_user_summary(user_id),
    }


@app.patch("/api/users/{user_id}")
def api_update_user(
    user_id: int,
    request: UserUpdateRequest,
) -> dict[str, Any]:
    repository = repo()

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


INDEX_HTML = (Path(__file__).with_name("static") / "index_html.html").read_text(encoding="utf-8")



USER_PROFILE_HTML = (Path(__file__).with_name("static") / "user_profile_html.html").read_text(encoding="utf-8")


USER_VIEW_HTML = (Path(__file__).with_name("static") / "user_view_html.html").read_text(encoding="utf-8")


USER_EDIT_HTML = (Path(__file__).with_name("static") / "user_edit_html.html").read_text(encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Your Guitar Chronicle Phase 1 browser GUI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://{args.host}:{args.port}")).start()

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
