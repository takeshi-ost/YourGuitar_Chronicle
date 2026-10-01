"""Validate user-entered Claim dates against UTC now in the viewer's timezone."""
from contextvars import ContextVar
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from pydantic import BaseModel, model_validator

viewer_timezone = ContextVar('claim_viewer_timezone', default=ZoneInfo('UTC'))


def validate_claim_date(value, *, now=None):
    if value is None or value == '':
        return value
    now = now or datetime.now(timezone.utc)
    local = viewer_timezone.get()
    text = str(value).strip()
    try:
        if len(text) == 10:
            future = date.fromisoformat(text) > now.astimezone(local).date()
        else:
            instant = datetime.fromisoformat(text.replace('Z', '+00:00'))
            if instant.tzinfo is None:
                instant = instant.replace(tzinfo=local)
            future = instant.astimezone(timezone.utc) > now.astimezone(timezone.utc)
    except ValueError:
        raise ValueError('Enter a valid Claim date or datetime.') from None
    if future:
        raise ValueError('Claim dates cannot be in the future (your local time).')
    return text if len(text)==10 else instant.astimezone(timezone.utc).isoformat()


class ClaimDateRequest(BaseModel):
    @model_validator(mode='before')
    @classmethod
    def check_dates(cls, data):
        if isinstance(data, dict):
            data=dict(data)
            for key in ('occurred_at', 'acquired_at', 'released_at', 'acquisition_date', 'release_date'):
                if key in data:
                    data[key]=validate_claim_date(data[key])
        return data
