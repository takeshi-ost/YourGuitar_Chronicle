"""Strict verified-author routes for the bounded cloud Claim editor."""
import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ygc.claim_dates import viewer_timezone
from ygc.claim_revision import ClaimConflict
from ygc.cloud_account_routes import bearer_token
from ygc.cloud_guitars import GuitarMissing, positive_id
from ygc.db.postgres_operations import ServiceRestricted


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON field.')
        result[key] = value
    return result


def claim_router(verifier, service):
    router = APIRouter()
    headers = {'Cache-Control': 'private, no-store', 'Vary': 'Authorization',
               'X-Content-Type-Options': 'nosniff'}

    async def handle(request, individual, claim=None, deactivate=False):
        try:
            identity = await run_in_threadpool(verifier.verify, bearer_token=bearer_token(request))
        except HTTPException:
            raise
        except PermissionError:
            raise HTTPException(401, 'Identity verification failed.', headers=headers) from None
        except Exception:
            raise HTTPException(503, 'Identity verification unavailable.', headers=headers) from None
        zone_token = None
        try:
            if identity.email_verified is not True:
                raise PermissionError()
            account = await run_in_threadpool(verifier.accounts.resolve_identity,
                issuer=identity.issuer, subject=identity.subject, tenant=identity.tenant)
            if request.headers.get('content-encoding') or len(request.headers.getlist('authorization')) != 1:
                raise ValueError()
            who, individual = account['app_user_id'], positive_id(individual)
            if claim is not None:
                claim = positive_id(claim)
            if request.method == 'GET':
                query = request.query_params
                if set(query) - {'after', 'limit'} or any(len(query.getlist(key)) != 1 for key in query):
                    raise ValueError()
                after = positive_id(query['after']) if 'after' in query else 0
                limit = positive_id(query['limit']) if 'limit' in query else 25
                result = await run_in_threadpool(service.list, who, individual, after=after, limit=limit)
            else:
                # Authentication is never cookie-based. Also reject cross-site
                # browser writes explicitly; this router does not enable CORS.
                origin = request.headers.get('origin')
                if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and origin != str(request.base_url).rstrip('/')):
                    raise PermissionError()
                if request.query_params or request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
                    raise ValueError()
                zone = request.headers.get('x-ygc-timezone', 'UTC')
                if len(zone) > 100:
                    raise ValueError()
                zone_token = viewer_timezone.set(ZoneInfo(zone))
                raw = bytearray()
                async for chunk in request.stream():
                    raw.extend(chunk)
                    # 50 fields and values at their Unicode limits, including
                    # escaped surrogate pairs, fit without silently truncating.
                    if len(raw) > 512 * 1024:
                        raise HTTPException(413, 'Claim request too large.', headers=headers)
                data = json.loads(raw, object_pairs_hook=unique_object)
                if not isinstance(data, dict):
                    raise ValueError()
                if claim is None:
                    result = await run_in_threadpool(service.create, who, individual, data)
                elif deactivate:
                    result = await run_in_threadpool(service.deactivate, who, individual, claim, data)
                else:
                    result = await run_in_threadpool(service.edit, who, individual, claim, data)
            return JSONResponse(result, headers=headers)
        except HTTPException:
            raise
        except GuitarMissing:
            raise HTTPException(404, 'Guitar or own Claim not found.', headers=headers) from None
        except ClaimConflict:
            raise HTTPException(409, 'Claim changed or maintenance is running. Reload before retrying.', headers=headers) from None
        except ServiceRestricted:
            raise HTTPException(403, {'code': 'service_restricted'}, headers=headers) from None
        except PermissionError:
            raise HTTPException(403, 'Verified active account and service access required.', headers=headers) from None
        except (ValueError, TypeError, UnicodeError, ZoneInfoNotFoundError):
            raise HTTPException(400, 'Invalid Claim or pending account projection.', headers=headers) from None
        except Exception:
            raise HTTPException(503, 'Claim result unavailable. Refresh before retrying.', headers=headers) from None
        finally:
            if zone_token is not None:
                viewer_timezone.reset(zone_token)

    @router.api_route('/api/auth/guitars/{individual}/claims', methods=['GET', 'POST'])
    async def claims(request: Request, individual: str):
        return await handle(request, individual)

    @router.patch('/api/auth/guitars/{individual}/claims/{claim}')
    async def edit(request: Request, individual: str, claim: str):
        return await handle(request, individual, claim)

    @router.post('/api/auth/guitars/{individual}/claims/{claim}/deactivate')
    async def deactivate(request: Request, individual: str, claim: str):
        return await handle(request, individual, claim, True)

    return router
