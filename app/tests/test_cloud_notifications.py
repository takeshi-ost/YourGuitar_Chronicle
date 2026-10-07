"""Private inbox boundary and business tests. Synthetic SQLite fixtures only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ygc.claim_revision import ClaimConflict
from ygc.cloud_notification_routes import notification_router
from ygc.cloud_notifications import (CloudNotifications, NotificationMissing, item_projection,
                                      result_projection)
from ygc.db.postgres_operations import ServiceRestricted
from ygc.db.postgres_ownership import BoundRepository
from ygc.db.repository import Repository
from ygc.identity_platform import VerifiedIdentity

BASE = '/api/auth/notifications'
AUTH = {'Authorization': 'Bearer synthetic'}
BIG = 9007199254740993


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    repo = Repository(tmp_path / 'notifications.db')
    repo.init_db()
    owner, author, outsider = [repo.create_user(name) for name in ('Owner', 'Author', 'Outsider')]
    individual, _, listing, _ = repo.create_initial_listing_claim(owner, manufacturer='Fender',
        model='Stratocaster', serial_number='NOTIFICATIONS', occurred_at='2020-01-01',
        media_storage_path='private/base.jpg')
    claim = repo.create_incident_claim(author, individual, incident_kind='damage',
        occurred_at='2021-02-03', detail='Private incident.')
    service = CloudNotifications(None, None)
    state = {'mode': 'normal', 'maintenance': False}

    @contextmanager
    def transaction(actor, *, write=False):
        with repo.connect() as con:
            if write:
                con.execute('BEGIN IMMEDIATE')
            if write and state['maintenance']:
                raise ClaimConflict()
            if state['mode'] in ('offline', 'admin_only') or (write and state['mode'] == 'read_only'):
                raise ServiceRestricted()
            if not con.execute("SELECT 1 FROM users WHERE id=? AND ban_status<>'ban' AND account_type<>'source'", (actor,)).fetchone():
                raise PermissionError()
            yield BoundRepository(con), actor, state['mode'] != 'read_only'

    monkeypatch.setattr(service, 'transaction', transaction)
    return repo, service, owner, author, outsider, individual, claim, state


def add(workflow, **kwargs):
    repo, _, owner, author, _, individual, claim, _ = workflow
    data = {'recipient_user_id': owner, 'actor_user_id': author, 'notification_type': 'claim_added',
            'individual_id': individual, 'claim_id': claim, 'title': 'New Incident Claim',
            'body': 'Author added an Incident Claim.', 'created_at': '2026-01-01T00:00:00+00:00'} | kwargs
    with repo.connect() as con:
        result = con.execute('INSERT INTO notifications (' + ','.join(data) + ') VALUES (' +
                             ','.join('?' for _ in data) + ')', tuple(data.values()))
        return result.lastrowid


def notification(repo, number):
    with repo.connect() as con:
        return dict(con.execute('SELECT * FROM notifications WHERE id=?', (number,)).fetchone())


def protected_state(repo):
    with repo.connect() as con:
        tables = [row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN ('notifications','sqlite_sequence') ORDER BY name")]
        return {table: [tuple(row) for row in con.execute(f'SELECT * FROM "{table}" ORDER BY rowid')]
                for table in tables}


def test_recipient_isolation_null_actor_allowlist_and_bigint_pagination(workflow):
    repo, service, owner, author, outsider, _, claim, _ = workflow
    oldest = add(workflow, id=BIG, body='<img src=x onerror=alert(1)>', created_at='2026-12-01')
    latest = add(workflow, id=BIG + 1, actor_user_id=None, body=None, created_at='2026-01-01')
    add(workflow, recipient_user_id=outsider)
    page = service.list(owner, limit=1)
    assert page['next_after'] == str(latest)
    assert page['unread_count'] == '2' and page['can_write'] is True
    assert page['items'][0]['id'] == str(latest)
    assert page['items'][0]['actor'] is None and page['items'][0]['body'] is None
    next_page = service.list(owner, after=int(page['next_after']), limit=1)
    assert next_page['next_after'] is None and next_page['items'][0]['id'] == str(oldest)
    assert next_page['items'][0]['body'] == '<img src=x onerror=alert(1)>'
    assert next_page['items'][0]['actor'] == {'id': str(author), 'display_name': 'Author'}
    assert set(next_page['items'][0]) == {'id', 'notification_type', 'title', 'body', 'created_at',
                                       'is_read', 'read_at', 'actor', 'destination'}
    assert set(service.list(author)['items']) == set()
    with pytest.raises(NotificationMissing):
        service.mark_read(outsider, oldest)
    assert notification(repo, oldest)['is_read'] == 0


@pytest.mark.parametrize('target', ['actor', 'author'])
@pytest.mark.parametrize('ban', ['ban', 'silent_ban'])
def test_banned_actor_or_author_hidden_from_list_count_and_both_updates(workflow, target, ban):
    repo, service, owner, author, outsider, _, _, _ = workflow
    hidden = add(workflow, actor_user_id=outsider if target == 'author' else author)
    visible = add(workflow, actor_user_id=None, claim_id=None, notification_type='ownership_dispute')
    with repo.connect() as con:
        con.execute('UPDATE users SET ban_status=? WHERE id=?', (ban, author))
    assert [row['id'] for row in service.list(owner)['items']] == [str(visible)]
    assert service.list(owner)['unread_count'] == service.unread_count(owner)['unread_count'] == '1'
    with pytest.raises(NotificationMissing):
        service.mark_read(owner, hidden)
    assert service.mark_all_read(owner) == {'marked_count': '1', 'unread_count': '0'}
    assert notification(repo, hidden)['read_at'] is None
    assert notification(repo, hidden)['is_read'] == 0
    assert notification(repo, visible)['is_read'] == 1
    with repo.connect() as con:
        con.execute("UPDATE users SET ban_status='normal' WHERE id=?", (author,))
    assert service.unread_count(owner)['unread_count'] == '1'


def test_inactive_claim_visibility_exactly_matches_local_repository(workflow):
    repo, service, owner, _, _, _, claim, _ = workflow
    hidden = add(workflow)
    visible = add(workflow, claim_id=None)
    with repo.connect() as con:
        con.execute("UPDATE claims SET status='inactive' WHERE id=?", (claim,))
    assert {row['id'] for row in repo.list_notifications(owner)} == {visible}
    assert {row['id'] for row in service.list(owner)['items']} == {str(visible)}
    assert service.unread_count(owner)['unread_count'] == str(repo.unread_notification_count(owner)) == '1'
    with pytest.raises(NotificationMissing):
        service.mark_read(owner, hidden)
    assert service.mark_all_read(owner)['marked_count'] == '1'
    assert notification(repo, hidden)['read_at'] is None


def test_first_read_preserved_repeated_single_read_all_and_concurrent_retries(workflow, monkeypatch):
    repo, service, owner, _, _, _, _, _ = workflow
    first, second = add(workflow), add(workflow)
    monkeypatch.setattr('ygc.cloud_notifications.utcnow', lambda: '2026-01-01T00:00:01+00:00')
    result = service.mark_read(owner, first)
    assert result == {'id': str(first), 'is_read': True, 'read_at': '2026-01-01T00:00:01+00:00', 'unread_count': '1'}
    monkeypatch.setattr('ygc.cloud_notifications.utcnow', lambda: '2026-01-01T00:00:02+00:00')
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: service.mark_read(owner, first), range(4)))
    assert all(item['read_at'] == result['read_at'] for item in results)
    assert service.mark_all_read(owner) == {'marked_count': '1', 'unread_count': '0'}
    assert notification(repo, first)['read_at'] == result['read_at']
    assert notification(repo, second)['read_at'] == '2026-01-01T00:00:02+00:00'
    assert service.mark_all_read(owner) == {'marked_count': '0', 'unread_count': '0'}


def test_reading_decline_dispute_transfer_never_changes_business_tables(workflow):
    repo, service, owner, author, outsider, individual, claim, _ = workflow
    with repo.connect() as con:
        con.execute('INSERT INTO ownership_declines(claim_id,owner_id,reason,created_at) VALUES (?,?,?,?)',
                    (claim, owner, 'Recorded decline', '2026-01-01'))
    transfer = repo.create_transfer(owner, individual, outsider)
    decline = add(workflow, notification_type='ownership_decline')
    add(workflow, notification_type='ownership_dispute', claim_id=None)
    before = protected_state(repo)
    service.list(owner)
    service.unread_count(owner)
    service.mark_read(owner, decline)
    service.mark_all_read(owner)
    service.mark_all_read(outsider)
    assert protected_state(repo) == before
    with repo.connect() as con:
        assert con.execute('SELECT acknowledged_at FROM ownership_declines WHERE claim_id=?', (claim,)).fetchone()[0] is None
        assert con.execute('SELECT state FROM claim_transfers WHERE claim_id=?', (transfer,)).fetchone()[0] == 'pending'


def test_destinations_recheck_owner_and_transfer_participant_and_unsupported_is_text(workflow):
    repo, service, owner, author, outsider, individual, claim, _ = workflow
    note = add(workflow)
    assert service.list(owner)['items'][0]['destination'] == {'kind': 'owner', 'individual_id': str(individual), 'claim_id': str(claim)}
    add(workflow, notification_type='ownership_dispute', claim_id=None)
    add(workflow, notification_type='unknown_future_type')
    assert all(item['destination'] is None for item in service.list(owner)['items'] if item['id'] != str(note))
    transfer = repo.create_transfer(owner, individual, outsider)
    assert service.list(outsider)['items'][0]['destination'] == {'kind': 'transfer', 'claim_id': str(transfer)}
    forged = add(workflow, recipient_user_id=author, claim_id=transfer, notification_type='transfer_request')
    assert next(item for item in service.list(author)['items'] if item['id'] == str(forged))['destination'] is None
    repo.resolve_transfer(transfer, outsider, 'accept')
    history = service.list(owner)['items']
    assert next(item for item in history if item['id'] == str(note))['destination'] is None
    result = next(item for item in history if item['notification_type'] == 'transfer_result')
    assert result['destination'] == {'kind': 'transfer', 'claim_id': str(transfer)}


def test_participants_include_hidden_history_but_never_other_recipients(workflow):
    repo, service, owner, author, outsider, _, _, _ = workflow
    add(workflow)
    add(workflow, recipient_user_id=outsider, actor_user_id=outsider, claim_id=None, individual_id=None)
    with repo.connect() as con:
        con.execute("UPDATE users SET ban_status='ban' WHERE id=?", (author,))
        assert service._participants(con, owner) == {owner, author}


def test_dispute_destinations_require_current_participation_and_unambiguous_case(workflow):
    repo, service, owner, author, outsider, individual, claim, _ = workflow
    with repo.connect() as con:
        con.execute("UPDATE claims SET claim_type='ownership',ownership_kind='acquire',verification_status='negative' WHERE id=?", (claim,))
        con.execute('''INSERT INTO acquire_applications(revision,applicant_id,individual_id,original_individual_id,
            serial,challenge,expires_at,created_at,prompt_version,status,claim_id)
            VALUES ('synthetic',?,?,?,'SERIAL','challenge',0,'2026-01-01','synthetic','accepted',?)''',
            (author, individual, individual, claim))
    decline = add(workflow, recipient_user_id=author, actor_user_id=owner, notification_type='ownership_decline')
    assert service.list(author)['items'][0]['destination'] == {'kind': 'dispute_option', 'claim_id': str(claim)}
    forged = add(workflow, recipient_user_id=outsider, actor_user_id=owner, notification_type='ownership_decline')
    assert next(row for row in service.list(outsider)['items'] if row['id'] == str(forged))['destination'] is None
    with repo.connect() as con:
        case = con.execute('''INSERT INTO ownership_disputes(individual_id,owner_id,locked_owner_id,status,
            created_at,updated_at) VALUES (?,?,?,'resolved','2026-01-01','2026-01-01')''',
            (individual, owner, owner)).lastrowid
        con.execute('INSERT INTO ownership_dispute_claims VALUES (?,?,?)', (case, claim, author))
    generic = add(workflow, recipient_user_id=author, actor_user_id=owner, claim_id=None, notification_type='ownership_dispute')
    rows = service.list(author)['items']
    assert all(row['destination'] == {'kind': 'dispute', 'case_id': str(case)} for row in rows if row['id'] in {str(decline), str(generic)})
    with repo.connect() as con:
        con.execute('''INSERT INTO ownership_disputes(individual_id,owner_id,locked_owner_id,status,
            created_at,updated_at) VALUES (?,?,?,'resolved','2026-02-01','2026-02-01')''',
            (individual, author, author))
    rows = service.list(author)['items']
    assert next(row for row in rows if row['id'] == str(generic))['destination'] is None
    assert next(row for row in rows if row['id'] == str(decline))['destination'] == {'kind': 'dispute', 'case_id': str(case)}
    with repo.connect() as con:
        con.execute("UPDATE users SET ban_status='silent_ban' WHERE id=?", (author,))
    assert all(row['destination'] is None for row in service.list(author)['items'])


def test_dispute_notification_fence_includes_retained_original_parties(workflow):
    repo, service, owner, author, outsider, individual, claim, _ = workflow
    add(workflow, recipient_user_id=owner, actor_user_id=None, claim_id=None, notification_type='ownership_dispute')
    with repo.connect() as con:
        case = con.execute('''INSERT INTO ownership_disputes(individual_id,owner_id,locked_owner_id,winner_id,status,
            created_at,updated_at) VALUES (?,?,?,?,'resolved','2026-01-01','2026-01-01')''',
            (individual, outsider, owner, author)).lastrowid
        con.execute('INSERT INTO ownership_dispute_claims VALUES (?,?,?)', (case, claim, author))
        assert service._participants(con, owner) == {owner, author, outsider}


@pytest.mark.parametrize('kwargs', [{'after': -1}, {'after': 2**63}, {'after': False}, {'after': '1'},
                                   {'limit': 0}, {'limit': 51}, {'limit': True}, {'limit': '1'}])
def test_service_page_input_bounds(workflow, kwargs):
    _, service, owner, *_ = workflow
    with pytest.raises(ValueError):
        service.list(owner, **kwargs)


@pytest.mark.parametrize('value', [0, -1, 2**63, True, '1', None])
def test_service_notification_input_bounds(workflow, value):
    _, service, owner, *_ = workflow
    with pytest.raises(ValueError):
        service.mark_read(owner, value)


@pytest.mark.parametrize('mode', ['read_only', 'offline', 'admin_only'])
def test_modes_do_not_read_mark_or_disclose_wrongly(workflow, mode):
    repo, service, owner, _, _, _, _, state = workflow
    number = add(workflow)
    state['mode'] = mode
    if mode == 'read_only':
        assert service.list(owner)['can_write'] is False
        assert service.unread_count(owner)['can_write'] is False
    else:
        with pytest.raises(ServiceRestricted):
            service.list(owner)
        with pytest.raises(ServiceRestricted):
            service.unread_count(owner)
    with pytest.raises(ServiceRestricted):
        service.mark_read(owner, number)
    with pytest.raises(ServiceRestricted):
        service.mark_all_read(owner)
    assert notification(repo, number)['is_read'] == 0


def test_maintenance_blocks_read_mutations(workflow):
    repo, service, owner, _, _, _, _, state = workflow
    number = add(workflow)
    state['maintenance'] = True
    assert service.list(owner)['items']
    with pytest.raises(ClaimConflict):
        service.mark_read(owner, number)
    with pytest.raises(ClaimConflict):
        service.mark_all_read(owner)
    assert notification(repo, number)['read_at'] is None


@pytest.mark.parametrize('field,value', [('title', 'x' * 201), ('body', 'x' * 8001),
    ('created_at', 'x' * 41), ('notification_type', 'x' * 65), ('body', '\x00'), ('title', '\n')])
def test_stored_text_is_bounded_without_truncation(workflow, field, value):
    _, service, owner, *_ = workflow
    add(workflow, **{field: value})
    with pytest.raises(RuntimeError):
        service.list(owner)


@pytest.fixture
def api():
    verifier, service = Mock(), Mock()
    verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', '', True)
    verifier.accounts.resolve_identity.return_value = {'app_user_id': 'canonical', 'id': 999}
    service.list.return_value = {'items': [], 'next_after': None, 'unread_count': '0', 'can_write': True}
    service.unread_count.return_value = {'unread_count': '0', 'can_write': True}
    service.mark_read.return_value = {'id': str(BIG), 'is_read': True, 'read_at': '2026-01-01', 'unread_count': '0'}
    service.mark_all_read.return_value = {'marked_count': '0', 'unread_count': '0'}
    app = FastAPI()
    app.include_router(notification_router(verifier, service))
    with TestClient(app) as client:
        yield client, verifier, service


def private(response):
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.headers['vary'] == 'Authorization'
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_routes_canonical_identity_never_cookie_or_caller_recipient(api):
    client, verifier, service = api
    response = client.get(BASE, headers=AUTH)
    assert response.status_code == 200
    private(response)
    service.list.assert_called_once_with('canonical', after=0, limit=25)
    verifier.accounts.resolve_identity.assert_called_once_with(issuer='issuer', subject='subject', tenant='')
    assert client.get(BASE + '/unread-count', headers=AUTH).status_code == 200
    service.unread_count.assert_called_once_with('canonical')
    response = client.post(BASE + f'/{BIG}/read', json={}, headers=AUTH)
    assert response.status_code == 200 and response.json()['id'] == str(BIG)
    service.mark_read.assert_called_once_with('canonical', BIG)
    response = client.post(BASE + '/read-all', json={}, headers=AUTH)
    assert response.status_code == 200
    service.mark_all_read.assert_called_once_with('canonical')


@pytest.mark.parametrize('path', ['', '/unread-count', f'/{BIG}/read', '/read-all'])
def test_all_routes_need_one_verified_bearer_with_private_failures(api, path):
    client, verifier, service = api
    method = client.post if path.endswith('read') or path.endswith('read-all') else client.get
    response = method(BASE + path, headers={'Cookie': 'user_id=999; session=secret'})
    assert response.status_code == 401
    private(response)
    verifier.verify.assert_not_called()
    response = method(BASE + path, headers=[('Authorization', 'Bearer first'), ('Authorization', 'Bearer second')])
    assert response.status_code == 401
    private(response)
    verifier.verify.assert_not_called()
    verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', '', False)
    response = method(BASE + path, headers=AUTH)
    assert response.status_code == 403
    private(response)
    verifier.accounts.resolve_identity.assert_not_called()


@pytest.mark.parametrize('query', ['?user_id=1', '?recipient_user_id=1', '?limit=51', '?limit=0',
    '?limit=true', '?limit=1&limit=2', '?after=0', '?after=-1', '?after=9223372036854775808',
    '?after=١', '?after=1&after=2', '?after=' + '1' * 100])
def test_route_rejects_unknown_repeated_or_unbounded_pagination(api, query):
    client, _, service = api
    response = client.get(BASE + query, headers=AUTH)
    assert response.status_code == 400
    private(response)
    service.list.assert_not_called()


def test_route_valid_bigint_cursor_and_count_query_rejection(api):
    client, _, service = api
    assert client.get(BASE + f'?after={BIG}&limit=50', headers=AUTH).status_code == 200
    service.list.assert_called_once_with('canonical', after=BIG, limit=50)
    assert client.get(BASE + '/unread-count?after=1', headers=AUTH).status_code == 400
    service.unread_count.assert_not_called()
    assert client.request('GET', BASE, headers=AUTH, content='{}').status_code == 400


@pytest.mark.parametrize('body', ['[]', 'null', 'true', '42', '{', '{"recipient_user_id":1}',
    '{"claim_id":1}', '{"is_read":true}', '{"x":1,"x":2}', '{"actor":"a"}'])
@pytest.mark.parametrize('path', [f'/{BIG}/read', '/read-all'])
def test_mutations_accept_only_empty_json_no_identity_or_business_inputs(api, body, path):
    client, _, service = api
    response = client.post(BASE + path, headers=AUTH | {'Content-Type': 'application/json'}, content=body)
    assert response.status_code == 400
    private(response)
    service.mark_read.assert_not_called()
    service.mark_all_read.assert_not_called()


@pytest.mark.parametrize('headers,code', [({'Origin': 'https://evil.example'}, 403),
    ({'Sec-Fetch-Site': 'cross-site'}, 403), ({'Content-Encoding': 'gzip'}, 400),
    ({'Content-Type': 'text/plain'}, 400)])
def test_cross_origin_encoded_or_non_json_writes_rejected(api, headers, code):
    client, _, service = api
    response = client.post(BASE + '/read-all', content='{}', headers=AUTH | {'Content-Type': 'application/json'} | headers)
    assert response.status_code == code
    private(response)
    service.mark_all_read.assert_not_called()


def test_post_body_bounded_and_query_identity_rejected(api):
    client, _, service = api
    response = client.post(BASE + '/read-all', content=' ' * 1025, headers=AUTH | {'Content-Type': 'application/json'})
    assert response.status_code == 413
    private(response)
    assert client.post(BASE + '/read-all?user_id=1', json={}, headers=AUTH).status_code == 400
    service.mark_all_read.assert_not_called()


@pytest.mark.parametrize('value', ['0', '-1', 'true', '9223372036854775808', '1' * 200])
def test_http_notification_ids_are_bounded(api, value):
    client, _, service = api
    response = client.post(BASE + '/' + value + '/read', json={}, headers=AUTH)
    assert response.status_code == 400
    private(response)
    service.mark_read.assert_not_called()


@pytest.mark.parametrize('exception,code', [(NotificationMissing, 404), (ClaimConflict, 409),
    (PermissionError, 403), (ServiceRestricted, 403), (ValueError, 400), (RuntimeError, 503)])
def test_sanitized_errors_always_private(api, exception, code):
    client, _, service = api
    service.mark_read.side_effect = exception('private internal data')
    response = client.post(BASE + f'/{BIG}/read', json={}, headers=AUTH)
    assert response.status_code == code and 'private internal data' not in response.text
    private(response)
    if exception is ServiceRestricted:
        assert response.json()['detail'] == {'code': 'service_restricted'}


@pytest.mark.parametrize('failure,code', [(PermissionError, 401), (RuntimeError, 503)])
def test_verifier_failures_sanitized(api, failure, code):
    client, verifier, service = api
    verifier.verify.side_effect = failure('private verifier error')
    response = client.get(BASE, headers=AUTH)
    assert response.status_code == code and 'private verifier error' not in response.text
    private(response)
    service.list.assert_not_called()


def test_http_response_allowlist_drops_private_service_additions(api):
    client, _, service = api
    row = {'id': str(BIG), 'notification_type': 'claim_added', 'title': '<script>alert(1)</script>',
           'body': '<img src=x onerror=alert(1)>', 'created_at': '2026-01-01', 'is_read': False,
           'read_at': None, 'actor': {'id': '2', 'display_name': 'Author', 'email': 'secret@example.com'},
           'destination': {'kind': 'transfer', 'claim_id': '3', 'url': 'https://evil.example'},
           'recipient_user_id': '99', 'report': 'private report', 'object_key': 'private/key'}
    service.list.return_value = {'items': [row], 'unread_count': '1', 'can_write': True,
                                 'next_after': None, 'accounts': 'private account rows'}
    response = client.get(BASE, headers=AUTH)
    assert response.status_code == 200
    assert response.json()['items'][0] == item_projection(row)
    assert response.json()['items'][0]['body'] == row['body']
    for value in ('secret@example.com', 'https://evil.example', 'recipient_user_id', 'private report', 'private/key', 'private account rows'):
        assert value not in response.text


@pytest.mark.parametrize('override', [{'unread_count': 1}, {'unread_count': '01'}, {'unread_count': '-1'},
    {'unread_count': str(2**63)}, {'can_write': 1}, {'items': [None]}, {'next_after': 'javascript:alert(1)'}])
def test_malformed_service_outputs_fail_closed(api, override):
    client, _, service = api
    service.list.return_value.update(override)
    response = client.get(BASE, headers=AUTH)
    assert response.status_code == 503
    private(response)


@pytest.fixture
def fenced_service(monkeypatch):
    """Exercise the actual service context manager, replacing only PG I/O."""
    events = []
    account = {'id': 7, 'app_user_id': 'canonical'}
    canonical = dict(account)
    state = {'mode': 'normal', 'locked': True, 'projection_error': None,
             'before': {7, 11}, 'after': {7, 11}}

    class Raw:
        def __init__(self, name):
            self.name = name

        def execute(self, query, parameters=None):
            events.append((self.name, query))
            cursor = Mock()
            cursor.fetchone.return_value = {'locked': state['locked']}
            return cursor

    @contextmanager
    def connect(settings, target):
        events.append(('connect', target))
        try:
            yield Raw(target)
        finally:
            events.append(('closed', target))

    class Operations:
        @contextmanager
        def access(self, kind, actor):
            events.append(('access', kind, actor))
            yield None, {'mode': state['mode']}, account
            events.append(('access_finished', kind))

    class Accounts:
        @contextmanager
        def content_transaction(self, actor, participants):
            events.append(('canonical', actor, participants))
            if state['projection_error']:
                raise state['projection_error']
            try:
                yield Raw('fenced_content'), canonical
            finally:
                events.append(('canonical_finished',))

    calls = []

    def participants(connection, user):
        calls.append(user)
        events.append(('participants', user))
        return state['before' if len(calls) == 1 else 'after']

    monkeypatch.setattr('ygc.cloud_notifications.connect', connect)
    monkeypatch.setattr('ygc.cloud_notifications.PostgresAccounts', lambda _: Accounts())
    service = CloudNotifications(None, Operations())
    monkeypatch.setattr(service, '_participants', participants)
    return service, state, canonical, events


@pytest.mark.parametrize('write', [False, True])
def test_production_transaction_retains_canonical_and_mode_fences_through_use(fenced_service, write):
    service, state, canonical, events = fenced_service
    state['mode'] = 'normal' if write else 'read_only'
    with service.transaction('canonical', write=write) as (repo, user, can_write):
        assert user == 7 and can_write is write
        assert ('canonical', 'canonical', {7, 11}) in events
        assert ('canonical_finished',) not in events
        assert ('access_finished', 'user_write' if write else 'user_read') not in events
        assert ('access', 'user_write' if write else 'user_read', 'canonical') in events
        assert sum(event[0] == 'participants' for event in events) == 2
        repo.connection.execute('SELECT synthetic_safe_read')
    access_index = next(i for i, event in enumerate(events) if event[0] == 'access')
    canonical_index = next(i for i, event in enumerate(events) if event[0] == 'canonical')
    assert access_index < canonical_index
    if write:
        lock_index = next(i for i, event in enumerate(events) if 'pg_try_advisory_xact_lock(79432190)' in str(event))
        assert lock_index < access_index
    assert events.index(('canonical_finished',)) < events.index(('access_finished', 'user_write' if write else 'user_read'))


def test_production_maintenance_failure_happens_before_account_and_content(fenced_service):
    service, state, _, events = fenced_service
    state['locked'] = False
    with pytest.raises(ClaimConflict):
        with service.transaction('canonical', write=True):
            pytest.fail('Maintenance allowed a notification mutation.')
    assert not any(event[0] in ('access', 'participants', 'canonical') for event in events)


def test_production_pending_or_inconsistent_projection_cannot_expose_actor(fenced_service):
    service, state, _, events = fenced_service
    state['projection_error'] = ValueError('Participant projection is pending or conflicts with registry.')
    with pytest.raises(ValueError):
        with service.transaction('canonical'):
            pytest.fail('Projection failure exposed a notification.')
    assert sum(event[0] == 'participants' for event in events) == 1
    assert not any(event[0] == 'fenced_content' for event in events)


def test_production_participant_change_fails_closed_before_projection_or_write(fenced_service):
    service, state, _, events = fenced_service
    state['after'] = {7, 11, 22}
    with pytest.raises(ClaimConflict):
        with service.transaction('canonical', write=True):
            pytest.fail('Changed scope escaped the canonical lock.')
    assert ('canonical', 'canonical', {7, 11}) in events
    assert sum(event[0] == 'participants' for event in events) == 2


def test_production_canonical_recipient_mismatch_fails_closed(fenced_service):
    service, _, canonical, events = fenced_service
    canonical['id'] = 17
    with pytest.raises(PermissionError):
        with service.transaction('canonical'):
            pytest.fail('A remapped recipient escaped the fence.')
    assert sum(event[0] == 'participants' for event in events) == 1
