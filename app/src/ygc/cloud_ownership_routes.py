"""Strict authenticated routes for private Transfer participants and Release."""
import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ygc.claim_dates import viewer_timezone
from ygc.claim_revision import ClaimConflict
from ygc.cloud_account_routes import bearer_token
from ygc.cloud_claim_routes import unique_object
from ygc.cloud_guitars import GuitarMissing, positive_id
from ygc.db.postgres_operations import ServiceRestricted


def ownership_router(verifier, service):
    router = APIRouter()
    headers = {'Cache-Control': 'private, no-store', 'Vary': 'Authorization',
               'X-Content-Type-Options': 'nosniff'}

    async def handle(request, method, individual=None, claim=None):
        try:
            identity = await run_in_threadpool(verifier.verify, bearer_token=bearer_token(request))
        except HTTPException as exc:
            exc.headers = {**(exc.headers or {}), **headers}
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
            args = [account['app_user_id']]
            if individual is not None:
                args.append(positive_id(individual))
            if claim is not None:
                args.append(positive_id(claim))
            kwargs = {}
            if request.method == 'GET':
                query = request.query_params
                allowed = {'q', 'offset', 'limit'} if method == 'search_users' else ({'after', 'limit'} if method in ('view', 'inbox') else set())
                if set(query) - allowed or any(len(query.getlist(key)) != 1 for key in query):
                    raise ValueError()
                if method == 'search_users':
                    offset = query.get('offset', '0')
                    if not offset.isascii() or not offset.isdecimal() or len(offset) > 3 or int(offset) > 200:
                        raise ValueError()
                    kwargs = {'q': query.get('q', ''), 'offset': int(offset),
                              'limit': positive_id(query['limit']) if 'limit' in query else 20}
                    if kwargs['limit'] > 20 or len(kwargs['q']) > 120 or any(ord(char) < 32 for char in kwargs['q']):
                        raise ValueError()
                elif method in ('view', 'inbox'):
                    kwargs = {'after': positive_id(query['after']) if 'after' in query else 0,
                              'limit': positive_id(query['limit']) if 'limit' in query else 25}
                    if kwargs['limit'] > 50:
                        raise ValueError()
            else:
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
                    if len(raw) > 32 * 1024:
                        raise HTTPException(413, 'Ownership request too large.', headers=headers)
                data = json.loads(raw, object_pairs_hook=unique_object)
                if not isinstance(data, dict):
                    raise ValueError()
                args.append(data)
            result = await run_in_threadpool(getattr(service, method), *args, **kwargs)
            return JSONResponse(result, headers=headers)
        except HTTPException as exc:
            exc.headers = {**(exc.headers or {}), **headers}
            raise
        except GuitarMissing:
            raise HTTPException(404, 'Ownership record not found.', headers=headers) from None
        except ClaimConflict:
            raise HTTPException(409, 'Ownership changed or maintenance is running. Reload before retrying.', headers=headers) from None
        except ServiceRestricted:
            raise HTTPException(403, {'code': 'service_restricted'}, headers=headers) from None
        except PermissionError:
            raise HTTPException(403, 'Verified active participant and service access required.', headers=headers) from None
        except (ValueError, TypeError, UnicodeError, ZoneInfoNotFoundError):
            raise HTTPException(400, 'Invalid ownership request or pending account projection.', headers=headers) from None
        except Exception:
            raise HTTPException(503, 'Ownership result unavailable. Refresh before retrying.', headers=headers) from None
        finally:
            if zone_token is not None:
                viewer_timezone.reset(zone_token)

    @router.get('/api/auth/ownership-transfers')
    async def inbox(request: Request):
        return await handle(request, 'inbox')

    @router.get('/api/auth/guitars/{individual}/ownership')
    async def view(request: Request, individual: str):
        return await handle(request, 'view', individual)

    @router.get('/api/auth/guitars/{individual}/transfer-users')
    async def users(request: Request, individual: str):
        return await handle(request, 'search_users', individual)

    @router.post('/api/auth/guitars/{individual}/transfers')
    async def create(request: Request, individual: str):
        return await handle(request, 'create', individual)

    @router.get('/api/auth/transfers/{claim}')
    async def detail(request: Request, claim: str):
        return await handle(request, 'detail', claim=claim)

    @router.post('/api/auth/transfers/{claim}/resolve')
    async def resolve(request: Request, claim: str):
        return await handle(request, 'resolve', claim=claim)

    @router.post('/api/auth/guitars/{individual}/release')
    async def release(request: Request, individual: str):
        return await handle(request, 'release', individual)

    return router
