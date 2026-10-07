"""Strict verified-author routes for private cloud Identity Corrections."""
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ygc.claim_revision import ClaimConflict
from ygc.cloud_account_routes import bearer_token
from ygc.cloud_claim_routes import unique_object
from ygc.cloud_guitars import GuitarMissing, positive_id
from ygc.db.postgres_operations import ServiceRestricted


def identity_correction_router(verifier, service):
    router = APIRouter()
    headers = {'Cache-Control': 'private, no-store', 'Vary': 'Authorization',
               'X-Content-Type-Options': 'nosniff'}

    async def handle(request, listing=None):
        try:
            identity = await run_in_threadpool(verifier.verify, bearer_token=bearer_token(request))
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
            if request.headers.get('content-encoding') or len(request.headers.getlist('authorization')) != 1:
                raise ValueError()
            args = [account['app_user_id']]
            if listing is not None:
                args.append(positive_id(listing))
            if request.method == 'GET':
                query = request.query_params
                if set(query) - {'after', 'limit'} or any(len(query.getlist(key)) != 1 for key in query):
                    raise ValueError()
                after = positive_id(query['after']) if 'after' in query else 0
                limit = positive_id(query['limit']) if 'limit' in query else 25
                if limit > 50:
                    raise ValueError()
                result = await run_in_threadpool(service.list if listing is None else service.detail,
                                                *args, after=after, limit=limit)
            else:
                origin = request.headers.get('origin')
                if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and origin != str(request.base_url).rstrip('/')):
                    raise PermissionError()
                if request.query_params or request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
                    raise ValueError()
                raw = bytearray()
                async for chunk in request.stream():
                    raw.extend(chunk)
                    if len(raw) > 32 * 1024:
                        raise HTTPException(413, 'Identity Correction request too large.', headers=headers)
                data = json.loads(raw, object_pairs_hook=unique_object)
                if not isinstance(data, dict):
                    raise ValueError()
                result = await run_in_threadpool(service.create, *args, data)
            return JSONResponse(result, headers=headers)
        except HTTPException as exc:
            exc.headers = {**(exc.headers or {}), **headers}
            raise
        except GuitarMissing:
            raise HTTPException(404, 'Own active Listing not found.', headers=headers) from None
        except ClaimConflict:
            raise HTTPException(409, 'Identity changed, duplicates another guitar, or maintenance is running. Reload before retrying.', headers=headers) from None
        except ServiceRestricted:
            raise HTTPException(403, {'code': 'service_restricted'}, headers=headers) from None
        except PermissionError:
            raise HTTPException(403, 'Verified active author and service access required.', headers=headers) from None
        except (ValueError, TypeError, UnicodeError):
            raise HTTPException(400, 'Invalid Identity Correction or pending account projection.', headers=headers) from None
        except Exception:
            raise HTTPException(503, 'Identity Correction result unavailable. Refresh before retrying.', headers=headers) from None

    @router.get('/api/auth/identity-corrections')
    async def listings(request: Request):
        return await handle(request)

    @router.api_route('/api/auth/identity-corrections/{listing}', methods=['GET', 'POST'])
    async def correction(request: Request, listing: str):
        return await handle(request, listing)

    return router
