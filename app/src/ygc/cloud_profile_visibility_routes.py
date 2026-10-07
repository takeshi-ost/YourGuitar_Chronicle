"""Self-only saved visibility preferences; no public profiles or image access."""
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ygc.cloud_account_routes import bearer_token
from ygc.cloud_claim_routes import unique_object
from ygc.cloud_profile import ProfileConflict, validate_visibility, visibility_result
from ygc.db.postgres_operations import ServiceRestricted


def profile_visibility_router(verifier, service):
    router = APIRouter()
    headers = {'Cache-Control': 'private, no-store', 'Vary': 'Authorization',
               'X-Content-Type-Options': 'nosniff'}

    @router.api_route('/api/auth/profile/visibility', methods=['GET', 'PUT'])
    async def visibility(request: Request):
        try:
            token = bearer_token(request)
            if (len(request.headers.getlist('authorization')) != 1
                    or len(token) > 16384 or token != token.strip()):
                raise HTTPException(401, 'One valid Bearer token is required.', headers=headers)
            identity = await run_in_threadpool(verifier.verify, bearer_token=token)
        except HTTPException as exc:
            exc.headers = {**(exc.headers or {}), **headers}
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
            if (request.query_params or request.headers.getlist('content-encoding')
                    or any(len(request.headers.getlist(key)) > 1 for key in
                           ('content-type', 'content-length', 'origin', 'sec-fetch-site'))):
                raise ValueError()
            if request.method == 'GET':
                async for chunk in request.stream():
                    if chunk:
                        raise ValueError()
                result = await run_in_threadpool(service.own_visibility, account['app_user_id'])
            else:
                origin = request.headers.get('origin')
                if (request.headers.get('sec-fetch-site') == 'cross-site'
                        or (origin and origin != str(request.base_url).rstrip('/'))):
                    raise PermissionError()
                if (len(request.headers.getlist('content-type')) != 1
                        or request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json'):
                    raise ValueError()
                raw = bytearray()
                async for chunk in request.stream():
                    raw.extend(chunk)
                    if len(raw) > 2048:
                        raise HTTPException(413, 'Visibility request too large.', headers=headers)
                body = json.loads(raw, object_pairs_hook=unique_object)
                validate_visibility(body)
                result = await run_in_threadpool(service.edit_own_visibility, account['app_user_id'], body)
            return JSONResponse(visibility_result(result), headers=headers)
        except HTTPException as exc:
            exc.headers = {**(exc.headers or {}), **headers}
            raise
        except ProfileConflict:
            raise HTTPException(409, 'Profile changed or maintenance is running. Refresh before editing.', headers=headers) from None
        except ServiceRestricted:
            raise HTTPException(403, {'code': 'service_restricted'}, headers=headers) from None
        except PermissionError:
            raise HTTPException(403, 'Verified active account and service access required.', headers=headers) from None
        except (ValueError, TypeError, UnicodeError):
            raise HTTPException(400, 'Invalid visibility settings.', headers=headers) from None
        except Exception:
            raise HTTPException(503, 'Visibility result unavailable. Refresh before retrying.', headers=headers) from None

    return router
