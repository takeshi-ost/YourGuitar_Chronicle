"""Revision-scoped participant admission, separate from canonical authorization.

No browser identity, email, role or cached profile can grant admission. A policy
change becomes effective when traffic has moved to the new configured revision;
already running requests are allowed to finish. This is not an account deletion.
"""
import json
import os

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse


def participant_subjects(*, required=False):
    value = os.environ.get('YGC_CLOSED_TEST_PARTICIPANTS')
    if value is None:
        if required:
            raise ValueError('An explicit closed-test participant configuration is required.')
        return None  # Ordinary, unrestricted application deployments.
    try:
        subjects = json.loads(value)
    except (ValueError, TypeError):
        raise ValueError('Invalid closed-test participant configuration.') from None
    if (not isinstance(subjects, list) or not 1 <= len(subjects) <= 200
            or any(not isinstance(s, str) or not 1 <= len(s) <= 128
                   or s != s.strip() or any(ord(c) < 32 for c in s) or s == '*'
                   for s in subjects) or len(set(subjects)) != len(subjects)):
        raise ValueError('Invalid closed-test participant configuration.')
    return frozenset(subjects)


class ParticipantAdmission:
    """Check all presented user credentials at the shared API boundary.

Anonymous public reads remain public. The review worker uses a separate identity
verifier at its exact existing endpoint, not a human participant credential.
Downstream routes still enforce account status, Admin, mode and resource access.
"""
    def __init__(self, app, *, verifier, subjects):
        self.app, self.verifier, self.subjects = app, verifier, subjects

    async def __call__(self, scope, receive, send):
        if (scope['type'] != 'http' or not scope['path'].startswith('/api/')
                or scope['path'] == '/api/review/mcp'):
            return await self.app(scope, receive, send)
        headers = [value for name, value in scope.get('headers', []) if name.lower() == b'authorization']
        if not headers:
            return await self.app(scope, receive, send)
        token = None
        if len(headers) == 1:
            scheme, sep, token = headers[0].decode('latin-1').partition(' ')
            if not sep or scheme.lower() != 'bearer' or not token.strip():
                token = None
        try:
            identity = await run_in_threadpool(self.verifier.verify, bearer_token=token)
        except PermissionError:
            response = JSONResponse({'detail': 'Identity token verification failed.'}, status_code=401,
                headers={'Cache-Control':'private, no-store', 'WWW-Authenticate':'Bearer'})
            return await response(scope, receive, send)
        except Exception:
            response = JSONResponse({'detail': 'Identity verification unavailable.'}, status_code=503,
                headers={'Cache-Control':'private, no-store'})
            return await response(scope, receive, send)
        if identity.subject not in self.subjects:
            response = JSONResponse({'detail': 'This account is not a closed-test participant.',
                'code': 'closed_test_participant_required'}, status_code=403,
                headers={'Cache-Control':'private, no-store'})
            return await response(scope, receive, send)
        # Only this request, this verifier and this exact verified bearer may
        # reuse the SDK result. No token or completed decision is stored globally.
        with self.verifier.verified_request(token, identity):
            await self.app(scope, receive, send)
