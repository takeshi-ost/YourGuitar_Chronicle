"""Explicit staging policies for real Google authentication, not local dummy login."""

VERSION = 'staging-draft-2026-10-04'
DOCUMENTS = {
    'terms': {'title': 'Terms — staging test draft', 'version': VERSION, 'paragraphs': [
        'This environment is for testing Your Guitar Chronicle. Data may be reset during testing. These provisional terms must be replaced before public launch.',
        'Use a display name or nickname. Respect other users and submit only content you are entitled to share. Ownership records do not establish legal title.',
        'Operators can review content and moderate accounts. Do not submit sensitive information during testing.',
    ]},
    'privacy': {'title': 'Privacy notice — staging test draft', 'version': VERSION, 'paragraphs': [
        'This staging environment uses Google Identity Platform for real authentication. Your browser sends your email address and password to Google; Google manages the authentication account.',
        'The application registration API receives an ID token to verify your identity. The token can contain your email address; the API does not accept separate email or password fields and does not store the token. It stores your application account ID, Google identity reference, display name, account type, profile settings, and policy agreement versions and times in the Accounts database and backups.',
        'Your display name is public. Optional profile fields use their visibility settings. Submitted claims and evidence may be reviewed through ChatGPT when the review feature is used. Data may be reset during testing. Final privacy information must be prepared before public launch.',
    ]},
}
