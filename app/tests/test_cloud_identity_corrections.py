"""Synthetic SQLite business and HTTP boundary tests; no production data."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import sqlite3
import threading
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ygc.claim_revision import ClaimConflict
from ygc.cloud_guitars import GuitarMissing
from ygc.cloud_identity_corrections import CloudIdentityCorrections, payload, own_listing
from ygc.cloud_identity_correction_routes import identity_correction_router
from ygc.db.postgres_operations import ServiceRestricted
from ygc.db.postgres_ownership import BoundRepository
from ygc.db.repository import Repository
from ygc.identity_platform import VerifiedIdentity

BASE = '/api/auth/identity-corrections'
AUTH = {'Authorization': 'Bearer synthetic'}
INPUT = dict(manufacturer='Fender', model='Stratocaster', year='1964',
             serial_number='NEW-001', reason='Corrected from the original record.')


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    repo = Repository(tmp_path / 'identity.db')
    repo.init_db()
    author, other, owner = (repo.create_user(name) for name in ('Author', 'Other author', 'Current owner'))
    individual, _, listing, media = repo.create_initial_listing_claim(author, manufacturer='Fender',
        model='Old model', serial_number='OLD-001', year='1963', finish='Sunburst',
        occurred_at='2020-01-01', body='Original Listing is immutable.', media_storage_path='private/original.jpg')
    service = CloudIdentityCorrections(None, None)
    state = {'mode': 'normal'}

    @contextmanager
    def transaction(actor, listing=None, *, write=False):
        with repo.connect() as con:
            if write:
                con.execute('BEGIN IMMEDIATE')
            if state['mode'] == 'offline' or (write and state['mode'] == 'read_only'):
                raise ServiceRestricted()
            row = con.execute("SELECT * FROM users WHERE id=? AND ban_status='normal' AND account_type<>'source'", (actor,)).fetchone()
            if not row:
                raise PermissionError()
            yield BoundRepository(con), actor, state['mode'] != 'read_only'

    monkeypatch.setattr(service, 'transaction', transaction)
    return repo, service, author, other, owner, individual, listing, state


def submit(workflow, **changes):
    _, service, author, _, _, _, listing, _ = workflow
    return service.create(author, listing, INPUT | changes | {'revision': service.detail(author, listing)['revision']})


def rows(repo, table):
    with repo.connect() as con:
        return [dict(row) for row in con.execute(f'SELECT * FROM {table} ORDER BY 1')]


def test_create_preserves_listing_evidence_ownership_and_records_exact_changes(workflow):
    repo, service, author, other, owner, individual, listing, _ = workflow
    # Author still has correction permission after transfer to another user.
    transfer = repo.create_transfer(author, individual, owner)
    repo.resolve_transfer(transfer, owner, 'accept')
    before_listing = next(row for row in rows(repo, 'claims') if row['id'] == listing)
    protected = {table: rows(repo, table) for table in ('claim_listing_items', 'claim_evidence',
        'claim_source_evidence', 'media_assets', 'claim_transfers', 'claim_transfer_acceptance')}
    before = dict(repo.get_individual(individual)[0])
    detail = service.detail(author, listing)
    assert detail['items'] == [] and detail['next_after'] is None
    result = submit(workflow)
    correction = result['correction']
    assert correction['verification_status'] == 'positive' and correction['status'] == 'active'
    assert correction['target_claim_id'] == str(listing) and correction['individual_id'] == str(individual)
    assert correction['occurred_at'] == '2020-01-01'
    assert correction['body'] == INPUT['reason']
    assert correction['changes'] == [
        {'field_name': 'model', 'old_value': 'Old model', 'new_value': 'Stratocaster'},
        {'field_name': 'year', 'old_value': '1963', 'new_value': '1964'},
        {'field_name': 'serial_number', 'old_value': 'OLD-001', 'new_value': 'NEW-001'}]
    assert result['detail']['individual'] == {'id': str(individual), **{key: INPUT[key] for key in INPUT if key != 'reason'}}
    assert result['detail']['revision'] != detail['revision']
    assert result['detail']['items'] == [correction]
    assert next(row for row in rows(repo, 'claims') if row['id'] == listing) == before_listing
    for table, original in protected.items():
        assert rows(repo, table) == original
    after = dict(repo.get_individual(individual)[0])
    for field in ('finish', 'current_owner_user_id', 'current_owner_name', 'current_owner_type',
                  'location_country', 'location_region', 'representative_media_asset_id'):
        assert after[field] == before[field]
    assert after['current_owner_user_id'] == owner
    assert int(correction['id']) not in repo.owner_verifiable_claim_ids(individual, owner)
    for actor in (author, owner):
        with pytest.raises(ValueError):
            repo.set_claim_response(int(correction['id']), actor, 'negative')


def test_history_and_entrance_private_to_author_not_owner_or_other(workflow):
    repo, service, author, other, owner, individual, listing, _ = workflow
    submit(workflow)
    transfer = repo.create_transfer(author, individual, owner)
    repo.resolve_transfer(transfer, owner, 'accept')
    for actor in (other, owner):
        assert service.list(actor)['items'] == []
        with pytest.raises(GuitarMissing):
            service.detail(actor, listing)
        with pytest.raises(GuitarMissing):
            service.create(actor, listing, INPUT | {'revision': 'a' * 64})
    for target in (99999, int(service.detail(author, listing)['items'][0]['id'])):
        with pytest.raises(GuitarMissing):
            service.detail(author, target)
    with repo.connect() as con:
        con.execute("UPDATE claims SET status='inactive' WHERE id=?", (listing,))
    assert service.list(author)['items'] == []
    with pytest.raises(GuitarMissing):
        service.detail(author, listing)


def test_list_and_history_cursor_bounded_and_revision_independent(workflow):
    repo, service, author, other, _, individual, listing, _ = workflow
    _, _, newest_listing, _ = repo.create_initial_listing_claim(author, manufacturer='Gibson',
        serial_number='OTHER-002', media_storage_path='private/2.jpg', occurred_at='2021-02-03')
    first = service.list(author, limit=1)
    assert first['items'][0]['id'] == first['next_after'] == str(newest_listing)
    assert service.list(author, after=newest_listing, limit=1)['items'][0]['id'] == str(listing)
    one = submit(workflow)['correction']
    two = submit(workflow, year='1965')['correction']
    first = service.detail(author, listing, limit=1)
    second = service.detail(author, listing, after=int(first['next_after']), limit=1)
    assert first['items'] == [two] and second['items'] == [one] and second['next_after'] is None
    assert first['revision'] == second['revision']
    # A correction of another Listing, even on this Individual, is not exposed.
    with repo.connect() as con:
        con.execute('UPDATE claims SET individual_id=?,author_user_id=? WHERE id=?', (individual, other, newest_listing))
        con.execute('UPDATE claims SET target_claim_id=?,author_user_id=? WHERE id=?', (newest_listing, other, int(two['id'])))
    assert service.detail(author, listing)['items'] == [one]


@pytest.mark.parametrize('method', ['list', 'detail'])
@pytest.mark.parametrize('values', [{'limit': 0}, {'limit': 51}, {'limit': True}, {'limit': '1'},
    {'after': -1}, {'after': 2**63}, {'after': False}, {'after': '2'}])
def test_service_page_types_and_bounds(workflow, method, values):
    _, service, author, _, _, _, listing, _ = workflow
    with pytest.raises(ValueError):
        getattr(service, method)(author, *([listing] if method == 'detail' else []), **values)


def test_lost_success_response_stale_retry_cannot_create_again(workflow):
    repo, service, author, _, _, _, listing, _ = workflow
    old = service.detail(author, listing)['revision']
    original = INPUT | {'revision': old}
    service.create(author, listing, original)
    with pytest.raises(ClaimConflict):
        service.create(author, listing, original)
    assert len(service.detail(author, listing)['items']) == 1
    with pytest.raises(ValueError, match='No identity fields'):
        service.create(author, listing, INPUT | {'revision': service.detail(author, listing)['revision']})


def test_revision_covers_status_items_listing_and_target_changes_same_timestamp(workflow):
    repo, service, author, _, _, individual, listing, _ = workflow
    correction = submit(workflow)['correction']
    changes = [
        ("UPDATE claims SET verification_status='negative' WHERE id=?", int(correction['id'])),
        ("UPDATE claim_identity_items SET old_value='other' WHERE claim_id=?", int(correction['id'])),
        ("UPDATE claims SET body='Listing changed' WHERE id=?", listing),
        ("UPDATE claim_listing_items SET value_text='Different model' WHERE claim_id=? AND field_name='model'", listing),
        ("UPDATE claims SET status='inactive' WHERE id=?", int(correction['id'])),
    ]
    for query, value in changes:
        old = service.detail(author, listing)['revision']
        with repo.connect() as con:
            con.execute(query, (value,))
        assert service.detail(author, listing)['revision'] != old
        with pytest.raises(ClaimConflict):
            service.create(author, listing, INPUT | {'year': '1999', 'revision': old})
    other, *_ = repo.create_initial_listing_claim(author, manufacturer='Gretsch', serial_number='TARGET', media_storage_path='x')
    old = service.detail(author, listing)['revision']
    with repo.connect() as con:
        con.execute('UPDATE claims SET individual_id=? WHERE id=?', (other, listing))
    with pytest.raises(ClaimConflict):
        service.create(author, listing, INPUT | {'revision': old})


def test_duplicate_maker_serial_rejected_regardless_model_and_does_not_leak_id(workflow):
    repo, service, author, other, _, individual, listing, _ = workflow
    hidden, *_ = repo.create_initial_listing_claim(other, manufacturer='Fender USA', model='Completely different',
        serial_number='SERIAL NUMBER: NEW.001', media_storage_path='private/hidden.jpg')
    before = rows(repo, 'claims')
    for create in (lambda: submit(workflow, serial_number='new001'), lambda: repo.create_identity_correction(author, listing,
        manufacturer='Fender', model='Different again', year=None, serial_number='new001')):
        with pytest.raises(ClaimConflict) as error:
            create()
        assert str(hidden) not in str(error.value)
        assert rows(repo, 'claims') == before
    assert repo.get_individual(individual)[0]['serial_number'] == 'OLD-001'


def test_failure_rolls_back_claim_items_and_snapshot(workflow):
    repo, service, author, _, _, individual, listing, _ = workflow
    before = {table: rows(repo, table) for table in ('claims', 'claim_identity_items', 'individuals')}
    with repo.connect() as con:
        con.execute("CREATE TRIGGER fail_identity BEFORE UPDATE ON individuals BEGIN SELECT RAISE(ABORT,'fixture rollback'); END")
    with pytest.raises(sqlite3.IntegrityError):
        submit(workflow)
    for table, original in before.items():
        assert rows(repo, table) == original


def test_trim_clear_and_legacy_listing_date_fallback(workflow):
    repo, service, author, _, _, _, listing, _ = workflow
    with repo.connect() as con:
        con.execute('UPDATE claims SET occurred_at=NULL WHERE id=?', (listing,))
        stamp = con.execute('SELECT created_at FROM claims WHERE id=?', (listing,)).fetchone()[0]
    correction = submit(workflow, manufacturer='  Fender ', model=' ', year=None, reason=' ')['correction']
    assert correction['occurred_at'] == stamp and correction['body'] is None
    assert correction['changes'][0]['new_value'] is None
    assert service.detail(author, listing)['individual']['model'] is None


def test_older_listing_correction_retains_existing_observation_chronology(workflow):
    repo, service, author, _, _, individual, listing, _ = workflow
    with repo.connect() as con:
        stamp = '2022-01-01'
        latest = con.execute("""INSERT INTO claims(individual_id,author_user_id,claim_type,occurred_at,created_at,updated_at)
            VALUES (?,?,'listing',?,?,?)""", (individual, author, stamp, stamp, stamp)).lastrowid
    repo.create_identity_correction(author, latest, manufacturer='Fender', model='Latest model', year='2000', serial_number='LATEST')
    result = submit(workflow)
    assert result['correction']['verification_status'] == 'positive'
    assert result['detail']['individual']['serial_number'] == 'LATEST'
    assert result['detail']['individual']['model'] == 'Latest model'


def test_modes_and_ban_block_without_writes(workflow):
    repo, service, author, _, _, _, listing, state = workflow
    original = INPUT | {'revision': service.detail(author, listing)['revision']}
    state['mode'] = 'read_only'
    assert not service.list(author)['can_write'] and not service.detail(author, listing)['can_write']
    with pytest.raises(ServiceRestricted):
        service.create(author, listing, original)
    state['mode'] = 'offline'
    with pytest.raises(ServiceRestricted):
        service.list(author)
    state['mode'] = 'normal'
    with repo.connect() as con:
        con.execute("UPDATE users SET ban_status='ban' WHERE id=?", (author,))
    with pytest.raises(PermissionError):
        service.create(author, listing, original)
    with pytest.raises(ValueError, match='active user'):
        repo.create_identity_correction(author, listing, **INPUT)
    assert not rows(repo, 'claim_identity_items')


def test_direct_concurrent_corrections_serialize_maker_serial_check(workflow):
    repo, service, author, other, _, _, listing, _ = workflow
    _, _, second, _ = repo.create_initial_listing_claim(other, manufacturer='Fender', model='Other model',
        serial_number='OTHER', media_storage_path='x')
    barrier = threading.Barrier(2)

    def correct(user, claim, model):
        barrier.wait()
        try:
            return repo.create_identity_correction(user, claim, manufacturer='Gibson', model=model,
                year=None, serial_number='COMMON')
        except ClaimConflict:
            return 'conflict'

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda values: correct(*values), [(author, listing, 'One'), (other, second, 'Two')]))
    assert results.count('conflict') == 1
    assert len([row for row in rows(repo, 'individuals') if row['normalized_serial'] == 'COMMON']) == 1


def test_concurrent_same_revision_produces_one_correction(workflow):
    repo, service, author, _, _, _, listing, _ = workflow
    original = INPUT | {'revision': service.detail(author, listing)['revision']}
    barrier = threading.Barrier(2)

    def create():
        barrier.wait()
        try:
            return service.create(author, listing, original)
        except ClaimConflict:
            return 'conflict'

    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(create), pool.submit(create)]
        results = [job.result() for job in jobs]
    assert results.count('conflict') == 1 and len(service.detail(author, listing)['items']) == 1


@pytest.mark.parametrize('changes', [
    {'manufacturer': None}, {'manufacturer': ''}, {'manufacturer': True}, {'manufacturer': 'x' * 201},
    {'model': []}, {'model': 'x' * 201}, {'year': 1965}, {'year': 'x' * 41},
    {'serial_number': None}, {'serial_number': ''}, {'serial_number': 'S/N:'}, {'serial_number': 'x' * 201},
    {'reason': False}, {'reason': 'x' * 2001}, {'reason': '\x00'}, {'model': 'line\nbreak'}, {'year': '\x7f'},
    {'reason': '\ud800'}, {'revision': None}, {'revision': 'A' * 64}, {'revision': 'a' * 63},
    {'author_user_id': 1}, {'individual_id': 1}, {'claim_type': 'listing'}, {'verification_status': 'positive'},
    {'occurred_at': '2020-01-02'}, {'current_owner_user_id': 1}, {'location_country': 'US'}, {'images': []},
])
def test_payload_strict_and_bounded(changes):
    with pytest.raises((ValueError, TypeError, UnicodeError)):
        payload(INPUT | {'revision': 'a' * 64} | changes)


@pytest.mark.parametrize('missing', ['revision', *INPUT])
def test_payload_missing_fields_rejected(missing):
    data = INPUT | {'revision': 'a' * 64}
    del data[missing]
    with pytest.raises(ValueError):
        payload(data)


@pytest.fixture
def api():
    verifier, service = Mock(), Mock()
    verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', '', True)
    verifier.accounts.resolve_identity.return_value = {'app_user_id': 'canonical'}
    service.list.return_value = {'items': [], 'next_after': None, 'can_write': True}
    service.detail.return_value = {'revision': 'a' * 64}
    service.create.return_value = {'correction': {'id': '19'}, 'detail': {}}
    app = FastAPI()
    app.include_router(identity_correction_router(verifier, service))
    with TestClient(app) as client:
        yield client, verifier, service


def test_router_verified_author_routes_and_safe_headers(api):
    client, verifier, service = api
    reply = client.get(BASE)
    assert reply.status_code == 401 and reply.headers['cache-control'] == 'private, no-store'
    reply = client.get(BASE + '?after=20&limit=2', headers=AUTH)
    assert reply.status_code == 200 and reply.headers['vary'] == 'Authorization'
    service.list.assert_called_once_with('canonical', after=20, limit=2)
    assert client.get(BASE + '/12?after=20&limit=2', headers=AUTH).status_code == 200
    service.detail.assert_called_once_with('canonical', 12, after=20, limit=2)
    data = INPUT | {'revision': 'a' * 64}
    assert client.post(BASE + '/12', headers=AUTH, json=data).status_code == 200
    service.create.assert_called_once_with('canonical', 12, data)
    verifier.verify.assert_called_with(bearer_token='synthetic')
    for method in (client.patch, client.delete):
        assert method(BASE + '/12', headers=AUTH).status_code == 405
    assert client.post(BASE, headers=AUTH, json=data).status_code == 405


@pytest.mark.parametrize('suffix', ['?user_id=1', '?limit=51', '?limit=0', '?limit=2&limit=3', '?after=0',
    '?after=-1', '?after=9223372036854775808', '?after=NaN', '/0', '/-1', '/true', '/9223372036854775808'])
def test_router_rejects_bad_paths_queries(api, suffix):
    client, _, service = api
    assert client.get(BASE + suffix, headers=AUTH).status_code == 400
    service.list.assert_not_called()
    service.detail.assert_not_called()


@pytest.mark.parametrize('content', ['[]', 'null', 'false', '{', '{"revision":"a","revision":"b"}',
    '{"manufacturer":{"name":"A","name":"B"}}'])
def test_router_rejects_malformed_duplicate_or_non_object_json(api, content):
    client, _, service = api
    assert client.post(BASE + '/12', headers=AUTH | {'Content-Type': 'application/json'}, content=content).status_code == 400
    service.create.assert_not_called()


@pytest.mark.parametrize('headers,query,status', [
    ({'Content-Type': 'text/plain'}, '', 400), ({'Content-Encoding': 'gzip'}, '', 400),
    ({'Origin': 'https://hostile.example'}, '', 403), ({'Sec-Fetch-Site': 'cross-site'}, '', 403),
    ({}, '?limit=1', 400),
])
def test_router_rejects_write_bypass(api, headers, query, status):
    client, _, service = api
    assert client.post(BASE + '/12' + query, headers=AUTH | headers, json=INPUT).status_code == status
    service.create.assert_not_called()


def test_router_rejects_large_body_and_duplicate_authorization(api):
    client, _, service = api
    assert client.post(BASE + '/12', headers=AUTH, json={'reason': 'x' * (33 * 1024)}).status_code == 413
    headers = [('Authorization', 'Bearer synthetic'), ('Authorization', 'Bearer second')]
    assert client.get(BASE, headers=headers).status_code in (400, 401)
    service.list.assert_not_called()
    service.create.assert_not_called()


@pytest.mark.parametrize('error,status', [(GuitarMissing('private-id-987'), 404), (ClaimConflict('private-id-987'), 409),
    (ServiceRestricted('secret'), 403), (PermissionError('disabled'), 403), (ValueError('private-id-987'), 400),
    (RuntimeError('private-token'), 503)])
def test_router_errors_do_not_expose_internal_details(api, error, status):
    client, _, service = api
    service.create.side_effect = error
    result = client.post(BASE + '/12', headers=AUTH, json=INPUT)
    assert result.status_code == status and result.headers['cache-control'] == 'private, no-store'
    assert all(word not in result.text for word in ('private-id', 'private-token', 'disabled', 'secret'))


def test_router_live_verified_identity_and_account_required(api):
    client, verifier, service = api
    verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', '', False)
    assert client.get(BASE, headers=AUTH).status_code == 403
    verifier.accounts.resolve_identity.assert_not_called()
    verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', '', True)
    verifier.accounts.resolve_identity.side_effect = PermissionError('account revoked')
    assert client.get(BASE, headers=AUTH).status_code == 403
    service.list.assert_not_called()


def test_hybrid_final_identity_duplicate_rolls_back_even_with_unique_input(workflow):
    repo, service, author, other, _, individual, listing, _ = workflow
    with repo.connect() as con:
        stamp = '2022-01-01'
        latest = con.execute("""INSERT INTO claims(individual_id,author_user_id,claim_type,occurred_at,created_at,updated_at)
            VALUES (?,?,'listing',?,?,?)""", (individual, author, stamp, stamp, stamp)).lastrowid
    repo.create_identity_correction(author, latest, manufacturer='Fender', model='Old model',
                                    year='1963', serial_number='LATER')
    repo.create_initial_listing_claim(other, manufacturer='Gibson', model='Entirely different',
        serial_number='LATER', media_storage_path='private/hidden.jpg')
    before = {table: rows(repo, table) for table in ('claims', 'claim_identity_items', 'individuals')}
    # Input Gibson/EARLIER is unique, but the later correction's serial wins:
    # Gibson/LATER would conflict across Models without the evaluated recheck.
    with pytest.raises(ClaimConflict):
        submit(workflow, manufacturer='Gibson', model='Old model', year='1963', serial_number='EARLIER')
    for table, original in before.items():
        assert rows(repo, table) == original


@pytest.mark.parametrize('table,field,value', [
    ('individuals', 'manufacturer', 'x' * 201), ('individuals', 'serial_number', 'x' * 201),
    ('individuals', 'model', 'x' * 201), ('individuals', 'year', 'x' * 41),
    ('claims', 'body', 'x' * 2001), ('claims', 'occurred_at', 'x' * 41),
    ('claims', 'created_at', 'x' * 41), ('claims', 'verification_status', 'unknown'),
    ('claim_identity_items', 'old_value', 'x' * 201),
    ('claim_identity_items', 'new_value', 'x' * 201),
    ('claim_identity_items', 'field_name', 'current_owner_user_id'),
])
def test_legacy_response_bounds_fail_closed_without_truncation(workflow, table, field, value):
    repo, service, author, _, _, individual, listing, _ = workflow
    correction = submit(workflow)['correction']
    with repo.connect() as con:
        where = 'id=?' if table != 'claim_identity_items' else 'claim_id=?'
        target = individual if table == 'individuals' else int(correction['id'])
        con.execute(f'UPDATE {table} SET {field}=? WHERE {where}', (value, target))
    with pytest.raises(RuntimeError, match='unavailable'):
        service.detail(author, listing)
    if table == 'individuals':
        with pytest.raises(RuntimeError, match='unavailable'):
            service.list(author)


def test_legacy_duplicate_or_unbounded_change_items_fail_closed(workflow):
    repo, service, author, _, _, _, listing, _ = workflow
    correction = submit(workflow)['correction']
    with repo.connect() as con:
        con.execute("UPDATE claim_identity_items SET field_name='model' WHERE claim_id=?", (int(correction['id']),))
    with pytest.raises(RuntimeError, match='unavailable'):
        service.detail(author, listing)
    with repo.connect() as con:
        con.executemany("INSERT INTO claim_identity_items(claim_id,field_name,new_value,created_at) VALUES (?,'model','x','2020')",
                        [(int(correction['id']),)] * 3)
    with pytest.raises(RuntimeError, match='unavailable'):
        service.detail(author, listing)


def test_dispute_disables_detail_and_rejects_create_without_unknown_result(workflow):
    repo, service, author, _, _, individual, listing, _ = workflow
    old_revision = service.detail(author, listing)['revision']
    with repo.connect() as con:
        con.execute("""INSERT INTO ownership_disputes(individual_id,owner_id,locked_owner_id,created_at,updated_at)
            VALUES (?,?,?,'2020','2020')""", (individual, author, author))
    detail = service.detail(author, listing)
    assert detail['revision'] != old_revision and detail['can_write'] is False
    with pytest.raises(ClaimConflict, match='dispute'):
        service.create(author, listing, INPUT | {'revision': detail['revision']})
    assert not rows(repo, 'claim_identity_items')
    with repo.connect() as con:
        con.execute("UPDATE ownership_disputes SET status='resolved',version=version+1 WHERE individual_id=?", (individual,))
    assert service.detail(author, listing)['can_write']
    assert service.detail(author, listing)['revision'] != detail['revision']


def test_pg_boundary_maintenance_and_private_target_revalidation(monkeypatch):
    from ygc import cloud_identity_corrections as module
    events = []
    raw, guard = Mock(), Mock()
    guard.execute.return_value.fetchone.return_value = {'locked': True}
    canonical = {'id': 7, 'app_user_id': 'canonical'}

    @contextmanager
    def connect(settings, target):
        events.append(target)
        yield guard if target == 'operations' else raw

    @contextmanager
    def access(kind, actor):
        events.append((kind, actor))
        yield None, {'mode': 'normal'}, canonical

    @contextmanager
    def fenced(actor, individual):
        events.append(('fenced', actor.user_id, individual))
        yield BoundRepository(Mock(connection=raw)), canonical

    operations = Mock(access=access)
    monkeypatch.setattr(module, 'connect', connect)
    monkeypatch.setattr(module, 'PostgresOwnership', Mock(return_value=Mock(_transaction=fenced)))
    check = Mock(side_effect=[{'individual_id': 4}, {'individual_id': 4}])
    monkeypatch.setattr(module, 'own_listing', check)
    service = CloudIdentityCorrections(None, operations)
    with service.transaction('canonical', 12, write=True) as (_, user, can_write):
        assert user == 7 and can_write
    assert events == ['operations', ('user_write', 'canonical'), 'chronicle', ('fenced', 7, 4)]
    assert check.call_count == 2
    assert '79432190' in guard.execute.call_args.args[0]
    check.side_effect = [{'individual_id': 4}, {'individual_id': 5}]
    with pytest.raises(ClaimConflict):
        with service.transaction('canonical', 12, write=True):
            pytest.fail('Moved Listing must fail before yielding')
    events.clear()
    guard.execute.return_value.fetchone.return_value = {'locked': False}
    with pytest.raises(ClaimConflict):
        with service.transaction('canonical', 12, write=True):
            pytest.fail('Maintenance must fence writes')
    assert events == ['operations']


def test_pg_boundary_checks_private_author_before_participant_discovery(monkeypatch):
    from ygc import cloud_identity_corrections as module
    canonical = {'id': 7, 'app_user_id': 'canonical'}

    @contextmanager
    def connect(settings, target):
        yield Mock()

    @contextmanager
    def access(kind, actor):
        yield None, {'mode': 'normal'}, canonical

    ownership = Mock()
    monkeypatch.setattr(module, 'connect', connect)
    monkeypatch.setattr(module, 'PostgresOwnership', ownership)
    monkeypatch.setattr(module, 'own_listing', Mock(side_effect=GuitarMissing()))
    with pytest.raises(GuitarMissing):
        with CloudIdentityCorrections(None, Mock(access=access)).transaction('canonical', 12):
            pytest.fail('Private Listing required')
    ownership.assert_not_called()


def test_pg_list_boundary_uses_canonical_projection_and_read_only_flag(monkeypatch):
    from ygc import cloud_identity_corrections as module
    canonical = {'id': 7, 'app_user_id': 'canonical'}
    raw = Mock()
    events = []

    @contextmanager
    def connect(settings, target):
        yield raw

    @contextmanager
    def access(kind, actor):
        events.append((kind, actor))
        yield None, {'mode': 'read_only'}, canonical

    @contextmanager
    def content(actor, participants):
        events.append(('projection', actor, participants))
        yield raw, canonical

    monkeypatch.setattr(module, 'connect', connect)
    monkeypatch.setattr(module, 'PostgresAccounts', Mock(return_value=Mock(content_transaction=content)))
    with CloudIdentityCorrections(None, Mock(access=access)).transaction('canonical') as (_, user, can_write):
        assert user == 7 and not can_write
    assert events == [('user_read', 'canonical'), ('projection', 'canonical', (7,))]
