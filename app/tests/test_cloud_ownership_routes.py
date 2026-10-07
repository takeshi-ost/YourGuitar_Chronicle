"""Authenticated ownership routes never accept a browser-selected actor."""
import json
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ygc.claim_dates import viewer_timezone
from ygc.claim_revision import ClaimConflict
from ygc.cloud_guitars import GuitarMissing
from ygc.cloud_ownership_routes import ownership_router
from ygc.db.postgres_operations import ServiceRestricted
from ygc.identity_platform import VerifiedIdentity

AUTH = {'Authorization': 'Bearer fixture'}
BASE = '/api/auth/guitars/12'
ROUTES = [('get', '/api/auth/ownership-transfers', 'inbox'),
    ('get', BASE + '/ownership', 'view'), ('get', BASE + '/transfer-users', 'search_users'),
    ('post', BASE + '/transfers', 'create'), ('get', '/api/auth/transfers/19', 'detail'),
    ('post', '/api/auth/transfers/19/resolve', 'resolve'), ('post', BASE + '/release', 'release')]


@pytest.fixture
def api():
    verifier, service = Mock(), Mock()
    verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', 'tenant', True)
    verifier.accounts.resolve_identity.return_value = {'app_user_id': 'canonical'}
    for _, _, name in ROUTES:
        getattr(service, name).return_value = {'ok': True}
    app = FastAPI()
    app.include_router(ownership_router(verifier, service))
    with TestClient(app) as client:
        yield client, verifier, service


@pytest.mark.parametrize('verb,path,method', ROUTES)
def test_all_routes_authenticate_and_hide_private_cache(api, verb, path, method):
    client, verifier, service = api
    kwargs = {'json': {}} if verb == 'post' else {}
    unauthenticated = getattr(client, verb)(path, **kwargs)
    assert unauthenticated.status_code == 401
    assert unauthenticated.headers['cache-control'] == 'private, no-store'
    assert unauthenticated.headers['vary'] == 'Authorization'
    response = getattr(client, verb)(path, headers=AUTH, **kwargs)
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.headers['vary'] == 'Authorization'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert getattr(service, method).call_args.args[0] == 'canonical'
    verifier.verify.assert_called_with(bearer_token='fixture')
    verifier.accounts.resolve_identity.assert_called_with(issuer='issuer', subject='subject', tenant='tenant')


def test_router_dispatch_and_string_identifier_bounds(api):
    client, _, service = api
    assert client.get(BASE + '/ownership?after=40&limit=2', headers=AUTH).status_code == 200
    service.view.assert_called_once_with('canonical', 12, after=40, limit=2)
    assert client.get(BASE + '/transfer-users?q=Recipient&offset=20&limit=3', headers=AUTH).status_code == 200
    service.search_users.assert_called_once_with('canonical', 12, q='Recipient', offset=20, limit=3)
    assert client.get('/api/auth/transfers/9007199254740993', headers=AUTH).status_code == 200
    service.detail.assert_called_once_with('canonical', 9007199254740993)
    data = {'action': 'accept', 'revision': 'a' * 64}
    assert client.post('/api/auth/transfers/19/resolve', json=data, headers=AUTH).status_code == 200
    service.resolve.assert_called_once_with('canonical', 19, data)


@pytest.mark.parametrize('query', ['user_id=2', 'viewer_id=2', 'after=0', 'after=-1', 'after=9223372036854775808',
    'after=x', 'limit=51', 'limit=1&limit=2', 'limit=0', 'offset=1'])
def test_invalid_page_queries_never_reach_service(api, query):
    client, _, service = api
    assert client.get(BASE + '/ownership?' + query, headers=AUTH).status_code == 400
    service.view.assert_not_called()


@pytest.mark.parametrize('query', ['offset=-1', 'offset=201', 'offset=1&offset=2', 'limit=21', 'q=a&q=b',
    'q=' + 'x' * 121, 'q=x%0A', 'email=a', 'viewer_id=2'])
def test_destination_search_bounds(api, query):
    client, _, service = api
    assert client.get(BASE + '/transfer-users?' + query, headers=AUTH).status_code == 400
    service.search_users.assert_not_called()


@pytest.mark.parametrize('verb,path,method', ROUTES)
def test_unverified_account_never_reaches_service(api, verb, path, method):
    client, verifier, service = api
    verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', '', False)
    kwargs = {'json': {}} if verb == 'post' else {}
    assert getattr(client, verb)(path, headers=AUTH, **kwargs).status_code == 403
    getattr(service, method).assert_not_called()


@pytest.mark.parametrize('extra', [{'Origin': 'https://foreign.invalid'}, {'Sec-Fetch-Site': 'cross-site'}])
def test_cross_site_mutations_denied(api, extra):
    client, _, service = api
    assert client.post(BASE + '/transfers', json={}, headers=AUTH | extra).status_code == 403
    service.create.assert_not_called()


def test_duplicate_authorization_and_body_fields_denied(api):
    client, _, service = api
    response = client.get(BASE + '/ownership', headers=[('Authorization', 'Bearer a'), ('Authorization', 'Bearer b')])
    assert response.status_code in (400, 401)
    service.view.assert_not_called()
    for raw in ('[]', 'null', '{', '{"action":"accept","action":"cancel"}'):
        assert client.post('/api/auth/transfers/19/resolve', headers=AUTH | {'Content-Type': 'application/json'}, content=raw).status_code == 400
    service.resolve.assert_not_called()


def test_request_size_timezone_and_no_cookie_identity(api):
    client, _, service = api
    path = BASE + '/release'
    assert client.post(path, headers=AUTH | {'Content-Type': 'application/json'}, content=' ' * (32 * 1024 + 1)).status_code == 413
    for extra in ({'Content-Encoding': 'gzip'}, {'X-YGC-Timezone': 'Invalid/Zone'}):
        assert client.post(path, headers=AUTH | extra, json={}).status_code == 400
    assert client.post(path + '?user_id=4', headers=AUTH, json={}).status_code == 400
    assert client.post(path, headers=AUTH, data='x=2').status_code == 400
    service.release.assert_not_called()
    previous = viewer_timezone.get()
    service.release.side_effect = lambda *args: {'zone': str(viewer_timezone.get())}
    response = client.post(path, headers=AUTH | {'X-YGC-Timezone': 'Asia/Tokyo', 'Origin': 'http://testserver'}, json={})
    assert response.json() == {'zone': 'Asia/Tokyo'} and viewer_timezone.get() == previous
    body = {'body': '🎸' * 2000, 'occurred_at': '2020-01-01', 'revision': 'a' * 64}
    assert client.post(path, headers=AUTH | {'Content-Type': 'application/json'}, content=json.dumps(body)).status_code == 200


@pytest.mark.parametrize('failure,code', [(GuitarMissing, 404), (ClaimConflict, 409), (PermissionError, 403),
    (ServiceRestricted, 403), (ValueError, 400), (RuntimeError, 503)])
def test_errors_are_sanitized(api, failure, code):
    client, _, service = api
    service.resolve.side_effect = failure('private account and SQL secret')
    response = client.post('/api/auth/transfers/19/resolve', headers=AUTH, json={})
    assert response.status_code == code and 'private account' not in response.text
    if failure is ServiceRestricted:
        assert response.json()['detail'] == {'code': 'service_restricted'}


def test_only_seven_bounded_cloud_routes_exist(api):
    client, _, service = api
    assert client.get('/api/transfer-users?viewer_id=2', headers=AUTH).status_code == 404
    assert client.get('/api/transfers/19?viewer_id=2', headers=AUTH).status_code == 404
    assert client.patch('/api/auth/transfers/19', headers=AUTH, json={}).status_code == 405
    assert client.get('/api/auth/transfers/19?viewer_id=2', headers=AUTH).status_code == 400


@pytest.mark.parametrize('authorization', ['Basic fixture', 'Bearer', ''])
def test_malformed_auth_errors_are_not_cacheable(api, authorization):
    client, _, service = api
    response = client.get(BASE + '/ownership', headers={'Authorization': authorization})
    assert response.status_code == 401
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.headers['vary'] == 'Authorization'
    assert response.headers['x-content-type-options'] == 'nosniff'
    service.view.assert_not_called()


def test_verifier_denial_is_not_cacheable(api):
    client, verifier, service = api
    verifier.verify.side_effect = PermissionError('private authentication detail')
    response = client.get(BASE + '/ownership', headers=AUTH)
    assert response.status_code == 401
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.headers['vary'] == 'Authorization'
    assert 'private authentication' not in response.text
    service.view.assert_not_called()
