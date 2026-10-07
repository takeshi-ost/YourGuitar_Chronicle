"""Portable business tests; PostgreSQL locks are covered by the PG suite."""
from contextlib import contextmanager
import json
import sqlite3
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ygc.claim_dates import viewer_timezone
from ygc.claim_revision import ClaimConflict
from ygc.cloud_claims import ClaimConnection, CloudClaims, payload
from ygc.cloud_claim_routes import claim_router
from ygc.cloud_guitars import GuitarMissing
from ygc.cloud_owner import CloudOwner
from ygc.db.postgres_ownership import BoundRepository
from ygc.db.repository import Repository
from ygc.identity_platform import VerifiedIdentity

SPEC = dict(claim_type='specification', specification_kind='specification',
    items=[dict(field_name='neck', value_text='Maple'), dict(field_name='pickups', value_text='Two single coils')],
    body='Private notes', occurred_at='2020-02-01')
INCIDENT = dict(claim_type='incident', incident_kind='damage', body='Body edge chipped.', occurred_at='2020-02-02')


class SQLiteConnection:
    def __init__(self, con):
        self.connection = con

    def execute(self, query, parameters=()):
        return self.connection.execute(query.removesuffix(' FOR UPDATE'), parameters)

    def executemany(self, query, parameters):
        return self.connection.executemany(query, parameters)


@pytest.fixture
def services(tmp_path, monkeypatch):
    repo = Repository(tmp_path / 'claims.db')
    repo.init_db()
    a, b, c = (repo.create_user(name) for name in ('Owner', 'Contributor', 'Other'))
    guitar, *_ = repo.create_initial_listing_claim(a, manufacturer='Fixture', model='Guitar',
        serial_number='CLAIM-001', media_storage_path='private/fixture.jpg', occurred_at='2020-01-01')
    service, owner = CloudClaims(None, None), CloudOwner(None, None)

    @contextmanager
    def transaction(actor, individual, *, write=False):
        assert individual == guitar
        with repo.connect() as con:
            if write:
                con.execute('BEGIN IMMEDIATE')
            yield BoundRepository(SQLiteConnection(con)), actor, True

    @contextmanager
    def owner_transaction(actor, individual, *, write=False):
        with transaction(actor, individual, write=write) as (bound, user, _):
            yield bound, user

    monkeypatch.setattr(service, 'transaction', transaction)
    monkeypatch.setattr(owner, 'transaction', owner_transaction)
    return repo, service, owner, a, b, c, guitar


def test_create_initial_status_full_typed_content_and_private_own_list(services):
    repo, service, owner, a, b, c, guitar = services
    mine = service.create(a, guitar, SPEC)['claim']
    theirs = service.create(b, guitar, SPEC | {'specification_kind': 'repair'})['claim']
    incident = service.create(b, guitar, INCIDENT)['claim']
    assert mine['verification_status'] == 'positive'
    assert theirs['verification_status'] == incident['verification_status'] == 'unverified'
    assert theirs['spec_items'] == SPEC['items'] and theirs['body'] == SPEC['body']
    assert theirs['field_name'] is None and theirs['value_text'] is None
    assert incident['incident_kind'] == 'damage'
    assert {'created_at', 'updated_at', 'revision'} <= theirs.keys()
    page = service.list(b, guitar, limit=1)
    assert page['can_write'] is True and page['items'] == [incident]
    assert page['next_after'] == incident['id']
    assert service.list(b, guitar, after=int(page['next_after']))['items'] == [theirs]
    assert service.list(c, guitar)['items'] == []
    assert set(page['individual']) == {'id', 'manufacturer', 'model', 'finish', 'year', 'serial_number'}
    assert not ({'author_user_id', 'author_name', 'evidence', 'storage_path'} & set(theirs))
    with repo.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM notifications WHERE notification_type='claim_added'").fetchone()[0] == 2
    assert {row['id'] for row in owner.pending(a, guitar)['items']} == {theirs['id'], incident['id']}
    assert owner.pending(b, guitar)['items'] == []


def test_edit_and_owner_revision_conflicts_keep_complete_content(services):
    repo, service, owner, a, b, c, guitar = services
    original = service.create(b, guitar, SPEC)['claim']
    pending = owner.pending(a, guitar)['items'][0]
    changed = service.edit(b, guitar, int(original['id']), SPEC | {
        'revision': original['revision'], 'items': [{'field_name': 'bridge', 'value_text': 'Brass'}],
        'specification_kind': 'repair', 'body': 'Replaced bridge'})['claim']
    assert changed['spec_items'] == [{'field_name': 'bridge', 'value_text': 'Brass'}]
    assert changed['verification_status'] == 'unverified'
    with pytest.raises(ClaimConflict):
        service.edit(b, guitar, int(original['id']), SPEC | {'revision': original['revision']})
    with pytest.raises(ClaimConflict):
        owner.respond(a, guitar, int(original['id']), dict(stance='positive', revision=pending['revision']))
    current = owner.pending(a, guitar)['items'][0]
    owner.respond(a, guitar, int(original['id']), dict(stance='positive', revision=current['revision']))
    with pytest.raises(ClaimConflict):
        service.edit(b, guitar, int(original['id']), SPEC | {'revision': changed['revision']})
    approved = service.list(b, guitar)['items'][0]
    edited = service.edit(b, guitar, int(original['id']), SPEC | {'revision': approved['revision']})['claim']
    # Migration preserves the local editor's existing semantics deliberately.
    assert edited['verification_status'] == 'positive' and edited['spec_items'] == SPEC['items']


def test_equal_timestamps_still_invalidate_typed_content_confirmation(services, monkeypatch):
    repo, service, owner, a, b, c, guitar = services
    monkeypatch.setattr('ygc.db.repository.utcnow', lambda: '2020-02-03T12:00:00+00:00')
    original = service.create(b, guitar, SPEC)['claim']
    pending = owner.pending(a, guitar)['items'][0]
    changed = service.edit(b, guitar, int(original['id']), SPEC | {'revision': original['revision'],
        'items': [dict(field_name='neck', value_text='Rosewood')]})['claim']
    assert changed['updated_at'] == original['updated_at']
    assert changed['revision'] != original['revision']
    with pytest.raises(ClaimConflict):
        owner.respond(a, guitar, int(original['id']), dict(stance='positive', revision=pending['revision']))


def test_author_only_edit_and_deactivate_tombstone(services):
    repo, service, owner, a, b, c, guitar = services
    original = service.create(b, guitar, INCIDENT)['claim']
    claim = int(original['id'])
    for actor in (a, c):
        with pytest.raises(GuitarMissing):
            service.edit(actor, guitar, claim, INCIDENT | {'revision': original['revision']})
        with pytest.raises(GuitarMissing):
            service.deactivate(actor, guitar, claim, {'revision': original['revision']})
    for changed in (INCIDENT | {'incident_kind': 'theft'}, SPEC):
        with pytest.raises(ValueError):
            service.edit(b, guitar, claim, changed | {'revision': original['revision']})
    updated = service.edit(b, guitar, claim, INCIDENT | {'body': 'Updated detail', 'revision': original['revision']})['claim']
    pending = owner.pending(a, guitar)['items'][0]
    inactive = service.deactivate(b, guitar, claim, {'revision': updated['revision']})['claim']
    assert inactive['status'] == 'inactive' and inactive['body'] == 'Updated detail'
    assert service.list(b, guitar)['items'] == [inactive]
    assert owner.pending(a, guitar)['items'] == []
    for action in (lambda: service.edit(b, guitar, claim, INCIDENT | {'revision': inactive['revision']}),
        lambda: service.deactivate(b, guitar, claim, {'revision': inactive['revision']}),
        lambda: owner.respond(a, guitar, claim, dict(stance='positive', revision=pending['revision']))):
        with pytest.raises(ClaimConflict):
            action()
    assert repo.get_individual(guitar)[0]['current_owner_user_id'] == a


def test_listing_never_uses_generic_editor(services):
    repo, service, owner, a, b, c, guitar = services
    with repo.connect() as con:
        listing = con.execute("SELECT id FROM claims WHERE claim_type='listing'").fetchone()[0]
    with pytest.raises(GuitarMissing):
        service.edit(a, guitar, listing, SPEC | {'revision': 'a' * 64})
    with pytest.raises(GuitarMissing):
        service.deactivate(a, guitar, listing, {'revision': 'a' * 64})
    assert service.list(a, guitar)['items'] == []


def test_notification_failure_rolls_back_claim_items_and_snapshot(services):
    repo, service, owner, a, b, c, guitar = services
    with repo.connect() as con:
        before = con.execute('SELECT COUNT(*) FROM claims').fetchone()[0]
        con.execute("CREATE TRIGGER fail_claim_notification BEFORE INSERT ON notifications BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        service.create(b, guitar, SPEC)
    with repo.connect() as con:
        assert con.execute('SELECT COUNT(*) FROM claims').fetchone()[0] == before
        assert not con.execute('SELECT 1 FROM claim_spec_items').fetchone()
    assert repo.get_individual(guitar)[0]['current_owner_user_id'] == a


@pytest.mark.parametrize('change', [dict(claim_type='listing'), dict(claim_type='ownership'), dict(claim_type='media'),
    dict(author_user_id=3), dict(verification_status='positive'), dict(body='x' * 2001), dict(body=[]),
    dict(occurred_at='2999-01-01'), dict(occurred_at=True), dict(items=[]), dict(items=[{}]),
    dict(items=[dict(field_name='neck', value_text=3)]), dict(items=[dict(field_name='x' * 121, value_text='x')]),
    dict(items=[dict(field_name='neck', value_text='x' * 501)]),
    dict(items=[dict(field_name='NECK', value_text='A'), dict(field_name=' neck ', value_text='B')]),
    dict(items=[dict(field_name=str(index), value_text='x') for index in range(51)]),
    dict(specification_kind='other'), dict(body='NUL\x00text')])
def test_payload_rejects_out_of_scope_or_lossy_fields(change):
    with pytest.raises(ValueError):
        payload(SPEC | change)


@pytest.mark.parametrize('change', [dict(body=''), dict(body=None), dict(incident_kind='other')])
def test_incident_requires_known_kind_and_detail(change):
    with pytest.raises(ValueError):
        payload(INCIDENT | change)


def test_postgres_adapter_returns_ids_and_batches_without_dialect_rewrites():
    con = Mock()
    con.execute.return_value.fetchone.return_value = {'id': 41}
    adapted = ClaimConnection(con)
    assert adapted.execute('INSERT INTO claims (body) VALUES (?)', ('hello',)).lastrowid == 41
    assert con.execute.call_args.args == ('INSERT INTO claims (body) VALUES (%s) RETURNING id', ('hello',))
    adapted.execute('INSERT INTO claim_spec_items (claim_id) VALUES (?)', (41,))
    assert 'RETURNING' not in con.execute.call_args.args[0]
    cursor = Mock()
    con.cursor.return_value.__enter__ = Mock(return_value=cursor)
    con.cursor.return_value.__exit__ = Mock(return_value=False)
    adapted.executemany('INSERT INTO claim_spec_items (claim_id) VALUES (?)', [(41,)])
    cursor.executemany.assert_called_once_with('INSERT INTO claim_spec_items (claim_id) VALUES (%s)', [(41,)])


@pytest.fixture
def api():
    verifier, service = Mock(), Mock()
    verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', '', True)
    verifier.accounts.resolve_identity.return_value = {'app_user_id': 'canonical'}
    service.list.return_value = {'items': [], 'can_write': True}
    for method in ('create', 'edit', 'deactivate'):
        getattr(service, method).return_value = {'claim': {'id': '19'}}
    app = FastAPI()
    app.include_router(claim_router(verifier, service))
    with TestClient(app) as client:
        yield client, verifier, service


BASE = '/api/auth/guitars/12/claims'
AUTH = {'Authorization': 'Bearer fixture'}


def test_routes_identity_bounded_reads_and_mutations(api):
    client, verifier, service = api
    assert client.get(BASE).status_code == 401
    reply = client.get(BASE + '?after=40&limit=2', headers=AUTH)
    assert reply.status_code == 200 and reply.headers['cache-control'] == 'private, no-store'
    assert reply.headers['vary'] == 'Authorization'
    service.list.assert_called_once_with('canonical', 12, after=40, limit=2)
    assert client.post(BASE, headers=AUTH, json=SPEC).status_code == 200
    service.create.assert_called_once_with('canonical', 12, SPEC)
    assert client.patch(BASE + '/19', headers=AUTH, json=SPEC | {'revision': 'a' * 64}).status_code == 200
    assert client.post(BASE + '/19/deactivate', headers=AUTH, json={'revision': 'a' * 64}).status_code == 200
    assert client.delete(BASE + '/19', headers=AUTH).status_code == 405
    verifier.verify.assert_called_with(bearer_token='fixture')


@pytest.mark.parametrize('query', ['user_id=2', 'limit=1&limit=2', 'after=0', 'after=-1', 'after=9223372036854775808', 'limit=x'])
def test_route_rejects_invalid_and_identity_queries(api, query):
    client, _, service = api
    assert client.get(BASE + '?' + query, headers=AUTH).status_code == 400
    service.list.assert_not_called()


@pytest.mark.parametrize('extra', [dict(Origin='https://foreign.invalid'), {'Sec-Fetch-Site': 'cross-site'}])
def test_route_rejects_cross_site_writes(api, extra):
    client, _, service = api
    assert client.post(BASE, headers=AUTH | extra, json=SPEC).status_code == 403
    service.create.assert_not_called()


def test_route_json_timezone_and_unicode_limits(api):
    client, _, service = api
    assert client.post(BASE, headers=AUTH | {'Origin': 'http://testserver'}, json=SPEC).status_code == 200
    service.create.reset_mock()
    for raw in ('[]', '{"claim_type":"incident","claim_type":"specification"}', 'null', '{'):
        assert client.post(BASE, headers=AUTH | {'Content-Type': 'application/json'}, content=raw).status_code == 400
    assert client.post(BASE, headers=AUTH | {'Content-Type': 'application/json'}, content=' ' * (512 * 1024 + 1)).status_code == 413
    for extra in ({'Content-Encoding': 'gzip'}, {'X-YGC-Timezone': 'Invalid/Zone'}):
        assert client.post(BASE, headers=AUTH | extra, json=SPEC).status_code == 400
    service.create.assert_not_called()
    previous = viewer_timezone.get()
    service.create.side_effect = lambda *args: {'zone': str(viewer_timezone.get())}
    reply = client.post(BASE, headers=AUTH | {'X-YGC-Timezone': 'Asia/Tokyo'}, json=SPEC)
    assert reply.json() == {'zone': 'Asia/Tokyo'}
    assert viewer_timezone.get() == previous
    large = SPEC | {'body': '🎸' * 2000, 'items': [dict(field_name=str(index), value_text='🎸' * 500) for index in range(50)]}
    assert client.post(BASE, headers=AUTH | {'Content-Type': 'application/json'}, content=json.dumps(large, ensure_ascii=True)).status_code == 200


@pytest.mark.parametrize('failure,code', [(PermissionError, 403), (ClaimConflict, 409), (GuitarMissing, 404), (ValueError, 400), (RuntimeError, 503)])
def test_route_errors_are_sanitized(api, failure, code):
    client, _, service = api
    service.create.side_effect = failure('private SQL and secrets')
    response = client.post(BASE, headers=AUTH, json=SPEC)
    assert response.status_code == code and 'private SQL' not in response.text


def test_unverified_identity_never_reaches_claim_service(api):
    client, verifier, service = api
    verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', '', False)
    assert client.get(BASE, headers=AUTH).status_code == 403
    assert client.post(BASE, headers=AUTH, json=SPEC).status_code == 403
    service.list.assert_not_called()
    service.create.assert_not_called()


def test_author_can_manage_inactive_submission_after_guitar_is_no_longer_public(services):
    repo, service, owner, a, b, c, guitar = services
    original = service.create(b, guitar, INCIDENT)['claim']
    inactive = service.deactivate(b, guitar, int(original['id']), {'revision': original['revision']})['claim']
    with repo.connect() as con:
        con.execute("UPDATE claims SET status='inactive' WHERE individual_id=?", (guitar,))
    assert service.list(b, guitar)['items'] == [inactive]
    with pytest.raises(GuitarMissing):
        service.list(c, guitar)
    with pytest.raises(GuitarMissing):
        service.create(c, guitar, SPEC)


def test_claim_api_is_mounted_but_does_not_expose_local_generic_edit_route(monkeypatch):
    from ygc import cloud_account_api
    from ygc.cloud_disputes import CloudDisputes
    monkeypatch.setattr(CloudDisputes, 'check_schema', Mock())
    accounts, verifier = Mock(), Mock()
    verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', '', False)
    monkeypatch.setattr(cloud_account_api, 'PostgresAccounts', Mock(return_value=accounts))
    monkeypatch.setattr(cloud_account_api, 'IdentityPlatformIdentity', Mock(return_value=verifier))
    with TestClient(cloud_account_api.create_app(None, project_id='fixture-project')) as client:
        assert client.get(BASE, headers=AUTH).status_code == 403
        assert client.patch('/api/claims/19', headers=AUTH, json={}).status_code == 404


def test_legacy_single_field_specification_has_lossless_editable_projection(services):
    repo, service, owner, a, b, c, guitar = services
    original = service.create(b, guitar, SPEC)['claim']
    with repo.connect() as con:
        con.execute('DELETE FROM claim_spec_items WHERE claim_id=?', (original['id'],))
        con.execute("UPDATE claims SET field_name='neck wood',value_text='Maple',specification_kind=NULL WHERE id=?", (original['id'],))
    legacy = service.list(b, guitar)['items'][0]
    assert legacy['specification_kind'] == 'specification'
    assert legacy['spec_items'] == [dict(field_name='neck wood', value_text='Maple')]
    edited = service.edit(b, guitar, int(legacy['id']), SPEC | {'revision': legacy['revision'],
        'items': legacy['spec_items'] + [dict(field_name='neck_wood', value_text='Separate old label')]})['claim']
    assert edited['spec_items'] == legacy['spec_items'] + [dict(field_name='neck_wood', value_text='Separate old label')]


@pytest.mark.parametrize('mode,write,expected_kind,can_write', [
    ('normal', False, 'user_read', True), ('normal', True, 'user_write', True),
    ('read_only', False, 'user_read', False), ('admin_only', True, 'user_write', True)])
def test_transaction_holds_existing_authority_fences_and_rechecks_visibility(monkeypatch, mode, write, expected_kind, can_write):
    import ygc.cloud_claims as module
    events = []
    account = dict(id=8, app_user_id='canonical', role='admin')
    raw = Mock()
    raw.execute.return_value.fetchone.return_value = {'locked': True}

    @contextmanager
    def connection(settings, target):
        events.append(('open', target))
        yield raw
        events.append(('close', target))

    @contextmanager
    def access(kind, actor):
        assert (kind, actor) == (expected_kind, 'canonical')
        events.append('authority-start')
        yield None, {'mode': mode}, account
        events.append('authority-end')

    @contextmanager
    def transaction(self, principal, individual):
        assert principal.user_id == 8 and principal.app_user_id == 'canonical' and principal.verified
        assert individual == 12
        events.append('content-start')
        yield BoundRepository(module.ObservationConnection(raw)), account
        events.append('content-end')

    operations = Mock()
    operations.access = access
    service = CloudClaims(None, operations)
    monkeypatch.setattr(module, 'connect', connection)
    monkeypatch.setattr(module.PostgresOwnership, '_transaction', transaction)
    service._individual = Mock(side_effect=lambda *args: events.append('visible'))
    with service.transaction('canonical', 12, write=write) as (repo, user, writable):
        assert user == 8 and writable is can_write and isinstance(repo.connection, ClaimConnection)
        events.append('action')
    assert events.index('authority-start') < events.index('content-start') < events.index('action')
    assert events.index('action') < events.index('content-end') < events.index('authority-end')
    assert events.count('visible') == 2
    assert events.index('visible') < events.index('content-start')
    assert service._individual.call_count == 2
    assert any('pg_try_advisory_xact_lock' in args.args[0] for args in raw.execute.call_args_list) is write


def test_hidden_target_rejected_before_participant_projection_discovery(monkeypatch):
    import ygc.cloud_claims as module
    raw, operations = Mock(), Mock()
    raw.execute.return_value.fetchone.return_value = None

    @contextmanager
    def connection(*args):
        yield raw

    @contextmanager
    def access(*args):
        yield None, {'mode': 'normal'}, dict(id=8, app_user_id='canonical')

    operations.access = access
    monkeypatch.setattr(module, 'connect', connection)
    participants = Mock()
    monkeypatch.setattr(module.PostgresOwnership, '_transaction', participants)
    with pytest.raises(GuitarMissing):
        with CloudClaims(None, operations).transaction('canonical', 12):
            pytest.fail('Missing or hidden individual must be rejected before participant discovery.')
    participants.assert_not_called()


@pytest.mark.parametrize('incident_kind', ['damage', 'lost', 'theft'])
def test_all_incident_kinds_leave_ownership_unchanged(services, incident_kind):
    repo, service, owner, a, b, c, guitar = services
    claim = service.create(a, guitar, INCIDENT | {'incident_kind': incident_kind})['claim']
    assert claim['incident_kind'] == incident_kind and claim['verification_status'] == 'positive'
    assert repo.get_individual(guitar)[0]['current_owner_user_id'] == a
