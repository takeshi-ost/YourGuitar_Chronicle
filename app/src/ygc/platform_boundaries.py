"""Local adapters and explicit replacement contracts for a future GCP deployment.

A prototype user ID is an assertion from the browser, NOT authentication.
No cloud SDK or simulated credential verifier is installed here.
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
    def resolve(self, *, bearer_token: str | None,
                prototype_user_id: int | None = None) -> ActorContext:
        # Future adapter: verify the Identity Platform ID token server-side;
        # map (issuer/provider, subject) to users.id; ignore client user IDs.
        raise PlatformAdapterRequired("Identity Platform token verification is not connected")


@dataclass(frozen=True)
class CrawlStep:
    category: str
    year_min: int
    year_max: int
    origin: str = "manual"

    def __post_init__(self) -> None:
        if self.category not in ("all", "electric", "acoustic") or not 1800 <= self.year_min <= self.year_max <= 2100:
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
        if actual != expected:
            raise PlatformAdapterRequired(
                f"{key}={actual!r} requires a GCP adapter and migration; "
                f"the local {expected} implementation must not be used instead"
            )


def local_repository(db_path: Path):
    require_local_platform()
    from ygc.db.repository import Repository
    return Repository(db_path)
