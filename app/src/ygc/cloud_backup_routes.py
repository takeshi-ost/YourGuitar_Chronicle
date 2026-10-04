"""Admin-only catalog reading; no raw backup, storage reference or restore endpoint."""
import json
from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from ygc.cloud_account_routes import bearer_token
from ygc.cloud_backup_job import KIND
from ygc.db.postgres import TARGETS


def catalog(operations,actor,target):
    if target not in TARGETS:raise ValueError('Invalid target.')
    with operations.access('admin_read',actor) as (con,mode,account):
        records=con.execute("""SELECT reason FROM events WHERE
            CASE WHEN reason LIKE %s THEN reason::jsonb ELSE NULL END ->>'target'=%s
            ORDER BY id DESC LIMIT 50""",('{"kind":"'+KIND+'",%',target)).fetchall()
        fields=('backup_id','target','created_at','schema_version','tables','rows')
        return {'target':target,'items':[{k:json.loads(row['reason'])[k] for k in fields} for row in records],
                'limit':50,'scope':'database_snapshot','restore_available':False}


def backup_router(verifier,operations):
    router=APIRouter();headers={'Cache-Control':'private, no-store'}
    @router.get('/api/admin/backups')
    async def listing(request:Request):
        try:identity=await run_in_threadpool(verifier.verify,bearer_token=bearer_token(request))
        except HTTPException:raise
        except PermissionError:raise HTTPException(401,'Identity verification failed.',headers=headers) from None
        except Exception:raise HTTPException(503,'Identity verification unavailable.',headers=headers) from None
        try:
            if not identity.email_verified:raise PermissionError()
            account=await run_in_threadpool(verifier.accounts.resolve_identity,issuer=identity.issuer,subject=identity.subject,tenant=identity.tenant)
            if account['role']!='admin':raise PermissionError()
            query=request.query_params
            if set(query)!={'target'} or len(query.getlist('target'))!=1:raise ValueError()
            result=await run_in_threadpool(catalog,operations,account['app_user_id'],query['target'])
            return JSONResponse(result,headers=headers)
        except ValueError:raise HTTPException(400,'Select one backup target.',headers=headers) from None
        except PermissionError:raise HTTPException(403,'A verified active administrator is required.',headers=headers) from None
        except Exception:raise HTTPException(503,'Backup catalog unavailable.',headers=headers) from None
    return router
