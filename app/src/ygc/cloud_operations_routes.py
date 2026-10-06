"""Cloud service mode API; no local Console token or claimed user IDs."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from ygc.cloud_account_routes import bearer_token
from ygc.db.postgres_operations import ModeConflict


def operations_router(verifier, operations, storage=None):
    router = APIRouter()

    def response(body):
        return JSONResponse(body, headers={'Cache-Control': 'private, no-store'})

    async def admin_identity(request):
        try:
            identity = await run_in_threadpool(verifier.verify, bearer_token=bearer_token(request))
        except PermissionError:
            raise HTTPException(401, 'Identity token verification failed.',
                headers={'WWW-Authenticate': 'Bearer', 'Cache-Control': 'no-store'}) from None
        if identity.email_verified is not True:
            raise HTTPException(403, 'Verify your email address first.', headers={'Cache-Control': 'no-store'})
        try:
            account = await run_in_threadpool(verifier.accounts.resolve_identity,
                issuer=identity.issuer, subject=identity.subject, tenant=identity.tenant)
        except PermissionError:
            raise HTTPException(403, 'An active administrator is required.', headers={'Cache-Control': 'no-store'}) from None
        except Exception:
            raise HTTPException(503, 'Account status is unavailable.', headers={'Cache-Control': 'no-store'}) from None
        if account['role'] != 'admin':
            raise HTTPException(403, 'An active administrator is required.', headers={'Cache-Control': 'no-store'})
        return account['app_user_id']

    async def execute(function, *args, **kwargs):
        try:
            return response(await run_in_threadpool(function, *args, **kwargs))
        except ModeConflict:
            raise HTTPException(409, 'Service status changed. Reload before retrying.', headers={'Cache-Control': 'no-store'}) from None
        except PermissionError:
            raise HTTPException(403, 'An active administrator is required.', headers={'Cache-Control': 'no-store'}) from None
        except ValueError:
            raise HTTPException(400, 'Invalid service settings.', headers={'Cache-Control': 'no-store'}) from None
        except Exception:
            raise HTTPException(503, 'Service status is unavailable.', headers={'Cache-Control': 'no-store'}) from None

    @router.get('/api/service/status')
    async def public_status():
        return await execute(operations.public_status)

    def storage_status(actor):
        with operations.access('admin_read', actor):
            if storage is None:
                raise RuntimeError('Storage is not configured.')
            return storage.status()

    @router.get('/api/admin/operations/storage')
    async def storage_details(request: Request):
        return await execute(storage_status, await admin_identity(request))

    @router.get('/api/admin/operations')
    async def details(request: Request):
        return await execute(operations.details, await admin_identity(request))

    @router.put('/api/admin/operations/mode')
    async def change_mode(request: Request):
        actor = await admin_identity(request)
        try:
            data = await request.json()
            if not isinstance(data, dict) or set(data) != {'mode', 'message', 'version'}:
                raise ValueError('Send only mode, message and version.')
        except (ValueError, TypeError):
            raise HTTPException(400, 'Send only mode, message and version.', headers={'Cache-Control': 'no-store'}) from None
        return await execute(operations.set_mode, actor, **data)

    @router.get('/api/admin/operations/review')
    async def review_status(request: Request):
        return await execute(operations.review_status, await admin_identity(request))

    @router.put('/api/admin/operations/review')
    async def review_mode(request: Request):
        actor = await admin_identity(request)
        if request.query_params or request.headers.get('content-encoding') or request.headers.get('content-type','').split(';')[0] != 'application/json':
            raise HTTPException(400, 'Invalid review settings.', headers={'Cache-Control':'no-store'})
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>1024:raise HTTPException(413, 'Request too large.')
        try:
            import json
            data=json.loads(body)
            if not isinstance(data,dict) or set(data)!={'enabled','expected_enabled'}:raise ValueError()
        except (ValueError,TypeError,UnicodeError):
            raise HTTPException(400,'Invalid review settings.') from None
        return await execute(operations.set_review,actor,**data)

    return router
