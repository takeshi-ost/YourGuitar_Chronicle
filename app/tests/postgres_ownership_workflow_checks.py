"""Cloud Transfer / Release contracts against disposable loopback PostgreSQL.

Only ``run(port)`` connects to PostgreSQL; importing this module does not launch
or install a server. The aggregate runner supplies an authorized local/CI test
server. Every identity, guitar and note is synthetic. Fixture SQL, canonical
account setup and fault injection use the database owner. Production services
run with the unchanged bootstrap/migration application grants throughout.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
import json
import re
from threading import Barrier
import uuid

import psycopg
from psycopg import errors, sql

from ygc.admin_bootstrap_job import grant_first_admin
from ygc.claim_revision import ClaimConflict
from ygc.cloud_guitars import GuitarMissing
from ygc.cloud_owner import CloudOwner
from ygc.cloud_ownership import CloudOwnership
from ygc.cloud_public_catalog import CloudPublicCatalog
from ygc.cloud_users import CloudUsers
from ygc.db.postgres import PostgresSettings, bootstrap, connect, migrate
from ygc.db.postgres_accounts import PostgresAccounts
from ygc.db.postgres_operations import PostgresOperations, ServiceRestricted
from ygc.db.postgres_ownership import PostgresOwnership
from ygc.platform_boundaries import ActorContext

ISSUER = 'synthetic-cloud-ownership-contract'
PRIVATE = 'OWNERSHIP-PRIVATE-DO-NOT-PUBLISH'
BIG_ID = 9007199254741009
PERSON_FIELDS = {'id', 'display_name', 'account_type'}
GUITAR_FIELDS = {'id', 'manufacturer', 'model', 'finish', 'year', 'serial_number'}
VIEW_FIELDS = {'viewer_user_id', 'individual', 'current_owner_user_id', 'is_current_owner',
               'revision', 'can_write', 'can_transfer', 'can_release', 'items',
               'next_after'}
TRANSFER_FIELDS = {'id', 'viewer_user_id', 'individual_id', 'individual', 'ownership_kind',
                   'from_user', 'to_user', 'state', 'status',
                   'verification_status', 'revision', 'created_at',
                   'resolved_at', 'occurred_at', 'acceptance', 'can_accept',
                   'can_decline', 'can_cancel', 'can_write'}
SNAPSHOT_TABLES = ('claims', 'claim_listing_items', 'claim_source_evidence',
                   'claim_transfers', 'claim_transfer_acceptance',
                   'claim_responses', 'claim_admin_actions', 'notifications',
                   'individuals', 'user_guitars', 'observations', 'users',
                   'account_projection_receipts')
GUITARS = ('privacy', 'release', 'decline', 'cancel', 'chain', 'ban', 'stale',
           'race_accept', 'race_release', 'fault_create', 'fault_accept',
           'fault_release', 'chronology_accept', 'chronology_release', 'mode_a',
           'mode_admin', 'deleted', 'pending_profile', 'guard', 'hidden')


def rejected(kind, operation):
    try:
        operation()
    except kind as exc:
        return exc
    label = ', '.join(item.__name__ for item in kind) if isinstance(kind, tuple) else kind.__name__
    raise AssertionError('Expected ' + label)


def exact_id(value, expected=None):
    assert isinstance(value, str) and value.isascii() and value.isdecimal(), value
    assert int(value) > 2**53, value
    if expected is not None:
        assert value == str(expected), (value, expected)


def revision(value):
    assert isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value), value


def private_free(value, records):
    serialized = json.dumps(value, default=str)
    assert PRIVATE not in serialized
    for account in records.values():
        assert account['app_user_id'] not in serialized
    for forbidden in ('identity_subject', 'identity_provider', 'date_of_birth',
                      'avatar_storage_path', 'projection_version', 'disabled'):
        assert '"' + forbidden + '"' not in serialized


@contextmanager
def reject_rows(owner, table):
    """An owner-installed constraint forces real SQL rollback, not a mock.

    NOT VALID permits existing fixtures but rejects INSERT and UPDATE. It does
    not alter the runtime role, grants, triggers, or production implementation.
    """
    constraint = 'synthetic_ownership_failure'
    with connect(owner, 'chronicle') as con:
        con.execute(sql.SQL('ALTER TABLE {} ADD CONSTRAINT {} CHECK (false) NOT VALID')
                    .format(sql.Identifier(table), sql.Identifier(constraint)))
    try:
        yield
    finally:
        with connect(owner, 'chronicle') as con:
            con.execute(sql.SQL('ALTER TABLE {} DROP CONSTRAINT {}')
                        .format(sql.Identifier(table), sql.Identifier(constraint)))


def grants(settings):
    """Read and compare grants so tests cannot silently broaden runtime access."""
    result = {}
    for target in ('accounts', 'chronicle', 'operations'):
        with connect(settings, target) as con:
            actor = con.execute('''SELECT current_user AS name,rolsuper,rolcreatedb,
                rolcreaterole,rolreplication,rolbypassrls FROM pg_roles
                WHERE rolname=current_user''').fetchone()
            assert actor['name'] == settings.user
            assert not any(actor[key] for key in actor if key != 'name')
            assert not con.execute("SELECT has_schema_privilege(current_user,'public','CREATE') AS allowed").fetchone()['allowed']
            rows = [dict(row) for row in con.execute('''SELECT c.relname,c.relkind,
                c.relacl::text AS acl,pg_get_userbyid(c.relowner) AS owner
                FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='public' AND c.relkind IN ('r','S') ORDER BY c.relname''')]
            assert all(row['owner'] != settings.user for row in rows)
            result[target] = rows
    return result


def seed(owner):
    """All fixture creation, including account projection, uses the DB owner."""
    setup = PostgresAccounts(owner)
    with connect(owner, 'accounts') as con:
        con.execute("SELECT setval(pg_get_serial_sequence('account_records','id'),%s,false)", (BIG_ID,))
    names = ('admin', 'a', 'b', 'c', 'source', 'banned', 'silent', 'disabled',
             'gone', 'retired', 'literal', 'candidate_1', 'candidate_2', 'candidate_3')
    records = {}
    for name in names:
        display = 'Scoped %_needle' if name == 'literal' else 'Scoped ' + name
        row = setup.ensure_identity(issuer=ISSUER, subject=name, display_name=display)
        setup.update_profile(row['app_user_id'], {'bio': PRIVATE + '-' + name,
            'location_country': 'JP' if name == 'b' else 'US',
            'location_region': PRIVATE + '-region-' + name,
            'date_of_birth': '1990-01-01', 'bio_visibility': 'Private',
            'residence_visibility': 'Private', 'birth_visibility': 'Private'})
        records[name] = row
    assert grant_first_admin(owner, records['admin']['app_user_id'], 'synthetic-test-operator')
    with connect(owner, 'accounts') as con:
        for name, column, value in (('source', 'account_type', 'source'),
                ('banned', 'ban_status', 'ban'), ('silent', 'ban_status', 'silent_ban'),
                ('disabled', 'disabled', 1)):
            con.execute(sql.SQL('UPDATE account_records SET {}=%s WHERE id=%s')
                        .format(sql.Identifier(column)), (value, records[name]['id']))
    assert setup.drain_projection(limit=1000) > 0
    ids = {name: BIG_ID + 1000 + index for index, name in enumerate(GUITARS)}
    with connect(owner, 'chronicle') as con:
        con.execute('DELETE FROM users WHERE id=%s', (records['gone']['id'],))
        for table in ('claims', 'notifications', 'user_guitars'):
            con.execute("SELECT setval(pg_get_serial_sequence(%s,'id'),%s,false)", (table, BIG_ID + 10000))
        for name, individual in ids.items():
            account = records['admin' if name == 'mode_admin' else 'a']
            user = account['id']
            con.execute('''INSERT INTO individuals(id,manufacturer,model,serial_number,
                normalized_manufacturer,normalized_model,normalized_serial,
                current_owner_user_id,current_owner_name,current_owner_type,
                location_country,location_region,created_at,updated_at)
                VALUES(%s,'Fender','Telecaster',%s,'fender','telecaster',%s,%s,
                       %s,'user','US',%s,'2026-01-01','2026-01-01')''',
                (individual, 'TRANSFER-' + name, 'transfer-' + name,
                 None if name == 'hidden' else user, account['display_name'], PRIVATE))
            if name == 'hidden':
                continue
            date = '9999-01-01' if name.startswith('chronology_') else '2026-01-01'
            claim = con.execute('''INSERT INTO claims(individual_id,author_user_id,
                claim_type,verification_status,occurred_at,created_at,updated_at)
                VALUES(%s,%s,'listing','positive',%s,'2026-01-01','2026-01-01') RETURNING id''',
                (individual, user, date)).fetchone()['id']
            for field, value in (('manufacturer', 'Fender'), ('model', 'Telecaster'),
                    ('serial_number', 'TRANSFER-' + name), ('owner_user_id', str(user))):
                con.execute('''INSERT INTO claim_listing_items(claim_id,field_name,value_text,created_at)
                    VALUES(%s,%s,%s,'2026-01-01')''', (claim, field, value))
            con.execute('''INSERT INTO user_guitars(user_id,individual_id,ownership_status,
                acquired_at,created_at,updated_at) VALUES(%s,%s,'current_owner',
                    '2026-01-01','2026-01-01','2026-01-01')''', (user, individual))
    return records, ids


class Workflow:
    def __init__(self, settings, owner, records, ids, operations):
        self.settings, self.db_owner, self.records, self.ids = settings, owner, records, ids
        self.operations = operations
        self.service = CloudOwnership(settings, operations)
        self.accounts = PostgresAccounts(settings)
        self.ownership = PostgresOwnership(settings)
        self.owners = CloudOwner(settings, operations)
        self.users = CloudUsers(settings, operations)
        self.catalog = CloudPublicCatalog(settings, operations)

    def actor(self, name):
        return self.records[name]['app_user_id']

    def user(self, name):
        return self.records[name]['id']

    def principal(self, name):
        return ActorContext(self.user(name), 'identity-platform', name, True, self.actor(name))

    def view(self, name='a', guitar='privacy', **page):
        result = self.service.view(self.actor(name), self.ids[guitar], **page)
        assert set(result) == VIEW_FIELDS
        exact_id(result['viewer_user_id'], self.user(name))
        assert set(result['individual']) == GUITAR_FIELDS
        exact_id(result['individual']['id'], self.ids[guitar])
        if result['current_owner_user_id'] is not None:
            exact_id(result['current_owner_user_id'])
        revision(result['revision'])
        return result

    def transfer(self, row):
        assert set(row) == TRANSFER_FIELDS, set(row)
        exact_id(row['id'])
        exact_id(row['viewer_user_id'])
        exact_id(row['individual_id'])
        assert set(row['individual']) == GUITAR_FIELDS
        assert row['individual']['id'] == row['individual_id']
        assert row['ownership_kind'] == 'transfer'
        revision(row['revision'])
        for key in ('from_user', 'to_user'):
            assert set(row[key]) == PERSON_FIELDS
            exact_id(row[key]['id'])
        if row['acceptance'] is not None:
            assert set(row['acceptance']) == {'accepted_by_user_id', 'accepted_at', 'current_owner_user_id'}
            exact_id(row['acceptance']['accepted_by_user_id'])
            exact_id(row['acceptance']['current_owner_user_id'])
        private_free(row, self.records)
        return row

    def create(self, guitar='privacy', source='a', target='b'):
        result = self.service.create(self.actor(source), self.ids[guitar], {
            'to_user_id': str(self.user(target)), 'revision': self.view(source, guitar)['revision']})
        assert set(result) == {'transfer'}
        exact_id(result['transfer']['viewer_user_id'], self.user(source))
        return self.transfer(result['transfer'])

    def detail(self, name, row):
        result = self.transfer(self.service.detail(self.actor(name), int(row['id'])))
        exact_id(result['viewer_user_id'], self.user(name))
        return result

    def resolve(self, name, row, action):
        result = self.service.resolve(self.actor(name), int(row['id']), {
            'action': action, 'revision': row['revision']})
        assert set(result) == {'transfer'}
        exact_id(result['transfer']['viewer_user_id'], self.user(name))
        return self.transfer(result['transfer'])

    def release(self, guitar='release', name='a', *, seen=None, date='2026-02-01'):
        seen = seen or self.view(name, guitar)
        return self.service.release(self.actor(name), self.ids[guitar], {
            'occurred_at': date, 'body': PRIVATE, 'revision': seen['revision']})

    def mode(self, value):
        admin = self.actor('admin')
        self.operations.set_mode(admin, mode=value, message='', version=self.operations.details(admin)['version'])

    def snapshot(self):
        with connect(self.settings, 'chronicle') as con:
            return {table: [row['value'] for row in con.execute(sql.SQL(
                'SELECT to_jsonb(t) AS value FROM {} t ORDER BY to_jsonb(t)::text')
                .format(sql.Identifier(table)))] for table in SNAPSHOT_TABLES}

    def unchanged(self, error, operation):
        before = self.snapshot()
        rejected(error, operation)
        assert self.snapshot() == before, 'Rejected action left Chronicle writes behind'

    def current(self, guitar, owner, *, former=()):
        individual = self.ids[guitar]
        with connect(self.settings, 'chronicle') as con:
            actual = con.execute('SELECT current_owner_user_id FROM individuals WHERE id=%s', (individual,)).fetchone()
            assert actual['current_owner_user_id'] == (self.user(owner) if owner else None), actual
            relations = {row['user_id']: dict(row) for row in con.execute(
                'SELECT * FROM user_guitars WHERE individual_id=%s', (individual,))}
        if owner:
            assert relations[self.user(owner)]['ownership_status'] == 'current_owner'
            assert individual in {row['id'] for row in self.users.own_guitars(self.actor(owner), kind='owned', limit=50)['items']}
        for name in former:
            assert relations[self.user(name)]['ownership_status'] == 'former_owner'
            assert individual in {row['id'] for row in self.users.own_guitars(self.actor(name), kind='formerly_owned', limit=50)['items']}
            assert individual not in {row['id'] for row in self.users.own_guitars(self.actor(name), kind='owned', limit=50)['items']}
        return relations

    def canonical(self, name, **changes):
        """Owner-only fixture mutation; delivery still exercises runtime code."""
        with connect(self.db_owner, 'accounts') as con:
            assignments = sql.SQL(',').join(sql.SQL('{}=%s').format(sql.Identifier(key)) for key in changes)
            con.execute(sql.SQL('UPDATE account_records SET {} WHERE id=%s').format(assignments),
                        (*changes.values(), self.user(name)))


def identity_search_privacy(w):
    view = w.view()
    assert view['is_current_owner'] and view['can_transfer'] and view['can_release']
    assert view['items'] == [] and view['next_after'] is None
    private_free(view, w.records)
    for actor in (None, str(w.user('a')), str(uuid.uuid4())):
        w.unchanged(PermissionError, lambda: w.service.view(actor, w.ids['privacy']))
    for name in ('source', 'banned', 'silent', 'disabled'):
        w.unchanged(PermissionError, lambda: w.view(name))
    for individual in (w.ids['hidden'], BIG_ID + 999999):
        w.unchanged(GuitarMissing, lambda: w.service.view(w.actor('a'), individual))
        w.unchanged(GuitarMissing, lambda: w.service.search_users(w.actor('a'), individual, q='Scoped'))
    for name in ('b', 'c', 'admin'):
        w.unchanged(GuitarMissing, lambda: w.view(name))
        w.unchanged(GuitarMissing, lambda: w.service.search_users(w.actor(name), w.ids['privacy'], q='Scoped'))

    search = lambda **query: w.service.search_users(w.actor('a'), w.ids['privacy'], **query)
    before = w.snapshot()
    assert search(q='')['items'] == [] and search(q='   ')['items'] == []
    found, offset = [], 0
    while True:
        page = search(q='sCoPeD', offset=offset, limit=2)
        assert set(page) == {'items', 'next_offset'}
        for row in page['items']:
            assert set(row) == PERSON_FIELDS
            exact_id(row['id'])
        private_free(page, w.records)
        found.extend(page['items'])
        if page['next_offset'] is None:
            break
        assert page['next_offset'] == offset + 2
        offset = page['next_offset']
        assert offset <= 200, 'Search cursor did not advance'
    expected = {str(w.user(name)) for name in ('admin', 'b', 'c', 'retired', 'literal', 'candidate_1', 'candidate_2', 'candidate_3')}
    assert {row['id'] for row in found} == expected
    assert len(found) == len(expected)
    exact = search(q=str(w.user('b')))['items']
    assert [row['id'] for row in exact] == [str(w.user('b'))]
    assert search(q=str(w.user('b'))[:-1])['items'] == []
    assert search(q=w.actor('b'))['items'] == []
    assert [row['id'] for row in search(q='%_needle')['items']] == [str(w.user('literal'))]
    assert search(q="' OR true --")['items'] == []
    assert w.snapshot() == before, 'Search must not repair account projections'
    for query in ({'q': 'x' * 121}, {'q': '\x00'}, {'q': 3}, {'offset': -1},
                  {'offset': 201}, {'offset': True}, {'limit': 0}, {'limit': 21}):
        w.unchanged(ValueError, lambda: search(**query))
    # Pending recipient projection cannot be repaired or exposed by search.
    w.canonical('candidate_1', display_name='Scoped renamed candidate')
    before = w.snapshot()
    assert search(q='renamed candidate')['items'] == []
    assert w.snapshot() == before
    assert w.accounts.drain_projection(limit=1000) > 0
    assert [row['id'] for row in search(q='renamed candidate')['items']] == [str(w.user('candidate_1'))]

    draft = w.create()
    assert draft['from_user']['id'] == str(w.user('a'))
    assert draft['to_user']['id'] == str(w.user('b'))
    assert draft['state'] == 'pending' and draft['verification_status'] == 'unverified'
    assert draft['occurred_at'] is None and draft['acceptance'] is None
    assert draft['can_cancel'] and not draft['can_accept'] and not draft['can_decline']
    recipient = w.detail('b', draft)
    assert recipient['can_accept'] and recipient['can_decline'] and not recipient['can_cancel']
    assert draft['revision'] == recipient['revision']
    assert not w.view('b')['is_current_owner']
    w.unchanged(PermissionError, lambda: w.service.search_users(w.actor('b'), w.ids['privacy'], q='Scoped'))
    for name in ('c', 'admin'):
        w.unchanged(GuitarMissing, lambda: w.detail(name, draft))
        w.unchanged(GuitarMissing, lambda: w.resolve(name, draft, 'accept'))
        w.unchanged(GuitarMissing, lambda: w.view(name))
        assert w.service.inbox(w.actor(name))['items'] == []
    w.unchanged(GuitarMissing, lambda: w.service.detail(w.actor('a'), BIG_ID + 999999))
    with connect(w.settings, 'chronicle') as con:
        listing = con.execute("SELECT id FROM claims WHERE individual_id=%s AND claim_type='listing'", (w.ids['privacy'],)).fetchone()['id']
    w.unchanged(GuitarMissing, lambda: w.service.detail(w.actor('a'), listing))
    for name, action in (('a', 'accept'), ('a', 'decline'), ('b', 'cancel')):
        w.unchanged(PermissionError, lambda: w.resolve(name, draft, action))
    with connect(w.settings, 'chronicle') as con:
        claim = con.execute('SELECT * FROM claims WHERE id=%s', (int(draft['id']),)).fetchone()
        assert claim['author_user_id'] == w.user('a')
        assert claim['ownership_source'] == 'user_transfer' and claim['value_text'] == str(w.user('b'))
        assert not con.execute('SELECT 1 FROM claim_transfer_acceptance WHERE claim_id=%s', (int(draft['id']),)).fetchone()
        assert not con.execute('SELECT 1 FROM user_guitars WHERE user_id=%s AND individual_id=%s', (w.user('b'), w.ids['privacy'])).fetchone()
        notices = con.execute('SELECT * FROM notifications WHERE claim_id=%s', (int(draft['id']),)).fetchall()
        assert len(notices) == 1 and notices[0]['recipient_user_id'] == w.user('b')
        assert notices[0]['notification_type'] == 'transfer_request'
    w.current('privacy', 'a')
    w.unchanged((ClaimConflict, ValueError), lambda: w.create())
    for target in ('a', 'source', 'banned', 'silent', 'disabled', 'gone'):
        w.unchanged((PermissionError, ValueError, GuitarMissing), lambda: w.create(target=target))
    unverified = ActorContext(w.user('b'), 'prototype', None, False, w.actor('b'))
    mismatch = ActorContext(w.user('b'), 'identity-platform', 'b', True, w.actor('a'))
    for principal in (unverified, mismatch):
        w.unchanged(PermissionError, lambda: w.ownership.resolve_transfer(int(draft['id']), principal, 'accept'))
    seen = w.view()
    for target in ('0', '-1', '1.0', str(2**63), True, w.user('c')):
        w.unchanged(ValueError, lambda: w.service.create(w.actor('a'), w.ids['privacy'],
            {'to_user_id': target, 'revision': seen['revision']}))
    w.unchanged(ValueError, lambda: w.service.create(w.actor('a'), w.ids['privacy'],
        {'to_user_id': str(BIG_ID + 999999), 'revision': seen['revision']}))
    for extra in ({'from_user_id': str(w.user('c'))}, {'author_user_id': str(w.user('c'))},
                  {'occurred_at': '2026-01-01'}, {'acceptance': {}}, {'verification_status': 'positive'}):
        w.unchanged(ValueError, lambda: w.service.create(w.actor('a'), w.ids['privacy'],
            {'to_user_id': str(w.user('c')), 'revision': seen['revision'], **extra}))
    return draft


def release_checks(w):
    # Being a legitimate participant does not authorize the recipient to release.
    w.create('release')
    before = w.view('a', 'release')
    w.unchanged(PermissionError, lambda: w.release(name='b', seen=before))
    for data in ({'revision': '0' * 64, 'occurred_at': '2026-02-01', 'body': None},):
        w.unchanged(ClaimConflict, lambda: w.service.release(w.actor('a'), w.ids['release'], data))
    for extra in ({'author_user_id': str(w.user('b'))}, {'ownership_kind': 'acquire'},
                  {'previous_owner_text': 'untrusted'}, {'verification_status': 'positive'}):
        w.unchanged(ValueError, lambda: w.service.release(w.actor('a'), w.ids['release'],
            {'revision': before['revision'], 'occurred_at': '2026-02-01', 'body': None, **extra}))
    for date in ('9999-01-01', 'not-a-date'):
        w.unchanged(ValueError, lambda: w.release(date=date))
    result = w.release(seen=before)
    assert set(result) == {'claim', 'ownership'}
    claim = result['claim']
    exact_id(claim['id'])
    exact_id(claim['individual_id'], w.ids['release'])
    assert claim['ownership_kind'] == 'release' and claim['verification_status'] == 'positive'
    assert claim['status'] == 'active' and claim['occurred_at'] == '2026-02-01' and claim['body'] == PRIVATE
    assert result['ownership']['current_owner_user_id'] is None
    assert result['ownership']['revision'] != before['revision']
    relations = w.current('release', None, former=('a',))
    assert relations[w.user('a')]['released_at'] == '2026-02-01'
    with connect(w.settings, 'chronicle') as con:
        row = con.execute('SELECT * FROM individuals WHERE id=%s', (w.ids['release'],)).fetchone()
        assert row['current_owner_name'] == 'Unknown'
        assert row['location_country'] is None and row['location_region'] is None
        raw = con.execute('SELECT * FROM claims WHERE id=%s', (int(claim['id']),)).fetchone()
        assert raw['author_user_id'] == w.user('a') and raw['value_text'] == 'unknown'
        assert raw['observation_id'] is None
        assert not con.execute('SELECT 1 FROM claim_transfers WHERE claim_id=%s', (int(claim['id']),)).fetchone()
    w.unchanged((ClaimConflict, PermissionError), lambda: w.release(seen=before))
    assert claim['id'] in {row['id'] for row in w.view('a', 'release')['items']}
    assert claim['id'] not in {row['id'] for row in w.view('b', 'release')['items']}
    private_free(w.catalog.chronicle(None, w.ids['release']), w.records)
    private_free(w.catalog.detail(None, w.ids['release']), w.records)


def accepted_and_repeated_checks(w, pending):
    accepted = w.resolve('b', w.detail('b', pending), 'accept')
    assert accepted['state'] == 'accepted' and accepted['verification_status'] == 'positive'
    assert not any(accepted[key] for key in ('can_accept', 'can_decline', 'can_cancel'))
    assert accepted['acceptance'] == {'accepted_by_user_id': str(w.user('b')),
        'accepted_at': accepted['occurred_at'], 'current_owner_user_id': str(w.user('a'))}
    assert accepted['resolved_at'] == accepted['occurred_at']
    relations = w.current('privacy', 'b', former=('a',))
    date = accepted['occurred_at'][:10]
    assert relations[w.user('a')]['released_at'] == date
    assert relations[w.user('b')]['acquired_at'] == date and relations[w.user('b')]['released_at'] is None
    with connect(w.settings, 'chronicle') as con:
        snap = con.execute('SELECT location_country,location_region FROM individuals WHERE id=%s', (w.ids['privacy'],)).fetchone()
        assert snap == {'location_country': 'JP', 'location_region': PRIVATE + '-region-b'}
        assert con.execute('SELECT COUNT(*) AS n FROM claim_transfer_acceptance WHERE claim_id=%s', (int(accepted['id']),)).fetchone()['n'] == 1
        notices = con.execute('SELECT * FROM notifications WHERE claim_id=%s ORDER BY id', (int(accepted['id']),)).fetchall()
        assert [row['notification_type'] for row in notices] == ['transfer_request', 'transfer_result']
        assert notices[0]['is_read'] == 1 and notices[0]['read_at']
        assert notices[1]['recipient_user_id'] == w.user('a')
    for name in ('a', 'b'):
        for stance in ('positive', 'negative', 'unverified'):
            w.unchanged(ValueError, lambda: w.ownership.set_claim_response(int(accepted['id']), w.principal(name), stance))
    assert accepted['id'] not in {row['id'] for row in w.owners.pending(w.actor('b'), w.ids['privacy'])['items']}
    before = w.snapshot()
    assert w.resolve('b', pending, 'accept')['state'] == 'accepted'
    assert w.snapshot() == before, 'Retry with original revision duplicated the accepted transaction'
    w.unchanged((ClaimConflict, ValueError), lambda: w.resolve('b', accepted, 'decline'))
    w.unchanged((ClaimConflict, ValueError), lambda: w.resolve('a', accepted, 'cancel'))
    w.unchanged(PermissionError, lambda: w.ownership.admin_moderate_claim(int(accepted['id']), w.principal('a'), 'negative'))
    for stance in ('negative', 'unverified'):
        w.ownership.admin_moderate_claim(int(accepted['id']), w.principal('admin'), stance)
        before = w.snapshot()
        retried = w.resolve('b', pending, 'accept')
        assert retried['state'] == 'accepted' and retried['verification_status'] == stance
        assert retried['acceptance'] == accepted['acceptance']
        assert w.snapshot() == before, 'Accept retry overwrote separate administrator Verification'
        w.current('privacy', 'a', former=('b',))
    w.ownership.admin_moderate_claim(int(accepted['id']), w.principal('admin'), 'positive')
    w.current('privacy', 'b', former=('a',))
    private_free(w.catalog.chronicle(None, w.ids['privacy']), w.records)

    for guitar, name, action, state in (('decline', 'b', 'decline', 'declined'),
                                       ('cancel', 'a', 'cancel', 'cancelled')):
        proposal = w.create(guitar)
        result = w.resolve(name, w.detail(name, proposal), action)
        assert result['state'] == state and result['acceptance'] is None
        assert result['occurred_at'] is None and result['verification_status'] == 'unverified'
        before = w.snapshot()
        assert w.resolve(name, proposal, action)['state'] == state
        assert w.snapshot() == before
        w.unchanged((ClaimConflict, ValueError), lambda: w.resolve('b', result, 'accept'))
        w.current(guitar, 'a')
        with connect(w.settings, 'chronicle') as con:
            assert not con.execute('SELECT 1 FROM user_guitars WHERE individual_id=%s AND user_id=%s', (w.ids[guitar], w.user('b'))).fetchone()
            assert con.execute('SELECT COUNT(*) AS n FROM notifications WHERE claim_id=%s', (int(result['id']),)).fetchone()['n'] == 2


def independent_chain_checks(w):
    first = w.create('chain')
    first = w.resolve('b', w.detail('b', first), 'accept')
    second = w.create('chain', 'b', 'c')
    second = w.resolve('c', w.detail('c', second), 'accept')
    w.current('chain', 'c', former=('a', 'b'))
    evidence = second['acceptance']
    assert evidence['current_owner_user_id'] == str(w.user('b'))
    for stance in ('positive', 'negative', 'unverified'):
        w.unchanged(ValueError, lambda: w.ownership.set_claim_response(int(second['id']), w.principal('c'), stance))
    for action in ('negative', 'unverified', 'deactivate', 'delete'):
        if action == 'deactivate':
            with w.ownership._transaction(w.principal('a'), w.ids['chain']) as (repo, account):
                assert repo.deactivate_claim(int(first['id']), account['id'])
        else:
            w.ownership.admin_moderate_claim(int(first['id']), w.principal('admin'), action)
        w.current('chain', 'c', former=('a', 'b'))
        assert w.detail('c', second)['acceptance'] == evidence
        assert int(first['id']) not in w.ownership.owner_verifiable_claim_ids(w.ids['chain'], w.principal('a'))
    # A newly accepted owner retains authority over other people's ordinary
    # content, including after the preceding transfer was removed.
    with connect(w.db_owner, 'chronicle') as con:
        claim = con.execute('''INSERT INTO claims(individual_id,author_user_id,
            claim_type,field_name,value_text,body,verification_status,occurred_at,
            created_at,updated_at) VALUES(%s,%s,'incident','incident_type','damage',
                %s,'unverified','2026-02-01','2026-02-01','2026-02-01') RETURNING id''',
            (w.ids['chain'], w.user('a'), PRIVATE)).fetchone()['id']
    w.unchanged(ValueError, lambda: w.ownership.set_claim_response(claim, w.principal('b'), 'positive'))
    assert w.ownership.set_claim_response(claim, w.principal('c'), 'positive')
    w.current('chain', 'c', former=('a', 'b'))


def canonical_and_ban_checks(w):
    proposal = w.create('pending_profile')
    for name in ('a', 'b'):
        for changes, restore in (({'disabled': 1}, {'disabled': 0}),
                ({'account_type': 'source'}, {'account_type': 'user'}),
                ({'ban_status': 'ban'}, {'ban_status': 'normal'}),
                ({'ban_status': 'silent_ban'}, {'ban_status': 'normal'})):
            w.canonical(name, **changes)
            w.unchanged((PermissionError, ValueError), lambda: w.resolve('b', proposal, 'accept'))
            if name == 'a' and changes == {'disabled': 1}:
                assert w.accounts.drain_projection(limit=1000) > 0
                assert not w.detail('b', proposal)['can_accept']
                w.unchanged(PermissionError, lambda: w.resolve('b', proposal, 'accept'))
            w.canonical(name, **restore)
            assert w.accounts.drain_projection(limit=1000) > 0
    w.canonical('b', bio=PRIVATE + '-pending-profile')
    w.unchanged((ValueError, ClaimConflict), lambda: w.resolve('b', proposal, 'accept'))
    assert w.accounts.drain_projection(limit=1000) > 0
    assert w.resolve('b', w.detail('b', proposal), 'accept')['state'] == 'accepted'

    # A recipient whose content identity disappears is never reconstructed by
    # the private read/search path, and cannot accept with an old browser form.
    deleted = w.create('deleted', target='retired')
    with connect(w.db_owner, 'chronicle') as con:
        con.execute('DELETE FROM users WHERE id=%s', (w.user('retired'),))
    w.unchanged((ValueError, GuitarMissing), lambda: w.resolve('retired', deleted, 'accept'))
    before = w.snapshot()
    candidates = w.service.search_users(w.actor('a'), w.ids['guard'], q='retired')
    assert candidates['items'] == [] and w.snapshot() == before
    # Restore this owner-tampered fixture only after the negative assertions;
    # otherwise its missing projection would intentionally block A's later inbox.
    with connect(w.db_owner, 'accounts') as con:
        account = con.execute('SELECT * FROM account_records WHERE id=%s', (w.user('retired'),)).fetchone()
    PostgresAccounts(w.db_owner)._project(account)

    first = w.create('ban')
    first = w.resolve('b', w.detail('b', first), 'accept')
    w.current('ban', 'b', former=('a',))
    # BAN arrives in canonical Accounts first. Projection delivery changes the
    # Snapshot and Owned classification even though B authored no Claim here.
    w.canonical('b', ban_status='ban')
    w.unchanged(PermissionError, lambda: w.service.release(w.actor('b'), w.ids['ban'],
        {'occurred_at': '2026-02-01', 'body': None, 'revision': 'a' * 64}))
    assert w.accounts.drain_projection(limit=1000) > 0
    w.current('ban', 'a')
    with connect(w.settings, 'chronicle') as con:
        assert con.execute('SELECT state FROM claim_transfers WHERE claim_id=%s', (int(first['id']),)).fetchone()['state'] == 'accepted'
        evidence = con.execute('SELECT * FROM claim_transfer_acceptance WHERE claim_id=%s', (int(first['id']),)).fetchone()
        assert evidence['accepted_by_user_id'] == w.user('b')
    w.canonical('b', ban_status='normal')
    assert w.accounts.drain_projection(limit=1000) > 0
    w.current('ban', 'b', former=('a',))
    assert w.detail('b', first)['acceptance'] == first['acceptance']


def race_checks(w):
    stale = w.create('stale')
    newer = w.create('stale', target='c')
    w.resolve('c', w.detail('c', newer), 'accept')
    w.unchanged((ClaimConflict, ValueError), lambda: w.resolve('b', stale, 'accept'))
    w.current('stale', 'c', former=('a',))

    left = w.create('race_accept')
    right = w.create('race_accept', target='c')
    w.unchanged(ClaimConflict, lambda: w.resolve('b', left, 'accept'))
    left, right = w.detail('b', left), w.detail('c', right)
    gate = Barrier(2)

    def accept(pair):
        name, row = pair
        gate.wait(timeout=10)
        try:
            return name, w.resolve(name, row, 'accept')
        except (ClaimConflict, ValueError):
            return name, None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(accept, (('b', left), ('c', right))))
    winners = [(name, row) for name, row in results if row is not None]
    assert len(winners) == 1, results
    winner, accepted = winners[0]
    w.current('race_accept', winner, former=('a',))
    with connect(w.settings, 'chronicle') as con:
        assert con.execute('''SELECT COUNT(*) AS n FROM claim_transfer_acceptance e
            JOIN claims c ON c.id=e.claim_id WHERE c.individual_id=%s''', (w.ids['race_accept'],)).fetchone()['n'] == 1
    loser, lost = next((name, row) for name, row in (('b', left), ('c', right)) if name != winner)
    w.unchanged((ClaimConflict, ValueError), lambda: w.resolve(loser, lost, 'accept'))

    proposal = w.create('race_release')
    seen = w.view('a', 'race_release')
    gate = Barrier(2)

    def accept_or_release(action):
        gate.wait(timeout=10)
        try:
            result = (w.resolve('b', proposal, 'accept') if action == 'accept'
                      else w.release('race_release', seen=seen))
            return action, result
        except (ClaimConflict, PermissionError, ValueError):
            return action, None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(accept_or_release, ('accept', 'release')))
    winners = [(action, result) for action, result in results if result is not None]
    assert len(winners) == 1, results
    won, _ = winners[0]
    w.current('race_release', 'b' if won == 'accept' else None, former=('a',))
    with connect(w.settings, 'chronicle') as con:
        accepted_count = con.execute('SELECT COUNT(*) AS n FROM claim_transfer_acceptance WHERE claim_id=%s', (int(proposal['id']),)).fetchone()['n']
        release_count = con.execute("SELECT COUNT(*) AS n FROM claims WHERE individual_id=%s AND ownership_kind='release'", (w.ids['race_release'],)).fetchone()['n']
        assert (accepted_count, release_count) == ((1, 0) if won == 'accept' else (0, 1))


def rollback_checks(w):
    for table in ('claims', 'claim_transfers', 'notifications'):
        with reject_rows(w.db_owner, table):
            w.unchanged(errors.CheckViolation, lambda: w.create('fault_create'))
    proposal = w.create('fault_accept')
    for table in ('claim_transfer_acceptance', 'user_guitars', 'claims',
                  'claim_transfers', 'individuals', 'notifications'):
        with reject_rows(w.db_owner, table):
            w.unchanged(errors.CheckViolation, lambda: w.resolve('b', proposal, 'accept'))
        assert w.detail('b', proposal)['state'] == 'pending'
    assert w.resolve('b', proposal, 'accept')['state'] == 'accepted'
    for table in ('claims', 'user_guitars', 'individuals'):
        with reject_rows(w.db_owner, table):
            w.unchanged(errors.CheckViolation, lambda: w.release('fault_release'))
    assert w.release('fault_release')['ownership']['current_owner_user_id'] is None

    # All SQL succeeded until Observation discovered a newer fixture claim.
    # The service must roll back evidence, history, notification acknowledgement
    # and Snapshot together, instead of recording a transfer that did not occur.
    proposal = w.create('chronology_accept')
    w.unchanged((ClaimConflict, ValueError), lambda: w.resolve('b', proposal, 'accept'))
    assert w.detail('b', proposal)['state'] == 'pending'
    w.current('chronology_accept', 'a')
    seen = w.view('a', 'chronology_release')
    historical = w.release('chronology_release', seen=seen)
    assert historical['claim']['occurred_at'] == '2026-02-01'
    assert historical['ownership']['current_owner_user_id'] == str(w.user('a'))
    assert historical['ownership']['revision'] != seen['revision']
    w.unchanged(ClaimConflict, lambda: w.release('chronology_release', seen=seen))
    w.current('chronology_release', 'a')

    proposal = w.create('guard')
    seen = w.view('a', 'guard')
    with connect(w.db_owner, 'operations') as guard:
        guard.execute('SELECT pg_advisory_xact_lock(79432190)')
        assert w.detail('b', proposal)['state'] == 'pending'
        w.unchanged(ClaimConflict, lambda: w.resolve('b', proposal, 'accept'))
        w.unchanged(ClaimConflict, lambda: w.create('guard', target='c'))
        w.unchanged(ClaimConflict, lambda: w.release('guard', seen=seen))


def service_mode_checks(w):
    normal = w.create('mode_a')
    admin = w.create('mode_admin', source='admin')
    captured = {name: w.view(name, guitar) for name, guitar in
                (('a', 'mode_a'), ('b', 'mode_a'), ('admin', 'mode_admin'))}

    def propose(name, guitar):
        return w.service.create(w.actor(name), w.ids[guitar], {
            'to_user_id': str(w.user('c')), 'revision': captured[name]['revision']})

    def release(name, guitar):
        return w.service.release(w.actor(name), w.ids[guitar], {
            'occurred_at': '2026-02-01', 'body': None, 'revision': captured[name]['revision']})

    w.mode('read_only')
    try:
        for name, guitar, row in (('a', 'mode_a', normal), ('admin', 'mode_admin', admin)):
            view = w.view(name, guitar)
            assert not view['can_write'] and not view['can_transfer'] and not view['can_release']
            assert w.service.inbox(w.actor(name))['can_write'] is False
            detail = w.detail(name, row)
            assert not any(detail[key] for key in ('can_write', 'can_accept', 'can_decline', 'can_cancel'))
            w.unchanged(ServiceRestricted, lambda: propose(name, guitar))
            w.unchanged(ServiceRestricted, lambda: release(name, guitar))
            w.unchanged(ServiceRestricted, lambda: w.resolve(name, row, 'cancel'))
        w.unchanged(ServiceRestricted, lambda: w.resolve('b', normal, 'accept'))
        w.unchanged(ServiceRestricted, lambda: w.resolve('b', normal, 'decline'))
        for mode in ('offline', 'admin_only'):
            w.mode(mode)
            for name in (('a', 'b', 'admin') if mode == 'offline' else ('a', 'b')):
                guitar = 'mode_admin' if name == 'admin' else 'mode_a'
                row = admin if name == 'admin' else normal
                w.unchanged(ServiceRestricted, lambda: w.view(name, guitar))
                w.unchanged(ServiceRestricted, lambda: w.service.inbox(w.actor(name)))
                w.unchanged(ServiceRestricted, lambda: w.detail(name, row))
                w.unchanged(ServiceRestricted, lambda: w.service.search_users(w.actor(name), w.ids[guitar], q='Scoped'))
                w.unchanged(ServiceRestricted, lambda: propose(name, guitar))
                w.unchanged(ServiceRestricted, lambda: release(name, guitar))
                w.unchanged(ServiceRestricted, lambda: w.resolve(name, row,
                    'accept' if name == 'b' else 'cancel'))
        assert w.view('admin', 'mode_admin')['can_write'] is True
        assert w.resolve('admin', admin, 'cancel')['state'] == 'cancelled'
        assert w.release('mode_admin', 'admin')['ownership']['current_owner_user_id'] is None
        # Cached credentials do not keep a revoked administrator role.
        w.canonical('admin', role='member')
        w.unchanged(ServiceRestricted, lambda: w.service.inbox(w.actor('admin')))
        w.canonical('admin', role='admin')
        assert w.accounts.drain_projection(limit=1000) > 0
    finally:
        w.mode('normal')


def pagination_and_read_checks(w):
    # Three current/past proposals on one guitar exercise a keyset boundary
    # whose decimal cursor cannot survive conversion through a JS Number.
    for target in ('candidate_1', 'candidate_2', 'candidate_3'):
        row = w.create('guard', target=target)
        w.resolve('a', row, 'cancel')
    full = w.view('a', 'guard', limit=50)['items']
    paged, after = [], 0
    while True:
        page = w.view('a', 'guard', after=after, limit=2)
        paged.extend(page['items'])
        if page['next_after'] is None:
            break
        exact_id(page['next_after'])
        assert page['next_after'] == page['items'][-1]['id']
        after = int(page['next_after'])
        assert len(paged) <= len(full)
    assert paged == full
    assert [int(row['id']) for row in full] == sorted({int(row['id']) for row in full}, reverse=True)
    full = w.service.inbox(w.actor('a'), limit=50)['items']
    paged, after = [], 0
    while True:
        page = w.service.inbox(w.actor('a'), after=after, limit=2)
        assert set(page) == {'viewer_user_id', 'items', 'can_write', 'next_after'}
        exact_id(page['viewer_user_id'], w.user('a'))
        paged.extend(page['items'])
        for row in page['items']:
            w.transfer(row)
            assert str(w.user('a')) in (row['from_user']['id'], row['to_user']['id'])
        if page['next_after'] is None:
            break
        exact_id(page['next_after'])
        after = int(page['next_after'])
        assert len(paged) <= len(full)
    assert paged == full
    for query in ({'after': -1}, {'after': 2**63}, {'after': True}, {'limit': 0}, {'limit': 51}):
        w.unchanged(ValueError, lambda: w.view('a', 'guard', **query))
        w.unchanged(ValueError, lambda: w.service.inbox(w.actor('a'), **query))
    before = w.snapshot()
    for name in ('a', 'b'):
        w.view(name, 'privacy')
    for name in ('a', 'b', 'c', 'admin'):
        w.service.inbox(w.actor(name))
    w.service.search_users(w.actor('a'), w.ids['guard'], q='candidate')
    assert w.snapshot() == before, 'Private GETs performed data repair or notification acknowledgement'
    with connect(w.settings, 'chronicle') as con:
        assert con.execute('SELECT COUNT(*) AS n FROM observations').fetchone()['n'] == 0


def run(port):
    prefix = 'ygctest_ownership_' + uuid.uuid4().hex[:10] + '_'
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
            records, ids = seed(owner)
            original_grants = grants(app)
            operations = PostgresOperations(app)
            workflow = Workflow(app, owner, records, ids, operations)
            workflow.mode('normal')
            pending = identity_search_privacy(workflow)
            release_checks(workflow)
            accepted_and_repeated_checks(workflow, pending)
            independent_chain_checks(workflow)
            canonical_and_ban_checks(workflow)
            race_checks(workflow)
            rollback_checks(workflow)
            service_mode_checks(workflow)
            pagination_and_read_checks(workflow)
            assert grants(app) == original_grants, 'Runtime privileges changed during checks'
            print('PostgreSQL Cloud Transfer/Release: canonical principal and participant '
                  'privacy, scoped minimal recipient search, exact large IDs, Release '
                  'revision/owner fences, acceptance evidence/history, idempotent '
                  'resolution and Admin Verification, independent A→B→C, canonical '
                  'BAN projection, competing writes, service modes and atomic '
                  'chronology/SQL-failure rollback passed with unchanged runtime grants.')
        finally:
            for name in reversed(databases):
                system.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            system.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(runtime)))
