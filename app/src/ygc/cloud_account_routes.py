"""Mountable cloud enrollment API; no SQLite or local test-user selection."""
from copy import deepcopy

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ygc.db.postgres_accounts import AccountNotRegistered
from ygc.registration_fields import validate_registration


def bearer_token(request):
    header = request.headers.get('Authorization', '')
    scheme, separator, value = header.partition(' ')
    if not separator or scheme.lower() != 'bearer' or not value.strip():
        raise HTTPException(401, 'An Identity Platform ID token is required.',
                            headers={'WWW-Authenticate': 'Bearer', 'Cache-Control': 'no-store'})
    return value


def account_response(identity, account):
    # A deliberate whitelist: never return canonical DB rows or credentials.
    return {'user': {key: account[key] for key in
                    ('id', 'app_user_id', 'display_name', 'account_type', 'role')},
            'identity': {'provider': 'identity-platform', 'email_verified': identity.email_verified}}


def account_router(verifier, documents):
    documents = deepcopy(documents)
    if set(documents) != {'terms', 'privacy'} or any(
            not isinstance(doc.get('version'), str) or not doc['version']
            or not isinstance(doc.get('title'), str) or not doc['title']
            or not isinstance(doc.get('paragraphs'), list) or not doc['paragraphs']
            or any(not isinstance(value, str) or not value for value in doc['paragraphs'])
            for doc in documents.values()):
        raise ValueError('Versioned Terms and Privacy documents are required.')
    versions = {kind: doc['version'] for kind, doc in documents.items()}
    router = APIRouter(prefix='/api/auth')

    def response(body):
        return JSONResponse(body, headers={'Cache-Control': 'private, no-store'})

    @router.get('/registration')
    def registration_documents():
        return response({'backend': 'identity_platform', 'documents': documents})

    @router.post('/register')
    async def register(request: Request):
        bearer = bearer_token(request)
        try:
            fields = validate_registration(await request.json(), versions)
        except ValueError as exc:
            raise HTTPException(400, str(exc), headers={'Cache-Control': 'no-store'}) from None
        try:
            identity = await run_in_threadpool(verifier.verify, bearer_token=bearer)
        except PermissionError:
            raise HTTPException(401, 'Identity token verification failed.',
                                headers={'WWW-Authenticate': 'Bearer', 'Cache-Control': 'no-store'}) from None
        try:
            account = await run_in_threadpool(verifier.accounts.ensure_identity,
                issuer=identity.issuer, subject=identity.subject, tenant=identity.tenant, **fields)
        except PermissionError:
            raise HTTPException(403, 'Account is not available.', headers={'Cache-Control': 'no-store'}) from None
        return response(account_response(identity, account))

    @router.get('/me')
    async def me(request: Request):
        bearer = bearer_token(request)
        try:
            identity = await run_in_threadpool(verifier.verify, bearer_token=bearer)
        except PermissionError:
            raise HTTPException(401, 'Identity token verification failed.',
                                headers={'WWW-Authenticate': 'Bearer', 'Cache-Control': 'no-store'}) from None
        try:
            account = await run_in_threadpool(verifier.accounts.resolve_identity,
                issuer=identity.issuer, subject=identity.subject, tenant=identity.tenant)
        except AccountNotRegistered:
            return JSONResponse({'detail': 'Complete application registration.', 'code': 'registration_required'},
                                status_code=409, headers={'Cache-Control': 'private, no-store'})
        except PermissionError:
            raise HTTPException(403, 'Account is not available.', headers={'Cache-Control': 'no-store'}) from None
        return response(account_response(identity, account))

    return router
