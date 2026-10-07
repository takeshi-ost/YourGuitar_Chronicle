"""Verified normal-user Owner responses, separate from Admin moderation."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from ygc.cloud_account_routes import bearer_token
from ygc.cloud_guitars import positive_id
from ygc.claim_revision import ClaimConflict
from ygc.db.postgres_operations import ServiceRestricted


def owner_router(verifier, service):
    router = APIRouter()
    headers = {'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'}

    async def handle(request, individual, claim=None):
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
            if request.query_params or request.headers.get('content-encoding'):
                raise ValueError()
            individual = positive_id(individual)
            if claim is None:
                result = await run_in_threadpool(service.pending, account['app_user_id'], individual)
            else:
                if request.headers.get('content-type', '').split(';')[0] != 'application/json':
                    raise ValueError()
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    # A 4,000-character reason may use JSON surrogate escapes.
                    if len(body) > 64 * 1024:
                        raise ValueError()
                import json
                result = await run_in_threadpool(service.respond, account['app_user_id'], individual,
                    positive_id(claim), json.loads(body))
            return JSONResponse(result, headers=headers)
        except ClaimConflict:
            raise HTTPException(409, 'Claim changed or maintenance is running.', headers=headers) from None
        except ServiceRestricted:
            raise HTTPException(403, {'code': 'service_restricted'}, headers=headers) from None
        except PermissionError:
            raise HTTPException(403, 'Active owner and service access required.', headers=headers) from None
        except (ValueError, TypeError, UnicodeError):
            raise HTTPException(400, 'Invalid or unauthorized Owner response.', headers=headers) from None
        except Exception:
            raise HTTPException(503, 'Owner response unavailable. Refresh before retrying.', headers=headers) from None

    @router.get('/api/auth/guitars/{individual}/owner-responses')
    async def pending(request: Request, individual: str):
        return await handle(request, individual)

    @router.post('/api/auth/guitars/{individual}/owner-responses/{claim}')
    async def respond(request: Request, individual: str, claim: str):
        return await handle(request, individual, claim)

    return router
