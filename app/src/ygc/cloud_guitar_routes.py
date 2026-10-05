"""Admin-only reading; no raw rows, private evidence, image URLs or writes."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from ygc.cloud_account_routes import bearer_token
from ygc.cloud_guitars import parameters,positive_id,GuitarMissing


def guitar_router(verifier,service):
    router=APIRouter();headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'}
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
    async def execute(request,detail_id=None):
        who=await actor(request)
        try:
            if detail_id is not None:
                if request.query_params:raise ValueError()
                result=await run_in_threadpool(service.detail,who,positive_id(detail_id))
            else:
                q,after,limit=parameters(request.query_params)
                result=await run_in_threadpool(service.list,who,q=q,after=after,limit=limit)
            # BIGINT identifiers cross JavaScript as decimal strings, without rounding.
            if detail_id is not None:result={**result,'id':str(result['id'])}
            else:
                result={'total':str(result['total']),'items':[{**row,'id':str(row['id'])} for row in result['items']],
                    'next_after':str(result['next_after']) if result['next_after'] is not None else None}
            return JSONResponse(result,headers=headers)
        except GuitarMissing:raise HTTPException(404,'Guitar not found.',headers=headers) from None
        except ValueError:raise HTTPException(400,'Invalid search or identifier.',headers=headers) from None
        except PermissionError:raise HTTPException(403,'Administrator access unavailable.',headers=headers) from None
        except Exception:raise HTTPException(503,'Guitar data unavailable.',headers=headers) from None
    @router.get('/api/admin/guitars')
    async def listing(request:Request):return await execute(request)
    @router.get('/api/admin/guitars/{individual_id}/chronicle')
    async def chronicle(request:Request,individual_id:str):
        who=await actor(request)
        try:
            if 'q' in request.query_params:raise ValueError()
            _,after,limit=parameters(request.query_params)
            result=await run_in_threadpool(service.chronicle,who,positive_id(individual_id),after=after,limit=limit)
            items=[{**row,'id':str(row['id']),'author_user_id':str(row['author_user_id'])} for row in result['items']]
            return JSONResponse({'items':items,'total':str(result['total']),
                'next_after':str(result['next_after']) if result['next_after'] is not None else None},headers=headers)
        except GuitarMissing:raise HTTPException(404,'Guitar not found.',headers=headers) from None
        except ValueError:raise HTTPException(400,'Invalid Chronicle page.',headers=headers) from None
        except PermissionError:raise HTTPException(403,'Administrator access unavailable.',headers=headers) from None
        except Exception:raise HTTPException(503,'Chronicle unavailable.',headers=headers) from None
    @router.get('/api/admin/guitars/{individual_id}')
    async def detail(request:Request,individual_id:str):return await execute(request,individual_id)
    return router
