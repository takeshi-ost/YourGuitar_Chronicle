"""Private Admin transport boundary: bearer identity, CSRF, exact payloads."""
from unittest.mock import Mock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ygc.cloud_admin_application_routes import admin_application_router
from ygc.cloud_admin_applications import ApplicationConflict, parameters, safe_diagnostic
from ygc.cloud_content_media import MediaConflict
from ygc.cloud_guitars import GuitarMissing
from ygc.identity_platform import VerifiedIdentity
from starlette.datastructures import QueryParams

BASE = '/api/admin/applications'
REV = 'a' * 32
AUTH = {'Authorization': 'Bearer token'}
PAYLOAD = dict(operation='accept', reason='Photos reviewed.', expected_version='b' * 64)


@pytest.fixture
def api():
    verifier = Mock()
    verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', '', True)
    verifier.accounts.resolve_identity.return_value = {'app_user_id': 'canonical-admin', 'role': 'admin'}
    service = Mock()
    service.list.return_value = {'items': [], 'total': '0', 'next_after': None}
    service.detail.return_value = {'revision': REV, 'status': 'pending'}
    service.decide.return_value = {'revision': REV, 'status': 'accepted'}
    service.image.return_value = b'jpeg'
    app = FastAPI()
    app.include_router(admin_application_router(verifier, service))
    with TestClient(app) as client:
        yield client, verifier, service


def test_admin_routes_use_only_server_identity_and_private_outputs(api):
    client, _, service = api
    result = client.get(BASE + '?q=Fender&kind=listing&status=pending&limit=5', headers=AUTH)
    assert result.status_code == 200
    service.list.assert_called_once_with('canonical-admin', q='Fender', kind='listing', status='pending', after=None, limit=5)
    assert client.get(BASE + '/' + REV, headers=AUTH).json()['status'] == 'pending'
    service.detail.assert_called_once_with('canonical-admin', REV)
    result = client.get(BASE + '/' + REV + '/photos/reference', headers=AUTH)
    assert result.content == b'jpeg' and result.headers['content-type'] == 'image/jpeg'
    assert result.headers['cache-control'] == 'private, no-store' and result.headers['x-content-type-options'] == 'nosniff'
    result = client.post(BASE + '/' + REV + '/decision', headers=AUTH, json=PAYLOAD)
    assert result.status_code == 200
    service.decide.assert_called_once_with('canonical-admin', REV, **PAYLOAD)


@pytest.mark.parametrize('case,status', [('missing', 401), ('invalid', 401), ('unverified', 403), ('member', 403), ('disabled', 403), ('unavailable', 503)])
@pytest.mark.parametrize('endpoint', ['', '/' + REV, '/' + REV + '/photos/closeup', '/' + REV + '/decision'])
def test_identity_failures_never_reach_service(api, case, status, endpoint):
    client, verifier, service = api
    headers = AUTH
    if case == 'missing':
        headers = {}
    if case == 'invalid':
        verifier.verify.side_effect = PermissionError('private')
    if case == 'unverified':
        verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', '', False)
    if case == 'member':
        verifier.accounts.resolve_identity.return_value['role'] = 'member'
    if case == 'disabled':
        verifier.accounts.resolve_identity.side_effect = PermissionError('private')
    if case == 'unavailable':
        verifier.accounts.resolve_identity.side_effect = RuntimeError('private')
    response = client.post(BASE + endpoint, headers=headers, json=PAYLOAD) if endpoint.endswith('decision') else client.get(BASE + endpoint, headers=headers)
    assert response.status_code == status and 'private' not in response.text
    for method in ('list', 'detail', 'decide', 'image'):
        getattr(service, method).assert_not_called()


@pytest.mark.parametrize('extra', [{'Origin': 'https://evil.example'}, {'Origin': 'null'}, {'Sec-Fetch-Site': 'cross-site'}])
def test_cross_origin_decision_refused(api, extra):
    client, _, service = api
    assert client.post(BASE + '/' + REV + '/decision', headers=AUTH | extra, json=PAYLOAD).status_code == 403
    service.decide.assert_not_called()


def test_same_origin_non_cookie_json_accepted(api):
    client, _, _ = api
    assert client.post(BASE + '/' + REV + '/decision', headers=AUTH | {'Origin': 'http://testserver', 'Sec-Fetch-Site': 'same-origin'}, json=PAYLOAD).status_code == 200
    client.cookies.set('session', 'token')
    assert client.post(BASE + '/' + REV + '/decision', json=PAYLOAD).status_code == 401


@pytest.mark.parametrize('payload', [[], None, {}, PAYLOAD | {'actor': 1}, {'operation': 'accept', 'reason': 'missing version'}])
def test_exact_decision_payload(api, payload):
    client, _, service = api
    assert client.post(BASE + '/' + REV + '/decision', headers=AUTH, json=payload).status_code == 400
    service.decide.assert_not_called()


def test_bad_json_duplicate_keys_body_limit_and_content_type(api):
    client, _, service = api
    path = BASE + '/' + REV + '/decision'
    for raw in (b'{', b'\xff', b'{"operation":"accept","operation":"reject","reason":"x","expected_version":"x"}'):
        assert client.post(path, headers=AUTH | {'Content-Type': 'application/json'}, content=raw).status_code == 400
    assert client.post(path, headers=AUTH | {'Content-Type': 'application/json'}, content=b'x' * (32768 + 1)).status_code == 413
    assert client.post(path, headers=AUTH, data=PAYLOAD).status_code == 400
    assert client.post(path, headers=AUTH | {'Content-Encoding': 'gzip'}, json=PAYLOAD).status_code == 400
    assert client.post(path + '?actor=x', headers=AUTH, json=PAYLOAD).status_code == 400
    service.decide.assert_not_called()


@pytest.mark.parametrize('query', ['actor=1', 'limit=51', 'limit=0', 'limit=true', 'q=a&q=b', 'status=unknown', 'kind=other', 'after=not-a-revision'])
def test_strict_search_parameters(api, query):
    client, _, service = api
    assert client.get(BASE + '?' + query, headers=AUTH).status_code == 400
    service.list.assert_not_called()


@pytest.mark.parametrize('exception,status', [(ApplicationConflict('secret'), 409), (MediaConflict('secret'), 409), (GuitarMissing('secret'), 404), (PermissionError('secret'), 403), (ValueError('secret'), 400), (RuntimeError('secret'), 503)])
def test_sanitized_failures_never_echo_internal_details(api, exception, status):
    client, _, service = api
    service.decide.side_effect = exception
    result = client.post(BASE + '/' + REV + '/decision', headers=AUTH, json=PAYLOAD)
    assert result.status_code == status and 'secret' not in result.text
    assert result.headers['cache-control'] == 'private, no-store'


def test_photo_boundary_and_unavailable_storage(api):
    client, _, service = api
    assert client.get(BASE + '/' + REV + '/photos/not-a-role', headers=AUTH).status_code == 400
    service.image.assert_not_called()
    service.storage = None
    assert client.get(BASE + '/' + REV + '/photos/closeup', headers=AUTH).status_code == 503
    service.image.assert_not_called()


def test_nested_diagnostics_strip_private_locators_and_authority():
    result = safe_diagnostic({'reference': {'path': 'gcs', 'url': 'https://private', 'claim_id': 2},
                              'previous_review': [{'lease_token': 'secret', 'observed': 'guitar'}]})
    assert result == {'reference': {'claim_id': 2}, 'previous_review': [{'observed': 'guitar'}]}
    assert parameters(QueryParams(''))['limit'] == 25
