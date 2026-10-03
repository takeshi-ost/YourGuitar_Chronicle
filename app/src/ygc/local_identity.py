"""Explicit loopback-only test login; never a verifier for cloud ID tokens."""
import os
import re
import threading
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from ygc import accounts

ACTOR_FIELDS = ('user_id', 'author_user_id', 'responder_user_id', 'viewer_id', 'viewer_user_id')
_sign_in_lock = threading.Lock()


def dummy_sign_in(repository, user_id=None):
    """Reuse a tab's test user, otherwise a stable dedicated dummy principal."""
    with _sign_in_lock:
        if user_id is not None:
            return accounts.login(repository,user_id)
        with repository.connect() as con:
            def available(value):
                return value and con.execute("SELECT 1 FROM account_records WHERE id=? AND disabled=0 AND ban_status<>'ban' AND account_type<>'source'",(value,)).fetchone()
            if not available(user_id):
                row=con.execute("SELECT value FROM account_metadata WHERE key='dummy_sign_in_user_id'").fetchone()
                user_id=int(row['value']) if row else None
                if not available(user_id):user_id=None
        if user_id is None:
            user_id=repository.create_user('Local Sign In User')
            with repository.connect() as con:
                con.execute("INSERT OR REPLACE INTO account_metadata VALUES ('dummy_sign_in_user_id',?)",(str(user_id),))
        return accounts.login(repository,user_id)


def enabled():
    return os.getenv('YGC_IDENTITY_BACKEND', 'prototype') == 'local_dummy'


def install(app, repository, local_request, console_admin):
    @app.get('/api/local-auth/registration')
    def registration_documents():
        from ygc.registration import DOCUMENTS
        return {'documents': DOCUMENTS}

    @app.post('/api/local-auth/register')
    async def register(request: Request):
        if not enabled() or not local_request(request):
            raise HTTPException(403, 'Local dummy registration only.')
        if request.headers.get('origin') and request.headers['origin'] != str(request.base_url).rstrip('/'):
            raise HTTPException(403, 'Origin not allowed.')
        from ygc import registration
        try:
            body = await request.json()
            user_id = await run_in_threadpool(registration.register, repository(), body)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        result = await run_in_threadpool(accounts.login, repository(), user_id)
        return JSONResponse(result, headers={'Cache-Control':'no-store'})

    @app.post('/api/local-auth/sign-in')
    async def sign_in(request: Request):
        if not enabled() or not local_request(request):
            raise HTTPException(403,'Local dummy sign-in only.')
        if request.headers.get('origin') and request.headers['origin'] != str(request.base_url).rstrip('/'):
            raise HTTPException(403,'Origin not allowed.')
        body=await request.json()
        # Only a local test-user hint is consumed; never email/password.
        try:user_id=int(body['user_id']) if body.get('user_id') else None
        except (TypeError,ValueError):user_id=None
        try:
            result=await run_in_threadpool(dummy_sign_in,repository(),user_id)
        except PermissionError as exc:
            raise HTTPException(403,str(exc))
        return JSONResponse(result,headers={'Cache-Control':'no-store'})
    @app.get('/api/local-auth')
    def status():
        return {'backend': 'local_dummy' if enabled() else 'prototype'}

    @app.post('/api/local-auth/login')
    async def login(request: Request):
        if not enabled() or not local_request(request):
            raise HTTPException(403, 'Local dummy login is available only on loopback in explicit local_dummy mode.')
        if request.headers.get('origin') and request.headers['origin'] != str(request.base_url).rstrip('/'):
            raise HTTPException(403, 'Origin not allowed.')
        body = await request.json()
        try:
            result = await run_in_threadpool(accounts.login, repository(), int(body['user_id']))
        except (KeyError, TypeError, ValueError):
            raise HTTPException(400, 'A valid test user ID is required.')
        except PermissionError as exc:
            raise HTTPException(403, str(exc))
        return JSONResponse(result, headers={'Cache-Control':'no-store'})

    @app.post('/api/local-auth/logout')
    async def logout(request: Request):
        if not enabled() or not local_request(request):
            raise HTTPException(403, 'Local dummy login is disabled.')
        bearer = request.headers.get('Authorization', '')
        if bearer.startswith('Bearer '):
            await run_in_threadpool(accounts.logout, repository(), bearer[7:])
        return {'ok': True}

    @app.middleware('http')
    async def authenticate(request: Request, call_next):
        if not enabled() or not request.url.path.startswith('/api/'):
            return await call_next(request)
        path = request.url.path
        if path.startswith('/api/local-auth'):
            return await call_next(request)
        if path == '/api/experiments/direct/mcp':
            return await call_next(request)  # Separate experiment-token boundary.
        if path == '/api/users' and request.method == 'POST':
            if not console_admin(request) or not local_request(request) or (request.headers.get('origin') and request.headers['origin'] != str(request.base_url).rstrip('/')):
                return JSONResponse({'detail':'Local test account creation only.'}, status_code=403)
            return await call_next(request)
        admin = console_admin(request)
        actor = None
        bearer = request.headers.get('Authorization', '')
        if bearer:
            try:
                if not bearer.startswith('Bearer '):
                    raise PermissionError('Invalid authorization header.')
                from ygc.platform_boundaries import LocalDummyIdentity
                principal = await run_in_threadpool(LocalDummyIdentity(repository()).resolve, bearer_token=bearer[7:])
                request.state.actor_context = principal
                actor = {'id':principal.user_id, 'app_user_id':principal.app_user_id}
            except PermissionError as exc:
                return JSONResponse({'detail':str(exc)}, status_code=401)
        request.state.local_actor = actor
        write = request.method not in ('GET','HEAD','OPTIONS')
        operator = path.startswith(('/api/admin/', '/api/crawl', '/api/backfill-', '/api/migrate-', '/api/vintage-audit')) or path in ('/api/import-db','/api/reset-db','/api/export-db') or (write and path == '/api/users') or (request.method == 'DELETE' and re.fullmatch(r'/api/(claims|individuals)/\d+',path))
        if operator and not admin:
            return JSONResponse({'detail':'Local Browser Console administrator access required.'}, status_code=403)
        if write and not admin and not actor:
            return JSONResponse({'detail':'Sign in before modifying service data.'}, status_code=401)
        claims = [request.query_params[key] for key in ACTOR_FIELDS if request.query_params.get(key)]
        own_path = re.match(r'^/api/users/(\d+)(.*)$',path)
        if own_path and (write or own_path[2] in ('','/notifications','/favorites')):
            claims.append(own_path[1])
        if write and not admin:
            content_type = request.headers.get('content-type','')
            if 'application/json' in content_type:
                try:
                    body = await request.json()
                except ValueError:
                    body = {}
                if isinstance(body,dict):
                    claims += [body[key] for key in ACTOR_FIELDS if body.get(key) is not None]
            elif 'multipart/form-data' in content_type:
                # Cache bytes so downstream FastAPI can parse the same upload.
                await request.body()
                form = await request.form()
                claims += [form[key] for key in ACTOR_FIELDS if form.get(key) is not None]
        if not admin:
            try:
                mismatch = any(not actor or int(claim) != actor['id'] for claim in claims)
            except (TypeError,ValueError):
                mismatch = True
            if mismatch:
                return JSONResponse({'detail':'The requested user does not match the signed-in account.'}, status_code=403)
        response = await call_next(request)
        if actor:
            response.headers['Cache-Control'] = 'private, no-store'
        return response
