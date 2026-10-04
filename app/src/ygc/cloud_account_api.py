"""Authentication and operations API factory for staged integration, not the full WebUI."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, RedirectResponse
from ygc.db.postgres import connect

from ygc.cloud_account_routes import account_router
from ygc.cloud_operations_routes import operations_router
from ygc.db.postgres_operations import PostgresOperations
from ygc.cloud_registration import DOCUMENTS
from ygc.db.postgres_accounts import PostgresAccounts
from ygc.identity_platform import IdentityPlatformIdentity
from ygc.cloud_account_page import install, public_config


def create_app(settings, *, project_id, tenant='', web_config=None):
    config = public_config(web_config, project_id=project_id, tenant=tenant) if web_config is not None else None
    accounts = PostgresAccounts(settings)
    verifier = IdentityPlatformIdentity(accounts, project_id=project_id, tenant=tenant)

    @asynccontextmanager
    async def lifespan(app):
        try:
            try:
                await run_in_threadpool(accounts.check_schema)
            except Exception:
                raise RuntimeError('Cloud account database initialization check failed.') from None
            yield
        finally:
            verifier.close()

    app = FastAPI(title='YGC staging account API', lifespan=lifespan, docs_url=None, redoc_url=None,
                  openapi_url=None)
    app.include_router(account_router(verifier, DOCUMENTS))
    app.include_router(operations_router(verifier, PostgresOperations(settings)))
    @app.get('/health')
    def health():
        return JSONResponse({'status': 'ok'}, headers={'Cache-Control': 'no-store'})

    @app.get('/ready')
    def ready():
        try:
            for target in ('accounts', 'chronicle', 'operations'):
                with connect(settings, target) as con:
                    con.execute('SELECT 1').fetchone()
        except Exception:
            return JSONResponse({'status': 'unavailable'}, status_code=503,
                                headers={'Cache-Control': 'no-store'})
        return health()

    if config is not None:
        install(app, config)
        @app.get('/')
        def index():
            return RedirectResponse('/account')
    return app
