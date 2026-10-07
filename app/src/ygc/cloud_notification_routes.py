"""Strict Bearer-authenticated notification history; recipient is never input."""
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ygc.claim_revision import ClaimConflict
from ygc.cloud_account_routes import bearer_token
from ygc.cloud_claim_routes import unique_object
from ygc.cloud_guitars import positive_id
from ygc.cloud_notifications import NotificationMissing, result_projection
from ygc.db.postgres_operations import ServiceRestricted


def notification_router(verifier, service):
    router = APIRouter()
    headers = {'Cache-Control': 'private, no-store', 'Vary': 'Authorization',
               'X-Content-Type-Options': 'nosniff'}

    async def handle(request, method, notification=None):
        try:
            token = bearer_token(request)
            if len(request.headers.getlist('authorization')) != 1 or len(token) > 16384 or token != token.strip():
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
            if request.headers.get('content-encoding'):
                raise ValueError()
            args, kwargs = [account['app_user_id']], {}
            if notification is not None:
                if len(notification) > 19:
                    raise ValueError()
                args.append(positive_id(notification))
            if request.method == 'GET':
                query = request.query_params
                allowed = {'after', 'limit'} if method == 'list' else set()
                if set(query) - allowed or any(len(query.getlist(key)) != 1 or len(query[key]) > 19 for key in query):
                    raise ValueError()
                if method == 'list':
                    kwargs = {'after': positive_id(query['after']) if 'after' in query else 0,
                              'limit': positive_id(query['limit']) if 'limit' in query else 25}
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
                raw = bytearray()
                async for chunk in request.stream():
                    raw.extend(chunk)
                    if len(raw) > 1024:
                        raise HTTPException(413, 'Notification request too large.', headers=headers)
                data = json.loads(raw, object_pairs_hook=unique_object)
                if not isinstance(data, dict) or data:
                    raise ValueError()
            result = await run_in_threadpool(getattr(service, method), *args, **kwargs)
            return JSONResponse(result_projection(method, result), headers=headers)
        except HTTPException as exc:
            exc.headers = {**(exc.headers or {}), **headers}
            raise
        except NotificationMissing:
            raise HTTPException(404, 'Notification not found.', headers=headers) from None
        except ClaimConflict:
            raise HTTPException(409, 'Notifications changed or maintenance is running. Reload before retrying.', headers=headers) from None
        except ServiceRestricted:
            raise HTTPException(403, {'code': 'service_restricted'}, headers=headers) from None
        except PermissionError:
            raise HTTPException(403, 'Verified active account and service access required.', headers=headers) from None
        except (ValueError, TypeError, UnicodeError):
            raise HTTPException(400, 'Invalid notification request or pending account projection.', headers=headers) from None
        except Exception:
            raise HTTPException(503, 'Notifications unavailable. Refresh before retrying.', headers=headers) from None

    @router.get('/api/auth/notifications')
    async def inbox(request: Request):
        return await handle(request, 'list')

    @router.get('/api/auth/notifications/unread-count')
    async def unread(request: Request):
        return await handle(request, 'unread_count')

    @router.post('/api/auth/notifications/read-all')
    async def read_all(request: Request):
        return await handle(request, 'mark_all_read')

    @router.post('/api/auth/notifications/{notification}/read')
    async def read(request: Request, notification: str):
        return await handle(request, 'mark_read', notification)

    return router
