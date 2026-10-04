from unittest.mock import Mock
import pytest
pytest.importorskip('psycopg')
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ygc.cloud_operations_routes import operations_router
from ygc.identity_platform import VerifiedIdentity
from ygc.db.postgres_operations import ModeConflict


@pytest.fixture
def api():
    verifier = Mock()
    verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', '', True)
    verifier.accounts.resolve_identity.return_value = {'app_user_id': 'canonical', 'role': 'admin'}
    operations = Mock()
    operations.public_status.return_value = {'mode': 'offline', 'message': 'Setup'}
    operations.details.return_value = {'mode': 'offline', 'message': 'Setup', 'version': 0}
    operations.set_mode.return_value = {'mode': 'admin_only', 'message': 'Admin test', 'version': 1}
    app = FastAPI()
    app.include_router(operations_router(verifier, operations))
    with TestClient(app) as client:
        yield client, verifier, operations


AUTH = {'Authorization': 'Bearer token'}
DATA = {'mode': 'admin_only', 'message': 'Admin test', 'version': 0}


def test_public_status_has_no_admin_details(api):
    client, verifier, operations = api
    assert client.get('/api/service/status').json() == {'mode': 'offline', 'message': 'Setup'}
    verifier.verify.assert_not_called()
    operations.details.assert_not_called()


def test_admin_operations_use_only_verified_canonical_uuid(api):
    client, verifier, operations = api
    assert client.get('/api/admin/operations', headers=AUTH).status_code == 200
    response = client.put('/api/admin/operations/mode', json=DATA, headers=AUTH)
    assert response.json()['version'] == 1
    assert response.headers['cache-control'] == 'private, no-store'
    operations.set_mode.assert_called_once_with('canonical', **DATA)


@pytest.mark.parametrize('failure', ['missing', 'token', 'email', 'role', 'disabled'])
def test_unauthorized_never_reads_or_writes_admin_state(api, failure):
    client, verifier, operations = api
    headers = AUTH
    if failure == 'missing': headers = {}
    if failure == 'token': verifier.verify.side_effect = PermissionError('private-token')
    if failure == 'email': verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', '', False)
    if failure == 'role': verifier.accounts.resolve_identity.return_value['role'] = 'member'
    if failure == 'disabled': verifier.accounts.resolve_identity.side_effect = PermissionError('disabled account')
    for response in (client.get('/api/admin/operations', headers=headers),
                     client.put('/api/admin/operations/mode', json=DATA, headers=headers)):
        assert response.status_code in (401, 403)
        assert 'private-token' not in response.text
    operations.details.assert_not_called()
    operations.set_mode.assert_not_called()


@pytest.mark.parametrize('body', [[], None, {**DATA, 'user_id': 7}, {**DATA, 'role': 'admin'}, {**DATA, 'reason': 'extra'}])
def test_forged_extra_fields_never_change_state(api, body):
    client, verifier, operations = api
    assert client.put('/api/admin/operations/mode', json=body, headers=AUTH).status_code == 400
    operations.set_mode.assert_not_called()


@pytest.mark.parametrize('error,status', [(ModeConflict('version'),409), (PermissionError('revoked'),403),
    (ValueError('bad mode'),400), (RuntimeError('private-password'),503)])
def test_recheck_failures_and_conflicts_do_not_leak(api, error, status):
    client, verifier, operations = api
    operations.set_mode.side_effect = error
    response = client.put('/api/admin/operations/mode', json=DATA, headers=AUTH)
    assert response.status_code == status
    assert 'private-password' not in response.text
