from unittest.mock import Mock

import pytest
pytest.importorskip('psycopg')
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ygc.cloud_account_routes import account_router
from ygc.cloud_registration import DOCUMENTS
from ygc.db.postgres_accounts import AccountNotRegistered
from ygc.identity_platform import VerifiedIdentity


def profile(**changes):
    return {'display_name': ' Test User ', 'account_type': 'user', 'terms_accepted': True,
            'privacy_accepted': True, 'terms_version': DOCUMENTS['terms']['version'],
            'privacy_version': DOCUMENTS['privacy']['version'], **changes}


@pytest.fixture
def api():
    identity = VerifiedIdentity('verified-issuer', 'verified-subject', '', False)
    account = {'id': 7, 'app_user_id': 'uuid', 'display_name': 'Test User', 'account_type': 'user',
               'role': 'member', 'disabled': 0, 'internal_secret': 'not-public'}
    verifier = Mock(verify=Mock(return_value=identity))
    verifier.accounts.ensure_identity.return_value = account
    verifier.accounts.resolve_identity.return_value = account
    app = FastAPI()
    app.include_router(account_router(verifier, DOCUMENTS))
    with TestClient(app) as client:
        yield client, verifier


AUTH = {'Authorization': 'Bearer test-token'}


def test_registration_only_for_verified_subject_and_safe_response(api):
    client, verifier = api
    response = client.post('/api/auth/register', json=profile(), headers=AUTH)
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.json() == {'user': {'id': 7, 'app_user_id': 'uuid', 'display_name': 'Test User',
        'account_type': 'user', 'role': 'member'}, 'identity': {'provider': 'identity-platform', 'email_verified': False}}
    verifier.verify.assert_called_once_with(bearer_token='test-token')
    verifier.accounts.ensure_identity.assert_called_once_with(issuer='verified-issuer', subject='verified-subject',
        tenant='', display_name='Test User', account_type='user',
        consents=(('terms', DOCUMENTS['terms']['version']), ('privacy', DOCUMENTS['privacy']['version'])))


@pytest.mark.parametrize('changes', [{'email': 'secret'}, {'password': 'secret'}, {'user_id': 8},
    {'role': 'admin'}, {'issuer': 'fake'}, {'subject': 'other'}, {'tenant': 'other'},
    {'terms_accepted': False}, {'privacy_accepted': 1}, {'terms_version': 'old'},
    {'display_name': ' '}, {'display_name': 'x' * 121}, {'account_type': 'admin'}, {'account_type': 'source'}])
def test_bad_profile_never_writes_or_verifies(api, changes):
    client, verifier = api
    response = client.post('/api/auth/register', json=profile(**changes), headers=AUTH)
    assert response.status_code == 400
    assert 'secret' not in response.text
    verifier.verify.assert_not_called()
    verifier.accounts.ensure_identity.assert_not_called()


@pytest.mark.parametrize('payload', [None, [], 'text', 123])
def test_non_object_payload_rejected(api, payload):
    client, verifier = api
    response = client.post('/api/auth/register', json=payload, headers=AUTH)
    assert response.status_code == 400
    verifier.accounts.ensure_identity.assert_not_called()


@pytest.mark.parametrize('header', ['', 'Basic password', 'Bearer '])
def test_missing_bearer_cannot_read_or_register(api, header):
    client, verifier = api
    assert client.get('/api/auth/me', headers={'Authorization': header}).status_code == 401
    assert client.post('/api/auth/register', json=profile(), headers={'Authorization': header}).status_code == 401
    verifier.verify.assert_not_called()


def test_invalid_token_never_touches_accounts(api):
    client, verifier = api
    verifier.verify.side_effect = PermissionError('private-token-details')
    for response in (client.get('/api/auth/me', headers=AUTH),
                     client.post('/api/auth/register', json=profile(), headers=AUTH)):
        assert response.status_code == 401
        assert 'private-token-details' not in response.text
    verifier.accounts.ensure_identity.assert_not_called()
    verifier.accounts.resolve_identity.assert_not_called()


def test_me_reads_live_account_without_automatic_enrollment(api):
    client, verifier = api
    assert client.get('/api/auth/me', headers=AUTH).status_code == 200
    verifier.accounts.resolve_identity.side_effect = AccountNotRegistered('Unknown')
    response = client.get('/api/auth/me', headers=AUTH)
    assert response.status_code == 409
    assert response.json()['code'] == 'registration_required'
    verifier.accounts.ensure_identity.assert_not_called()


def test_blocked_account_cannot_log_in_or_register(api):
    client, verifier = api
    verifier.accounts.resolve_identity.side_effect = PermissionError('disabled')
    verifier.accounts.ensure_identity.side_effect = PermissionError('disabled')
    assert client.get('/api/auth/me', headers=AUTH).status_code == 403
    assert client.post('/api/auth/register', json=profile(), headers=AUTH).status_code == 403


def test_staging_documents_are_available_without_token_and_versioned(api):
    client, _ = api
    response = client.get('/api/auth/registration')
    assert response.status_code == 200
    assert response.json()['documents'] == DOCUMENTS
    assert response.json()['backend'] == 'identity_platform'
    assert DOCUMENTS['terms']['version'].startswith('staging-')


def test_api_startup_checks_schema_and_closes_verifier(monkeypatch):
    from ygc import cloud_account_api
    accounts = Mock()
    verifier = Mock(accounts=accounts)
    monkeypatch.setattr(cloud_account_api, 'PostgresAccounts', Mock(return_value=accounts))
    monkeypatch.setattr(cloud_account_api, 'IdentityPlatformIdentity', Mock(return_value=verifier))
    app = cloud_account_api.create_app(object(), project_id='test-project')
    with TestClient(app) as client:
        accounts.check_schema.assert_called_once()
        assert client.get('/api/users').status_code == 404
        assert client.get('/docs').status_code == 404
    verifier.close.assert_called_once()


def test_api_startup_failure_closes_verifier(monkeypatch):
    from ygc import cloud_account_api
    accounts = Mock()
    accounts.check_schema.side_effect = ValueError('schema missing')
    verifier = Mock(accounts=accounts)
    monkeypatch.setattr(cloud_account_api, 'PostgresAccounts', Mock(return_value=accounts))
    monkeypatch.setattr(cloud_account_api, 'IdentityPlatformIdentity', Mock(return_value=verifier))
    app = cloud_account_api.create_app(object(), project_id='test-project')
    with pytest.raises(ValueError):
        with TestClient(app):
            pass
    verifier.close.assert_called_once()
