"""Verified applicant identity; private application and binary photo delivery."""
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from ygc.claim_dates import viewer_timezone
from ygc.cloud_account_routes import bearer_token
from ygc.cloud_applications import revision_id
from ygc.cloud_avatar import MAX_UPLOAD, ImageUploadInvalid
from ygc.cloud_content_media import MediaConflict
from ygc.cloud_guitars import GuitarMissing


def application_router(verifier,service):
    router=APIRouter();headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'}
    async def handle(request,revision=None,action=None,role=None):
        try:identity=await run_in_threadpool(verifier.verify,bearer_token=bearer_token(request))
        except HTTPException:raise
        except PermissionError:raise HTTPException(401,'Identity verification failed.',headers=headers) from None
        except Exception:raise HTTPException(503,'Identity verification unavailable.',headers=headers) from None
        zone_token=None
        try:
            if identity.email_verified is not True:raise PermissionError()
            account=await run_in_threadpool(verifier.accounts.resolve_identity,issuer=identity.issuer,subject=identity.subject,tenant=identity.tenant)
            if request.query_params or request.headers.get('content-encoding'):raise ValueError()
            zone=request.headers.get('x-ygc-timezone','UTC')
            if len(zone)>100:raise ValueError()
            zone_token=viewer_timezone.set(ZoneInfo(zone))
            who=account['app_user_id']
            if revision is not None:revision_id(revision)
            if role is not None and role not in ('closeup','overview'):raise ValueError()
            if role is not None and request.method=='GET':
                if service.storage is None:raise HTTPException(503,'Image storage unavailable.',headers=headers)
                image=await run_in_threadpool(service.image,who,revision,role)
                return Response(image,media_type='image/jpeg',headers=headers)
            if request.method=='GET':result=await run_in_threadpool(service.list,who)
            else:
                mime=request.headers.get('content-type','').split(';')[0].strip().lower()
                if role is not None:
                    if service.storage is None:raise HTTPException(503,'Image storage unavailable.',headers=headers)
                    if mime not in ('image/jpeg','image/png','image/webp'):raise ImageUploadInvalid('image_format')
                    limit=MAX_UPLOAD
                else:
                    if mime!='application/json':raise ValueError()
                    limit=20000
                chunks=[];size=0
                async for chunk in request.stream():
                    size+=len(chunk)
                    if size>limit:raise HTTPException(413,{'code':'image_size_limit'} if role else 'Request too large.',headers=headers)
                    chunks.append(chunk)
                raw=b''.join(chunks)
                if role is not None:result=await run_in_threadpool(service.upload,who,revision,role,raw,mime)
                else:
                    import json
                    data=json.loads(raw)
                    if not isinstance(data,dict):raise ValueError()
                    if action=='cancel':
                        if data:raise ValueError()
                        result=await run_in_threadpool(service.cancel,who,revision)
                    elif action=='submit':
                        if service.storage is None:raise HTTPException(503,'Image storage unavailable.',headers=headers)
                        result=await run_in_threadpool(service.submit,who,revision,data)
                    else:result=await run_in_threadpool(service.start,who,data)
            return JSONResponse(result,headers=headers)
        except HTTPException:raise
        except GuitarMissing:raise HTTPException(404,'Application or image not found.',headers=headers) from None
        except MediaConflict:raise HTTPException(409,'Crawl or database maintenance is running.',headers=headers) from None
        except PermissionError:raise HTTPException(403,'Verified applicant and service access required.',headers=headers) from None
        except ImageUploadInvalid as error:raise HTTPException(400,{'code':error.code},headers=headers) from None
        except (ValueError,TypeError,UnicodeError,ZoneInfoNotFoundError):raise HTTPException(400,'Invalid application, expired draft or pending account projection.',headers=headers) from None
        except Exception:raise HTTPException(503,'Application result unavailable. Refresh before retrying.',headers=headers) from None
        finally:
            if zone_token is not None:viewer_timezone.reset(zone_token)
    @router.api_route('/api/auth/applications',methods=['GET','POST'])
    async def applications(request:Request):return await handle(request)
    @router.post('/api/auth/applications/{revision}/submit')
    async def submit(request:Request,revision:str):return await handle(request,revision,'submit')
    @router.post('/api/auth/applications/{revision}/cancel')
    async def cancel(request:Request,revision:str):return await handle(request,revision,'cancel')
    @router.api_route('/api/auth/applications/{revision}/photos/{role}',methods=['GET','POST'])
    async def photo(request:Request,revision:str,role:str):return await handle(request,revision,role=role)
    return router
