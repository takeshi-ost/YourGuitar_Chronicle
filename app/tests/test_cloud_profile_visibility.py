"""Self-only preferences stay separate from existing profile and photo APIs."""
from contextlib import contextmanager
from copy import deepcopy
from itertools import product
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from ygc.cloud_profile import (ProfileConflict, VISIBILITY_FIELDS, VISIBILITY_VALUES,
                               validate_visibility, visibility_fields, visibility_result)
from ygc.cloud_profile_visibility_routes import profile_visibility_router
from ygc.cloud_users import CloudUsers, positive_id
from ygc.db.postgres_operations import ServiceRestricted
from ygc.identity_platform import VerifiedIdentity

FIELDS = dict(zip(VISIBILITY_FIELDS, ('Private', 'Private', 'Public', 'Public')))
BODY = {'revision': '9007199254741009', 'fields': FIELDS}
RESULT = {'profile_revision': BODY['revision'], 'fields': FIELDS}
AUTH = {'Authorization': 'Bearer token'}
PATH = '/api/auth/profile/visibility'


@pytest.mark.parametrize('values', product(VISIBILITY_VALUES, repeat=4))
def test_exact_visibility_combinations(values):
    fields = dict(zip(VISIBILITY_FIELDS, values))
    assert validate_visibility({'revision': BODY['revision'], 'fields': fields}) == (9007199254741009, fields)


@pytest.mark.parametrize('value', [None, True, 1, [], {}, 'public', ' Public', 'Public ', '', 'SECRET', 'Private\x00'])
def test_invalid_enum_never_normalized(value):
    body = deepcopy(BODY)
    body['fields']['avatar_visibility'] = value
    with pytest.raises(ValueError):
        validate_visibility(body)


@pytest.mark.parametrize('value', [None, 1, True, '', '0', '-1', '1.5', '１', '1e2', '9' * 20, '0' * 10000, str(2**63)])
def test_bounded_string_revision(value):
    with pytest.raises(ValueError):
        validate_visibility({**BODY, 'revision': value})
    with pytest.raises(ValueError):
        positive_id(value)


@pytest.mark.parametrize('key', ['id', 'app_user_id', 'role', 'account_type', 'disabled', 'ban_status',
                                 'theme', 'date_of_birth', 'avatar_storage_path', 'display_name'])
def test_authority_and_other_profile_inputs_rejected(key):
    with pytest.raises(ValueError):
        validate_visibility({**BODY, key: 'attacker'})
    with pytest.raises(ValueError):
        validate_visibility({**BODY, 'fields': {**FIELDS, key: 'attacker'}})


def test_missing_or_unknown_fields_rejected():
    for value in (None, [], {}, {'revision': '1'}, {'revision': '1', 'fields': {}},
                  {**BODY, 'fields': {key: value for key, value in FIELDS.items() if key != 'bio_visibility'}}):
        with pytest.raises(ValueError):
            validate_visibility(value)


def test_legacy_values_are_explicitly_unset_and_unchanged():
    account = {**FIELDS, 'bio_visibility': 'legacy-private-secret', 'avatar_visibility': None,
               'date_of_birth': 'secret', 'avatar_storage_path': 'private-object'}
    before = deepcopy(account)
    assert visibility_fields(account) == {**FIELDS, 'bio_visibility': None, 'avatar_visibility': None}
    assert account == before
    assert visibility_result({**RESULT, 'fields': {**FIELDS, 'role': 'admin'}, 'avatar_storage_path': 'secret'}) == RESULT
    for revision in ('01', '0', '9' * 20, 1):
        with pytest.raises(RuntimeError):
            visibility_result({**RESULT, 'profile_revision': revision})


@pytest.fixture
def api():
    verifier = Mock()
    verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', '', True)
    verifier.accounts.resolve_identity.return_value = {'app_user_id': 'canonical-self', 'role': 'member'}
    service = Mock()
    service.own_visibility.return_value = deepcopy(RESULT)
    service.edit_own_visibility.return_value = deepcopy(RESULT)
    app = FastAPI()
    app.include_router(profile_visibility_router(verifier, service))
    with TestClient(app) as client:
        yield client, verifier, service


def private(response, status):
    assert response.status_code == status, response.text
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.headers['vary'] == 'Authorization'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert 'secret' not in response.text.lower()


def test_canonical_self_and_exact_dto(api):
    client, verifier, service = api
    service.own_visibility.return_value['private_account'] = 'secret'
    service.own_visibility.return_value['fields']['private_photo'] = 'secret'
    response = client.get(PATH, headers=AUTH)
    private(response, 200)
    assert response.json() == RESULT
    service.own_visibility.assert_called_once_with('canonical-self')
    response = client.put(PATH, headers=AUTH, json=BODY)
    private(response, 200)
    assert response.json() == RESULT
    service.edit_own_visibility.assert_called_once_with('canonical-self', BODY)
    verifier.accounts.resolve_identity.assert_called_with(issuer='issuer', subject='subject', tenant='')


@pytest.mark.parametrize('case,status', [('missing', 401), ('duplicate', 401), ('oversize', 401),
    ('spaces', 401), ('token', 401), ('unverified', 403), ('unregistered', 403), ('unavailable', 503)])
def test_identity_refusals(api, case, status):
    client, verifier, service = api
    headers = AUTH
    if case == 'missing': headers = {}
    if case == 'duplicate': headers = [('Authorization', 'Bearer token'), ('authorization', 'Bearer token')]
    if case == 'oversize': headers = {'Authorization': 'Bearer ' + 'x' * 16385}
    if case == 'spaces': headers = {'Authorization': 'Bearer token '}
    if case == 'token': verifier.verify.side_effect = PermissionError('secret')
    if case == 'unverified': verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', '', False)
    if case == 'unregistered': verifier.accounts.resolve_identity.side_effect = PermissionError('secret')
    if case == 'unavailable': verifier.verify.side_effect = RuntimeError('secret')
    for method in ('GET', 'PUT'):
        private(client.request(method, PATH, headers=headers, json=BODY if method == 'PUT' else None), status)
    service.own_visibility.assert_not_called()
    service.edit_own_visibility.assert_not_called()


@pytest.mark.parametrize('body', ['[]', 'null', '{', '{"revision":"1","revision":"2","fields":{}}',
    '{"revision":"1","fields":{"bio_visibility":"Public","bio_visibility":"Private"}}',
    '{"revision":"1","fields":{},"app_user_id":"someone-else"}'])
def test_strict_json(api, body):
    client, _, service = api
    private(client.put(PATH, headers={**AUTH, 'Content-Type': 'application/json'}, content=body), 400)
    service.edit_own_visibility.assert_not_called()


@pytest.mark.parametrize('query', ['user_id=2', 'user_id=2&user_id=3', 'revision=1', 'fields=Public'])
def test_no_query_targets(api, query):
    client, _, service = api
    private(client.get(PATH + '?' + query, headers=AUTH), 400)
    private(client.put(PATH + '?' + query, headers=AUTH, json=BODY), 400)
    service.own_visibility.assert_not_called()
    service.edit_own_visibility.assert_not_called()


@pytest.mark.parametrize('name,value', [('content-type', 'application/json'), ('content-length', '1'),
    ('origin', 'http://testserver'), ('sec-fetch-site', 'same-origin')])
def test_duplicate_headers_rejected(api, name, value):
    client, _, service = api
    headers = [*AUTH.items(), (name, value), (name, value)]
    private(client.request('GET', PATH, headers=headers), 400)
    private(client.request('PUT', PATH, headers=headers, content='{}'), 400)
    service.own_visibility.assert_not_called()
    service.edit_own_visibility.assert_not_called()


def test_bodies_encoding_content_type_origin_and_size(api):
    client, _, service = api
    private(client.request('GET', PATH, headers=AUTH, content='{}'), 400)
    for method in ('GET', 'PUT'):
        private(client.request(method, PATH, headers={**AUTH, 'Content-Encoding': ''}), 400)
        private(client.request(method, PATH, headers={**AUTH, 'Content-Encoding': 'gzip'}), 400)
    private(client.put(PATH, headers=AUTH, content='{}'), 400)
    private(client.put(PATH, headers={**AUTH, 'Content-Type': 'application/json'}, content=b'\xff'), 400)
    private(client.put(PATH, headers={**AUTH, 'Content-Type': 'application/json'}, content=' ' * 2049), 413)
    private(client.put(PATH, headers={**AUTH, 'Origin': 'https://attacker.invalid'}, json=BODY), 403)
    private(client.put(PATH, headers={**AUTH, 'Sec-Fetch-Site': 'cross-site'}, json=BODY), 403)
    service.own_visibility.assert_not_called()
    service.edit_own_visibility.assert_not_called()


@pytest.mark.parametrize('error,status', [(ProfileConflict('secret'), 409), (ServiceRestricted('secret'), 403),
    (PermissionError('secret'), 403), (RuntimeError('secret'), 503)])
def test_service_failures_safe(api, error, status):
    client, _, service = api
    service.own_visibility.side_effect = error
    service.edit_own_visibility.side_effect = error
    private(client.get(PATH, headers=AUTH), status)
    private(client.put(PATH, headers=AUTH, json=BODY), status)


@pytest.mark.parametrize('result', [None, [], {}, {**RESULT, 'profile_revision': 1},
    {**RESULT, 'fields': {**FIELDS, 'bio_visibility': 'secret'}}])
def test_invalid_service_response_does_not_leak(api, result):
    client, _, service = api
    service.own_visibility.return_value = result
    private(client.get(PATH, headers=AUTH), 503)


def test_service_read_uses_only_locked_canonical_preferences():
    account = {**FIELDS, 'projection_version': 9007199254741009,
               'bio_visibility': 'unsupported', 'role': 'admin', 'avatar_storage_path': 'secret'}
    operations = Mock()
    @contextmanager
    def access(kind, actor):
        assert (kind, actor) == ('user_read', 'canonical-self')
        yield Mock(), {'mode': 'normal'}, account
    operations.account_access.side_effect = access
    assert CloudUsers(None, operations).own_visibility('canonical-self') == {
        **RESULT, 'fields': {**FIELDS, 'bio_visibility': None}}


def test_service_write_fences_cas_and_fixed_update(monkeypatch):
    import json
    import ygc.cloud_users as module
    calls, lifecycle = [], []
    account = {**FIELDS, 'id': 21, 'app_user_id': 'canonical-self',
               'projection_version': 9007199254741009, 'role': 'member', 'bio': 'secret'}
    updates = dict(zip(VISIBILITY_FIELDS, VISIBILITY_VALUES))
    row = {**updates, 'projection_version': account['projection_version'] + 1}
    con = Mock()
    def execute(statement, params=None):
        calls.append((statement, params))
        return Mock(fetchone=lambda: row)
    con.execute.side_effect = execute
    guard = Mock()
    guard.execute.return_value.fetchone.return_value = {'locked': True}
    @contextmanager
    def connection(settings, target):
        assert target == 'operations'
        lifecycle.append('maintenance-lock')
        yield guard
        lifecycle.append('maintenance-release')
    @contextmanager
    def access(kind, actor):
        assert (kind, actor) == ('user_write', 'canonical-self')
        lifecycle.append('account-and-mode-lock')
        yield con, {'mode': 'normal'}, account
        lifecycle.append('account-commit-and-mode-release')
    monkeypatch.setattr(module, 'connect', connection)
    operations = Mock()
    operations.account_access.side_effect = access
    service = CloudUsers(None, operations)
    assert service.edit_own_visibility('canonical-self', {**BODY, 'fields': updates}) == {
        'profile_revision': str(row['projection_version']), 'fields': updates}
    assert lifecycle == ['maintenance-lock', 'account-and-mode-lock',
                         'account-commit-and-mode-release', 'maintenance-release']
    update = next((statement, params) for statement, params in calls if statement.startswith('UPDATE '))
    assert 'WHERE id=%s AND app_user_id=%s AND projection_version=%s' in update[0]
    assert 'RETURNING *' not in update[0]
    assert update[1][:4] == tuple(updates.values())
    assert update[1][-3:] == (21, 'canonical-self', account['projection_version'])
    metadata = next(params for statement, params in calls if statement.startswith('INSERT '))
    assert metadata[0].startswith('self_visibility:')
    audit = json.loads(metadata[1])
    assert audit['actor_app_user_id'] == audit['target_app_user_id'] == 'canonical-self'
    assert 'secret' not in metadata[1]
    calls.clear()
    with pytest.raises(ProfileConflict):
        service.edit_own_visibility('canonical-self', {**BODY, 'revision': '1'})
    assert not any(statement.startswith(('UPDATE ', 'INSERT ')) for statement, _ in calls)
    operations.account_access.reset_mock()
    guard.execute.return_value.fetchone.return_value = {'locked': False}
    with pytest.raises(ProfileConflict):
        service.edit_own_visibility('canonical-self', BODY)
    operations.account_access.assert_not_called()
