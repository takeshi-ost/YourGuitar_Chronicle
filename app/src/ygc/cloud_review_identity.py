"""Google-signed, audience-bound identity for a dedicated review client."""
import re
from urllib.parse import urlsplit
import requests
from google.auth.transport.requests import Request
from google.oauth2.id_token import verify_oauth2_token


def validate_settings(audience,email,subject):
    parsed=urlsplit(audience)
    if parsed.scheme!='https' or not parsed.hostname or not parsed.hostname.endswith('.run.app') or parsed.netloc!=parsed.hostname or parsed.path or parsed.query or parsed.fragment:
        raise ValueError('Explicit Cloud Run service audience required.')
    if not re.fullmatch(r'[a-z][a-z0-9-]{4,28}[a-z0-9]@[a-z][a-z0-9-]{4,61}[a-z0-9]\.iam\.gserviceaccount\.com',email):raise ValueError('Dedicated service account required.')
    if not re.fullmatch(r'[0-9]{10,30}',subject):raise ValueError('Service account numeric identity required.')


class ReviewIdentity:
    def __init__(self,audience,email,subject):
        validate_settings(audience,email,subject)
        self.audience,self.email,self.subject=audience,email,subject
        self.session=requests.Session();self.session.trust_env=False
        request=Request(session=self.session)
        def bounded_request(*args,**kwargs):
            kwargs['timeout']=10
            return request(*args,**kwargs)
        self.request=bounded_request
    def close(self):self.session.close()
    def verify(self,token):
        if not isinstance(token,str) or not 0<len(token)<=16384:raise PermissionError('Review identity required.')
        try:claims=verify_oauth2_token(token,self.request,audience=self.audience)
        except Exception:raise PermissionError('Review identity invalid.') from None
        if (not isinstance(claims,dict) or claims.get('iss') not in ('accounts.google.com','https://accounts.google.com') or claims.get('aud')!=self.audience
            or claims.get('sub')!=self.subject or claims.get('email')!=self.email or claims.get('email_verified') is not True):raise PermissionError('Review identity mismatch.')
        return self.subject
