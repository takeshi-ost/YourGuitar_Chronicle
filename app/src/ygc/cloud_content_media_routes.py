"""Explicit administrator image creation and authenticated binary delivery."""
from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import JSONResponse,Response
from starlette.concurrency import run_in_threadpool
from ygc.cloud_account_routes import bearer_token
from ygc.cloud_guitars import positive_id,GuitarMissing
from ygc.cloud_content_media import MediaConflict
from ygc.cloud_avatar import MAX_UPLOAD,ImageUploadInvalid


def content_media_router(verifier,service):
    router=APIRouter();headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'}
    async def handle(request,individual,media=None):
        try:identity=await run_in_threadpool(verifier.verify,bearer_token=bearer_token(request))
        except HTTPException:raise
        except PermissionError:raise HTTPException(401,'Identity verification failed.',headers=headers) from None
        except Exception:raise HTTPException(503,'Identity verification unavailable.',headers=headers) from None
        try:
            if identity.email_verified is not True:raise PermissionError()
            account=await run_in_threadpool(verifier.accounts.resolve_identity,issuer=identity.issuer,subject=identity.subject,tenant=identity.tenant)
            if account['role']!='admin':raise PermissionError()
            who=account['app_user_id'];individual=positive_id(individual)
            if service.storage is None:raise HTTPException(503,'Image storage unavailable.',headers=headers)
            if media is not None:
                if request.query_params:raise ValueError()
                data=await run_in_threadpool(service.get,who,individual,positive_id(media))
                return Response(data,media_type='image/jpeg',headers=headers)
            if request.method=='GET':
                query=request.query_params
                if set(query)-{'after'} or any(len(query.getlist(k))!=1 for k in query):raise ValueError()
                result=await run_in_threadpool(service.listing,who,individual,after=positive_id(query['after']) if 'after' in query else 0)
            else:
                if request.query_params or request.headers.get('content-encoding'):raise ValueError()
                mime=request.headers.get('content-type','').split(';')[0].strip().lower()
                if mime not in ('image/jpeg','image/png','image/webp'):raise ImageUploadInvalid('image_format')
                chunks=[];size=0
                async for chunk in request.stream():
                    size+=len(chunk)
                    if size>MAX_UPLOAD:raise HTTPException(413,{'code':'image_size_limit'},headers=headers)
                    chunks.append(chunk)
                result=await run_in_threadpool(service.upload,who,individual,b''.join(chunks),mime)
            return JSONResponse(result,headers=headers)
        except HTTPException:raise
        except GuitarMissing:raise HTTPException(404,'Image or guitar not found.',headers=headers) from None
        except MediaConflict:raise HTTPException(409,'Crawl or database maintenance is running.',headers=headers) from None
        except PermissionError:raise HTTPException(403,'Verified administrator access required.',headers=headers) from None
        except ImageUploadInvalid as error:raise HTTPException(400,{'code':error.code},headers=headers) from None
        except (ValueError,TypeError):raise HTTPException(400,'Invalid image, identifier or pending account projection.',headers=headers) from None
        except Exception:raise HTTPException(503,'Image result unavailable. Refresh before retrying.',headers=headers) from None
    @router.api_route('/api/admin/guitars/{individual}/media',methods=['GET','POST'])
    async def images(request:Request,individual:str):return await handle(request,individual)
    @router.get('/api/admin/guitars/{individual}/media/{media}')
    async def image(request:Request,individual:str,media:str):return await handle(request,individual,media)
    return router
