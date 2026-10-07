"""Strict private favorites routes. User/actor identity is never request input."""
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ygc.claim_revision import ClaimConflict
from ygc.cloud_account_routes import bearer_token
from ygc.cloud_claim_routes import unique_object
from ygc.cloud_favorites import result_projection
from ygc.cloud_guitars import GuitarMissing, positive_id
from ygc.db.postgres_operations import ServiceRestricted

MAX_BODY = 1024


def identifier(value):
    if not isinstance(value, str) or len(value) > 19 or value.startswith('0'):
        raise ValueError('Invalid identifier.')
    return positive_id(value)


def favorite_router(verifier, service):
    router = APIRouter()
    headers = {'Cache-Control': 'private, no-store', 'Vary': 'Authorization',
               'X-Content-Type-Options': 'nosniff'}

    async def handle(request, method, individual=None):
        try:
            token = bearer_token(request)
            if (len(request.headers.getlist('authorization')) != 1 or len(token) > 16384
                    or any(ord(char) < 33 or ord(char) > 126 for char in token)):
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
            raw_headers = request.scope.get('headers', [])
            if len(raw_headers) > 128 or sum(len(key) + len(value) for key, value in raw_headers) > 32768:
                raise ValueError()
            for name in ('content-type', 'content-length', 'content-encoding', 'origin', 'sec-fetch-site'):
                values = request.headers.getlist(name)
                if len(values) > 1 or any(len(value) > 2048 for value in values):
                    raise ValueError()
            if 'content-encoding' in request.headers or len(request.scope.get('query_string', b'')) > 128:
                raise ValueError()
            args, kwargs = [account['app_user_id']], {}
            if individual is not None:
                args.append(identifier(individual))
            if request.method == 'GET':
                query = request.query_params
                allowed = {'after', 'limit'} if method == 'list' else set()
                if set(query) - allowed or any(len(query.getlist(key)) != 1 for key in query):
                    raise ValueError()
                if method == 'list':
                    kwargs = {'after': identifier(query['after']) if 'after' in query else 0,
                              'limit': identifier(query['limit']) if 'limit' in query else 25}
                    if kwargs['limit'] > 50:
                        raise ValueError()
                async for chunk in request.stream():
                    if chunk:
                        raise ValueError()
            else:
                origin = request.headers.get('origin')
                if (request.headers.get('sec-fetch-site') == 'cross-site'
                        or (origin and origin != str(request.base_url).rstrip('/'))):
                    raise PermissionError()
                if (request.query_params or len(request.headers.getlist('content-type')) != 1
                        or request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json'):
                    raise ValueError()
                length = request.headers.get('content-length')
                if length is not None:
                    if not length.isascii() or not length.isdecimal() or len(length) > 10:
                        raise ValueError()
                    if int(length) > MAX_BODY:
                        raise HTTPException(413, 'Favorite request too large.', headers=headers)
                raw = bytearray()
                async for chunk in request.stream():
                    raw.extend(chunk)
                    if len(raw) > MAX_BODY:
                        raise HTTPException(413, 'Favorite request too large.', headers=headers)
                if length is not None and int(length) != len(raw):
                    raise ValueError()
                data = json.loads(raw, object_pairs_hook=unique_object)
                if not isinstance(data, dict) or set(data) != {'favorite'} or type(data['favorite']) is not bool:
                    raise ValueError()
                kwargs = {'favorite': data['favorite']}
            result = await run_in_threadpool(getattr(service, method), *args, **kwargs)
            return JSONResponse(result_projection(method, result), headers=headers)
        except HTTPException as exc:
            exc.headers = {**(exc.headers or {}), **headers}
            raise
        except GuitarMissing:
            raise HTTPException(404, 'Guitar not found.', headers=headers) from None
        except ClaimConflict:
            raise HTTPException(409, 'Favorites changed or maintenance is running. Reload before retrying.', headers=headers) from None
        except ServiceRestricted:
            raise HTTPException(403, {'code': 'service_restricted'}, headers=headers) from None
        except PermissionError:
            raise HTTPException(403, 'Verified active account and service access required.', headers=headers) from None
        except (ValueError, TypeError, UnicodeError):
            raise HTTPException(400, 'Invalid favorite request or pending account projection.', headers=headers) from None
        except Exception:
            raise HTTPException(503, 'Favorites unavailable. Refresh before retrying.', headers=headers) from None

    @router.get('/api/auth/favorites')
    async def listing(request: Request):
        return await handle(request, 'list')

    @router.get('/api/auth/favorites/{individual}')
    async def detail(request: Request, individual: str):
        return await handle(request, 'detail', individual)

    @router.put('/api/auth/favorites/{individual}')
    async def update(request: Request, individual: str):
        return await handle(request, 'set', individual)

    return router
