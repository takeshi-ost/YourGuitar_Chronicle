"""Canonical verified-Admin Reverb control; credentials stay out of browser APIs."""
from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from ygc.cloud_account_routes import bearer_token
from ygc.cloud_backup_control import BackupBusy


def crawl_router(verifier,control):
    router=APIRouter();headers={'Cache-Control':'private, no-store'}
    async def actor(request):
        try:identity=await run_in_threadpool(verifier.verify,bearer_token=bearer_token(request))
        except HTTPException:raise
        except PermissionError:raise HTTPException(401,'Identity verification failed.',headers=headers) from None
        except Exception:raise HTTPException(503,'Identity verification unavailable.',headers=headers) from None
        try:
            if not identity.email_verified:raise PermissionError()
            account=await run_in_threadpool(verifier.accounts.resolve_identity,issuer=identity.issuer,subject=identity.subject,tenant=identity.tenant)
            if account['role']!='admin':raise PermissionError()
            return account['app_user_id']
        except PermissionError:raise HTTPException(403,'A verified active Admin is required.',headers=headers) from None
        except Exception:raise HTTPException(503,'Account status unavailable.',headers=headers) from None
    async def execute(function,*args):
        try:return JSONResponse(await run_in_threadpool(function,*args),headers=headers)
        except BackupBusy:raise HTTPException(409,'Crawl or maintenance is pending.',headers=headers) from None
        except ValueError:raise HTTPException(400,'Invalid Crawl request.',headers=headers) from None
        except PermissionError:raise HTTPException(403,'A verified active Admin is required.',headers=headers) from None
        except Exception:raise HTTPException(503,'Crawl operation unavailable.',headers=headers) from None
    async def data(request):
        try:
            if request.query_params or len(await request.body())>1024:raise ValueError()
            return await request.json()
        except (ValueError,TypeError):raise HTTPException(400,'Invalid Crawl settings.',headers=headers) from None
    @router.get('/api/admin/crawl')
    async def details(request:Request):
        admin=await actor(request)
        if request.query_params:raise HTTPException(400,'Unexpected query.',headers=headers)
        return await execute(control.details,admin)
    @router.put('/api/admin/crawl')
    async def configure(request:Request):return await execute(control.configure,await actor(request),await data(request))
    @router.post('/api/admin/crawl/start')
    async def start(request:Request):return await execute(control.start,await actor(request),await data(request))
    return router
