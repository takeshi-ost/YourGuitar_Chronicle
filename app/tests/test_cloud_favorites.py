"""Self-only favorite API, portable SQL behavior and production lock contracts."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import re
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ygc.claim_revision import ClaimConflict
from ygc.cloud_favorite_routes import favorite_router
from ygc.cloud_favorites import CloudFavorites, result_projection
from ygc.cloud_guitars import GuitarMissing
from ygc.cloud_public_catalog import GUITAR_FIELDS
from ygc.db.postgres_operations import ServiceRestricted
from ygc.db.repository import Repository
from ygc.db.postgres_queries import SharedCursor
from ygc.identity_platform import VerifiedIdentity

BASE = '/api/auth/favorites'
AUTH = {'Authorization': 'Bearer synthetic'}
BIG = 9007199254740993


class SQLiteSQL:
    """Test-only parameter/left/ANY adapter; production runs native PostgreSQL."""
    def __init__(self, connection):
        self.connection = connection

    def execute(self, statement, params=()):
        statement = re.sub(r'left\((i\.\w+),200\)', r'substr(\1,1,200)', statement)
        values = []
        for value in params:
            if isinstance(value, list):
                statement = statement.replace('=ANY(%s)', ' IN (' + ','.join('?' for _ in value) + ')', 1)
                values.extend(value)
            else:
                statement = statement.replace('%s', '?', 1)
                values.append(value)
        return SharedCursor(self.connection.execute(statement, tuple(values)))


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    repo = Repository(tmp_path / 'favorites.db')
    repo.init_db()
    a, b, author = [repo.create_user(name) for name in ('A', 'B', 'Author')]
    ids = []
    for index in range(4):
        if index == 3:
            with repo.connect() as con:
                con.execute("UPDATE sqlite_sequence SET seq=? WHERE name='individuals'", (BIG - 1,))
        individual, *_ = repo.create_initial_listing_claim(author, manufacturer='Fender',
            model='Model ' + str(index), serial_number='FAVORITE-' + str(index),
            occurred_at='2020-01-01', media_storage_path='private/base.jpg')
        ids.append(individual)
    assert ids[-1] == BIG
    state = {'mode': 'normal', 'maintenance': False}
    service = CloudFavorites(None, None)

    @contextmanager
    def transaction(actor, *, individual=None, write=False, inspect_target=True):
        if write and state['maintenance']:
            raise ClaimConflict()
        if state['mode'] in ('offline', 'admin_only') or (write and state['mode'] == 'read_only'):
            raise ServiceRestricted()
        with repo.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            if not con.execute("SELECT 1 FROM users WHERE id=? AND ban_status<>'ban' AND account_type<>'source'", (actor,)).fetchone():
                raise PermissionError()
            yield SQLiteSQL(con), actor

    monkeypatch.setattr(service, 'transaction', transaction)
    return repo, service, a, b, author, ids, state


def snapshot(repo):
    with repo.connect() as con:
        tables = [row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {table: [tuple(row) for row in con.execute(f'SELECT * FROM "{table}" ORDER BY rowid')]
                for table in tables}


def test_self_only_idempotent_bigint_keyset_and_no_side_effects(workflow):
    repo, service, a, b, _, ids, _ = workflow
    before = snapshot(repo)
    for target in ids:
        assert service.set(a, target, favorite=True) == {'individual_id': str(target), 'favorite': True}
    service.set(b, ids[1], favorite=True)
    after = snapshot(repo)
    assert {k: v for k, v in before.items() if k != 'user_favorites'} == {k: v for k, v in after.items() if k != 'user_favorites'}
    for target in ids:
        service.set(a, target, favorite=True)
    assert snapshot(repo) == after
    page = service.list(a, limit=2)
    assert [row['id'] for row in page['items']] == [str(ids[3]), str(ids[2])]
    assert page['total'] == '4' and page['next_after'] == str(ids[2])
    assert all(set(row) == {'id', *GUITAR_FIELDS, 'photo'} and row['photo'] is None for row in page['items'])
    second = service.list(a, after=int(page['next_after']), limit=2)
    assert [row['id'] for row in second['items']] == [str(ids[1]), str(ids[0])]
    assert second['total'] == '4' and second['next_after'] is None
    assert service.detail(b, ids[0])['favorite'] is False
    assert service.detail(a, ids[0])['favorite'] is True
    assert snapshot(repo) == after, 'GETs changed data'
    service.set(a, ids[1], favorite=False)
    service.set(a, ids[1], favorite=False)
    assert service.detail(b, ids[1])['favorite'] is True
    assert service.detail(a, ids[1])['favorite'] is False


@pytest.mark.parametrize('change', ["status='inactive'", "claim_type='private_kind'", "verification_status='private_state'"])
def test_hidden_or_deleted_targets_absent_from_both_list_and_total(workflow, change):
    repo, service, a, _, _, ids, _ = workflow
    for target in ids:
        service.set(a, target, favorite=True)
    with repo.connect() as con:
        con.execute('UPDATE claims SET ' + change + ' WHERE individual_id=?', (ids[0],))
        con.execute('DELETE FROM individuals WHERE id=?', (ids[1],))
    assert service.list(a)['total'] == '2'
    assert [row['id'] for row in service.list(a)['items']] == [str(ids[3]), str(ids[2])]
    for target in (ids[0], ids[1], BIG + 99):
        with pytest.raises(GuitarMissing):
            service.detail(a, target)
        with pytest.raises(GuitarMissing):
            service.set(a, target, favorite=True)
        assert service.set(a, target, favorite=False) == {'individual_id': str(target), 'favorite': False}


@pytest.mark.parametrize('ban', ['ban', 'silent_ban'])
def test_author_ban_visibility_and_no_favorite_disclosure(workflow, ban):
    repo, service, a, b, author, ids, _ = workflow
    service.set(a, ids[0], favorite=True)
    with repo.connect() as con:
        con.execute('UPDATE users SET ban_status=? WHERE id=?', (ban, author))
    assert service.list(a) == {'items': [], 'total': '0', 'next_after': None}
    for user in (a, b):
        with pytest.raises(GuitarMissing):
            service.detail(user, ids[0])
        with pytest.raises(GuitarMissing):
            service.set(user, ids[0], favorite=True)


def test_nonpositive_supported_claims_remain_public(workflow):
    repo, service, a, _, _, ids, _ = workflow
    for target, state in zip(ids, ('positive', 'unverified', 'negative', 'positive')):
        with repo.connect() as con:
            con.execute('UPDATE claims SET verification_status=? WHERE individual_id=?', (state, target))
        service.set(a, target, favorite=True)
    assert service.list(a)['total'] == '4'


def test_repeated_concurrent_add_and_remove_are_single_self_rows(workflow):
    repo, service, a, b, _, ids, _ = workflow
    target = ids[0]
    for state in (True, False):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: service.set(a, target, favorite=state), range(8)))
        assert all(row['favorite'] is state for row in results)
        assert service.detail(a, target)['favorite'] is state
        assert service.detail(b, target)['favorite'] is False


@pytest.mark.parametrize('mode', ['read_only', 'offline', 'admin_only'])
def test_modes_and_maintenance_preserve_relation(workflow, mode):
    repo, service, a, _, _, ids, state = workflow
    service.set(a, ids[0], favorite=True)
    state['mode'] = mode
    before = snapshot(repo)
    if mode == 'read_only':
        assert service.list(a)['total'] == '1'
        assert service.detail(a, ids[0])['favorite'] is True
    else:
        with pytest.raises(ServiceRestricted):
            service.list(a)
        with pytest.raises(ServiceRestricted):
            service.detail(a, ids[0])
    for wanted in (True, False):
        with pytest.raises(ServiceRestricted):
            service.set(a, ids[0], favorite=wanted)
    state['mode'], state['maintenance'] = 'normal', True
    assert service.list(a)['total'] == '1'
    for wanted in (True, False):
        with pytest.raises(ClaimConflict):
            service.set(a, ids[0], favorite=wanted)
    assert snapshot(repo) == before


@pytest.mark.parametrize('kwargs', [{'after': -1}, {'after': 2**63}, {'after': False}, {'after': '1'},
                                   {'limit': 0}, {'limit': 51}, {'limit': True}, {'limit': '1'}])
def test_service_page_bounds(workflow, kwargs):
    _, service, a, *_ = workflow
    with pytest.raises(ValueError):
        service.list(a, **kwargs)


@pytest.mark.parametrize('value', [0, -1, 2**63, True, '1', None])
def test_service_id_bounds(workflow, value):
    _, service, a, *_ = workflow
    with pytest.raises(ValueError):
        service.detail(a, value)
    with pytest.raises(ValueError):
        service.set(a, value, favorite=False)


@pytest.mark.parametrize('value', [1, 0, 'true', None, [], {}])
def test_service_requires_real_boolean(workflow, value):
    _, service, a, _, _, ids, _ = workflow
    with pytest.raises(ValueError):
        service.set(a, ids[0], favorite=value)


@pytest.fixture
def api():
    verifier, service = Mock(), Mock()
    verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', '', True)
    verifier.accounts.resolve_identity.return_value = {'app_user_id': 'canonical', 'id': 999}
    service.list.return_value = {'items': [], 'total': '0', 'next_after': None}
    service.detail.return_value = service.set.return_value = {'individual_id': str(BIG), 'favorite': True}
    app = FastAPI()
    app.include_router(favorite_router(verifier, service))
    with TestClient(app) as client:
        yield client, verifier, service


def private(response):
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.headers['vary'] == 'Authorization'
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_canonical_identity_bigint_and_exact_contract(api):
    client, verifier, service = api
    response = client.get(BASE, headers=AUTH)
    assert response.status_code == 200 and response.json() == {'items': [], 'total': '0', 'next_after': None}
    private(response)
    service.list.assert_called_once_with('canonical', after=0, limit=25)
    verifier.accounts.resolve_identity.assert_called_once_with(issuer='issuer', subject='subject', tenant='')
    response = client.get(BASE + '/' + str(BIG), headers=AUTH)
    assert response.status_code == 200 and response.json()['individual_id'] == str(BIG)
    service.detail.assert_called_once_with('canonical', BIG)
    response = client.put(BASE + '/' + str(BIG), json={'favorite': False}, headers=AUTH)
    assert response.status_code == 200
    service.set.assert_called_once_with('canonical', BIG, favorite=False)


@pytest.mark.parametrize('method,path', [('get', ''), ('get', '/' + str(BIG)), ('put', '/' + str(BIG))])
def test_one_verified_bearer_required_on_every_route(api, method, path):
    client, verifier, service = api
    for headers in ({'Cookie': 'user_id=999; session=secret'},
            [('Authorization', 'Bearer first'), ('Authorization', 'Bearer second')],
            {'Authorization': 'Bearer token '}, {'Authorization': 'Bearer ' + 'x' * 16385}):
        response = getattr(client, method)(BASE + path, headers=headers)
        assert response.status_code == 401
        private(response)
    verifier.verify.assert_not_called()
    verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', '', False)
    response = getattr(client, method)(BASE + path, headers=AUTH)
    assert response.status_code == 403
    verifier.accounts.resolve_identity.assert_not_called()
    assert not service.mock_calls


@pytest.mark.parametrize('query', ['?user_id=1', '?actor=1', '?individual_id=1', '?limit=51', '?limit=0',
    '?limit=true', '?limit=1&limit=2', '?after=0', '?after=-1', '?after=9223372036854775808',
    '?after=١', '?after=1&after=2', '?after=01', '?after=' + '1' * 200])
def test_unknown_duplicate_or_unbounded_query_rejected(api, query):
    client, _, service = api
    response = client.get(BASE + query, headers=AUTH)
    assert response.status_code == 400
    private(response)
    service.list.assert_not_called()


def test_valid_bigint_cursor_and_empty_get_body(api):
    client, _, service = api
    assert client.get(BASE + f'?after={BIG}&limit=50', headers=AUTH).status_code == 200
    service.list.assert_called_once_with('canonical', after=BIG, limit=50)
    assert client.request('GET', BASE, headers=AUTH, content='{}').status_code == 400
    assert client.get(BASE + f'/{BIG}?after=1', headers=AUTH).status_code == 400
    service.detail.assert_not_called()


@pytest.mark.parametrize('body', ['[]', 'null', 'true', '42', '{', '{}', '{"user_id":1,"favorite":true}',
    '{"favorite":1}', '{"favorite":"true"}', '{"favorite":null}', '{"favorite":true,"favorite":false}',
    '{"favorite":true,"actor":"other"}'])
def test_only_exact_boolean_object_accepted(api, body):
    client, _, service = api
    response = client.put(BASE + f'/{BIG}', headers=AUTH | {'Content-Type': 'application/json'}, content=body)
    assert response.status_code == 400
    private(response)
    service.set.assert_not_called()


@pytest.mark.parametrize('headers,code', [({'Origin': 'https://evil.example'}, 403),
    ({'Sec-Fetch-Site': 'cross-site'}, 403), ({'Content-Encoding': 'gzip'}, 400),
    ({'Content-Type': 'text/plain'}, 400), ({'Origin': 'x' * 2049}, 400)])
def test_origin_encoding_and_content_type_strict(api, headers, code):
    client, _, service = api
    response = client.put(BASE + f'/{BIG}', content='{"favorite":true}', headers=AUTH | {'Content-Type': 'application/json'} | headers)
    assert response.status_code == code
    private(response)
    service.set.assert_not_called()


@pytest.mark.parametrize('name,value', [('Content-Type', 'application/json'), ('Origin', 'http://testserver'),
    ('Sec-Fetch-Site', 'same-origin'), ('Content-Length', '17'), ('Content-Encoding', '')])
def test_ambiguous_duplicate_headers_rejected(api, name, value):
    client, _, service = api
    headers = [('Authorization', 'Bearer synthetic'), (name, value), (name, value)]
    if name.lower() != 'content-type':
        headers.append(('Content-Type', 'application/json'))
    response = client.put(BASE + f'/{BIG}', content='{"favorite":true}', headers=headers)
    assert response.status_code == 400
    private(response)
    service.set.assert_not_called()


def test_oversized_body_and_query_on_update_rejected(api):
    client, _, service = api
    assert client.put(BASE + f'/{BIG}', content=' ' * 1025, headers=AUTH | {'Content-Type': 'application/json'}).status_code == 413
    assert client.put(BASE + f'/{BIG}?user_id=1', json={'favorite': True}, headers=AUTH).status_code == 400
    service.set.assert_not_called()


@pytest.mark.parametrize('value', ['0', '01', '-1', 'true', '9223372036854775808', '1' * 200])
def test_http_ids_bounded_canonical_decimal(api, value):
    client, _, service = api
    for method in ('get', 'put'):
        response = client.request(method, BASE + '/' + value, json={'favorite': False} if method == 'put' else None, headers=AUTH)
        assert response.status_code == 400
        private(response)
    assert not service.mock_calls


@pytest.mark.parametrize('exception,code', [(GuitarMissing, 404), (ClaimConflict, 409),
    (PermissionError, 403), (ServiceRestricted, 403), (ValueError, 400), (RuntimeError, 503)])
def test_generic_private_service_errors(api, exception, code):
    client, _, service = api
    service.set.side_effect = exception('private internal data')
    response = client.put(BASE + f'/{BIG}', json={'favorite': True}, headers=AUTH)
    assert response.status_code == code and 'private internal data' not in response.text
    private(response)
    if exception is ServiceRestricted:
        assert response.json()['detail'] == {'code': 'service_restricted'}


@pytest.mark.parametrize('failure,code', [(PermissionError, 401), (RuntimeError, 503)])
def test_verifier_errors_sanitized(api, failure, code):
    client, verifier, service = api
    verifier.verify.side_effect = failure('private verifier error')
    response = client.get(BASE, headers=AUTH)
    assert response.status_code == code and 'private verifier error' not in response.text
    private(response)
    assert not service.mock_calls


def test_http_allowlist_filters_future_private_fields_and_media(api):
    client, _, service = api
    row = {'id': str(BIG), 'manufacturer': '<script>alert(1)</script>',
           'current_owner_name': 'SECRET', 'location_region': 'SECRET',
           'photo': 'gs://SECRET', 'author': {'email': 'SECRET'}}
    service.list.return_value = {'items': [row], 'total': '1', 'next_after': None, 'user_id': 'SECRET'}
    response = client.get(BASE, headers=AUTH)
    assert response.status_code == 200
    assert set(response.json()['items'][0]) == {'id', *GUITAR_FIELDS, 'photo'}
    assert response.json()['items'][0]['photo'] is None and 'SECRET' not in response.text
    service.detail.return_value = {'individual_id': str(BIG), 'favorite': True, 'owner': 'SECRET'}
    assert client.get(BASE + f'/{BIG}', headers=AUTH).json() == {'individual_id': str(BIG), 'favorite': True}


@pytest.mark.parametrize('override', [{'total': 1}, {'total': '01'}, {'total': '-1'}, {'total': str(2**63)},
    {'items': [None]}, {'items': [{'id': '1', 'model': {}}]}, {'items': [{'id': '1', 'model': 'x' * 201}]},
    {'next_after': 'javascript:alert(1)'}, {'items': [{'id': BIG}]}])
def test_malformed_service_projection_fails_closed(api, override):
    client, _, service = api
    service.list.return_value.update(override)
    response = client.get(BASE, headers=AUTH)
    assert response.status_code == 503
    private(response)


@pytest.fixture
def fenced_service(monkeypatch):
    events = []
    account = {'id': 7, 'app_user_id': 'canonical'}
    canonical = dict(account)
    state = {'locked': True, 'projection_error': None, 'before': {7, 11}, 'after': {7, 11}}

    class Raw:
        def __init__(self, name):
            self.name = name

        def execute(self, query, parameters=None):
            events.append((self.name, query))
            cursor = Mock()
            cursor.fetchone.return_value = None if state.get('target_missing') and query.startswith('SELECT i.id') else {'locked': state['locked']}
            return cursor

    @contextmanager
    def connect(settings, target):
        events.append(('connect', target))
        yield Raw(target)
        events.append(('closed', target))

    class Operations:
        @contextmanager
        def access(self, kind, actor):
            events.append(('access', kind, actor))
            yield None, {'mode': 'normal'}, account
            events.append(('access_finished', kind))

    class Accounts:
        @contextmanager
        def content_transaction(self, actor, participants):
            events.append(('canonical', actor, participants))
            if state['projection_error'] and (not state.get('target_error') or participants != {7}):
                raise state['projection_error']
            yield Raw('fenced_content'), canonical
            events.append(('canonical_finished',))

    calls = []

    def participants(connection, user, individual=None):
        calls.append(user)
        events.append(('participants', user, individual))
        return state['before' if len(calls) == 1 else 'after']

    monkeypatch.setattr('ygc.cloud_favorites.connect', connect)
    monkeypatch.setattr('ygc.cloud_favorites.PostgresAccounts', lambda _: Accounts())
    service = CloudFavorites(None, Operations())
    monkeypatch.setattr(service, '_participants', participants)
    return service, state, canonical, events


@pytest.mark.parametrize('write', [False, True])
def test_production_guards_remain_until_content_commits(fenced_service, write):
    service, _, _, events = fenced_service
    with service.transaction('canonical', individual=55, write=write) as (con, user):
        assert user == 7 and ('canonical', 'canonical', {7, 11}) in events
        assert events.count(('canonical_finished',)) == 1
        assert not any(row[0] == 'access_finished' for row in events)
        assert sum(row[0] == 'participants' for row in events) == 2
    assert events.count(('canonical_finished',)) == 2
    assert max(i for i, event in enumerate(events) if event == ('canonical_finished',)) < events.index(('access_finished', 'user_write' if write else 'user_read'))
    if write:
        lock = next(i for i, row in enumerate(events) if 'pg_try_advisory_xact_lock(79432190)' in str(row))
        assert lock < events.index(('access', 'user_write', 'canonical'))


def test_production_remove_checks_only_self_mapping_never_target(fenced_service):
    service, _, _, events = fenced_service
    with service.transaction('canonical', individual=55, write=True, inspect_target=False):
        assert ('canonical', 'canonical', {7}) in events
        assert not any(row[0] == 'participants' for row in events)


def test_production_maintenance_rejects_before_account_or_content(fenced_service):
    service, state, _, events = fenced_service
    state['locked'] = False
    with pytest.raises(ClaimConflict):
        with service.transaction('canonical', write=True):
            pytest.fail('Maintenance allowed a write')
    assert not any(row[0] in ('access', 'canonical', 'participants') for row in events)


@pytest.mark.parametrize('failure', ['projection', 'scope', 'mapping'])
def test_production_projection_mapping_and_participant_change_fail_closed(fenced_service, failure):
    service, state, canonical, _ = fenced_service
    expected = {'projection': ValueError, 'scope': ClaimConflict, 'mapping': PermissionError}[failure]
    if failure == 'projection':
        state['projection_error'] = ValueError('Pending projection')
    if failure == 'scope':
        state['after'] = {7, 11, 22}
    if failure == 'mapping':
        canonical['id'] = 17
    with pytest.raises(expected):
        with service.transaction('canonical'):
            pytest.fail('Failed fence exposed content')


@pytest.mark.parametrize('write', [False, True])
def test_hidden_or_unknown_targets_are_missing_before_participant_discovery(fenced_service, write):
    service, state, _, events = fenced_service
    state['target_missing'] = True
    state['projection_error'], state['target_error'] = ValueError('Unknown author'), True
    with pytest.raises(GuitarMissing):
        with service.transaction('canonical', individual=55, write=write):
            pytest.fail('Hidden target escaped')
    assert not any(event[0] == 'participants' for event in events)


@pytest.mark.parametrize('write', [False, True])
def test_visible_target_with_stale_or_missing_author_is_indistinguishably_missing(fenced_service, write):
    service, state, _, events = fenced_service
    state['projection_error'], state['target_error'] = ValueError('Target author pending'), True
    with pytest.raises(GuitarMissing):
        with service.transaction('canonical', individual=55, write=write):
            pytest.fail('Unavailable target author exposed target')
    assert ('canonical', 'canonical', {7}) in events
    assert ('canonical', 'canonical', {7, 11}) in events


def test_participant_scope_follows_only_self_favorites_or_selected_target(workflow):
    repo, service, a, b, author, ids, _ = workflow
    service.set(a, ids[0], favorite=True)
    with repo.connect() as con:
        con.execute('UPDATE claims SET author_user_id=? WHERE individual_id=?', (b, ids[1]))
        con.execute("UPDATE claims SET status='inactive' WHERE individual_id=?", (ids[0],))
        assert service._participants(SQLiteSQL(con), a) == {a, author}
        assert service._participants(SQLiteSQL(con), a, ids[1]) == {a, b}
