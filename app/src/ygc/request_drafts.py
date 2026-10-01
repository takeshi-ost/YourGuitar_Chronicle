"""Signed, unsaved form previews. Only Keep/Submit persists an application."""
from ygc.claim_dates import validate_claim_date
import base64
import hashlib
import hmac
import json
import secrets
import time

_KEY = secrets.token_bytes(32)


def preview(kind, user, revision, challenge, expires_at, **fields):
    payload=dict(request_kind=kind,applicant_id=user,revision=revision,challenge=challenge,
                 expires_at=expires_at,**fields)
    raw=base64.urlsafe_b64encode(json.dumps(payload,separators=(',',':')).encode()).decode()
    token=raw+'.'+hmac.new(_KEY,raw.encode(),hashlib.sha256).hexdigest()
    return dict(payload,draft_token=token,status='draft',unsaved=True,images={},events=[],
                report=None,error=None,claim_id=None,unread_result=False)


def decode(token,user):
    try:
        raw,signature=token.rsplit('.',1)
        if not hmac.compare_digest(signature,hmac.new(_KEY,raw.encode(),hashlib.sha256).hexdigest()):
            raise ValueError()
        data=json.loads(base64.urlsafe_b64decode(raw))
        if data['applicant_id']!=user:raise ValueError()
        if data['expires_at']<=time.time():raise ValueError()
        return data
    except (ValueError,KeyError,TypeError):
        raise ValueError('This unsaved form has expired or is no longer valid. Reopen the request to generate a new challenge.') from None


def keep(repo,user,token):
    from ygc import acquire_review,listing_review
    data=decode(token,user)
    with repo.connect() as con:
        existing=con.execute('SELECT status FROM acquire_applications WHERE revision=?',(data['revision'],)).fetchone()
        if existing:
            if existing['status']!='draft':raise ValueError('This request has already been submitted or closed.')
            return acquire_review.detail(con,data['revision'],user)
    if data['request_kind']=='listing':
        row=listing_review.start(repo,user,data['listing_payload'],draft=data)
    else:
        row=acquire_review.start(repo,user,data['original_individual_id'],draft=data)
    if row.get('revision')!=data['revision']:
        raise ValueError('Another request already exists. Close this form and open Ownership Requests.')
    return row


def save_inputs(repo,user,revision,acquired,body):
    from datetime import date
    from ygc import acquire_review as review
    validate_claim_date(acquired)
    if acquired:
        try:date.fromisoformat(acquired)
        except ValueError:raise ValueError('Enter a valid date as YYYY-MM-DD.') from None
    if len(body)>4000:raise ValueError('The description must be 4,000 characters or fewer.')
    with review.transaction(repo) as con:
        review.expire(con)
        row=review.find(con,revision)
        if row['applicant_id']!=user or not review.available_user(con,user):raise PermissionError('Only the applicant can keep this request.')
        if row['status']!='draft':raise ValueError('This request is no longer a draft.')
        if row['request_kind']=='acquire':
            con.execute('UPDATE acquire_applications SET acquisition_date=?,body=? WHERE revision=?',(acquired or None,body,revision))
        return review.detail(con,revision,user)
