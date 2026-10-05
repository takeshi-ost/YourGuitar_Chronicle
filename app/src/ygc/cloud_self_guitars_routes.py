"""Read-only ownership pages whose subject is always the authenticated user."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import QueryParams
from ygc.cloud_account_routes import bearer_token
from ygc.cloud_users import parameters


def self_guitars_router(verifier, service):
    router=APIRouter()
    headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'}

    @router.get('/api/auth/guitars')
    async def guitars(request:Request):
        try:
            identity=await run_in_threadpool(verifier.verify,bearer_token=bearer_token(request))
        except HTTPException:raise
        except PermissionError:raise HTTPException(401,'Identity verification failed.',headers=headers) from None
        except Exception:raise HTTPException(503,'Identity verification unavailable.',headers=headers) from None
        try:
            if identity.email_verified is not True:raise PermissionError()
            account=await run_in_threadpool(verifier.accounts.resolve_identity,
                issuer=identity.issuer,subject=identity.subject,tenant=identity.tenant)
            query=request.query_params
            if set(query)-{'kind','after','limit'} or any(len(query.getlist(key))!=1 for key in query):raise ValueError()
            kind=query.get('kind','owned')
            if kind not in ('owned','formerly_owned'):raise ValueError()
            _,after,limit=parameters(QueryParams([(key,value) for key,value in query.multi_items() if key!='kind']))
            page=await run_in_threadpool(service.own_guitars,account['app_user_id'],kind=kind,after=after,limit=limit)
            return JSONResponse(dict(total=str(page['total']),
                items=[{**row,'id':str(row['id'])} for row in page['items']],
                next_after=str(page['next_after']) if page['next_after'] is not None else None),headers=headers)
        except (ValueError,TypeError):raise HTTPException(400,'Invalid ownership page.',headers=headers) from None
        except PermissionError:raise HTTPException(403,'Verified account and service access are required.',headers=headers) from None
        except Exception:raise HTTPException(503,'Ownership data unavailable.',headers=headers) from None
    return router
