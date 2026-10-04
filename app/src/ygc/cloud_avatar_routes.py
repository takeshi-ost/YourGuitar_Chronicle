"""Authenticated self-avatar APIs; administrator maintenance path is explicit."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from ygc.cloud_account_routes import bearer_token
from ygc.cloud_avatar import CloudAvatar, AvatarMissing, MAX_UPLOAD


def avatar_router(verifier, operations, storage):
    router = APIRouter()
    service = CloudAvatar(operations,storage)
    headers = {'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'}

    async def actor(request, admin):
        if request.query_params:
            raise HTTPException(400,'Do not supply an account identifier.',headers=headers)
        try:
            identity = await run_in_threadpool(verifier.verify,bearer_token=bearer_token(request))
        except PermissionError:
            raise HTTPException(401,'Identity token verification failed.',headers=headers) from None
        except HTTPException:raise
        except Exception:
            raise HTTPException(503,'Identity verification is unavailable.',headers=headers) from None
        try:
            if identity.email_verified is not True:raise PermissionError()
            account = await run_in_threadpool(verifier.accounts.resolve_identity,
                issuer=identity.issuer,subject=identity.subject,tenant=identity.tenant)
            if admin and account['role']!='admin':raise PermissionError()
            return account['app_user_id']
        except HTTPException:raise
        except PermissionError:
            raise HTTPException(403,'A verified active account is required.',headers=headers) from None
        except Exception:
            raise HTTPException(503,'Account status is unavailable.',headers=headers) from None

    async def handle(request, admin=False):
        who = await actor(request,admin)
        if storage is None:raise HTTPException(503,'Image storage is unavailable.',headers=headers)
        try:
            if request.method=='GET':
                data=await run_in_threadpool(service.get,who,admin=admin)
                return Response(data,media_type='image/jpeg',headers=headers)
            data=None;mime=None
            if request.method=='PUT':
                if request.headers.get('content-encoding'):
                    raise ValueError('Unsupported encoding.')
                mime=request.headers.get('content-type','').split(';')[0].strip().lower()
                if mime not in ('image/jpeg','image/png','image/webp'):raise ValueError('Unsupported type.')
                chunks=[];size=0
                async for chunk in request.stream():
                    size+=len(chunk)
                    if size>MAX_UPLOAD:raise HTTPException(413,'Image size limit exceeded.',headers=headers)
                    chunks.append(chunk)
                data=b''.join(chunks)
            result=await run_in_threadpool(service.set,who,data,mime,admin=admin)
            return JSONResponse(result,headers=headers)
        except HTTPException:raise
        except AvatarMissing:
            raise HTTPException(404,'No account image.',headers=headers) from None
        except PermissionError:
            raise HTTPException(403,'This operation is not available.',headers=headers) from None
        except ValueError:
            raise HTTPException(400,'Use a valid JPEG, PNG or WebP image within the limits.',headers=headers) from None
        except Exception:
            raise HTTPException(503,'Account image is unavailable.',headers=headers) from None

    @router.api_route('/api/auth/avatar',methods=['GET','PUT','DELETE'])
    async def own_avatar(request:Request):return await handle(request)

    @router.api_route('/api/admin/accounts/me/avatar',methods=['GET','PUT','DELETE'])
    async def administrative_avatar(request:Request):return await handle(request,True)

    return router
