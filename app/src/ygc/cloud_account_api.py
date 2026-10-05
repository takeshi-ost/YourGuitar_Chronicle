"""Authentication and operations API factory for staged integration, not the full WebUI."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, RedirectResponse
from ygc.db.postgres import connect

from ygc.cloud_account_routes import account_router
from ygc.cloud_avatar_routes import avatar_router
from ygc.cloud_backup_routes import backup_router
from ygc.cloud_guitar_routes import guitar_router
from ygc.cloud_guitars import CloudGuitars
from ygc.cloud_users import CloudUsers
from ygc.cloud_user_routes import user_router
from ygc.cloud_operations_routes import operations_router
from ygc.db.postgres_operations import PostgresOperations
from ygc.cloud_registration import DOCUMENTS
from ygc.db.postgres_accounts import PostgresAccounts
from ygc.identity_platform import IdentityPlatformIdentity
from ygc.cloud_account_page import install, public_config


def create_app(settings, *, project_id, tenant='', web_config=None, storage=None, backup_client=None,maintenance_client=None,crawl_client=None,review_verifier=None):
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
            if review_verifier is not None:review_verifier.close()
            if backup_client is not None:
                backup_client.close()
            if maintenance_client is not None:maintenance_client.close()
            if crawl_client is not None:crawl_client.close()
            if storage is not None:
                storage.close()

    app = FastAPI(title='YGC staging account API', lifespan=lifespan, docs_url=None, redoc_url=None,
                  openapi_url=None)
    app.include_router(account_router(verifier, DOCUMENTS))
    if review_verifier is not None:
        from ygc.cloud_review_gateway import review_gateway
        app.include_router(review_gateway(review_verifier))
    operations = PostgresOperations(settings)
    app.include_router(operations_router(verifier, operations, storage))
    app.include_router(avatar_router(verifier, operations, storage))
    from ygc.cloud_backup_control import BackupControl
    from ygc.cloud_maintenance_control import MaintenanceControl
    app.include_router(backup_router(verifier,operations,BackupControl(operations,backup_client) if backup_client is not None else None,MaintenanceControl(operations,maintenance_client) if maintenance_client is not None else None))
    from ygc.cloud_crawl_control import CrawlControl
    from ygc.cloud_crawl_routes import crawl_router
    app.include_router(crawl_router(verifier,CrawlControl(operations,crawl_client)))
    app.include_router(guitar_router(verifier, CloudGuitars(settings,operations)))
    from ygc.cloud_content_media import CloudContentMedia
    from ygc.cloud_content_media_routes import content_media_router
    app.include_router(content_media_router(verifier,CloudContentMedia(settings,operations,storage)))
    app.include_router(user_router(verifier,CloudUsers(settings,operations)))
    from ygc.cloud_self_profile_routes import self_profile_router
    app.include_router(self_profile_router(verifier,CloudUsers(settings,operations)))
    from ygc.cloud_self_guitars_routes import self_guitars_router
    app.include_router(self_guitars_router(verifier,CloudUsers(settings,operations)))
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
