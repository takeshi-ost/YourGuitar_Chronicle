"""Provider-neutral sign-in result. Cloud adapters map verified credentials here."""
from dataclasses import dataclass


@dataclass(frozen=True)
class SignInResult:
    user_id: int
    app_user_id: str
    subject: str
    id_token: str
    display_name: str
    expires_in: int = 3600
    provider: str = 'local-dummy'
    refresh_token: str | None = None

    def as_response(self):
        # Identity Platform REST field names; no synthetic refresh capability.
        return {'localId': self.subject, 'idToken': self.id_token,
                'expiresIn': str(self.expires_in), 'refreshToken': self.refresh_token,
                'displayName': self.display_name, 'registered': True,
                'user_id': self.user_id, 'app_user_id': self.app_user_id,
                'provider': self.provider, 'subject': self.subject,
                'token': self.id_token, 'capabilities': {'refresh': bool(self.refresh_token)}}
