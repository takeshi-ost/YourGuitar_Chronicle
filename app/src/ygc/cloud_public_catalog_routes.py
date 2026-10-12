"""Anonymous or authenticated reads with identical public-only projections."""
import hashlib

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from ygc.cloud_account_routes import bearer_token
from ygc.cloud_guitars import GuitarMissing, positive_id
from ygc.cloud_public_catalog import (CLAIM_TYPES, STATES, SPEC_FIELDS, parameters,
                                      guitar_projection, claim_projection)
from ygc.db.postgres_operations import ServiceRestricted
from ygc.cloud_public_presentation import person_projection, reverb_image_url


def public_catalog_router(verifier, service):
    router = APIRouter(prefix='/api/public/guitars')
    headers = {'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff', 'Vary': 'Authorization'}

    def revalidated(request, data):
        # Only the completed PUBLIC DTO is cacheable. Actor/service/visibility
        # checks run on every read, before evaluating any conditional header.
        response = JSONResponse(data, headers={**headers,
            'Cache-Control': 'private, no-cache, max-age=0, must-revalidate'})
        tag = '"' + hashlib.sha256(response.body).hexdigest() + '"'
        response.headers['ETag'] = tag
        condition = request.headers.get('if-none-match', '')
        if len(condition) <= 8192 and any(value.strip().removeprefix('W/') in (tag, '*') for value in condition.split(',')):
            return Response(status_code=304, headers={key: value for key, value in response.headers.items() if key not in ('content-length', 'content-type')})
        return response

    async def actor(request):
        if 'authorization' not in request.headers:
            return None
        # A presented invalid token must never silently downgrade to Guest.
        try:
            identity = await run_in_threadpool(verifier.verify, bearer_token=bearer_token(request))
        except HTTPException:
            raise
        except PermissionError:
            raise HTTPException(401, 'Identity verification failed.', headers=headers) from None
        except Exception:
            raise HTTPException(503, 'Identity verification unavailable.', headers=headers) from None
        try:
            account = await run_in_threadpool(verifier.accounts.resolve_identity,
                issuer=identity.issuer, subject=identity.subject, tenant=identity.tenant)
            # An unverified account can still browse the ordinary public view.
            # It cannot use its Admin role to enter the Admin-only mode.
            if account['role'] == 'admin' and identity.email_verified is not True:
                raise PermissionError()
            return account['app_user_id']
        except PermissionError:
            raise HTTPException(403, 'Account access unavailable.', headers=headers) from None
        except Exception:
            raise HTTPException(503, 'Account status unavailable.', headers=headers) from None

    async def execute(request, individual_id=None, chronicle=False):
        who = await actor(request)
        try:
            if individual_id is None:
                q, sort, page, limit = parameters(request.query_params)
                data = await run_in_threadpool(service.list, who, q=q, sort=sort, page=page, limit=limit)
                result = {'items': [guitar_projection(row) for row in data['items']], 'total': str(data['total']),
                          'page': data['page'], 'page_size': data['page_size'], 'total_pages': data['total_pages']}
            elif chronicle:
                query = request.query_params
                if set(query)-{'after', 'limit'} or any(len(query.getlist(key)) != 1 for key in query):
                    raise ValueError()
                after = positive_id(query['after']) if 'after' in query else 0
                limit = positive_id(query['limit']) if 'limit' in query else 25
                if limit > 50:
                    raise ValueError()
                data = await run_in_threadpool(service.chronicle, who, positive_id(individual_id), after=after, limit=limit)
                result = {'items': [claim_projection(row) for row in data['items']
                                    if row.get('claim_type') in CLAIM_TYPES and row.get('verification_status') in STATES],
                          'next_after': str(data['next_after']) if data['next_after'] is not None else None}
            else:
                if request.query_params:
                    raise ValueError()
                data = await run_in_threadpool(service.detail, who, positive_id(individual_id))
                result = guitar_projection(data)
                result['public_photo'] = '/api/public/guitars/'+str(positive_id(individual_id))+'/photo' if data.get('public_photo') == '/api/public/guitars/'+str(positive_id(individual_id))+'/photo' else reverb_image_url(data.get('public_photo'))
                presentation = data.get('presentation')
                if isinstance(presentation, dict):
                    result['presentation'] = {'owner': person_projection(presentation.get('owner')),
                        **{key: presentation[key][:400] if isinstance(presentation.get(key), str) else None for key in ('location', 'source_owner_name')}}
                result['specifications'] = [{'field_name': row['field_name'], 'value_text': row['value_text']}
                    for row in data['specifications'] if row['field_name'] in SPEC_FIELDS]
            return revalidated(request, result)
        except GuitarMissing:
            raise HTTPException(404, 'Guitar not found.', headers=headers) from None
        except (ValueError, TypeError):
            raise HTTPException(400, 'Invalid catalog request.', headers=headers) from None
        except ServiceRestricted:
            raise HTTPException(403, {'code': 'service_restricted', 'message': 'Catalog access is temporarily restricted.'}, headers=headers) from None
        except PermissionError:
            raise HTTPException(403, 'Account access unavailable.', headers=headers) from None
        except Exception:
            raise HTTPException(503, 'Catalog data unavailable.', headers=headers) from None

    @router.get('')
    async def listing(request: Request):
        return await execute(request)

    async def insights(request, method):
        who = await actor(request)
        try:
            if request.query_params:
                raise ValueError()
            data = await run_in_threadpool(getattr(service, method), who)
            # Dedicated DTOs prevent extra service fields from escaping.
            if method == 'discoveries':
                result = {'items': [{**guitar_projection(row),
                    **{key: row[key] for key in ('activity_at', 'activity_type', 'claim_type')}} for row in data['items']]}
            elif method == 'statistics':
                result = {'individuals': data['individuals'],
                    **{key: [{field: row[field] for field in ('label', 'count')} for row in data[key]] for key in ('models', 'years')},
                    'listings_30d': [{field: row[field] for field in ('date', 'count')} for row in data['listings_30d']]}
            else:
                result = {'countries': [{field: row[field] for field in ('country', 'count')} for row in data['countries']]}
            return revalidated(request, result)
        except (ValueError, TypeError):
            raise HTTPException(400, 'Invalid catalog request.', headers=headers) from None
        except ServiceRestricted:
            raise HTTPException(403, {'code': 'service_restricted', 'message': 'Catalog access is temporarily restricted.'}, headers=headers) from None
        except PermissionError:
            raise HTTPException(403, 'Account access unavailable.', headers=headers) from None
        except Exception:
            raise HTTPException(503, 'Catalog data unavailable.', headers=headers) from None

    @router.get('/discoveries')
    async def discoveries(request: Request):
        return await insights(request, 'discoveries')

    @router.get('/statistics')
    async def statistics(request: Request):
        return await insights(request, 'statistics')

    @router.get('/world-map')
    async def world_map(request: Request):
        return await insights(request, 'world_map')

    @router.get('/{individual_id}')
    async def detail(request: Request, individual_id: str):
        return await execute(request, individual_id)

    @router.get('/{individual_id}/photo')
    async def photo(request: Request, individual_id: str):
        who = await actor(request)
        try:
            if request.query_params:
                raise ValueError()
            data = await run_in_threadpool(service.photo, who, positive_id(individual_id))
            return Response(data, media_type='image/jpeg', headers=headers)
        except GuitarMissing:
            raise HTTPException(404, 'Image unavailable.', headers=headers) from None
        except ValueError:
            raise HTTPException(400, 'Invalid image request.', headers=headers) from None
        except (ServiceRestricted, PermissionError):
            raise HTTPException(403, 'Image access restricted.', headers=headers) from None
        except Exception:
            raise HTTPException(503, 'Image unavailable.', headers=headers) from None

    @router.get('/{individual_id}/chronicle')
    async def chronicle(request: Request, individual_id: str):
        return await execute(request, individual_id, chronicle=True)

    return router
