"""Local prototype registration; credentials never cross this boundary."""
from ygc.db.repository import utcnow

VERSION = 'local-draft-2026-10-03'
DOCUMENTS = {
    'terms': {'title': 'Terms — local prototype draft', 'version': VERSION, 'paragraphs': [
        'These provisional terms apply to local testing of Your Guitar Chronicle. Final terms must be prepared before public launch.',
        'Use a display name or nickname. Respect other users and submit only content you are entitled to share. Ownership records and reviews describe submitted information; they do not establish legal title.',
        'Operators can review submitted content and moderate accounts. This prototype may change during development.'
    ]},
    'privacy': {'title': 'Privacy notice — local prototype draft', 'version': VERSION, 'paragraphs': [
        'This provisional notice describes local testing. Final privacy information must be prepared before public launch.',
        'The dummy registration does not send or save your email address or password. Your display name, account identifier, profile settings, and agreement versions and times are saved in the local user database and its backups.',
        'Your display name is public. Optional profile fields use their visibility settings. Submitted claims and evidence may be reviewed through ChatGPT when the review feature is used. Do not submit sensitive information during testing.'
    ]}
}


def register(repository, body):
    allowed = {'account_type', 'display_name', 'terms_accepted', 'privacy_accepted', 'terms_version', 'privacy_version'}
    if not isinstance(body, dict) or set(body) - allowed:
        raise ValueError('Send only profile and agreement fields; credentials are not accepted.')
    name = body.get('display_name')
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
        raise ValueError('Display Name is required (maximum 120 characters).')
    if body.get('terms_accepted') is not True or body.get('privacy_accepted') is not True:
        raise ValueError('Agree to the Terms and Privacy notice to create an account.')
    if body.get('terms_version') != VERSION or body.get('privacy_version') != VERSION:
        raise ValueError('The agreement version has changed. Reopen Create Account and review the current documents.')
    account_type = body.get('account_type', 'user')
    if account_type not in ('user', 'shop', 'builder', 'repairer', 'organization'):
        raise ValueError('Select a valid Account Type.')
    now = utcnow()
    # Projection triggers and agreements share one cross-database transaction.
    with repository.connect() as con:
        user_id = con.execute("INSERT INTO users(display_name,account_type,created_at,updated_at) VALUES (?,?,?,?)", (name.strip(),account_type,now,now)).lastrowid
        app_user_id = con.execute('SELECT app_user_id FROM users WHERE id=?',(user_id,)).fetchone()[0]
        con.executemany('INSERT INTO accounts.account_consents VALUES (?,?,?,?)', [(app_user_id,kind,VERSION,now) for kind in DOCUMENTS])
    return user_id
