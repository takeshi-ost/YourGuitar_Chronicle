"""Authenticated member directory and Follow routes. No Guest data or public profile fields."""
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from ygc.cloud_avatar import AvatarMissing
from ygc.cloud_storage import MAX_BYTES
from starlette.concurrency import run_in_threadpool

from ygc.cloud_account_routes import bearer_token
from ygc.cloud_claim_routes import unique_object
from ygc.cloud_follows import result_projection, FollowConflict, FollowTargetMissing
from ygc.cloud_guitars import positive_id
from ygc.db.postgres_operations import ServiceRestricted

MAX_BODY = 1024


def identifier(value):
    if not isinstance(value, str) or len(value) > 19 or value.startswith('0'):
        raise ValueError('Invalid identifier.')
    return positive_id(value)


def follow_router(verifier, service):
    router = APIRouter()
    headers = {'Cache-Control': 'private, no-store', 'Vary': 'Authorization',
               'X-Content-Type-Options': 'nosniff', 'Cross-Origin-Resource-Policy': 'same-origin'}

    async def handle(request, method, individual=None, direction=None):
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
            if 'content-encoding' in request.headers or len(request.scope.get('query_string', b'')) > 2048:
                raise ValueError()
            args, kwargs = [account['app_user_id']], {}
            if individual is not None:
                args.append(identifier(individual))
            if request.method == 'GET':
                query = request.query_params
                allowed = {'q', 'after', 'limit'} if method == 'search' else {'after', 'limit'} if method == 'connections' else set()
                if set(query) - allowed or any(len(query.getlist(key)) != 1 for key in query):
                    raise ValueError()
                if method in ('search', 'connections'):
                    kwargs = {'after': identifier(query['after']) if 'after' in query else 0,
                              'limit': identifier(query['limit']) if 'limit' in query else 25}
                    if kwargs['limit'] > 50:
                        raise ValueError()
                if method == 'search':
                    kwargs['q'] = query.get('q', '')
                    if len(kwargs['q']) > 120 or any(ord(c) < 32 or ord(c) == 127 for c in kwargs['q']):
                        raise ValueError()
                if method == 'connections':
                    if direction not in ('followers', 'following'):
                        raise ValueError()
                    kwargs['direction'] = direction
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
                        raise HTTPException(413, 'Follow request too large.', headers=headers)
                raw = bytearray()
                async for chunk in request.stream():
                    raw.extend(chunk)
                    if len(raw) > MAX_BODY:
                        raise HTTPException(413, 'Follow request too large.', headers=headers)
                if length is not None and int(length) != len(raw):
                    raise ValueError()
                data = json.loads(raw, object_pairs_hook=unique_object)
                if not isinstance(data, dict) or set(data) != {'following'} or type(data['following']) is not bool:
                    raise ValueError()
                kwargs = {'following': data['following']}
            result = await run_in_threadpool(getattr(service, method), *args, **kwargs)
            if method == 'avatar':
                if not isinstance(result, bytes) or not 0 < len(result) <= MAX_BYTES:
                    raise RuntimeError('Invalid avatar response.')
                return Response(result, media_type='image/jpeg', headers=headers)
            return JSONResponse(result_projection(method, result), headers=headers)
        except HTTPException as exc:
            exc.headers = {**(exc.headers or {}), **headers}
            raise
        except (FollowTargetMissing, AvatarMissing):
            raise HTTPException(404, 'Member not found.', headers=headers) from None
        except FollowConflict:
            raise HTTPException(409, 'Follow state changed or maintenance is running. Reload before retrying.', headers=headers) from None
        except ServiceRestricted:
            raise HTTPException(403, {'code': 'service_restricted'}, headers=headers) from None
        except PermissionError:
            raise HTTPException(403, 'Verified active account and service access required.', headers=headers) from None
        except (ValueError, TypeError, UnicodeError):
            raise HTTPException(400, 'Invalid member request.', headers=headers) from None
        except Exception:
            raise HTTPException(503, 'Members unavailable. Refresh before retrying.', headers=headers) from None

    @router.get('/api/auth/members')
    async def search(request: Request):
        return await handle(request, 'search')

    @router.get('/api/auth/members/{individual}')
    async def profile(request: Request, individual: str):
        return await handle(request, 'profile', individual)

    @router.get('/api/auth/members/{individual}/connections/{direction}')
    async def connections(request: Request, individual: str, direction: str):
        return await handle(request, 'connections', individual, direction)

    @router.put('/api/auth/members/{individual}/following')
    async def update(request: Request, individual: str):
        return await handle(request, 'set_following', individual)

    @router.get('/api/auth/members/{individual}/avatar')
    async def avatar(request: Request, individual: str):
        return await handle(request, 'avatar', individual)

    return router
