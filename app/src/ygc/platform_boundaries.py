"""Local adapters and explicit replacement contracts for a future GCP deployment.

A prototype user ID is an assertion from the browser, NOT authentication.
Production verification is provided by ygc.identity_platform.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol


class PlatformAdapterRequired(RuntimeError):
    """A requested production integration has no implementation yet."""


@dataclass(frozen=True)
class ActorContext:
    user_id: int | None
    provider: str
    subject: str | None
    verified: bool
    app_user_id: str | None = None
    tenant: str = ''


class IdentityBoundary(Protocol):
    def resolve(self, *, bearer_token: str | None,
                prototype_user_id: int | None) -> ActorContext: ...


class PrototypeIdentity:
    def resolve(self, *, bearer_token: str | None = None,
                prototype_user_id: int | None = None) -> ActorContext:
        # Deliberately never converts a supplied ID or bearer token into a
        # verified principal. Future endpoints must reject unverified actors.
        if bearer_token:
            raise PlatformAdapterRequired("No user bearer token verifier is installed")
        return ActorContext(prototype_user_id, "prototype", None, False)


class IdentityPlatformReplacement:
    """Compatibility entry point; explicit project and canonical store required."""
    def __new__(cls, accounts, *, project_id: str, tenant: str = ''):
        from ygc.identity_platform import IdentityPlatformIdentity
        return IdentityPlatformIdentity(accounts, project_id=project_id, tenant=tenant)


class LocalDummyIdentity:
    """Resolve a server-issued local session into the same principal contract."""
    def __init__(self, repository):
        self.repository = repository

    def resolve(self, *, bearer_token: str | None = None,
                prototype_user_id: int | None = None) -> ActorContext:
        require_local_platform()
        if os.getenv('YGC_IDENTITY_BACKEND') != 'local_dummy':
            raise PlatformAdapterRequired('Local dummy identity requires explicit local_dummy mode')
        if not bearer_token:
            return ActorContext(None, 'local-dummy', None, False)
        from ygc.accounts import resolve_session
        account = resolve_session(self.repository, bearer_token)
        if prototype_user_id is not None and prototype_user_id != account['id']:
            raise PermissionError('The requested user does not match the signed-in account.')
        return ActorContext(account['id'], 'local-dummy', 'local-' + account['app_user_id'], True, account['app_user_id'])


@dataclass(frozen=True)
class CrawlStep:
    category: str
    year_min: int
    year_max: int
    origin: str = "manual"

    def __post_init__(self) -> None:
        if self.category not in ("electric", "acoustic", "electric_acoustic") or not 1800 <= self.year_min <= self.year_max <= 2100:
            raise ValueError("Invalid crawl category or manufacture-year range")
        if self.origin not in ("manual", "scheduled"):
            raise ValueError("Invalid crawl origin")


class CrawlRunner(Protocol):
    def run(self, step: CrawlStep, repository: Any, collector: Any,
            progress_callback: Callable[[dict], None] | None = None) -> dict: ...


class LocalCrawlRunner:
    def run(self, step: CrawlStep, repository: Any, collector: Any,
            progress_callback: Callable[[dict], None] | None = None) -> dict:
        from ygc.incremental_crawl import advance_program
        return advance_program(repository, collector, step.category, step.year_min,
                               step.year_max, progress_callback=progress_callback)


class CloudRunJobReplacement:
    def run(self, step: CrawlStep, repository: Any, collector: Any,
            progress_callback: Callable[[dict], None] | None = None) -> dict:
        # Cloud Scheduler must invoke a Cloud Run Job using IAM. It does not
        # supply a user ID or authorize an ordinary HTTP crawl request.
        raise PlatformAdapterRequired("Cloud Run Jobs execution is not connected")


def require_local_platform() -> None:
    """Fail before touching local SQLite, files, or an in-process job queue."""
    if os.getenv("K_SERVICE") or os.getenv("CLOUD_RUN_JOB"):
        raise PlatformAdapterRequired(
            "Cloud Run requires Identity Platform, PostgreSQL, durable media and "
            "Cloud Run Jobs adapters; local SQLite and in-process jobs are disabled"
        )
    choices = {
        "YGC_PLATFORM_TARGET": "local",
        "YGC_IDENTITY_BACKEND": "prototype",
        "YGC_DATABASE_BACKEND": "sqlite",
        "YGC_CRAWL_BACKEND": "local",
        "YGC_MEDIA_BACKEND": "local",
    }
    for key, expected in choices.items():
        actual = os.getenv(key, expected).strip().lower()
        if key == 'YGC_IDENTITY_BACKEND' and actual == 'local_dummy':
            continue
        if actual != expected:
            raise PlatformAdapterRequired(
                f"{key}={actual!r} requires a GCP adapter and migration; "
                f"the local {expected} implementation must not be used instead"
            )


def local_repository(db_path: Path):
    require_local_platform()
    from ygc.db.repository import Repository
    from ygc import config
    account_path = config.ACCOUNTS_DB_PATH if os.getenv('YGC_IDENTITY_BACKEND', 'prototype') == 'local_dummy' else None
    if account_path is None and config.ACCOUNTS_DB_PATH.is_file():
        import sqlite3
        with sqlite3.connect(config.ACCOUNTS_DB_PATH.as_uri() + '?mode=ro', uri=True) as con:
            if con.execute("SELECT 1 FROM sqlite_master WHERE name='account_records'").fetchone():
                raise PlatformAdapterRequired('This data has split accounts; restart with YGC_IDENTITY_BACKEND=local_dummy to preserve account synchronization.')
    return Repository(db_path, account_db_path=account_path)
