"""Canonical verified Admin routes for private application management."""
import json
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from ygc.cloud_account_routes import bearer_token
from ygc.cloud_admin_applications import ApplicationConflict, parameters
from ygc.cloud_applications import revision_id
from ygc.cloud_content_media import MediaConflict
from ygc.cloud_guitars import GuitarMissing


def admin_application_router(verifier, service):
    router = APIRouter(prefix='/api/admin/applications')
    headers = {'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'}

    async def actor(request):
        try:
            identity = await run_in_threadpool(verifier.verify, bearer_token=bearer_token(request))
        except HTTPException:
            raise
        except PermissionError:
            raise HTTPException(401, 'Identity verification failed.', headers=headers) from None
        except Exception:
            raise HTTPException(503, 'Identity verification unavailable.', headers=headers) from None
        try:
            if identity.email_verified is not True:
                raise PermissionError()
            account = await run_in_threadpool(verifier.accounts.resolve_identity,
                issuer=identity.issuer, subject=identity.subject, tenant=identity.tenant)
            if account['role'] != 'admin':
                raise PermissionError()
            return account['app_user_id']
        except PermissionError:
            raise HTTPException(403, 'A verified active administrator is required.', headers=headers) from None
        except Exception:
            raise HTTPException(503, 'Account status unavailable.', headers=headers) from None

    async def handle(request, revision=None, role=None, decision=False):
        who = await actor(request)
        try:
            # Authorization is an explicit bearer header, never ambient cookies.
            # No CORS route is installed. Reject browser cross-origin attempts
            # as defense in depth, including form-compatible content types.
            origin = request.headers.get('origin')
            if ((origin is not None and origin != str(request.base_url).rstrip('/'))
                    or request.headers.get('sec-fetch-site') == 'cross-site'):
                raise PermissionError()
            if request.headers.get('content-encoding'):
                raise ValueError()
            if revision is None:
                result = await run_in_threadpool(service.list, who, **parameters(request.query_params))
            else:
                revision_id(revision)
                if request.query_params:
                    raise ValueError()
                if role is not None:
                    if role not in ('closeup', 'overview', 'reference'):
                        raise ValueError()
                    if service.storage is None:
                        raise HTTPException(503, 'Private image storage unavailable.', headers=headers)
                    data = await run_in_threadpool(service.image, who, revision, role)
                    return Response(data, media_type='image/jpeg', headers=headers)
                if decision:
                    if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
                        raise ValueError()
                    body = bytearray()
                    async for chunk in request.stream():
                        body.extend(chunk)
                        if len(body) > 32 * 1024:
                            raise HTTPException(413, 'Request too large.', headers=headers)
                    def unique(pairs):
                        data = {}
                        for key, value in pairs:
                            if key in data:
                                raise ValueError()
                            data[key] = value
                        return data
                    payload = json.loads(body, object_pairs_hook=unique)
                    if not isinstance(payload, dict) or set(payload) != {'operation', 'reason', 'expected_version'}:
                        raise ValueError()
                    result = await run_in_threadpool(service.decide, who, revision, **payload)
                else:
                    result = await run_in_threadpool(service.detail, who, revision)
            return JSONResponse(result, headers=headers)
        except HTTPException:
            raise
        except GuitarMissing:
            raise HTTPException(404, 'Application or private image not found.', headers=headers) from None
        except (ApplicationConflict, MediaConflict):
            raise HTTPException(409, 'Application changed or maintenance is running. Refresh before deciding.', headers=headers) from None
        except PermissionError:
            raise HTTPException(403, 'Administrator access unavailable.', headers=headers) from None
        except (ValueError, TypeError, UnicodeError):
            raise HTTPException(400, 'Invalid application decision, evidence or account projection. Refresh before deciding.', headers=headers) from None
        except Exception:
            raise HTTPException(503, 'Application result unavailable. Refresh before retrying.', headers=headers) from None

    @router.get('')
    async def listing(request: Request):
        return await handle(request)

    @router.get('/{revision}')
    async def detail(request: Request, revision: str):
        return await handle(request, revision)

    @router.get('/{revision}/photos/{role}')
    async def image(request: Request, revision: str, role: str):
        return await handle(request, revision, role=role)

    @router.post('/{revision}/decision')
    async def decide(request: Request, revision: str):
        return await handle(request, revision, decision=True)

    return router
