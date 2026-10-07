"""Synthetic self-only favorites acceptance on disposable loopback PostgreSQL.

Import/compilation opens no connection. The aggregate PostgreSQL runner invokes
run(port) only on an approved local test cluster. Existing bootstrap/migrations
create throwaway databases and their unchanged restricted runtime role. No live
account, token, photo, cloud service, new migration or grant is involved.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from threading import Barrier
from unittest.mock import patch
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
import psycopg
from psycopg import errors, sql

from postgres_event_claim_checks import structure
from postgres_media_claim_checks import rejected, reject_new_rows
from ygc.admin_bootstrap_job import grant_first_admin
from ygc.claim_revision import ClaimConflict
from ygc.cloud_favorite_routes import favorite_router
from ygc.cloud_favorites import CloudFavorites
from ygc.cloud_guitars import GuitarMissing
from ygc.cloud_public_catalog import CloudPublicCatalog, GUITAR_FIELDS
from ygc.db.postgres import PostgresSettings, bootstrap, connect, migrate
from ygc.db.postgres_accounts import PostgresAccounts
from ygc.db.postgres_operations import PostgresOperations, ServiceRestricted
from ygc.identity_platform import VerifiedIdentity

BASE = '/api/auth/favorites'
ISSUER = 'local-private-favorite-contract'
BIG = 9007199254740993
PRIVATE = 'FAVORITE-PRIVATE-DO-NOT-PUBLISH'
STAMP = '2026-10-01T00:00:00+00:00'


class Workflow:
    def __init__(self, settings, owner, accounts, operations, records):
        self.settings, self.owner = settings, owner
        self.accounts, self.operations, self.records = accounts, operations, records
        self.service = CloudFavorites(settings, operations)
        self.catalog = CloudPublicCatalog(settings, operations)

    def actor(self, name='a'):
        return self.records[name]['app_user_id']

    def user(self, name='a'):
        return self.records[name]['id']

    def canonical(self, name, **changes):
        with connect(self.owner, 'accounts') as con:
            assignments = sql.SQL(',').join(sql.SQL('{}=%s').format(sql.Identifier(key)) for key in changes)
            con.execute(sql.SQL('UPDATE account_records SET {} WHERE id=%s').format(assignments),
                        (*changes.values(), self.user(name)))

    def mode(self, value):
        self.operations.set_mode(self.actor('admin'), mode=value, message='',
            version=self.operations.details(self.actor('admin'))['version'])

    def snapshot(self):
        result = {}
        for target in ('accounts', 'chronicle', 'operations'):
            with connect(self.settings, target) as con:
                tables = [row['tablename'] for row in con.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
                result[target] = {table: [row['value'] for row in con.execute(sql.SQL(
                    'SELECT to_jsonb(t) AS value FROM {} t ORDER BY to_jsonb(t)::text').format(sql.Identifier(table)))]
                    for table in tables}
        return result

    def unchanged(self, failure, operation):
        before = self.snapshot()
        rejected(failure, operation)
        assert self.snapshot() == before, 'Rejected favorite operation wrote data'

    def favorite_rows(self):
        with connect(self.settings, 'chronicle') as con:
            return [dict(row) for row in con.execute('SELECT * FROM user_favorites ORDER BY user_id,individual_id')]


def favorite_changes_only(before, after):
    assert before['accounts'] == after['accounts']
    assert before['operations'] == after['operations']
    for table in before['chronicle']:
        if table != 'user_favorites':
            assert before['chronicle'][table] == after['chronicle'][table], 'Favorites changed ' + table


def seed(w):
    with connect(w.owner, 'chronicle') as con:
        for index in range(10):
            individual = BIG + index
            con.execute('''INSERT INTO individuals(id,manufacturer,model,finish,year,serial_number,
                normalized_manufacturer,normalized_model,normalized_serial,location_country,
                location_region,current_owner_name,current_owner_user_id,created_at,updated_at)
                VALUES(%s,'Fender',%s,'Sunburst','1960',%s,'fender',%s,%s,%s,%s,%s,%s,%s,%s)''',
                (individual, 'Synthetic ' + str(index), str(individual), 'synthetic ' + str(index),
                 str(individual), PRIVATE, PRIVATE, PRIVATE, w.user('b'), STAMP, STAMP))
            if index != 8:  # No public Claim at all.
                claim = con.execute('''INSERT INTO claims(individual_id,author_user_id,claim_type,
                    status,verification_status,body,occurred_at,created_at,updated_at)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
                    (individual, w.user({4: 'banned', 5: 'silent'}.get(index, 'author')),
                     'private_kind' if index == 6 else 'listing',
                     'inactive' if index == 3 else 'active',
                     {1: 'unverified', 2: 'negative', 7: 'private_state'}.get(index, 'positive'),
                     PRIVATE, STAMP, STAMP, STAMP)).fetchone()['id']
                identity_claims = [claim]
                if index in (3, 6):
                    # Observation keeps identity from active Listing Claims,
                    # even from BAN authors. This permanent banned scaffold
                    # supplies a valid rebuild identity without making an
                    # inactive-only or unsupported-kind target public.
                    identity_claims.append(con.execute('''INSERT INTO claims(individual_id,
                        author_user_id,claim_type,status,verification_status,occurred_at,created_at,updated_at)
                        VALUES(%s,%s,'listing','active','positive',%s,%s,%s) RETURNING id''',
                        (individual, w.user('banned'), STAMP, STAMP, STAMP)).fetchone()['id'])
                for identity_claim in identity_claims:
                    for field, value in (('manufacturer', 'Fender'), ('model', 'Synthetic ' + str(index)),
                                         ('serial_number', str(individual))):
                        con.execute('''INSERT INTO claim_listing_items(claim_id,field_name,value_text,created_at)
                            VALUES(%s,%s,%s,%s)''', (identity_claim, field, value, STAMP))
            con.execute('INSERT INTO user_favorites VALUES(%s,%s,%s)', (w.user(), individual, STAMP))
        con.execute('INSERT INTO user_favorites VALUES(%s,%s,%s)', (w.user('b'), BIG + 1, STAMP))
        con.execute('DELETE FROM individuals WHERE id=%s', (BIG + 9,))


def relation_checks(w):
    before = w.snapshot()
    public = [str(BIG + 2), str(BIG + 1), str(BIG)]
    assert [row['id'] for row in w.catalog.list()['items']] == public
    first = w.service.list(w.actor(), limit=2)
    assert first['total'] == '3' and first['next_after'] == str(BIG + 1)
    assert [row['id'] for row in first['items']] == public[:2]
    second = w.service.list(w.actor(), after=BIG + 1, limit=2)
    assert second['total'] == '3' and second['next_after'] is None
    assert [row['id'] for row in second['items']] == public[2:]
    for row in first['items'] + second['items']:
        assert set(row) == {'id', *GUITAR_FIELDS, 'photo'} and row['photo'] is None
    assert PRIVATE not in json.dumps(first)
    assert w.service.list(w.actor('b'))['total'] == '1'
    assert w.service.detail(w.actor('b'), BIG)['favorite'] is False
    assert w.service.detail(w.actor(), BIG)['favorite'] is True
    assert w.snapshot() == before, 'GETs performed data repair or wrote history'
    # Public privacy preferences never publish another member's favorites.
    w.canonical('a', birth_visibility='Public', residence_visibility='Public',
                bio_visibility='Public', avatar_visibility='Public')
    w.accounts.drain_projection()
    assert w.service.list(w.actor('b'))['total'] == '1'
    assert w.service.list(w.actor('admin'))['total'] == '0'
    before = w.snapshot()
    for _ in range(2):
        assert w.service.set(w.actor(), BIG, favorite=True) == {'individual_id': str(BIG), 'favorite': True}
    assert w.snapshot() == before, 'Repeated add changed the first timestamp'
    for _ in range(2):
        assert w.service.set(w.actor(), BIG + 1, favorite=False)['favorite'] is False
    assert w.service.detail(w.actor('b'), BIG + 1)['favorite'] is True
    favorite_changes_only(before, w.snapshot())
    w.service.set(w.actor(), BIG + 1, favorite=True)
    for individual in (*range(BIG + 3, BIG + 10), BIG + 99999):
        for name in ('a', 'b', 'admin'):
            w.unchanged(GuitarMissing, lambda: w.service.detail(w.actor(name), individual))
            w.unchanged(GuitarMissing, lambda: w.service.set(w.actor(name), individual, favorite=True))
        before = w.snapshot()
        assert w.service.set(w.actor(), individual, favorite=False) == {'individual_id': str(individual), 'favorite': False}
        favorite_changes_only(before, w.snapshot())
    assert w.service.list(w.actor())['total'] == '3'


def fence_checks(w):
    operations = (lambda: w.service.list(w.actor()),
                  lambda: w.service.detail(w.actor(), BIG),
                  lambda: w.service.set(w.actor(), BIG, favorite=True),
                  lambda: w.service.set(w.actor(), BIG, favorite=False))
    # Canonical self revocation always precedes relation access, even when the
    # Chronicle user projection is stale. Silent BAN remains self-accessible.
    for changes, restore in (({'disabled': 1}, {'disabled': 0}),
                             ({'ban_status': 'ban'}, {'ban_status': 'normal'}),
                             ({'account_type': 'source'}, {'account_type': 'user'})):
        w.canonical('a', **changes)
        for operation in operations:
            w.unchanged(PermissionError, operation)
        w.canonical('a', **restore)
        w.accounts.drain_projection()
    w.canonical('a', display_name='New canonical favorite owner')
    for operation in operations:
        w.unchanged(ValueError, operation)
    w.accounts.drain_projection()
    # An author pending BAN cannot expose an existing hidden ID through a
    # projection error that an unknown ID would not produce.
    for ban in ('ban', 'silent_ban'):
        w.canonical('author', ban_status=ban)
        w.unchanged(ValueError, operations[0])
        for individual in (BIG, BIG + 3, BIG + 99999):
            w.unchanged(GuitarMissing, lambda: w.service.detail(w.actor(), individual))
            w.unchanged(GuitarMissing, lambda: w.service.set(w.actor(), individual, favorite=True))
        before = w.snapshot()
        assert w.service.set(w.actor(), BIG, favorite=False) == {'individual_id': str(BIG), 'favorite': False}
        favorite_changes_only(before, w.snapshot())
        w.accounts.drain_projection()
        assert w.service.list(w.actor()) == {'items': [], 'total': '0', 'next_after': None}
        w.canonical('author', ban_status='normal')
        w.accounts.drain_projection()
        w.service.set(w.actor(), BIG, favorite=True)
    # Missing and mismapped target receipts must be indistinguishable from an
    # unknown target; missing self receipt still refuses all self access.
    for name in ('author', 'a'):
        with connect(w.owner, 'chronicle') as con:
            receipt = dict(con.execute('SELECT * FROM account_projection_receipts WHERE account_id=%s', (w.user(name),)).fetchone())
            con.execute('DELETE FROM account_projection_receipts WHERE account_id=%s', (w.user(name),))
        try:
            failure = GuitarMissing if name == 'author' else ValueError
            w.unchanged(failure, lambda: w.service.detail(w.actor(), BIG))
            w.unchanged(failure, lambda: w.service.set(w.actor(), BIG, favorite=True))
        finally:
            with connect(w.owner, 'chronicle') as con:
                con.execute('INSERT INTO account_projection_receipts(account_id,app_user_id,revision,applied_at) VALUES(%s,%s,%s,%s)',
                    tuple(receipt[key] for key in ('account_id', 'app_user_id', 'revision', 'applied_at')))
    # A retained Chronicle-only author must not create a private-ID oracle.
    orphan = BIG + 5000
    with connect(w.owner, 'chronicle') as con:
        con.execute("INSERT INTO users(id,display_name,account_type,ban_status,app_user_id,created_at,updated_at) VALUES(%s,'Orphan','user','normal',%s,%s,%s)",
                    (orphan, 'synthetic-orphan-author', STAMP, STAMP))
        primary = con.execute('SELECT id FROM claims WHERE individual_id=%s AND author_user_id=%s',
                              (BIG + 3, w.user('author'))).fetchone()['id']
        con.execute('UPDATE claims SET author_user_id=%s WHERE id=%s', (orphan, primary))
    try:
        for status in ('inactive', 'active'):
            with connect(w.owner, 'chronicle') as con:
                con.execute('UPDATE claims SET status=%s WHERE id=%s', (status, primary))
            for individual in (BIG + 3, BIG + 99999):
                w.unchanged(GuitarMissing, lambda: w.service.detail(w.actor(), individual))
                w.unchanged(GuitarMissing, lambda: w.service.set(w.actor(), individual, favorite=True))
    finally:
        with connect(w.owner, 'chronicle') as con:
            con.execute("UPDATE claims SET author_user_id=%s,status='inactive' WHERE id=%s", (w.user('author'), primary))
            con.execute('DELETE FROM users WHERE id=%s', (orphan,))
    for field, changed in (('app_user_id', 'synthetic-mismapped-receipt'), ('revision', 999999)):
        with connect(w.owner, 'chronicle') as con:
            original = con.execute(sql.SQL('SELECT {} FROM account_projection_receipts WHERE account_id=%s').format(sql.Identifier(field)), (w.user(),)).fetchone()[field]
            con.execute(sql.SQL('UPDATE account_projection_receipts SET {}=%s WHERE account_id=%s').format(sql.Identifier(field)), (changed, w.user()))
        try:
            for operation in operations:
                w.unchanged(ValueError, operation)
        finally:
            with connect(w.owner, 'chronicle') as con:
                con.execute(sql.SQL('UPDATE account_projection_receipts SET {}=%s WHERE account_id=%s').format(sql.Identifier(field)), (original, w.user()))
    for mode in ('read_only', 'offline', 'admin_only'):
        w.mode(mode)
        if mode == 'read_only':
            before = w.snapshot()
            operations[0](); operations[1]()
            assert w.snapshot() == before
        else:
            w.unchanged(ServiceRestricted, operations[0])
            w.unchanged(ServiceRestricted, operations[1])
        for operation in operations[2:]:
            w.unchanged(ServiceRestricted, operation)
        if mode == 'offline':
            w.unchanged(ServiceRestricted, lambda: w.service.list(w.actor('admin')))
        if mode == 'admin_only':
            assert w.service.list(w.actor('admin'))['total'] == '0'
            w.service.set(w.actor('admin'), BIG, favorite=True)
            assert w.service.list(w.actor('admin'))['total'] == '1'
            w.service.set(w.actor('admin'), BIG, favorite=False)
        w.mode('normal')
    with connect(w.owner, 'operations') as con:
        con.execute('SELECT pg_advisory_xact_lock(79432190)')
        for operation in operations[2:]:
            w.unchanged(ClaimConflict, operation)
        assert w.service.list(w.actor())['total'] == '3'
    # Source, disabled and BAN actors cannot use the private relation; the
    # established Silent BAN policy still permits their self-only actions.
    for name in ('banned', 'disabled', 'source'):
        w.unchanged(PermissionError, lambda: w.service.list(w.actor(name)))
        w.unchanged(PermissionError, lambda: w.service.set(w.actor(name), BIG, favorite=True))
    w.service.set(w.actor('silent'), BIG, favorite=True)
    assert w.service.detail(w.actor('silent'), BIG)['favorite'] is True
    w.service.set(w.actor('silent'), BIG, favorite=False)
    # Canonical self, author and service-mode locks remain held while content
    # is used. Account revocation/mode changes cannot slip between checks/use.
    with w.service.transaction(w.actor(), individual=BIG):
        for target, statement, args in (
            ('accounts', 'UPDATE account_records SET disabled=1 WHERE id=%s', (w.user(),)),
            ('accounts', "UPDATE account_records SET ban_status='ban' WHERE id=%s", (w.user('author'),)),
            ('operations', "UPDATE settings SET mode='offline' WHERE id=1", ())):
            def blocked():
                with connect(w.owner, target) as con:
                    con.execute("SET LOCAL lock_timeout='50ms'")
                    con.execute(statement, args)
            rejected(errors.LockNotAvailable, blocked)


def concurrency_and_rollback_checks(w):
    for desired in (False, True):
        barrier = Barrier(2)
        def change(_):
            barrier.wait(timeout=10)
            try:
                return w.service.set(w.actor(), BIG, favorite=desired)
            except ClaimConflict:
                return None
        before = w.snapshot()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(change, range(2)))
        assert any(result is not None for result in results)
        # A contending maintenance mutex may ask for a retry; the same desired
        # state is always safe, with no duplicate row or timestamp replacement.
        for result in results:
            if result is None:
                w.service.set(w.actor(), BIG, favorite=desired)
        assert w.service.detail(w.actor(), BIG)['favorite'] is desired
        favorite_changes_only(before, w.snapshot())
        before = w.snapshot()
        w.service.set(w.actor(), BIG, favorite=desired)
        assert w.snapshot() == before
    w.service.set(w.actor(), BIG, favorite=False)
    before = w.snapshot()
    with reject_new_rows(w.owner, 'user_favorites'):
        rejected(errors.CheckViolation, lambda: w.service.set(w.actor(), BIG, favorite=True))
    assert w.snapshot() == before
    w.service.set(w.actor(), BIG, favorite=True)
    # Rechecking scope after the canonical locks catches a newly discovered
    # author, before the read or write can use unguarded participant state.
    original = w.service._participants
    calls = []
    def changed(connection, user, individual=None):
        scope = original(connection, user, individual)
        calls.append(True)
        return scope if len(calls) == 1 else scope | {w.user('b')}
    before = w.snapshot()
    with patch.object(w.service, '_participants', side_effect=changed):
        rejected(ClaimConflict, lambda: w.service.set(w.actor(), BIG, favorite=True))
    assert w.snapshot() == before


def http_checks(w):
    class Verifier:
        accounts = w.accounts
        def verify(self, *, bearer_token):
            if bearer_token not in w.records and bearer_token != 'unverified':
                raise PermissionError('Synthetic secret')
            return VerifiedIdentity(ISSUER, 'a' if bearer_token == 'unverified' else bearer_token,
                                    '', bearer_token != 'unverified')
    app = FastAPI()
    app.include_router(favorite_router(Verifier(), w.service))
    def headers(name='a'):
        return {'Authorization': 'Bearer ' + name}
    def check(response, expected):
        assert response.status_code == expected, response.text
        assert response.headers['cache-control'] == 'private, no-store'
        assert response.headers['vary'] == 'Authorization'
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert PRIVATE not in response.text
        return response
    with TestClient(app) as client:
        before = w.snapshot()
        for path in (BASE, BASE + '/' + str(BIG)):
            check(client.get(path), 401)
            check(client.get(path, headers={'Cookie': 'user_id=' + str(w.user())}), 401)
            check(client.get(path, headers=headers('unverified')), 403)
            check(client.get(path, headers=headers('banned')), 403)
        for query in ('user_id=1', 'actor=other', 'after=0', 'after=01', 'limit=51',
                      'limit=1&limit=2', 'after=9223372036854775808'):
            check(client.get(BASE + '?' + query, headers=headers()), 400)
        check(client.get(BASE, headers=[('Authorization', 'Bearer a'), ('Authorization', 'Bearer b')]), 401)
        check(client.get(BASE + f'?after={BIG + 2}&limit=2', headers=headers()), 200)
        check(client.request('GET', BASE, headers=headers(), content='{}'), 400)
        for body in ('{}', '{"favorite":1}', '{"favorite":true,"favorite":false}',
                     '{"favorite":true,"user_id":1}'):
            check(client.put(BASE + '/' + str(BIG), content=body,
                headers=headers() | {'Content-Type': 'application/json'}), 400)
        for individual in (BIG + 3, BIG + 8, BIG + 9, BIG + 99999):
            detail = check(client.get(BASE + '/' + str(individual), headers=headers()), 404)
            add = check(client.put(BASE + '/' + str(individual), json={'favorite': True}, headers=headers()), 404)
            assert detail.json() == add.json() == {'detail': 'Guitar not found.'}
        assert w.snapshot() == before
        for wanted in (False, False, True, True):
            response = check(client.put(BASE + '/' + str(BIG), json={'favorite': wanted}, headers=headers()), 200)
            assert response.json() == {'individual_id': str(BIG), 'favorite': wanted}
        assert check(client.get(BASE + '/' + str(BIG), headers=headers('b')), 200).json()['favorite'] is False
        favorite_changes_only(before, w.snapshot())


def run(port):
    prefix = 'ygctest_favorites_' + uuid.uuid4().hex[:10] + '_'
    runtime = prefix + 'app'
    owner = PostgresSettings('127.0.0.1', 'postgres', 'ygc-tests-only', port, prefix)
    settings = replace(owner, user=runtime)
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
            with connect(owner, 'accounts') as con:
                con.execute("SELECT setval(pg_get_serial_sequence('account_records','id'),%s,false)", (BIG + 1000,))
            accounts, operations = PostgresAccounts(settings), PostgresOperations(settings)
            records = {name: accounts.ensure_identity(issuer=ISSUER, subject=name,
                display_name='Synthetic ' + name) for name in
                ('admin', 'a', 'b', 'author', 'banned', 'silent', 'disabled', 'source')}
            assert grant_first_admin(settings, records['admin']['app_user_id'], 'local-favorite-test')
            w = Workflow(settings, owner, accounts, operations, records)
            w.canonical('banned', ban_status='ban')
            w.canonical('silent', ban_status='silent_ban')
            w.canonical('disabled', disabled=1)
            w.canonical('source', account_type='source')
            accounts.drain_projection()
            w.mode('normal')
            seed(w)
            relation_checks(w)
            fence_checks(w)
            concurrency_and_rollback_checks(w)
            http_checks(w)
            assert structure(owner, runtime) == original_structure
            print('PostgreSQL private favorites: canonical self-only relation, exact BIGINT pagination, '
                  'public-target privacy and totals, generic hidden IDs, canonical/projection/service/maintenance fences, '
                  'repeat/concurrent retry, rollback, unchanged schema/grants and no owner/Claim/media/profile side effects passed.')
        finally:
            for name in reversed(databases):
                system.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            system.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(runtime)))
