"""Self-only preference contracts on disposable loopback PostgreSQL only.

run(port) is called by the existing opt-in PostgreSQL runner. Import/compilation
opens no sockets. All identities, photos and data are synthetic; runtime calls
use unchanged restricted grants. Owner-only rollback fault injection is reversed.
No live system, public delivery, rollout migration or auth grant is involved.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
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
from test_cloud_avatar import Storage, png
from ygc.cloud_avatar import CloudAvatar
from ygc.cloud_avatar_routes import avatar_router
from ygc.cloud_profile import ProfileConflict, VISIBILITY_FIELDS, VISIBILITY_VALUES
from ygc.cloud_profile_visibility_routes import profile_visibility_router
from ygc.cloud_self_profile_routes import self_profile_router
from ygc.cloud_users import CloudUsers
from ygc.db.postgres import PostgresSettings, TARGETS, bootstrap, connect, migrate
from ygc.db.postgres_accounts import PostgresAccounts
from ygc.db.postgres_operations import MODES, PostgresOperations, ServiceRestricted
from ygc.identity_platform import VerifiedIdentity

ISSUER = 'synthetic-self-visibility-contract'
PRIVATE = 'VISIBILITY-PRIVATE-DO-NOT-PUBLISH'
BASE = '/api/auth/profile/visibility'
DEFAULTS = dict(zip(VISIBILITY_FIELDS, ('Private', 'Private', 'Public', 'Public')))
PREFERENCES = dict(zip(VISIBILITY_FIELDS, VISIBILITY_VALUES))


def rejected(error, operation):
    try:
        operation()
    except error:
        return
    raise AssertionError('Expected ' + error.__name__)


class Workflow:
    def __init__(self, settings, owner, accounts, operations, records):
        self.settings, self.owner, self.accounts, self.operations, self.records = settings, owner, accounts, operations, records
        self.service = CloudUsers(settings, operations)
        self.storage = Storage()
        self.avatars = CloudAvatar(operations, self.storage)

    def actor(self, name='a'):
        return self.records[name]['app_user_id']

    def record(self, name='a'):
        with connect(self.settings, 'accounts') as con:
            return dict(con.execute('SELECT * FROM account_records WHERE app_user_id=%s', (self.actor(name),)).fetchone())

    def seed_account(self, name='a', **changes):
        with connect(self.owner, 'accounts') as con:
            assignments = sql.SQL(',').join(sql.SQL('{}=%s').format(sql.Identifier(key)) for key in changes)
            con.execute(sql.SQL('UPDATE account_records SET {} WHERE app_user_id=%s').format(assignments),
                        (*changes.values(), self.actor(name)))

    def snapshot(self, target='accounts'):
        with connect(self.settings, target) as con:
            tables = [row['tablename'] for row in con.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
            return {table: [row['value'] for row in con.execute(sql.SQL(
                'SELECT to_jsonb(t) AS value FROM {} t ORDER BY to_jsonb(t)::text').format(sql.Identifier(table)))]
                for table in tables}

    def unchanged(self, error, operation):
        before = self.snapshot(), self.snapshot('chronicle')
        rejected(error, operation)
        assert (self.snapshot(), self.snapshot('chronicle')) == before

    def mode(self, value):
        actor = self.actor('admin')
        self.operations.set_mode(actor, mode=value, message='', version=self.operations.details(actor)['version'])

    def read(self, name='a'):
        result = self.service.own_visibility(self.actor(name))
        assert set(result) == {'profile_revision', 'fields'}
        assert set(result['fields']) == set(VISIBILITY_FIELDS)
        assert str(int(result['profile_revision'])) == result['profile_revision']
        assert all(value is None or value in VISIBILITY_VALUES for value in result['fields'].values())
        assert PRIVATE not in json.dumps(result)
        return result

    def body(self, name='a', fields=None):
        return {'revision': str(self.record(name)['projection_version']), 'fields': fields or dict(PREFERENCES)}

    def write(self, name='a', fields=None):
        return self.service.edit_own_visibility(self.actor(name), self.body(name, fields))

    @contextmanager
    def reject_inserts(self, table):
        name = 'synthetic_visibility_failure'
        with connect(self.owner, 'accounts') as con:
            con.execute(sql.SQL('ALTER TABLE {} ADD CONSTRAINT {} CHECK (false) NOT VALID')
                        .format(sql.Identifier(table), sql.Identifier(name)))
        try:
            yield
        finally:
            with connect(self.owner, 'accounts') as con:
                con.execute(sql.SQL('ALTER TABLE {} DROP CONSTRAINT {}')
                            .format(sql.Identifier(table), sql.Identifier(name)))


def preference_checks(w):
    # Defaults are observed, not a migration or an inferred publication consent.
    assert w.read()['fields'] == DEFAULTS
    before = w.snapshot(), w.snapshot('chronicle')
    assert w.read()['fields'] == DEFAULTS
    assert (w.snapshot(), w.snapshot('chronicle')) == before
    w.seed_account(bio=PRIVATE, date_of_birth='1990-02-03', location_country=PRIVATE,
                   location_region=PRIVATE, bio_visibility='legacy-' + PRIVATE)
    before = w.snapshot(), w.snapshot('chronicle')
    assert w.read()['fields'] == {**DEFAULTS, 'bio_visibility': None}
    assert (w.snapshot(), w.snapshot('chronicle')) == before
    assert w.accounts.drain_projection() > 0
    with connect(w.settings, 'chronicle') as con:
        projected = con.execute('SELECT bio_visibility FROM users WHERE app_user_id=%s', (w.actor(),)).fetchone()
        assert projected['bio_visibility'] == 'legacy-' + PRIVATE

    old = w.record()
    other = w.record('b')
    before_chronicle = w.snapshot('chronicle')
    before = w.snapshot()
    result = w.write()
    after = w.record()
    assert result == {'profile_revision': str(old['projection_version'] + 1), 'fields': PREFERENCES}
    assert w.read() == result and w.record('b') == other
    unchanged_keys = set(old) - set(VISIBILITY_FIELDS) - {'updated_at', 'projection_version'}
    assert {key: old[key] for key in unchanged_keys} == {key: after[key] for key in unchanged_keys}
    assert w.snapshot('chronicle') == before_chronicle  # Only the durable outbox hands off.
    current = w.snapshot()
    assert len(current['account_projection_outbox']) == len(before['account_projection_outbox']) + 1
    audit_rows = [row for row in current['account_metadata'] if row['key'].startswith('self_visibility:')]
    assert len(audit_rows) == 1
    audit = json.loads(audit_rows[0]['value'])
    assert set(audit) == {'action', 'actor_app_user_id', 'target_app_user_id', 'changed_fields',
                          'previous_revision', 'revision', 'occurred_at'}
    assert audit['actor_app_user_id'] == audit['target_app_user_id'] == w.actor()
    assert audit['previous_revision'] == old['projection_version'] and audit['revision'] == after['projection_version']
    assert set(audit['changed_fields']) == {key for key in VISIBILITY_FIELDS if old[key] != PREFERENCES[key]}
    assert PRIVATE not in audit_rows[0]['value']
    w.unchanged(ProfileConflict, lambda: w.service.edit_own_visibility(w.actor(),
        {'revision': str(old['projection_version']), 'fields': PREFERENCES}))
    for value in VISIBILITY_VALUES:
        fields = {key: value for key in VISIBILITY_FIELDS}
        assert w.write(fields=fields)['fields'] == fields
        assert w.accounts.drain_projection() > 0
        with connect(w.settings, 'chronicle') as con:
            row = con.execute('SELECT birth_visibility,residence_visibility,bio_visibility,avatar_visibility '
                              'FROM users WHERE app_user_id=%s', (w.actor(),)).fetchone()
            assert dict(row) == fields
    # A settings writer and the original text editor share exactly one revision.
    visibility_body = w.body()
    profile = w.service.own_profile(w.actor())
    text_fields = dict(profile['fields'], display_name='Synthetic edited self')
    w.service.edit_own_profile(w.actor(), {'revision': profile['profile_revision'], 'fields': text_fields})
    w.unchanged(ProfileConflict, lambda: w.service.edit_own_visibility(w.actor(), visibility_body))
    profile = w.service.own_profile(w.actor())
    w.write()
    w.unchanged(ProfileConflict, lambda: w.service.edit_own_profile(w.actor(),
        {'revision': profile['profile_revision'], 'fields': text_fields}))
    assert w.service.own_profile(w.actor())['fields'] == text_fields
    # Avatar mutation also increments the canonical revision, without changing preferences.
    visibility_body = w.body()
    old_fields = w.read()['fields']
    w.avatars.set(w.actor(), png(), 'image/png')
    w.unchanged(ProfileConflict, lambda: w.service.edit_own_visibility(w.actor(), visibility_body))
    assert w.read()['fields'] == old_fields


def fence_checks(w):
    for mode in MODES:
        w.mode(mode)
        for name in ('a', 'admin'):
            can_read = mode in ('normal', 'read_only') or (mode == 'admin_only' and name == 'admin')
            can_write = mode == 'normal' or (mode == 'admin_only' and name == 'admin')
            if can_read:
                before = w.snapshot(), w.snapshot('chronicle')
                w.read(name)
                assert (w.snapshot(), w.snapshot('chronicle')) == before
            else:
                w.unchanged(ServiceRestricted, lambda: w.read(name))
            if can_write:
                w.write(name)
            else:
                w.unchanged(ServiceRestricted, lambda: w.write(name))
    w.mode('normal')
    for changes, restore in (({'ban_status': 'ban'}, {'ban_status': 'normal'}),
                             ({'disabled': 1}, {'disabled': 0}),
                             ({'account_type': 'source'}, {'account_type': 'user'})):
        w.seed_account(**changes)
        w.unchanged(PermissionError, lambda: w.read())
        w.unchanged(PermissionError, lambda: w.write())
        w.seed_account(**restore)
    w.seed_account(ban_status='silent_ban')
    assert w.write()['fields'] == PREFERENCES  # Existing silent-ban self-access semantics.
    w.seed_account(ban_status='normal')
    w.unchanged(PermissionError, lambda: w.service.own_visibility('unknown-synthetic-account'))
    w.unchanged(PermissionError, lambda: w.service.edit_own_visibility('unknown-synthetic-account', w.body()))
    with connect(w.settings, 'operations') as guard:
        guard.execute('SELECT pg_advisory_xact_lock(79432190)')
        assert w.read()['fields'] == PREFERENCES
        w.unchanged(ProfileConflict, lambda: w.write())
    for table in ('account_metadata', 'account_projection_outbox'):
        with w.reject_inserts(table):
            w.unchanged(errors.CheckViolation, lambda: w.write())
    # Exercise the actual service while canonical role/BAN/mode locks are held.
    original_access = w.operations.account_access
    @contextmanager
    def fenced(kind, actor):
        with original_access(kind, actor) as result:
            def mutate(target, statement, params=()):
                with connect(w.owner, target) as con:
                    con.execute("SET LOCAL statement_timeout='100ms'")
                    con.execute(statement, params)
            rejected(errors.QueryCanceled, lambda: mutate('accounts',
                "UPDATE account_records SET ban_status='ban' WHERE app_user_id=%s", (actor,)))
            rejected(errors.QueryCanceled, lambda: mutate('accounts',
                "UPDATE account_records SET role='member' WHERE app_user_id=%s", (actor,)))
            rejected(errors.QueryCanceled, lambda: mutate('operations', "UPDATE settings SET mode='offline' WHERE id=1"))
            yield result
    with patch.object(w.operations, 'account_access', fenced):
        w.write('admin')
    assert w.operations.public_status()['mode'] == 'normal'
    assert w.record('admin')['role'] == 'admin'
    body = w.body()
    barrier = Barrier(2)
    def save():
        barrier.wait(timeout=5)
        try:
            return w.service.edit_own_visibility(w.actor(), body)
        except ProfileConflict:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: save(), range(2)))
    assert sum(result is not None for result in results) == 1
    assert w.record()['projection_version'] == int(body['revision']) + 1


def projection_retry_checks(w):
    """A committed Chronicle projection with an unacknowledged outbox is safe."""
    w.accounts.drain_projection()
    before_chronicle = w.snapshot('chronicle')
    fields = dict(zip(VISIBILITY_FIELDS, ('Public', 'Followers', 'Private', 'Members')))
    saved = w.write(fields=fields)
    before_accounts = w.snapshot()
    pending = [row for row in before_accounts['account_projection_outbox'] if row['delivered_at'] is None]
    assert len(pending) == 1
    event = pending[0]
    user_id = w.records['a']['id']
    assert event['account_id'] == user_id and event['revision'] == int(saved['profile_revision'])

    class Interrupted(RuntimeError):
        pass

    def interrupt_after_commit():
        raise Interrupted('Synthetic interruption after Chronicle commit')

    rejected(Interrupted, lambda: w.accounts.project_next(after_content_commit=interrupt_after_commit))
    assert w.snapshot() == before_accounts  # Account and outbox acknowledgment rolled back.
    assert w.read() == saved
    after_commit = w.snapshot('chronicle')

    def unrelated(snapshot):
        return {table: [row for row in rows if not (
            table == 'users' and row['id'] == user_id or
            table == 'account_projection_receipts' and row['account_id'] == user_id)]
            for table, rows in snapshot.items()}

    assert unrelated(after_commit) == unrelated(before_chronicle)
    user = next(row for row in after_commit['users'] if row['id'] == user_id)
    previous_user = next(row for row in before_chronicle['users'] if row['id'] == user_id)
    assert {key: user[key] for key in VISIBILITY_FIELDS} == fields
    assert {key: value for key, value in user.items() if key not in (*VISIBILITY_FIELDS, 'updated_at')} == {
        key: value for key, value in previous_user.items() if key not in (*VISIBILITY_FIELDS, 'updated_at')}
    receipt = next(row for row in after_commit['account_projection_receipts'] if row['account_id'] == user_id)
    assert receipt['app_user_id'] == w.actor() and receipt['revision'] == int(saved['profile_revision'])

    assert w.accounts.project_next() is True
    after_retry = w.snapshot('chronicle')
    assert unrelated(after_retry) == unrelated(after_commit)
    assert after_retry['users'] == after_commit['users']
    retried_receipt = next(row for row in after_retry['account_projection_receipts'] if row['account_id'] == user_id)
    # An idempotent replay may refresh only the receipt's applied timestamp.
    assert {key: value for key, value in retried_receipt.items() if key != 'applied_at'} == {
        key: value for key, value in receipt.items() if key != 'applied_at'}
    after_accounts = w.snapshot()
    for table in before_accounts:
        if table != 'account_projection_outbox':
            assert after_accounts[table] == before_accounts[table]
    delivered = next(row for row in after_accounts['account_projection_outbox'] if row['id'] == event['id'])
    assert delivered['delivered_at'] is not None
    assert {key: value for key, value in delivered.items() if key != 'delivered_at'} == {
        key: value for key, value in event.items() if key != 'delivered_at'}
    assert [row for row in after_accounts['account_projection_outbox'] if row['id'] != event['id']] == [
        row for row in before_accounts['account_projection_outbox'] if row['id'] != event['id']]
    assert w.accounts.drain_projection() == 0 and w.read() == saved


def http_checks(w):
    class Verifier:
        accounts = w.accounts
        def verify(self, *, bearer_token):
            if bearer_token == 'unverified':
                return VerifiedIdentity(ISSUER, 'a', '', False)
            if bearer_token not in w.records:
                raise PermissionError(PRIVATE)
            return VerifiedIdentity(ISSUER, bearer_token, '', True)
    app = FastAPI()
    verifier = Verifier()
    app.include_router(profile_visibility_router(verifier, w.service))
    app.include_router(self_profile_router(verifier, w.service))
    app.include_router(avatar_router(verifier, w.operations, w.storage))
    def headers(name='a'):
        return {'Authorization': 'Bearer ' + name}
    def check(response, status):
        assert response.status_code == status, response.text
        assert response.headers['cache-control'] == 'private, no-store'
        assert response.headers['vary'] == 'Authorization'
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert PRIVATE not in response.text
    with TestClient(app) as client:
        before = w.snapshot(), w.snapshot('chronicle')
        check(client.get(BASE), 401)
        check(client.get(BASE, headers=headers('invalid')), 401)
        check(client.get(BASE, headers=headers('unverified')), 403)
        for method in ('GET', 'PUT'):
            check(client.request(method, BASE + '?user_id=' + str(w.records['b']['id']),
                                 headers=headers(), json=w.body() if method == 'PUT' else None), 400)
            check(client.request(method, BASE, headers=[*headers().items(), *headers().items()]), 401)
        check(client.request('GET', BASE, headers=headers(), content='{}'), 400)
        check(client.put(BASE, headers={**headers(), 'Content-Type': 'application/json'},
                         content='{"revision":"1","revision":"2","fields":{}}'), 400)
        for field in ('role', 'disabled', 'app_user_id', 'avatar_storage_path', 'birth_date', 'display_name'):
            check(client.put(BASE, headers=headers(), json={**w.body(), field: PRIVATE}), 400)
        assert (w.snapshot(), w.snapshot('chronicle')) == before
        check(client.get(BASE, headers=headers()), 200)
        body = w.body(fields={key: 'Public' for key in VISIBILITY_FIELDS})
        check(client.put(BASE, headers=headers(), json=body), 200)
        check(client.put(BASE, headers=headers(), json=body), 409)
        # Choosing Public grants no public/profile-by-ID path and no image sharing.
        assert client.get('/api/public/users/' + str(w.records['a']['id'])).status_code == 404
        assert client.get('/api/auth/profile/' + str(w.records['b']['id'])).status_code == 404
        assert client.get('/api/public/avatar/' + str(w.records['a']['id'])).status_code == 404
        assert client.get('/api/auth/avatar').status_code == 401
        assert client.get('/api/auth/avatar', headers=headers('b')).status_code == 404
        assert client.get('/api/auth/avatar?user_id=' + str(w.records['a']['id']), headers=headers('b')).status_code == 400
        image = client.get('/api/auth/avatar', headers=headers())
        assert image.status_code == 200 and image.headers['cache-control'] == 'private, no-store'
        assert image.content == w.avatars.get(w.actor())
        w.mode('read_only')
        check(client.get(BASE, headers=headers()), 200)
        check(client.put(BASE, headers=headers(), json=w.body()), 403)
        w.mode('normal')
        w.seed_account(disabled=1)
        check(client.get(BASE, headers=headers()), 403)
        w.seed_account(disabled=0)


def run(port):
    prefix = 'ygctest_visibility_' + uuid.uuid4().hex[:10] + '_'
    runtime = prefix + 'app'
    owner = PostgresSettings('127.0.0.1', 'postgres', 'ygc-tests-only', port, prefix)
    settings = replace(owner, user=runtime)
    databases = []
    with psycopg.connect(host='127.0.0.1', port=port, dbname='postgres', user='postgres',
                         password='ygc-tests-only', autocommit=True) as system:
        try:
            system.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(
                sql.Identifier(runtime), sql.Literal('ygc-tests-only')))
            for target in TARGETS:
                name = owner.database(target)
                system.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
                databases.append(name)
                bootstrap(owner, target, runtime)
                migrate(owner, target, runtime)
            baseline = structure(owner, runtime)
            accounts, operations = PostgresAccounts(settings), PostgresOperations(settings)
            records = {name: accounts.ensure_identity(issuer=ISSUER, subject=name,
                display_name='Synthetic ' + name) for name in ('admin', 'a', 'b')}
            with connect(owner, 'accounts') as con:
                con.execute("UPDATE account_records SET role='admin' WHERE app_user_id=%s",
                            (records['admin']['app_user_id'],))
            assert all(record['role'] == 'member' for record in records.values())
            accounts.drain_projection()
            w = Workflow(settings, owner, accounts, operations, records)
            w.mode('normal')
            preference_checks(w)
            projection_retry_checks(w)
            fence_checks(w)
            http_checks(w)
            assert accounts.drain_projection() > 0
            assert accounts.drain_projection() == 0
            assert structure(owner, runtime) == baseline, 'Visibility work changed schema or runtime grants'
            print('PostgreSQL self visibility: preserved defaults/legacy values, exact private DTO, '
                  'complete enums, shared Account CAS/outbox projection, self/BAN/mode/maintenance fences, '
                  'projection interruption/retry, concurrent writes, atomic audit/outbox rollback '
                  'and unchanged image protection passed; '
                  'schema and runtime grants unchanged.')
        finally:
            for name in reversed(databases):
                system.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            system.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(runtime)))
