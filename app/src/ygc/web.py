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
from ygc.db.repository import Repository
from ygc.extractors.serial import extract_serial_candidates
from ygc.reverb_adapter import (
    classify_vintage_listing,
    to_listing_claim_data,
    to_provenance_observation,
)


app = FastAPI(title="Your Guitar Chronicle Phase 1")

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

    result.update(
        repository.active_cached_listing_ids(
            "reverb",
            ids,
        )
    )
    return result


def _cache_rejected_listing(
    repository: Repository,
    listing_id: str | None,
    status: str,
) -> None:
    if not listing_id:
        return

    normalized = str(status or "").strip().lower()
    if normalized not in {
        "modern",
        "non_target",
        "unknown",
    }:
        return

    ttl = (
        timedelta(days=1)
        if normalized == "unknown"
        else timedelta(days=30)
    )
    recheck_after = (
        datetime.now(timezone.utc) + ttl
    ).isoformat()
    repository.cache_listing_rejection(
        "reverb",
        str(listing_id),
        normalized,
        recheck_after=recheck_after,
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


class ReleaseClaimRequest(BaseModel):
    user_id: int = Field(ge=1)
    reason: str | None = Field(
        default=None,
        max_length=2000,
    )


class OwnerChangeClaimRequest(BaseModel):
    user_id: int = Field(ge=1)
    acquired_at: str | None = Field(
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
                        claim_data = to_listing_claim_data(
                            item,
                            config.SERIAL_CONFIDENCE_THRESHOLD,
                        )
                        status = str(
                            claim_data.get(
                                "vintage_status",
                                "unknown",
                            )
                        )

                        detail_listing_id = (
                            collector.listing_id(item)
                        )
                        if status == "modern":
                            skipped_modern += 1
                            _cache_rejected_listing(
                                repository,
                                detail_listing_id,
                                status,
                            )
                            continue
                        if status == "non_target":
                            skipped_non_target += 1
                            _cache_rejected_listing(
                                repository,
                                detail_listing_id,
                                status,
                            )
                            continue
                        if status != "vintage":
                            skipped_unknown += 1
                            _cache_rejected_listing(
                                repository,
                                detail_listing_id,
                                "unknown",
                            )
                            continue

                        provenance = to_provenance_observation(
                            item,
                            config.SERIAL_CONFIDENCE_THRESHOLD,
                        )
                        result = (
                            repository.persist_reverb_listing_claim(
                                claim_data,
                                provenance,
                            )
                        )
                        if result["created"]:
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
    return result[:24]


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


@app.post("/api/individuals/{individual_id}/release-claim")
def api_release_claim(
    individual_id: int,
    request: ReleaseClaimRequest,
) -> dict[str, Any]:
    repository = repo()

    try:
        (
            observation_id,
            claim_id,
        ) = repository.create_release_claim(
            request.user_id,
            individual_id,
            reason=request.reason,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    user, guitars = repository.get_user(
        request.user_id
    )

    return {
        "observation_id": observation_id,
        "claim_id": claim_id,
        "user": _row_dict(user),
        "guitars": [
            _row_dict(row)
            for row in guitars
        ],
    }


@app.post("/api/individuals/{individual_id}/owner-change-claim")
def api_owner_change_claim(
    individual_id: int,
    request: OwnerChangeClaimRequest,
) -> dict[str, Any]:
    repository = repo()

    try:
        (
            observation_id,
            claim_id,
        ) = repository.create_owner_change_claim(
            request.user_id,
            individual_id,
            acquired_at=request.acquired_at,
            previous_owner_text=(
                request.previous_owner_text
            ),
            body=request.body,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    user, guitars = repository.get_user(
        request.user_id
    )

    return {
        "observation_id": observation_id,
        "claim_id": claim_id,
        "user": _row_dict(user),
        "guitars": [
            _row_dict(row)
            for row in guitars
        ],
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


INDEX_HTML = r"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Your Guitar Chronicle — Phase 1</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;600;700;800&display=swap');
:root{color-scheme:dark;--bg:#101214;--panel:#181b1f;--line:#2a2f35;--text:#edf0f3;--muted:#9ba6b0;--accent:#d0a45d;--good:#66c58a;--warn:#e0b65f;--bad:#e07171}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 "Noto Sans JP",sans-serif}
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
#detail{white-space:normal}.detail-image{display:block;width:75%;max-height:270px;object-fit:contain;background:#111418;border:1px solid var(--line);border-radius:8px}.detail-image-link{display:block;margin:0 0 6px}.detail-gallery{display:grid;grid-template-columns:20px minmax(0,1fr) 20px;align-items:center;gap:5px;width:75%;margin:0 0 6px}.detail-gallery .detail-image{width:100%;min-width:0}.detail-gallery-nav{width:20px;min-width:20px;height:28px;padding:0;border-radius:5px;background:#20252a;color:#777f87;font-size:11px;font-weight:600;line-height:1}.detail-gallery-nav:hover{background:#272d32;color:#a8b0b7}.detail-gallery-nav:disabled{opacity:.18;cursor:default}.detail-source{display:block;margin:0 0 14px;color:var(--muted);font-size:11px}.detail-source a{color:var(--muted)}.detail-header{margin:0 0 16px}.detail-header-title{font-size:16px;font-weight:700;margin-bottom:6px}.current-owner-line{font-size:13px;margin-bottom:10px}.catalog-spec{font-size:13px;line-height:1.7}.catalog-spec-row{overflow-wrap:anywhere}.catalog-spec-label{font-weight:700}.catalog-spec-empty{color:var(--muted)}.detail-meta-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.detail-meta-item{background:#14171a;border:1px solid var(--line);border-radius:8px;padding:9px 10px;min-width:0}.detail-meta-label{display:block;color:var(--muted);font-size:10px;margin-bottom:2px}.detail-meta-value{display:block;color:var(--text);font-size:12px;overflow-wrap:anywhere}.detail-meta-value a{color:var(--text)}.detail-section{margin:18px 0 8px;font-size:13px;font-weight:700;color:var(--text);border-bottom:1px solid var(--line);padding-bottom:6px}.latest-observation-scroll{max-height:340px;overflow-y:auto;scrollbar-gutter:stable;padding-right:4px}.latest-observation-scroll .observation-card{margin-bottom:0}.observation-card{border:1px solid var(--line);border-radius:10px;background:#14171a;padding:12px 13px;margin:0 0 10px}.observation-card.latest{border-color:#5c513d;background:#181713}.observation-card-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:8px}.observation-date{font-weight:700}.observation-source{font-size:11px;color:var(--muted);white-space:nowrap}.observation-source a{color:var(--muted)}.observation-row{display:grid;grid-template-columns:78px minmax(0,1fr);gap:8px;margin:4px 0}.observation-label{color:var(--muted);font-size:11px}.observation-value{min-width:0;overflow-wrap:anywhere}.observation-title{font-weight:600}.pill{display:inline-block;padding:2px 6px;border:1px solid var(--line);border-radius:10px;margin-right:5px;color:var(--muted)}
.chronicle-toolbar{display:flex;justify-content:space-between;align-items:center;gap:10px;margin:18px 0 10px;border-bottom:1px solid var(--line);padding-bottom:8px}
.claim-card{border:1px solid #4a4337;border-radius:10px;background:#171612;padding:12px 13px;margin:8px 0 12px 22px}
.claim-card.claim-type-ownership{background:#101d16;border-color:#294b37}
.claim-card.claim-type-specification{background:#101820;border-color:#29465d}
.claim-card.claim-type-incident{background:#211111;border-color:#5a2c2c}
.claim-card.claim-type-event{background:#1b1422;border-color:#4d3560}
.claim-card.claim-type-media{background:#21190d;border-color:#5b4724}
.claim-card.claim-type-ownership .claim-badge{background:#4f9a68;color:#08110b}
.claim-card.claim-type-specification .claim-badge{background:#4d88b8;color:#071018}
.claim-card.claim-type-incident .claim-badge{background:#b85a5a;color:#160808}
.claim-card.claim-type-event .claim-badge{background:#9360b8;color:#120917}
.claim-card.claim-type-media .claim-badge{background:#c68a32;color:#171006}.identity-correction-card{margin-left:42px;border-style:dashed}
.claim-head{display:flex;align-items:center;gap:8px;margin-bottom:10px}.claim-badge{display:inline-block;padding:3px 7px;border-radius:999px;background:var(--accent);color:#18130c;font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:.03em}.claim-event-date{margin-left:auto;text-align:right;font-size:11px;color:var(--muted);white-space:nowrap}
.claim-body{font-size:12px;line-height:1.5}.claim-memo{margin-top:8px;white-space:pre-wrap}.claim-card img.claim-evidence-image{display:block!important;width:48px!important;height:48px!important;max-width:48px!important;max-height:48px!important;object-fit:cover;border:1px solid var(--line);border-radius:6px;margin-top:6px}.claim-media-thumbs{display:flex;gap:6px;flex-wrap:wrap;margin-top:7px}.claim-media-thumbs img{display:block!important;width:48px!important;height:48px!important;max-width:48px!important;max-height:48px!important;object-fit:cover;border:1px solid var(--line);border-radius:6px}.claim-card img.claim-media-image{display:block;width:min(320px,100%);height:auto;max-height:240px;object-fit:contain;border:1px solid var(--line);border-radius:8px;margin-top:8px;background:#0f1114}
.claim-footer{margin-top:10px;padding-top:8px;border-top:1px solid var(--line);font-size:9px;color:var(--muted);display:flex;align-items:center;justify-content:space-between;gap:10px}.claim-footer-meta{text-align:right}.claim-votes{display:flex;gap:6px}.claim-vote{padding:4px 7px;border-radius:999px;background:#252a2f;color:var(--text);font-size:10px;min-width:54px}.claim-vote.active{outline:1px solid var(--accent)}
#chronicleEntries{max-height:560px;overflow-y:auto;padding-right:6px}
.claim-card{position:relative}
.claim-card:not(:last-child)::after{content:"";position:absolute;left:50%;top:100%;width:1px;height:12px;background:#4c5258;pointer-events:none;transform:translateX(-.5px)}
.modal-backdrop{display:none;position:fixed;inset:0;background:rgba(0,0,0,.65);align-items:center;justify-content:center;z-index:1000}.modal-backdrop.open{display:flex}.modal{width:min(520px,calc(100vw - 32px));background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px;box-shadow:0 18px 60px rgba(0,0,0,.45)}.modal-actions{display:flex;gap:8px;justify-content:flex-end;margin-top:14px}
@media(max-width:900px){.grid{grid-template-columns:1fr}.cards{grid-template-columns:repeat(2,1fr)}.crawl-controls{grid-template-columns:repeat(2,minmax(0,1fr))}.crawl-controls>div:last-child{grid-column:1/-1}.crawl-controls button{width:100%}}@media(max-width:520px){.detail-meta-grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<header><div><h1>Your Guitar Chronicle <span class="sub">Phase 1 Browser Console</span></h1><div class="sub">Reverb収集・Individual確認をブラウザから操作</div></div><div class="toolbar" style="margin:0"><select id="activeUserSelect" style="width:auto;min-width:150px" onchange="setActiveUser(this.value)"><option value="">Guest</option></select><button onclick="createUser()">新規アカウント</button><button class="secondary" onclick="window.open('/user-view','_blank','noopener')">User View</button><div id="tokenState"></div><button class="secondary" onclick="openTokenSettings()">Token設定</button><button class="secondary" onclick="exportDatabase()">バックアップ</button><button class="secondary" onclick="openDatabaseImport()">バックアップ復元</button><button class="secondary" onclick="runClaimMigration()">Claim Migration</button><button class="secondary bad" onclick="resetDatabase()">DB初期化</button></div></header>
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
<div class="toolbar"><h2 style="margin:0;flex:1">Product List</h2><input id="individualFilter" placeholder="maker / model / finish / year / serial" oninput="renderIndividuals()"><button class="secondary" onclick="startBackfill()">既存DBバックフィル（今回のみ）</button><button class="secondary" onclick="loadIndividuals()">更新</button></div>
<div class="table-wrap"><table><thead><tr><th class="sortable" onclick="setIndividualSort('id')">ID<span class="sort-indicator" id="sort-id"></span></th><th class="sortable" onclick="setIndividualSort('manufacturer')">Maker<span class="sort-indicator" id="sort-manufacturer"></span></th><th class="sortable" onclick="setIndividualSort('model')">Model<span class="sort-indicator" id="sort-model"></span></th><th class="sortable" onclick="setIndividualSort('finish')">Finish<span class="sort-indicator" id="sort-finish"></span></th><th class="sortable" onclick="setIndividualSort('year')">Year<span class="sort-indicator" id="sort-year"></span></th><th class="sortable" onclick="setIndividualSort('serial_number')">Serial<span class="sort-indicator" id="sort-serial_number"></span></th><th class="sortable" onclick="setIndividualSort('claim_count')">Claims<span class="sort-indicator" id="sort-claim_count"></span></th></tr></thead><tbody id="individualBody"></tbody></table></div>
</div>
<div class="panel">
<div class="toolbar"><h2 style="margin:0;flex:1">Statistics</h2><button class="secondary" onclick="loadStatistics()">更新</button></div>
<div id="statistics" class="sub">集計中...</div>
</div>
<div class="panel">
<div class="toolbar"><h2 style="margin:0;flex:1">User Account</h2><button class="secondary" onclick="loadActiveUser()">更新</button></div>
<div id="accountPanel" class="sub">上部の「新規アカウント」からアカウントを作成してください。</div>
</div>
</section>

<section>
<div class="panel">
<h2>Product Detail</h2>
<div id="detail" class="sub">Product List の行をクリックすると履歴を表示します。</div>
</div>
</section>
</div>
</main>
<input id="dbImportInput" type="file" accept=".zip,.db,application/zip,application/vnd.sqlite3,application/x-sqlite3" style="display:none" onchange="importDatabaseFile(this)">
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
let users=[];
let activeUser=null;
let selectedIndividualId=null;
let productGallery=[];
let productGalleryIndex=0;
const TOKEN_KEY='ygc_reverb_api_token';
const ACTIVE_USER_KEY='ygc_active_user_id';
const esc=s=>String(s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[m]));
function storedToken(){return (localStorage.getItem(TOKEN_KEY)||'').trim()}
async function jfetch(url,opt={}){const headers=new Headers(opt.headers||{});const token=storedToken();if(token)headers.set('X-Reverb-Token',token);const r=await fetch(url,{...opt,headers});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||r.statusText);return d}
function statCard(label,value){return '<div class="card"><div class="num">'+esc(value)+'</div><div class="label">'+esc(label)+'</div></div>'}
async function refreshStatus(){const d=await jfetch('/api/status');const s=d.stats;document.getElementById('cards').innerHTML=[
statCard('Observations',s.observations),statCard('Serial Listings',s.serial_observations),statCard('Serial Rate',s.serial_extraction_rate.toFixed(1)+'%'),statCard('Product List',s.individuals),statCard('Repeated',s.repeated_individuals)
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
  const message='現在のDBとMediaを選択したバックアップで置き換えます。\n\n'+file.name+'\n\n旧形式の .db も復元できますが、その場合Mediaは含まれません。\n\n実行前に必要であれば現在の状態をバックアップしてください。続行しますか？';
  if(!confirm(message)){input.value='';return}
  try{
    const d=await jfetch('/api/import-db',{
      method:'POST',
      headers:{'Content-Type':'application/octet-stream'},
      body:file
    });
    individuals=[];
    document.getElementById('detail').textContent='Product List の行をクリックすると履歴を表示します。';
    document.getElementById('jobResults').innerHTML='';
    document.getElementById('jobMessage').textContent='バックアップを復元しました';
    document.getElementById('jobBar').style.width='0%';
    await refreshStatus();
    await loadIndividuals();
    await loadUsers();
    const imported=d.imported_counts||{};
    const media=d.legacy_database?'旧DB形式（Mediaなし）':('Media: '+(d.imported_media_count??0));
    const architecture=await jfetch('/api/claim-architecture-status');
    alert('バックアップを復元しました。\nObservations: '+(imported.observations??'')+'\nProduct List: '+(imported.individuals??'')+'\nCrawl Runs: '+(imported.crawl_runs??'')+'\n'+media+'\nClaim Migration: '+(architecture.ready?'不要':'必要'));
  }catch(e){
    alert('バックアップ復元に失敗しました。\n'+e.message);
  }finally{
    input.value='';
  }
}
async function runClaimMigration(){
  try{
    const status=await jfetch('/api/claim-architecture-status');
    if(status.ready){
      alert('このDBはClaim-centered構造で、Snapshotも最新です。');
      return;
    }
    const message='旧Observation中心DBをClaim-centered構造へ移行します。\n\n未移行Listing Observation: '+status.unmigrated_listing_observations+'\nClaimなしIndividual: '+status.claimless_individuals+'\n\n既存Claimは重複生成しません。続行しますか？';
    if(!confirm(message))return;
    const d=await jfetch('/api/migrate-claims',{method:'POST'});
    const m=d.migration||{};
    const a=d.after||{};
    await refreshStatus();
    await loadIndividuals();
    const r=d.rebuild||{};
    alert('Claim Migration / Snapshot Rebuild完了\nClaims created: '+(m.claims_created??0)+'\nListing items created: '+(m.listing_items_created??0)+'\nMigration snapshots: '+(m.snapshots_rebuilt??0)+'\nAll snapshots rebuilt: '+(r.snapshots_rebuilt??0)+'\nSkipped: '+(r.snapshots_skipped??0)+'\nReady: '+(a.ready?'Yes':'No')+(a.backfill_recommended?'\n\nReverb Listing ClaimのLocation等が不足しています。続けて「既存DBバックフィル（今回のみ）」を実行してください。':''));
  }catch(e){
    alert('Claim Migrationに失敗しました。\n'+e.message);
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
    document.getElementById('detail').textContent='Product List の行をクリックすると履歴を表示します。';
    document.getElementById('jobResults').innerHTML='';
    document.getElementById('jobMessage').textContent='DBを初期化しました';
    document.getElementById('jobBar').style.width='0%';
    localStorage.removeItem(ACTIVE_USER_KEY);
    activeUser=null;
    await refreshStatus();
    await loadIndividuals();
    await loadUsers();
    alert('DBを初期化しました。');
  }catch(e){
    alert(e.message);
  }
}
async function loadIndividuals(){individuals=await jfetch('/api/individuals');renderIndividuals()}
function countList(title,rows){
  if(!rows||!rows.length)return '<div><strong>'+esc(title)+'</strong><div class="sub">—</div></div>';
  return '<div><strong>'+esc(title)+'</strong>'+rows.map(x=>'<div class="sub">'+esc(x.label)+' : '+esc(x.count)+'</div>').join('')+'</div>';
}
async function loadStatistics(){
  try{
    const d=await jfetch('/api/statistics');
    const s=d.summary||{};
    const summary='<div class="detail-meta-grid" style="margin-bottom:12px">'+[
      ['Product List',s.individuals],
      ['Makers',s.makers],
      ['Models',s.models],
      ['Finishes',s.finishes],
      ['Current Location known',s.located_individuals]
    ].map(x=>'<div class="detail-meta-item"><span class="detail-meta-label">'+esc(x[0])+'</span><span class="detail-meta-value">'+esc(x[1]??0)+'</span></div>').join('')+'</div>';
    const lists='<div class="detail-meta-grid">'+[
      countList('Maker',d.makers),
      countList('Model',d.models),
      countList('Finish',d.finishes),
      countList('Current Country',d.current_countries)
    ].map(x=>'<div class="detail-meta-item">'+x+'</div>').join('')+'</div>';
    document.getElementById('statistics').innerHTML=summary+lists;
  }catch(e){
    document.getElementById('statistics').textContent='Statistics error: '+e.message;
  }
}
async function loadUsers(){
  users=await jfetch('/api/users');
  const select=document.getElementById('activeUserSelect');
  const saved=localStorage.getItem(ACTIVE_USER_KEY)||'';
  select.innerHTML='<option value="">Guest</option>'+users.map(u=>'<option value="'+u.id+'">'+esc(u.display_name)+' (#'+u.id+')</option>').join('');
  const target=users.some(u=>String(u.id)===String(saved))?saved:'';
  select.value=target;
  if(target){
    localStorage.setItem(ACTIVE_USER_KEY,target);
    await loadActiveUser();
  }else{
    activeUser=null;
    localStorage.removeItem(ACTIVE_USER_KEY);
    renderAccount();
  }
}
async function createUser(){
  try{
    const d=await jfetch('/api/users',{method:'POST'});
    const id=String(d.user.id);
    localStorage.setItem(ACTIVE_USER_KEY,id);
    await loadUsers();
    document.getElementById('activeUserSelect').value=id;
    await loadActiveUser();
  }catch(e){
    alert('アカウント作成に失敗しました。\n'+e.message);
  }
}
async function setActiveUser(value){
  if(!value){
    activeUser=null;
    localStorage.removeItem(ACTIVE_USER_KEY);
    renderAccount();
    if(selectedIndividualId)await showIndividual(selectedIndividualId);
    return;
  }
  localStorage.setItem(ACTIVE_USER_KEY,String(value));
  await loadActiveUser();
  if(selectedIndividualId)await showIndividual(selectedIndividualId);
}
async function loadActiveUser(){
  const id=localStorage.getItem(ACTIVE_USER_KEY);
  if(!id){
    activeUser=null;
    renderAccount();
    return;
  }
  try{
    activeUser=await jfetch('/api/users/'+id);
    renderAccount();
  }catch(e){
    activeUser=null;
    localStorage.removeItem(ACTIVE_USER_KEY);
    await loadUsers();
  }
}
function renderAccount(){
  const el=document.getElementById('accountPanel');
  if(!activeUser||!activeUser.user){
    el.className='sub';
    el.textContent='上部の「新規アカウント」からアカウントを作成してください。';
    return;
  }
  const u=activeUser.user;
  const guitars=activeUser.guitars||[];
  el.className='';
  el.innerHTML='<div class="detail-meta-grid">'+
    '<div class="detail-meta-item"><span class="detail-meta-label">Display Name</span><input id="accountName" value="'+esc(u.display_name||'')+'"></div>'+
    '<div class="detail-meta-item"><span class="detail-meta-label">Account Type</span><select id="accountType"><option value="user"'+(u.account_type==='user'?' selected':'')+'>User</option><option value="shop"'+(u.account_type==='shop'?' selected':'')+'>Shop</option></select></div>'+
    '<div class="detail-meta-item"><span class="detail-meta-label">Country</span><input id="accountCountry" placeholder="JP / US / NL ..." value="'+esc(u.location_country||'')+'"></div>'+
    '<div class="detail-meta-item"><span class="detail-meta-label">Region</span><input id="accountRegion" placeholder="Kyoto / CA / NH ..." value="'+esc(u.location_region||'')+'"></div>'+
    '</div>'+
    '<div class="toolbar" style="margin-top:10px"><button onclick="saveUser()">保存</button><span class="sub">認証なしのPhase 1アカウント / ID '+esc(u.id)+'</span></div>'+
    '<div class="detail-section">Owned Guitars</div>'+
    (guitars.length?guitars.map(g=>'<div class="observation-card"><div class="observation-card-head"><div class="observation-date">'+esc(g.manufacturer)+' '+esc(g.model||'')+'</div><div class="observation-source">'+esc(g.ownership_status||'')+'</div></div><div class="sub">'+esc(g.year||'')+(g.finish?' / '+esc(g.finish):'')+(g.serial_number?' / '+esc(g.serial_number):'')+'</div><div class="toolbar" style="margin-top:8px"><button class="secondary" onclick="showIndividual('+g.individual_id+')">Detail</button><button class="secondary bad" onclick="unlinkOwnedGuitar('+g.individual_id+')">紐づけ解除</button></div></div>').join(''):'<div class="sub">まだ所有ギターは登録されていません。</div>');
}
async function saveUser(){
  if(!activeUser||!activeUser.user)return;
  const id=activeUser.user.id;
  const body={
    display_name:document.getElementById('accountName').value.trim(),
    account_type:document.getElementById('accountType').value,
    location_country:document.getElementById('accountCountry').value.trim()||null,
    location_region:document.getElementById('accountRegion').value.trim()||null
  };
  try{
    activeUser=await jfetch('/api/users/'+id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    await loadUsers();
    document.getElementById('activeUserSelect').value=String(id);
    await loadActiveUser();
  }catch(e){
    alert('アカウント保存に失敗しました。\n'+e.message);
  }
}
function activeUserOwns(individualId){
  return !!(activeUser&&(activeUser.guitars||[]).some(g=>Number(g.individual_id)===Number(individualId)&&g.ownership_status==='current_owner'));
}
function ownershipControlsHtml(individualId){
  if(!activeUser||!activeUser.user)return '<div class="sub" style="margin-top:10px">所有ギターに紐づけるにはUserを選択してください。</div>';
  if(activeUserOwns(individualId)){
    return '<div class="toolbar" style="margin-top:10px"><span class="status good">現在のUserが所有中</span><button class="secondary bad" onclick="unlinkOwnedGuitar('+individualId+')">紐づけ解除</button></div>';
  }
  return '<div class="toolbar" style="margin-top:10px"><button onclick="linkOwnedGuitar('+individualId+')">所有ギターに追加</button></div>';
}
async function linkOwnedGuitar(individualId){
  if(!activeUser||!activeUser.user)return;
  try{
    activeUser=await jfetch('/api/users/'+activeUser.user.id+'/guitars/'+individualId,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ownership_status:'current_owner'})});
    renderAccount();
    await showIndividual(individualId);
  }catch(e){
    alert('所有ギターの紐づけに失敗しました。\n'+e.message);
  }
}
async function unlinkOwnedGuitar(individualId){
  if(!activeUser||!activeUser.user)return;
  try{
    activeUser=await jfetch('/api/users/'+activeUser.user.id+'/guitars/'+individualId,{method:'DELETE'});
    renderAccount();
    if(selectedIndividualId===Number(individualId))await showIndividual(individualId);
  }catch(e){
    alert('所有ギターの紐づけ解除に失敗しました。\n'+e.message);
  }
}
function normalizeSortValue(value,key){if(key==='id'||key==='claim_count')return Number(value||0);return String(value??'').toLowerCase()}
function setIndividualSort(key){if(individualSortKey===key){individualSortDirection*=-1}else{individualSortKey=key;individualSortDirection=1}renderIndividuals()}
function updateSortIndicators(){for(const key of ['id','manufacturer','model','finish','year','serial_number','claim_count']){const el=document.getElementById('sort-'+key);if(el)el.textContent=individualSortKey===key?(individualSortDirection===1?'▲':'▼'):''}}
function renderIndividuals(){const q=document.getElementById('individualFilter').value.toLowerCase();const rows=individuals.filter(x=>[x.manufacturer,x.model,x.finish,x.year,x.serial_number].join(' ').toLowerCase().includes(q)).slice().sort((a,b)=>{const av=normalizeSortValue(a[individualSortKey],individualSortKey);const bv=normalizeSortValue(b[individualSortKey],individualSortKey);if(av<bv)return-1*individualSortDirection;if(av>bv)return 1*individualSortDirection;return Number(a.id)-Number(b.id)});updateSortIndicators();document.getElementById('individualBody').innerHTML=rows.map(x=>'<tr class="clickable" onclick="showIndividual('+x.id+')"><td>'+x.id+'</td><td>'+esc(x.manufacturer)+'</td><td>'+esc(x.model)+'</td><td>'+esc(x.finish||'')+'</td><td>'+esc(x.year||'')+'</td><td class="mono">'+esc(x.serial_number)+'</td><td>'+x.claim_count+'</td></tr>').join('')}
function sourceName(o){return String(o.source_site||'').toLowerCase()==='reverb'?'Reverb':String(o.source_site||'Source')}
function currentSnapshotOwnerHtml(i){if(!i)return '—';const name=String(i.current_owner_name||'').trim();if(!name)return '—';const type=String(i.current_owner_type||'').trim();const listingUrl=String(i.current_owner_source_url||'').trim();const label=type==='shop'?name+' (Shop)':name;if(type==='shop'&&listingUrl)return '<a href="'+esc(listingUrl)+'" target="_blank" rel="noopener noreferrer">'+esc(label)+'</a>';return esc(label)}
function currentLocationHtml(i){const parts=[i&&i.location_country,i&&i.location_region].filter(Boolean);return parts.length?esc(parts.join(' / ')):'—'}
function productGalleryHtml(images,model){
  productGallery=(images||[]).slice();
  productGalleryIndex=0;
  if(!productGallery.length)return '';
  const item=productGallery[0];
  const disabled=productGallery.length<2?' disabled':'';
  const caption=String(item.caption||'').trim();
  const source=String(item.label||'Uploaded Image')+(caption?' — '+caption:'')+' (1/'+productGallery.length+')';
  return '<div class="detail-gallery">'+
    '<button class="detail-gallery-nav" onclick="stepProductGallery(-1)"'+disabled+'>◀</button>'+
    '<img class="detail-image" id="productGalleryImage" src="'+esc(item.url)+'" alt="'+esc(model||'Guitar')+'" loading="lazy" onerror="this.onerror=null;this.src=\'/assets/no-picture.svg\'">'+
    '<button class="detail-gallery-nav" onclick="stepProductGallery(1)"'+disabled+'>▶</button>'+
    '</div><span class="detail-source" id="productGallerySource">'+esc(source)+'</span>';
}
function stepProductGallery(delta){
  if(productGallery.length<2)return;
  productGalleryIndex=(productGalleryIndex+delta+productGallery.length)%productGallery.length;
  const item=productGallery[productGalleryIndex];
  const image=document.getElementById('productGalleryImage');
  const source=document.getElementById('productGallerySource');
  if(image)image.src=item.url;
  if(source){
    const caption=String(item.caption||'').trim();
    source.textContent=String(item.label||'Uploaded Image')+(caption?' — '+caption:'')+' ('+(productGalleryIndex+1)+'/'+productGallery.length+')';
  }
}
function specificationFieldLabel(value){const labels={body:'Body',bridge:'Bridge',fingerboard:'Fingerboard',frets:'Frets',neck:'Neck',nut:'Nut',pickups:'Pickups',pickguard:'Pickguard',potentiometers:'Potentiometers',tuners:'Tuners',wiring:'Wiring',weight:'Weight',finish:'Finish'};const key=String(value||'').trim();return labels[key]||key.replace(/_/g,' ').replace(/\b\w/g,m=>m.toUpperCase())}
function identityFieldLabel(value){const labels={manufacturer:'Maker',model:'Model',year:'Year',serial_number:'Serial'};return labels[String(value||'')]||String(value||'').replace(/_/g,' ')}
function claimTypeLabel(value){return String(value||'claim').split('_').map(x=>x?x[0].toUpperCase()+x.slice(1):'').join(' ')}
function displayEventDate(value){if(!value)return '日付不明';const text=String(value).trim();const direct=text.match(/^(\d{4}-\d{2}-\d{2})/);if(direct)return direct[1];const d=new Date(text);if(Number.isNaN(d.getTime()))return text;return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')}
function displayInputDate(value){if(!value)return '入力日時不明';const d=new Date(String(value));return Number.isNaN(d.getTime())?String(value):d.toLocaleString('ja-JP')}
function claimHeaderHtml(c,type,eventDate){return '<span class="claim-badge">'+esc(type)+'</span><span class="claim-event-date">'+esc(eventDate)+'</span>'}
function claimVisualTypeClass(c){
  if(c.claim_type==='ownership'||c.claim_type==='owner_change'||c.claim_type==='release')return ' claim-type-ownership';
  if(c.claim_type==='specification')return ' claim-type-specification';
  if(c.claim_type==='incident')return ' claim-type-incident';
  if(c.claim_type==='event')return ' claim-type-event';
  if(c.claim_type==='media')return ' claim-type-media';
  return '';
}
function claimCard(c){
  const type=c.claim_type==='specification'?(c.specification_kind==='repair'?'Repair':'Specification'):(c.claim_type==='ownership'?claimTypeLabel(c.ownership_kind||'acquire'):(c.claim_type==='incident'?claimTypeLabel(c.value_text||'incident'):(c.claim_type==='event'?claimTypeLabel(c.value_text||'event'):(c.claim_type==='release'?'Release':claimTypeLabel(c.claim_type)))));
  const eventDate=displayEventDate(c.occurred_at);
  let body='';
  if(c.claim_type==='ownership'){
    const kind=String(c.ownership_kind||'acquire');
    const owner=String(c.author_name||'User').trim()||'User';
    const raw=String(c.observation_raw_text||'');
    const firstLine=(raw.split(/\r?\n/)[0]||'').trim();
    const party=firstLine.startsWith('Previous owner:')
      ? (firstLine.slice('Previous owner:'.length).trim()||'Unknown')
      : 'Unknown';
    if(kind==='release'){
      body='<div><strong>'+esc(owner)+' released this product.</strong></div>';
    }else if(kind==='transfer'){
      body='<div><strong>'+esc(party)+' acquired this product from '+esc(owner)+'.</strong></div>';
    }else if(kind==='inherit'){
      body='<div><strong>'+esc(party)+' inherited this product from '+esc(owner)+'.</strong></div>';
    }else{
      body='<div><strong>'+esc(owner)+' became the owner of this product.</strong></div>';
    }
    if(c.body)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }else if(c.claim_type==='incident'){
    if(c.body)body+='<div><strong>'+esc(c.body)+'</strong></div>';
  }else if(c.claim_type==='event'){
    if(c.body)body+='<div><strong>'+esc(c.body)+'</strong></div>';
  }else if(c.claim_type==='owner_change'){
    body='<div><strong>'+esc(c.author_name||'User')+' has become the owner.</strong></div>';
    if(c.body)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }else if(c.claim_type==='release'){
    body='<div><strong>Ownership released. Current owner is Unknown.</strong></div>';
    if(c.body)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }else if(c.claim_type==='specification'){
    const items=(c.spec_items&&c.spec_items.length)?c.spec_items:(c.field_name?[{field_name:c.field_name,value_text:c.value_text}]:[]);
    body=items.map(item=>'<div><strong>'+esc(specificationFieldLabel(item.field_name))+': '+esc(item.value_text||'')+'</strong></div>').join('');
    if(c.body)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }else if(c.claim_type==='identity_correction'){
    const items=c.identity_items||[];
    body=items.map(item=>'<div><strong>'+esc(identityFieldLabel(item.field_name))+':</strong> '+esc(item.old_value||'—')+' → '+esc(item.new_value||'—')+'</div>').join('');
    if(c.body)body+='<div class="claim-memo">Reason: '+esc(c.body)+'</div>';
  }else if(c.claim_type==='media'){
    const mediaImages=(c.media_images&&c.media_images.length)
      ? c.media_images
      : (c.evidence_media_id?[{id:c.evidence_media_id,url:'/api/media/'+encodeURIComponent(c.evidence_media_id)}]:[]);
    if(mediaImages.length){
      body+='<div class="claim-media-thumbs">'+mediaImages.map(m=>'<img class="claim-evidence-image" width="48" height="48" style="width:48px!important;height:48px!important;max-width:48px!important;max-height:48px!important;object-fit:cover" src="'+esc(m.url)+'" alt="Media Claim image" loading="lazy" onerror="this.onerror=null;this.src=\'/assets/no-picture.svg\'">').join('')+'</div>';
    }
    if(c.body)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }else if(c.claim_type==='listing'){
    const title=c.listing_title||c.body||'Listing observed';
    body='<div><strong>'+esc(title)+'</strong></div>';
    const details=[];
    const listingOwner=String(c.observed_owner_name||'').trim();
    const seller=String(c.seller||'').trim();
    if(listingOwner&&listingOwner!==seller)details.push('Owner: '+listingOwner);
    if(seller)details.push('Seller: '+seller);
    const location=[c.location_country,c.location_region].filter(Boolean).join(' / ');
    if(location)details.push('Location: '+location);
    const specs=[c.observed_model&&('Model: '+c.observed_model),c.observed_finish&&('Finish: '+c.observed_finish),c.observed_year&&('Year: '+c.observed_year),c.observed_serial_number&&('Serial: '+c.observed_serial_number)].filter(Boolean).join(' / ');
    if(specs)details.push(specs);
    if(details.length)body+='<div class="claim-memo">'+details.map(esc).join('<br>')+'</div>';
    if(c.body&&c.body!==title)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
    if(c.source_url)body+='<div class="claim-memo"><a href="'+esc(c.source_url)+'" target="_blank" rel="noopener noreferrer">Open listing</a></div>';
  }else{
    if(c.value_text)body+='<div><strong>'+esc(c.value_text)+'</strong></div>';
    if(c.body)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }
  if(c.evidence_media_id&&c.claim_type!=='media')body+='<div class="claim-memo"><img class="claim-evidence-image" width="48" height="48" style="width:48px;height:48px;max-width:48px;max-height:48px;object-fit:cover" src="/api/media/'+encodeURIComponent(c.evidence_media_id)+'" alt="Claim evidence" loading="lazy" onerror="this.onerror=null;this.src=\'/assets/no-picture.svg\'"></div>';
  const good=String(Number(c.good_count||0)).padStart(2,'0');
  const bad=String(Number(c.bad_count||0)).padStart(2,'0');
  const votes='<div class="claim-votes"><span class="claim-vote">👍 '+good+'</span><span class="claim-vote">👎 '+bad+'</span><button class="claim-vote bad" onclick="deleteClaim('+c.id+')">Delete</button></div>';
  return '<div class="claim-card'+claimVisualTypeClass(c)+(c.claim_type==='identity_correction'?' identity-correction-card':'')+'"><div class="claim-head">'+claimHeaderHtml(c,type,eventDate)+'</div><div class="claim-body">'+body+'</div><div class="claim-footer">'+votes+'<div class="claim-footer-meta">'+esc(displayInputDate(c.created_at))+' · By '+esc(c.author_name||('User #'+c.author_user_id))+'</div></div></div>';
}
function renderAdminChronicle(claims){
  const sorted=(claims||[]).slice().sort((a,b)=>{const av=String(a.occurred_at||a.created_at||'');const bv=String(b.occurred_at||b.created_at||'');if(av<bv)return 1;if(av>bv)return-1;return Number(b.id)-Number(a.id)});
  const correctionsByTarget=new Map();const roots=[];
  for(const claim of sorted){if(claim.claim_type==='identity_correction'&&claim.target_claim_id){const key=Number(claim.target_claim_id);if(!correctionsByTarget.has(key))correctionsByTarget.set(key,[]);correctionsByTarget.get(key).push(claim)}else roots.push(claim)}
  const ordered=[];for(const claim of roots){ordered.push(claim);const corrections=correctionsByTarget.get(Number(claim.id))||[];corrections.sort((a,b)=>String(a.created_at||'').localeCompare(String(b.created_at||'')));ordered.push(...corrections);correctionsByTarget.delete(Number(claim.id))}
  for(const corrections of correctionsByTarget.values())ordered.push(...corrections);
  return ordered.length?ordered.map(claimCard).join(''):'<div class="sub">Claimはまだありません。</div>';
}
async function showIndividual(id){
  selectedIndividualId=Number(id);
  const [d,claims,currentSpecifications]=await Promise.all([
    jfetch('/api/individuals/'+id),
    jfetch('/api/individuals/'+id+'/claims'+(activeUser&&activeUser.user?'?viewer_user_id='+encodeURIComponent(activeUser.user.id):'')),
    jfetch('/api/individuals/'+id+'/current-specifications')
  ]);
  const i=d.individual;
  const observations=d.observations||[];
  const listing=d.current_listing||null;
  const imageObservation=observations.slice().reverse().find(o=>o.image_url)||null;
  const galleryImages=d.gallery_images||[];
  let out='';
  if(galleryImages.length){
    out+=productGalleryHtml(galleryImages,i.model||'Guitar');
  }else if(i.representative_image_url){
    out+='<img class="detail-image" src="'+esc(i.representative_image_url)+'" alt="'+esc(i.model||'Guitar')+'" loading="lazy" onerror="this.onerror=null;this.src=\'/assets/no-picture.svg\'"><span class="detail-source">Representative Image</span>';
  }else if(listing&&listing.image_url){
    const listingUrl=String(listing.source_url||'');
    const image='<img class="detail-image" src="'+esc(listing.image_url)+'" alt="'+esc(listing.listing_title||i.model||'Guitar')+'" loading="lazy" referrerpolicy="no-referrer" onerror="this.onerror=null;this.src=\'/assets/no-picture.svg\'">';
    if(listingUrl)out+='<a class="detail-image-link" href="'+esc(listingUrl)+'" target="_blank" rel="noopener noreferrer">'+image+'</a><span class="detail-source">Source: <a href="'+esc(listingUrl)+'" target="_blank" rel="noopener noreferrer">'+esc(String(listing.source_site||'Source'))+'</a></span>';
    else out+=image+'<span class="detail-source">Listing Claim</span>';
  }else if(imageObservation){
    const imageUrl=String(imageObservation.source_url||'');
    const image='<img class="detail-image" src="'+esc(imageObservation.image_url)+'" alt="'+esc(imageObservation.title||i.model||'Guitar')+'" loading="lazy" referrerpolicy="no-referrer" onerror="this.onerror=null;this.src=\'/assets/no-picture.svg\'">';
    if(imageUrl)out+='<a class="detail-image-link" href="'+esc(imageUrl)+'" target="_blank" rel="noopener noreferrer">'+image+'</a><span class="detail-source">Source: Reverb image (provenance)</span>';
    else out+=image+'<span class="detail-source">Source: Reverb image (provenance)</span>';
  }else{
    out+='<img class="detail-image" src="/assets/no-picture.svg" alt="No picture"><span class="detail-source">No Picture</span>';
  }

  const specMap={};for(const s of (currentSpecifications||[]))specMap[String(s.field_name||'')]=s;
  const finishValue=specMap.finish?specMap.finish.value_text:(i.finish||'—');
  const fixedSpecRows=[['Maker',i.manufacturer||'—'],['Model',i.model||'—'],['Finish',finishValue||'—'],['Year',i.year||'—'],['Serial',i.serial_number||'—']];
  const hiddenFields=new Set(['maker','manufacturer','model','finish','year','serial','serial_number']);
  const preferredOrder=['body','bridge','fingerboard','frets','neck','nut','pickups','pickguard','potentiometers','tuners','wiring','weight'];
  const dynamicSpecs=(currentSpecifications||[]).filter(s=>!hiddenFields.has(String(s.field_name||'').toLowerCase())).slice().sort((a,b)=>{const ak=String(a.field_name||'').toLowerCase();const bk=String(b.field_name||'').toLowerCase();const ai=preferredOrder.indexOf(ak);const bi=preferredOrder.indexOf(bk);if(ai>=0||bi>=0){if(ai<0)return 1;if(bi<0)return-1;if(ai!==bi)return ai-bi}return ak.localeCompare(bk)});

  out+='<div class="detail-header"><div class="detail-header-title">'+esc(i.manufacturer)+' '+esc(i.model||'')+'</div>'+
    '<div class="current-owner-line"><span class="catalog-spec-label">Current Owner:</span> '+currentSnapshotOwnerHtml(i)+'</div>'+
    '<div class="current-owner-line"><span class="catalog-spec-label">Location:</span> '+currentLocationHtml(i)+'</div>'+
    ownershipControlsHtml(i.id)+
    '<div class="toolbar" style="margin-top:8px"><button class="secondary bad" onclick="deleteIndividual('+i.id+')">Delete Individual</button></div></div>';
  out+='<div class="chronicle-toolbar"><strong>Specification</strong></div><div class="catalog-spec">'+
    fixedSpecRows.map(row=>'<div class="catalog-spec-row"><span class="catalog-spec-label">'+esc(row[0])+':</span> '+esc(row[1])+'</div>').join('')+
    dynamicSpecs.map(s=>'<div class="catalog-spec-row"><span class="catalog-spec-label">'+esc(specificationFieldLabel(s.field_name))+':</span> '+esc(s.value_text||'—')+'</div>').join('')+
    '</div>';
  out+='<div class="chronicle-toolbar"><strong>Chronicle</strong></div><div id="chronicleEntries">'+renderAdminChronicle(claims)+'</div>';
  document.getElementById('detail').innerHTML=out;
}
async function deleteClaim(claimId){
  if(!confirm('Claim #'+claimId+' を完全に削除します。\nこの操作は元に戻せません。続行しますか？'))return;
  try{
    const d=await jfetch('/api/claims/'+claimId,{method:'DELETE'});
    if(selectedIndividualId===Number(d.individual_id))await showIndividual(d.individual_id);
    await loadIndividuals();
  }catch(e){
    alert('Claim削除に失敗しました。\n'+e.message);
  }
}
async function deleteIndividual(individualId){
  const individual=individuals.find(x=>Number(x.id)===Number(individualId));
  const label=individual?(individual.manufacturer+' '+(individual.model||'')+' / '+(individual.serial_number||'')):('Individual #'+individualId);
  if(!confirm(label+' を関連するClaim・Observation・所有紐づけを含め完全に削除します。\n\nこの操作は元に戻せません。続行しますか？'))return;
  const typed=prompt('確認のため DELETE と入力してください。');
  if(typed!=='DELETE')return;
  try{
    await jfetch('/api/individuals/'+individualId,{method:'DELETE'});
    if(selectedIndividualId===Number(individualId))selectedIndividualId=null;
    document.getElementById('detail').textContent='Individualを削除しました。';
    await loadIndividuals();
    await loadStatistics();
    if(activeUser&&activeUser.user)await loadActiveUser();
  }catch(e){
    alert('Individual削除に失敗しました。\n'+e.message);
  }
}
async function startBackfill(){if(!confirm('既存Reverb Listingを再取得して不足しているListing Claim情報を補完します。Observationは変更しません。実行しますか？'))return;try{const d=await jfetch('/api/backfill-metadata',{method:'POST'});pollJob(d.job_id)}catch(e){alert(e.message)}}
async function startCrawl(){const queries=document.getElementById('queries').value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);const minValue=document.getElementById('yearMin').value;const maxValue=document.getElementById('yearMax').value;const body={queries,limit:Number(document.getElementById('limit').value),workers:Number(document.getElementById('workers').value),year_min:minValue?Number(minValue):null,year_max:maxValue?Number(maxValue):null};const btn=document.getElementById('crawlBtn');btn.disabled=true;try{const d=await jfetch('/api/crawl',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});pollJob(d.job_id)}catch(e){alert(e.message);btn.disabled=false}}
async function pollJob(id){try{const d=await jfetch('/api/jobs/'+id);document.getElementById('jobBar').style.width=((d.progress||0)*100)+'%';document.getElementById('jobMessage').textContent=d.message||d.status;let resultHtml=(d.query_results||[]).map(x=>'<div class="sub">'+esc(x.query)+' — new '+x.new_observations+', detail '+x.details_fetched+', existing '+x.skipped_existing+'</div>').join('');if(d.aggregate&&d.aggregate.target_claims!==undefined){resultHtml+='<div class="sub">Backfill — target '+d.aggregate.target_claims+', updated '+d.aggregate.claims_updated+'</div>'}document.getElementById('jobResults').innerHTML=resultHtml;if(d.status==='running'){setTimeout(()=>pollJob(id),1000)}else{document.getElementById('crawlBtn').disabled=false;await refreshStatus();await loadIndividuals();if(d.status==='error')alert(d.error||'crawl error')}}catch(e){document.getElementById('crawlBtn').disabled=false;alert(e.message)}}
(async()=>{await refreshStatus();await loadIndividuals();await loadStatistics();await loadUsers()})()
</script>
</body></html>"""



USER_PROFILE_HTML = r"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Your Guitar Chronicle — User Profile</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;600;700;800&display=swap');
:root{color-scheme:dark;--bg:#101214;--panel:#181b1f;--line:#2a2f35;--text:#edf0f3;--muted:#9ba6b0;--accent:#d0a45d}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 "Noto Sans JP",sans-serif}
header{padding:18px 24px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:12px}
h1{font-size:19px;margin:0}.sub{color:var(--muted);font-size:11px}
button{border:0;border-radius:8px;padding:8px 12px;background:#2a3036;color:var(--text);font:inherit;font-weight:700;cursor:pointer}
button.primary{background:var(--accent);color:#18130c}
main{max-width:1120px;margin:auto;padding:24px}
.profile-hero{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:18px;align-items:center;background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:22px}
.avatar{width:88px;height:88px;border-radius:50%;object-fit:cover;background:#111418;border:1px solid var(--line)}
.name-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.name{font-size:24px;font-weight:800}.you{font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:.05em;padding:3px 7px;border-radius:999px;background:#2a3036;color:var(--muted)}
.meta{margin-top:5px;color:var(--muted);font-size:12px}.bio{margin-top:11px;color:#c8ced4;max-width:680px}
.hero-actions{display:flex;gap:7px;flex-wrap:wrap;justify-content:flex-end}
.stats{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));margin-top:14px;background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.stat{padding:12px;text-align:center;border-right:1px solid var(--line)}.stat:last-child{border-right:0}.stat-value{display:block;font-size:18px;font-weight:800}.stat-label{display:block;margin-top:3px;color:var(--muted);font-size:10px}
.section{margin-top:18px;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px}.section h2{font-size:15px;margin:0 0 12px}
.guitar-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.guitar-card{display:block;text-decoration:none;color:var(--text);background:#14171a;border:1px solid var(--line);border-radius:10px;padding:12px}.guitar-card:hover{background:#1d2125}.guitar-title{font-weight:700}.guitar-meta{font-size:10px;color:var(--muted);margin-top:4px}.empty{color:var(--muted);font-size:11px;padding:6px 0}.placeholder{border:1px dashed #363c43;border-radius:10px;padding:14px;color:var(--muted);font-size:11px}
@media(max-width:760px){.profile-hero{grid-template-columns:auto 1fr}.hero-actions{grid-column:1/-1;justify-content:flex-start}.stats{grid-template-columns:repeat(2,1fr)}.stat{border-bottom:1px solid var(--line)}.guitar-grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<header>
  <h1>Your Guitar Chronicle <span class="sub">User Profile</span></h1>
  <button onclick="window.location.href='/user-view'">User View</button>
</header>
<main>
  <div id="profile"><div class="empty">Loading...</div></div>
</main>
<script>
const ACTIVE_USER_KEY='ygc_active_user_id';
const esc=s=>String(s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[m]));
async function jfetch(url){const r=await fetch(url);const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||r.statusText);return d}
function profileUserId(){const m=location.pathname.match(/\/users\/(\d+)$/);return m?Number(m[1]):null}
function guitarCard(g){
  const title=[g.manufacturer,g.model].filter(Boolean).join(' ')||('Individual #'+g.individual_id);
  const meta=[g.year,g.finish,g.serial_number&&('S/N '+g.serial_number)].filter(Boolean).join(' · ');
  return '<a class="guitar-card" href="/user-view?individual_id='+Number(g.individual_id)+'">'+
    '<div class="guitar-title">'+esc(title)+'</div>'+
    '<div class="guitar-meta">'+esc(meta||'No additional details')+'</div>'+
  '</a>';
}
async function loadProfile(){
  const id=profileUserId();
  if(!id)return;
  const root=document.getElementById('profile');
  const viewerId=Number(localStorage.getItem(ACTIVE_USER_KEY)||0);
  if(!viewerId){
    root.innerHTML=
      '<section class="profile-hero">'+
        '<div></div>'+
        '<div><div class="name">Members only</div><div class="meta">User ProfileはYGCメンバーのみ閲覧できます。</div></div>'+
        '<div class="hero-actions"><button onclick="window.location.href=\'/user-view/edit\'">Sign In</button><button class="primary" onclick="window.location.href=\'/user-view/edit\'">Create Account</button></div>'+
      '</section>';
    return;
  }
  try{
    const d=await jfetch('/api/users/'+id);
    const u=d.user||{};
    const guitars=d.guitars||[];
    const summary=d.summary||{};
    const own=viewerId===Number(id);
    const owned=guitars.filter(g=>g.ownership_status==='current_owner');
    const former=guitars.filter(g=>g.ownership_status==='former_owner');
    const locationText=[u.location_country,u.location_region].filter(Boolean).join(' / ')||'Location not set';
    const accountType=String(u.account_type||'user');
    const joined=u.created_at?('Member since '+String(u.created_at).slice(0,10)):'';
    const actions=own
      ? '<button class="primary" onclick="window.location.href=\'/user-view/edit\'">Edit Your Chronicle</button>'
      : '<button class="primary" type="button">Follow</button><button type="button">Message</button>';
    root.innerHTML=
      '<section class="profile-hero">'+
        '<img class="avatar" src="/api/users/'+u.id+'/avatar?v='+encodeURIComponent(u.updated_at||'')+'" alt="'+esc(u.display_name||'User')+'" onerror="this.onerror=null;this.src=\'/assets/no-icon.svg\'">'+
        '<div>'+
          '<div class="name-row"><span class="name">'+esc(u.display_name||'User')+'</span>'+(own?'<span class="you">You</span>':'')+'</div>'+
          '<div class="meta">'+esc(locationText)+' · '+esc(accountType)+(joined?' · '+esc(joined):'')+'</div>'+
          '<div class="bio">Bio has not been added yet.</div>'+
        '</div>'+
        '<div class="hero-actions">'+actions+'</div>'+
      '</section>'+
      '<section class="stats">'+
        '<div class="stat"><span class="stat-value">'+Number(summary.owned_count||0)+'</span><span class="stat-label">Owned</span></div>'+
        '<div class="stat"><span class="stat-value">'+Number(summary.former_count||0)+'</span><span class="stat-label">Formerly Owned</span></div>'+
        '<div class="stat"><span class="stat-value">'+Number(summary.claim_count||0)+'</span><span class="stat-label">Claims</span></div>'+
        '<div class="stat"><span class="stat-value">0</span><span class="stat-label">Followers</span></div>'+
        '<div class="stat"><span class="stat-value">0</span><span class="stat-label">Following</span></div>'+
      '</section>'+
      '<section class="section"><h2>Owned Guitars</h2><div class="guitar-grid">'+
        (owned.length?owned.map(guitarCard).join(''):'<div class="empty">No owned guitars.</div>')+
      '</div></section>'+
      '<section class="section"><h2>Formerly Owned Guitars</h2><div class="guitar-grid">'+
        (former.length?former.map(guitarCard).join(''):'<div class="empty">No formerly owned guitars.</div>')+
      '</div></section>'+
      '<section class="section"><h2>Recent Activity</h2><div class="placeholder">Recent Claims / Media / Follow activity will appear here.</div></section>';
    document.title=(u.display_name||'User')+' — Your Guitar Chronicle';
  }catch(e){
    root.innerHTML='<div class="empty">User Profileを読み込めませんでした。 '+esc(e.message)+'</div>';
  }
}
loadProfile();
</scrUSER_VIEW_HTML = r"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Your Guitar Chronicle — Top Page</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;600;700;800&display=swap');
:root{color-scheme:dark;--bg:#101214;--panel:#181b1f;--line:#2a2f35;--text:#edf0f3;--muted:#9ba6b0;--accent:#d0a45d;--good:#66c58a;--bad:#e07171}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 "Noto Sans JP",sans-serif}
.sticky-header{position:fixed;top:0;left:0;right:0;z-index:900;background:var(--bg);box-shadow:0 8px 24px rgba(0,0,0,.22)}
header{padding:8px 22px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:20px;min-height:47px}
h1{font-size:20px;margin:0;white-space:nowrap}.sub{color:var(--muted);font-size:12px}
.page-nav{display:flex;align-items:center;gap:4px;margin-left:auto;overflow-x:auto}
.page-nav a{display:block;padding:5px 8px;border-radius:7px;color:var(--muted);text-decoration:none;font-size:11px;font-weight:700;white-space:nowrap}
.page-nav a:hover{background:#23282d;color:var(--text)}
.page-section{scroll-margin-top:108px}
.section-stack{margin-top:16px}
.content-frame{width:960px;max-width:100%;margin-left:auto;margin-right:auto}
.dashboard-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.dashboard-card{min-height:250px;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px}
.dashboard-placeholder{height:190px;border:1px dashed #3b4249;border-radius:9px;display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:11px;background:#14171a}
.world-map-panel{height:390px;min-height:390px;max-height:390px}
.world-map-placeholder{height:320px;border:1px dashed #3b4249;border-radius:9px;display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:11px;background:#14171a}
.page-bottom-space{height:max(24px,calc(100vh - 108px - 390px));}
main{max-width:none;margin:0;padding:108px calc(clamp(320px,28vw,430px) + 44px) 22px 22px}
.grid{display:block}
.left-column{display:grid;grid-template-rows:150px minmax(0,1fr);gap:12px;min-height:0}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;margin-bottom:0}
.discovery-panel{min-height:0;overflow:hidden}
.discovery-list{height:98px;overflow-y:auto;border:1px solid var(--line);border-radius:8px;background:#14171a}
.discovery-item{display:flex;align-items:center;gap:10px;padding:6px 10px;cursor:pointer;min-height:30px;white-space:nowrap;overflow:hidden}
.discovery-item:hover{background:#20252a}
.discovery-time{flex:0 0 auto;color:var(--muted);font-size:10px;font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
.discovery-story{min-width:0;overflow:hidden;text-overflow:ellipsis;font-size:11px}
.discovery-story strong{color:var(--text);font-weight:800}
.product-list-panel{height:620px;min-height:620px;max-height:620px;display:flex;flex-direction:column}
.detail-shell{position:fixed;top:108px;right:22px;bottom:14px;width:clamp(320px,28vw,430px);z-index:850}
.detail-panel{height:100%;min-height:0;display:flex;flex-direction:column;box-shadow:0 12px 30px rgba(0,0,0,.25)}
.product-list-panel .table-wrap{flex:1;max-height:none;min-height:0;overflow:auto}
.detail-panel #detail{flex:1;min-height:0;overflow-y:auto;padding-right:4px}
h2{font-size:17px;margin:0 0 14px}
.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px}
.toolbar h2{margin:0;flex:1}
input,button{font:inherit}
input{width:100%;background:#111418;color:var(--text);border:1px solid #343b43;border-radius:8px;padding:9px 10px}
button{border:0;border-radius:8px;padding:9px 13px;background:var(--accent);color:#18130c;font-weight:700;cursor:pointer}
button.secondary{background:#2a3036;color:var(--text)}
.account-hub{width:100%;height:47px;display:grid;grid-template-columns:minmax(220px,1.05fr) auto minmax(280px,1fr);gap:10px;align-items:center;padding:4px 22px;background:#15181b;color:var(--text);border-bottom:1px solid var(--line);overflow:hidden}
.account-hub-user{display:flex;align-items:center;gap:8px;min-width:0}
.account-hub-avatar{width:28px;height:28px;border-radius:50%;object-fit:cover;background:#111418;border:1px solid var(--line);flex:0 0 auto}
.account-hub-user-copy{min-width:0;display:flex;align-items:center;gap:8px}.account-hub-name-row{display:flex;align-items:center;gap:6px;min-width:0}.account-hub-name{font-size:13px;font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.account-hub-you{display:inline-block;padding:1px 5px;border-radius:999px;background:#2a3036;color:var(--muted);font-size:8px;font-weight:800;letter-spacing:.04em;text-transform:uppercase}
.account-hub-location{font-size:9px;color:var(--muted);margin:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.account-hub-guest-title{font-size:12px;font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.account-hub-guest-copy{display:none}.account-hub-guest-mark{width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:#24201a;border:1px solid #4b402e;color:var(--accent);font-size:13px;font-weight:800;flex:0 0 auto}
.account-hub-summary{display:flex;align-items:center;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:#14171a;height:30px}
.account-hub-stat{min-width:68px;padding:3px 8px;text-align:center;border-right:1px solid var(--line);white-space:nowrap}.account-hub-stat:last-child{border-right:0}.account-hub-stat-value{display:inline;font-size:12px;font-weight:800;line-height:1}.account-hub-stat-label{display:inline;margin-left:4px;color:var(--muted);font-size:8px;white-space:nowrap}
.account-hub-actions{display:flex;justify-content:flex-end;gap:5px;flex-wrap:nowrap;min-width:0}.account-hub-action{display:flex;align-items:center;gap:5px;padding:4px 7px;border-radius:8px;background:#252a2f;color:var(--text);font-size:11px;font-weight:700}.account-hub-action:hover{background:#30363c}.account-hub-action.primary{background:var(--accent);color:#18130c}.account-hub-count{min-width:17px;height:17px;padding:0 5px;border-radius:999px;background:#3b4147;color:var(--text);font-size:9px;line-height:17px;text-align:center}.account-hub-empty{color:var(--muted);font-size:12px}
.notification-panel{display:none;margin:-8px 0 18px;background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.notification-panel.open{display:block}
.notification-panel-head{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:11px 14px;border-bottom:1px solid var(--line)}
.notification-panel-title{font-size:13px;font-weight:800}.notification-panel-actions{display:flex;gap:6px}.notification-panel-actions button{padding:5px 8px;font-size:10px;background:#252a2f;color:var(--text)}
.notification-list{max-height:300px;overflow-y:auto}.notification-item{display:block;width:100%;text-align:left;border:0;border-bottom:1px solid var(--line);border-radius:0;background:#171a1e;color:var(--text);padding:11px 14px}.notification-item:last-child{border-bottom:0}.notification-item:hover{background:#20252a}.notification-item.unread{background:#1d211e}.notification-item-title{font-size:11px;font-weight:800}.notification-item-body{font-size:11px;color:var(--muted);margin-top:3px}.notification-item-time{font-size:9px;color:#737d86;margin-top:4px}.notification-empty{padding:18px 14px;color:var(--muted);font-size:11px;text-align:center}
@media(max-width:1050px){.account-hub{grid-template-columns:minmax(230px,1fr) auto}.account-hub-actions{grid-column:1/-1;justify-content:flex-start}}
@media(max-width:650px){.account-hub{grid-template-columns:1fr}.account-hub-summary{width:100%}.account-hub-stat{flex:1;min-width:0}.account-hub-actions{grid-column:auto}}
.table-wrap{max-height:620px;overflow:auto;border:1px solid var(--line);border-radius:8px}
table{width:100%;border-collapse:collapse;font-size:11px;table-layout:fixed}
th,td{text-align:left;border-bottom:1px solid var(--line);padding:5px 7px;vertical-align:middle;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;height:28px}
th{color:var(--muted);font-weight:600;position:sticky;top:0;background:var(--panel);z-index:2}
.product-list-panel th:nth-child(1),.product-list-panel td:nth-child(1){width:52px}
.product-list-panel th:nth-child(2),.product-list-panel td:nth-child(2){width:120px}
.product-list-panel th:nth-child(3),.product-list-panel td:nth-child(3){width:190px}
.product-list-panel th:nth-child(4),.product-list-panel td:nth-child(4){width:120px}
.product-list-panel th:nth-child(5),.product-list-panel td:nth-child(5){width:72px}
.product-list-panel th:nth-child(6),.product-list-panel td:nth-child(6){width:145px}
.product-list-panel th:nth-child(7),.product-list-panel td:nth-child(7){width:64px}
th.sortable{cursor:pointer;user-select:none}.sort-indicator{font-size:10px;margin-left:4px}
.clickable{cursor:pointer}.clickable:hover{background:#20252a}.clickable.selected{background:#3a3326}.clickable.selected:hover{background:#463c2c}
.mono{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
.status{display:inline-block;padding:3px 7px;border-radius:999px;font-size:11px;background:#2b3035}.good{color:var(--good)}
.detail-image{display:block;width:75%;max-height:270px;object-fit:contain;background:#111418;border:1px solid var(--line);border-radius:8px}
.detail-image-link{display:block;margin:0 0 6px}
.detail-gallery{display:grid;grid-template-columns:20px minmax(0,1fr) 20px;align-items:center;gap:5px;width:75%;margin:0 0 6px}
.detail-gallery .detail-image{width:100%;min-width:0}
.detail-gallery-nav{width:20px;min-width:20px;height:28px;padding:0;border-radius:5px;background:#20252a;color:#777f87;font-size:11px;font-weight:600;line-height:1}
.detail-gallery-nav:hover{background:#272d32;color:#a8b0b7}
.detail-gallery-nav:disabled{opacity:.18;cursor:default}
.detail-source{display:block;margin:0 0 14px;color:var(--muted);font-size:11px}.detail-source a{color:var(--muted)}
.detail-header{margin:0 0 16px}.detail-header-title{font-size:16px;font-weight:700;margin-bottom:6px}.current-owner-line{font-size:13px;margin-bottom:10px}.catalog-spec{font-size:13px;line-height:1.7}.catalog-spec-row{overflow-wrap:anywhere}.catalog-spec-label{font-weight:700}.catalog-spec-empty{color:var(--muted)}
.detail-meta-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.detail-meta-item{background:#14171a;border:1px solid var(--line);border-radius:8px;padding:9px 10px;min-width:0}
.detail-meta-label{display:block;color:var(--muted);font-size:10px;margin-bottom:2px}
.detail-meta-value{display:block;color:var(--text);font-size:12px;overflow-wrap:anywhere}.detail-meta-value a{color:var(--text)}
.detail-section{margin:18px 0 8px;font-size:13px;font-weight:700;border-bottom:1px solid var(--line);padding-bottom:6px}
.observation-card{border:1px solid var(--line);border-radius:10px;background:#14171a;padding:12px 13px;margin:0 0 10px}
.observation-card.latest{border-color:#5c513d;background:#181713}
.observation-card-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:8px}
.observation-date{font-weight:700}.observation-source{font-size:11px;color:var(--muted);white-space:nowrap}.observation-source a{color:var(--muted)}
.observation-row{display:grid;grid-template-columns:78px minmax(0,1fr);gap:8px;margin:4px 0}
.observation-label{color:var(--muted);font-size:11px}.observation-value{min-width:0;overflow-wrap:anywhere}.observation-title{font-weight:600}
#detail{white-space:normal}
.chronicle-toolbar{display:flex;justify-content:space-between;align-items:center;gap:10px;margin:18px 0 10px;border-bottom:1px solid var(--line);padding-bottom:8px}
.chronicle-toolbar select{width:auto;min-width:130px}
.claim-card{border:1px solid #4a4337;border-radius:10px;background:#171612;padding:12px 13px;margin:8px 0 12px 22px}
.claim-card.claim-type-ownership{background:#101d16;border-color:#294b37}
.claim-card.claim-type-specification{background:#101820;border-color:#29465d}
.claim-card.claim-type-incident{background:#211111;border-color:#5a2c2c}
.claim-card.claim-type-event{background:#1b1422;border-color:#4d3560}
.claim-card.claim-type-media{background:#21190d;border-color:#5b4724}
.claim-card.claim-type-ownership .claim-badge{background:#4f9a68;color:#08110b}
.claim-card.claim-type-specification .claim-badge{background:#4d88b8;color:#071018}
.claim-card.claim-type-incident .claim-badge{background:#b85a5a;color:#160808}
.claim-card.claim-type-event .claim-badge{background:#9360b8;color:#120917}
.claim-card.claim-type-media .claim-badge{background:#c68a32;color:#171006}.identity-correction-card{margin-left:42px;border-style:dashed}
.claim-head{display:flex;align-items:center;gap:8px;margin-bottom:10px}.claim-event-date{margin-left:auto;text-align:right}
.claim-badge{display:inline-block;padding:3px 7px;border-radius:999px;background:var(--accent);color:#18130c;font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:.03em}
.claim-event-date{font-size:11px;color:var(--muted);white-space:nowrap}
.claim-body{font-size:12px;line-height:1.5}
.claim-memo{margin-top:8px;white-space:pre-wrap}.claim-card img.claim-evidence-image{display:block!important;width:48px!important;height:48px!important;max-width:48px!important;max-height:48px!important;object-fit:cover;border:1px solid var(--line);border-radius:6px;margin-top:6px}.claim-media-thumbs{display:flex;gap:6px;flex-wrap:wrap;margin-top:7px}.claim-media-thumbs img{display:block!important;width:48px!important;height:48px!important;max-width:48px!important;max-height:48px!important;object-fit:cover;border:1px solid var(--line);border-radius:6px}.claim-card img.claim-media-image{display:block;width:min(320px,100%);height:auto;max-height:240px;object-fit:contain;border:1px solid var(--line);border-radius:8px;margin-top:8px;background:#0f1114}
.claim-footer{margin-top:10px;padding-top:8px;border-top:1px solid var(--line);font-size:9px;color:var(--muted);display:flex;align-items:center;justify-content:space-between;gap:10px}.claim-footer-meta{text-align:right}.claim-votes{display:flex;gap:6px}.claim-vote{padding:4px 7px;border-radius:999px;background:#252a2f;color:var(--text);font-size:10px;min-width:54px}.claim-vote.active{outline:1px solid var(--accent)}.claim-response-select{width:auto;min-width:108px;padding:4px 7px;font-size:11px}
#chronicleEntries{padding-right:6px}
.accordion-section{margin-top:10px}
.accordion-header{display:flex;align-items:center;gap:8px;margin:18px 0 10px;border-bottom:1px solid var(--line);padding-bottom:8px}
.accordion-toggle{width:24px;height:24px;min-width:24px;padding:0;border-radius:6px;background:#252a2f;color:var(--text);font-size:12px;line-height:24px;text-align:center}
.accordion-title{font-weight:700;cursor:pointer}
.accordion-header .toolbar{margin:0 0 0 auto}
.accordion-body{display:block}
.accordion-section.collapsed .accordion-body{display:none}
.accordion-section.collapsed .accordion-toggle{transform:rotate(-90deg)}
.claim-card{position:relative}
.claim-card:not(:last-child)::after{content:"";position:absolute;left:50%;top:100%;width:1px;height:12px;background:#4c5258;pointer-events:none;transform:translateX(-.5px)}
.modal-backdrop{display:none;position:fixed;inset:0;background:rgba(0,0,0,.68);align-items:center;justify-content:center;z-index:1000;padding:16px}.modal-backdrop.open{display:flex}.modal{width:min(560px,100%);background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px;box-shadow:0 18px 60px rgba(0,0,0,.45)}.modal textarea{width:100%;min-height:110px;background:#111418;color:var(--text);border:1px solid #343b43;border-radius:8px;padding:9px 10px;font:inherit;resize:vertical}.form-row{margin-bottom:12px}.form-label{display:block;color:var(--muted);font-size:11px;margin-bottom:4px}.modal-actions{display:flex;gap:8px;justify-content:flex-end;margin-top:16px}
@media(max-width:900px){.grid{grid-template-columns:1fr}}
@media(max-width:520px){.detail-meta-grid{grid-template-columns:1fr}}

.claim-menu-wrap{position:relative;display:inline-block}.claim-menu{display:none;position:absolute;right:0;top:calc(100% + 6px);min-width:190px;background:#1c2024;border:1px solid var(--line);border-radius:9px;padding:6px;z-index:40;box-shadow:0 12px 32px rgba(0,0,0,.38)}.claim-menu.open{display:block}.claim-menu button{display:block;width:100%;text-align:left;background:transparent;color:var(--text);padding:8px 10px}.claim-menu button:hover{background:#2a3036}
.modal-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.form-row{margin-bottom:12px}.form-row.full{grid-column:1/-1}.form-label{display:block;color:var(--muted);font-size:11px;margin-bottom:4px}.modal textarea{width:100%;min-height:90px;background:#111418;color:var(--text);border:1px solid #343b43;border-radius:8px;padding:9px 10px;font:inherit;resize:vertical}
.spec-kind{display:flex;gap:6px;margin-bottom:14px}.spec-kind button{background:#2a3036;color:var(--text)}.spec-kind button.active{background:var(--accent);color:#18130c}.spec-add-wrap{position:relative;display:inline-block}.spec-add-button{font-size:18px;line-height:1;padding:7px 11px}.spec-item-menu{left:0;right:auto;min-width:220px;max-height:270px;overflow:auto}.spec-items{display:flex;flex-direction:column;gap:8px;margin:10px 0 14px}.spec-scroll-modal{max-height:calc(100vh - 32px);max-height:calc(100dvh - 32px);overflow-y:auto;overscroll-behavior:contain}.spec-item-row{display:grid;grid-template-columns:minmax(110px,.7fr) minmax(0,1.5fr) 34px;gap:8px;align-items:center}.spec-item-label{font-size:12px;color:var(--muted)}.spec-item-remove{padding:7px;background:#3a2626;color:#f0b3b3}.media-image-inputs{display:flex;flex-direction:column;gap:7px;max-height:220px;overflow-y:auto;padding-right:4px}.media-image-slot{display:none}.media-image-slot.visible{display:block}.media-image-slot input{font-size:11px;padding:7px 8px}@media(max-width:560px){.modal-grid{grid-template-columns:1fr}.form-row.full{grid-column:auto}}

.claim-compact-row{display:flex;justify-content:center;align-items:center;min-height:24px;margin:2px 0 4px 22px;position:relative}
.claim-compact-row:not(:last-child)::after{content:"";position:absolute;left:50%;top:100%;width:1px;height:6px;background:#4c5258;pointer-events:none;transform:translateX(-.5px)}
.claim-compact-tag{border:0;border-radius:999px;padding:4px 9px;font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:.03em;cursor:pointer;background:#3a3f45;color:var(--text)}
.claim-compact-tag.claim-type-ownership{background:#4f9a68;color:#08110b}
.claim-compact-tag.claim-type-specification{background:#4d88b8;color:#071018}
.claim-compact-tag.claim-type-incident{background:#b85a5a;color:#160808}
.claim-compact-tag.claim-type-event{background:#9360b8;color:#120917}
.claim-compact-tag.claim-type-media{background:#c68a32;color:#171006}
.claim-negative-dot{border:0;background:transparent!important;color:#737a81!important;padding:0 4px;font-size:20px;line-height:1;cursor:pointer}
.claim-negative-dot:hover{color:#a0a7ae!important}
.claim-popup-modal{position:fixed;width:auto;background:transparent;border:0;padding:0;box-shadow:none;z-index:1001}
.claim-popup-modal .claim-card{margin:0}.claim-popup-modal .claim-card::after{display:none}
#claimPopupModal{background:transparent;align-items:initial;justify-content:initial;padding:0}
@media(max-width:900px){
  .sticky-header{position:static}
  header{align-items:flex-start;flex-direction:column;gap:6px}
  .page-nav{margin-left:0;width:100%}
  .account-hub{grid-template-columns:1fr;gap:8px;height:auto}
  main{padding:14px 14px 22px}
  .left-column{grid-template-rows:150px 520px}
  .product-list-panel{height:520px}
  .detail-shell{position:static;width:auto;height:520px;margin-top:14px}
  .detail-panel{height:100%}
  .content-frame{width:100%;max-width:none}
  .dashboard-grid{grid-template-columns:1fr}
  .page-bottom-space{height:24px}
  .page-section{scroll-margin-top:12px}
}
</style>
</head>
<body>
<div class="sticky-header">
  <header>
    <h1>Your Guitar Chronicle <span class="sub">Top Page</span></h1>
    <nav class="page-nav" aria-label="Top Page sections">
      <a href="#discovery">New Discovery</a>
      <a href="#products">Products</a>
      <a href="#statistics">Statistics</a>
      <a href="#world-map">World Map</a>
    </nav>
  </header>
  <div class="account-hub" id="accountHub">
    <div class="account-hub-empty">User情報を読み込み中...</div>
  </div>
</div>
<main>
<div class="notification-panel" id="notificationPanel">
  <div class="notification-panel-head">
    <span class="notification-panel-title">Notifications</span>
    <div class="notification-panel-actions">
      <button type="button" onclick="markAllNotificationsRead()">Mark all read</button>
    </div>
  </div>
  <div class="notification-list" id="notificationList"></div>
</div>

<div class="grid">
<section class="left-column content-frame">
  <div class="panel discovery-panel page-section" id="discovery">
    <div class="toolbar"><h2>New discovery</h2></div>
    <div class="discovery-list" id="newDiscoveryList"><div class="sub" style="padding:8px">最近の更新を読み込み中...</div></div>
  </div>
  <div class="panel product-list-panel page-section" id="products">
    <div class="toolbar">
      <h2>Product List</h2>
      <input id="individualFilter" style="max-width:320px" placeholder="maker / model / finish / year / serial" oninput="renderIndividuals()">
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th class="sortable" onclick="setIndividualSort('id')">ID<span class="sort-indicator" id="sort-id"></span></th>
          <th class="sortable" onclick="setIndividualSort('manufacturer')">Maker<span class="sort-indicator" id="sort-manufacturer"></span></th>
          <th class="sortable" onclick="setIndividualSort('model')">Model<span class="sort-indicator" id="sort-model"></span></th>
          <th class="sortable" onclick="setIndividualSort('finish')">Finish<span class="sort-indicator" id="sort-finish"></span></th>
          <th class="sortable" onclick="setIndividualSort('year')">Year<span class="sort-indicator" id="sort-year"></span></th>
          <th class="sortable" onclick="setIndividualSort('serial_number')">Serial<span class="sort-indicator" id="sort-serial_number"></span></th>
          <th class="sortable" onclick="setIndividualSort('claim_count')">Claims<span class="sort-indicator" id="sort-claim_count"></span></th>
        </tr></thead>
        <tbody id="individualBody"></tbody>
      </table>
    </div>
  </div>
</section>

</div>

<aside class="detail-shell">
  <div class="panel detail-panel">
    <h2>Product Detail</h2>
    <div id="detail" class="sub">Product List の行をクリックすると履歴を表示します。</div>
  </div>
</aside>

<section class="section-stack page-section content-frame" id="statistics">
  <div class="toolbar"><h2>Statistics</h2></div>
  <div class="dashboard-grid">
    <div class="dashboard-card">
      <h2>Maker Distribution</h2>
      <div class="dashboard-placeholder">Chart placeholder</div>
    </div>
    <div class="dashboard-card">
      <h2>Decade Distribution</h2>
      <div class="dashboard-placeholder">Chart placeholder</div>
    </div>
    <div class="dashboard-card">
      <h2>Top Models</h2>
      <div class="dashboard-placeholder">Chart placeholder</div>
    </div>
    <div class="dashboard-card">
      <h2>Claim Activity</h2>
      <div class="dashboard-placeholder">Chart placeholder</div>
    </div>
  </div>
</section>

<section class="section-stack page-section content-frame" id="world-map">
  <div class="panel world-map-panel">
    <h2>World Map</h2>
    <div class="world-map-placeholder">World heat map placeholder</div>
  </div>
</section>
<div class="page-bottom-space" aria-hidden="true"></div>
</main>

<div class="modal-backdrop" id="mediaClaimModal" onclick="closeMediaClaim(event)">
  <div class="modal" onclick="event.stopPropagation()">
    <h2>Media Claim</h2>
    <div class="sub" id="mediaClaimGuitar" style="margin-bottom:14px"></div>
    <div class="modal-grid">
      <div class="form-row full">
        <label class="form-label">Images <span class="sub">最大10枚</span></label>
        <div class="media-image-inputs" id="mediaClaimImages"><div class="media-image-slot visible" id="mediaImageSlot0"><input class="media-image-input" data-index="0" type="file" accept="image/jpeg,image/png,image/webp,image/gif" onchange="updateMediaImageSlots()"></div><div class="media-image-slot" id="mediaImageSlot1"><input class="media-image-input" data-index="1" type="file" accept="image/jpeg,image/png,image/webp,image/gif" onchange="updateMediaImageSlots()"></div><div class="media-image-slot" id="mediaImageSlot2"><input class="media-image-input" data-index="2" type="file" accept="image/jpeg,image/png,image/webp,image/gif" onchange="updateMediaImageSlots()"></div><div class="media-image-slot" id="mediaImageSlot3"><input class="media-image-input" data-index="3" type="file" accept="image/jpeg,image/png,image/webp,image/gif" onchange="updateMediaImageSlots()"></div><div class="media-image-slot" id="mediaImageSlot4"><input class="media-image-input" data-index="4" type="file" accept="image/jpeg,image/png,image/webp,image/gif" onchange="updateMediaImageSlots()"></div><div class="media-image-slot" id="mediaImageSlot5"><input class="media-image-input" data-index="5" type="file" accept="image/jpeg,image/png,image/webp,image/gif" onchange="updateMediaImageSlots()"></div><div class="media-image-slot" id="mediaImageSlot6"><input class="media-image-input" data-index="6" type="file" accept="image/jpeg,image/png,image/webp,image/gif" onchange="updateMediaImageSlots()"></div><div class="media-image-slot" id="mediaImageSlot7"><input class="media-image-input" data-index="7" type="file" accept="image/jpeg,image/png,image/webp,image/gif" onchange="updateMediaImageSlots()"></div><div class="media-image-slot" id="mediaImageSlot8"><input class="media-image-input" data-index="8" type="file" accept="image/jpeg,image/png,image/webp,image/gif" onchange="updateMediaImageSlots()"></div><div class="media-image-slot" id="mediaImageSlot9"><input class="media-image-input" data-index="9" type="file" accept="image/jpeg,image/png,image/webp,image/gif" onchange="updateMediaImageSlots()"></div></div>
      </div>
      <div class="form-row">
        <label class="form-label" for="mediaClaimDate">Date</label>
        <input id="mediaClaimDate" type="date">
      </div>
      <div class="form-row full">
        <label class="form-label" for="mediaClaimCaption">Caption</label>
        <textarea id="mediaClaimCaption" maxlength="2000" placeholder="Caption or detail"></textarea>
      </div>
    </div>
    <div class="modal-actions">
      <button class="secondary" onclick="closeMediaClaim()">キャンセル</button>
      <button id="mediaClaimSubmit" onclick="submitMediaClaim()">Claimを追加</button>
    </div>
  </div>
</div>

<div class="modal-backdrop" id="eventClaimModal" onclick="closeEventClaim(event)">
  <div class="modal" onclick="event.stopPropagation()">
    <h2>Event Claim</h2>
    <div class="sub" id="eventClaimGuitar" style="margin-bottom:14px"></div>
    <div class="modal-grid">
      <div class="form-row">
        <label class="form-label" for="eventClaimKind">Tag</label>
        <select id="eventClaimKind">
          <option value="exhibition">Exhibition</option>
          <option value="performance">Performance</option>
          <option value="recording">Recording</option>
          <option value="auction">Auction</option>
          <option value="other">Other</option>
        </select>
      </div>
      <div class="form-row">
        <label class="form-label" for="eventClaimDate">Date</label>
        <input id="eventClaimDate" type="date">
      </div>
      <div class="form-row full">
        <label class="form-label" for="eventClaimDetail">Detail</label>
        <textarea id="eventClaimDetail" maxlength="2000" placeholder="What happened?"></textarea>
      </div>
    </div>
    <div class="modal-actions">
      <button class="secondary" onclick="closeEventClaim()">キャンセル</button>
      <button id="eventClaimSubmit" onclick="submitEventClaim()">Claimを追加</button>
    </div>
  </div>
</div>

<div class="modal-backdrop" id="incidentClaimModal" onclick="closeIncidentClaim(event)">
  <div class="modal" onclick="event.stopPropagation()">
    <h2>Incident Claim</h2>
    <div class="sub" id="incidentClaimGuitar" style="margin-bottom:14px"></div>
    <div class="modal-grid">
      <div class="form-row">
        <label class="form-label" for="incidentClaimKind">Tag</label>
        <select id="incidentClaimKind">
          <option value="damage">Damage</option>
          <option value="lost">Lost</option>
          <option value="theft">Theft</option>
        </select>
      </div>
      <div class="form-row">
        <label class="form-label" for="incidentClaimDate">Date</label>
        <input id="incidentClaimDate" type="date">
      </div>
      <div class="form-row full">
        <label class="form-label" for="incidentClaimDetail">Detail</label>
        <textarea id="incidentClaimDetail" maxlength="2000" placeholder="What happened?"></textarea>
      </div>
    </div>
    <div class="modal-actions">
      <button class="secondary" onclick="closeIncidentClaim()">キャンセル</button>
      <button id="incidentClaimSubmit" onclick="submitIncidentClaim()">Claimを追加</button>
    </div>
  </div>
</div>

<div class="modal-backdrop" id="specClaimModal" onclick="closeSpecificationClaim(event)">
  <div class="modal spec-scroll-modal" onclick="event.stopPropagation()">
    <h2 id="specClaimTitle">Specification/Repair Claim</h2>
    <div class="sub" id="specClaimGuitar" style="margin-bottom:14px"></div>

    <div class="spec-kind">
      <button id="specKindSpecification" type="button" class="active" onclick="setSpecificationKind('specification')">Specification</button>
      <button id="specKindRepair" type="button" onclick="setSpecificationKind('repair')">Repair</button>
    </div>

    <div class="spec-add-wrap">
      <button type="button" class="spec-add-button" onclick="toggleSpecItemMenu(event)">＋</button>
      <div class="claim-menu spec-item-menu" id="specItemMenu"></div>
    </div>
    <span class="sub" style="margin-left:8px">項目を追加</span>

    <div class="spec-items" id="specClaimItems"></div>

    <div class="modal-grid">
      <div class="form-row">
        <label class="form-label" for="specClaimDate">Date</label>
        <input id="specClaimDate" type="date">
      </div>
      <div class="form-row full">
        <label class="form-label" for="specClaimBody">Memo（任意）</label>
        <textarea id="specClaimBody" maxlength="2000" placeholder="仕様、交換、調整、修理内容などの補足"></textarea>
      </div>
    </div>

    <div class="sub">追加した各項目は、この1件のClaimとして保存されます。Specificationには各項目の最新値が表示されます。</div>
    <div class="modal-actions">
      <button class="secondary" onclick="closeSpecificationClaim()">キャンセル</button>
      <button id="specClaimSubmit" onclick="submitSpecificationClaim()">Claimを追加</button>
    </div>
  </div>
</div>

<div class="modal-backdrop" id="formerOwnerClaimModal" onclick="closeFormerOwnerClaim(event)">
  <div class="modal" onclick="event.stopPropagation()" onkeydown="if(event.key==='Enter'&&event.target.tagName!=='TEXTAREA'){event.preventDefault();submitFormerOwnerClaim()}">
    <h2>Former Owner</h2>
    <div class="sub" id="formerOwnerClaimGuitar" style="margin-bottom:14px"></div>
    <div class="modal-grid">
      <div class="form-row">
        <label class="form-label" for="formerOwnerAcquisitionDate">Acquisition Date *</label>
        <input id="formerOwnerAcquisitionDate" type="date" required>
      </div>
      <div class="form-row">
        <label class="form-label" for="formerOwnerReleaseDate">Release Date *</label>
        <input id="formerOwnerReleaseDate" type="date" required>
      </div>
      <div class="form-row full">
        <label class="form-label" for="formerOwnerDetail">Detail（任意）</label>
        <textarea id="formerOwnerDetail" maxlength="2000" placeholder="Ownership history detail"></textarea>
      </div>
    </div>
    <div class="sub">Acquire / Release Claimを2件作成し、このUserのFormerly Owned Guitarsへ追加します。</div>
    <div class="modal-actions">
      <button class="secondary" onclick="closeFormerOwnerClaim()">キャンセル</button>
      <button id="formerOwnerClaimSubmit" onclick="submitFormerOwnerClaim()">Add Claims</button>
    </div>
  </div>
</div>

<div class="modal-backdrop" id="ownershipClaimModal" onclick="closeOwnershipClaim(event)">
  <div class="modal" onclick="event.stopPropagation()">
    <h2>Ownership</h2>
    <div class="sub" id="ownershipClaimGuitar" style="margin-bottom:14px"></div>
    <div class="form-row">
      <label class="form-label">Tag</label>
      <div id="ownershipClaimFixedTag"><strong>Acquire</strong></div>
      <select id="ownershipClaimKind" style="display:none">
        <option value="acquire">Acquire</option>
        <option value="transfer">Transfer</option>
        <option value="inherit">Inherit</option>
        <option value="release">Release</option>
      </select>
    </div>
    <div class="form-row">
      <label class="form-label" for="ownershipClaimDate">Date</label>
      <input id="ownershipClaimDate" type="date">
    </div>
    <div class="form-row" id="ownershipClaimPreviousRow">
      <label class="form-label" for="ownershipClaimPrevious">相手先・関係者（任意）</label>
      <input id="ownershipClaimPrevious" placeholder="Former owner / Recipient / Family ...">
    </div>
    <div class="form-row">
      <label class="form-label" for="ownershipClaimBody">Memo（任意）</label>
      <textarea id="ownershipClaimBody" maxlength="2000" placeholder="Ownershipに関する補足"></textarea>
    </div>
    <div class="modal-actions">
      <button class="secondary" onclick="closeOwnershipClaim()">キャンセル</button>
      <button id="ownershipClaimSubmit" onclick="submitOwnershipClaim()">Claimを追加</button>
    </div>
  </div>
</div>

<div class="modal-backdrop" id="accountRequiredModal" onclick="closeAccountRequired(event)">
  <div class="modal" onclick="event.stopPropagation()">
    <h2>Join Your Guitar Chronicle</h2>
    <div class="sub" style="margin-bottom:14px">この操作にはアカウントが必要です。既存アカウントでログインするか、新しいアカウントを作成してください。</div>
    <div class="modal-actions">
      <button class="secondary" type="button" onclick="closeAccountRequired()">キャンセル</button>
      <button class="secondary" type="button" onclick="window.location.href='/user-view/edit'">Sign In</button>
      <button type="button" onclick="window.location.href='/user-view/edit'">Create Account</button>
    </div>
  </div>
</div>

<div class="modal-backdrop" id="claimPopupModal" onclick="closeClaimPopup(event)">
  <div class="claim-popup-modal" onclick="event.stopPropagation()">
    <div id="claimPopupContent"></div>
  </div>
</div>

<script>
let individuals=[];
let newDiscoveries=[];
let activeUser=null;
let selectedIndividualId=null;
let productGallery=[];
let productGalleryIndex=0;
let currentObservations=[];
let currentClaims=[];
let chronicleSort='event';
let notificationData={unread_count:0,notifications:[]};
let pendingOwnershipClaimIndividualId=null;
let ownershipClaimMode='acquire';
let individualSortKey='id';
let individualSortDirection=1;
const ACTIVE_USER_KEY='ygc_active_user_id';

const esc=s=>String(s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[m]));
async function jfetch(url,opt={}){
  const r=await fetch(url,opt);
  const d=await r.json().catch(()=>({}));
  if(!r.ok)throw new Error(d.detail||r.statusText);
  return d;
}
function renderAccountHub(){
  const hub=document.getElementById('accountHub');
  if(!hub)return;
  if(!activeUser||!activeUser.user){
    hub.innerHTML=
      '<div class="account-hub-user">'+
        '<div class="account-hub-guest-mark">YGC</div>'+
        '<div class="account-hub-user-copy">'+
          '<div class="account-hub-guest-title">Explore guitar histories. Add yours when you are ready.</div>'+
          '<div class="account-hub-guest-copy">Product ListとChronicleはGuestでも閲覧できます。自分に関係するギターを見つけたら、アカウントを作成してその履歴に参加できます。</div>'+
        '</div>'+
      '</div>'+
      '<div></div>'+
      '<div class="account-hub-actions">'+
        '<button class="account-hub-action" type="button" onclick="window.location.href=\'/user-view/edit\'">Sign In</button>'+
        '<button class="account-hub-action primary" type="button" onclick="window.location.href=\'/user-view/edit\'">Create Account</button>'+
      '</div>';
    return;
  }
  const u=activeUser.user;
  const summary=activeUser.summary||{};
  const guitars=activeUser.guitars||[];
  const owned=summary.owned_count??guitars.filter(g=>g.ownership_status==='current_owner').length;
  const former=summary.former_count??guitars.filter(g=>g.ownership_status==='former_owner').length;
  const claims=summary.claim_count??0;
  const location=[u.location_country,u.location_region].filter(Boolean).join(' / ')||'Location not set';
  hub.innerHTML=
    '<div class="account-hub-user">'+
      '<img class="account-hub-avatar" src="/api/users/'+u.id+'/avatar?v='+encodeURIComponent(u.updated_at||'')+'" alt="'+esc(u.display_name||'User')+'" onerror="this.onerror=null;this.src=\'/assets/no-icon.svg\'">'+
      '<div class="account-hub-user-copy">'+
        '<div class="account-hub-name-row"><span class="account-hub-name">'+esc(u.display_name||'User')+'</span><span class="account-hub-you">You</span></div>'+
        '<div class="account-hub-location">'+esc(location)+'</div>'+
      '</div>'+
    '</div>'+
    '<div class="account-hub-summary">'+
      '<div class="account-hub-stat"><span class="account-hub-stat-value">'+owned+'</span><span class="account-hub-stat-label">Owned</span></div>'+
      '<div class="account-hub-stat"><span class="account-hub-stat-value">'+former+'</span><span class="account-hub-stat-label">Formerly Owned</span></div>'+
      '<div class="account-hub-stat"><span class="account-hub-stat-value">'+claims+'</span><span class="account-hub-stat-label">Claims</span></div>'+
    '</div>'+
    '<div class="account-hub-actions">'+
      '<button class="account-hub-action" type="button" onclick="toggleNotifications()">Notifications <span class="account-hub-count" id="notificationCount">'+Number(notificationData.unread_count||0)+'</span></button>'+
      '<button class="account-hub-action" type="button">Messages <span class="account-hub-count">0</span></button>'+
      '<button class="account-hub-action" type="button" onclick="window.location.href=\'/users/'+u.id+'\'">View Profile</button>'+
      '<button class="account-hub-action primary" type="button" onclick="window.location.href=\'/user-view/edit\'">Edit Your Chronicle</button>'+
    '</div>';
}

function renderNotificationPanel(){
  const list=document.getElementById('notificationList');
  if(!list)return;
  const items=notificationData.notifications||[];
  list.innerHTML=items.length
    ? items.map(n=>
        '<button type="button" class="notification-item'+(Number(n.is_read)?'':' unread')+'" onclick="openNotification('+n.id+','+(n.individual_id===null?'null':Number(n.individual_id))+')">'+
          '<div class="notification-item-title">'+esc(n.title||'Notification')+'</div>'+
          '<div class="notification-item-body">'+esc(n.body||'')+'</div>'+
          '<div class="notification-item-time">'+esc(displayInputDate(n.created_at))+'</div>'+
        '</button>'
      ).join('')
    : '<div class="notification-empty">通知はありません。</div>';
  const count=document.getElementById('notificationCount');
  if(count)count.textContent=String(Number(notificationData.unread_count||0));
}
async function loadNotifications(){
  if(!activeUser||!activeUser.user){
    notificationData={unread_count:0,notifications:[]};
    renderNotificationPanel();
    return;
  }
  try{
    notificationData=await jfetch('/api/users/'+activeUser.user.id+'/notifications');
  }catch(e){
    notificationData={unread_count:0,notifications:[]};
  }
  renderNotificationPanel();
}
async function toggleNotifications(){
  const panel=document.getElementById('notificationPanel');
  if(!panel)return;
  if(!panel.classList.contains('open'))await loadNotifications();
  panel.classList.toggle('open');
}
async function openNotification(notificationId,individualId){
  if(!activeUser||!activeUser.user)return;
  try{
    await jfetch('/api/users/'+activeUser.user.id+'/notifications/'+notificationId+'/read',{method:'POST'});
  }catch(e){}
  const item=(notificationData.notifications||[]).find(n=>Number(n.id)===Number(notificationId));
  if(item)item.is_read=1;
  notificationData.unread_count=Math.max(0,Number(notificationData.unread_count||0)-(item&&Number(item.is_read)===0?1:0));
  await loadNotifications();
  const panel=document.getElementById('notificationPanel');
  if(panel)panel.classList.remove('open');
  if(individualId!==null&&individualId!==undefined)await showIndividual(Number(individualId));
}
async function markAllNotificationsRead(){
  if(!activeUser||!activeUser.user)return;
  try{
    await jfetch('/api/users/'+activeUser.user.id+'/notifications/read-all',{method:'POST'});
    await loadNotifications();
  }catch(e){
    alert('通知の既読化に失敗しました。\n'+e.message);
  }
}

async function loadActiveUser(){
  const id=localStorage.getItem(ACTIVE_USER_KEY);
  if(!id){
    activeUser=null;
    notificationData={unread_count:0,notifications:[]};
    renderAccountHub();
    renderNotificationPanel();
    return;
  }
  try{
    activeUser=await jfetch('/api/users/'+id);
  }catch(e){
    activeUser=null;
    localStorage.removeItem(ACTIVE_USER_KEY);
  }
  await loadNotifications();
  renderAccountHub();
  renderNotificationPanel();
}

async function loadNewDiscoveries(){
  try{
    newDiscoveries=await jfetch('/api/new-discoveries');
  }catch(e){
    newDiscoveries=[];
  }
  renderNewDiscoveries();
}
function discoveryMessage(item){
  return item.activity_type==='claim'
    ? 'has secured a new claim!'
    : 'has been newly added to the list!';
}
function discoveryProductName(item){
  const base=[item.manufacturer,item.model].filter(Boolean).join(' ').trim()||('Product #'+item.id);
  const year=item.year?' ('+item.year+')':'';
  const finish=item.finish?' '+item.finish:'';
  return base+year+finish;
}
function renderNewDiscoveries(){
  const root=document.getElementById('newDiscoveryList');
  if(!root)return;
  if(!newDiscoveries.length){
    root.innerHTML='<div class="sub" style="padding:10px">最近の更新はありません。</div>';
    return;
  }
  root.innerHTML=newDiscoveries.map(item=>{
    const when=displayDiscoveryDateTime(item.activity_at||'');
    const product=discoveryProductName(item);
    const message=discoveryMessage(item);
    return '<div class="discovery-item" onclick="showIndividual('+Number(item.id)+')" title="'+esc(when+' '+product+' '+message)+'">'+
      '<span class="discovery-time">'+esc(when)+'</span>'+
      '<span class="discovery-story"><strong>'+esc(product)+'</strong> '+esc(message)+'</span>'+
    '</div>';
  }).join('');
}

async function loadIndividuals(){
  individuals=await jfetch('/api/individuals');
  renderIndividuals();
}
function normalizeSortValue(value,key){
  if(key==='id'||key==='claim_count')return Number(value||0);
  return String(value??'').toLowerCase();
}
function setIndividualSort(key){
  if(individualSortKey===key)individualSortDirection*=-1;
  else{individualSortKey=key;individualSortDirection=1}
  renderIndividuals();
}
function updateSortIndicators(){
  for(const key of ['id','manufacturer','model','finish','year','serial_number','claim_count']){
    const el=document.getElementById('sort-'+key);
    if(el)el.textContent=individualSortKey===key?(individualSortDirection===1?'▲':'▼'):'';
  }
}
function renderIndividuals(){
  const q=document.getElementById('individualFilter').value.toLowerCase();
  const rows=individuals.filter(x=>[x.manufacturer,x.model,x.finish,x.year,x.serial_number].join(' ').toLowerCase().includes(q)).slice().sort((a,b)=>{
    const av=normalizeSortValue(a[individualSortKey],individualSortKey);
    const bv=normalizeSortValue(b[individualSortKey],individualSortKey);
    if(av<bv)return-1*individualSortDirection;
    if(av>bv)return 1*individualSortDirection;
    return Number(a.id)-Number(b.id);
  });
  updateSortIndicators();
  document.getElementById('individualBody').innerHTML=rows.map(x=>
    '<tr class="clickable'+(Number(x.id)===Number(selectedIndividualId)?' selected':'')+'" onclick="showIndividual('+x.id+')"><td>'+x.id+'</td><td>'+esc(x.manufacturer)+'</td><td>'+esc(x.model)+'</td><td>'+esc(x.finish||'')+'</td><td>'+esc(x.year||'')+'</td><td class="mono">'+esc(x.serial_number)+'</td><td>'+x.claim_count+'</td></tr>'
  ).join('');
}

function sourceName(o){return String(o.source_site||'').toLowerCase()==='reverb'?'Reverb':String(o.source_site||'Source')}
function ownerLabel(o){
  const name=String(o.owner_user_name||o.owner_name||o.seller||'').trim();
  if(!name)return '';
  const type=String(o.owner_type||'').trim();
  return type==='shop'?name+' (Shop)':(type==='user'?name+' (User)':name);
}
function currentOwnerHtml(o){
  if(!o)return '—';
  const name=String(o.owner_user_name||o.owner_name||o.seller||'').trim();
  if(!name)return '—';
  const type=String(o.owner_type||'').trim();
  const listingUrl=String(o.source_url||'').trim();
  const label=type==='shop'?name+' (Shop)':name;
  if(type==='shop'&&listingUrl)return '<a href="'+esc(listingUrl)+'" target="_blank" rel="noopener noreferrer">'+esc(label)+'</a>';
  return esc(label);
}
function currentSnapshotOwnerHtml(i){
  if(!i)return '—';
  const name=String(i.current_owner_name||'').trim();
  if(!name)return '—';
  const type=String(i.current_owner_type||'').trim();
  const listingUrl=String(i.current_owner_source_url||'').trim();
  const label=type==='shop'?name+' (Shop)':name;
  if(i.current_owner_user_id&&activeUser&&activeUser.user)return '<a href="/users/'+Number(i.current_owner_user_id)+'">'+esc(label)+'</a>';
  if(type==='shop'&&listingUrl)return '<a href="'+esc(listingUrl)+'" target="_blank" rel="noopener noreferrer">'+esc(label)+'</a>';
  return esc(label);
}
function currentLocationHtml(o){
  if(!o)return '—';
  const country=String(o.location_country||'').trim();
  const region=String(o.location_region||'').trim();
  const value=[country,region].filter(Boolean).join(' / ');
  return value?esc(value):'—';
}
function observationCard(o,isLatest){
  const url=String(o.source_url||'');
  const source=sourceName(o);
  const sourceHtml=url?'<a href="'+esc(url)+'" target="_blank" rel="noopener noreferrer">'+esc(source)+'</a>':esc(source);
  const owner=ownerLabel(o);
  const seller=String(o.seller||'').trim();
  let rows='';
  if(owner)rows+='<div class="observation-row"><div class="observation-label">Owner</div><div class="observation-value">'+esc(owner)+'</div></div>';
  if(seller&&seller!==String(o.owner_user_name||o.owner_name||'').trim())rows+='<div class="observation-row"><div class="observation-label">Shop</div><div class="observation-value">'+esc(seller)+'</div></div>';
  const location=[o.location_country,o.location_region].filter(Boolean).join(' / ');
  if(location)rows+='<div class="observation-row"><div class="observation-label">Location</div><div class="observation-value">'+esc(location)+'</div></div>';
  if(o.title)rows+='<div class="observation-row"><div class="observation-label">Listing</div><div class="observation-value observation-title">'+esc(o.title)+'</div></div>';
  const specs=[o.model&&('Model: '+o.model),o.finish&&('Finish: '+o.finish),o.year&&('Year: '+o.year)].filter(Boolean).join(' / ');
  if(specs)rows+='<div class="observation-row"><div class="observation-label">Info</div><div class="observation-value">'+esc(specs)+'</div></div>';
  if(url)rows+='<div class="observation-row"><div class="observation-label">URL</div><div class="observation-value"><a href="'+esc(url)+'" target="_blank" rel="noopener noreferrer">Open listing</a></div></div>';
  return '<div class="observation-card'+(isLatest?' latest':'')+'"><div class="observation-card-head"><div class="observation-date">'+esc(o.listing_date||o.observed_at||'')+'</div><div class="observation-source">Source: '+sourceHtml+'</div></div>'+rows+'</div>';
}
function activeUserOwns(individualId){
  return !!(activeUser&&(activeUser.guitars||[]).some(g=>Number(g.individual_id)===Number(individualId)&&g.ownership_status==='current_owner'));
}
function requireAccount(){
  const modal=document.getElementById('accountRequiredModal');
  if(modal)modal.classList.add('open');
}
function closeAccountRequired(event){
  if(event&&event.target&&event.target.id!=='accountRequiredModal')return;
  const modal=document.getElementById('accountRequiredModal');
  if(modal)modal.classList.remove('open');
}
function ownershipControlsHtml(individualId){
  if(activeUser&&activeUser.user&&activeUserOwns(individualId)){
    return '<div class="toolbar" style="margin-top:10px"><span class="status good">Your Guitar</span></div>';
  }
  if(!activeUser||!activeUser.user){
    return '<div class="toolbar" style="margin-top:10px"><button onclick="requireAccount()">Add to Your Chronicle</button></div>';
  }
  return '<div class="toolbar" style="margin-top:10px"><button onclick="openOwnerClaim('+individualId+')">Add to Your Chronicle</button></div>';
}

function productGalleryHtml(images,model){
  productGallery=(images||[]).slice();
  productGalleryIndex=0;
  if(!productGallery.length)return '';
  const item=productGallery[0];
  const disabled=productGallery.length<2?' disabled':'';
  const caption=String(item.caption||'').trim();
  const source=String(item.label||'Uploaded Image')+(caption?' — '+caption:'')+' (1/'+productGallery.length+')';
  return '<div class="detail-gallery">'+
    '<button class="detail-gallery-nav" onclick="stepProductGallery(-1)"'+disabled+'>◀</button>'+
    '<img class="detail-image" id="productGalleryImage" src="'+esc(item.url)+'" alt="'+esc(model||'Guitar')+'" loading="lazy" onerror="this.onerror=null;this.src=\'/assets/no-picture.svg\'">'+
    '<button class="detail-gallery-nav" onclick="stepProductGallery(1)"'+disabled+'>▶</button>'+
    '</div><span class="detail-source" id="productGallerySource">'+esc(source)+'</span>';
}
function stepProductGallery(delta){
  if(productGallery.length<2)return;
  productGalleryIndex=(productGalleryIndex+delta+productGallery.length)%productGallery.length;
  const item=productGallery[productGalleryIndex];
  const image=document.getElementById('productGalleryImage');
  const source=document.getElementById('productGallerySource');
  if(image)image.src=item.url;
  if(source){
    const caption=String(item.caption||'').trim();
    source.textContent=String(item.label||'Uploaded Image')+(caption?' — '+caption:'')+' ('+(productGalleryIndex+1)+'/'+productGallery.length+')';
  }
}
function specificationFieldLabel(value){
  const labels={
    nut:'Nut',
    frets:'Frets',
    pickguard:'Pickguard',
    potentiometers:'Potentiometers',
    wiring:'Wiring',
    neck:'Neck',
    pickups:'Pickups',
    bridge:'Bridge',
    tuners:'Tuners',
    body:'Body',
    fingerboard:'Fingerboard',
    finish:'Finish',
    weight:'Weight'
  };
  const key=String(value||'').trim();
  return labels[key]||key.replace(/_/g,' ').replace(/\b\w/g,m=>m.toUpperCase());
}
function identityFieldLabel(value){
  const labels={
    manufacturer:'Maker',
    model:'Model',
    year:'Year',
    serial_number:'Serial'
  };
  return labels[String(value||'')]||String(value||'').replace(/_/g,' ');
}
function claimTypeLabel(value){
  return String(value||'claim').split('_').map(x=>x?x[0].toUpperCase()+x.slice(1):'').join(' ');
}
function displayEventDate(value){
  if(!value)return '日付不明';
  const text=String(value).trim();
  const direct=text.match(/^(\d{4}-\d{2}-\d{2})/);
  if(direct)return direct[1];
  const d=new Date(text);
  if(Number.isNaN(d.getTime()))return text;
  const year=d.getFullYear();
  const month=String(d.getMonth()+1).padStart(2,'0');
  const day=String(d.getDate()).padStart(2,'0');
  return year+'-'+month+'-'+day;
}
function displayInputDate(value){
  if(!value)return '入力日時不明';
  const d=new Date(String(value));
  return Number.isNaN(d.getTime())?String(value):d.toLocaleString('ja-JP');
}
function displayDiscoveryDateTime(value){
  const raw=String(value||'').trim();
  if(!raw)return '';
  const d=new Date(raw);
  if(Number.isNaN(d.getTime()))return raw;
  return d.getFullYear()+'/'+(d.getMonth()+1)+'/'+d.getDate()+' '+
    String(d.getHours()).padStart(2,'0')+':'+
    String(d.getMinutes()).padStart(2,'0')+':'+
    String(d.getSeconds()).padStart(2,'0');
}
function claimHeaderHtml(c,type,eventDate){
  let response='';
  const isOwner=activeUser&&activeUser.user&&activeUserOwns(selectedIndividualId);
  const isOtherUser=isOwner&&Number(c.author_user_id)!==Number(activeUser.user.id);
  const verifiableTypes=new Set(['specification','incident','event','media']);
  const isFormerOwnerOwnership=(
    c.claim_type==='ownership'
    && String(c.ownership_source||'')==='former_owner'
  );
  if(isOtherUser&&(verifiableTypes.has(String(c.claim_type||''))||isFormerOwnerOwnership)){
    const current=String(c.verification_status||'unverified').toLowerCase();
    response='<select class="claim-response-select" onchange="setClaimResponse('+c.id+',this.value)">'+
      '<option value="positive"'+(current==='positive'?' selected':'')+'>Positive</option>'+
      '<option value="negative"'+(current==='negative'?' selected':'')+'>Negative</option>'+
      '<option value="unverified"'+(current==='unverified'?' selected':'')+'>Unverified</option>'+
      '</select>';
  }
  return '<span class="claim-badge">'+esc(type)+'</span>'+response+'<span class="claim-event-date">'+esc(eventDate)+'</span>';
}
function claimVisualTypeClass(c){
  if(c.claim_type==='ownership'||c.claim_type==='owner_change'||c.claim_type==='release')return ' claim-type-ownership';
  if(c.claim_type==='specification')return ' claim-type-specification';
  if(c.claim_type==='incident')return ' claim-type-incident';
  if(c.claim_type==='event')return ' claim-type-event';
  if(c.claim_type==='media')return ' claim-type-media';
  return '';
}
function claimCardFull(c){
  const type=c.claim_type==='specification'
    ? (c.specification_kind==='repair'?'Repair':'Specification')
    : (c.claim_type==='ownership'?claimTypeLabel(c.ownership_kind||'acquire'):(c.claim_type==='incident'?claimTypeLabel(c.value_text||'incident'):(c.claim_type==='event'?claimTypeLabel(c.value_text||'event'):(c.claim_type==='release'?'Release':claimTypeLabel(c.claim_type)))));
  const eventDate=displayEventDate(c.occurred_at);
  let body='';
  if(c.claim_type==='ownership'){
    const kind=String(c.ownership_kind||'acquire');
    const owner=String(c.author_name||'User').trim()||'User';
    const raw=String(c.observation_raw_text||'');
    const firstLine=(raw.split(/\r?\n/)[0]||'').trim();
    const party=firstLine.startsWith('Previous owner:')
      ? (firstLine.slice('Previous owner:'.length).trim()||'Unknown')
      : 'Unknown';
    if(kind==='release'){
      body='<div><strong>'+esc(owner)+' released this product.</strong></div>';
    }else if(kind==='transfer'){
      body='<div><strong>'+esc(party)+' acquired this product from '+esc(owner)+'.</strong></div>';
    }else if(kind==='inherit'){
      body='<div><strong>'+esc(party)+' inherited this product from '+esc(owner)+'.</strong></div>';
    }else{
      body='<div><strong>'+esc(owner)+' became the owner of this product.</strong></div>';
    }
    if(c.body)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }else if(c.claim_type==='incident'){
    if(c.body)body+='<div><strong>'+esc(c.body)+'</strong></div>';
  }else if(c.claim_type==='event'){
    if(c.body)body+='<div><strong>'+esc(c.body)+'</strong></div>';
  }else if(c.claim_type==='owner_change'){
    body='<div><strong>'+esc(c.author_name||'User')+' has become the owner.</strong></div>';
    if(c.body)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }else if(c.claim_type==='release'){
    body='<div><strong>Ownership released. Current owner is Unknown.</strong></div>';
    if(c.body)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }else if(c.claim_type==='specification'){
    const items=(c.spec_items&&c.spec_items.length)
      ? c.spec_items
      : (c.field_name?[{field_name:c.field_name,value_text:c.value_text}]:[]);
    body=items.map(item=>'<div><strong>'+esc(specificationFieldLabel(item.field_name))+': '+esc(item.value_text||'')+'</strong></div>').join('');
    if(c.body)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }else if(c.claim_type==='identity_correction'){
    const items=c.identity_items||[];
    body=items.map(item=>
      '<div><strong>'+esc(identityFieldLabel(item.field_name))+':</strong> '+
      esc(item.old_value||'—')+' → '+esc(item.new_value||'—')+'</div>'
    ).join('');
    if(c.body)body+='<div class="claim-memo">Reason: '+esc(c.body)+'</div>';
  }else if(c.claim_type==='media'){
    const mediaImages=(c.media_images&&c.media_images.length)
      ? c.media_images
      : (c.evidence_media_id?[{id:c.evidence_media_id,url:'/api/media/'+encodeURIComponent(c.evidence_media_id)}]:[]);
    if(mediaImages.length){
      body+='<div class="claim-media-thumbs">'+mediaImages.map(m=>'<img class="claim-evidence-image" width="48" height="48" style="width:48px!important;height:48px!important;max-width:48px!important;max-height:48px!important;object-fit:cover" src="'+esc(m.url)+'" alt="Media Claim image" loading="lazy" onerror="this.onerror=null;this.src=\'/assets/no-picture.svg\'">').join('')+'</div>';
    }
    if(c.body)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }else if(c.claim_type==='listing'){
    const title=c.listing_title||c.body||'Listing observed';
    body='<div><strong>'+esc(title)+'</strong></div>';
    const details=[];
    const listingOwner=String(c.observed_owner_name||'').trim();
    const seller=String(c.seller||'').trim();
    if(listingOwner&&listingOwner!==seller)details.push('Owner: '+listingOwner);
    if(seller)details.push('Seller: '+seller);
    const location=[c.location_country,c.location_region].filter(Boolean).join(' / ');
    if(location)details.push('Location: '+location);
    const specs=[
      c.observed_model&&('Model: '+c.observed_model),
      c.observed_finish&&('Finish: '+c.observed_finish),
      c.observed_year&&('Year: '+c.observed_year),
      c.observed_serial_number&&('Serial: '+c.observed_serial_number)
    ].filter(Boolean).join(' / ');
    if(specs)details.push(specs);
    if(details.length)body+='<div class="claim-memo">'+details.map(esc).join('<br>')+'</div>';
    if(c.body&&c.body!==title)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
    if(c.source_url)body+='<div class="claim-memo"><a href="'+esc(c.source_url)+'" target="_blank" rel="noopener noreferrer">Open listing</a></div>';
  }else{
    if(c.value_text)body+='<div><strong>'+esc(c.value_text)+'</strong></div>';
    if(c.body)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }
  if(c.evidence_media_id&&c.claim_type!=='media'){
    body+='<div class="claim-memo"><img class="claim-evidence-image" width="48" height="48" style="width:48px;height:48px;max-width:48px;max-height:48px;object-fit:cover" src="/api/media/'+encodeURIComponent(c.evidence_media_id)+'" alt="Claim evidence" loading="lazy" onerror="this.onerror=null;this.src=\'/assets/no-picture.svg\'"></div>';
  }
  const good=String(Number(c.good_count||0)).padStart(2,'0');
  const bad=String(Number(c.bad_count||0)).padStart(2,'0');
  const votes='<div class="claim-votes">'+
    '<button class="claim-vote'+(c.viewer_vote==='good'?' active':'')+'" onclick="voteClaim('+c.id+',\'good\')">👍 '+good+'</button>'+
    '<button class="claim-vote'+(c.viewer_vote==='bad'?' active':'')+'" onclick="voteClaim('+c.id+',\'bad\')">👎 '+bad+'</button>'+
    '</div>';
  return '<div class="claim-card'+claimVisualTypeClass(c)+(c.claim_type==='identity_correction'?' identity-correction-card':'')+'">'+
    '<div class="claim-head">'+claimHeaderHtml(c,type,eventDate)+'</div>'+
    '<div class="claim-body">'+body+'</div>'+
    '<div class="claim-footer">'+votes+'<div class="claim-footer-meta">'+esc(displayInputDate(c.created_at))+' · By '+((activeUser&&activeUser.user)?'<a href="/users/'+Number(c.author_user_id)+'">'+esc(c.author_name||('User #'+c.author_user_id))+'</a>':esc(c.author_name||('User #'+c.author_user_id)))+'</div></div>'+
    '</div>';
}
function compactClaimType(c){
  return c.claim_type==='specification'
    ? (c.specification_kind==='repair'?'Repair':'Specification')
    : (c.claim_type==='ownership'?claimTypeLabel(c.ownership_kind||'acquire')
      :(c.claim_type==='incident'?claimTypeLabel(c.value_text||'incident')
      :(c.claim_type==='event'?claimTypeLabel(c.value_text||'event')
      :(c.claim_type==='release'?'Release':claimTypeLabel(c.claim_type)))));
}
function claimCard(c){
  const verification=String(c.verification_status||'positive').toLowerCase();
  if(verification==='positive')return claimCardFull(c);
  if(verification==='unverified'){
    return '<div class="claim-compact-row"><button type="button" class="claim-compact-tag'+claimVisualTypeClass(c)+'" onclick="openClaimPopup('+c.id+',this)">'+esc(compactClaimType(c))+'</button></div>';
  }
  if(verification==='negative'){
    return '<div class="claim-compact-row"><button type="button" class="claim-negative-dot" title="Negative Claim" onclick="openClaimPopup('+c.id+',this)">◉</button></div>';
  }
  return claimCardFull(c);
}
function positionClaimPopup(trigger){
  const backdrop=document.getElementById('claimPopupModal');
  const popup=backdrop?backdrop.querySelector('.claim-popup-modal'):null;
  const chronicle=document.getElementById('chronicleEntries');
  if(!backdrop||!popup||!chronicle||!trigger)return;

  const triggerRect=trigger.getBoundingClientRect();
  const chronicleRect=chronicle.getBoundingClientRect();
  const marginLeft=22;
  const edge=10;
  const width=Math.max(220,chronicleRect.width-marginLeft);
  const preferredLeft=chronicleRect.left+marginLeft-(width*0.5);
  const left=Math.min(
    Math.max(edge,preferredLeft),
    Math.max(edge,window.innerWidth-width-edge)
  );

  popup.style.width=width+'px';
  popup.style.left=left+'px';
  popup.style.top=Math.min(
    window.innerHeight-edge,
    triggerRect.bottom+6
  )+'px';

  requestAnimationFrame(()=>{
    const popupRect=popup.getBoundingClientRect();
    let top=triggerRect.bottom+6;
    if(top+popupRect.height>window.innerHeight-edge){
      top=triggerRect.top-popupRect.height-6;
    }
    if(top<edge)top=edge;
    popup.style.top=top+'px';
  });
}
function openClaimPopup(claimId,trigger){
  if(!activeUser||!activeUser.user){
    requireAccount();
    return;
  }
  const claim=currentClaims.find(c=>Number(c.id)===Number(claimId));
  if(!claim)return;
  const content=document.getElementById('claimPopupContent');
  if(content)content.innerHTML=claimCardFull(claim);
  const modal=document.getElementById('claimPopupModal');
  if(modal){
    modal.classList.add('open');
    positionClaimPopup(trigger);
  }
}
function closeClaimPopup(event){
  if(event&&event.target&&event.target.id!=='claimPopupModal')return;
  const modal=document.getElementById('claimPopupModal');
  if(modal)modal.classList.remove('open');
}

function toggleDetailAccordion(id){
  const section=document.getElementById(id);
  if(section)section.classList.toggle('collapsed');
}

function chronologyValue(c,mode){
  if(mode==='input')return String(c.created_at||'');
  return String(c.occurred_at||c.created_at||'');
}
function renderChronicle(){
  const sorted=currentClaims.slice().sort((a,b)=>{
    const av=chronologyValue(a,chronicleSort);
    const bv=chronologyValue(b,chronicleSort);
    if(av<bv)return 1;
    if(av>bv)return -1;
    return Number(b.id)-Number(a.id);
  });
  const correctionsByTarget=new Map();
  const roots=[];
  for(const claim of sorted){
    if(claim.claim_type==='identity_correction'&&claim.target_claim_id){
      const key=Number(claim.target_claim_id);
      if(!correctionsByTarget.has(key))correctionsByTarget.set(key,[]);
      correctionsByTarget.get(key).push(claim);
    }else{
      roots.push(claim);
    }
  }
  const claims=[];
  for(const claim of roots){
    claims.push(claim);
    const corrections=correctionsByTarget.get(Number(claim.id))||[];
    corrections.sort((a,b)=>String(a.created_at||'').localeCompare(String(b.created_at||'')));
    claims.push(...corrections);
    correctionsByTarget.delete(Number(claim.id));
  }
  for(const corrections of correctionsByTarget.values())claims.push(...corrections);
  const el=document.getElementById('chronicleEntries');
  if(el)el.innerHTML=claims.length
    ? claims.map(claimCard).join('')
    : '<div class="sub">Claimはまだありません。</div>';
}
function setChronicleSort(value){
  chronicleSort=value==='input'?'input':'event';
  renderChronicle();
}

async function setClaimResponse(claimId,stance){
  if(!activeUser||!activeUser.user)return;
  try{
    await jfetch('/api/claims/'+claimId+'/response',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        responder_user_id:Number(activeUser.user.id),
        stance
      })
    });
    closeClaimPopup();
    if(selectedIndividualId!==null)await showIndividual(selectedIndividualId);
  }catch(e){
    alert('Owner Verificationの更新に失敗しました。\n'+e.message);
    if(selectedIndividualId!==null)await showIndividual(selectedIndividualId);
  }
}

async function voteClaim(claimId,vote){
  if(!activeUser||!activeUser.user){
    requireAccount();
    return;
  }
  try{
    await jfetch('/api/claims/'+claimId+'/vote',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({user_id:Number(activeUser.user.id),vote})
    });
    if(selectedIndividualId!==null)await showIndividual(selectedIndividualId);
  }catch(e){
    alert('Voteの更新に失敗しました。\n'+e.message);
  }
}

async function showIndividual(id){
  const nextIndividualId=Number(id);
  const changedIndividual=Number(selectedIndividualId)!==nextIndividualId;
  selectedIndividualId=nextIndividualId;
  if(changedIndividual){
    const detail=document.getElementById('detail');
    if(detail)detail.scrollTop=0;
  }
  if(typeof renderIndividuals==='function')renderIndividuals();
  const [d,claims,currentSpecifications]=await Promise.all([
    jfetch('/api/individuals/'+id),
    jfetch('/api/individuals/'+id+'/claims'+(activeUser&&activeUser.user?'?viewer_user_id='+encodeURIComponent(activeUser.user.id):'')),
    jfetch('/api/individuals/'+id+'/current-specifications')
  ]);
  const i=d.individual;
  const observations=d.observations||[];
  currentObservations=observations;
  currentClaims=claims||[];
  const latest=observations.length?observations[observations.length-1]:null;
  const imageListing=(claims||[]).slice().reverse().find(c=>c.claim_type==='listing'&&c.status==='active'&&c.image_url)||null;
  const imageObservation=observations.slice().reverse().find(o=>o.image_url)||null;
  const galleryImages=d.gallery_images||[];
  let out='';
  if(galleryImages.length){
    out+=productGalleryHtml(galleryImages,i.model||'Guitar');
  }else if(i.representative_image_url){
    out+='<img class="detail-image" src="'+esc(i.representative_image_url)+'" alt="'+esc(i.model||'Guitar')+'" loading="lazy" onerror="this.onerror=null;this.src=\'/assets/no-picture.svg\'"><span class="detail-source">Representative Image</span>';
  }else if(imageListing){
    const imageUrl=String(imageListing.source_url||'');
    const image='<img class="detail-image" src="'+esc(imageListing.image_url)+'" alt="'+esc(imageListing.listing_title||i.model||'Guitar')+'" loading="lazy" referrerpolicy="no-referrer" onerror="this.onerror=null;this.src=\'/assets/no-picture.svg\'">';
    if(imageUrl)out+='<a class="detail-image-link" href="'+esc(imageUrl)+'" target="_blank" rel="noopener noreferrer">'+image+'</a><span class="detail-source">Source: <a href="'+esc(imageUrl)+'" target="_blank" rel="noopener noreferrer">'+esc(String(imageListing.source_site||'Source'))+'</a></span>';
    else out+=image+'<span class="detail-source">Listing Claim</span>';
  }else if(imageObservation){
    const imageUrl=String(imageObservation.source_url||'');
    const image='<img class="detail-image" src="'+esc(imageObservation.image_url)+'" alt="'+esc(imageObservation.title||i.model||'Guitar')+'" loading="lazy" referrerpolicy="no-referrer" onerror="this.onerror=null;this.src=\'/assets/no-picture.svg\'">';
    if(imageUrl)out+='<a class="detail-image-link" href="'+esc(imageUrl)+'" target="_blank" rel="noopener noreferrer">'+image+'</a><span class="detail-source">Source: Reverb image (provenance)</span>';
    else out+=image+'<span class="detail-source">Source: Reverb image (provenance)</span>';
  }else{
    out+='<img class="detail-image" src="/assets/no-picture.svg" alt="No picture"><span class="detail-source">No Picture</span>';
  }
  const specMap={};
  for(const s of (currentSpecifications||[]))specMap[String(s.field_name||'')]=s;
  const finishValue=specMap.finish?specMap.finish.value_text:(i.finish||'—');
  const fixedSpecRows=[
    ['Maker',i.manufacturer||'—'],
    ['Model',i.model||'—'],
    ['Finish',finishValue||'—'],
    ['Year',i.year||'—'],
    ['Serial',i.serial_number||'—']
  ];
  const hiddenFields=new Set(['maker','manufacturer','model','finish','year','serial','serial_number']);
  const preferredOrder=['body','bridge','fingerboard','frets','neck','nut','pickups','pickguard','potentiometers','tuners','wiring','weight'];
  const dynamicSpecs=(currentSpecifications||[])
    .filter(s=>!hiddenFields.has(String(s.field_name||'').toLowerCase()))
    .slice()
    .sort((a,b)=>{
      const ak=String(a.field_name||'').toLowerCase();
      const bk=String(b.field_name||'').toLowerCase();
      const ai=preferredOrder.indexOf(ak);
      const bi=preferredOrder.indexOf(bk);
      if(ai>=0||bi>=0){
        if(ai<0)return 1;
        if(bi<0)return-1;
        if(ai!==bi)return ai-bi;
      }
      return ak.localeCompare(bk);
    });
  out+='<div class="detail-header"><div class="detail-header-title">'+esc(i.manufacturer)+' '+esc(i.model||'')+'</div>'+
    '<div class="current-owner-line"><span class="catalog-spec-label">Current Owner:</span> '+currentSnapshotOwnerHtml(i)+'</div>'+
    '<div class="current-owner-line"><span class="catalog-spec-label">Location:</span> '+currentLocationHtml(i)+'</div>'+
    ownershipControlsHtml(i.id)+'</div>';
  out+='<section class="accordion-section" id="specificationAccordion">'+
    '<div class="accordion-header">'+
      '<button type="button" class="accordion-toggle" onclick="toggleDetailAccordion(\'specificationAccordion\')">▼</button>'+
      '<span class="accordion-title" onclick="toggleDetailAccordion(\'specificationAccordion\')">Specification</span>'+
    '</div>'+
    '<div class="accordion-body"><div class="catalog-spec">'+
      fixedSpecRows.map(row=>'<div class="catalog-spec-row"><span class="catalog-spec-label">'+esc(row[0])+':</span> '+esc(row[1])+'</div>').join('')+
      dynamicSpecs.map(s=>'<div class="catalog-spec-row"><span class="catalog-spec-label">'+esc(specificationFieldLabel(s.field_name))+':</span> '+esc(s.value_text||'—')+'</div>').join('')+
    '</div></div></section>';
  out+='<section class="accordion-section" id="chronicleAccordion">'+
    '<div class="accordion-header">'+
      '<button type="button" class="accordion-toggle" onclick="toggleDetailAccordion(\'chronicleAccordion\')">▼</button>'+
      '<span class="accordion-title" onclick="toggleDetailAccordion(\'chronicleAccordion\')">Chronicle</span>'+
      '<div class="toolbar"><div class="claim-menu-wrap"><button onclick="toggleAddClaimMenu(event,'+i.id+')">Add Claim</button><div class="claim-menu" id="addClaimMenu"><button onclick="chooseClaimType(\'specification_repair\')">Specification/Repair</button><button onclick="chooseClaimType(\'incident\')">Incident</button><button onclick="chooseClaimType(\'event\')">Event</button><button onclick="chooseClaimType(\'media\')">Media</button>'+(activeUserOwns(i.id)?'<button onclick="chooseClaimType(\'ownership\')">Ownership</button>':'<button onclick="chooseClaimType(\'former_owner\')">Former Owner</button>')+'</div></div><select onchange="setChronicleSort(this.value)"><option value="event"'+(chronicleSort==='event'?' selected':'')+'>出来事順</option><option value="input"'+(chronicleSort==='input'?' selected':'')+'>入力順</option></select></div>'+
    '</div>'+
    '<div class="accordion-body"><div id="chronicleEntries"></div></div></section>';
  document.getElementById('detail').innerHTML=out;
  renderChronicle();
  if(changedIndividual){
    const detail=document.getElementById('detail');
    if(detail)detail.scrollTop=0;
  }
}


const SPEC_FIELDS=[
  ['nut','Nut'],['frets','Frets'],['pickguard','Pickguard'],
  ['potentiometers','Potentiometers'],['wiring','Wiring'],['neck','Neck'],
  ['pickups','Pickups'],['bridge','Bridge'],['tuners','Tuners'],
  ['body','Body'],['fingerboard','Fingerboard'],['finish','Finish'],['weight','Weight']
];
let specificationKind='specification';
let specificationItems=[];
let editingSpecificationClaimId=null;

function toggleAddClaimMenu(event,individualId){
  event.stopPropagation();
  if(!activeUser||!activeUser.user){
    requireAccount();
    return;
  }
  selectedIndividualId=Number(individualId);
  const menu=document.getElementById('addClaimMenu');
  if(menu)menu.classList.toggle('open');
}
function chooseClaimType(type){
  const menu=document.getElementById('addClaimMenu');
  if(menu)menu.classList.remove('open');
  if(type==='specification_repair')openSpecificationClaim(selectedIndividualId);
  else if(type==='incident')openIncidentClaim(selectedIndividualId);
  else if(type==='event')openEventClaim(selectedIndividualId);
  else if(type==='media')openMediaClaim(selectedIndividualId);
  else if(type==='former_owner')openFormerOwnerClaim(selectedIndividualId);
  else if(type==='ownership')openOwnershipClaim(selectedIndividualId,'add_claim');
}

function mediaImageInputs(){
  return Array.from(document.querySelectorAll('#mediaClaimImages .media-image-input'));
}
function resetMediaImageInputs(){
  mediaImageInputs().forEach((input,index)=>{
    input.value='';
    const slot=document.getElementById('mediaImageSlot'+index);
    if(slot)slot.classList.toggle('visible',index===0);
  });
}
function updateMediaImageSlots(){
  const inputs=mediaImageInputs();
  let lastSelected=-1;
  inputs.forEach((input,index)=>{if(input.files&&input.files.length)lastSelected=index;});
  const next=Math.min(lastSelected+1,inputs.length-1);
  inputs.forEach((input,index)=>{
    const slot=document.getElementById('mediaImageSlot'+index);
    if(slot)slot.classList.toggle('visible',index===0||index<=next||(input.files&&input.files.length>0));
  });
}
function openMediaClaim(individualId){
  if(!activeUser||!activeUser.user)return;
  selectedIndividualId=Number(individualId);
  const guitar=individuals.find(x=>Number(x.id)===Number(individualId));
  document.getElementById('mediaClaimGuitar').textContent=guitar?guitar.manufacturer+' '+(guitar.model||'')+(guitar.serial_number?' / '+guitar.serial_number:''):'Individual #'+individualId;
  resetMediaImageInputs();
  document.getElementById('mediaClaimDate').value=new Date().toISOString().slice(0,10);
  document.getElementById('mediaClaimCaption').value='';
  document.getElementById('mediaClaimModal').classList.add('open');
}
function closeMediaClaim(event){
  if(event&&event.target&&event.target.id!=='mediaClaimModal')return;
  document.getElementById('mediaClaimModal').classList.remove('open');
}
async function submitMediaClaim(){
  if(!activeUser||!activeUser.user||selectedIndividualId===null)return;
  const images=mediaImageInputs().map(input=>input.files&&input.files[0]).filter(Boolean);
  if(!images.length){alert('画像ファイルを1枚以上選択してください。');return;}
  for(const image of images){
    if(!['image/jpeg','image/png','image/webp','image/gif'].includes(image.type)){alert('JPEG / PNG / WebP / GIF画像を選択してください。');return;}
    if(image.size>12*1024*1024){alert('画像は1枚12MB以下にしてください。');return;}
  }
  const form=new FormData();
  form.append('user_id',String(activeUser.user.id));
  images.forEach(image=>form.append('images',image));
  form.append('occurred_at',document.getElementById('mediaClaimDate').value||'');
  form.append('caption',document.getElementById('mediaClaimCaption').value.trim());
  const button=document.getElementById('mediaClaimSubmit');
  button.disabled=true;
  try{
    const response=await fetch('/api/individuals/'+selectedIndividualId+'/media-claim',{method:'POST',body:form});
    const data=await response.json().catch(()=>({}));
    if(!response.ok)throw new Error(data.detail||response.statusText);
    closeMediaClaim();
    await showIndividual(selectedIndividualId);
  }catch(e){alert('Media Claimの登録に失敗しました。\n'+e.message);}
  finally{button.disabled=false;}
}

function openEventClaim(individualId){
  if(!activeUser||!activeUser.user)return;
  selectedIndividualId=Number(individualId);
  const guitar=individuals.find(x=>Number(x.id)===Number(individualId));
  document.getElementById('eventClaimGuitar').textContent=guitar?guitar.manufacturer+' '+(guitar.model||'')+(guitar.serial_number?' / '+guitar.serial_number:''):'Individual #'+individualId;
  document.getElementById('eventClaimKind').value='exhibition';
  document.getElementById('eventClaimDate').value=new Date().toISOString().slice(0,10);
  document.getElementById('eventClaimDetail').value='';
  document.getElementById('eventClaimModal').classList.add('open');
}
function closeEventClaim(event){
  if(event&&event.target&&event.target.id!=='eventClaimModal')return;
  document.getElementById('eventClaimModal').classList.remove('open');
}
async function submitEventClaim(){
  const detail=document.getElementById('eventClaimDetail').value.trim();
  if(!detail){alert('Detailを入力してください。');return;}
  const button=document.getElementById('eventClaimSubmit');button.disabled=true;
  try{
    await jfetch('/api/individuals/'+selectedIndividualId+'/event-claim',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:Number(activeUser.user.id),event_kind:document.getElementById('eventClaimKind').value,occurred_at:document.getElementById('eventClaimDate').value||null,detail})});
    closeEventClaim();await showIndividual(selectedIndividualId);
  }catch(e){alert('Event Claimの登録に失敗しました。\n'+e.message);}
  finally{button.disabled=false;}
}

function openIncidentClaim(individualId){
  if(!activeUser||!activeUser.user)return;
  selectedIndividualId=Number(individualId);
  const guitar=individuals.find(x=>Number(x.id)===Number(individualId));
  document.getElementById('incidentClaimGuitar').textContent=guitar?guitar.manufacturer+' '+(guitar.model||'')+(guitar.serial_number?' / '+guitar.serial_number:''):'Individual #'+individualId;
  document.getElementById('incidentClaimKind').value='damage';
  document.getElementById('incidentClaimDate').value=new Date().toISOString().slice(0,10);
  document.getElementById('incidentClaimDetail').value='';
  document.getElementById('incidentClaimModal').classList.add('open');
}
function closeIncidentClaim(event){
  if(event&&event.target&&event.target.id!=='incidentClaimModal')return;
  document.getElementById('incidentClaimModal').classList.remove('open');
}
async function submitIncidentClaim(){
  const detail=document.getElementById('incidentClaimDetail').value.trim();
  if(!detail){alert('Detailを入力してください。');return;}
  const button=document.getElementById('incidentClaimSubmit');button.disabled=true;
  try{
    await jfetch('/api/individuals/'+selectedIndividualId+'/incident-claim',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:Number(activeUser.user.id),incident_kind:document.getElementById('incidentClaimKind').value,occurred_at:document.getElementById('incidentClaimDate').value||null,detail})});
    closeIncidentClaim();await showIndividual(selectedIndividualId);
  }catch(e){alert('Incident Claimの登録に失敗しました。\n'+e.message);}
  finally{button.disabled=false;}
}

function setSpecificationKind(kind){
  specificationKind=kind==='repair'?'repair':'specification';
  document.getElementById('specKindSpecification').classList.toggle('active',specificationKind==='specification');
  document.getElementById('specKindRepair').classList.toggle('active',specificationKind==='repair');
}
function openSpecificationClaim(individualId){
  if(!activeUser||!activeUser.user)return;
  selectedIndividualId=Number(individualId);
  const guitar=individuals.find(x=>Number(x.id)===Number(individualId));
  document.getElementById('specClaimGuitar').textContent=guitar?guitar.manufacturer+' '+(guitar.model||'')+(guitar.serial_number?' / '+guitar.serial_number:''):'Individual #'+individualId;
  editingSpecificationClaimId=null;specificationItems=[];setSpecificationKind('specification');
  document.getElementById('specClaimTitle').textContent='Specification/Repair Claim';
  document.getElementById('specClaimSubmit').textContent='Claimを追加';
  document.getElementById('specClaimDate').value=new Date().toISOString().slice(0,10);
  document.getElementById('specClaimBody').value='';
  renderSpecificationItems();renderSpecItemMenu();
  document.getElementById('specClaimModal').classList.add('open');
}
function closeSpecificationClaim(event){
  if(event&&event.target&&event.target.id!=='specClaimModal')return;
  document.getElementById('specClaimModal').classList.remove('open');
  const menu=document.getElementById('specItemMenu');if(menu)menu.classList.remove('open');
}
function toggleSpecItemMenu(event){
  event.stopPropagation();renderSpecItemMenu();document.getElementById('specItemMenu').classList.toggle('open');
}
function renderSpecItemMenu(){
  const menu=document.getElementById('specItemMenu');if(!menu)return;
  const used=new Set(specificationItems.map(x=>x.field_name));
  menu.innerHTML=SPEC_FIELDS.filter(([key])=>!used.has(key)).map(([key,label])=>'<button type="button" onclick="addSpecificationItem(\''+key+'\')">'+esc(label)+'</button>').join('')+'<button type="button" onclick="addCustomSpecificationItem()">Custom…</button>';
}
function addSpecificationItem(fieldName,label){
  if(specificationItems.some(x=>x.field_name===fieldName))return;
  const found=SPEC_FIELDS.find(([key])=>key===fieldName);
  specificationItems.push({field_name:fieldName,label:label||(found?found[1]:specificationFieldLabel(fieldName)),value_text:''});
  document.getElementById('specItemMenu').classList.remove('open');renderSpecificationItems();
}
function addCustomSpecificationItem(){
  const raw=prompt('Specification項目名を入力してください。');if(!raw)return;
  const fieldName=raw.trim().toLowerCase().replace(/\s+/g,'_');if(!fieldName)return;
  if(specificationItems.some(x=>x.field_name===fieldName)){alert('同じ項目はすでに追加されています。');return;}
  addSpecificationItem(fieldName,raw.trim());
}
function removeSpecificationItem(index){specificationItems.splice(index,1);renderSpecificationItems();renderSpecItemMenu();}
function updateSpecificationItem(index,value){if(specificationItems[index])specificationItems[index].value_text=value;}
function renderSpecificationItems(){
  const el=document.getElementById('specClaimItems');if(!el)return;
  el.innerHTML=specificationItems.length?specificationItems.map((item,index)=>'<div class="spec-item-row"><div class="spec-item-label">'+esc(item.label)+'</div><input maxlength="500" value="'+esc(item.value_text)+'" oninput="updateSpecificationItem('+index+',this.value)" placeholder="Value"><button type="button" class="spec-item-remove" onclick="removeSpecificationItem('+index+')">×</button></div>').join(''):'<div class="sub">＋から入力したい項目を追加してください。</div>';
}
async function submitSpecificationClaim(){
  const items=specificationItems.map(item=>({field_name:item.field_name,value_text:String(item.value_text||'').trim()})).filter(item=>item.value_text);
  if(!items.length){alert('少なくとも1つの項目とValueを入力してください。');return;}
  if(items.length!==specificationItems.length){alert('追加した項目のValueをすべて入力してください。');return;}
  const button=document.getElementById('specClaimSubmit');button.disabled=true;
  try{
    await jfetch('/api/individuals/'+selectedIndividualId+'/specification-claim',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:Number(activeUser.user.id),specification_kind:specificationKind,items,occurred_at:document.getElementById('specClaimDate').value||null,body:document.getElementById('specClaimBody').value.trim()||null})});
    closeSpecificationClaim();await showIndividual(selectedIndividualId);
  }catch(e){alert('Specification/Repair Claimの登録に失敗しました。\n'+e.message);}
  finally{button.disabled=false;}
}

document.addEventListener('click',()=>{
  const claimMenu=document.getElementById('addClaimMenu');if(claimMenu)claimMenu.classList.remove('open');
  const specMenu=document.getElementById('specItemMenu');if(specMenu)specMenu.classList.remove('open');
});

function openFormerOwnerClaim(individualId){
  if(!activeUser||!activeUser.user){
    alert('先にUserを選択してください。');
    return;
  }
  if(activeUserOwns(individualId)){
    alert('現在OwnerはFormer Owner Claimを追加できません。');
    return;
  }
  selectedIndividualId=Number(individualId);
  const guitar=individuals.find(x=>Number(x.id)===Number(individualId));
  document.getElementById('formerOwnerClaimGuitar').textContent=guitar
    ? guitar.manufacturer+' '+(guitar.model||'')+(guitar.serial_number?' / '+guitar.serial_number:'')
    : 'Individual #'+individualId;
  document.getElementById('formerOwnerAcquisitionDate').value='';
  document.getElementById('formerOwnerReleaseDate').value='';
  document.getElementById('formerOwnerDetail').value='';
  document.getElementById('formerOwnerClaimModal').classList.add('open');
  setTimeout(()=>document.getElementById('formerOwnerAcquisitionDate').focus(),0);
}
function closeFormerOwnerClaim(event){
  if(event&&event.target&&event.target.id!=='formerOwnerClaimModal')return;
  const modal=document.getElementById('formerOwnerClaimModal');
  if(modal)modal.classList.remove('open');
}
async function submitFormerOwnerClaim(){
  if(!activeUser||!activeUser.user||selectedIndividualId===null)return;
  const acquisitionDate=document.getElementById('formerOwnerAcquisitionDate').value;
  const releaseDate=document.getElementById('formerOwnerReleaseDate').value;
  if(!acquisitionDate||!releaseDate){
    alert('Acquisition DateとRelease Dateは必須です。');
    return;
  }
  if(acquisitionDate>=releaseDate){
    alert('Acquisition DateはRelease Dateより前の日付にしてください。');
    return;
  }
  const button=document.getElementById('formerOwnerClaimSubmit');
  button.disabled=true;
  try{
    const individualId=selectedIndividualId;
    const d=await jfetch('/api/individuals/'+individualId+'/former-owner-claim',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        user_id:Number(activeUser.user.id),
        acquisition_date:acquisitionDate,
        release_date:releaseDate,
        detail:document.getElementById('formerOwnerDetail').value.trim()||null
      })
    });
    activeUser={user:d.user,guitars:d.guitars};
    closeFormerOwnerClaim();
    if(typeof renderAccount==='function')renderAccount();
    await showIndividual(individualId);
  }catch(e){
    alert('Former Owner Claimの登録に失敗しました。\n'+e.message);
  }finally{
    button.disabled=false;
  }
}

function configureOwnershipClaim(mode){
  ownershipClaimMode=mode==='add_claim'?'add_claim':'acquire';
  const kind=document.getElementById('ownershipClaimKind');
  const fixed=document.getElementById('ownershipClaimFixedTag');
  const previousRow=document.getElementById('ownershipClaimPreviousRow');
  if(ownershipClaimMode==='acquire'){
    kind.value='acquire';
    kind.style.display='none';
    fixed.style.display='block';
    fixed.innerHTML='<strong>Acquire</strong>';
    previousRow.style.display='';
  }else{
    kind.innerHTML='<option value="transfer">Transfer</option><option value="release">Release</option><option value="inherit">Inherit</option>';
    kind.value='transfer';
    kind.style.display='block';
    fixed.style.display='none';
    previousRow.style.display='';
  }
}
function openOwnershipClaim(individualId,mode='acquire'){
  if(!activeUser||!activeUser.user){
    requireAccount();
    return;
  }
  if(mode==='add_claim'&&!activeUserOwns(individualId)){
    alert('現在のUserが所有中のギターだけOwnership Claimを追加できます。');
    return;
  }
  pendingOwnershipClaimIndividualId=Number(individualId);
  selectedIndividualId=Number(individualId);
  const guitar=individuals.find(x=>Number(x.id)===Number(individualId));
  document.getElementById('ownershipClaimGuitar').textContent=guitar
    ? guitar.manufacturer+' '+(guitar.model||'')+(guitar.serial_number?' / '+guitar.serial_number:'')
    : 'Individual #'+individualId;
  configureOwnershipClaim(mode);
  document.getElementById('ownershipClaimDate').value='';
  document.getElementById('ownershipClaimPrevious').value='';
  document.getElementById('ownershipClaimBody').value='';
  document.getElementById('ownershipClaimSubmit').textContent=mode==='acquire'?'Add to Your Chronicle':'Claimを追加';
  document.getElementById('ownershipClaimModal').classList.add('open');
}
function openOwnerClaim(individualId){
  openOwnershipClaim(individualId,'acquire');
}
function closeOwnershipClaim(event){
  if(event&&event.target&&event.target.id!=='ownershipClaimModal')return;
  document.getElementById('ownershipClaimModal').classList.remove('open');
  pendingOwnershipClaimIndividualId=null;
}
async function submitOwnershipClaim(){
  if(!activeUser||!activeUser.user||pendingOwnershipClaimIndividualId===null)return;
  const button=document.getElementById('ownershipClaimSubmit');
  const kind=document.getElementById('ownershipClaimKind').value;
  if(kind==='release'){
    const guitar=individuals.find(x=>Number(x.id)===Number(pendingOwnershipClaimIndividualId));
    const label=guitar?guitar.manufacturer+' '+(guitar.model||''):'このギター';
    if(!confirm(label+' の所有紐づけを解除し、Current OwnerをUnknownに変更します。\n\nこの内容でReleaseしますか？'))return;
  }
  button.disabled=true;
  try{
    const body={
      user_id:Number(activeUser.user.id),
      ownership_kind:kind,
      occurred_at:document.getElementById('ownershipClaimDate').value||null,
      previous_owner_text:document.getElementById('ownershipClaimPrevious').value.trim()||null,
      body:document.getElementById('ownershipClaimBody').value.trim()||null
    };
    const individualId=pendingOwnershipClaimIndividualId;
    const d=await jfetch('/api/individuals/'+individualId+'/ownership-claim',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body)
    });
    activeUser={user:d.user,guitars:d.guitars};
    closeOwnershipClaim();
    if(typeof renderAccount==='function')renderAccount();
    await showIndividual(individualId);
  }catch(e){
    alert('Ownership Claimの登録に失敗しました.\n'+e.message);
  }finally{
    button.disabled=false;
  }
}

(async()=>{
  await loadActiveUser();
  await loadNewDiscoveries();
  await loadIndividuals();

  const requested=Number(new URLSearchParams(window.location.search).get('individual_id')||0);
  const requestedExists=requested&&individuals.some(x=>Number(x.id)===requested);
  if(requestedExists){
    selectedIndividualId=requested;
  }else if(newDiscoveries.length){
    const candidates=newDiscoveries
      .map(item=>Number(item.id))
      .filter(id=>individuals.some(x=>Number(x.id)===id));
    if(candidates.length){
      selectedIndividualId=candidates[Math.floor(Math.random()*candidates.length)];
    }
  }else if(individuals.length){
    selectedIndividualId=Number(individuals[0].id);
  }else{
    selectedIndividualId=null;
  }

  renderIndividuals();
  if(selectedIndividualId!==null){
    await showIndividual(selectedIndividualId);
  }else{
    document.getElementById('detail').textContent='表示できるIndividualがありません。';
  }
})()
</script>
</body>
</html>"""


ipt>
</body>
</html>"""


USER_EDIT_HTML = r"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Your Guitar Chronicle — Edit Your Chronicle</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;600;700;800&display=swap');
:root{color-scheme:dark;--bg:#101214;--panel:#181b1f;--line:#2a2f35;--text:#edf0f3;--muted:#9ba6b0;--accent:#d0a45d;--good:#66c58a;--bad:#e07171}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 "Noto Sans JP",sans-serif}
header{padding:22px 26px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center;gap:16px}
h1{font-size:21px;margin:0}.sub{color:var(--muted);font-size:12px}
main{max-width:1500px;margin:auto;padding:22px}
.grid{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(380px,.85fr);gap:18px;align-items:start}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px;margin-bottom:18px}
h2{font-size:17px;margin:0 0 14px}
.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px}
.toolbar h2{margin:0;flex:1}
input,select,button{font:inherit}
input,select{width:100%;background:#111418;color:var(--text);border:1px solid #343b43;border-radius:8px;padding:9px 10px}
button{border:0;border-radius:8px;padding:9px 13px;background:var(--accent);color:#18130c;font-weight:700;cursor:pointer}
button.secondary{background:#2a3036;color:var(--text)}
button.bad{background:#3a2626;color:#f0b3b3}
.table-wrap{max-height:620px;overflow:auto;border:1px solid var(--line);border-radius:8px}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{text-align:left;border-bottom:1px solid var(--line);padding:8px 7px;vertical-align:top}
th{color:var(--muted);font-weight:600;position:sticky;top:0;background:var(--panel)}
th.sortable{cursor:pointer;user-select:none}.sort-indicator{font-size:10px;margin-left:4px}
.clickable{cursor:pointer}.clickable:hover{background:#20252a}
.mono{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
.status{display:inline-block;padding:3px 7px;border-radius:999px;font-size:11px;background:#2b3035}.good{color:var(--good)}
.detail-image{display:block;width:75%;max-height:270px;object-fit:contain;background:#111418;border:1px solid var(--line);border-radius:8px}
.detail-image-link{display:block;margin:0 0 6px}
.detail-gallery{display:grid;grid-template-columns:20px minmax(0,1fr) 20px;align-items:center;gap:5px;width:75%;margin:0 0 6px}
.detail-gallery .detail-image{width:100%;min-width:0}
.detail-gallery-nav{width:20px;min-width:20px;height:28px;padding:0;border-radius:5px;background:#20252a;color:#777f87;font-size:11px;font-weight:600;line-height:1}
.detail-gallery-nav:hover{background:#272d32;color:#a8b0b7}
.detail-gallery-nav:disabled{opacity:.18;cursor:default}
.detail-source{display:block;margin:0 0 14px;color:var(--muted);font-size:11px}.detail-source a{color:var(--muted)}
.detail-header{margin:0 0 16px}.detail-header-title{font-size:16px;font-weight:700;margin-bottom:6px}.current-owner-line{font-size:13px;margin-bottom:10px}.catalog-spec{font-size:13px;line-height:1.7}.catalog-spec-row{overflow-wrap:anywhere}.catalog-spec-label{font-weight:700}.catalog-spec-empty{color:var(--muted)}
.detail-meta-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.detail-meta-item{background:#14171a;border:1px solid var(--line);border-radius:8px;padding:9px 10px;min-width:0}
.detail-meta-label{display:block;color:var(--muted);font-size:10px;margin-bottom:2px}
.detail-meta-value{display:block;color:var(--text);font-size:12px;overflow-wrap:anywhere}.detail-meta-value a{color:var(--text)}
.detail-section{margin:18px 0 8px;font-size:13px;font-weight:700;border-bottom:1px solid var(--line);padding-bottom:6px}
.observation-card{border:1px solid var(--line);border-radius:10px;background:#14171a;padding:12px 13px;margin:0 0 10px}
.observation-card.latest{border-color:#5c513d;background:#181713}
.observation-card-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:8px}
.observation-date{font-weight:700}.observation-source{font-size:11px;color:var(--muted);white-space:nowrap}.observation-source a{color:var(--muted)}
.observation-row{display:grid;grid-template-columns:78px minmax(0,1fr);gap:8px;margin:4px 0}
.observation-label{color:var(--muted);font-size:11px}.observation-value{min-width:0;overflow-wrap:anywhere}.observation-title{font-weight:600}
#detail{white-space:normal}
.chronicle-toolbar{display:flex;justify-content:space-between;align-items:center;gap:10px;margin:18px 0 10px;border-bottom:1px solid var(--line);padding-bottom:8px}
.chronicle-toolbar select{width:auto;min-width:130px}
.claim-card{border:1px solid #4a4337;border-radius:10px;background:#171612;padding:12px 13px;margin:8px 0 12px 22px}
.claim-card.claim-type-ownership{background:#101d16;border-color:#294b37}
.claim-card.claim-type-specification{background:#101820;border-color:#29465d}
.claim-card.claim-type-incident{background:#211111;border-color:#5a2c2c}
.claim-card.claim-type-event{background:#1b1422;border-color:#4d3560}
.claim-card.claim-type-media{background:#21190d;border-color:#5b4724}
.claim-card.claim-type-ownership .claim-badge{background:#4f9a68;color:#08110b}
.claim-card.claim-type-specification .claim-badge{background:#4d88b8;color:#071018}
.claim-card.claim-type-incident .claim-badge{background:#b85a5a;color:#160808}
.claim-card.claim-type-event .claim-badge{background:#9360b8;color:#120917}
.claim-card.claim-type-media .claim-badge{background:#c68a32;color:#171006}.identity-correction-card{margin-left:42px;border-style:dashed}
.claim-head{display:flex;align-items:center;gap:8px;margin-bottom:10px}.claim-event-date{margin-left:auto;text-align:right}
.claim-badge{display:inline-block;padding:3px 7px;border-radius:999px;background:var(--accent);color:#18130c;font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:.03em}
.claim-event-date{font-size:11px;color:var(--muted);white-space:nowrap}
.claim-body{font-size:12px;line-height:1.5}
.claim-memo{margin-top:8px;white-space:pre-wrap}.claim-card img.claim-media-image{display:block;width:min(320px,100%);height:auto;max-height:240px;object-fit:contain;border:1px solid var(--line);border-radius:8px;margin-top:8px;background:#0f1114}
.claim-footer{margin-top:10px;padding-top:8px;border-top:1px solid var(--line);font-size:9px;color:var(--muted);display:flex;align-items:center;justify-content:space-between;gap:10px}.claim-footer-meta{text-align:right}.claim-votes{display:flex;gap:6px}.claim-vote{padding:4px 7px;border-radius:999px;background:#252a2f;color:var(--text);font-size:10px;min-width:54px}.claim-vote.active{outline:1px solid var(--accent)}.claim-response-select{width:auto;min-width:108px;padding:4px 7px;font-size:11px}
#chronicleEntries{max-height:560px;overflow-y:auto;padding-right:6px}
.claim-card{position:relative}
.claim-card:not(:last-child)::after{content:"";position:absolute;left:50%;top:100%;width:1px;height:12px;background:#4c5258;pointer-events:none;transform:translateX(-.5px)}
.modal-backdrop{display:none;position:fixed;inset:0;background:rgba(0,0,0,.68);align-items:center;justify-content:center;z-index:1000;padding:16px}.modal-backdrop.open{display:flex}.modal{width:min(620px,100%);background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px;box-shadow:0 18px 60px rgba(0,0,0,.45)}.modal-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.form-row{margin-bottom:12px}.form-row.full{grid-column:1/-1}.form-label{display:block;color:var(--muted);font-size:11px;margin-bottom:4px}.modal textarea{width:100%;min-height:90px;background:#111418;color:var(--text);border:1px solid #343b43;border-radius:8px;padding:9px 10px;font:inherit;resize:vertical}.modal-actions{display:flex;gap:8px;justify-content:flex-end;margin-top:16px}.claim-menu-wrap{position:relative;display:inline-block}.claim-menu{display:none;position:absolute;right:0;top:calc(100% + 6px);min-width:190px;background:#1c2024;border:1px solid var(--line);border-radius:9px;padding:6px;z-index:40;box-shadow:0 12px 32px rgba(0,0,0,.38)}.claim-menu.open{display:block}.claim-menu button{display:block;width:100%;text-align:left;background:transparent;color:var(--text);padding:8px 10px}.claim-menu button:hover{background:#2a3036}.spec-kind{display:flex;gap:6px;margin-bottom:14px}.spec-kind button{background:#2a3036;color:var(--text)}.spec-kind button.active{background:var(--accent);color:#18130c}.spec-add-wrap{position:relative;display:inline-block}.spec-add-button{font-size:18px;line-height:1;padding:7px 11px}.spec-item-menu{left:0;right:auto;min-width:220px;max-height:270px;overflow:auto}.spec-items{display:flex;flex-direction:column;gap:8px;margin:10px 0 14px}.spec-scroll-modal{max-height:calc(100vh - 32px);max-height:calc(100dvh - 32px);overflow-y:auto;overscroll-behavior:contain}.spec-item-row{display:grid;grid-template-columns:minmax(110px,.7fr) minmax(0,1.5fr) 34px;gap:8px;align-items:center}.spec-item-label{font-size:12px;color:var(--muted)}.spec-item-remove{padding:7px;background:#3a2626;color:#f0b3b3}.media-image-inputs{display:flex;flex-direction:column;gap:7px;max-height:220px;overflow-y:auto;padding-right:4px}.media-image-slot{display:none}.media-image-slot.visible{display:block}.media-image-slot input{font-size:11px;padding:7px 8px}@media(max-width:560px){.modal-grid{grid-template-columns:1fr}.form-row.full{grid-column:auto}}
.user-profile-row{display:flex;align-items:center;gap:14px;margin:2px 0 14px}.user-avatar{width:84px;height:84px;object-fit:cover;border:1px solid var(--line);border-radius:14px;background:#111418}.user-avatar-controls{flex:1;min-width:0}.user-avatar-controls input{margin-top:5px}
.owned-list{display:flex;flex-direction:column;gap:6px}
.owned-row{display:grid;grid-template-columns:28px minmax(120px,1.4fr) 70px minmax(100px,1fr) minmax(90px,1fr) minmax(110px,1.2fr);gap:8px;align-items:center;border:1px solid var(--line);border-radius:8px;background:#14171a;padding:7px 8px}.owned-row[data-individual-id]{cursor:pointer}.owned-row[data-individual-id]:hover{background:#20252a}
.owned-row.dragging{opacity:.45}
.drag-handle{cursor:grab;color:var(--muted);font-size:16px;text-align:center;user-select:none}
.owned-cell{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px}
.owned-head{color:var(--muted);font-size:10px}
@media(max-width:900px){.grid{grid-template-columns:1fr}}
@media(max-width:520px){.detail-meta-grid{grid-template-columns:1fr}}

.claim-compact-row{display:flex;justify-content:center;align-items:center;min-height:24px;margin:2px 0 4px 22px;position:relative}
.claim-compact-row:not(:last-child)::after{content:"";position:absolute;left:50%;top:100%;width:1px;height:6px;background:#4c5258;pointer-events:none;transform:translateX(-.5px)}
.claim-compact-tag{border:0;border-radius:999px;padding:4px 9px;font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:.03em;cursor:pointer;background:#3a3f45;color:var(--text)}
.claim-compact-tag.claim-type-ownership{background:#4f9a68;color:#08110b}
.claim-compact-tag.claim-type-specification{background:#4d88b8;color:#071018}
.claim-compact-tag.claim-type-incident{background:#b85a5a;color:#160808}
.claim-compact-tag.claim-type-event{background:#9360b8;color:#120917}
.claim-compact-tag.claim-type-media{background:#c68a32;color:#171006}
.claim-negative-dot{border:0;background:transparent!important;color:#737a81!important;padding:0 4px;font-size:20px;line-height:1;cursor:pointer}
.claim-negative-dot:hover{color:#a0a7ae!important}
.claim-popup-modal{position:fixed;width:auto;background:transparent;border:0;padding:0;box-shadow:none;z-index:1001}
.claim-popup-modal .claim-card{margin:0}.claim-popup-modal .claim-card::after{display:none}
#claimPopupModal{background:transparent;align-items:initial;justify-content:initial;padding:0}
</style>
</head>
<body>
<header>
  <div>
    <h1>Your Guitar Chronicle <span class="sub">Edit Your Chronicle</span></h1>
    <div class="sub">User Account / Product Detail</div>
  </div>
  <div class="toolbar" style="margin:0">
    <select id="activeUserSelect" style="width:auto;min-width:170px" onchange="setActiveUser(this.value)">
      <option value="">User未選択</option>
    </select>
    <button onclick="createUser()">新規アカウント</button>
  </div>
</header>
<main>
<div class="grid">
<section>
  <div class="panel">
    <div class="toolbar">
      <h2>User Account</h2>
      <button class="secondary" onclick="loadActiveUser()">更新</button>
    </div>
    <div id="accountPanel" class="sub">アカウントを選択してください。</div>
  </div>

</section>

<section>
  <div class="panel">
    <h2>Product Detail</h2>
    <div id="detail" class="sub">Product List の行をクリックすると履歴を表示します。</div>
  </div>
</section>
</div>
<div style="display:flex;justify-content:center;margin:8px 0 24px">
  <button class="secondary" onclick="window.location.href='/user-view'">Close</button>
</div>
</main>

<div class="modal-backdrop" id="formerOwnerClaimModal" onclick="closeFormerOwnerClaim(event)">
  <div class="modal" onclick="event.stopPropagation()" onkeydown="if(event.key==='Enter'&&event.target.tagName!=='TEXTAREA'){event.preventDefault();submitFormerOwnerClaim()}">
    <h2>Former Owner</h2>
    <div class="sub" id="formerOwnerClaimGuitar" style="margin-bottom:14px"></div>
    <div class="modal-grid">
      <div class="form-row">
        <label class="form-label" for="formerOwnerAcquisitionDate">Acquisition Date *</label>
        <input id="formerOwnerAcquisitionDate" type="date" required>
      </div>
      <div class="form-row">
        <label class="form-label" for="formerOwnerReleaseDate">Release Date *</label>
        <input id="formerOwnerReleaseDate" type="date" required>
      </div>
      <div class="form-row full">
        <label class="form-label" for="formerOwnerDetail">Detail（任意）</label>
        <textarea id="formerOwnerDetail" maxlength="2000" placeholder="Ownership history detail"></textarea>
      </div>
    </div>
    <div class="sub">Acquire / Release Claimを2件作成し、このUserのFormerly Owned Guitarsへ追加します。</div>
    <div class="modal-actions">
      <button class="secondary" onclick="closeFormerOwnerClaim()">キャンセル</button>
      <button id="formerOwnerClaimSubmit" onclick="submitFormerOwnerClaim()">Add Claims</button>
    </div>
  </div>
</div>

<div class="modal-backdrop" id="ownershipClaimModal" onclick="closeOwnershipClaim(event)">
  <div class="modal" onclick="event.stopPropagation()">
    <h2>Ownership</h2>
    <div class="sub" id="ownershipClaimGuitar" style="margin-bottom:14px"></div>
    <div class="form-row">
      <label class="form-label">Tag</label>
      <div id="ownershipClaimFixedTag"><strong>Acquire</strong></div>
      <select id="ownershipClaimKind" style="display:none">
        <option value="acquire">Acquire</option>
        <option value="transfer">Transfer</option>
        <option value="release">Release</option>
        <option value="inherit">Inherit</option>
      </select>
    </div>
    <div class="form-row">
      <label class="form-label" for="ownershipClaimDate">Date</label>
      <input id="ownershipClaimDate" type="date">
    </div>
    <div class="form-row" id="ownershipClaimPreviousRow">
      <label class="form-label" for="ownershipClaimPrevious">相手先・関係者（任意）</label>
      <input id="ownershipClaimPrevious" placeholder="Former owner / Recipient / Family ...">
    </div>
    <div class="form-row">
      <label class="form-label" for="ownershipClaimBody">Memo（任意）</label>
      <textarea id="ownershipClaimBody" maxlength="2000" placeholder="Ownershipに関する補足"></textarea>
    </div>
    <div class="modal-actions">
      <button class="secondary" onclick="closeOwnershipClaim()">キャンセル</button>
      <button id="ownershipClaimSubmit" onclick="submitOwnershipClaim()">Claimを追加</button>
    </div>
  </div>
</div>

<div class="modal-backdrop" id="identityCorrectionModal" onclick="closeIdentityCorrection(event)">
  <div class="modal" onclick="event.stopPropagation()">
    <h2>Identity Correction</h2>
    <div class="sub" style="margin-bottom:14px">Listingそのものは変更せず、訂正内容を履歴として残してIndividualの現在値を更新します。</div>
    <div class="modal-grid">
      <div class="form-row">
        <label class="form-label" for="identityMaker">Maker *</label>
        <input id="identityMaker" maxlength="120">
      </div>
      <div class="form-row">
        <label class="form-label" for="identityModel">Model</label>
        <input id="identityModel" maxlength="160">
      </div>
      <div class="form-row">
        <label class="form-label" for="identityYear">Year</label>
        <input id="identityYear" maxlength="40">
      </div>
      <div class="form-row">
        <label class="form-label" for="identitySerial">Serial *</label>
        <input id="identitySerial" maxlength="160">
      </div>
      <div class="form-row full">
        <label class="form-label" for="identityReason">Reason（任意）</label>
        <textarea id="identityReason" maxlength="2000" placeholder="Typo / Transcription error / Misidentification ..."></textarea>
      </div>
    </div>
    <div class="sub">保存前にMaker / Model / Serialで既存Individualとの重複を確認します。重複した場合は更新を中断します。</div>
    <div class="modal-actions">
      <button class="secondary" onclick="closeIdentityCorrection()">キャンセル</button>
      <button id="identityCorrectionSubmit" onclick="submitIdentityCorrection()">Identity Correctionを作成</button>
    </div>
  </div>
</div>

<div class="modal-backdrop" id="claimEditModal" onclick="closeClaimEdit(event)">
  <div class="modal" onclick="event.stopPropagation()">
    <h2 id="claimEditTitle">Edit Claim</h2>
    <div class="sub" id="claimEditType" style="margin-bottom:14px"></div>
    <div class="form-row">
      <label class="form-label" for="claimEditDate">Date</label>
      <input id="claimEditDate" type="date">
    </div>
    <div class="form-row">
      <label class="form-label" for="claimEditBody">Memo</label>
      <textarea id="claimEditBody" maxlength="2000"></textarea>
    </div>
    <div class="modal-actions">
      <button id="claimEditDelete" type="button" class="secondary bad" style="margin-right:auto" onclick="deactivateEditingClaim()">Delete Claim</button>
      <button class="secondary" onclick="closeClaimEdit()">キャンセル</button>
      <button id="claimEditSubmit" onclick="submitClaimEdit()">更新</button>
    </div>
  </div>
</div>

<div class="modal-backdrop" id="mediaClaimModal" onclick="closeMediaClaim(event)">
  <div class="modal" onclick="event.stopPropagation()">
    <h2>Media Claim</h2>
    <div class="sub" id="mediaClaimGuitar" style="margin-bottom:14px"></div>
    <div class="modal-grid">
      <div class="form-row full">
        <label class="form-label">Images <span class="sub">最大10枚</span></label>
        <div class="media-image-inputs" id="mediaClaimImages"><div class="media-image-slot visible" id="mediaImageSlot0"><input class="media-image-input" data-index="0" type="file" accept="image/jpeg,image/png,image/webp,image/gif" onchange="updateMediaImageSlots()"></div><div class="media-image-slot" id="mediaImageSlot1"><input class="media-image-input" data-index="1" type="file" accept="image/jpeg,image/png,image/webp,image/gif" onchange="updateMediaImageSlots()"></div><div class="media-image-slot" id="mediaImageSlot2"><input class="media-image-input" data-index="2" type="file" accept="image/jpeg,image/png,image/webp,image/gif" onchange="updateMediaImageSlots()"></div><div class="media-image-slot" id="mediaImageSlot3"><input class="media-image-input" data-index="3" type="file" accept="image/jpeg,image/png,image/webp,image/gif" onchange="updateMediaImageSlots()"></div><div class="media-image-slot" id="mediaImageSlot4"><input class="media-image-input" data-index="4" type="file" accept="image/jpeg,image/png,image/webp,image/gif" onchange="updateMediaImageSlots()"></div><div class="media-image-slot" id="mediaImageSlot5"><input class="media-image-input" data-index="5" type="file" accept="image/jpeg,image/png,image/webp,image/gif" onchange="updateMediaImageSlots()"></div><div class="media-image-slot" id="mediaImageSlot6"><input class="media-image-input" data-index="6" type="file" accept="image/jpeg,image/png,image/webp,image/gif" onchange="updateMediaImageSlots()"></div><div class="media-image-slot" id="mediaImageSlot7"><input class="media-image-input" data-index="7" type="file" accept="image/jpeg,image/png,image/webp,image/gif" onchange="updateMediaImageSlots()"></div><div class="media-image-slot" id="mediaImageSlot8"><input class="media-image-input" data-index="8" type="file" accept="image/jpeg,image/png,image/webp,image/gif" onchange="updateMediaImageSlots()"></div><div class="media-image-slot" id="mediaImageSlot9"><input class="media-image-input" data-index="9" type="file" accept="image/jpeg,image/png,image/webp,image/gif" onchange="updateMediaImageSlots()"></div></div>
      </div>
      <div class="form-row">
        <label class="form-label" for="mediaClaimDate">Date</label>
        <input id="mediaClaimDate" type="date">
      </div>
      <div class="form-row full">
        <label class="form-label" for="mediaClaimCaption">Caption</label>
        <textarea id="mediaClaimCaption" maxlength="2000" placeholder="Caption or detail"></textarea>
      </div>
    </div>
    <div class="modal-actions">
      <button class="secondary" onclick="closeMediaClaim()">キャンセル</button>
      <button id="mediaClaimSubmit" onclick="submitMediaClaim()">Claimを追加</button>
    </div>
  </div>
</div>

<div class="modal-backdrop" id="eventClaimModal" onclick="closeEventClaim(event)">
  <div class="modal" onclick="event.stopPropagation()">
    <h2>Event Claim</h2>
    <div class="sub" id="eventClaimGuitar" style="margin-bottom:14px"></div>
    <div class="modal-grid">
      <div class="form-row">
        <label class="form-label" for="eventClaimKind">Tag</label>
        <select id="eventClaimKind">
          <option value="exhibition">Exhibition</option>
          <option value="performance">Performance</option>
          <option value="recording">Recording</option>
          <option value="auction">Auction</option>
          <option value="other">Other</option>
        </select>
      </div>
      <div class="form-row">
        <label class="form-label" for="eventClaimDate">Date</label>
        <input id="eventClaimDate" type="date">
      </div>
      <div class="form-row full">
        <label class="form-label" for="eventClaimDetail">Detail</label>
        <textarea id="eventClaimDetail" maxlength="2000" placeholder="What happened?"></textarea>
      </div>
    </div>
    <div class="modal-actions">
      <button class="secondary" onclick="closeEventClaim()">キャンセル</button>
      <button id="eventClaimSubmit" onclick="submitEventClaim()">Claimを追加</button>
    </div>
  </div>
</div>

<div class="modal-backdrop" id="incidentClaimModal" onclick="closeIncidentClaim(event)">
  <div class="modal" onclick="event.stopPropagation()">
    <h2>Incident Claim</h2>
    <div class="sub" id="incidentClaimGuitar" style="margin-bottom:14px"></div>
    <div class="modal-grid">
      <div class="form-row">
        <label class="form-label" for="incidentClaimKind">Tag</label>
        <select id="incidentClaimKind">
          <option value="damage">Damage</option>
          <option value="lost">Lost</option>
          <option value="theft">Theft</option>
        </select>
      </div>
      <div class="form-row">
        <label class="form-label" for="incidentClaimDate">Date</label>
        <input id="incidentClaimDate" type="date">
      </div>
      <div class="form-row full">
        <label class="form-label" for="incidentClaimDetail">Detail</label>
        <textarea id="incidentClaimDetail" maxlength="2000" placeholder="What happened?"></textarea>
      </div>
    </div>
    <div class="modal-actions">
      <button class="secondary" onclick="closeIncidentClaim()">キャンセル</button>
      <button id="incidentClaimSubmit" onclick="submitIncidentClaim()">Claimを追加</button>
    </div>
  </div>
</div>

<div class="modal-backdrop" id="specClaimModal" onclick="closeSpecificationClaim(event)">
  <div class="modal spec-scroll-modal" onclick="event.stopPropagation()">
    <h2 id="specClaimTitle">Specification/Repair Claim</h2>
    <div class="sub" id="specClaimGuitar" style="margin-bottom:14px"></div>

    <div class="spec-kind">
      <button id="specKindSpecification" type="button" class="active" onclick="setSpecificationKind('specification')">Specification</button>
      <button id="specKindRepair" type="button" onclick="setSpecificationKind('repair')">Repair</button>
    </div>

    <div class="spec-add-wrap">
      <button type="button" class="spec-add-button" onclick="toggleSpecItemMenu(event)">＋</button>
      <div class="claim-menu spec-item-menu" id="specItemMenu"></div>
    </div>
    <span class="sub" style="margin-left:8px">項目を追加</span>

    <div class="spec-items" id="specClaimItems"></div>

    <div class="modal-grid">
      <div class="form-row">
        <label class="form-label" for="specClaimDate">Date</label>
        <input id="specClaimDate" type="date">
      </div>
      <div class="form-row full">
        <label class="form-label" for="specClaimBody">Memo（任意）</label>
        <textarea id="specClaimBody" maxlength="2000" placeholder="仕様、交換、調整、修理内容などの補足"></textarea>
      </div>
    </div>

    <div class="sub">追加した各項目は、この1件のClaimとして保存されます。Specificationには各項目の最新値が表示されます。</div>
    <div class="modal-actions">
      <button id="specClaimDelete" type="button" class="secondary bad" style="margin-right:auto;display:none" onclick="deactivateSpecificationClaim()">Delete Claim</button>
      <button class="secondary" onclick="closeSpecificationClaim()">キャンセル</button>
      <button id="specClaimSubmit" onclick="submitSpecificationClaim()">Claimを追加</button>
    </div>
  </div>
</div>

<div class="modal-backdrop" id="newGuitarModal" onclick="closeNewGuitar(event)">
  <div class="modal" onclick="event.stopPropagation()">
    <h2>新しいギターを登録する</h2>
    <div class="sub" style="margin-bottom:14px">最初のListing Claimを作成し、このUserを初期Ownerとして登録します。</div>
    <div class="modal-grid">
      <div class="form-row">
        <label class="form-label" for="newGuitarMaker">Maker *</label>
        <input id="newGuitarMaker" maxlength="120" placeholder="Fender">
      </div>
      <div class="form-row">
        <label class="form-label" for="newGuitarModel">Model</label>
        <input id="newGuitarModel" maxlength="160" placeholder="Telecaster Thinline">
      </div>
      <div class="form-row">
        <label class="form-label" for="newGuitarYear">Year</label>
        <input id="newGuitarYear" maxlength="40" placeholder="1976">
      </div>
      <div class="form-row">
        <label class="form-label" for="newGuitarFinish">Finish</label>
        <input id="newGuitarFinish" maxlength="160" placeholder="Natural">
      </div>
      <div class="form-row">
        <label class="form-label" for="newGuitarSerial">Serial *</label>
        <input id="newGuitarSerial" maxlength="160" placeholder="Serial number">
      </div>
      <div class="form-row">
        <label class="form-label" for="newGuitarDate">Listing Date</label>
        <input id="newGuitarDate" type="date">
      </div>
      <div class="form-row full">
        <label class="form-label" for="newGuitarImage">Representative Image *</label>
        <input id="newGuitarImage" type="file" accept="image/jpeg,image/png,image/webp,image/gif">
        <div class="sub" style="margin-top:5px">JPEG / PNG / WebP / GIF、12MB以下。Listing ClaimのEvidenceとしても保存します。</div>
      </div>
      <div class="form-row full">
        <label class="form-label" for="newGuitarMemo">Claim memo（任意）</label>
        <textarea id="newGuitarMemo" maxlength="2000" placeholder="初期状態についてのメモ"></textarea>
      </div>
    </div>
    <div class="sub">同じMaker / Model / SerialのIndividualが既にある場合は新規作成しません。</div>
    <div class="modal-actions">
      <button class="secondary" onclick="closeNewGuitar()">キャンセル</button>
      <button id="newGuitarSubmit" onclick="submitNewGuitar()">Listing Claimを作成</button>
    </div>
  </div>
</div>

<div class="modal-backdrop" id="claimPopupModal" onclick="closeClaimPopup(event)">
  <div class="claim-popup-modal" onclick="event.stopPropagation()">
    <div id="claimPopupContent"></div>
  </div>
</div>

<script>
let individuals=[];
let users=[];
let activeUser=null;
let selectedIndividualId=null;
let productGallery=[];
let productGalleryIndex=0;
let currentObservations=[];
let currentClaims=[];
let currentIndividual=null;
let chronicleSort='event';
let individualSortKey='id';
let individualSortDirection=1;
const ACTIVE_USER_KEY='ygc_active_user_id';

const esc=s=>String(s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[m]));
async function jfetch(url,opt={}){
  const r=await fetch(url,opt);
  const d=await r.json().catch(()=>({}));
  if(!r.ok)throw new Error(d.detail||r.statusText);
  return d;
}

async function loadUsers(){
  users=await jfetch('/api/users');
  const select=document.getElementById('activeUserSelect');
  const saved=localStorage.getItem(ACTIVE_USER_KEY)||'';
  select.innerHTML='<option value="">User未選択</option>'+users.map(u=>'<option value="'+u.id+'">'+esc(u.display_name)+' (#'+u.id+')</option>').join('');
  const target=users.some(u=>String(u.id)===String(saved))?saved:'';
  select.value=target;
  if(target){
    await loadActiveUser();
  }else{
    activeUser=null;
    localStorage.removeItem(ACTIVE_USER_KEY);
    renderAccount();
  }
}

async function createUser(){
  try{
    const d=await jfetch('/api/users',{method:'POST'});
    localStorage.setItem(ACTIVE_USER_KEY,String(d.user.id));
    window.location.href='/user-view';
  }catch(e){
    alert('アカウント作成に失敗しました。\\n'+e.message);
  }
}

async function setActiveUser(value){
  selectedIndividualId=null;
  if(value){
    localStorage.setItem(ACTIVE_USER_KEY,String(value));
    window.location.href='/user-view';
    return;
  }
  localStorage.removeItem(ACTIVE_USER_KEY);
  activeUser=null;
  renderAccount();
}

async function loadActiveUser(){
  const id=localStorage.getItem(ACTIVE_USER_KEY);
  if(!id){
    activeUser=null;
    renderAccount();
    return;
  }
  try{
    activeUser=await jfetch('/api/users/'+id);
    renderAccount();
    const firstOwned=(activeUser.guitars||[]).find(g=>g.ownership_status==='current_owner');
    if(firstOwned&&selectedIndividualId===null){
      await showIndividual(firstOwned.individual_id);
    }
  }catch(e){
    activeUser=null;
    localStorage.removeItem(ACTIVE_USER_KEY);
    renderAccount();
  }
}

function renderAccount(){
  const el=document.getElementById('accountPanel');
  if(!activeUser||!activeUser.user){
    el.className='sub';
    el.textContent='アカウントを選択してください。';
    return;
  }
  const u=activeUser.user;
  const allGuitars=activeUser.guitars||[];
  const guitars=allGuitars.filter(g=>g.ownership_status==='current_owner');
  const formerGuitars=allGuitars.filter(g=>g.ownership_status==='former_owner');
  el.className='';
  el.innerHTML=
    '<div class="user-profile-row">'+
      '<img class="user-avatar" id="userAvatarPreview" src="/api/users/'+u.id+'/avatar?v='+encodeURIComponent(u.updated_at||'')+'" alt="'+esc(u.display_name||'User')+'" onerror="this.onerror=null;this.src=\'/assets/no-icon.svg\'">'+
      '<div class="user-avatar-controls"><span class="detail-meta-label">User Image</span><input id="accountAvatar" type="file" accept="image/jpeg,image/png,image/webp,image/gif" onchange="uploadUserAvatar(this)"><div class="sub">JPEG / PNG / WebP / GIF、12MB以下</div></div>'+
    '</div>'+
    '<div class="detail-meta-grid">'+
      '<div class="detail-meta-item"><span class="detail-meta-label">Display Name</span><input id="accountName" value="'+esc(u.display_name||'')+'"></div>'+
      '<div class="detail-meta-item"><span class="detail-meta-label">Account Type</span><select id="accountType"><option value="user"'+(u.account_type==='user'?' selected':'')+'>User</option><option value="shop"'+(u.account_type==='shop'?' selected':'')+'>Shop</option></select></div>'+
      '<div class="detail-meta-item"><span class="detail-meta-label">Country</span><input id="accountCountry" value="'+esc(u.location_country||'')+'"></div>'+
      '<div class="detail-meta-item"><span class="detail-meta-label">Region</span><input id="accountRegion" value="'+esc(u.location_region||'')+'"></div>'+
    '</div>'+
    '<div class="toolbar" style="margin-top:10px"><button onclick="saveUser()">保存</button><span class="sub">User ID '+esc(u.id)+'</span></div>'+
    '<div class="detail-section">Owned Guitars</div>'+
    (guitars.length
      ? '<div class="owned-list" id="ownedGuitarList">'+
        '<div class="owned-row" style="background:transparent;border:0;padding-top:0;padding-bottom:2px">'+
          '<div></div><div class="owned-head">Guitar</div><div class="owned-head">Year</div><div class="owned-head">Finish</div><div class="owned-head">Serial</div><div class="owned-head">Status</div>'+
        '</div>'+
        guitars.map(g=>
          '<div class="owned-row" draggable="true" data-individual-id="'+g.individual_id+'" onclick="ownedRowClick(event,'+g.individual_id+')" ondragstart="ownedDragStart(event)" ondragover="ownedDragOver(event)" ondrop="ownedDrop(event)" ondragend="ownedDragEnd(event)">'+
            '<div class="drag-handle" title="ドラッグして並び替え">☰</div>'+
            '<div class="owned-cell" title="'+esc(g.manufacturer)+' '+esc(g.model||'')+'">'+esc(g.manufacturer)+' '+esc(g.model||'')+'</div>'+
            '<div class="owned-cell">'+esc(g.year||'—')+'</div>'+
            '<div class="owned-cell" title="'+esc(g.finish||'')+'">'+esc(g.finish||'—')+'</div>'+
            '<div class="owned-cell mono" title="'+esc(g.serial_number||'')+'">'+esc(g.serial_number||'—')+'</div>'+
            '<div class="owned-cell">'+esc(g.ownership_status||'')+'</div>'+
          '</div>'
        ).join('')+
        '</div>'
      : '<div class="sub">まだ所有ギターは登録されていません。</div>')+
    '<div class="toolbar" style="margin-top:12px"><button onclick="registerNewGuitar()">新しいギターを登録する</button></div>'+
    '<div class="detail-section">Formerly Owned Guitars</div>'+
    (formerGuitars.length
      ? '<div class="owned-list">'+
        '<div class="owned-row" style="background:transparent;border:0;padding-top:0;padding-bottom:2px">'+
          '<div></div><div class="owned-head">Guitar</div><div class="owned-head">Year</div><div class="owned-head">Finish</div><div class="owned-head">Serial</div><div class="owned-head">Status</div>'+
        '</div>'+
        formerGuitars.map(g=>
          '<div class="owned-row" data-individual-id="'+g.individual_id+'" onclick="showIndividual('+g.individual_id+')">'+
            '<div></div>'+
            '<div class="owned-cell" title="'+esc(g.manufacturer)+' '+esc(g.model||'')+'">'+esc(g.manufacturer)+' '+esc(g.model||'')+'</div>'+
            '<div class="owned-cell">'+esc(g.year||'—')+'</div>'+
            '<div class="owned-cell" title="'+esc(g.finish||'')+'">'+esc(g.finish||'—')+'</div>'+
            '<div class="owned-cell mono" title="'+esc(g.serial_number||'')+'">'+esc(g.serial_number||'—')+'</div>'+
            '<div class="owned-cell">Former Owner</div>'+
          '</div>'
        ).join('')+
        '</div>'
      : '<div class="sub">過去に所有していたギターはまだありません。</div>');
}

let ownedDraggedId=null;
let ownedDidDrag=false;
function ownedRowClick(event,individualId){
  if(ownedDidDrag){
    ownedDidDrag=false;
    return;
  }
  showIndividual(individualId);
}
function ownedDragStart(event){
  const row=event.currentTarget;
  ownedDraggedId=Number(row.dataset.individualId);
  row.classList.add('dragging');
  event.dataTransfer.effectAllowed='move';
}
function ownedDragOver(event){
  event.preventDefault();
  ownedDidDrag=true;
  const row=event.currentTarget;
  if(Number(row.dataset.individualId)===ownedDraggedId)return;
  const list=document.getElementById('ownedGuitarList');
  const dragging=list&&list.querySelector('.owned-row.dragging');
  if(!dragging)return;
  const rect=row.getBoundingClientRect();
  if(event.clientY<rect.top+rect.height/2)list.insertBefore(dragging,row);
  else list.insertBefore(dragging,row.nextSibling);
}
function ownedDrop(event){
  event.preventDefault();
}
async function ownedDragEnd(event){
  event.currentTarget.classList.remove('dragging');
  ownedDraggedId=null;
  setTimeout(()=>{ownedDidDrag=false},0);
  const list=document.getElementById('ownedGuitarList');
  if(!list||!activeUser||!activeUser.user)return;
  const ids=[...list.querySelectorAll('.owned-row[data-individual-id]')].map(row=>Number(row.dataset.individualId));
  try{
    activeUser=await jfetch('/api/users/'+activeUser.user.id+'/guitar-order',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({individual_ids:ids})
    });
    renderAccount();
  }catch(e){
    alert('並び替えの保存に失敗しました。\n'+e.message);
    await loadActiveUser();
  }
}

function registerNewGuitar(){
  if(!activeUser||!activeUser.user){
    alert('先にUserを選択してください。');
    return;
  }
  document.getElementById('newGuitarMaker').value='';
  document.getElementById('newGuitarModel').value='';
  document.getElementById('newGuitarYear').value='';
  document.getElementById('newGuitarFinish').value='';
  document.getElementById('newGuitarSerial').value='';
  document.getElementById('newGuitarDate').value=new Date().toISOString().slice(0,10);
  document.getElementById('newGuitarImage').value='';
  document.getElementById('newGuitarMemo').value='';
  document.getElementById('newGuitarModal').classList.add('open');
  document.getElementById('newGuitarMaker').focus();
}
function closeNewGuitar(event){
  if(event&&event.target&&event.target.id!=='newGuitarModal')return;
  document.getElementById('newGuitarModal').classList.remove('open');
}
async function submitNewGuitar(){
  if(!activeUser||!activeUser.user)return;
  const manufacturer=document.getElementById('newGuitarMaker').value.trim();
  const serial=document.getElementById('newGuitarSerial').value.trim();
  const imageInput=document.getElementById('newGuitarImage');
  const image=imageInput.files&&imageInput.files[0];
  if(!manufacturer||!serial){
    alert('Maker と Serial は必須です。');
    return;
  }
  if(!image){
    alert('Representative Image は必須です。');
    return;
  }
  const button=document.getElementById('newGuitarSubmit');
  button.disabled=true;
  try{
    const form=new FormData();
    form.append('manufacturer',manufacturer);
    form.append('serial_number',serial);
    form.append('model',document.getElementById('newGuitarModel').value.trim());
    form.append('year',document.getElementById('newGuitarYear').value.trim());
    form.append('finish',document.getElementById('newGuitarFinish').value.trim());
    form.append('occurred_at',document.getElementById('newGuitarDate').value||'');
    form.append('body',document.getElementById('newGuitarMemo').value.trim());
    form.append('representative_image',image);
    const d=await jfetch('/api/users/'+activeUser.user.id+'/new-guitar',{
      method:'POST',
      body:form
    });
    activeUser={user:d.user,guitars:d.guitars};
    closeNewGuitar();
    renderAccount();
    selectedIndividualId=Number(d.individual_id);
    await showIndividual(d.individual_id);
  }catch(e){
    alert('新規ギター登録に失敗しました.\n'+e.message);
  }finally{
    button.disabled=false;
  }
}

async function uploadUserAvatar(input){
  if(!activeUser||!activeUser.user||!input||!input.files||!input.files[0])return;
  const form=new FormData();
  form.append('avatar',input.files[0]);
  input.disabled=true;
  try{
    await jfetch('/api/users/'+activeUser.user.id+'/avatar',{
      method:'POST',
      body:form
    });
    activeUser=await jfetch('/api/users/'+activeUser.user.id);
    renderAccount();
  }catch(e){
    alert('ユーザー画像の保存に失敗しました。\\n'+e.message);
    input.disabled=false;
  }
}

async function saveUser(){
  if(!activeUser||!activeUser.user)return;
  const id=activeUser.user.id;
  const body={
    display_name:document.getElementById('accountName').value.trim(),
    account_type:document.getElementById('accountType').value,
    location_country:document.getElementById('accountCountry').value.trim()||null,
    location_region:document.getElementById('accountRegion').value.trim()||null
  };
  try{
    activeUser=await jfetch('/api/users/'+id,{
      method:'PATCH',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body)
    });
    await loadUsers();
    document.getElementById('activeUserSelect').value=String(id);
  }catch(e){
    alert('アカウント保存に失敗しました。\\n'+e.message);
  }
}

async function loadIndividuals(){
  individuals=await jfetch('/api/individuals');
  renderIndividuals();
}

function normalizeSortValue(value,key){
  if(key==='id'||key==='claim_count')return Number(value||0);
  return String(value??'').toLowerCase();
}
function setIndividualSort(key){
  if(individualSortKey===key)individualSortDirection*=-1;
  else{individualSortKey=key;individualSortDirection=1}
  renderIndividuals();
}
function updateSortIndicators(){
  for(const key of ['id','manufacturer','model','finish','year','serial_number','claim_count']){
    const el=document.getElementById('sort-'+key);
    if(el)el.textContent=individualSortKey===key?(individualSortDirection===1?'▲':'▼'):'';
  }
}
function renderIndividuals(){
  const q=document.getElementById('individualFilter').value.toLowerCase();
  const rows=individuals
    .filter(x=>[x.manufacturer,x.model,x.finish,x.year,x.serial_number].join(' ').toLowerCase().includes(q))
    .slice()
    .sort((a,b)=>{
      const av=normalizeSortValue(a[individualSortKey],individualSortKey);
      const bv=normalizeSortValue(b[individualSortKey],individualSortKey);
      if(av<bv)return-1*individualSortDirection;
      if(av>bv)return 1*individualSortDirection;
      return Number(a.id)-Number(b.id);
    });
  updateSortIndicators();
  document.getElementById('individualBody').innerHTML=rows.map(x=>
    '<tr class="clickable" onclick="showIndividual('+x.id+')">'+
      '<td>'+x.id+'</td><td>'+esc(x.manufacturer)+'</td><td>'+esc(x.model)+'</td><td>'+esc(x.finish||'')+'</td><td>'+esc(x.year||'')+'</td><td class="mono">'+esc(x.serial_number)+'</td><td>'+x.claim_count+'</td>'+
    '</tr>'
  ).join('');
}

function sourceName(o){
  return String(o.source_site||'').toLowerCase()==='reverb'?'Reverb':String(o.source_site||'Source');
}
function ownerLabel(o){
  const name=String(o.owner_user_name||o.owner_name||o.seller||'').trim();
  if(!name)return '';
  const type=String(o.owner_type||'').trim();
  return type==='shop'?name+' (Shop)':(type==='user'?name+' (User)':name);
}
function currentOwnerHtml(o){
  if(!o)return '—';
  const name=String(o.owner_user_name||o.owner_name||o.seller||'').trim();
  if(!name)return '—';
  const type=String(o.owner_type||'').trim();
  const listingUrl=String(o.source_url||'').trim();
  const label=type==='shop'?name+' (Shop)':name;
  if(type==='shop'&&listingUrl)return '<a href="'+esc(listingUrl)+'" target="_blank" rel="noopener noreferrer">'+esc(label)+'</a>';
  return esc(label);
}
function currentSnapshotOwnerHtml(i){
  if(!i)return '—';
  const name=String(i.current_owner_name||'').trim();
  if(!name)return '—';
  const type=String(i.current_owner_type||'').trim();
  const listingUrl=String(i.current_owner_source_url||'').trim();
  const label=type==='shop'?name+' (Shop)':name;
  if(i.current_owner_user_id)return '<a href="/users/'+Number(i.current_owner_user_id)+'">'+esc(label)+'</a>';
  if(type==='shop'&&listingUrl)return '<a href="'+esc(listingUrl)+'" target="_blank" rel="noopener noreferrer">'+esc(label)+'</a>';
  return esc(label);
}
function currentLocationHtml(o){
  if(!o)return '—';
  const country=String(o.location_country||'').trim();
  const region=String(o.location_region||'').trim();
  const value=[country,region].filter(Boolean).join(' / ');
  return value?esc(value):'—';
}
function observationCard(o,isLatest){
  const url=String(o.source_url||'');
  const source=sourceName(o);
  const sourceHtml=url?'<a href="'+esc(url)+'" target="_blank" rel="noopener noreferrer">'+esc(source)+'</a>':esc(source);
  const owner=ownerLabel(o);
  const seller=String(o.seller||'').trim();
  let rows='';
  if(owner)rows+='<div class="observation-row"><div class="observation-label">Owner</div><div class="observation-value">'+esc(owner)+'</div></div>';
  if(seller&&seller!==String(o.owner_user_name||o.owner_name||'').trim())rows+='<div class="observation-row"><div class="observation-label">Shop</div><div class="observation-value">'+esc(seller)+'</div></div>';
  const location=[o.location_country,o.location_region].filter(Boolean).join(' / ');
  if(location)rows+='<div class="observation-row"><div class="observation-label">Location</div><div class="observation-value">'+esc(location)+'</div></div>';
  if(o.title)rows+='<div class="observation-row"><div class="observation-label">Listing</div><div class="observation-value observation-title">'+esc(o.title)+'</div></div>';
  const specs=[o.model&&('Model: '+o.model),o.finish&&('Finish: '+o.finish),o.year&&('Year: '+o.year)].filter(Boolean).join(' / ');
  if(specs)rows+='<div class="observation-row"><div class="observation-label">Info</div><div class="observation-value">'+esc(specs)+'</div></div>';
  if(url)rows+='<div class="observation-row"><div class="observation-label">URL</div><div class="observation-value"><a href="'+esc(url)+'" target="_blank" rel="noopener noreferrer">Open listing</a></div></div>';
  return '<div class="observation-card'+(isLatest?' latest':'')+'"><div class="observation-card-head"><div class="observation-date">'+esc(o.listing_date||o.observed_at||'')+'</div><div class="observation-source">Source: '+sourceHtml+'</div></div>'+rows+'</div>';
}

function activeUserOwns(individualId){
  return !!(activeUser&&(activeUser.guitars||[]).some(g=>Number(g.individual_id)===Number(individualId)&&g.ownership_status==='current_owner'));
}
function ownershipControlsHtml(individualId){
  if(!activeUser||!activeUser.user)return '<div class="sub" style="margin-top:10px">Chronicleに追加するにはUserを選択してください。</div>';
  if(activeUserOwns(individualId)){
    return '<div class="toolbar" style="margin-top:10px"><span class="status good">Your Guitar</span></div>';
  }
  return '<div class="toolbar" style="margin-top:10px"><button onclick="openOwnershipClaim('+individualId+',\'acquire\')">Add to Your Chronicle</button></div>';
}

function productGalleryHtml(images,model){
  productGallery=(images||[]).slice();
  productGalleryIndex=0;
  if(!productGallery.length)return '';
  const item=productGallery[0];
  const disabled=productGallery.length<2?' disabled':'';
  const caption=String(item.caption||'').trim();
  const source=String(item.label||'Uploaded Image')+(caption?' — '+caption:'')+' (1/'+productGallery.length+')';
  return '<div class="detail-gallery">'+
    '<button class="detail-gallery-nav" onclick="stepProductGallery(-1)"'+disabled+'>◀</button>'+
    '<img class="detail-image" id="productGalleryImage" src="'+esc(item.url)+'" alt="'+esc(model||'Guitar')+'" loading="lazy" onerror="this.onerror=null;this.src=\'/assets/no-picture.svg\'">'+
    '<button class="detail-gallery-nav" onclick="stepProductGallery(1)"'+disabled+'>▶</button>'+
    '</div><span class="detail-source" id="productGallerySource">'+esc(source)+'</span>';
}
function stepProductGallery(delta){
  if(productGallery.length<2)return;
  productGalleryIndex=(productGalleryIndex+delta+productGallery.length)%productGallery.length;
  const item=productGallery[productGalleryIndex];
  const image=document.getElementById('productGalleryImage');
  const source=document.getElementById('productGallerySource');
  if(image)image.src=item.url;
  if(source){
    const caption=String(item.caption||'').trim();
    source.textContent=String(item.label||'Uploaded Image')+(caption?' — '+caption:'')+' ('+(productGalleryIndex+1)+'/'+productGallery.length+')';
  }
}
function specificationFieldLabel(value){
  const labels={
    nut:'Nut',
    frets:'Frets',
    pickguard:'Pickguard',
    potentiometers:'Potentiometers',
    wiring:'Wiring',
    neck:'Neck',
    pickups:'Pickups',
    bridge:'Bridge',
    tuners:'Tuners',
    body:'Body',
    fingerboard:'Fingerboard',
    finish:'Finish',
    weight:'Weight'
  };
  const key=String(value||'').trim();
  return labels[key]||key.replace(/_/g,' ').replace(/\b\w/g,m=>m.toUpperCase());
}
function identityFieldLabel(value){
  const labels={
    manufacturer:'Maker',
    model:'Model',
    year:'Year',
    serial_number:'Serial'
  };
  return labels[String(value||'')]||String(value||'').replace(/_/g,' ');
}
function claimTypeLabel(value){
  return String(value||'claim').split('_').map(x=>x?x[0].toUpperCase()+x.slice(1):'').join(' ');
}
function displayEventDate(value){
  if(!value)return '日付不明';
  const text=String(value).trim();
  const direct=text.match(/^(\d{4}-\d{2}-\d{2})/);
  if(direct)return direct[1];
  const d=new Date(text);
  if(Number.isNaN(d.getTime()))return text;
  const year=d.getFullYear();
  const month=String(d.getMonth()+1).padStart(2,'0');
  const day=String(d.getDate()).padStart(2,'0');
  return year+'-'+month+'-'+day;
}
function displayInputDate(value){
  if(!value)return '入力日時不明';
  const d=new Date(String(value));
  return Number.isNaN(d.getTime())?String(value):d.toLocaleString('ja-JP');
}
function claimHeaderHtml(c,type,eventDate){
  let response='';
  const isOwner=activeUser&&activeUser.user&&activeUserOwns(selectedIndividualId);
  const isOtherUser=isOwner&&Number(c.author_user_id)!==Number(activeUser.user.id);
  const verifiableTypes=new Set(['specification','incident','event','media']);
  const isFormerOwnerOwnership=(
    c.claim_type==='ownership'
    && String(c.ownership_source||'')==='former_owner'
  );
  if(isOtherUser&&(verifiableTypes.has(String(c.claim_type||''))||isFormerOwnerOwnership)){
    const current=String(c.verification_status||'unverified').toLowerCase();
    response='<select class="claim-response-select" onchange="setClaimResponse('+c.id+',this.value)">'+
      '<option value="positive"'+(current==='positive'?' selected':'')+'>Positive</option>'+
      '<option value="negative"'+(current==='negative'?' selected':'')+'>Negative</option>'+
      '<option value="unverified"'+(current==='unverified'?' selected':'')+'>Unverified</option>'+
      '</select>';
  }
  return '<span class="claim-badge">'+esc(type)+'</span>'+response+'<span class="claim-event-date">'+esc(eventDate)+'</span>';
}
function claimVisualTypeClass(c){
  if(c.claim_type==='ownership'||c.claim_type==='owner_change'||c.claim_type==='release')return ' claim-type-ownership';
  if(c.claim_type==='specification')return ' claim-type-specification';
  if(c.claim_type==='incident')return ' claim-type-incident';
  if(c.claim_type==='event')return ' claim-type-event';
  if(c.claim_type==='media')return ' claim-type-media';
  return '';
}
function claimCardFull(c){
  const type=c.claim_type==='specification'
    ? (c.specification_kind==='repair'?'Repair':'Specification')
    : (c.claim_type==='ownership'?claimTypeLabel(c.ownership_kind||'acquire'):(c.claim_type==='incident'?claimTypeLabel(c.value_text||'incident'):(c.claim_type==='event'?claimTypeLabel(c.value_text||'event'):(c.claim_type==='release'?'Release':claimTypeLabel(c.claim_type)))));
  const eventDate=displayEventDate(c.occurred_at);
  let body='';
  if(c.claim_type==='ownership'){
    const kind=String(c.ownership_kind||'acquire');
    const owner=String(c.author_name||'User').trim()||'User';
    const raw=String(c.observation_raw_text||'');
    const firstLine=(raw.split(/\r?\n/)[0]||'').trim();
    const party=firstLine.startsWith('Previous owner:')
      ? (firstLine.slice('Previous owner:'.length).trim()||'Unknown')
      : 'Unknown';
    if(kind==='release'){
      body='<div><strong>'+esc(owner)+' released this product.</strong></div>';
    }else if(kind==='transfer'){
      body='<div><strong>'+esc(party)+' acquired this product from '+esc(owner)+'.</strong></div>';
    }else if(kind==='inherit'){
      body='<div><strong>'+esc(party)+' inherited this product from '+esc(owner)+'.</strong></div>';
    }else{
      body='<div><strong>'+esc(owner)+' became the owner of this product.</strong></div>';
    }
    if(c.body)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }else if(c.claim_type==='incident'){
    if(c.body)body+='<div><strong>'+esc(c.body)+'</strong></div>';
  }else if(c.claim_type==='event'){
    if(c.body)body+='<div><strong>'+esc(c.body)+'</strong></div>';
  }else if(c.claim_type==='owner_change'){
    body='<div><strong>'+esc(c.author_name||'User')+' has become the owner.</strong></div>';
    if(c.body)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }else if(c.claim_type==='release'){
    body='<div><strong>Ownership released. Current owner is Unknown.</strong></div>';
    if(c.body)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }else if(c.claim_type==='specification'){
    const items=(c.spec_items&&c.spec_items.length)
      ? c.spec_items
      : (c.field_name?[{field_name:c.field_name,value_text:c.value_text}]:[]);
    body=items.map(item=>'<div><strong>'+esc(specificationFieldLabel(item.field_name))+': '+esc(item.value_text||'')+'</strong></div>').join('');
    if(c.body)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }else if(c.claim_type==='identity_correction'){
    const items=c.identity_items||[];
    body=items.map(item=>
      '<div><strong>'+esc(identityFieldLabel(item.field_name))+':</strong> '+
      esc(item.old_value||'—')+' → '+esc(item.new_value||'—')+'</div>'
    ).join('');
    if(c.body)body+='<div class="claim-memo">Reason: '+esc(c.body)+'</div>';
  }else if(c.claim_type==='media'){
    const mediaImages=(c.media_images&&c.media_images.length)
      ? c.media_images
      : (c.evidence_media_id?[{id:c.evidence_media_id,url:'/api/media/'+encodeURIComponent(c.evidence_media_id)}]:[]);
    if(mediaImages.length){
      body+='<div class="claim-media-thumbs">'+mediaImages.map(m=>'<img class="claim-evidence-image" width="48" height="48" style="width:48px!important;height:48px!important;max-width:48px!important;max-height:48px!important;object-fit:cover" src="'+esc(m.url)+'" alt="Media Claim image" loading="lazy" onerror="this.onerror=null;this.src=\'/assets/no-picture.svg\'">').join('')+'</div>';
    }
    if(c.body)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }else if(c.claim_type==='listing'){
    const title=c.listing_title||c.body||'Listing observed';
    body='<div><strong>'+esc(title)+'</strong></div>';
    const details=[];
    const listingOwner=String(c.observed_owner_name||'').trim();
    const seller=String(c.seller||'').trim();
    if(listingOwner&&listingOwner!==seller)details.push('Owner: '+listingOwner);
    if(seller)details.push('Seller: '+seller);
    const location=[c.location_country,c.location_region].filter(Boolean).join(' / ');
    if(location)details.push('Location: '+location);
    const specs=[
      c.observed_model&&('Model: '+c.observed_model),
      c.observed_finish&&('Finish: '+c.observed_finish),
      c.observed_year&&('Year: '+c.observed_year),
      c.observed_serial_number&&('Serial: '+c.observed_serial_number)
    ].filter(Boolean).join(' / ');
    if(specs)details.push(specs);
    if(details.length)body+='<div class="claim-memo">'+details.map(esc).join('<br>')+'</div>';
    if(c.body&&c.body!==title)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
    if(c.source_url)body+='<div class="claim-memo"><a href="'+esc(c.source_url)+'" target="_blank" rel="noopener noreferrer">Open listing</a></div>';
  }else{
    if(c.value_text)body+='<div><strong>'+esc(c.value_text)+'</strong></div>';
    if(c.body)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }
  if(c.evidence_media_id&&c.claim_type!=='media'){
    body+='<div class="claim-memo"><img class="claim-evidence-image" width="48" height="48" style="width:48px;height:48px;max-width:48px;max-height:48px;object-fit:cover" src="/api/media/'+encodeURIComponent(c.evidence_media_id)+'" alt="Claim evidence" loading="lazy" onerror="this.onerror=null;this.src=\'/assets/no-picture.svg\'"></div>';
  }
  const good=String(Number(c.good_count||0)).padStart(2,'0');
  const bad=String(Number(c.bad_count||0)).padStart(2,'0');
  const votes='<div class="claim-votes">'+
    '<button class="claim-vote'+(c.viewer_vote==='good'?' active':'')+'" onclick="voteClaim('+c.id+',\'good\')">👍 '+good+'</button>'+
    '<button class="claim-vote'+(c.viewer_vote==='bad'?' active':'')+'" onclick="voteClaim('+c.id+',\'bad\')">👎 '+bad+'</button>'+
    '</div>';
  const canEdit=activeUser&&activeUser.user&&c.status==='active'&&c.claim_type!=='identity_correction'&&Number(c.author_user_id)===Number(activeUser.user.id);
  const editButton=canEdit?'<button class="claim-vote" onclick="editOwnClaim('+c.id+')">Edit</button>':'';
  return '<div class="claim-card'+claimVisualTypeClass(c)+(c.claim_type==='identity_correction'?' identity-correction-card':'')+'">'+
    '<div class="claim-head">'+claimHeaderHtml(c,type,eventDate)+'</div>'+
    '<div class="claim-body">'+body+'</div>'+
    '<div class="claim-footer"><div style="display:flex;gap:6px;align-items:center">'+votes+editButton+'</div><div class="claim-footer-meta">'+esc(displayInputDate(c.created_at))+' · By <a href="/users/'+Number(c.author_user_id)+'">'+esc(c.author_name||('User #'+c.author_user_id))+'</a></div></div>'+
    '</div>';
}
function compactClaimType(c){
  return c.claim_type==='specification'
    ? (c.specification_kind==='repair'?'Repair':'Specification')
    : (c.claim_type==='ownership'?claimTypeLabel(c.ownership_kind||'acquire')
      :(c.claim_type==='incident'?claimTypeLabel(c.value_text||'incident')
      :(c.claim_type==='event'?claimTypeLabel(c.value_text||'event')
      :(c.claim_type==='release'?'Release':claimTypeLabel(c.claim_type)))));
}
function claimCard(c){
  const verification=String(c.verification_status||'positive').toLowerCase();
  if(verification==='positive')return claimCardFull(c);
  if(verification==='unverified'){
    return '<div class="claim-compact-row"><button type="button" class="claim-compact-tag'+claimVisualTypeClass(c)+'" onclick="openClaimPopup('+c.id+',this)">'+esc(compactClaimType(c))+'</button></div>';
  }
  if(verification==='negative'){
    return '<div class="claim-compact-row"><button type="button" class="claim-negative-dot" title="Negative Claim" onclick="openClaimPopup('+c.id+',this)">◉</button></div>';
  }
  return claimCardFull(c);
}
function positionClaimPopup(trigger){
  const backdrop=document.getElementById('claimPopupModal');
  const popup=backdrop?backdrop.querySelector('.claim-popup-modal'):null;
  const chronicle=document.getElementById('chronicleEntries');
  if(!backdrop||!popup||!chronicle||!trigger)return;

  const triggerRect=trigger.getBoundingClientRect();
  const chronicleRect=chronicle.getBoundingClientRect();
  const marginLeft=22;
  const edge=10;
  const width=Math.max(220,chronicleRect.width-marginLeft);
  const preferredLeft=chronicleRect.left+marginLeft-(width*0.5);
  const left=Math.min(
    Math.max(edge,preferredLeft),
    Math.max(edge,window.innerWidth-width-edge)
  );

  popup.style.width=width+'px';
  popup.style.left=left+'px';
  popup.style.top=Math.min(
    window.innerHeight-edge,
    triggerRect.bottom+6
  )+'px';

  requestAnimationFrame(()=>{
    const popupRect=popup.getBoundingClientRect();
    let top=triggerRect.bottom+6;
    if(top+popupRect.height>window.innerHeight-edge){
      top=triggerRect.top-popupRect.height-6;
    }
    if(top<edge)top=edge;
    popup.style.top=top+'px';
  });
}
function openClaimPopup(claimId,trigger){
  const claim=currentClaims.find(c=>Number(c.id)===Number(claimId));
  if(!claim)return;
  const content=document.getElementById('claimPopupContent');
  if(content)content.innerHTML=claimCardFull(claim);
  const modal=document.getElementById('claimPopupModal');
  if(modal){
    modal.classList.add('open');
    positionClaimPopup(trigger);
  }
}
function closeClaimPopup(event){
  if(event&&event.target&&event.target.id!=='claimPopupModal')return;
  const modal=document.getElementById('claimPopupModal');
  if(modal)modal.classList.remove('open');
}

function chronologyValue(c,mode){
  if(mode==='input')return String(c.created_at||'');
  return String(c.occurred_at||c.created_at||'');
}
function renderChronicle(){
  const sorted=currentClaims.slice().sort((a,b)=>{
    const av=chronologyValue(a,chronicleSort);
    const bv=chronologyValue(b,chronicleSort);
    if(av<bv)return 1;
    if(av>bv)return -1;
    return Number(b.id)-Number(a.id);
  });
  const correctionsByTarget=new Map();
  const roots=[];
  for(const claim of sorted){
    if(claim.claim_type==='identity_correction'&&claim.target_claim_id){
      const key=Number(claim.target_claim_id);
      if(!correctionsByTarget.has(key))correctionsByTarget.set(key,[]);
      correctionsByTarget.get(key).push(claim);
    }else{
      roots.push(claim);
    }
  }
  const claims=[];
  for(const claim of roots){
    claims.push(claim);
    const corrections=correctionsByTarget.get(Number(claim.id))||[];
    corrections.sort((a,b)=>String(a.created_at||'').localeCompare(String(b.created_at||'')));
    claims.push(...corrections);
    correctionsByTarget.delete(Number(claim.id));
  }
  for(const corrections of correctionsByTarget.values())claims.push(...corrections);
  const el=document.getElementById('chronicleEntries');
  if(el)el.innerHTML=claims.length
    ? claims.map(claimCard).join('')
    : '<div class="sub">Claimはまだありません。</div>';
}
function setChronicleSort(value){
  chronicleSort=value==='input'?'input':'event';
  renderChronicle();
}

async function setClaimResponse(claimId,stance){
  if(!activeUser||!activeUser.user)return;
  try{
    await jfetch('/api/claims/'+claimId+'/response',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        responder_user_id:Number(activeUser.user.id),
        stance
      })
    });
    closeClaimPopup();
    if(selectedIndividualId!==null)await showIndividual(selectedIndividualId);
  }catch(e){
    alert('Owner Verificationの更新に失敗しました。\n'+e.message);
    if(selectedIndividualId!==null)await showIndividual(selectedIndividualId);
  }
}

async function voteClaim(claimId,vote){
  if(!activeUser||!activeUser.user){
    window.location.href='/user-view/edit';
    return;
  }
  try{
    await jfetch('/api/claims/'+claimId+'/vote',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({user_id:Number(activeUser.user.id),vote})
    });
    if(selectedIndividualId!==null)await showIndividual(selectedIndividualId);
  }catch(e){
    alert('Voteの更新に失敗しました。\n'+e.message);
  }
}

async function showIndividual(id){
  selectedIndividualId=Number(id);
  const [d,claims,currentSpecifications]=await Promise.all([
    jfetch('/api/individuals/'+id),
    jfetch('/api/individuals/'+id+'/claims'+(activeUser&&activeUser.user?'?viewer_user_id='+encodeURIComponent(activeUser.user.id):'')),
    jfetch('/api/individuals/'+id+'/current-specifications')
  ]);
  const i=d.individual;
  currentIndividual=i;
  const observations=d.observations||[];
  currentObservations=observations;
  currentClaims=claims||[];
  const latest=observations.length?observations[observations.length-1]:null;
  const imageListing=(claims||[]).slice().reverse().find(c=>c.claim_type==='listing'&&c.status==='active'&&c.image_url)||null;
  const imageObservation=observations.slice().reverse().find(o=>o.image_url)||null;
  const galleryImages=d.gallery_images||[];
  let out='';
  if(galleryImages.length){
    out+=productGalleryHtml(galleryImages,i.model||'Guitar');
  }else if(i.representative_image_url){
    out+='<img class="detail-image" src="'+esc(i.representative_image_url)+'" alt="'+esc(i.model||'Guitar')+'" loading="lazy" onerror="this.onerror=null;this.src=\'/assets/no-picture.svg\'"><span class="detail-source">Representative Image</span>';
  }else if(imageListing){
    const imageUrl=String(imageListing.source_url||'');
    const image='<img class="detail-image" src="'+esc(imageListing.image_url)+'" alt="'+esc(imageListing.listing_title||i.model||'Guitar')+'" loading="lazy" referrerpolicy="no-referrer" onerror="this.onerror=null;this.src=\'/assets/no-picture.svg\'">';
    if(imageUrl)out+='<a class="detail-image-link" href="'+esc(imageUrl)+'" target="_blank" rel="noopener noreferrer">'+image+'</a><span class="detail-source">Source: <a href="'+esc(imageUrl)+'" target="_blank" rel="noopener noreferrer">'+esc(String(imageListing.source_site||'Source'))+'</a></span>';
    else out+=image+'<span class="detail-source">Listing Claim</span>';
  }else if(imageObservation){
    const imageUrl=String(imageObservation.source_url||'');
    const image='<img class="detail-image" src="'+esc(imageObservation.image_url)+'" alt="'+esc(imageObservation.title||i.model||'Guitar')+'" loading="lazy" referrerpolicy="no-referrer" onerror="this.onerror=null;this.src=\'/assets/no-picture.svg\'">';
    if(imageUrl)out+='<a class="detail-image-link" href="'+esc(imageUrl)+'" target="_blank" rel="noopener noreferrer">'+image+'</a><span class="detail-source">Source: Reverb image (provenance)</span>';
    else out+=image+'<span class="detail-source">Source: Reverb image (provenance)</span>';
  }else{
    out+='<img class="detail-image" src="/assets/no-picture.svg" alt="No picture"><span class="detail-source">No Picture</span>';
  }
  const specMap={};
  for(const s of (currentSpecifications||[]))specMap[String(s.field_name||'')]=s;
  const finishValue=specMap.finish?specMap.finish.value_text:(i.finish||'—');
  const fixedSpecRows=[
    ['Maker',i.manufacturer||'—'],
    ['Model',i.model||'—'],
    ['Finish',finishValue||'—'],
    ['Year',i.year||'—'],
    ['Serial',i.serial_number||'—']
  ];
  const hiddenFields=new Set(['maker','manufacturer','model','finish','year','serial','serial_number']);
  const preferredOrder=['body','bridge','fingerboard','frets','neck','nut','pickups','pickguard','potentiometers','tuners','wiring','weight'];
  const dynamicSpecs=(currentSpecifications||[])
    .filter(s=>!hiddenFields.has(String(s.field_name||'').toLowerCase()))
    .slice()
    .sort((a,b)=>{
      const ak=String(a.field_name||'').toLowerCase();
      const bk=String(b.field_name||'').toLowerCase();
      const ai=preferredOrder.indexOf(ak);
      const bi=preferredOrder.indexOf(bk);
      if(ai>=0||bi>=0){
        if(ai<0)return 1;
        if(bi<0)return-1;
        if(ai!==bi)return ai-bi;
      }
      return ak.localeCompare(bk);
    });
  out+='<div class="detail-header"><div class="detail-header-title">'+esc(i.manufacturer)+' '+esc(i.model||'')+'</div>'+
    '<div class="current-owner-line"><span class="catalog-spec-label">Current Owner:</span> '+currentSnapshotOwnerHtml(i)+'</div>'+
    '<div class="current-owner-line"><span class="catalog-spec-label">Location:</span> '+currentLocationHtml(i)+'</div>'+
    ownershipControlsHtml(i.id)+'</div>';
  out+='<div class="chronicle-toolbar"><strong>Specification</strong></div><div class="catalog-spec">'+
    fixedSpecRows.map(row=>'<div class="catalog-spec-row"><span class="catalog-spec-label">'+esc(row[0])+':</span> '+esc(row[1])+'</div>').join('')+
    dynamicSpecs.map(s=>'<div class="catalog-spec-row"><span class="catalog-spec-label">'+esc(specificationFieldLabel(s.field_name))+':</span> '+esc(s.value_text||'—')+'</div>').join('')+
    '</div>';
  out+='<div class="chronicle-toolbar"><strong>Chronicle</strong><div class="toolbar" style="margin:0"><div class="claim-menu-wrap"><button onclick="toggleAddClaimMenu(event,'+i.id+')">Add Claim</button><div class="claim-menu" id="addClaimMenu"><button onclick="chooseClaimType(\'specification_repair\')">Specification/Repair</button><button onclick="chooseClaimType(\'incident\')">Incident</button><button onclick="chooseClaimType(\'event\')">Event</button><button onclick="chooseClaimType(\'media\')">Media</button>'+(activeUserOwns(i.id)?'<button onclick="chooseClaimType(\'ownership\')">Ownership</button>':'<button onclick="chooseClaimType(\'former_owner\')">Former Owner</button>')+'</div></div><select onchange="setChronicleSort(this.value)"><option value="event"'+(chronicleSort==='event'?' selected':'')+'>出来事順</option><option value="input"'+(chronicleSort==='input'?' selected':'')+'>入力順</option></select></div></div><div id="chronicleEntries"></div>';
  document.getElementById('detail').innerHTML=out;
  renderChronicle();
}

const SPEC_FIELDS=[
  ['nut','Nut'],
  ['frets','Frets'],
  ['pickguard','Pickguard'],
  ['potentiometers','Potentiometers'],
  ['wiring','Wiring'],
  ['neck','Neck'],
  ['pickups','Pickups'],
  ['bridge','Bridge'],
  ['tuners','Tuners'],
  ['body','Body'],
  ['fingerboard','Fingerboard'],
  ['finish','Finish'],
  ['weight','Weight']
];
let specificationKind='specification';
let specificationItems=[];
let editingSpecificationClaimId=null;
let pendingOwnershipClaimIndividualId=null;
let ownershipClaimMode='add_claim';

function toggleAddClaimMenu(event,individualId){
  event.stopPropagation();
  if(!activeUser||!activeUser.user){
    alert('先にUserを選択してください。');
    return;
  }
  selectedIndividualId=Number(individualId);
  const menu=document.getElementById('addClaimMenu');
  if(menu)menu.classList.toggle('open');
}
function chooseClaimType(type){
  const menu=document.getElementById('addClaimMenu');
  if(menu)menu.classList.remove('open');
  if(type==='specification_repair'){
    openSpecificationClaim(selectedIndividualId);
  }else if(type==='incident'){
    openIncidentClaim(selectedIndividualId);
  }else if(type==='event'){
    openEventClaim(selectedIndividualId);
  }else if(type==='media'){
    openMediaClaim(selectedIndividualId);
  }else if(type==='former_owner'){
    openFormerOwnerClaim(selectedIndividualId);
  }else if(type==='ownership'){
    openOwnershipClaim(selectedIndividualId,'add_claim');
  }
}

function mediaImageInputs(){
  return Array.from(document.querySelectorAll('#mediaClaimImages .media-image-input'));
}
function resetMediaImageInputs(){
  const inputs=mediaImageInputs();
  inputs.forEach((input,index)=>{
    input.value='';
    const slot=document.getElementById('mediaImageSlot'+index);
    if(slot)slot.classList.toggle('visible',index===0);
  });
}
function updateMediaImageSlots(){
  const inputs=mediaImageInputs();
  let lastSelected=-1;
  inputs.forEach((input,index)=>{
    if(input.files&&input.files.length)lastSelected=index;
  });
  const next=Math.min(lastSelected+1,inputs.length-1);
  inputs.forEach((input,index)=>{
    const slot=document.getElementById('mediaImageSlot'+index);
    if(slot)slot.classList.toggle(
      'visible',
      index===0||index<=next||(input.files&&input.files.length>0)
    );
  });
}
function openMediaClaim(individualId){
  if(!activeUser||!activeUser.user){
    alert('先にUserを選択してください。');
    return;
  }
  selectedIndividualId=Number(individualId);
  const guitar=individuals.find(x=>Number(x.id)===Number(individualId));
  document.getElementById('mediaClaimGuitar').textContent=guitar
    ? guitar.manufacturer+' '+(guitar.model||'')+(guitar.serial_number?' / '+guitar.serial_number:'')
    : 'Individual #'+individualId;
  resetMediaImageInputs();
  document.getElementById('mediaClaimDate').value=new Date().toISOString().slice(0,10);
  document.getElementById('mediaClaimCaption').value='';
  document.getElementById('mediaClaimModal').classList.add('open');
}
function closeMediaClaim(event){
  if(event&&event.target&&event.target.id!=='mediaClaimModal')return;
  document.getElementById('mediaClaimModal').classList.remove('open');
}
async function submitMediaClaim(){
  if(!activeUser||!activeUser.user||selectedIndividualId===null)return;
  const images=mediaImageInputs()
    .map(input=>input.files&&input.files[0])
    .filter(Boolean);
  if(!images.length){
    alert('画像ファイルを1枚以上選択してください。');
    return;
  }
  if(images.length>10){
    alert('画像は最大10枚です。');
    return;
  }
  for(const image of images){
    if(!['image/jpeg','image/png','image/webp','image/gif'].includes(image.type)){
      alert('JPEG / PNG / WebP / GIF画像を選択してください。');
      return;
    }
    if(image.size>12*1024*1024){
      alert('画像は1枚12MB以下にしてください。');
      return;
    }
  }
  const form=new FormData();
  form.append('user_id',String(activeUser.user.id));
  images.forEach(image=>form.append('images',image));
  form.append('occurred_at',document.getElementById('mediaClaimDate').value||'');
  form.append('caption',document.getElementById('mediaClaimCaption').value.trim());
  const button=document.getElementById('mediaClaimSubmit');
  button.disabled=true;
  try{
    const r=await fetch('/api/individuals/'+selectedIndividualId+'/media-claim',{
      method:'POST',
      body:form
    });
    const d=await r.json().catch(()=>({}));
    if(!r.ok)throw new Error(d.detail||r.statusText);
    closeMediaClaim();
    await showIndividual(selectedIndividualId);
  }catch(e){
    alert('Media Claimの登録に失敗しました。\\n'+e.message);
  }finally{
    button.disabled=false;
  }
}

function openEventClaim(individualId){
  if(!activeUser||!activeUser.user){
    alert('先にUserを選択してください。');
    return;
  }
  selectedIndividualId=Number(individualId);
  const guitar=individuals.find(x=>Number(x.id)===Number(individualId));
  document.getElementById('eventClaimGuitar').textContent=guitar
    ? guitar.manufacturer+' '+(guitar.model||'')+(guitar.serial_number?' / '+guitar.serial_number:'')
    : 'Individual #'+individualId;
  document.getElementById('eventClaimKind').value='exhibition';
  document.getElementById('eventClaimDate').value=new Date().toISOString().slice(0,10);
  document.getElementById('eventClaimDetail').value='';
  document.getElementById('eventClaimModal').classList.add('open');
}
function closeEventClaim(event){
  if(event&&event.target&&event.target.id!=='eventClaimModal')return;
  document.getElementById('eventClaimModal').classList.remove('open');
}
async function submitEventClaim(){
  if(!activeUser||!activeUser.user||selectedIndividualId===null)return;
  const detail=document.getElementById('eventClaimDetail').value.trim();
  if(!detail){
    alert('Detailを入力してください。');
    return;
  }
  const button=document.getElementById('eventClaimSubmit');
  button.disabled=true;
  try{
    await jfetch('/api/individuals/'+selectedIndividualId+'/event-claim',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        user_id:Number(activeUser.user.id),
        event_kind:document.getElementById('eventClaimKind').value,
        occurred_at:document.getElementById('eventClaimDate').value||null,
        detail
      })
    });
    closeEventClaim();
    await showIndividual(selectedIndividualId);
  }catch(e){
    alert('Event Claimの登録に失敗しました.\\n'+e.message);
  }finally{
    button.disabled=false;
  }
}

function openIncidentClaim(individualId){
  if(!activeUser||!activeUser.user){
    alert('先にUserを選択してください。');
    return;
  }
  selectedIndividualId=Number(individualId);
  const guitar=individuals.find(x=>Number(x.id)===Number(individualId));
  document.getElementById('incidentClaimGuitar').textContent=guitar
    ? guitar.manufacturer+' '+(guitar.model||'')+(guitar.serial_number?' / '+guitar.serial_number:'')
    : 'Individual #'+individualId;
  document.getElementById('incidentClaimKind').value='damage';
  document.getElementById('incidentClaimDate').value=new Date().toISOString().slice(0,10);
  document.getElementById('incidentClaimDetail').value='';
  document.getElementById('incidentClaimModal').classList.add('open');
}
function closeIncidentClaim(event){
  if(event&&event.target&&event.target.id!=='incidentClaimModal')return;
  document.getElementById('incidentClaimModal').classList.remove('open');
}
async function submitIncidentClaim(){
  if(!activeUser||!activeUser.user||selectedIndividualId===null)return;
  const detail=document.getElementById('incidentClaimDetail').value.trim();
  if(!detail){
    alert('Detailを入力してください。');
    return;
  }
  const button=document.getElementById('incidentClaimSubmit');
  button.disabled=true;
  try{
    await jfetch('/api/individuals/'+selectedIndividualId+'/incident-claim',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        user_id:Number(activeUser.user.id),
        incident_kind:document.getElementById('incidentClaimKind').value,
        occurred_at:document.getElementById('incidentClaimDate').value||null,
        detail
      })
    });
    closeIncidentClaim();
    await showIndividual(selectedIndividualId);
  }catch(e){
    alert('Incident Claimの登録に失敗しました.\\n'+e.message);
  }finally{
    button.disabled=false;
  }
}

function openFormerOwnerClaim(individualId){
  if(!activeUser||!activeUser.user){
    alert('先にUserを選択してください。');
    return;
  }
  if(activeUserOwns(individualId)){
    alert('現在OwnerはFormer Owner Claimを追加できません。');
    return;
  }
  selectedIndividualId=Number(individualId);
  const guitar=individuals.find(x=>Number(x.id)===Number(individualId));
  document.getElementById('formerOwnerClaimGuitar').textContent=guitar
    ? guitar.manufacturer+' '+(guitar.model||'')+(guitar.serial_number?' / '+guitar.serial_number:'')
    : 'Individual #'+individualId;
  document.getElementById('formerOwnerAcquisitionDate').value='';
  document.getElementById('formerOwnerReleaseDate').value='';
  document.getElementById('formerOwnerDetail').value='';
  document.getElementById('formerOwnerClaimModal').classList.add('open');
  setTimeout(()=>document.getElementById('formerOwnerAcquisitionDate').focus(),0);
}
function closeFormerOwnerClaim(event){
  if(event&&event.target&&event.target.id!=='formerOwnerClaimModal')return;
  const modal=document.getElementById('formerOwnerClaimModal');
  if(modal)modal.classList.remove('open');
}
async function submitFormerOwnerClaim(){
  if(!activeUser||!activeUser.user||selectedIndividualId===null)return;
  const acquisitionDate=document.getElementById('formerOwnerAcquisitionDate').value;
  const releaseDate=document.getElementById('formerOwnerReleaseDate').value;
  if(!acquisitionDate||!releaseDate){
    alert('Acquisition DateとRelease Dateは必須です。');
    return;
  }
  if(acquisitionDate>=releaseDate){
    alert('Acquisition DateはRelease Dateより前の日付にしてください。');
    return;
  }
  const button=document.getElementById('formerOwnerClaimSubmit');
  button.disabled=true;
  try{
    const individualId=selectedIndividualId;
    const d=await jfetch('/api/individuals/'+individualId+'/former-owner-claim',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        user_id:Number(activeUser.user.id),
        acquisition_date:acquisitionDate,
        release_date:releaseDate,
        detail:document.getElementById('formerOwnerDetail').value.trim()||null
      })
    });
    activeUser={user:d.user,guitars:d.guitars};
    closeFormerOwnerClaim();
    if(typeof renderAccount==='function')renderAccount();
    await showIndividual(individualId);
  }catch(e){
    alert('Former Owner Claimの登録に失敗しました。\n'+e.message);
  }finally{
    button.disabled=false;
  }
}

function configureOwnershipClaim(mode){
  ownershipClaimMode=mode==='add_claim'?'add_claim':'acquire';
  const kind=document.getElementById('ownershipClaimKind');
  const fixed=document.getElementById('ownershipClaimFixedTag');
  const previousRow=document.getElementById('ownershipClaimPreviousRow');
  if(ownershipClaimMode==='acquire'){
    kind.value='acquire';
    kind.style.display='none';
    fixed.style.display='block';
    fixed.innerHTML='<strong>Acquire</strong>';
    previousRow.style.display='';
  }else{
    kind.innerHTML='<option value="transfer">Transfer</option><option value="release">Release</option><option value="inherit">Inherit</option>';
    kind.value='transfer';
    kind.style.display='block';
    fixed.style.display='none';
    previousRow.style.display='';
  }
}
function openOwnershipClaim(individualId,mode='add_claim'){
  if(!activeUser||!activeUser.user){
    alert('先にUserを選択してください。');
    return;
  }
  if(mode==='add_claim'&&!activeUserOwns(individualId)){
    alert('現在のUserが所有中のギターだけOwnership Claimを追加できます。');
    return;
  }
  pendingOwnershipClaimIndividualId=Number(individualId);
  selectedIndividualId=Number(individualId);
  const guitar=individuals.find(x=>Number(x.id)===Number(individualId));
  document.getElementById('ownershipClaimGuitar').textContent=guitar
    ? guitar.manufacturer+' '+(guitar.model||'')+(guitar.serial_number?' / '+guitar.serial_number:'')
    : 'Individual #'+individualId;
  configureOwnershipClaim(mode);
  document.getElementById('ownershipClaimDate').value=new Date().toISOString().slice(0,10);
  document.getElementById('ownershipClaimPrevious').value='';
  document.getElementById('ownershipClaimBody').value='';
  document.getElementById('ownershipClaimSubmit').textContent='Claimを追加';
  document.getElementById('ownershipClaimModal').classList.add('open');
}
function closeOwnershipClaim(event){
  if(event&&event.target&&event.target.id!=='ownershipClaimModal')return;
  document.getElementById('ownershipClaimModal').classList.remove('open');
  pendingOwnershipClaimIndividualId=null;
}
async function submitOwnershipClaim(){
  if(!activeUser||!activeUser.user||pendingOwnershipClaimIndividualId===null)return;
  const button=document.getElementById('ownershipClaimSubmit');
  const kind=document.getElementById('ownershipClaimKind').value;
  if(['transfer','release','inherit'].includes(kind)){
    const guitar=individuals.find(x=>Number(x.id)===Number(pendingOwnershipClaimIndividualId));
    const label=guitar?guitar.manufacturer+' '+(guitar.model||''):'このギター';
    if(!confirm(label+' の所有状態を終了し、Current OwnerをUnknownに変更します。\n\nこの内容で'+claimTypeLabel(kind)+'を登録しますか？'))return;
  }
  button.disabled=true;
  try{
    const individualId=pendingOwnershipClaimIndividualId;
    const d=await jfetch('/api/individuals/'+individualId+'/ownership-claim',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        user_id:Number(activeUser.user.id),
        ownership_kind:kind,
        occurred_at:document.getElementById('ownershipClaimDate').value||null,
        previous_owner_text:document.getElementById('ownershipClaimPrevious').value.trim()||null,
        body:document.getElementById('ownershipClaimBody').value.trim()||null
      })
    });
    activeUser={user:d.user,guitars:d.guitars};
    closeOwnershipClaim();
    renderAccount();
    await showIndividual(individualId);
  }catch(e){
    alert('Ownership Claimの登録に失敗しました。\n'+e.message);
  }finally{
    button.disabled=false;
  }
}

function setSpecificationKind(kind){
  specificationKind=kind==='repair'?'repair':'specification';
  document.getElementById('specKindSpecification').classList.toggle('active',specificationKind==='specification');
  document.getElementById('specKindRepair').classList.toggle('active',specificationKind==='repair');
}
function openSpecificationClaim(individualId){
  if(!activeUser||!activeUser.user){
    alert('先にUserを選択してください。');
    return;
  }
  selectedIndividualId=Number(individualId);
  const guitar=individuals.find(x=>Number(x.id)===Number(individualId));
  document.getElementById('specClaimGuitar').textContent=guitar
    ? guitar.manufacturer+' '+(guitar.model||'')+(guitar.serial_number?' / '+guitar.serial_number:'')
    : 'Individual #'+individualId;
  editingSpecificationClaimId=null;
  specificationKind='specification';
  const deleteButton=document.getElementById('specClaimDelete');
  if(deleteButton)deleteButton.style.display='none';
  specificationItems=[];
  setSpecificationKind('specification');
  document.getElementById('specClaimTitle').textContent='Specification/Repair Claim';
  document.getElementById('specClaimSubmit').textContent='Claimを追加';
  document.getElementById('specClaimDate').value=new Date().toISOString().slice(0,10);
  document.getElementById('specClaimBody').value='';
  renderSpecificationItems();
  renderSpecItemMenu();
  document.getElementById('specClaimModal').classList.add('open');
}
let identityCorrectionListingClaimId=null;

function openIdentityCorrection(listingClaimId){
  if(!activeUser||!activeUser.user||!currentIndividual)return;
  identityCorrectionListingClaimId=Number(listingClaimId);
  document.getElementById('identityMaker').value=currentIndividual.manufacturer||'';
  document.getElementById('identityModel').value=currentIndividual.model||'';
  document.getElementById('identityYear').value=currentIndividual.year||'';
  document.getElementById('identitySerial').value=currentIndividual.serial_number||'';
  document.getElementById('identityReason').value='';
  document.getElementById('identityCorrectionModal').classList.add('open');
}

function closeIdentityCorrection(event){
  if(event&&event.target&&event.target.id!=='identityCorrectionModal')return;
  document.getElementById('identityCorrectionModal').classList.remove('open');
  identityCorrectionListingClaimId=null;
}

async function submitIdentityCorrection(){
  if(!activeUser||!activeUser.user||identityCorrectionListingClaimId===null)return;
  const maker=document.getElementById('identityMaker').value.trim();
  const serial=document.getElementById('identitySerial').value.trim();
  if(!maker||!serial){
    alert('MakerとSerialは必須です。');
    return;
  }
  const button=document.getElementById('identityCorrectionSubmit');
  button.disabled=true;
  try{
    await jfetch('/api/claims/'+identityCorrectionListingClaimId+'/identity-correction',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        user_id:Number(activeUser.user.id),
        manufacturer:maker,
        model:document.getElementById('identityModel').value.trim()||null,
        year:document.getElementById('identityYear').value.trim()||null,
        serial_number:serial,
        reason:document.getElementById('identityReason').value.trim()||null
      })
    });
    closeIdentityCorrection();
    individuals=await jfetch('/api/individuals');
    if(selectedIndividualId!==null)await showIndividual(selectedIndividualId);
    await loadActiveUser();
  }catch(e){
    alert('Identity Correctionを作成できませんでした。\n'+e.message);
  }finally{
    button.disabled=false;
  }
}

let editingClaimId=null;

function editOwnClaim(claimId){
  if(!activeUser||!activeUser.user)return;
  const claim=currentClaims.find(c=>Number(c.id)===Number(claimId));
  if(!claim||Number(claim.author_user_id)!==Number(activeUser.user.id))return;
  if(claim.claim_type==='listing'){
    if(window.confirm('Listingは編集できません。Identity Correctionを作成しますか？')){
      openIdentityCorrection(claimId);
    }
    return;
  }
  if(claim.claim_type==='specification'){
    editSpecificationClaim(claimId);
    return;
  }
  if(claim.claim_type==='identity_correction')return;
  editingClaimId=Number(claimId);
  document.getElementById('claimEditTitle').textContent='Edit '+claimTypeLabel(claim.claim_type)+' Claim';
  document.getElementById('claimEditType').textContent=claimTypeLabel(claim.claim_type);
  document.getElementById('claimEditDate').value=String(claim.occurred_at||'').slice(0,10);
  document.getElementById('claimEditBody').value=claim.body||'';
  document.getElementById('claimEditModal').classList.add('open');
}

function closeClaimEdit(event){
  if(event&&event.target&&event.target.id!=='claimEditModal')return;
  document.getElementById('claimEditModal').classList.remove('open');
  editingClaimId=null;
}

async function submitClaimEdit(){
  if(!activeUser||!activeUser.user||editingClaimId===null)return;
  const claimId=editingClaimId;
  const button=document.getElementById('claimEditSubmit');
  button.disabled=true;
  try{
    await jfetch('/api/claims/'+claimId,{
      method:'PATCH',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        user_id:Number(activeUser.user.id),
        occurred_at:document.getElementById('claimEditDate').value||null,
        body:document.getElementById('claimEditBody').value.trim()||null
      })
    });
    closeClaimEdit();
    if(selectedIndividualId!==null)await showIndividual(selectedIndividualId);
    await loadActiveUser();
  }catch(e){
    alert('Claimの更新に失敗しました。\n'+e.message);
  }finally{
    button.disabled=false;
  }
}

async function deactivateEditingClaim(){
  if(!activeUser||!activeUser.user||editingClaimId===null)return;
  const claimId=editingClaimId;
  if(!confirm('このClaimをDeactivateします。\nChronicle上では無効となり、現在状態の計算から除外されます。続行しますか？'))return;
  const button=document.getElementById('claimEditDelete');
  button.disabled=true;
  try{
    const d=await jfetch('/api/claims/'+claimId+'/deactivate',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({user_id:Number(activeUser.user.id)})
    });
    closeClaimEdit();
    if(selectedIndividualId!==null)await showIndividual(selectedIndividualId);
    await loadActiveUser();
  }catch(e){
    alert('ClaimのDeactivateに失敗しました。\n'+e.message);
  }finally{
    button.disabled=false;
  }
}

async function deactivateSpecificationClaim(){
  if(!activeUser||!activeUser.user||editingSpecificationClaimId===null)return;
  const claimId=editingSpecificationClaimId;
  if(!confirm('このClaimをDeactivateします。\nChronicle上では無効となり、現在Specificationの計算から除外されます。続行しますか？'))return;
  const button=document.getElementById('specClaimDelete');
  button.disabled=true;
  try{
    await jfetch('/api/claims/'+claimId+'/deactivate',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({user_id:Number(activeUser.user.id)})
    });
    closeSpecificationClaim();
    if(selectedIndividualId!==null)await showIndividual(selectedIndividualId);
    await loadActiveUser();
  }catch(e){
    alert('ClaimのDeactivateに失敗しました。\n'+e.message);
  }finally{
    button.disabled=false;
  }
}

function editSpecificationClaim(claimId){
  if(!activeUser||!activeUser.user)return;
  const claim=currentClaims.find(c=>Number(c.id)===Number(claimId));
  if(!claim||Number(claim.author_user_id)!==Number(activeUser.user.id))return;
  if(claim.claim_type!=='specification')return;

  editingSpecificationClaimId=Number(claimId);
  specificationKind=claim.specification_kind==='repair'?'repair':'specification';
  const sourceItems=(claim.spec_items&&claim.spec_items.length)
    ? claim.spec_items
    : (claim.field_name?[{field_name:claim.field_name,value_text:claim.value_text}]:[]);
  specificationItems=sourceItems.map(item=>({
    field_name:String(item.field_name||''),
    label:specificationFieldLabel(item.field_name),
    value_text:String(item.value_text||'')
  }));
  setSpecificationKind(specificationKind);
  document.getElementById('specClaimTitle').textContent='Edit Specification/Repair Claim';
  document.getElementById('specClaimSubmit').textContent='更新';
  document.getElementById('specClaimDelete').style.display='';
  document.getElementById('specClaimDate').value=String(claim.occurred_at||'').slice(0,10);
  document.getElementById('specClaimBody').value=claim.body||'';
  const guitar=individuals.find(x=>Number(x.id)===Number(selectedIndividualId));
  document.getElementById('specClaimGuitar').textContent=guitar
    ? guitar.manufacturer+' '+(guitar.model||'')+(guitar.serial_number?' / '+guitar.serial_number:'')
    : 'Individual #'+selectedIndividualId;
  renderSpecificationItems();
  renderSpecItemMenu();
  document.getElementById('specClaimModal').classList.add('open');
}
function closeSpecificationClaim(event){
  if(event&&event.target&&event.target.id!=='specClaimModal')return;
  document.getElementById('specClaimModal').classList.remove('open');
  editingSpecificationClaimId=null;
  const menu=document.getElementById('specItemMenu');
  if(menu)menu.classList.remove('open');
}
function toggleSpecItemMenu(event){
  event.stopPropagation();
  renderSpecItemMenu();
  document.getElementById('specItemMenu').classList.toggle('open');
}
function renderSpecItemMenu(){
  const menu=document.getElementById('specItemMenu');
  if(!menu)return;
  const used=new Set(specificationItems.map(x=>x.field_name));
  menu.innerHTML=SPEC_FIELDS
    .filter(([key])=>!used.has(key))
    .map(([key,label])=>'<button type="button" onclick="addSpecificationItem(\''+key+'\')">'+esc(label)+'</button>')
    .join('')+
    '<button type="button" onclick="addCustomSpecificationItem()">Custom…</button>';
}
function addSpecificationItem(fieldName,label){
  if(specificationItems.some(x=>x.field_name===fieldName))return;
  const found=SPEC_FIELDS.find(([key])=>key===fieldName);
  specificationItems.push({
    field_name:fieldName,
    label:label||(found?found[1]:specificationFieldLabel(fieldName)),
    value_text:''
  });
  document.getElementById('specItemMenu').classList.remove('open');
  renderSpecificationItems();
}
function addCustomSpecificationItem(){
  const raw=prompt('Specification項目名を入力してください。');
  if(!raw)return;
  const fieldName=raw.trim().toLowerCase().replace(/\s+/g,'_');
  if(!fieldName)return;
  if(specificationItems.some(x=>x.field_name===fieldName)){
    alert('同じ項目はすでに追加されています。');
    return;
  }
  addSpecificationItem(fieldName,raw.trim());
}
function removeSpecificationItem(index){
  specificationItems.splice(index,1);
  renderSpecificationItems();
  renderSpecItemMenu();
}
function updateSpecificationItem(index,value){
  if(specificationItems[index])specificationItems[index].value_text=value;
}
function renderSpecificationItems(){
  const el=document.getElementById('specClaimItems');
  if(!el)return;
  el.innerHTML=specificationItems.length
    ? specificationItems.map((item,index)=>
      '<div class="spec-item-row">'+
        '<div class="spec-item-label">'+esc(item.label)+'</div>'+
        '<input maxlength="500" value="'+esc(item.value_text)+'" oninput="updateSpecificationItem('+index+',this.value)" placeholder="Value">'+
        '<button type="button" class="spec-item-remove" onclick="removeSpecificationItem('+index+')">×</button>'+
      '</div>'
    ).join('')
    : '<div class="sub">＋から入力したい項目を追加してください。</div>';
}
async function submitSpecificationClaim(){
  if(!activeUser||!activeUser.user||selectedIndividualId===null)return;
  const items=specificationItems
    .map(item=>({
      field_name:item.field_name,
      value_text:String(item.value_text||'').trim()
    }))
    .filter(item=>item.value_text);
  if(!items.length){
    alert('少なくとも1つの項目とValueを入力してください。');
    return;
  }
  if(items.length!==specificationItems.length){
    alert('追加した項目のValueをすべて入力してください。');
    return;
  }
  const button=document.getElementById('specClaimSubmit');
  button.disabled=true;
  try{
    const payload={
      user_id:Number(activeUser.user.id),
      specification_kind:specificationKind,
      items,
      occurred_at:document.getElementById('specClaimDate').value||null,
      body:document.getElementById('specClaimBody').value.trim()||null
    };
    const url=editingSpecificationClaimId===null
      ? '/api/individuals/'+selectedIndividualId+'/specification-claim'
      : '/api/claims/'+editingSpecificationClaimId+'/specification';
    await jfetch(url,{
      method:editingSpecificationClaimId===null?'POST':'PATCH',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(payload)
    });
    closeSpecificationClaim();
    await showIndividual(selectedIndividualId);
  }catch(e){
    alert('Specification/Repair Claimの登録に失敗しました.\n'+e.message);
  }finally{
    button.disabled=false;
  }
}

document.addEventListener('click',()=>{
  const claimMenu=document.getElementById('addClaimMenu');
  if(claimMenu)claimMenu.classList.remove('open');
  const specMenu=document.getElementById('specItemMenu');
  if(specMenu)specMenu.classList.remove('open');
});

async function linkOwnedGuitar(individualId){
  if(!activeUser||!activeUser.user)return;
  try{
    activeUser=await jfetch('/api/users/'+activeUser.user.id+'/guitars/'+individualId,{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({ownership_status:'current_owner'})
    });
    renderAccount();
    await showIndividual(individualId);
  }catch(e){
    alert('所有ギターの紐づけに失敗しました。\\n'+e.message);
  }
}
async function unlinkOwnedGuitar(individualId){
  if(!activeUser||!activeUser.user)return;
  try{
    activeUser=await jfetch('/api/users/'+activeUser.user.id+'/guitars/'+individualId,{method:'DELETE'});
    renderAccount();
    if(selectedIndividualId===Number(individualId))await showIndividual(individualId);
  }catch(e){
    alert('所有ギターの紐づけ解除に失敗しました。\\n'+e.message);
  }
}

(async()=>{
  await loadUsers();
})()
</script>
</body>
</html>"""


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
