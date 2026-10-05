"""Strict administrator profile patch; authority and credentials are excluded."""
from ygc.registration_fields import DISPLAY_NAME_MAX

FIELDS=('display_name','location_country','location_region','bio')
class ProfileConflict(ValueError):pass


def validate(body):
    from ygc.cloud_users import positive_id
    if not isinstance(body,dict) or set(body)!={'revision','fields'}:raise ValueError('Invalid profile.')
    version=positive_id(body['revision'])
    fields=body['fields']
    if not isinstance(fields,dict) or set(fields)!=set(FIELDS):raise ValueError('Invalid profile fields.')
    result={}
    for key in FIELDS:
        value=fields[key]
        limit=2000 if key=='bio' else DISPLAY_NAME_MAX
        if not isinstance(value,str) or len(value)>limit or any(ord(c)<32 and not (key=='bio' and c in '\n\t\r') for c in value):
            raise ValueError('Invalid profile value.')
        result[key]=value.strip()
    if not result['display_name']:raise ValueError('Display name is required.')
    return version,result
