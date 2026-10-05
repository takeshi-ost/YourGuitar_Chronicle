"""Verified self-profile access; target comes only from the canonical identity."""
import json
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from ygc.cloud_account_routes import bearer_token
from ygc.cloud_profile import validate, ProfileConflict


def self_profile_router(verifier, service):
    router = APIRouter()
    headers = {'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'}

    @router.api_route('/api/auth/profile', methods=['GET', 'PUT'])
    async def profile(request: Request):
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
            if request.query_params:
                raise ValueError()
            if request.method == 'GET':
                result = await run_in_threadpool(service.own_profile, account['app_user_id'])
            else:
                if request.headers.get('content-encoding') or request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
                    raise ValueError()
                chunks, size = [], 0
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > 20000:
                        raise HTTPException(413, 'Profile size exceeded.', headers=headers)
                    chunks.append(chunk)
                def unique(pairs):
                    result = {}
                    for key, value in pairs:
                        if key in result:
                            raise ValueError()
                        result[key] = value
                    return result
                body = json.loads(b''.join(chunks), object_pairs_hook=unique)
                validate(body)
                result = await run_in_threadpool(service.edit_own_profile, account['app_user_id'], body)
            return JSONResponse(result, headers=headers)
        except HTTPException:
            raise
        except ProfileConflict:
            raise HTTPException(409, 'Profile changed or maintenance is running. Refresh before editing.', headers=headers) from None
        except (ValueError, TypeError):
            raise HTTPException(400, 'Invalid profile.', headers=headers) from None
        except PermissionError:
            raise HTTPException(403, 'Verified account and service access are required.', headers=headers) from None
        except Exception:
            raise HTTPException(503, 'Profile result unavailable. Refresh before retrying.', headers=headers) from None
    return router
