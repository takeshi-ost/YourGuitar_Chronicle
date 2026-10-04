"""Server-side Identity Platform verification and canonical account lookup.

No registration or linking by email happens during token resolution.
"""
import os
import re
import uuid

from ygc.platform_boundaries import ActorContext


class IdentityPlatformIdentity:
    def __init__(self, accounts, *, project_id: str, tenant: str = ''):
        if not isinstance(project_id, str) or not re.fullmatch(r'[a-z][a-z0-9-]{4,61}[a-z0-9]', project_id):
            raise ValueError('An explicit Google Cloud project ID is required.')
        if not isinstance(tenant, str):
            raise ValueError('Tenant must be an explicit string.')
        self._reject_emulator()
        import firebase_admin
        from firebase_admin import auth, tenant_mgt
        self.accounts = accounts
        self.project_id = project_id
        self.tenant = tenant
        self._app = firebase_admin.initialize_app(
            options={'projectId': project_id, 'httpTimeout': 10},
            name='ygc-' + uuid.uuid4().hex,
        )
        self._delete_app = firebase_admin.delete_app
        try:
            self._verify = (tenant_mgt.auth_for_tenant(tenant, app=self._app).verify_id_token
                            if tenant else lambda token, **kwargs: auth.verify_id_token(
                                token, app=self._app, **kwargs))
        except Exception:
            self.close()
            raise

    @staticmethod
    def _reject_emulator():
        if 'FIREBASE_AUTH_EMULATOR_HOST' in os.environ:
            raise ValueError('Production identity verification does not allow the Auth emulator.')

    def close(self):
        if self._app is not None:
            self._delete_app(self._app)
            self._app = None

    def resolve(self, *, bearer_token: str | None,
                prototype_user_id: int | None = None) -> ActorContext:
        self._reject_emulator()
        if self._app is None:
            raise RuntimeError('Identity verifier has been closed.')
        if not isinstance(bearer_token, str) or not bearer_token.strip():
            raise PermissionError('An Identity Platform ID token is required.')
        try:
            claims = self._verify(bearer_token, check_revoked=True)
        except Exception:
            # SDK exceptions may contain credential details. Keep public errors generic.
            raise PermissionError('Identity token verification failed.') from None
        issuer = 'https://securetoken.google.com/' + self.project_id
        firebase = claims.get('firebase') if isinstance(claims, dict) else None
        subject = claims.get('sub') if isinstance(claims, dict) else None
        if (not isinstance(firebase, dict) or firebase.get('tenant', '') != self.tenant
                or claims.get('iss') != issuer or claims.get('aud') != self.project_id
                or not isinstance(subject, str) or not subject or len(subject) > 128):
            raise PermissionError('Identity token does not match the configured project and tenant.')
        account = self.accounts.resolve_identity(issuer=issuer, tenant=self.tenant, subject=subject)
        if prototype_user_id is not None and prototype_user_id != account['id']:
            raise PermissionError('The requested user does not match the signed-in account.')
        return ActorContext(account['id'], 'identity-platform', subject, True,
                            account['app_user_id'], self.tenant)
