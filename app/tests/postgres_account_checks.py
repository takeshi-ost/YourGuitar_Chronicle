"""Real PostgreSQL registry/projection failures and Observation transitions."""
from concurrent.futures import ThreadPoolExecutor
import uuid
import psycopg
from psycopg import sql
from ygc.db.postgres import PostgresSettings, bootstrap, migrate, status, connect
from ygc.db.postgres_accounts import PostgresAccounts
from ygc.db.postgres_queries import ObservationConnection
from ygc.observation_evaluator import evaluate_observation
from ygc.db.postgres_ownership import PostgresOwnership
from ygc.platform_boundaries import ActorContext


def raises(kind, operation):
    try:
        operation()
    except kind:
        return
    raise AssertionError('Expected ' + kind.__name__)


def run(port):
    prefix = 'ygctest_' + uuid.uuid4().hex[:12] + '_'
    role = prefix + 'app'
    owner = PostgresSettings('127.0.0.1', 'postgres', 'ygc-tests-only', port, prefix)
    app = PostgresSettings('127.0.0.1', role, 'ygc-tests-only', port, prefix)
    store = PostgresAccounts(app)
    created = []
    with psycopg.connect(host='127.0.0.1', port=port, dbname='postgres', user='postgres', password='ygc-tests-only', autocommit=True) as admin:
        try:
            admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(role), sql.Literal('ygc-tests-only')))
            for target in ('accounts', 'chronicle'):
                name = owner.database(target)
                admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
                created.append(name)
                bootstrap(owner, target, role)
                assert migrate(owner, target, role) == [2]
                assert migrate(owner, target, role) == []
                assert not bootstrap(owner, target, role)
                assert status(app, target)['version'] == 2
                raises(ValueError, lambda: migrate(app, target, role))
            def register(subject, **extra):
                return store.ensure_identity(issuer='verified-test-issuer', subject=subject, display_name=subject, **extra)
            with ThreadPoolExecutor(max_workers=4) as pool:
                duplicates = list(pool.map(lambda _: register('A', consents=(('terms','1'),)), range(4)))
            a = duplicates[0]
            assert len({r['id'] for r in duplicates}) == 1
            b, c = register('B'), register('C')
            tenant = register('A', tenant='other')
            assert tenant['id'] != a['id']
            raises(ValueError, lambda: register('rollback', consents=(('', '1'),)))
            with connect(app, 'accounts') as con:
                assert con.execute("SELECT COUNT(*) AS n FROM account_records WHERE display_name='rollback'").fetchone()['n'] == 0
                assert con.execute('SELECT COUNT(*) AS n FROM account_consents').fetchone()['n'] == 1
                assert con.execute('SELECT COUNT(*) AS n FROM account_projection_outbox').fetchone()['n'] == 4
            # The same bounded entry point used by Cloud Run Jobs handles the real outbox.
            from ygc.account_projection_job import run as run_job
            assert run_job(app, limit=2) == {'status': 'ok', 'processed': 2, 'pending': 2}
            assert run_job(app, limit=100) == {'status': 'ok', 'processed': 2, 'pending': 0}
            assert run_job(app) == {'status': 'ok', 'processed': 0, 'pending': 0}
            # Scheduler delivery can overlap; concurrent workers must neither duplicate
            # users nor acknowledge an event without projecting its latest revision.
            for account in (a, b, a, b):
                store.update_profile(account['app_user_id'], {'bio': 'concurrent projection'})
            with ThreadPoolExecutor(max_workers=2) as pool:
                runs = list(pool.map(lambda _: run_job(app), range(2)))
            assert sum(result['processed'] for result in runs) == 4
            assert run_job(app)['pending'] == 0
            with connect(app, 'chronicle') as con:
                assert con.execute('SELECT COUNT(*) AS n FROM users').fetchone()['n'] == 4
            def content_action():
                with store.content_transaction(a['app_user_id'], [a['id'], b['id']]) as (con, actor):
                    assert actor['id'] == a['id'] and actor['role'] == 'member'
                    assert con.execute('SELECT COUNT(*) AS n FROM users').fetchone()['n'] == 4
            content_action()
            store.update_profile(b['app_user_id'], {'bio': 'not yet projected'})
            raises(ValueError, content_action)
            store.drain_projection()
            content_action()
            # A stale content projection cannot permit login, or grant an admin role.
            with connect(app, 'accounts') as con:
                con.execute('UPDATE account_records SET disabled=1,role=\'admin\' WHERE id=%s', (b['id'],))
            raises(PermissionError, lambda: store.resolve_identity(issuer='verified-test-issuer', subject='B'))
            def disabled_action():
                with store.content_transaction(b['app_user_id'], [b['id']]):
                    raise AssertionError('Disabled account must not enter a content transaction.')
            raises(PermissionError, disabled_action)
            with connect(app, 'chronicle') as con:
                assert 'role' not in con.execute('SELECT * FROM users WHERE id=%s', (b['id'],)).fetchone()
            with connect(app, 'accounts') as con:
                con.execute('UPDATE account_records SET disabled=0,role=\'member\' WHERE id=%s', (b['id'],))
            store.drain_projection()
            raises(ValueError, lambda: store.update_profile(a['app_user_id'], {'role': 'admin'}))
            raises(ValueError, lambda: store.update_profile(a['app_user_id'], {'app_user_id': b['app_user_id']}))
            store.update_profile(a['app_user_id'], {'display_name': 'Updated A'})
            def crash():
                raise RuntimeError('Simulated interruption after content commit')
            raises(RuntimeError, lambda: store.project_next(after_content_commit=crash))
            with connect(app, 'accounts') as con:
                assert con.execute('SELECT COUNT(*) AS n FROM account_projection_outbox WHERE delivered_at IS NULL').fetchone()['n'] == 1
            assert store.drain_projection() == 1
            with connect(app, 'chronicle') as con:
                assert con.execute('SELECT COUNT(*) AS n FROM users').fetchone()['n'] == 4
                assert con.execute('SELECT display_name FROM users WHERE id=%s', (a['id'],)).fetchone()['display_name'] == 'Updated A'
            # Source ID is never reassigned; an altered content UUID blocks a retry.
            with connect(owner, 'chronicle') as con:
                con.execute('ALTER TABLE users DISABLE TRIGGER immutable_participant_identity')
                con.execute('UPDATE users SET app_user_id=%s WHERE id=%s', (str(uuid.uuid4()), a['id']))
                con.execute('ALTER TABLE users ENABLE TRIGGER immutable_participant_identity')
            store.update_profile(a['app_user_id'], {'bio': 'pending'})
            raises(ValueError, lambda: run_job(app))
            with connect(owner, 'chronicle') as con:
                con.execute('ALTER TABLE users DISABLE TRIGGER immutable_participant_identity')
                con.execute('UPDATE users SET app_user_id=%s WHERE id=%s', (a['app_user_id'], a['id']))
                con.execute('ALTER TABLE users ENABLE TRIGGER immutable_participant_identity')
            store.drain_projection()
            # Shared evaluator and Snapshot execute on PG; Claim authority APIs
            # use the same fenced business algorithms as SQLite.
            transitions(app, store, a, b, c)
            # Empty content reset keeps accounts; reconciliation restores identities.
            with connect(owner, 'chronicle') as con:
                con.execute('TRUNCATE individuals,users CASCADE')
            assert store.reconcile_projection() == 4
            assert store.resolve_identity(issuer='verified-test-issuer', subject='A')['id'] == a['id']
            with connect(app, 'chronicle') as con:
                assert con.execute('SELECT COUNT(*) AS n FROM individuals').fetchone()['n'] == 0
                con.execute("INSERT INTO users(id,display_name,created_at,updated_at,app_user_id) VALUES(999,'unknown','now','now','unknown-uuid')")
            raises(ValueError, store.reconcile_projection)
            cloud_registration_checks(app, store)
            print('PostgreSQL accounts: migration/repeat, concurrent registration, rollback, live authority, crash retry, UUID conflict, Observation/BAN/Transfer and content-reset reconciliation passed.')
        finally:
            for name in reversed(created):
                admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            admin.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(role)))


def cloud_registration_checks(settings, store):
    """HTTP enrollment and live authorization against a real disposable registry."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ygc.cloud_account_routes import account_router
    from ygc.cloud_registration import DOCUMENTS
    from ygc.identity_platform import VerifiedIdentity
    from ygc.registration_fields import ACCOUNT_TYPES

    class TestVerifier:
        accounts = store

        def verify(self, *, bearer_token):
            # Test-only trusted results replace external Google verification.
            if not bearer_token.startswith('test-session-'):
                raise PermissionError('Invalid test credential')
            return VerifiedIdentity('verified-http-test-issuer', bearer_token, '', True)

    api = FastAPI()
    api.include_router(account_router(TestVerifier(), DOCUMENTS))
    with TestClient(api) as client:
        def headers(kind):
            return {'Authorization': 'Bearer test-session-' + kind}

        def body(kind, **changes):
            return {'display_name': 'N' * 120, 'account_type': kind, 'terms_accepted': True,
                    'privacy_accepted': True, 'terms_version': DOCUMENTS['terms']['version'],
                    'privacy_version': DOCUMENTS['privacy']['version'], **changes}

        assert client.get('/api/auth/me', headers=headers('user')).status_code == 409
        with ThreadPoolExecutor(max_workers=3) as pool:
            replies = list(pool.map(lambda _: client.post('/api/auth/register',
                                headers=headers('user'), json=body('user')), range(3)))
        assert all(reply.status_code == 200 for reply in replies)
        assert len({reply.json()['user']['app_user_id'] for reply in replies}) == 1
        registered = [replies[0].json()['user']]
        for kind in ACCOUNT_TYPES[1:]:
            reply = client.post('/api/auth/register', headers=headers(kind), json=body(kind))
            assert reply.status_code == 200
            registered.append(reply.json()['user'])
        for kind, user in zip(ACCOUNT_TYPES, registered):
            repeat = client.post('/api/auth/register', headers=headers(kind),
                                 json=body(kind, display_name='Do not overwrite'))
            assert repeat.json()['user'] == user
            assert user['role'] == 'member' and user['account_type'] == kind
        ids = [user['id'] for user in registered]
        with connect(settings, 'accounts') as con:
            assert con.execute('SELECT COUNT(*) AS n FROM account_projection_outbox WHERE account_id=ANY(%s)',
                               (ids,)).fetchone()['n'] == 5
            assert con.execute('SELECT COUNT(*) AS n FROM account_consents WHERE app_user_id=ANY(%s)',
                               ([user['app_user_id'] for user in registered],)).fetchone()['n'] == 10
            con.execute('UPDATE account_records SET disabled=1 WHERE id=%s', (ids[0],))
        assert client.get('/api/auth/me', headers=headers('user')).status_code == 403
        assert client.post('/api/auth/register', headers=headers('user'), json=body('user')).status_code == 403
        assert client.post('/api/auth/register', headers=headers('shop'),
                           json=body('shop', role='admin')).status_code == 400
        assert client.get('/api/auth/me', headers={'Authorization': 'Bearer invalid'}).status_code == 401
        assert store.drain_projection() > 0
        with connect(settings, 'chronicle') as con:
            rows = con.execute('SELECT id,display_name,account_type FROM users WHERE id=ANY(%s) ORDER BY id', (ids,)).fetchall()
            assert len(rows) == 5
            assert {row['account_type'] for row in rows} == set(ACCOUNT_TYPES)
            assert all(len(row['display_name']) == 120 for row in rows)
    print('PostgreSQL cloud enrollment: HTTP registration/login, concurrent retry, consent atomicity, five account types, 120-character names, authority rejection and projection passed.')


def transitions(app, store, a, b, c):
    ownership = PostgresOwnership(app)
    actors = {x['id']: ActorContext(x['id'], 'identity-platform', x['identity_subject'], True, x['app_user_id']) for x in (a,b,c)}
    with connect(app, 'chronicle') as con:
        individual = con.execute("""INSERT INTO individuals(manufacturer,normalized_manufacturer,serial_number,
            normalized_serial,created_at,updated_at,current_owner_user_id)
            VALUES('Fender','fender','PG001','pg001','now','now',%s) RETURNING id""", (a['id'],)).fetchone()['id']
        listing = con.execute("""INSERT INTO claims(individual_id,author_user_id,claim_type,occurred_at,created_at,updated_at)
            VALUES(%s,%s,'listing','2026-01-01','now','now') RETURNING id""", (individual,a['id'])).fetchone()['id']
        for field,value in [('manufacturer','Fender'),('serial_number','PG001'),('owner_user_id',str(a['id']))]:
            con.execute('INSERT INTO claim_listing_items(claim_id,field_name,value_text,created_at) VALUES(%s,%s,%s,\'now\')', (listing,field,value))
        for account in (a,):
            con.execute("INSERT INTO user_guitars(user_id,individual_id,created_at,updated_at) VALUES(%s,%s,'now','now')", (account['id'],individual))
        con.execute('UPDATE users SET signature_individual_id=%s WHERE id=%s', (individual,a['id']))
        acquire = con.execute("""INSERT INTO claims(individual_id,author_user_id,claim_type,ownership_kind,ownership_source,
            value_text,verification_status,occurred_at,created_at,updated_at)
            VALUES(%s,%s,'ownership','acquire','user',%s,'unverified','2026-02-01','now','now') RETURNING id""",
            (individual,b['id'],str(b['id']))).fetchone()['id']
        con.execute("INSERT INTO claim_source_evidence(claim_id,evidence_type,effective_date,created_at) VALUES(%s,'acquisition_date','2026-02-01','now')", (acquire,))
        assert evaluate_observation(ObservationConnection(con), individual).values['current_owner_user_id'] == str(a['id'])
        assert con.execute('SELECT COUNT(*) AS n FROM user_guitars WHERE user_id=%s', (b['id'],)).fetchone()['n'] == 0
    raises(ValueError, lambda: ownership.set_claim_response(acquire, actors[b['id']], 'positive'))
    unverified = ActorContext(a['id'], 'prototype', None, False, a['app_user_id'])
    raises(PermissionError, lambda: ownership.set_claim_response(acquire, unverified, 'positive'))
    mismatched = ActorContext(b['id'], 'identity-platform', 'A', True, a['app_user_id'])
    raises(PermissionError, lambda: ownership.set_claim_response(acquire, mismatched, 'positive'))
    assert acquire in ownership.owner_verifiable_claim_ids(individual, actors[a['id']])
    assert ownership.set_claim_response(acquire, actors[a['id']], 'positive')
    for stance in ('positive', 'negative', 'unverified'):
        raises(ValueError, lambda: ownership.set_claim_response(acquire, actors[b['id']], stance))
    raises(ValueError, lambda: ownership.set_claim_response(acquire, actors[a['id']], 'negative'))
    store.update_profile(b['app_user_id'], {'display_name':'Owner B'})
    store.drain_projection()
    with connect(app, 'chronicle') as con:
        assert con.execute('SELECT current_owner_user_id,current_owner_name FROM individuals WHERE id=%s', (individual,)).fetchone() == {'current_owner_user_id':b['id'], 'current_owner_name':'Owner B'}
        owned = {r['user_id']:r['ownership_status'] for r in con.execute('SELECT user_id,ownership_status FROM user_guitars WHERE individual_id=%s', (individual,))}
        assert owned[b['id']] == 'current_owner' and owned[a['id']] == 'former_owner'
    with connect(app, 'accounts') as con:
        con.execute('UPDATE account_records SET disabled=1 WHERE id=%s', (c['id'],))
    raises(PermissionError, lambda: ownership.create_transfer(individual, actors[b['id']], c['id']))
    with connect(app, 'accounts') as con:
        con.execute('UPDATE account_records SET disabled=0 WHERE id=%s', (c['id'],))
    store.drain_projection()
    transfer = ownership.create_transfer(individual, actors[b['id']], c['id'])
    with connect(app, 'accounts') as con:
        con.execute('UPDATE account_records SET disabled=1 WHERE id=%s', (b['id'],))
    raises(PermissionError, lambda: ownership.resolve_transfer(transfer, actors[c['id']], 'accept'))
    with connect(app, 'accounts') as con:
        con.execute('UPDATE account_records SET disabled=0 WHERE id=%s', (b['id'],))
    store.drain_projection()
    raises(ValueError, lambda: ownership.resolve_transfer(transfer, actors[a['id']], 'accept'))
    assert ownership.resolve_transfer(transfer, actors[c['id']], 'accept')['state'] == 'accepted'
    assert ownership.resolve_transfer(transfer, actors[c['id']], 'accept')['state'] == 'accepted'
    for stance in ('positive', 'negative', 'unverified'):
        raises(ValueError, lambda: ownership.set_claim_response(transfer, actors[c['id']], stance))
    raises(PermissionError, lambda: ownership.admin_moderate_claim(acquire, actors[a['id']], 'negative'))
    with connect(app, 'accounts') as con:
        con.execute("UPDATE account_records SET role='admin' WHERE id=%s", (a['id'],))
    raises(ValueError, lambda: ownership.admin_moderate_claim(acquire, actors[a['id']], 'negative'))
    store.drain_projection()
    # An admin can negate A->B after B->C acceptance without revoking C.
    ownership.admin_moderate_claim(acquire, actors[a['id']], 'negative')
    with connect(app, 'chronicle') as con:
        assert con.execute('SELECT actor FROM claim_admin_actions ORDER BY id DESC LIMIT 1').fetchone()['actor'] == 'identity-platform:' + a['app_user_id']
    store.update_profile(c['app_user_id'], {'display_name':'Owner C'})
    store.drain_projection()
    with connect(app, 'chronicle') as con:
        assert con.execute('SELECT current_owner_user_id FROM individuals WHERE id=%s', (individual,)).fetchone()['current_owner_user_id'] == c['id']
        assert con.execute('SELECT signature_individual_id FROM users WHERE id=%s', (a['id'],)).fetchone()['signature_individual_id'] == individual
    # Moderation is a source change; source remains authoritative before delivery.
    with connect(app, 'accounts') as con:
        con.execute("UPDATE account_records SET ban_status='ban' WHERE id=%s", (c['id'],))
    raises(PermissionError, lambda: store.resolve_identity(issuer='verified-test-issuer', subject='C'))
    store.drain_projection()
    with connect(app, 'chronicle') as con:
        assert con.execute('SELECT current_owner_user_id FROM individuals WHERE id=%s', (individual,)).fetchone()['current_owner_user_id'] == a['id']
    with connect(app, 'accounts') as con:
        con.execute("UPDATE account_records SET ban_status='normal' WHERE id=%s", (c['id'],))
    store.drain_projection()
    # Exact A->B->C Transfer transition from the architectural invariants.
    with connect(app, 'chronicle') as con:
        second = con.execute("""INSERT INTO individuals(manufacturer,normalized_manufacturer,serial_number,
            normalized_serial,created_at,updated_at,current_owner_user_id)
            VALUES('Fender','fender','PG002','pg002','now','now',%s) RETURNING id""", (a['id'],)).fetchone()['id']
        listing = con.execute("""INSERT INTO claims(individual_id,author_user_id,claim_type,occurred_at,created_at,updated_at)
            VALUES(%s,%s,'listing','2026-01-01','now','now') RETURNING id""", (second,a['id'])).fetchone()['id']
        for field,value in [('manufacturer','Fender'),('serial_number','PG002'),('owner_user_id',str(a['id']))]:
            con.execute('INSERT INTO claim_listing_items(claim_id,field_name,value_text,created_at) VALUES(%s,%s,%s,\'now\')', (listing,field,value))
        con.execute("INSERT INTO user_guitars(user_id,individual_id,created_at,updated_at) VALUES(%s,%s,'now','now')", (a['id'],second))
    first = ownership.create_transfer(second, actors[a['id']], b['id'])
    ownership.resolve_transfer(first, actors[b['id']], 'accept')
    later = ownership.create_transfer(second, actors[b['id']], c['id'])
    ownership.resolve_transfer(later, actors[c['id']], 'accept')
    for action in ('negative', 'unverified', 'delete'):
        ownership.admin_moderate_claim(first, actors[a['id']], action)
        with connect(app, 'chronicle') as con:
            assert con.execute('SELECT current_owner_user_id FROM individuals WHERE id=%s', (second,)).fetchone()['current_owner_user_id'] == c['id']
