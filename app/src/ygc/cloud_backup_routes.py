"""Admin-only backup catalog and confirmed private maintenance Jobs."""
import json
from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from ygc.cloud_account_routes import bearer_token
from ygc.cloud_backup_job import KIND
from ygc.cloud_backup_control import BackupBusy
from ygc.cloud_backup_policy import policy,configure
from ygc.cloud_maintenance_control import MaintenanceModeRequired
from ygc.db.postgres import TARGETS


def catalog(operations,actor,target):
    if target not in TARGETS:raise ValueError('Invalid target.')
    with operations.access('admin_read',actor) as (con,mode,account):
        records=con.execute("""SELECT reason FROM events WHERE
            CASE WHEN reason LIKE %s THEN reason::jsonb ELSE NULL END ->>'target'=%s
            AND CASE WHEN reason LIKE %s THEN reason::jsonb ELSE NULL END ->>'deleted_at' IS NULL
            ORDER BY id DESC LIMIT 50""",('{"kind":"'+KIND+'",%',target,'{"kind":"'+KIND+'",%')).fetchall()
        fields=('backup_id','target','created_at','schema_version','tables','rows')
        return {'target':target,'items':[{k:json.loads(row['reason'])[k] for k in fields} for row in records],
                'limit':50,'scope':'database_snapshot','restore_available':False}


def backup_router(verifier,operations,control=None,maintenance=None):
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
        except PermissionError:raise HTTPException(403,'A verified active administrator is required.',headers=headers) from None
        except Exception:raise HTTPException(503,'Account status unavailable.',headers=headers) from None

    def target_query(request):
        query=request.query_params
        if set(query)!={'target'} or len(query.getlist('target'))!=1 or query['target'] not in TARGETS:raise ValueError()
        return query['target']

    async def execute(function,*args):
        try:
            return JSONResponse(await run_in_threadpool(function,*args),headers=headers)
        except BackupBusy:raise HTTPException(409,'A save is already pending for this database.',headers=headers) from None
        except MaintenanceModeRequired:raise HTTPException(409,'Maintenance mode is required.',headers=headers) from None
        except ValueError:raise HTTPException(400,'Invalid backup request.',headers=headers) from None
        except PermissionError:raise HTTPException(403,'A verified active administrator is required.',headers=headers) from None
        except Exception:raise HTTPException(503,'Backup operation unavailable.',headers=headers) from None

    @router.get('/api/admin/backups')
    async def listing(request:Request):
        admin=await actor(request)
        try:
            target=target_query(request)
        except ValueError:raise HTTPException(400,'Select one backup target.',headers=headers) from None
        result=await execute(catalog,operations,admin,target)
        # Availability is deployment configuration, never inferred from client privileges.
        body=json.loads(result.body);body['save_available']=control is not None;body['maintenance_available']=maintenance is not None;body['restore_available']=maintenance is not None
        return JSONResponse(body,headers=headers)

    @router.post('/api/admin/backups/save')
    async def save(request:Request):
        admin=await actor(request)
        if control is None:raise HTTPException(503,'Manual saving is not configured.',headers=headers)
        try:
            if request.query_params or len(await request.body())>1024:raise ValueError()
            data=await request.json()
            if not isinstance(data,dict) or set(data)!={'target','request_id'}:raise ValueError()
        except (ValueError,TypeError):raise HTTPException(400,'Select one database and request UUID.',headers=headers) from None
        return await execute(control.start,admin,data['target'],data['request_id'])

    @router.get('/api/admin/backups/policy')
    async def read_policy(request:Request):
        admin=await actor(request)
        try:target=target_query(request)
        except ValueError:raise HTTPException(400,'Select one backup target.',headers=headers) from None
        return await execute(policy,operations,admin,target)

    @router.put('/api/admin/backups/policy')
    async def write_policy(request:Request):
        admin=await actor(request)
        try:
            if request.query_params or len(await request.body())>1024:raise ValueError()
            data=await request.json()
            if not isinstance(data,dict) or set(data)!={'target','generations','enabled','interval_hours'}:raise ValueError()
        except (ValueError,TypeError):raise HTTPException(400,'Invalid backup policy.',headers=headers) from None
        return await execute(configure,operations,admin,data['target'],data['generations'],data['enabled'],data['interval_hours'])

    @router.get('/api/admin/backups/save-status')
    async def status(request:Request):
        admin=await actor(request)
        if control is None:raise HTTPException(503,'Manual saving is not configured.',headers=headers)
        try:target=target_query(request)
        except ValueError:raise HTTPException(400,'Select one backup target.',headers=headers) from None
        return await execute(control.status,admin,target)

    @router.post('/api/admin/databases/maintain')
    async def maintain(request:Request):
        admin=await actor(request)
        if maintenance is None:raise HTTPException(503,'Maintenance is not configured.',headers=headers)
        try:
            if request.query_params or len(await request.body())>1024:raise ValueError()
            data=await request.json()
        except (ValueError,TypeError):raise HTTPException(400,'Invalid maintenance request.',headers=headers) from None
        return await execute(maintenance.start,admin,data)

    @router.get('/api/admin/databases/status')
    async def maintenance_status(request:Request):
        admin=await actor(request)
        if maintenance is None:raise HTTPException(503,'Maintenance is not configured.',headers=headers)
        try:target=target_query(request)
        except ValueError:raise HTTPException(400,'Select one database.',headers=headers) from None
        return await execute(maintenance.status,admin,target)
    return router
