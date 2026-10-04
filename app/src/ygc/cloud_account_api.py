"""Authentication-only API factory for staged integration, not the full WebUI."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from ygc.cloud_account_routes import account_router
from ygc.cloud_registration import DOCUMENTS
from ygc.db.postgres_accounts import PostgresAccounts
from ygc.identity_platform import IdentityPlatformIdentity


def create_app(settings, *, project_id, tenant=''):
    accounts = PostgresAccounts(settings)
    verifier = IdentityPlatformIdentity(accounts, project_id=project_id, tenant=tenant)

    @asynccontextmanager
    async def lifespan(app):
        try:
            await run_in_threadpool(accounts.check_schema)
            yield
        finally:
            verifier.close()

    app = FastAPI(title='YGC staging account API', lifespan=lifespan, docs_url=None, redoc_url=None,
                  openapi_url=None)
    app.include_router(account_router(verifier, DOCUMENTS))
    return app
