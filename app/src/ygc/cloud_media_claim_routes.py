"""Verified, private multipart Media/Event creation and Claim-bound photo delivery."""
import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from anyio import CancelScope
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from ygc.claim_dates import viewer_timezone
from ygc.claim_revision import ClaimConflict
from ygc.cloud_account_routes import bearer_token
from ygc.cloud_avatar import MAX_UPLOAD, ImageUploadInvalid
from ygc.cloud_claim_media import MAX_IMAGES, MAX_TOTAL_UPLOAD
from ygc.cloud_claim_routes import unique_object
from ygc.cloud_claims import payload, expected_revision
from ygc.cloud_guitars import GuitarMissing, positive_id
from ygc.db.postgres_operations import ServiceRestricted


class UploadTooLarge(MultiPartException):
    pass


class MediaParser(MultiPartParser):
    """Bound file bytes and headers before spooling; reject truncated forms."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.complete = False
        self.file_bytes = 0

    def on_part_begin(self):
        super().on_part_begin()
        self.part_bytes = self.header_bytes = 0

    def on_part_data(self, data, start, end):
        if self._current_part.file is not None:
            self.part_bytes += end - start
            self.file_bytes += end - start
            if self.part_bytes > MAX_UPLOAD or self.file_bytes > MAX_TOTAL_UPLOAD:
                raise UploadTooLarge('Image upload too large.')
        super().on_part_data(data, start, end)

    def _header_limit(self, size):
        self.header_bytes += size
        if self.header_bytes > 8192:
            raise MultiPartException('Invalid image headers.')

    def on_header_field(self, data, start, end):
        self._header_limit(end - start)
        super().on_header_field(data, start, end)

    def on_header_value(self, data, start, end):
        self._header_limit(end - start)
        super().on_header_value(data, start, end)

    def on_end(self):
        self.complete = True
        super().on_end()

    def close_files(self):
        # A truncated final part need not appear in the returned FormData.
        # Close every spool, including unfinished parts and cancelled uploads.
        for file in self._files_to_close_on_error:
            file.close()


def media_claim_router(verifier, service):
    router = APIRouter()
    headers = {'Cache-Control': 'private, no-store', 'Vary': 'Authorization',
               'X-Content-Type-Options': 'nosniff', 'Cross-Origin-Resource-Policy': 'same-origin'}

    async def handle(request, individual, claim=None, media=None, *, kind='media'):
        try:
            identity = await run_in_threadpool(verifier.verify, bearer_token=bearer_token(request))
        except HTTPException as error:
            error.headers = {**(error.headers or {}), **headers}
            raise
        except PermissionError:
            raise HTTPException(401, 'Identity verification failed.', headers=headers) from None
        except Exception:
            raise HTTPException(503, 'Identity verification unavailable.', headers=headers) from None
        zone_token, form, parser = None, None, None
        try:
            if identity.email_verified is not True:
                raise PermissionError()
            account = await run_in_threadpool(verifier.accounts.resolve_identity,
                issuer=identity.issuer, subject=identity.subject, tenant=identity.tenant)
            if request.headers.get('content-encoding') or len(request.headers.getlist('authorization')) != 1:
                raise ValueError()
            individual, who = positive_id(individual), account['app_user_id']
            if request.method == 'GET':
                if service.storage is None:
                    raise HTTPException(503, 'Image storage unavailable.', headers=headers)
                query = request.query_params
                if set(query) != {'revision'} or len(query.getlist('revision')) != 1:
                    raise ValueError()
                revision = expected_revision({'revision': query['revision']})
                image = await run_in_threadpool(service.image, who, individual,
                    positive_id(claim), positive_id(media), revision)
                return Response(image, media_type='image/jpeg', headers=headers)
            origin = request.headers.get('origin')
            if (request.headers.get('sec-fetch-site') == 'cross-site'
                    or (origin and origin != str(request.base_url).rstrip('/'))):
                raise PermissionError()
            content_type = request.headers.get('content-type', '')
            if (request.query_params or len(request.headers.getlist('content-type')) != 1
                    or len(content_type) > 1024
                    or content_type.split(';')[0].strip().lower() != 'multipart/form-data'):
                raise ValueError()
            zone = request.headers.get('x-ygc-timezone', 'UTC')
            if len(zone) > 100:
                raise ValueError()
            zone_token = viewer_timezone.set(ZoneInfo(zone))

            async def bounded_stream():
                size = 0
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_TOTAL_UPLOAD + 64 * 1024:
                        raise UploadTooLarge('Image request too large.')
                    yield chunk

            parser = MediaParser(request.headers, bounded_stream(), max_files=MAX_IMAGES,
                                 max_fields=1, max_part_size=(32 if kind == 'event' else 16) * 1024)
            form = await parser.parse()
            fields = {'metadata', 'images'} if 'images' in form or kind == 'media' else {'metadata'}
            if (not parser.complete or set(form) != fields
                    or len(form.getlist('metadata')) != 1 or not isinstance(form['metadata'], str)):
                raise ValueError()
            uploads = form.getlist('images')
            if not (0 if kind == 'event' else 1) <= len(uploads) <= MAX_IMAGES or any(not isinstance(item, UploadFile) for item in uploads):
                raise ValueError()
            data = payload(json.loads(form['metadata'], object_pairs_hook=unique_object), media_upload=True)
            if data['claim_type'] != kind:
                raise ValueError()
            if (uploads or kind == 'media') and service.storage is None:
                raise HTTPException(503, 'Image storage unavailable.', headers=headers)
            # Read/normalize files serially in the worker. The parser spools
            # larger inputs; it never loads all raw photos into RAM together.
            images = ((item.file.read(MAX_UPLOAD + 1), item.content_type) for item in uploads)
            create = service.create_event if kind == 'event' else service.create_media
            result = await run_in_threadpool(create, who, individual, data, images)
            return JSONResponse(result, headers=headers)
        except HTTPException:
            raise
        except GuitarMissing:
            raise HTTPException(404, 'Claim, photo or guitar not found.', headers=headers) from None
        except ClaimConflict:
            raise HTTPException(409, 'Claim changed or maintenance is running. Reload before retrying.', headers=headers) from None
        except ServiceRestricted:
            raise HTTPException(403, {'code': 'service_restricted'}, headers=headers) from None
        except PermissionError:
            raise HTTPException(403, 'Verified active account and service access required.', headers=headers) from None
        except UploadTooLarge:
            raise HTTPException(413, {'code': 'image_size_limit'}, headers=headers) from None
        except ImageUploadInvalid as error:
            raise HTTPException(400, {'code': error.code}, headers=headers) from None
        except (ValueError, TypeError, UnicodeError, ZoneInfoNotFoundError, MultiPartException):
            raise HTTPException(400, 'Invalid photo Claim, image or pending account projection.', headers=headers) from None
        except Exception:
            raise HTTPException(503, 'Claim result unavailable. Check saved Claims before retrying.', headers=headers) from None
        finally:
            try:
                # Disconnected/cancelled requests must still close disk-backed
                # and unfinished spools. FormData.close alone can be cancelled
                # before its worker runs and omits an unfinished final part.
                with CancelScope(shield=True):
                    if parser is not None:
                        await run_in_threadpool(parser.close_files)
            finally:
                if zone_token is not None:
                    viewer_timezone.reset(zone_token)

    @router.post('/api/auth/guitars/{individual}/media-claims')
    async def create(request: Request, individual: str):
        return await handle(request, individual)

    @router.post('/api/auth/guitars/{individual}/event-claims')
    async def event(request: Request, individual: str):
        return await handle(request, individual, kind='event')

    @router.get('/api/auth/guitars/{individual}/claims/{claim}/media/{media}')
    async def image(request: Request, individual: str, claim: str, media: str):
        return await handle(request, individual, claim, media)

    return router
