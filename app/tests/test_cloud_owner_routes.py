from unittest.mock import Mock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ygc.cloud_owner_routes import owner_router
from ygc.identity_platform import VerifiedIdentity
from ygc.claim_revision import ClaimConflict

AUTH = {'Authorization': 'Bearer fixture'}
PATH = '/api/auth/guitars/12/owner-responses'


@pytest.fixture
def api():
    verifier, service = Mock(), Mock()
    verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', '', True)
    verifier.accounts.resolve_identity.return_value = {'app_user_id': 'canonical'}
    service.pending.return_value = {'items': []}
    service.respond.return_value = {'claim_id': '23', 'verification_status': 'positive'}
    app = FastAPI(); app.include_router(owner_router(verifier, service))
    with TestClient(app) as client:
        yield client, verifier, service


def test_owner_identity_and_private_response(api):
    client, verifier, service = api
    assert client.get(PATH).status_code == 401
    response = client.get(PATH, headers=AUTH)
    assert response.json() == {'items': []} and response.headers['cache-control'] == 'private, no-store'
    service.pending.assert_called_once_with('canonical', 12)
    body = {'stance': 'positive', 'revision': 'a' * 64}
    assert client.post(PATH + '/23', headers=AUTH, json=body).status_code == 200
    service.respond.assert_called_once_with('canonical', 12, 23, body)
    assert client.get(PATH + '?user_id=2', headers=AUTH).status_code == 400
    assert client.post(PATH + '/23', headers=AUTH, content='x' * 4097).status_code == 400


@pytest.mark.parametrize('failure,code', [(PermissionError, 403), (ClaimConflict, 409), (ValueError, 400), (RuntimeError, 503)])
def test_owner_errors_are_sanitized(api, failure, code):
    client, verifier, service = api
    service.respond.side_effect = failure('secret details')
    response = client.post(PATH + '/23', headers=AUTH, json={})
    assert response.status_code == code and 'secret details' not in response.text


def test_unverified_identity_does_not_reach_owner_service(api):
    client, verifier, service = api
    verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', '', False)
    assert client.get(PATH, headers=AUTH).status_code == 403
    service.pending.assert_not_called()
