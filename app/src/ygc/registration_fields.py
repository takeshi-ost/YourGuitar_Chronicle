"""Profile and consent validation shared by local and cloud registration."""

ACCOUNT_TYPES = ('user', 'shop', 'builder', 'repairer', 'organization')
DISPLAY_NAME_MAX = 120


def validate_registration(body, versions):
    allowed = {'account_type', 'display_name', 'terms_accepted', 'privacy_accepted', 'terms_version', 'privacy_version'}
    if not isinstance(body, dict) or set(body) - allowed:
        raise ValueError('Send only profile and agreement fields; credentials are not accepted.')
    name = body.get('display_name')
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > DISPLAY_NAME_MAX:
        raise ValueError('Display Name is required (maximum 120 characters).')
    if body.get('terms_accepted') is not True or body.get('privacy_accepted') is not True:
        raise ValueError('Agree to the Terms and Privacy notice to create an account.')
    if any(body.get(kind + '_version') != version for kind, version in versions.items()):
        raise ValueError('The agreement version has changed. Reopen Create Account and review the current documents.')
    account_type = body.get('account_type', 'user')
    if account_type not in ACCOUNT_TYPES:
        raise ValueError('Select a valid Account Type.')
    return {'display_name': name.strip(), 'account_type': account_type,
            'consents': tuple(versions.items())}
