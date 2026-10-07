"""Strict shared profile patch; authority and credentials are excluded."""
from ygc.registration_fields import DISPLAY_NAME_MAX

FIELDS=('display_name','location_country','location_region','bio')
VISIBILITY_FIELDS = ('birth_visibility', 'residence_visibility', 'bio_visibility', 'avatar_visibility')
VISIBILITY_VALUES = ('Public', 'Members', 'Followers', 'Private')
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


def validate_visibility(body):
    """An explicit complete selection, never a profile/authority patch."""
    from ygc.cloud_users import positive_id
    if not isinstance(body, dict) or set(body) != {'revision', 'fields'}:
        raise ValueError('Invalid visibility settings.')
    revision = body['revision']
    if not isinstance(revision, str) or len(revision) > 19:
        raise ValueError('Invalid profile revision.')
    version = positive_id(revision)
    fields = body['fields']
    if not isinstance(fields, dict) or set(fields) != set(VISIBILITY_FIELDS):
        raise ValueError('Invalid visibility fields.')
    if any(not isinstance(value, str) or value not in VISIBILITY_VALUES for value in fields.values()):
        raise ValueError('Invalid visibility value.')
    return version, {key: fields[key] for key in VISIBILITY_FIELDS}


def visibility_fields(account):
    """Unknown legacy values are unset in the DTO, never normalized in storage.

    Schema defaults are saved preferences, not proof of consent to publish.
    No public profile or image access decision may be derived from this DTO.
    """
    return {key: account[key] if account[key] in VISIBILITY_VALUES else None
            for key in VISIBILITY_FIELDS}


def visibility_result(result):
    """Defense-in-depth response whitelist; account and image data stay private."""
    from ygc.cloud_users import positive_id
    try:
        if not isinstance(result, dict) or not isinstance(result['fields'], dict):
            raise ValueError()
        revision = result['profile_revision']
        if not isinstance(revision, str) or len(revision) > 19:
            raise ValueError()
        if str(positive_id(revision)) != revision:
            raise ValueError()
        fields = {key: result['fields'][key] for key in VISIBILITY_FIELDS}
        if any(value is not None and (not isinstance(value, str) or value not in VISIBILITY_VALUES)
               for value in fields.values()):
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise RuntimeError('Invalid visibility result.') from None
    return {'profile_revision': revision, 'fields': fields}
