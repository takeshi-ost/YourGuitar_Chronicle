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
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from ygc import config
from ygc.collectors.reverb import ReverbAPICollector
from ygc.db.repository import Repository
from ygc.extractors.serial import extract_serial_candidates
from ygc.matching.individual_matcher import match_or_create
from ygc.reverb_adapter import (
    classify_vintage_listing,
    listing_image_url,
    to_observation,
)


app = FastAPI(title="Your Guitar Chronicle Phase 0")

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

                    image_url = (
                        listing_image_url(
                            detail
                        )
                    )

                    parsed_observation = (
                        to_observation(
                            detail,
                            config.SERIAL_CONFIDENCE_THRESHOLD,
                        )
                    )
                    owner_name = (
                        parsed_observation.get(
                            "owner_name"
                        )
                    )
                    owner_type = (
                        parsed_observation.get(
                            "owner_type"
                        )
                    )
                    owner_profile_url = (
                        parsed_observation.get(
                            "owner_profile_url"
                        )
                    )
                    location_country = (
                        parsed_observation.get(
                            "location_country"
                        )
                    )
                    location_region = (
                        parsed_observation.get(
                            "location_region"
                        )
                    )
                    location_source = (
                        parsed_observation.get(
                            "location_source"
                        )
                    )

                    repository.update_observation_metadata(
                        int(
                            row["id"]
                        ),
                        model=model,
                        finish=finish,
                        year=year,
                        image_url=image_url,
                        owner_name=owner_name,
                        owner_type=owner_type,
                        owner_profile_url=owner_profile_url,
                        location_country=location_country,
                        location_region=location_region,
                        location_source=location_source,
                    )

                    if (
                        model
                        or finish
                        or year
                        or image_url
                        or owner_profile_url
                        or location_country
                        or location_region
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
                "model / finish / year / image / location "
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


@app.get("/api/individuals")
def api_individuals() -> list[dict[str, Any]]:
    return [_row_dict(row) for row in repo().list_individuals()]


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

    return {
        "individual": individual_data,
        "observations": [_row_dict(row) for row in observations],
    }


@app.get("/api/individuals/{individual_id}/claims")
def api_individual_claims(
    individual_id: int,
    viewer_user_id: int | None = None,
) -> list[dict[str, Any]]:
    return [
        _row_dict(row)
        for row
        in repo().list_claims(
            individual_id,
            viewer_user_id=viewer_user_id,
        )
    ]


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
#detail{white-space:normal}.detail-image{display:block;width:100%;max-height:360px;object-fit:contain;background:#111418;border:1px solid var(--line);border-radius:8px}.detail-image-link{display:block;margin:0 0 6px}.detail-source{display:block;margin:0 0 14px;color:var(--muted);font-size:11px}.detail-source a{color:var(--muted)}.detail-header{margin:0 0 16px}.detail-header-title{font-size:16px;font-weight:700;margin-bottom:10px}.detail-meta-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.detail-meta-item{background:#14171a;border:1px solid var(--line);border-radius:8px;padding:9px 10px;min-width:0}.detail-meta-label{display:block;color:var(--muted);font-size:10px;margin-bottom:2px}.detail-meta-value{display:block;color:var(--text);font-size:12px;overflow-wrap:anywhere}.detail-meta-value a{color:var(--text)}.detail-section{margin:18px 0 8px;font-size:13px;font-weight:700;color:var(--text);border-bottom:1px solid var(--line);padding-bottom:6px}.latest-observation-scroll{max-height:340px;overflow-y:auto;scrollbar-gutter:stable;padding-right:4px}.latest-observation-scroll .observation-card{margin-bottom:0}.observation-card{border:1px solid var(--line);border-radius:10px;background:#14171a;padding:12px 13px;margin:0 0 10px}.observation-card.latest{border-color:#5c513d;background:#181713}.observation-card-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:8px}.observation-date{font-weight:700}.observation-source{font-size:11px;color:var(--muted);white-space:nowrap}.observation-source a{color:var(--muted)}.observation-row{display:grid;grid-template-columns:78px minmax(0,1fr);gap:8px;margin:4px 0}.observation-label{color:var(--muted);font-size:11px}.observation-value{min-width:0;overflow-wrap:anywhere}.observation-title{font-weight:600}.pill{display:inline-block;padding:2px 6px;border:1px solid var(--line);border-radius:10px;margin-right:5px;color:var(--muted)}
.modal-backdrop{display:none;position:fixed;inset:0;background:rgba(0,0,0,.65);align-items:center;justify-content:center;z-index:1000}.modal-backdrop.open{display:flex}.modal{width:min(520px,calc(100vw - 32px));background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px;box-shadow:0 18px 60px rgba(0,0,0,.45)}.modal-actions{display:flex;gap:8px;justify-content:flex-end;margin-top:14px}
@media(max-width:900px){.grid{grid-template-columns:1fr}.cards{grid-template-columns:repeat(2,1fr)}.crawl-controls{grid-template-columns:repeat(2,minmax(0,1fr))}.crawl-controls>div:last-child{grid-column:1/-1}.crawl-controls button{width:100%}}@media(max-width:520px){.detail-meta-grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<header><div><h1>Your Guitar Chronicle <span class="sub">Phase 0 Browser Console</span></h1><div class="sub">Reverb収集・Individual確認をブラウザから操作</div></div><div class="toolbar" style="margin:0"><select id="activeUserSelect" style="width:auto;min-width:150px" onchange="setActiveUser(this.value)"><option value="">User未選択</option></select><button onclick="createUser()">新規アカウント</button><button class="secondary" onclick="window.open('/user-view','_blank','noopener')">User View</button><div id="tokenState"></div><button class="secondary" onclick="openTokenSettings()">Token設定</button><button class="secondary" onclick="exportDatabase()">バックアップ</button><button class="secondary" onclick="openDatabaseImport()">バックアップ復元</button><button class="secondary bad" onclick="resetDatabase()">DB初期化</button></div></header>
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
<h2>Individual Detail</h2>
<div id="detail" class="sub">Individuals の行をクリックすると履歴を表示します。</div>
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
const TOKEN_KEY='ygc_reverb_api_token';
const ACTIVE_USER_KEY='ygc_active_user_id';
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
  const message='現在のDBとMediaを選択したバックアップで置き換えます。\n\n'+file.name+'\n\n旧形式の .db も復元できますが、その場合Mediaは含まれません。\n\n実行前に必要であれば現在の状態をバックアップしてください。続行しますか？';
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
    document.getElementById('jobMessage').textContent='バックアップを復元しました';
    document.getElementById('jobBar').style.width='0%';
    await refreshStatus();
    await loadIndividuals();
    await loadUsers();
    const imported=d.imported_counts||{};
    const media=d.legacy_database?'旧DB形式（Mediaなし）':('Media: '+(d.imported_media_count??0));
    alert('バックアップを復元しました。\nObservations: '+(imported.observations??'')+'\nIndividuals: '+(imported.individuals??'')+'\nCrawl Runs: '+(imported.crawl_runs??'')+'\n'+media);
  }catch(e){
    alert('バックアップ復元に失敗しました。\n'+e.message);
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
      ['Individuals',s.individuals],
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
  select.innerHTML='<option value="">User未選択</option>'+users.map(u=>'<option value="'+u.id+'">'+esc(u.display_name)+' (#'+u.id+')</option>').join('');
  const target=users.some(u=>String(u.id)===String(saved))?saved:(users[0]?String(users[0].id):'');
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
    '<div class="toolbar" style="margin-top:10px"><button onclick="saveUser()">保存</button><span class="sub">認証なしのPhase 0アカウント / ID '+esc(u.id)+'</span></div>'+
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
function normalizeSortValue(value,key){if(key==='id'||key==='observation_count')return Number(value||0);return String(value??'').toLowerCase()}
function setIndividualSort(key){if(individualSortKey===key){individualSortDirection*=-1}else{individualSortKey=key;individualSortDirection=1}renderIndividuals()}
function updateSortIndicators(){for(const key of ['id','manufacturer','model','finish','year','serial_number','observation_count']){const el=document.getElementById('sort-'+key);if(el)el.textContent=individualSortKey===key?(individualSortDirection===1?'▲':'▼'):''}}
function renderIndividuals(){const q=document.getElementById('individualFilter').value.toLowerCase();const rows=individuals.filter(x=>[x.manufacturer,x.model,x.finish,x.year,x.serial_number].join(' ').toLowerCase().includes(q)).slice().sort((a,b)=>{const av=normalizeSortValue(a[individualSortKey],individualSortKey);const bv=normalizeSortValue(b[individualSortKey],individualSortKey);if(av<bv)return-1*individualSortDirection;if(av>bv)return 1*individualSortDirection;return Number(a.id)-Number(b.id)});updateSortIndicators();document.getElementById('individualBody').innerHTML=rows.map(x=>'<tr class="clickable" onclick="showIndividual('+x.id+')"><td>'+x.id+'</td><td>'+esc(x.manufacturer)+'</td><td>'+esc(x.model)+'</td><td>'+esc(x.finish||'')+'</td><td>'+esc(x.year||'')+'</td><td class="mono">'+esc(x.serial_number)+'</td><td>'+x.observation_count+'</td></tr>').join('')}
function sourceName(o){return String(o.source_site||'').toLowerCase()==='reverb'?'Reverb':String(o.source_site||'Source')}
function ownerLabel(o){const name=String(o.owner_name||o.seller||'').trim();if(!name)return '';const type=String(o.owner_type||'').trim();return type==='shop'?name+' (Shop)':(type==='user'?name+' (User)':name)}
function currentOwnerHtml(o){if(!o)return '—';const name=String(o.owner_name||o.seller||'').trim();if(!name)return '—';const type=String(o.owner_type||'').trim();const profileUrl=String(o.owner_profile_url||'').trim();const listingUrl=String(o.source_url||'').trim();const label=type==='shop'?name+' (Shop)':name;if(type==='shop'&&listingUrl){return '<a href="'+esc(listingUrl)+'" target="_blank" rel="noopener noreferrer">'+esc(label)+'</a>'}if(type==='user'&&profileUrl){return '<a href="'+esc(profileUrl)+'">'+esc(label)+'</a>'}return esc(label)}
function observationCard(o,isLatest){const url=String(o.source_url||'');const source=sourceName(o);const sourceHtml=url?'<a href="'+esc(url)+'" target="_blank" rel="noopener noreferrer">'+esc(source)+'</a>':esc(source);const owner=ownerLabel(o);const seller=String(o.seller||'').trim();let rows='';if(owner)rows+='<div class="observation-row"><div class="observation-label">Owner</div><div class="observation-value">'+esc(owner)+'</div></div>';if(seller&&seller!==String(o.owner_name||'').trim())rows+='<div class="observation-row"><div class="observation-label">Shop</div><div class="observation-value">'+esc(seller)+'</div></div>';const location=[o.location_country,o.location_region].filter(Boolean).join(' / ');if(location)rows+='<div class="observation-row"><div class="observation-label">Location</div><div class="observation-value">'+esc(location)+'</div></div>';if(o.title)rows+='<div class="observation-row"><div class="observation-label">Listing</div><div class="observation-value observation-title">'+esc(o.title)+'</div></div>';const specs=[o.model&&('Model: '+o.model),o.finish&&('Finish: '+o.finish),o.year&&('Year: '+o.year)].filter(Boolean).join(' / ');if(specs)rows+='<div class="observation-row"><div class="observation-label">Info</div><div class="observation-value">'+esc(specs)+'</div></div>';if(url)rows+='<div class="observation-row"><div class="observation-label">URL</div><div class="observation-value"><a href="'+esc(url)+'" target="_blank" rel="noopener noreferrer">Open listing</a></div></div>';return '<div class="observation-card'+(isLatest?' latest':'')+'"><div class="observation-card-head"><div class="observation-date">'+esc(o.listing_date||o.observed_at||'')+'</div><div class="observation-source">Source: '+sourceHtml+'</div></div>'+rows+'</div>'}
async function showIndividual(id){selectedIndividualId=Number(id);const d=await jfetch('/api/individuals/'+id);const i=d.individual;const observations=d.observations||[];const latestIndex=observations.length-1;const latest=latestIndex>=0?observations[latestIndex]:null;let out='';if(latest&&latest.image_url){const latestUrl=String(latest.source_url||'');const image='<img class="detail-image" src="'+esc(latest.image_url)+'" alt="'+esc(latest.title||i.model||'Guitar')+'" loading="lazy" referrerpolicy="no-referrer">';if(latestUrl){out+='<a class="detail-image-link" href="'+esc(latestUrl)+'" target="_blank" rel="noopener noreferrer" title="Reverb Listingを開く">'+image+'</a><span class="detail-source">Source: <a href="'+esc(latestUrl)+'" target="_blank" rel="noopener noreferrer">'+esc(sourceName(latest))+'</a></span>'}else{out+=image+'<span class="detail-source">Source: '+esc(sourceName(latest))+'</span>'}}out+='<div class="detail-header"><div class="detail-header-title">'+esc(i.manufacturer)+' '+esc(i.model||'')+'</div><div class="detail-meta-grid"><div class="detail-meta-item"><span class="detail-meta-label">Finish</span><span class="detail-meta-value">'+esc(i.finish||'—')+'</span></div><div class="detail-meta-item"><span class="detail-meta-label">Year</span><span class="detail-meta-value">'+esc(i.year||'—')+'</span></div><div class="detail-meta-item"><span class="detail-meta-label">Serial</span><span class="detail-meta-value mono">'+esc(i.serial_number||'—')+'</span></div><div class="detail-meta-item"><span class="detail-meta-label">Current Owner</span><span class="detail-meta-value">'+currentOwnerHtml(latest)+'</span></div></div>'+ownershipControlsHtml(i.id)+'</div>';if(latest){out+='<div class="detail-section">最新Observation</div><div class="latest-observation-scroll">'+observationCard(latest,true)+'</div>'}const history=observations.slice(0,Math.max(0,latestIndex)).reverse();if(history.length){out+='<div class="detail-section">履歴</div>'+history.map(o=>observationCard(o,false)).join('')}document.getElementById('detail').innerHTML=out}
async function startBackfill(){if(!confirm('既存Reverb Listingを再取得して model / finish / year / image URL / Owner / Location をバックフィルします。初回移行用の処理です。実行しますか？'))return;try{const d=await jfetch('/api/backfill-metadata',{method:'POST'});pollJob(d.job_id)}catch(e){alert(e.message)}}
async function startCrawl(){const queries=document.getElementById('queries').value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);const minValue=document.getElementById('yearMin').value;const maxValue=document.getElementById('yearMax').value;const body={queries,limit:Number(document.getElementById('limit').value),workers:Number(document.getElementById('workers').value),year_min:minValue?Number(minValue):null,year_max:maxValue?Number(maxValue):null};const btn=document.getElementById('crawlBtn');btn.disabled=true;try{const d=await jfetch('/api/crawl',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});pollJob(d.job_id)}catch(e){alert(e.message);btn.disabled=false}}
async function pollJob(id){try{const d=await jfetch('/api/jobs/'+id);document.getElementById('jobBar').style.width=((d.progress||0)*100)+'%';document.getElementById('jobMessage').textContent=d.message||d.status;let resultHtml=(d.query_results||[]).map(x=>'<div class="sub">'+esc(x.query)+' — new '+x.new_observations+', detail '+x.details_fetched+', existing '+x.skipped_existing+'</div>').join('');if(d.aggregate&&d.aggregate.target_observations!==undefined){resultHtml+='<div class="sub">Backfill — target '+d.aggregate.target_observations+', updated '+d.aggregate.metadata_updated+', individuals '+d.aggregate.individuals_synced+'</div>'}document.getElementById('jobResults').innerHTML=resultHtml;if(d.status==='running'){setTimeout(()=>pollJob(id),1000)}else{document.getElementById('crawlBtn').disabled=false;await refreshStatus();await loadIndividuals();if(d.status==='error')alert(d.error||'crawl error')}}catch(e){document.getElementById('crawlBtn').disabled=false;alert(e.message)}}
(async()=>{await refreshStatus();await loadIndividuals();await loadStatistics();await loadUsers()})()
</script>
</body></html>"""



USER_VIEW_HTML = r"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Your Guitar Chronicle — User View</title>
<style>
:root{color-scheme:dark;--bg:#101214;--panel:#181b1f;--line:#2a2f35;--text:#edf0f3;--muted:#9ba6b0;--accent:#d0a45d;--good:#66c58a;--bad:#e07171}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
header{padding:22px 26px;border-bottom:1px solid var(--line)}
h1{font-size:21px;margin:0}.sub{color:var(--muted);font-size:12px}
main{max-width:1500px;margin:auto;padding:22px}
.grid{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(380px,.85fr);gap:18px;align-items:start}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px;margin-bottom:18px}
h2{font-size:17px;margin:0 0 14px}
.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px}
.toolbar h2{margin:0;flex:1}
input,button{font:inherit}
input{width:100%;background:#111418;color:var(--text);border:1px solid #343b43;border-radius:8px;padding:9px 10px}
button{border:0;border-radius:8px;padding:9px 13px;background:var(--accent);color:#18130c;font-weight:700;cursor:pointer}
button.secondary{background:#2a3036;color:var(--text)}
.edit-chronicle{width:100%;display:flex;align-items:center;justify-content:space-between;text-align:left;padding:14px 16px;margin-bottom:18px;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:12px}
.edit-chronicle:hover{background:#20252a}
.edit-chronicle-title{font-weight:700}.edit-chronicle-sub{font-size:12px;color:var(--muted);font-weight:400}
.table-wrap{max-height:620px;overflow:auto;border:1px solid var(--line);border-radius:8px}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{text-align:left;border-bottom:1px solid var(--line);padding:8px 7px;vertical-align:top}
th{color:var(--muted);font-weight:600;position:sticky;top:0;background:var(--panel)}
th.sortable{cursor:pointer;user-select:none}.sort-indicator{font-size:10px;margin-left:4px}
.clickable{cursor:pointer}.clickable:hover{background:#20252a}.clickable.selected{background:#3a3326}.clickable.selected:hover{background:#463c2c}
.mono{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
.status{display:inline-block;padding:3px 7px;border-radius:999px;font-size:11px;background:#2b3035}.good{color:var(--good)}
.detail-image{display:block;width:100%;max-height:360px;object-fit:contain;background:#111418;border:1px solid var(--line);border-radius:8px}
.detail-image-link{display:block;margin:0 0 6px}
.detail-source{display:block;margin:0 0 14px;color:var(--muted);font-size:11px}.detail-source a{color:var(--muted)}
.detail-header{margin:0 0 16px}.detail-header-title{font-size:16px;font-weight:700;margin-bottom:10px}
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
.claim-head{display:flex;align-items:center;gap:8px;margin-bottom:10px}.claim-event-date{margin-left:auto;text-align:right}
.claim-badge{display:inline-block;padding:3px 7px;border-radius:999px;background:var(--accent);color:#18130c;font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.03em}
.claim-event-date{font-size:12px;color:var(--muted);white-space:nowrap}
.claim-body{font-size:13px;line-height:1.55}
.claim-memo{margin-top:8px;white-space:pre-wrap}.claim-evidence-image{display:block;max-width:220px;max-height:180px;object-fit:cover;border:1px solid var(--line);border-radius:8px;margin-top:8px}
.claim-footer{margin-top:10px;padding-top:8px;border-top:1px solid var(--line);font-size:10px;color:var(--muted);display:flex;align-items:center;justify-content:space-between;gap:10px}.claim-footer-meta{text-align:right}.claim-votes{display:flex;gap:6px}.claim-vote{padding:4px 7px;border-radius:999px;background:#252a2f;color:var(--text);font-size:11px;min-width:54px}.claim-vote.active{outline:1px solid var(--accent)}
#chronicleEntries{max-height:560px;overflow-y:auto;padding-right:6px}
.modal-backdrop{display:none;position:fixed;inset:0;background:rgba(0,0,0,.68);align-items:center;justify-content:center;z-index:1000;padding:16px}.modal-backdrop.open{display:flex}.modal{width:min(560px,100%);background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px;box-shadow:0 18px 60px rgba(0,0,0,.45)}.modal textarea{width:100%;min-height:110px;background:#111418;color:var(--text);border:1px solid #343b43;border-radius:8px;padding:9px 10px;font:inherit;resize:vertical}.form-row{margin-bottom:12px}.form-label{display:block;color:var(--muted);font-size:11px;margin-bottom:4px}.modal-actions{display:flex;gap:8px;justify-content:flex-end;margin-top:16px}
@media(max-width:900px){.grid{grid-template-columns:1fr}}
@media(max-width:520px){.detail-meta-grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<header>
  <h1>Your Guitar Chronicle <span class="sub">User View</span></h1>
</header>
<main>
<button class="edit-chronicle" onclick="window.location.href='/user-view/edit'">
  <span>
    <span class="edit-chronicle-title">Edit Your Chronicle</span><br>
    <span class="edit-chronicle-sub" id="editChronicleSub">プロフィールや所有ギターを編集</span>
  </span>
  <span>›</span>
</button>

<div class="grid">
<section>
  <div class="panel">
    <div class="toolbar">
      <h2>Individuals</h2>
      <input id="individualFilter" style="max-width:320px" placeholder="maker / model / finish / year / serial" oninput="renderIndividuals()">
      <button class="secondary" onclick="loadIndividuals()">更新</button>
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
          <th class="sortable" onclick="setIndividualSort('observation_count')">Obs<span class="sort-indicator" id="sort-observation_count"></span></th>
        </tr></thead>
        <tbody id="individualBody"></tbody>
      </table>
    </div>
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

<div class="modal-backdrop" id="ownerClaimModal" onclick="closeOwnerClaim(event)">
  <div class="modal" onclick="event.stopPropagation()">
    <h2>Add to Your Chronicle</h2>
    <div class="sub" id="ownerClaimGuitar" style="margin-bottom:14px"></div>
    <div class="form-row">
      <label class="form-label" for="ownerClaimDate">取得日 / Owner Change Date</label>
      <input id="ownerClaimDate" type="date">
    </div>
    <div class="form-row">
      <label class="form-label" for="ownerClaimPrevious">以前の所有者・入手元（任意）</label>
      <input id="ownerClaimPrevious" placeholder="Former owner / Shop / Family ...">
    </div>
    <div class="form-row">
      <label class="form-label" for="ownerClaimBody">Claimメモ（任意）</label>
      <textarea id="ownerClaimBody" placeholder="この個体を所有することになった経緯など"></textarea>
    </div>
    <div class="sub">登録すると Owner Change Observation と ownership Claim が作成され、このギターがあなたのChronicleに追加されます。</div>
    <div class="modal-actions">
      <button class="secondary" onclick="closeOwnerClaim()">キャンセル</button>
      <button id="ownerClaimSubmit" onclick="submitOwnerClaim()">Add to Your Chronicle</button>
    </div>
  </div>
</div>

<script>
let individuals=[];
let activeUser=null;
let selectedIndividualId=null;
let currentObservations=[];
let currentClaims=[];
let chronicleSort='event';
let pendingOwnerClaimIndividualId=null;
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

async function loadActiveUser(){
  const id=localStorage.getItem(ACTIVE_USER_KEY);
  if(!id){
    activeUser=null;
    document.getElementById('editChronicleSub').textContent='プロフィールや所有ギターを編集';
    return;
  }
  try{
    activeUser=await jfetch('/api/users/'+id);
    const u=activeUser.user;
    document.getElementById('editChronicleSub').textContent=(u&&u.display_name?u.display_name+' — ':'')+'プロフィールや所有ギターを編集';
  }catch(e){
    activeUser=null;
    localStorage.removeItem(ACTIVE_USER_KEY);
  }
}

async function loadIndividuals(){
  individuals=await jfetch('/api/individuals');
  if(individuals.length){
    const randomIndex=Math.floor(Math.random()*individuals.length);
    selectedIndividualId=Number(individuals[randomIndex].id);
  }else{
    selectedIndividualId=null;
  }
  renderIndividuals();
  if(selectedIndividualId!==null){
    await showIndividual(selectedIndividualId);
  }else{
    document.getElementById('detail').textContent='表示できるIndividualがありません。';
  }
}
function normalizeSortValue(value,key){
  if(key==='id'||key==='observation_count')return Number(value||0);
  return String(value??'').toLowerCase();
}
function setIndividualSort(key){
  if(individualSortKey===key)individualSortDirection*=-1;
  else{individualSortKey=key;individualSortDirection=1}
  renderIndividuals();
}
function updateSortIndicators(){
  for(const key of ['id','manufacturer','model','finish','year','serial_number','observation_count']){
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
    '<tr class="clickable'+(Number(x.id)===Number(selectedIndividualId)?' selected':'')+'" onclick="showIndividual('+x.id+')"><td>'+x.id+'</td><td>'+esc(x.manufacturer)+'</td><td>'+esc(x.model)+'</td><td>'+esc(x.finish||'')+'</td><td>'+esc(x.year||'')+'</td><td class="mono">'+esc(x.serial_number)+'</td><td>'+x.observation_count+'</td></tr>'
  ).join('');
}

function sourceName(o){return String(o.source_site||'').toLowerCase()==='reverb'?'Reverb':String(o.source_site||'Source')}
function ownerLabel(o){
  const name=String(o.owner_name||o.seller||'').trim();
  if(!name)return '';
  const type=String(o.owner_type||'').trim();
  return type==='shop'?name+' (Shop)':(type==='user'?name+' (User)':name);
}
function currentOwnerHtml(o){
  if(!o)return '—';
  const name=String(o.owner_name||o.seller||'').trim();
  if(!name)return '—';
  const type=String(o.owner_type||'').trim();
  const listingUrl=String(o.source_url||'').trim();
  const label=type==='shop'?name+' (Shop)':name;
  if(type==='shop'&&listingUrl)return '<a href="'+esc(listingUrl)+'" target="_blank" rel="noopener noreferrer">'+esc(label)+'</a>';
  return esc(label);
}
function observationCard(o,isLatest){
  const url=String(o.source_url||'');
  const source=sourceName(o);
  const sourceHtml=url?'<a href="'+esc(url)+'" target="_blank" rel="noopener noreferrer">'+esc(source)+'</a>':esc(source);
  const owner=ownerLabel(o);
  const seller=String(o.seller||'').trim();
  let rows='';
  if(owner)rows+='<div class="observation-row"><div class="observation-label">Owner</div><div class="observation-value">'+esc(owner)+'</div></div>';
  if(seller&&seller!==String(o.owner_name||'').trim())rows+='<div class="observation-row"><div class="observation-label">Shop</div><div class="observation-value">'+esc(seller)+'</div></div>';
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
  if(activeUser&&activeUser.user&&activeUserOwns(individualId)){
    return '<div class="toolbar" style="margin-top:10px"><span class="status good">Your Guitar</span></div>';
  }
  return '<div class="toolbar" style="margin-top:10px"><button onclick="openOwnerClaim('+individualId+')">Add to Your Chronicle</button></div>';
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
  return '<span class="claim-badge">'+esc(type)+'</span><span class="claim-event-date">'+esc(eventDate)+'</span>';
}
function claimCard(c){
  const type=claimTypeLabel(c.claim_type);
  const eventDate=displayEventDate(c.occurred_at);
  let body='';
  if(c.claim_type==='owner_change'){
    body='<div><strong>'+esc(c.author_name||'User')+' has become the owner.</strong></div>';
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
  if(c.evidence_media_id){
    body+='<div class="claim-memo"><img class="claim-evidence-image" src="/api/media/'+encodeURIComponent(c.evidence_media_id)+'" alt="Claim evidence" loading="lazy"></div>';
  }
  const good=String(Number(c.good_count||0)).padStart(2,'0');
  const bad=String(Number(c.bad_count||0)).padStart(2,'0');
  const votes='<div class="claim-votes">'+
    '<button class="claim-vote'+(c.viewer_vote==='good'?' active':'')+'" onclick="voteClaim('+c.id+',\'good\')">👍 '+good+'</button>'+
    '<button class="claim-vote'+(c.viewer_vote==='bad'?' active':'')+'" onclick="voteClaim('+c.id+',\'bad\')">👎 '+bad+'</button>'+
    '</div>';
  return '<div class="claim-card">'+
    '<div class="claim-head">'+claimHeaderHtml(c,type,eventDate)+'</div>'+
    '<div class="claim-body">'+body+'</div>'+
    '<div class="claim-footer">'+votes+'<div class="claim-footer-meta">'+esc(displayInputDate(c.created_at))+' · By '+esc(c.author_name||('User #'+c.author_user_id))+'</div></div>'+
    '</div>';
}
function chronologyValue(c,mode){
  if(mode==='input')return String(c.created_at||'');
  return String(c.occurred_at||c.created_at||'');
}
function renderChronicle(){
  const claims=currentClaims.slice().sort((a,b)=>{
    const av=chronologyValue(a,chronicleSort);
    const bv=chronologyValue(b,chronicleSort);
    if(av<bv)return 1;
    if(av>bv)return -1;
    return Number(b.id)-Number(a.id);
  });
  const el=document.getElementById('chronicleEntries');
  if(el)el.innerHTML=claims.length
    ? claims.map(claimCard).join('')
    : '<div class="sub">Claimはまだありません。</div>';
}
function setChronicleSort(value){
  chronicleSort=value==='input'?'input':'event';
  renderChronicle();
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
  if(typeof renderIndividuals==='function')renderIndividuals();
  const [d,claims]=await Promise.all([
    jfetch('/api/individuals/'+id),
    jfetch('/api/individuals/'+id+'/claims'+(activeUser&&activeUser.user?'?viewer_user_id='+encodeURIComponent(activeUser.user.id):''))
  ]);
  const i=d.individual;
  const observations=d.observations||[];
  currentObservations=observations;
  currentClaims=claims||[];
  const latest=observations.length?observations[observations.length-1]:null;
  const imageObservation=observations.slice().reverse().find(o=>o.image_url)||null;
  let out='';
  if(i.representative_image_url){
    out+='<img class="detail-image" src="'+esc(i.representative_image_url)+'" alt="'+esc(i.model||'Guitar')+'" loading="lazy"><span class="detail-source">Representative Image</span>';
  }else if(imageObservation){
    const imageUrl=String(imageObservation.source_url||'');
    const image='<img class="detail-image" src="'+esc(imageObservation.image_url)+'" alt="'+esc(imageObservation.title||i.model||'Guitar')+'" loading="lazy" referrerpolicy="no-referrer">';
    if(imageUrl)out+='<a class="detail-image-link" href="'+esc(imageUrl)+'" target="_blank" rel="noopener noreferrer">'+image+'</a><span class="detail-source">Source: <a href="'+esc(imageUrl)+'" target="_blank" rel="noopener noreferrer">'+esc(sourceName(imageObservation))+'</a></span>';
    else out+=image+'<span class="detail-source">Source: '+esc(sourceName(imageObservation))+'</span>';
  }
  out+='<div class="detail-header"><div class="detail-header-title">'+esc(i.manufacturer)+' '+esc(i.model||'')+'</div><div class="detail-meta-grid">'+
    '<div class="detail-meta-item"><span class="detail-meta-label">Finish</span><span class="detail-meta-value">'+esc(i.finish||'—')+'</span></div>'+
    '<div class="detail-meta-item"><span class="detail-meta-label">Year</span><span class="detail-meta-value">'+esc(i.year||'—')+'</span></div>'+
    '<div class="detail-meta-item"><span class="detail-meta-label">Serial</span><span class="detail-meta-value mono">'+esc(i.serial_number||'—')+'</span></div>'+
    '<div class="detail-meta-item"><span class="detail-meta-label">Current Owner</span><span class="detail-meta-value">'+currentOwnerHtml(latest)+'</span></div>'+
    '</div>'+ownershipControlsHtml(i.id)+'</div>';
  out+='<div class="chronicle-toolbar"><strong>Chronicle</strong><select onchange="setChronicleSort(this.value)"><option value="event"'+(chronicleSort==='event'?' selected':'')+'>出来事順</option><option value="input"'+(chronicleSort==='input'?' selected':'')+'>入力順</option></select></div><div id="chronicleEntries"></div>';
  document.getElementById('detail').innerHTML=out;
  renderChronicle();
}

function openOwnerClaim(individualId){
  if(!activeUser||!activeUser.user){
    window.location.href='/user-view/edit';
    return;
  }
  pendingOwnerClaimIndividualId=Number(individualId);
  const guitar=individuals.find(x=>Number(x.id)===Number(individualId));
  document.getElementById('ownerClaimGuitar').textContent=guitar
    ? guitar.manufacturer+' '+(guitar.model||'')+(guitar.serial_number?' / '+guitar.serial_number:'')
    : 'Individual #'+individualId;
  document.getElementById('ownerClaimDate').value='';
  document.getElementById('ownerClaimPrevious').value='';
  document.getElementById('ownerClaimBody').value='';
  document.getElementById('ownerClaimModal').classList.add('open');
}
function closeOwnerClaim(event){
  if(event&&event.target&&event.target.id!=='ownerClaimModal')return;
  document.getElementById('ownerClaimModal').classList.remove('open');
  pendingOwnerClaimIndividualId=null;
}
async function submitOwnerClaim(){
  if(!activeUser||!activeUser.user||pendingOwnerClaimIndividualId===null)return;
  const button=document.getElementById('ownerClaimSubmit');
  button.disabled=true;
  try{
    const body={
      user_id:Number(activeUser.user.id),
      acquired_at:document.getElementById('ownerClaimDate').value||null,
      previous_owner_text:document.getElementById('ownerClaimPrevious').value.trim()||null,
      body:document.getElementById('ownerClaimBody').value.trim()||null
    };
    const individualId=pendingOwnerClaimIndividualId;
    const d=await jfetch('/api/individuals/'+individualId+'/owner-change-claim',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body)
    });
    activeUser={user:d.user,guitars:d.guitars};
    closeOwnerClaim();
    await showIndividual(individualId);
  }catch(e){
    alert('Claimの登録に失敗しました。\\n'+e.message);
  }finally{
    button.disabled=false;
  }
}

(async()=>{
  await loadActiveUser();
  await loadIndividuals();
})()
</script>
</body>
</html>"""


USER_EDIT_HTML = r"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Your Guitar Chronicle — Edit Your Chronicle</title>
<style>
:root{color-scheme:dark;--bg:#101214;--panel:#181b1f;--line:#2a2f35;--text:#edf0f3;--muted:#9ba6b0;--accent:#d0a45d;--good:#66c58a;--bad:#e07171}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
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
.detail-image{display:block;width:100%;max-height:360px;object-fit:contain;background:#111418;border:1px solid var(--line);border-radius:8px}
.detail-image-link{display:block;margin:0 0 6px}
.detail-source{display:block;margin:0 0 14px;color:var(--muted);font-size:11px}.detail-source a{color:var(--muted)}
.detail-header{margin:0 0 16px}.detail-header-title{font-size:16px;font-weight:700;margin-bottom:10px}
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
.claim-head{display:flex;align-items:center;gap:8px;margin-bottom:10px}.claim-event-date{margin-left:auto;text-align:right}
.claim-badge{display:inline-block;padding:3px 7px;border-radius:999px;background:var(--accent);color:#18130c;font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.03em}
.claim-event-date{font-size:12px;color:var(--muted);white-space:nowrap}
.claim-body{font-size:13px;line-height:1.55}
.claim-memo{margin-top:8px;white-space:pre-wrap}
.claim-footer{margin-top:10px;padding-top:8px;border-top:1px solid var(--line);font-size:10px;color:var(--muted);display:flex;align-items:center;justify-content:space-between;gap:10px}.claim-footer-meta{text-align:right}.claim-votes{display:flex;gap:6px}.claim-vote{padding:4px 7px;border-radius:999px;background:#252a2f;color:var(--text);font-size:11px;min-width:54px}.claim-vote.active{outline:1px solid var(--accent)}.claim-response-select{width:auto;min-width:108px;padding:4px 7px;font-size:11px}
#chronicleEntries{max-height:560px;overflow-y:auto;padding-right:6px}
.modal-backdrop{display:none;position:fixed;inset:0;background:rgba(0,0,0,.68);align-items:center;justify-content:center;z-index:1000;padding:16px}.modal-backdrop.open{display:flex}.modal{width:min(620px,100%);background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px;box-shadow:0 18px 60px rgba(0,0,0,.45)}.modal-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.form-row{margin-bottom:12px}.form-row.full{grid-column:1/-1}.form-label{display:block;color:var(--muted);font-size:11px;margin-bottom:4px}.modal textarea{width:100%;min-height:90px;background:#111418;color:var(--text);border:1px solid #343b43;border-radius:8px;padding:9px 10px;font:inherit;resize:vertical}.modal-actions{display:flex;gap:8px;justify-content:flex-end;margin-top:16px}@media(max-width:560px){.modal-grid{grid-template-columns:1fr}.form-row.full{grid-column:auto}}
.owned-list{display:flex;flex-direction:column;gap:6px}
.owned-row{display:grid;grid-template-columns:28px minmax(120px,1.4fr) 70px minmax(100px,1fr) minmax(90px,1fr) minmax(110px,1.2fr);gap:8px;align-items:center;border:1px solid var(--line);border-radius:8px;background:#14171a;padding:7px 8px}.owned-row[data-individual-id]{cursor:pointer}.owned-row[data-individual-id]:hover{background:#20252a}
.owned-row.dragging{opacity:.45}
.drag-handle{cursor:grab;color:var(--muted);font-size:16px;text-align:center;user-select:none}
.owned-cell{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px}
.owned-head{color:var(--muted);font-size:10px}
@media(max-width:900px){.grid{grid-template-columns:1fr}}
@media(max-width:520px){.detail-meta-grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<header>
  <div>
    <h1>Your Guitar Chronicle <span class="sub">Edit Your Chronicle</span></h1>
    <div class="sub">User Account / Individual Detail</div>
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
    <h2>Individual Detail</h2>
    <div id="detail" class="sub">Individuals の行をクリックすると履歴を表示します。</div>
  </div>
</section>
</div>
<div style="display:flex;justify-content:center;margin:8px 0 24px">
  <button class="secondary" onclick="window.location.href='/user-view'">Close</button>
</div>
</main>

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

<script>
let individuals=[];
let users=[];
let activeUser=null;
let selectedIndividualId=null;
let currentObservations=[];
let currentClaims=[];
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
  const target=users.some(u=>String(u.id)===String(saved))?saved:(users[0]?String(users[0].id):'');
  select.value=target;
  if(target){
    localStorage.setItem(ACTIVE_USER_KEY,target);
    await loadActiveUser();
  }else{
    activeUser=null;
    renderAccount();
  }
}

async function createUser(){
  try{
    const d=await jfetch('/api/users',{method:'POST'});
    localStorage.setItem(ACTIVE_USER_KEY,String(d.user.id));
    await loadUsers();
  }catch(e){
    alert('アカウント作成に失敗しました。\\n'+e.message);
  }
}

async function setActiveUser(value){
  selectedIndividualId=null;
  if(value){
    localStorage.setItem(ACTIVE_USER_KEY,String(value));
    await loadActiveUser();
  }else{
    localStorage.removeItem(ACTIVE_USER_KEY);
    activeUser=null;
    renderAccount();
  }
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
  const guitars=(activeUser.guitars||[]).filter(g=>g.ownership_status==='current_owner');
  el.className='';
  el.innerHTML=
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
    '<div class="toolbar" style="margin-top:12px"><button onclick="registerNewGuitar()">新しいギターを登録する</button></div>';
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
  if(key==='id'||key==='observation_count')return Number(value||0);
  return String(value??'').toLowerCase();
}
function setIndividualSort(key){
  if(individualSortKey===key)individualSortDirection*=-1;
  else{individualSortKey=key;individualSortDirection=1}
  renderIndividuals();
}
function updateSortIndicators(){
  for(const key of ['id','manufacturer','model','finish','year','serial_number','observation_count']){
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
      '<td>'+x.id+'</td><td>'+esc(x.manufacturer)+'</td><td>'+esc(x.model)+'</td><td>'+esc(x.finish||'')+'</td><td>'+esc(x.year||'')+'</td><td class="mono">'+esc(x.serial_number)+'</td><td>'+x.observation_count+'</td>'+
    '</tr>'
  ).join('');
}

function sourceName(o){
  return String(o.source_site||'').toLowerCase()==='reverb'?'Reverb':String(o.source_site||'Source');
}
function ownerLabel(o){
  const name=String(o.owner_name||o.seller||'').trim();
  if(!name)return '';
  const type=String(o.owner_type||'').trim();
  return type==='shop'?name+' (Shop)':(type==='user'?name+' (User)':name);
}
function currentOwnerHtml(o){
  if(!o)return '—';
  const name=String(o.owner_name||o.seller||'').trim();
  if(!name)return '—';
  const type=String(o.owner_type||'').trim();
  const listingUrl=String(o.source_url||'').trim();
  const label=type==='shop'?name+' (Shop)':name;
  if(type==='shop'&&listingUrl)return '<a href="'+esc(listingUrl)+'" target="_blank" rel="noopener noreferrer">'+esc(label)+'</a>';
  return esc(label);
}
function observationCard(o,isLatest){
  const url=String(o.source_url||'');
  const source=sourceName(o);
  const sourceHtml=url?'<a href="'+esc(url)+'" target="_blank" rel="noopener noreferrer">'+esc(source)+'</a>':esc(source);
  const owner=ownerLabel(o);
  const seller=String(o.seller||'').trim();
  let rows='';
  if(owner)rows+='<div class="observation-row"><div class="observation-label">Owner</div><div class="observation-value">'+esc(owner)+'</div></div>';
  if(seller&&seller!==String(o.owner_name||'').trim())rows+='<div class="observation-row"><div class="observation-label">Shop</div><div class="observation-value">'+esc(seller)+'</div></div>';
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
  if(!activeUser||!activeUser.user)return '<div class="sub" style="margin-top:10px">所有ギターに紐づけるにはUserを選択してください。</div>';
  if(activeUserOwns(individualId)){
    return '<div class="toolbar" style="margin-top:10px"><span class="status good">現在のUserが所有中</span><button class="bad" onclick="unlinkOwnedGuitar('+individualId+')">紐づけ解除</button></div>';
  }
  return '<div class="toolbar" style="margin-top:10px"><button onclick="linkOwnedGuitar('+individualId+')">所有ギターに追加</button></div>';
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
  if(isOtherUser){
    const current=c.viewer_stance||'neutral';
    response='<select class="claim-response-select" onchange="setClaimResponse('+c.id+',this.value)">'+
      '<option value="endorse"'+(current==='endorse'?' selected':'')+'>positive</option>'+
      '<option value="dispute"'+(current==='dispute'?' selected':'')+'>negative</option>'+
      '<option value="neutral"'+(current==='neutral'?' selected':'')+'>Unverified</option>'+
      '</select>';
  }
  return '<span class="claim-badge">'+esc(type)+'</span>'+response+'<span class="claim-event-date">'+esc(eventDate)+'</span>';
}
function claimCard(c){
  const type=claimTypeLabel(c.claim_type);
  const eventDate=displayEventDate(c.occurred_at);
  let body='';
  if(c.claim_type==='owner_change'){
    body='<div><strong>'+esc(c.author_name||'User')+' has become the owner.</strong></div>';
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
  const good=String(Number(c.good_count||0)).padStart(2,'0');
  const bad=String(Number(c.bad_count||0)).padStart(2,'0');
  const votes='<div class="claim-votes">'+
    '<button class="claim-vote'+(c.viewer_vote==='good'?' active':'')+'" onclick="voteClaim('+c.id+',\'good\')">👍 '+good+'</button>'+
    '<button class="claim-vote'+(c.viewer_vote==='bad'?' active':'')+'" onclick="voteClaim('+c.id+',\'bad\')">👎 '+bad+'</button>'+
    '</div>';
  return '<div class="claim-card">'+
    '<div class="claim-head">'+claimHeaderHtml(c,type,eventDate)+'</div>'+
    '<div class="claim-body">'+body+'</div>'+
    '<div class="claim-footer">'+votes+'<div class="claim-footer-meta">'+esc(displayInputDate(c.created_at))+' · By '+esc(c.author_name||('User #'+c.author_user_id))+'</div></div>'+
    '</div>';
}
function chronologyValue(c,mode){
  if(mode==='input')return String(c.created_at||'');
  return String(c.occurred_at||c.created_at||'');
}
function renderChronicle(){
  const claims=currentClaims.slice().sort((a,b)=>{
    const av=chronologyValue(a,chronicleSort);
    const bv=chronologyValue(b,chronicleSort);
    if(av<bv)return 1;
    if(av>bv)return -1;
    return Number(b.id)-Number(a.id);
  });
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
    if(selectedIndividualId!==null)await showIndividual(selectedIndividualId);
  }catch(e){
    alert('Claim評価の更新に失敗しました。\n'+e.message);
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
  const [d,claims]=await Promise.all([
    jfetch('/api/individuals/'+id),
    jfetch('/api/individuals/'+id+'/claims'+(activeUser&&activeUser.user?'?viewer_user_id='+encodeURIComponent(activeUser.user.id):''))
  ]);
  const i=d.individual;
  const observations=d.observations||[];
  currentObservations=observations;
  currentClaims=claims||[];
  const latest=observations.length?observations[observations.length-1]:null;
  const imageObservation=observations.slice().reverse().find(o=>o.image_url)||null;
  let out='';
  if(i.representative_image_url){
    out+='<img class="detail-image" src="'+esc(i.representative_image_url)+'" alt="'+esc(i.model||'Guitar')+'" loading="lazy"><span class="detail-source">Representative Image</span>';
  }else if(imageObservation){
    const imageUrl=String(imageObservation.source_url||'');
    const image='<img class="detail-image" src="'+esc(imageObservation.image_url)+'" alt="'+esc(imageObservation.title||i.model||'Guitar')+'" loading="lazy" referrerpolicy="no-referrer">';
    if(imageUrl)out+='<a class="detail-image-link" href="'+esc(imageUrl)+'" target="_blank" rel="noopener noreferrer">'+image+'</a><span class="detail-source">Source: <a href="'+esc(imageUrl)+'" target="_blank" rel="noopener noreferrer">'+esc(sourceName(imageObservation))+'</a></span>';
    else out+=image+'<span class="detail-source">Source: '+esc(sourceName(imageObservation))+'</span>';
  }
  out+='<div class="detail-header"><div class="detail-header-title">'+esc(i.manufacturer)+' '+esc(i.model||'')+'</div><div class="detail-meta-grid">'+
    '<div class="detail-meta-item"><span class="detail-meta-label">Finish</span><span class="detail-meta-value">'+esc(i.finish||'—')+'</span></div>'+
    '<div class="detail-meta-item"><span class="detail-meta-label">Year</span><span class="detail-meta-value">'+esc(i.year||'—')+'</span></div>'+
    '<div class="detail-meta-item"><span class="detail-meta-label">Serial</span><span class="detail-meta-value mono">'+esc(i.serial_number||'—')+'</span></div>'+
    '<div class="detail-meta-item"><span class="detail-meta-label">Current Owner</span><span class="detail-meta-value">'+currentOwnerHtml(latest)+'</span></div>'+
    '</div>'+ownershipControlsHtml(i.id)+'</div>';
  out+='<div class="chronicle-toolbar"><strong>Chronicle</strong><select onchange="setChronicleSort(this.value)"><option value="event"'+(chronicleSort==='event'?' selected':'')+'>出来事順</option><option value="input"'+(chronicleSort==='input'?' selected':'')+'>入力順</option></select></div><div id="chronicleEntries"></div>';
  document.getElementById('detail').innerHTML=out;
  renderChronicle();
}

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
