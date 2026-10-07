"""Strict private HTTP boundary for participant and administrator disputes.

Authentication is server resolved on every read, download and mutation. Uploads
are bounded before spooling; neither cookies nor caller-selected users confer
authority. The service independently checks current canonical access and CAS.
"""
import json

from anyio import CancelScope
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from ygc.claim_revision import ClaimConflict
from ygc.cloud_backup_preflight import BackupCapacityError
from ygc.cloud_account_routes import bearer_token
from ygc.cloud_claim_routes import unique_object
from ygc.cloud_disputes import request_projection, result_projection
from ygc.cloud_guitars import GuitarMissing, positive_id
from ygc.db.postgres_operations import ServiceRestricted
from ygc.disputes import MAX_BYTES

MAX_DATA = 64 * 1024


def identifier(value):
    if not isinstance(value, str) or len(value) > 19:
        raise ValueError()
    result = positive_id(value)
    if str(result) != value:
        raise ValueError()
    return result


class UploadTooLarge(MultiPartException):
    pass


class DisputeParser(MultiPartParser):
    """Single private attachment, with bounded headers and incomplete cleanup."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.complete = False

    def on_part_begin(self):
        super().on_part_begin()
        self.part_bytes = self.header_bytes = 0

    def on_part_data(self, data, start, end):
        if self._current_part.file is not None:
            self.part_bytes += end - start
            if self.part_bytes > MAX_BYTES:
                raise UploadTooLarge('Attachment too large.')
        super().on_part_data(data, start, end)

    def _header_limit(self, size):
        self.header_bytes += size
        if self.header_bytes > 8192:
            raise MultiPartException('Invalid attachment headers.')

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
        for file in self._files_to_close_on_error:
            file.close()


def dispute_router(verifier, service):
    router = APIRouter()
    headers = {'Cache-Control': 'private, no-store', 'Vary': 'Authorization',
               'X-Content-Type-Options': 'nosniff', 'Cross-Origin-Resource-Policy': 'same-origin'}

    async def handle(request, method, target=None, *, admin=False):
        parser = None
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
            if target is not None:
                args.append(identifier(target))
            if method in ('list', 'detail', 'attachment'):
                kwargs['admin'] = admin
            if request.method == 'GET':
                query = request.query_params
                allowed = {'after', 'limit', 'status'} if method == 'list' else {'after', 'limit'} if method == 'options' else set()
                if set(query) - allowed or any(len(query.getlist(key)) != 1 or len(query[key]) > 19 for key in query):
                    raise ValueError()
                if method in ('list', 'options'):
                    kwargs.update(after=identifier(query['after']) if 'after' in query else 0,
                                  limit=identifier(query['limit']) if 'limit' in query else 25)
                    if kwargs['limit'] > 50:
                        raise ValueError()
                if method == 'list':
                    kwargs['status'] = query.get('status', 'open')
                    if kwargs['status'] not in ('open', 'resolved', 'all'):
                        raise ValueError()
                async for chunk in request.stream():
                    if chunk:
                        raise ValueError()
            else:
                origin = request.headers.get('origin')
                if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and origin != str(request.base_url).rstrip('/')):
                    raise PermissionError()
                content_type = request.headers.get('content-type', '')
                if request.query_params or len(request.headers.getlist('content-type')) != 1 or len(content_type) > 1024:
                    raise ValueError()
                if method == 'submit':
                    if content_type.split(';')[0].strip().lower() != 'multipart/form-data':
                        raise ValueError()

                    async def bounded_stream():
                        size = 0
                        async for chunk in request.stream():
                            size += len(chunk)
                            if size > MAX_BYTES + MAX_DATA + 16384:
                                raise UploadTooLarge('Dispute request too large.')
                            yield chunk

                    parser = DisputeParser(request.headers, bounded_stream(), max_files=1,
                                           max_fields=1, max_part_size=MAX_DATA)
                    form = await parser.parse()
                    if (not parser.complete or set(form) not in ({'data'}, {'data', 'attachment'})
                            or len(form.getlist('data')) != 1 or not isinstance(form['data'], str)):
                        raise ValueError()
                    data = json.loads(form['data'], object_pairs_hook=unique_object)
                    if not isinstance(data, dict):
                        raise ValueError()
                    uploads = form.getlist('attachment')
                    if len(uploads) > 1 or any(not isinstance(item, UploadFile) for item in uploads):
                        raise ValueError()
                    if uploads:
                        kwargs['content'] = await run_in_threadpool(uploads[0].file.read, MAX_BYTES + 1)
                        kwargs['filename'] = uploads[0].filename or ''
                    request_projection(method, data)
                    args.append(data)
                else:
                    if content_type.split(';')[0].strip().lower() != 'application/json':
                        raise ValueError()
                    raw = bytearray()
                    async for chunk in request.stream():
                        raw.extend(chunk)
                        if len(raw) > MAX_DATA:
                            raise HTTPException(413, 'Dispute request too large.', headers=headers)
                    data = json.loads(raw, object_pairs_hook=unique_object)
                    if not isinstance(data, dict):
                        raise ValueError()
                    request_projection(method, data)
                    args.append(data)
            result = await run_in_threadpool(getattr(service, method), *args, **kwargs)
            if method == 'attachment':
                if (not isinstance(result, dict) or not isinstance(result.get('content'), bytes)
                        or not 0 < len(result['content']) <= MAX_BYTES
                        or (result.get('content_type'), result.get('filename')) not in
                        (('image/jpeg', 'photo.jpg'), ('application/pdf', 'document.pdf'))):
                    raise RuntimeError('Invalid private attachment.')
                return Response(result['content'], media_type=result['content_type'], headers={**headers,
                    'Content-Disposition': 'attachment; filename="' + result['filename'] + '"',
                    'Content-Security-Policy': "sandbox; default-src 'none'"})
            return JSONResponse(result_projection(method, result), headers=headers)
        except HTTPException as exc:
            exc.headers = {**(exc.headers or {}), **headers}
            raise
        except GuitarMissing:
            raise HTTPException(404, 'Dispute, application or attachment not found.', headers=headers) from None
        except BackupCapacityError:
            # This is an operator-owned legacy storage limit, not invalid
            # participant input. Do not expose aggregate private-data sizes.
            raise HTTPException(409, {'code': 'dispute_storage_preflight_required'}, headers=headers) from None
        except ClaimConflict:
            raise HTTPException(409, 'Dispute changed or maintenance is running. Refresh before retrying.', headers=headers) from None
        except ServiceRestricted:
            raise HTTPException(403, {'code': 'service_restricted'}, headers=headers) from None
        except PermissionError:
            raise HTTPException(403, 'Verified active account and current dispute access required.', headers=headers) from None
        except UploadTooLarge:
            raise HTTPException(413, 'Dispute attachment too large.', headers=headers) from None
        except (ValueError, TypeError, UnicodeError, MultiPartException):
            raise HTTPException(400, 'Invalid dispute request or pending account projection.', headers=headers) from None
        except Exception:
            raise HTTPException(503, 'Dispute result unavailable. Refresh before retrying.', headers=headers) from None
        finally:
            with CancelScope(shield=True):
                if parser is not None:
                    await run_in_threadpool(parser.close_files)

    @router.get('/api/auth/ownership-disputes')
    async def listing(request: Request):
        return await handle(request, 'list')

    @router.get('/api/auth/ownership-disputes/options')
    async def options(request: Request):
        return await handle(request, 'options')

    @router.get('/api/auth/ownership-disputes/options/{claim}')
    async def option(request: Request, claim: str):
        return await handle(request, 'option', claim)

    @router.post('/api/auth/ownership-disputes/options/{claim}/acknowledge')
    async def acknowledge(request: Request, claim: str):
        return await handle(request, 'acknowledge', claim)

    @router.post('/api/auth/ownership-disputes/options/{claim}/evidence')
    async def submit(request: Request, claim: str):
        return await handle(request, 'submit', claim)

    @router.get('/api/auth/ownership-disputes/evidence/{evidence}/attachment')
    async def attachment(request: Request, evidence: str):
        return await handle(request, 'attachment', evidence)

    @router.get('/api/auth/ownership-disputes/{case}')
    async def detail(request: Request, case: str):
        return await handle(request, 'detail', case)

    @router.get('/api/auth/admin/ownership-disputes')
    async def admin_listing(request: Request):
        return await handle(request, 'list', admin=True)

    @router.get('/api/auth/admin/ownership-disputes/evidence/{evidence}/attachment')
    async def admin_attachment(request: Request, evidence: str):
        return await handle(request, 'attachment', evidence, admin=True)

    @router.post('/api/auth/admin/ownership-disputes/evidence/{evidence}/publish')
    async def publish(request: Request, evidence: str):
        return await handle(request, 'publish', evidence, admin=True)

    @router.get('/api/auth/admin/ownership-disputes/{case}')
    async def admin_detail(request: Request, case: str):
        return await handle(request, 'detail', case, admin=True)

    @router.post('/api/auth/admin/ownership-disputes/{case}/decision')
    async def decision(request: Request, case: str):
        return await handle(request, 'decide', case, admin=True)

    return router
