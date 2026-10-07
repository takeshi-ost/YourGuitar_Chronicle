"""Identity Correction acceptance on isolated loopback PostgreSQL databases.

All accounts, Listings, photos and corrections are synthetic. Only fixture setup
and deliberate fault injection use the database owner; product calls use the
unchanged restricted runtime role. Import/compilation opens no sockets. Execute
only with the approved Mac/CI PostgreSQL runner, never against staging/live data.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
import json
import re
from threading import Barrier
from unittest.mock import patch
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
import psycopg
from psycopg import errors, sql

from postgres_event_claim_checks import structure
from postgres_media_claim_checks import Storage, seed, reject_new_rows
from ygc.admin_bootstrap_job import grant_first_admin
from ygc.claim_revision import ClaimConflict
from ygc.cloud_guitars import GuitarMissing
from ygc.cloud_identity_corrections import CloudIdentityCorrections
from ygc.cloud_identity_correction_routes import identity_correction_router
from ygc.cloud_owner import CloudOwner, content_revision
from ygc.cloud_public_catalog import CloudPublicCatalog
from ygc.db.postgres import PostgresSettings, bootstrap, connect, migrate
from ygc.db.postgres_accounts import PostgresAccounts
from ygc.db.postgres_operations import PostgresOperations, ServiceRestricted
from ygc.db.postgres_ownership import BoundRepository
from ygc.db.postgres_queries import ObservationConnection
from ygc.identity_platform import VerifiedIdentity
from ygc.extractors.normalization import normalize_manufacturer, normalize_serial

ISSUER = 'synthetic-identity-correction-acceptance'
PRIVATE = 'PRIVATE-IDENTITY-CORRECTION-REASON'
FIELDS = ('manufacturer', 'model', 'year', 'serial_number')
IDENTITY_FIELDS = {'id', *FIELDS}
LIST_FIELDS = {'id', 'individual', 'occurred_at'}
DETAIL_FIELDS = {'listing', 'individual', 'items', 'next_after', 'revision', 'can_write'}
CORRECTION_FIELDS = {'id', 'target_claim_id', 'individual_id', 'body', 'occurred_at',
                     'created_at', 'status', 'verification_status', 'changes'}
TABLES = ('individuals', 'claims', 'claim_listing_items', 'claim_identity_items',
          'media_assets', 'claim_evidence', 'claim_source_evidence', 'notifications',
          'claim_responses', 'user_guitars', 'observations')
BASE = '/api/auth/identity-corrections'


def rejected(error, operation):
    try:
        operation()
    except error:
        return
    names = ', '.join(item.__name__ for item in error) if isinstance(error, tuple) else error.__name__
    raise AssertionError('Expected ' + names)


def run(port):
    prefix = 'ygctest_identity_' + uuid.uuid4().hex[:10] + '_'
    runtime = prefix + 'app'
    owner = PostgresSettings('127.0.0.1', 'postgres', 'ygc-tests-only', port, prefix)
    app = replace(owner, user=runtime)
    databases = []
    with psycopg.connect(host='127.0.0.1', port=port, dbname='postgres', user='postgres',
                         password='ygc-tests-only', autocommit=True) as system:
        try:
            system.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(
                sql.Identifier(runtime), sql.Literal('ygc-tests-only')))
            for target in ('accounts', 'chronicle', 'operations'):
                name = owner.database(target)
                system.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
                databases.append(name)
                bootstrap(owner, target, runtime)
                migrate(owner, target, runtime)
            original_structure = structure(owner, runtime)
            accounts, operations = PostgresAccounts(app), PostgresOperations(app)
            records = {name: accounts.ensure_identity(issuer=ISSUER, subject=name,
                display_name='Synthetic identity ' + name) for name in ('admin', 'a', 'b', 'c')}
            admin = records['admin']['app_user_id']
            assert grant_first_admin(app, admin, 'synthetic-identity-operator')
            accounts.drain_projection()
            operations.set_mode(admin, mode='normal', message='',
                                version=operations.details(admin)['version'])
            fixture = seed(owner, records, Storage())
            with connect(owner, 'chronicle') as con:
                # A is Listing author, B is Current Owner. Correction must be
                # accessible to A without granting A Owner Verification rights.
                con.execute("UPDATE claim_listing_items SET value_text=%s WHERE field_name='owner_user_id'",
                            (str(records['b']['id']),))
                for individual in (fixture['individual'], fixture['other']):
                    listing = con.execute("SELECT id FROM claims WHERE individual_id=%s AND claim_type='listing'",
                                          (individual,)).fetchone()['id']
                    for field, value in (('year', '1965'), ('location_country', 'JP'), ('location_region', 'Tokyo')):
                        con.execute("INSERT INTO claim_listing_items(claim_id,field_name,value_text,created_at) VALUES(%s,%s,%s,'2026-01-01')",
                                    (listing, field, value))
                    BoundRepository(ObservationConnection(con))._rebuild_individual_snapshot_in_connection(
                        ObservationConnection(con), individual)
                fixture['other_listing'] = con.execute("SELECT id FROM claims WHERE individual_id=%s AND claim_type='listing'",
                                                       (fixture['other'],)).fetchone()['id']
            checks(app, owner, accounts, operations, records, fixture)
            assert structure(owner, runtime) == original_structure
            # The global schema retains its existing 3-field uniqueness. Only
            # correction/new-registration checks reject Maker+Serial collisions.
            with connect(app, 'chronicle') as con:
                con.execute("INSERT INTO individuals(manufacturer,model,serial_number,normalized_manufacturer,normalized_model,normalized_serial,created_at,updated_at) VALUES('Dup','One','DUP','dup','one','dup','now','now')")
                con.execute("INSERT INTO individuals(manufacturer,model,serial_number,normalized_manufacturer,normalized_model,normalized_serial,created_at,updated_at) VALUES('Dup','Two','DUP','dup','two','dup','now','now')")
                with con.transaction():
                    try:
                        with con.transaction():
                            con.execute("CREATE TABLE identity_forbidden(id BIGINT)")
                    except errors.InsufficientPrivilege:
                        pass
                    else:
                        raise AssertionError('Correction must not expand runtime DDL privileges')
            print('PostgreSQL Identity Correction: author-only active Listings, bounded private history, '
                  'immediate Positive inherited-date correction, source/evidence preservation, current identity/search, '
                  'Maker+Serial collision/concurrency, stale/repeated/unknown outcomes, auth/mode fences, '
                  'normal Owner exclusion, rollback and unchanged schema/grants passed.')
        finally:
            for name in reversed(databases):
                system.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            system.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(runtime)))


def checks(settings, owner, accounts, operations, records, fixture):
    service, owners = CloudIdentityCorrections(settings, operations), CloudOwner(settings, operations)
    catalog = CloudPublicCatalog(settings, operations)
    actors = {name: row['app_user_id'] for name, row in records.items()}
    listing, individual = fixture['listing'], fixture['individual']

    def snapshot():
        with connect(settings, 'chronicle') as con:
            return {table: [dict(row) for row in con.execute(sql.SQL('SELECT * FROM {} ORDER BY id').format(sql.Identifier(table)))]
                    for table in TABLES}

    def detail(target=listing, name='a', **paging):
        row = service.detail(actors[name], target, **paging)
        assert set(row) == DETAIL_FIELDS and set(row['individual']) == IDENTITY_FIELDS
        assert set(row['listing']) == {'id', 'individual_id', 'occurred_at'}
        assert row['listing']['id'] == str(target)
        assert re.fullmatch('[0-9a-f]{64}', row['revision'])
        assert type(row['can_write']) is bool
        for correction in row['items']:
            assert set(correction) == CORRECTION_FIELDS
            assert int(correction['id']) > 2**53 and correction['target_claim_id'] == str(target)
            assert correction['individual_id'] == row['individual']['id']
            assert all(set(change) == {'field_name', 'old_value', 'new_value'} and change['field_name'] in FIELDS
                       for change in correction['changes'])
        return row

    def data(target=listing, **changes):
        current = detail(target)
        result = {field: current['individual'][field] for field in FIELDS}
        result.update(revision=current['revision'], reason=PRIVATE, model='Corrected model')
        return result | changes

    def create(payload=None, target=listing):
        before = detail(target)
        payload = data(target) if payload is None else payload
        result = service.create(actors['a'], target, payload)
        assert set(result) == {'correction', 'detail'}
        correction, current = result['correction'], result['detail']
        assert set(correction) == CORRECTION_FIELDS and current == detail(target)
        assert correction in current['items'] and correction['status'] == 'active'
        assert correction['verification_status'] == 'positive'
        assert correction['occurred_at'] == before['listing']['occurred_at']
        expected = {field: (before['individual'][field], current['individual'][field]) for field in FIELDS
                    if before['individual'][field] != current['individual'][field]}
        assert {change['field_name']: (change['old_value'], change['new_value']) for change in correction['changes']} == expected
        assert current['revision'] != before['revision']
        with connect(settings, 'chronicle') as con:
            stored = con.execute('SELECT * FROM claims WHERE id=%s', (int(correction['id']),)).fetchone()
            assert stored['author_user_id'] == records['a']['id'] and stored['observation_id'] is None
            assert stored['claim_type'] == 'identity_correction' and stored['target_claim_id'] == target
        return result

    rows = service.list(actors['a'])
    assert set(rows) == {'items', 'next_after', 'can_write'} and len(rows['items']) == 2
    assert all(set(row) == LIST_FIELDS and set(row['individual']) == IDENTITY_FIELDS for row in rows['items'])
    assert {row['id'] for row in rows['items']} == {str(listing), str(fixture['other_listing'])}
    assert all(int(row['id']) > 2**53 for row in rows['items'])
    page = service.list(actors['a'], limit=1)
    rest = service.list(actors['a'], after=int(page['next_after']), limit=1)
    assert len(page['items']) == len(rest['items']) == 1 and page['items'][0]['id'] != rest['items'][0]['id']
    assert rest['next_after'] is None
    for name in ('b', 'c', 'admin'):
        assert service.list(actors[name])['items'] == []
        rejected(GuitarMissing, lambda: detail(name=name))
        rejected(GuitarMissing, lambda: service.create(actors[name], listing, data()))
    for target in (fixture['hidden_claim'], fixture['absent'], 9223372036854775807):
        rejected(GuitarMissing, lambda: detail(target))
    # An inactive authored Listing disappears instead of becoming writable.
    with connect(owner, 'chronicle') as con:
        con.execute("UPDATE claims SET status='inactive' WHERE id=%s", (listing,))
    try:
        assert str(listing) not in {row['id'] for row in service.list(actors['a'])['items']}
        rejected(GuitarMissing, lambda: detail())
    finally:
        with connect(owner, 'chronicle') as con:
            con.execute("UPDATE claims SET status='active' WHERE id=%s", (listing,))

    before = snapshot()
    old_payload = data(manufacturer='  Gibson  ', model='  Corrected model  ', year=' 1967 ', serial_number='  FIX-001  ')
    first = create(old_payload)
    after = snapshot()
    assert first['detail']['individual'] == dict(id=str(individual), manufacturer='Gibson', model='Corrected model', year='1967', serial_number='FIX-001')
    source_before = next(row for row in before['claims'] if row['id'] == listing)
    assert next(row for row in after['claims'] if row['id'] == listing) == source_before
    for table in ('claim_listing_items', 'media_assets', 'claim_evidence', 'claim_source_evidence',
                  'observations', 'notifications', 'claim_responses'):
        assert before[table] == after[table], table
    for old in before['individuals']:
        new = next(row for row in after['individuals'] if row['id'] == old['id'])
        assert all(old[key] == new[key] for key in ('current_owner_user_id', 'location_country', 'location_region'))
    classifications = lambda state: [(r['user_id'], r['individual_id'], r['ownership_status']) for r in state['user_guitars']]
    assert classifications(before) == classifications(after)
    assert next(row for row in after['individuals'] if row['id'] == individual)['current_owner_user_id'] == records['b']['id']
    rejected(ClaimConflict, lambda: service.create(actors['a'], listing, old_payload))
    assert snapshot() == after
    with connect(settings, 'chronicle') as con:
        saved = con.execute('SELECT * FROM claims WHERE id=%s', (int(first['correction']['id']),)).fetchone()
        owner_revision = content_revision(ObservationConnection(con), saved)
    for name in ('a', 'b'):
        assert first['correction']['id'] not in {row['id'] for row in owners.pending(actors[name], individual)['items']}
        for stance in ('positive', 'negative', 'unverified'):
            rejected(ValueError, lambda: owners.respond(actors[name], individual, int(first['correction']['id']),
                     {'stance': stance, 'revision': owner_revision}))
    assert owners.pending(actors['a'], individual)['items'] == []

    # Public identity/search follow the snapshot; private reason/diff/author and
    # Listing proof references never become new public history fields.
    public = catalog.detail(None, individual)
    assert all(public[field] == first['detail']['individual'][field] for field in FIELDS)
    assert str(individual) in {row['id'] for row in catalog.list(q='FIX-001')['items']}
    assert str(individual) not in {row['id'] for row in catalog.list(q='MEDIA-' + str(individual))['items']}
    history = catalog.chronicle(None, individual)
    public_text = json.dumps({'guitar': public, 'history': history})
    assert PRIVATE not in public_text and 'old_value' not in public_text and 'new_value' not in public_text
    assert 'storage_path' not in public_text and 'gcs-content-v1:' not in public_text and 'author_user_id' not in public_text

    # Exact bounded fields, nullable model/year/reason, Unicode and no-op rules.
    stable = snapshot()
    valid = data(model='Another model')
    invalid = [valid | {'unexpected': True}, {k: v for k, v in valid.items() if k != 'reason'},
               valid | {'revision': 'x'}, valid | {'manufacturer': ' '}, valid | {'serial_number': None},
               valid | {'author_user_id': records['b']['id']}, valid | {'verification_status': 'negative'},
               valid | {'occurred_at': '2026-06-01'}, valid | {'target_claim_id': listing}]
    for field, limit in (('manufacturer', 200), ('model', 200), ('year', 40), ('serial_number', 200), ('reason', 2000)):
        invalid.extend(valid | {field: value} for value in ('x' * (limit + 1), '\x00', 42, True, [], {}))
    invalid.append({**{field: detail()['individual'][field] for field in FIELDS}, 'revision': detail()['revision'], 'reason': PRIVATE})
    for payload in invalid:
        rejected(ValueError, lambda: service.create(actors['a'], listing, payload))
        assert snapshot() == stable
    create(data(model=None, year=None, reason=None))
    create(data(model='😀' * 200, year='年' * 40, reason='記' * 2000))
    page = detail(limit=1)
    assert len(page['items']) == 1 and page['next_after']
    second_page = detail(after=int(page['next_after']), limit=1)
    assert second_page['items'][0]['id'] != page['items'][0]['id']
    for paging in ({'limit': 0}, {'limit': 51}, {'limit': True}, {'after': -1}, {'after': True}):
        rejected(ValueError, lambda: service.list(actors['a'], **paging))
        rejected(ValueError, lambda: detail(**paging))

    # Both target facts and current snapshot values participate in CAS, even
    # when the updater did not change updated_at.
    for table, column, value, identifier in (('claims', 'body', PRIVATE + '-target-changed', listing),
                ('individuals', 'year', '1988', individual)):
        stale = data(model='Stale preview')
        with connect(owner, 'chronicle') as con:
            old = con.execute(sql.SQL('SELECT {} FROM {} WHERE id=%s').format(sql.Identifier(column), sql.Identifier(table)), (identifier,)).fetchone()[column]
            con.execute(sql.SQL('UPDATE {} SET {}=%s WHERE id=%s').format(sql.Identifier(table), sql.Identifier(column)), (value, identifier))
        try:
            rejected(ClaimConflict, lambda: service.create(actors['a'], listing, stale))
        finally:
            with connect(owner, 'chronicle') as con:
                con.execute(sql.SQL('UPDATE {} SET {}=%s WHERE id=%s').format(sql.Identifier(table), sql.Identifier(column)), (old, identifier))

    other = detail(fixture['other_listing'])['individual']
    collision = data(manufacturer='  FENDER ', model='Deliberately different model', serial_number=' media-' + str(fixture['other']) + ' ')
    before = snapshot()
    rejected(ClaimConflict, lambda: service.create(actors['a'], listing, collision))
    assert snapshot() == before and other['manufacturer'] == 'Fender'
    race = Barrier(2)
    candidates = [(target, data(target, manufacturer='Collision Maker', model='Distinct ' + str(index), serial_number='RACE-001'))
                  for index, target in enumerate((listing, fixture['other_listing']))]
    def contender(candidate):
        target, payload = candidate
        race.wait(timeout=10)
        try:
            return service.create(actors['a'], target, payload)
        except ClaimConflict:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(contender, candidates))
    assert sum(result is not None for result in results) == 1
    loser = candidates[results.index(None)][0]
    rejected(ClaimConflict, lambda: service.create(actors['a'], loser,
        data(loser, manufacturer=' collision maker ', model='Different again', serial_number=' race-001 ')))
    with connect(settings, 'chronicle') as con:
        assert con.execute("SELECT COUNT(*) AS n FROM individuals WHERE normalized_manufacturer=%s AND normalized_serial=%s",
                           (normalize_manufacturer("Collision Maker"), normalize_serial("RACE-001"))).fetchone()['n'] == 1

    # Failure while appending field evidence rolls the Claim and snapshot back.
    for table in ('claims', 'claim_identity_items'):
        before = snapshot()
        with reject_new_rows(owner, table):
            rejected(errors.CheckViolation, lambda: service.create(actors['a'], listing, data(model='Rollback ' + table)))
        assert snapshot() == before
    # A lost commit acknowledgement must remain discoverable. Replaying the
    # exact prior preview cannot create a second correction.
    real_transaction = service.transaction
    @contextmanager
    def lost_acknowledgement(*args, **kwargs):
        with real_transaction(*args, **kwargs) as result:
            yield result
        if kwargs.get('write'):
            raise RuntimeError('Synthetic acknowledgement lost')
    payload = data(model='Unknown committed model', reason=PRIVATE + '-unknown')
    before = snapshot()
    with patch.object(service, 'transaction', lost_acknowledgement):
        rejected(RuntimeError, lambda: service.create(actors['a'], listing, payload))
    assert len(snapshot()['claims']) == len(before['claims']) + 1
    assert any(row['body'] == PRIVATE + '-unknown' for row in detail()['items'])
    rejected(ClaimConflict, lambda: service.create(actors['a'], listing, payload))
    hybrid_collision_checks(owner, records, service, fixture, data, snapshot)
    stored_bounds_checks(owner, actors['a'], service, fixture, data, snapshot)
    dispute_checks(owner, records, service, fixture, data, snapshot)
    fence_checks(owner, accounts, operations, records, service, fixture, data, snapshot)
    http_checks(owner, accounts, operations, records, service, fixture, data)



def hybrid_collision_checks(owner, records, service, fixture, data, snapshot):
    """The reducer's final Maker+Serial must be unique, not only the proposal.

    A later date's correction can supply Serial while this older correction
    supplies Maker. Different Models do not excuse the resulting collision.
    """
    actor = records['a']['app_user_id']
    def listing(con, individual, maker, model, serial, date):
        claim = con.execute("""INSERT INTO claims(individual_id,author_user_id,claim_type,
            verification_status,occurred_at,created_at,updated_at)
            VALUES(%s,%s,'listing','positive',%s,%s,%s) RETURNING id""",
            (individual, records['a']['id'], date, date, date)).fetchone()['id']
        for key, value in (('manufacturer', maker), ('model', model), ('serial_number', serial),
                           ('owner_user_id', str(records['b']['id']))):
            con.execute("INSERT INTO claim_listing_items(claim_id,field_name,value_text,created_at) VALUES(%s,%s,%s,%s)",
                        (claim, key, value, date))
        BoundRepository(ObservationConnection(con))._rebuild_individual_snapshot_in_connection(ObservationConnection(con), individual)
        return claim
    individual, other = fixture['absent'] + 100, fixture['absent'] + 101
    with connect(owner, 'chronicle') as con:
        for identifier in (individual, other):
            con.execute("INSERT INTO individuals(id,manufacturer,normalized_manufacturer,created_at,updated_at) VALUES(%s,'Fixture','fixture','2020-01-01','2020-01-01')", (identifier,))
        old = listing(con, individual, 'Fender', 'A', 'ORIGINAL', '2020-01-01')
        new = listing(con, individual, 'Fender', 'A', 'ORIGINAL', '2021-01-01')
        listing(con, other, 'Gibson', 'B', 'LATER', '2021-01-01')
    later = service.create(actor, new, data(new, model='A', serial_number='LATER'))
    assert later['detail']['individual']['serial_number'] == 'LATER'
    proposed = data(old, manufacturer='Gibson', model='A', serial_number='EARLIER')
    before = snapshot()
    rejected(ClaimConflict, lambda: service.create(actor, old, proposed))
    assert snapshot() == before, 'Final-snapshot collision must roll back Claim, items and all projections'
    # Keep existing chronology: the same older edit with a noncolliding Maker
    # is allowed, but the later-date Serial remains the current snapshot.
    accepted = service.create(actor, old, data(old, manufacturer='Gretsch', model='A', serial_number='EARLIER'))
    assert accepted['correction']['occurred_at'] == '2020-01-01'
    assert accepted['detail']['individual']['manufacturer'] == 'Gretsch'
    assert accepted['detail']['individual']['serial_number'] == 'LATER'
    assert any(row['field_name'] == 'serial_number' and row['new_value'] == 'EARLIER'
               for row in accepted['correction']['changes'])


def stored_bounds_checks(owner, actor, service, fixture, data, snapshot):
    """Legacy or corrupted oversized state must fail closed, never truncate."""
    listing, individual = fixture['listing'], fixture['individual']
    correction = int(service.detail(actor, listing)['items'][0]['id'])
    for table, column, identifier, value in (('individuals', 'model', individual, 'x' * 201),
            ('claims', 'body', correction, 'x' * 2001), ('claims', 'created_at', correction, 'x' * 41)):
        valid = data(model='Never commit against unreviewable state')
        with connect(owner, 'chronicle') as con:
            old = con.execute(sql.SQL('SELECT {} FROM {} WHERE id=%s').format(sql.Identifier(column), sql.Identifier(table)), (identifier,)).fetchone()[column]
            con.execute(sql.SQL('UPDATE {} SET {}=%s WHERE id=%s').format(sql.Identifier(table), sql.Identifier(column)), (value, identifier))
        try:
            rejected(RuntimeError, lambda: service.detail(actor, listing))
            if table == 'individuals':
                rejected(RuntimeError, lambda: service.list(actor))
            before = snapshot()
            # Current malformed identity is rejected before revision comparison;
            # changed malformed history may instead invalidate the old revision.
            rejected((RuntimeError, ClaimConflict), lambda: service.create(actor, listing, valid))
            assert snapshot() == before
        finally:
            with connect(owner, 'chronicle') as con:
                con.execute(sql.SQL('UPDATE {} SET {}=%s WHERE id=%s').format(sql.Identifier(table), sql.Identifier(column)), (old, identifier))


def dispute_checks(owner, records, service, fixture, data, snapshot):
    actor, individual, listing = records['a']['app_user_id'], fixture['individual'], fixture['listing']
    before_revision = service.detail(actor, listing)['revision']
    payload = data(model='Blocked during dispute')
    with connect(owner, 'chronicle') as con:
        dispute = con.execute("""INSERT INTO ownership_disputes(individual_id,owner_id,locked_owner_id,created_at,updated_at)
            VALUES(%s,%s,%s,'2026-10-07','2026-10-07') RETURNING id""",
            (individual, records['b']['id'], records['b']['id'])).fetchone()['id']
    try:
        current = service.detail(actor, listing)
        assert current['can_write'] is False and current['revision'] != before_revision
        before = snapshot()
        rejected(ClaimConflict, lambda: service.create(actor, listing, payload))
        rejected(ClaimConflict, lambda: service.create(actor, listing, payload | {'revision': current['revision']}))
        assert snapshot() == before
    finally:
        with connect(owner, 'chronicle') as con:
            con.execute('DELETE FROM ownership_disputes WHERE id=%s', (dispute,))


def fence_checks(owner, accounts, operations, records, service, fixture, data, snapshot):
    actor, admin, listing = records['a']['app_user_id'], records['admin']['app_user_id'], fixture['listing']
    payload = data(model='Not written under fences')
    def mode(value):
        operations.set_mode(admin, mode=value, message='', version=operations.details(admin)['version'])
    for column, value, restored in (('disabled', 1, 0), ('ban_status', 'ban', 'normal'), ('account_type', 'source', 'user')):
        before = snapshot()
        with connect(owner, 'accounts') as con:
            con.execute(sql.SQL('UPDATE account_records SET {}=%s WHERE app_user_id=%s').format(sql.Identifier(column)), (value, actor))
        try:
            for action in (lambda: service.list(actor), lambda: service.detail(actor, listing), lambda: service.create(actor, listing, payload)):
                rejected(PermissionError, action)
            assert snapshot() == before
        finally:
            with connect(owner, 'accounts') as con:
                con.execute(sql.SQL('UPDATE account_records SET {}=%s WHERE app_user_id=%s').format(sql.Identifier(column)), (restored, actor))
            accounts.drain_projection()
    mode('read_only')
    assert service.list(actor)['can_write'] is False and service.detail(actor, listing)['can_write'] is False
    rejected(ServiceRestricted, lambda: service.create(actor, listing, payload))
    mode('admin_only')
    rejected(ServiceRestricted, lambda: service.list(actor))
    assert service.list(admin)['items'] == []
    rejected(GuitarMissing, lambda: service.detail(admin, listing))
    mode('offline')
    for who in (actor, admin):
        rejected(ServiceRestricted, lambda: service.list(who))
        rejected(ServiceRestricted, lambda: service.create(who, listing, payload))
    mode('normal')
    # Existing maintenance/crawl mutex remains the shared write boundary.
    with connect(owner, 'operations') as con:
        con.execute('SELECT pg_advisory_xact_lock(79432190)')
        rejected(ClaimConflict, lambda: service.create(actor, listing, payload))


def http_checks(owner, accounts, operations, records, service, fixture, data):
    class Verifier:
        def __init__(self):
            self.accounts = accounts
        def verify(self, *, bearer_token):
            if bearer_token == 'unavailable':
                raise RuntimeError(PRIVATE)
            if bearer_token not in (*records, 'unverified'):
                raise PermissionError(PRIVATE)
            return VerifiedIdentity(ISSUER, 'a' if bearer_token == 'unverified' else bearer_token, '', bearer_token != 'unverified')
    api = FastAPI()
    api.include_router(identity_correction_router(Verifier(), service))
    path = BASE + '/' + str(fixture['listing'])
    auth = lambda actor='a': {'Authorization': 'Bearer ' + actor}
    def private(response):
        assert response.headers['cache-control'] == 'private, no-store'
        assert response.headers['vary'] == 'Authorization'
        assert response.headers['x-content-type-options'] == 'nosniff'
    with TestClient(api) as client:
        for actor, code in ((None, 401), ('bad', 401), ('unverified', 403), ('unavailable', 503)):
            headers = auth(actor) if actor else {}
            for url in (BASE, path):
                response = client.get(url, headers=headers)
                assert response.status_code == code and PRIVATE not in response.text
            assert client.post(path, headers=headers, json=data()).status_code == code
        for url in (BASE, path):
            response = client.get(url, headers=auth())
            assert response.status_code == 200
            private(response)
            for query in ('?limit=0', '?limit=51', '?limit=1&limit=2', '?after=0', '?after=-1', '?author=1'):
                assert client.get(url + query, headers=auth()).status_code == 400
        for identifier in ('0', '-1', '1.0', '9223372036854775808'):
            assert client.get(BASE + '/' + identifier, headers=auth()).status_code == 400
        for actor in ('b', 'c', 'admin'):
            response = client.get(path, headers=auth(actor))
            assert response.status_code == 404 and PRIVATE not in response.text
            assert client.post(path, headers=auth(actor), json=data()).status_code == 404
        valid = data(model='HTTP corrected model')
        for extra, code in (({'Origin': 'https://untrusted.invalid'}, 403), ({'Sec-Fetch-Site': 'cross-site'}, 403),
                            ({'Content-Encoding': 'gzip'}, 400)):
            response = client.post(path, headers=auth() | extra, json=valid)
            assert response.status_code == code
            private(response)
        for raw in ('[]', 'null', '{"revision":"a","revision":"b"}', '{broken', '"string"'):
            assert client.post(path, headers=auth() | {'Content-Type': 'application/json'}, content=raw).status_code == 400
        assert client.post(path + '?after=1', headers=auth(), json=valid).status_code == 400
        assert client.post(path, headers=auth(), content=json.dumps(valid)).status_code == 400
        assert client.post(path, headers=auth() | {'Content-Type': 'application/json'}, content='x' * (512 * 1024 + 1)).status_code == 413
        response = client.post(path, headers=auth(), json=valid)
        assert response.status_code == 200, response.text
        private(response)
        assert response.json()['correction']['verification_status'] == 'positive'
        assert client.post(path, headers=auth(), json=valid).status_code == 409
        # Non-JSON results must not reveal SQL, source paths or private content.
        with patch.object(service, 'create', side_effect=RuntimeError(PRIVATE + ' SELECT credentials')):
            response = client.post(path, headers=auth(), json=valid)
            assert response.status_code == 503 and PRIVATE not in response.text and 'SELECT' not in response.text
            private(response)
