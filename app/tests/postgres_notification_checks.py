"""Synthetic notification contracts on disposable loopback PostgreSQL only.

Registered in run_postgres_checks.py. Import/compilation starts no server and
opens no sockets. Fixture setup and reversible failure injection use the database
owner; every product operation uses the existing restricted runtime role. No
cloud account, credential, live database, migration or privilege expansion is used.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from itertools import count
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
from postgres_media_claim_checks import BIG_ID, Storage, rejected, reject_new_rows, seed, seed_acquire
from ygc.admin_bootstrap_job import grant_first_admin
from ygc.claim_revision import ClaimConflict
from ygc.cloud_claims import CloudClaims
from ygc.cloud_notification_routes import notification_router
from ygc.cloud_notifications import CloudNotifications, NotificationMissing
from ygc.cloud_owner import CloudOwner
from ygc.cloud_owner_routes import owner_router
from ygc.cloud_ownership import CloudOwnership
from ygc.db.postgres import PostgresSettings, bootstrap, connect, migrate
from ygc.db.postgres_accounts import PostgresAccounts
from ygc.db.postgres_operations import PostgresOperations, ServiceRestricted
from ygc.db.postgres_ownership import BoundRepository
from ygc.db.postgres_queries import ObservationConnection
from ygc.identity_platform import VerifiedIdentity

ISSUER = 'local-private-notification-contract'
PRIVATE = 'NOTIFICATION-PRIVATE-DO-NOT-PUBLISH'
STAMP = '2026-06-01T12:00:00+00:00'
ITEM_FIELDS = {'id', 'notification_type', 'title', 'body', 'created_at', 'is_read',
               'read_at', 'actor', 'destination'}


def decimal(value, expected=None):
    assert isinstance(value, str) and re.fullmatch(r'0|[1-9][0-9]*', value), value
    if expected is not None:
        assert value == str(expected), (value, expected)
    return int(value)


class Workflow:
    def __init__(self, settings, owner, accounts, operations, records, fixture, storage):
        self.settings, self.db_owner = settings, owner
        self.accounts, self.operations = accounts, operations
        self.records, self.fixture = records, fixture
        self.service = CloudNotifications(settings, operations)
        self.owners = CloudOwner(settings, operations)
        self.claims = CloudClaims(settings, operations, storage=storage)
        self.ownership = CloudOwnership(settings, operations)

    def actor(self, name):
        return self.records[name]['app_user_id']

    def user(self, name):
        return self.records[name]['id']

    def canonical(self, name, **changes):
        with connect(self.db_owner, 'accounts') as con:
            assignments = sql.SQL(',').join(sql.SQL('{}=%s').format(sql.Identifier(key)) for key in changes)
            con.execute(sql.SQL('UPDATE account_records SET {} WHERE id=%s').format(assignments),
                        (*changes.values(), self.user(name)))

    def snapshot(self):
        """Whole Chronicle state catches even unexpected read-side mutations."""
        with connect(self.settings, 'chronicle') as con:
            tables = [row['tablename'] for row in con.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
            return {table: [row['value'] for row in con.execute(sql.SQL(
                'SELECT to_jsonb(t) AS value FROM {} t ORDER BY to_jsonb(t)::text')
                .format(sql.Identifier(table)))] for table in tables}

    def unchanged(self, error, operation):
        before = self.snapshot()
        rejected(error, operation)
        assert self.snapshot() == before, 'Rejected action left Chronicle writes behind'

    def notice(self, recipient='a', *, actor='b', claim=None, individual=None,
               kind='history', read=False, body=PRIVATE, title='Synthetic history'):
        with connect(self.db_owner, 'chronicle') as con:
            return con.execute('''INSERT INTO notifications(recipient_user_id,actor_user_id,
                notification_type,individual_id,claim_id,title,body,is_read,created_at,read_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
                (self.user(recipient), self.user(actor) if actor else None, kind,
                 individual, claim, title, body, int(read), STAMP, STAMP if read else None)).fetchone()['id']

    def raw_claim(self, name='b', *, status='active', individual=None):
        with connect(self.db_owner, 'chronicle') as con:
            return con.execute('''INSERT INTO claims(individual_id,author_user_id,claim_type,
                field_name,value_text,body,status,verification_status,occurred_at,created_at,updated_at)
                VALUES(%s,%s,'event','event_kind','performance',%s,%s,'unverified',
                    '2026-03-01',%s,%s) RETURNING id''',
                (individual or self.fixture['individual'], self.user(name), PRIVATE, status,
                 STAMP, STAMP)).fetchone()['id']

    def claim(self, name='b', *, individual=None):
        return self.claims.create(self.actor(name), individual or self.fixture['individual'],
            dict(claim_type='event', event_kind='performance', body=PRIVATE,
                 occurred_at='2026-03-01'))['claim']

    def pending(self, claim, name='a', *, individual=None):
        return next(row for row in self.owners.pending(self.actor(name),
            individual or self.fixture['individual'])['items'] if row['id'] == str(claim))

    def respond(self, row, stance='positive', name='a', **extra):
        return self.owners.respond(self.actor(name), int(row['individual_id']), int(row['id']),
                                  dict(stance=stance, revision=row['revision']) | extra)

    def mode(self, value):
        admin = self.actor('admin')
        self.operations.set_mode(admin, mode=value, message='',
                                 version=self.operations.details(admin)['version'])

    def notices(self, *, claim=None, kind=None):
        with connect(self.settings, 'chronicle') as con:
            return [dict(row) for row in con.execute('''SELECT * FROM notifications
                WHERE (%s::bigint IS NULL OR claim_id=%s) AND (%s::text IS NULL OR notification_type=%s)
                ORDER BY id''', (claim, claim, kind, kind))]

    def list(self, name='a', **pagination):
        result = self.service.list(self.actor(name), **pagination)
        assert set(result) == {'items', 'next_after', 'unread_count', 'can_write'}
        decimal(result['unread_count'])
        assert type(result['can_write']) is bool
        if result['next_after'] is not None:
            assert decimal(result['next_after']) > 2**53
        for row in result['items']:
            assert set(row) == ITEM_FIELDS and decimal(row['id']) > 2**53
            assert type(row['is_read']) is bool
            if row['actor'] is not None:
                assert set(row['actor']) == {'id', 'display_name'}
                assert decimal(row['actor']['id']) > 2**53
            destination = row['destination']
            if destination is not None:
                assert destination['kind'] in ('owner', 'transfer', 'dispute', 'dispute_option')
                if destination['kind'] == 'dispute':
                    assert set(destination) == {'kind', 'case_id'}
                    decimal(destination['case_id'])
                else:
                    assert decimal(destination['claim_id']) > 2**53
                    if destination['kind'] == 'owner':
                        assert set(destination) == {'kind', 'individual_id', 'claim_id'}
                        assert decimal(destination['individual_id']) > 2**53
                    else:
                        assert set(destination) == {'kind', 'claim_id'}
        payload = json.dumps(result)
        for secret in ('recipient_user_id', 'app_user_id', 'identity_subject', 'storage_path',
                       'claim_responses', 'acknowledged_at', 'projection_version'):
            assert secret not in payload
        return result


def read_changes_only(before, after, allowed):
    """Only the selected existing notification read fields may change."""
    assert before.keys() == after.keys()
    for table in before:
        if table != 'notifications':
            assert after[table] == before[table], 'Inbox changed ' + table
    old = {row['id']: row for row in before['notifications']}
    new = {row['id']: row for row in after['notifications']}
    assert old.keys() == new.keys(), 'Reading created or removed a notification'
    for key in old:
        if key not in allowed:
            assert old[key] == new[key], 'Reading changed hidden/foreign history'
            continue
        assert {k: v for k, v in old[key].items() if k not in ('is_read', 'read_at')} == {
            k: v for k, v in new[key].items() if k not in ('is_read', 'read_at')}
        assert new[key]['is_read'] == 1 and new[key]['read_at']
        if old[key]['read_at'] is not None:
            assert new[key]['read_at'] == old[key]['read_at']


def inbox_checks(w):
    assert w.list()['items'] == [] and w.list()['unread_count'] == '0'
    active = w.raw_claim()
    banned_claim, silent_claim = w.raw_claim('banned'), w.raw_claim('silent')
    visible = [w.notice(actor=None), w.notice(claim=active, individual=w.fixture['individual'], kind='claim_added'),
               w.notice(read=True, body=None), w.notice(kind='future_unknown', body='<script>plain history</script>')]
    foreign = [w.notice('b'), w.notice('admin')]
    hidden = [w.notice(actor='banned'), w.notice(actor='silent'),
              w.notice(actor='a', claim=banned_claim), w.notice(actor='a', claim=silent_claim),
              w.notice(claim=w.fixture['hidden_claim'], individual=w.fixture['hidden'])]
    w.canonical('banned', ban_status='ban')
    w.canonical('silent', ban_status='silent_ban')
    w.accounts.drain_projection()
    before = w.snapshot()
    ids, after = [], 0
    while True:
        page = w.list(after=after, limit=2)
        decimal(page['unread_count'], 3)
        assert len(page['items']) <= 2
        ids.extend(int(row['id']) for row in page['items'])
        if page['next_after'] is None:
            break
        after = int(page['next_after'])
    assert ids == sorted(visible, reverse=True) and len(ids) == len(set(ids))
    assert w.service.unread_count(w.actor('a')) == {'unread_count': '3', 'can_write': True}
    assert [int(row['id']) for row in w.list('b')['items']] == foreign[:1]
    assert [int(row['id']) for row in w.list('admin')['items']] == foreign[1:]
    items = {int(row['id']): row for row in w.list()['items']}
    assert items[visible[0]]['actor'] is None and items[visible[0]]['destination'] is None
    assert items[visible[1]]['destination'] == dict(kind='owner',
        individual_id=str(w.fixture['individual']), claim_id=str(active))
    assert items[visible[3]]['destination'] is None
    # The local inbox read predicate is the compatibility oracle, while cloud
    # keyset pagination deliberately orders by exact descending notification ID.
    with connect(w.settings, 'chronicle') as con:
        repo = BoundRepository(ObservationConnection(con))
        assert {row['id'] for row in repo.list_notifications(w.user('a'))} == set(visible)
        assert repo.unread_notification_count(w.user('a')) == 3
    assert w.snapshot() == before, 'List/count mutated history or Claims'
    for notification in foreign + hidden + [BIG_ID + 999999]:
        w.unchanged(NotificationMissing, lambda: w.service.mark_read(w.actor('a'), notification))
    first = w.service.mark_read(w.actor('a'), visible[0])
    assert set(first) == {'id', 'is_read', 'read_at', 'unread_count'}
    assert first['is_read'] is True and first['unread_count'] == '2'
    decimal(first['id'], visible[0])
    with patch('ygc.cloud_notifications.utcnow', return_value='2026-09-01T00:00:00+00:00'):
        repeated = w.service.mark_read(w.actor('a'), visible[0])
    assert repeated == first
    read_changes_only(before, w.snapshot(), {visible[0]})
    prior = w.snapshot()
    assert w.service.mark_all_read(w.actor('a')) == {'marked_count': '2', 'unread_count': '0'}
    read_changes_only(prior, w.snapshot(), set(visible))
    assert w.service.mark_all_read(w.actor('a')) == {'marked_count': '0', 'unread_count': '0'}
    assert all(row['is_read'] for row in w.list()['items'])
    for after, limit in ((-1, 2), (True, 2), (0, False), (0, 0), (0, 51), (2**63, 2), ('0', 2)):
        w.unchanged(ValueError, lambda: w.service.list(w.actor('a'), after=after, limit=limit))
    for notification in (0, -1, True, str(visible[0]), 2**63):
        w.unchanged(ValueError, lambda: w.service.mark_read(w.actor('a'), notification))
    return visible[0]


def fence_checks(w, notification):
    operations = (lambda: w.list(), lambda: w.service.unread_count(w.actor('a')),
                  lambda: w.service.mark_read(w.actor('a'), notification),
                  lambda: w.service.mark_all_read(w.actor('a')))
    # Stale canonical actors, authors and recipients must fail closed even when
    # their old projected fields would hide the row from this page.
    for name in ('a', 'b', 'banned'):
        w.canonical(name, display_name=PRIVATE + '-pending-' + name)
        for action in operations:
            w.unchanged(ValueError, action)
        w.accounts.drain_projection()
        assert w.list()['items']
    for column, value, restore in (('disabled', 1, 0), ('ban_status', 'ban', 'normal'),
                                   ('account_type', 'source', 'user')):
        w.canonical('a', **{column: value})
        for action in operations:
            w.unchanged(PermissionError, action)
        w.canonical('a', **{column: restore})
        w.accounts.drain_projection()
    # Receipt/ID drift cannot be repaired by a read and must not widen identity.
    with connect(w.db_owner, 'chronicle') as con:
        con.execute('UPDATE account_projection_receipts SET revision=revision+1 WHERE account_id=%s', (w.user('a'),))
    try:
        for action in operations:
            w.unchanged(ValueError, action)
    finally:
        with connect(w.db_owner, 'chronicle') as con:
            con.execute('UPDATE account_projection_receipts SET revision=revision-1 WHERE account_id=%s', (w.user('a'),))
    w.mode('read_only')
    try:
        for name in ('a', 'admin'):
            assert w.list(name)['can_write'] is False
            assert w.service.unread_count(w.actor(name))['can_write'] is False
            w.unchanged(ServiceRestricted, lambda: w.service.mark_read(w.actor(name), notification))
            w.unchanged(ServiceRestricted, lambda: w.service.mark_all_read(w.actor(name)))
    finally:
        w.mode('normal')
    for mode in ('offline', 'admin_only'):
        w.mode(mode)
        try:
            for action in operations:
                w.unchanged(ServiceRestricted, action)
            if mode == 'offline':
                for action in (lambda: w.list('admin'), lambda: w.service.unread_count(w.actor('admin')),
                               lambda: w.service.mark_all_read(w.actor('admin'))):
                    w.unchanged(ServiceRestricted, action)
            else:
                assert w.list('admin')['can_write'] is True
                # Mode permits an administrator only their own inbox, never IDOR.
                w.unchanged(NotificationMissing, lambda: w.service.mark_read(w.actor('admin'), notification))
                assert w.service.mark_all_read(w.actor('admin'))['unread_count'] == '0'
        finally:
            w.mode('normal')
    before = w.snapshot()
    with connect(w.settings, 'operations') as guard:
        guard.execute('SELECT pg_advisory_xact_lock(79432190)')
        assert w.list()['can_write'] is True
        w.service.unread_count(w.actor('a'))
        rejected(ClaimConflict, lambda: w.service.mark_read(w.actor('a'), notification))
        rejected(ClaimConflict, lambda: w.service.mark_all_read(w.actor('a')))
    assert w.snapshot() == before


def concurrent_read_checks(w):
    for together in ('single-single', 'single-all'):
        notification = w.notice()
        before, gate, times = w.snapshot(), Barrier(2), count(1)
        def timestamp():
            return '2026-07-01T00:00:%02d+00:00' % next(times)
        def read(which):
            gate.wait(timeout=10)
            try:
                return w.service.mark_all_read(w.actor('a')) if which else w.service.mark_read(w.actor('a'), notification)
            except ClaimConflict:
                # Maintenance arbitration can reject one concurrent writer. A
                # safe later retry must preserve the winning first read stamp.
                return None
        with patch('ygc.cloud_notifications.utcnow', side_effect=timestamp):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(read, False), pool.submit(read, together == 'single-all')]
                results = [future.result(timeout=20) for future in futures]
        assert any(result is not None for result in results)
        saved = next(row for row in w.notices() if row['id'] == notification)
        assert saved['is_read'] == 1 and saved['read_at']
        for result in results:
            if result is not None and 'read_at' in result:
                assert result['read_at'] == saved['read_at']
        with patch('ygc.cloud_notifications.utcnow', return_value='2026-08-01T00:00:00+00:00'):
            assert w.service.mark_read(w.actor('a'), notification)['read_at'] == saved['read_at']
            w.service.mark_all_read(w.actor('a'))
        read_changes_only(before, w.snapshot(), {notification})
    # Legacy unread rows may already carry a first-read timestamp. Bulk reads
    # preserve it just as single reads do rather than silently replacing history.
    legacy = w.notice(read=True)
    with connect(w.db_owner, 'chronicle') as con:
        con.execute('UPDATE notifications SET is_read=0 WHERE id=%s', (legacy,))
    before = w.snapshot()
    with patch('ygc.cloud_notifications.utcnow', return_value='2026-08-02T00:00:00+00:00'):
        assert w.service.mark_all_read(w.actor('a')) == {'marked_count': '1', 'unread_count': '0'}
    assert next(row for row in w.notices() if row['id'] == legacy)['read_at'] == STAMP
    read_changes_only(before, w.snapshot(), {legacy})


def verification_checks(w):
    row = w.claim()
    claim = int(row['id'])
    with connect(w.db_owner, 'chronicle') as con:
        con.execute('UPDATE claims SET updated_at=%s WHERE id=%s', (STAMP, claim))
    review = w.pending(claim)
    assert not w.notices(claim=claim, kind='claim_verified')
    # First response is deliberately the existing stance at the exact existing
    # timestamp. A successful confirmation must still consume its revision.
    with patch('ygc.db.repository.utcnow', return_value=STAMP):
        for stance in ('unverified', 'unverified', 'positive', 'negative'):
            before = len(w.notices(claim=claim, kind='claim_verified'))
            result = w.respond(review, stance)
            assert result == {'claim_id': str(claim), 'verification_status': stance}
            notices = w.notices(claim=claim, kind='claim_verified')
            assert len(notices) == before + 1
            notice = notices[-1]
            assert notice['id'] > 2**53 and notice['claim_id'] == claim
            assert notice['recipient_user_id'] == w.user('b') and notice['actor_user_id'] == w.user('a')
            assert notice['individual_id'] == w.fixture['individual'] and notice['is_read'] == 0
            assert notice['created_at'] == STAMP and stance.title() in notice['title']
            w.unchanged(ClaimConflict, lambda: w.respond(review, stance))
            fresh = w.pending(claim)
            assert fresh['revision'] != review['revision']
            review = fresh
    # Inbox state does not alter the full-content confirmation token.
    w.service.mark_read(w.actor('b'), notice['id'])
    assert w.pending(claim)['revision'] == review['revision']
    w.respond(review, 'positive')
    review = w.pending(claim)
    before = w.snapshot()
    with reject_new_rows(w.db_owner, 'notifications'):
        rejected(errors.CheckViolation, lambda: w.respond(review, 'negative'))
    assert w.snapshot() == before, 'Notice insertion failure committed a decision'
    # Even failure after the insert rolls back both decision and author notice.
    original = BoundRepository.create_verification_notification_in_connection
    def fail_after_notice(repo, *args, **kwargs):
        original(repo, *args, **kwargs)
        raise RuntimeError('Synthetic failure after author notice')
    with patch.object(BoundRepository, 'create_verification_notification_in_connection', fail_after_notice):
        rejected(RuntimeError, lambda: w.respond(review, 'negative'))
    assert w.snapshot() == before
    own = w.claim('a')
    for name, target in (('a', own), ('b', row), ('c', row), ('admin', row)):
        w.unchanged(ValueError, lambda: w.respond(target, name=name))
    # Current content modifications reject a stale confirmation without notices.
    stale = w.pending(claim)
    with connect(w.db_owner, 'chronicle') as con:
        con.execute('UPDATE claims SET body=%s WHERE id=%s', (PRIVATE + '-changed', claim))
    w.unchanged(ClaimConflict, lambda: w.respond(stale))
    # Two simultaneous requests carry one confirmation. The winner commits one
    # author notice; either maintenance arbitration or the consumed revision
    # rejects the loser, including an equal-time/equal-stance decision.
    raced = int(w.claim()['id'])
    with connect(w.db_owner, 'chronicle') as con:
        con.execute('UPDATE claims SET updated_at=%s WHERE id=%s', (STAMP, raced))
    same, gate = w.pending(raced), Barrier(2)
    def decide():
        gate.wait(timeout=10)
        try:
            w.respond(same, 'unverified')
            return 'accepted'
        except ClaimConflict:
            return 'conflict'
    with patch('ygc.db.repository.utcnow', return_value=STAMP):
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(decide), pool.submit(decide)]
            results = [future.result(timeout=20) for future in futures]
    assert sorted(results) == ['accepted', 'conflict']
    assert len(w.notices(claim=raced, kind='claim_verified')) == 1
    w.unchanged(ClaimConflict, lambda: w.respond(same, 'unverified'))
    return claim


def former_pair_checks(w):
    pair, claims = uuid.uuid4().hex, []
    with connect(w.db_owner, 'chronicle') as con:
        for kind, date in (('acquire', '2025-01-01'), ('release', '2025-02-01')):
            claims.append(con.execute('''INSERT INTO claims(individual_id,author_user_id,claim_type,
                ownership_kind,ownership_source,ownership_pair_id,value_text,verification_status,
                occurred_at,created_at,updated_at)
                VALUES(%s,%s,'ownership',%s,'former_owner',%s,%s,'unverified',%s,%s,%s) RETURNING id''',
                (w.fixture['individual'], w.user('c'), kind, pair, str(w.user('c')), date, STAMP, STAMP)).fetchone()['id'])
    seen = [w.pending(claim) for claim in claims]
    with patch('ygc.db.repository.utcnow', return_value=STAMP):
        w.respond(seen[0], 'unverified')
        w.unchanged(ClaimConflict, lambda: w.respond(seen[1], 'unverified'))
        fresh = [w.pending(claim) for claim in claims]
        assert all(old['revision'] != new['revision'] for old, new in zip(seen, fresh))
        w.respond(fresh[1], 'unverified')
        w.unchanged(ClaimConflict, lambda: w.respond(fresh[0], 'unverified'))
    assert sum(len(w.notices(claim=claim, kind='claim_verified')) for claim in claims) == 2


def decline_and_side_effect_checks(w):
    guitar = w.fixture['other']
    acquire = seed_acquire(w.db_owner, w.user('b'), guitar)
    with connect(w.db_owner, 'chronicle') as con:
        con.execute('''INSERT INTO acquire_applications(revision,applicant_id,individual_id,
            original_individual_id,serial,challenge,expires_at,created_at,status,prompt_version,claim_id)
            VALUES(%s,%s,%s,%s,'SYNTHETIC','SYNTHETIC',0,%s,'accepted','synthetic-notifications',%s)''',
            (uuid.uuid4().hex, w.user('b'), guitar, guitar, STAMP, acquire))
    review = w.pending(acquire, individual=guitar)
    assert review['decline_reason_required'] is True
    w.unchanged(ValueError, lambda: w.respond(review, 'negative'))
    before = w.snapshot()
    with reject_new_rows(w.db_owner, 'notifications'):
        rejected(errors.CheckViolation, lambda: w.respond(review, 'negative', reason='Synthetic decline reason'))
    assert w.snapshot() == before
    w.respond(review, 'negative', reason='Synthetic decline reason')
    notices = w.notices(claim=acquire)
    assert {row['notification_type'] for row in notices} == {'claim_verified', 'ownership_decline'}
    assert len(notices) == 2 and all(row['recipient_user_id'] == w.user('b') for row in notices)
    decline_notice = next(row for row in notices if row['notification_type'] == 'ownership_decline')
    before = w.snapshot()
    decline_item = next(row for row in w.list('b', limit=50)['items'] if row['id'] == str(decline_notice['id']))
    assert decline_item['destination'] == {'kind': 'dispute_option', 'claim_id': str(acquire)}
    assert w.snapshot() == before, 'Resolving the dispute option destination changed business state'
    w.unchanged(ClaimConflict, lambda: w.respond(review, 'negative', reason='Synthetic decline reason'))
    view = w.ownership.view(w.actor('a'), guitar)
    transfer = w.ownership.create(w.actor('a'), guitar,
        {'to_user_id': str(w.user('c')), 'revision': view['revision']})['transfer']
    transfer_id = int(transfer['id'])
    transfer_notice = next(row for row in w.notices(claim=transfer_id) if row['recipient_user_id'] == w.user('c'))
    item = next(row for row in w.list('c')['items'] if row['id'] == str(transfer_notice['id']))
    assert item['destination'] == {'kind': 'transfer', 'claim_id': str(transfer_id)}
    with connect(w.db_owner, 'chronicle') as con:
        case = con.execute('''INSERT INTO ownership_disputes(individual_id,owner_id,locked_owner_id,
            created_at,updated_at) VALUES(%s,%s,%s,%s,%s) RETURNING id''',
            (w.fixture['absent'], w.user('a'), w.user('a'), STAMP, STAMP)).fetchone()['id']
        con.execute('''INSERT INTO ownership_dispute_events(dispute_id,actor_id,kind,note,created_at)
            VALUES(%s,%s,'opened','Synthetic dispute',%s)''', (case, w.user('b'), STAMP))
    dispute_notice = w.notice('a', kind='ownership_dispute', individual=w.fixture['absent'])
    before = w.snapshot()
    allowed = set()
    for name in ('a', 'b', 'c'):
        allowed.update(int(row['id']) for row in w.list(name, limit=50)['items'])
    for notice in notices:
        w.service.mark_read(w.actor('b'), notice['id'])
    w.service.mark_read(w.actor('c'), transfer_notice['id'])
    w.service.mark_read(w.actor('a'), dispute_notice)
    for name in ('a', 'b', 'c'):
        w.service.mark_all_read(w.actor(name))
    read_changes_only(before, w.snapshot(), allowed)
    with connect(w.settings, 'chronicle') as con:
        assert con.execute('SELECT acknowledged_at FROM ownership_declines WHERE claim_id=%s',
                           (acquire,)).fetchone()['acknowledged_at'] is None
        assert con.execute('SELECT state FROM claim_transfers WHERE claim_id=%s',
                           (transfer_id,)).fetchone()['state'] == 'pending'
        assert not con.execute('SELECT 1 FROM claim_transfer_acceptance WHERE claim_id=%s', (transfer_id,)).fetchone()
        assert con.execute('SELECT status,version FROM ownership_disputes WHERE id=%s',
                           (case,)).fetchone() == {'status': 'open', 'version': 1}
    # A later, separately authorized Transfer response keeps the already saved
    # inbox timestamp; its result notice retains a participant-only destination.
    first_read = next(row for row in w.notices(claim=transfer_id) if row['id'] == transfer_notice['id'])['read_at']
    seen = w.ownership.detail(w.actor('c'), transfer_id)
    with patch('ygc.db.repository.utcnow', return_value='2026-10-01T12:00:00+00:00'):
        result = w.ownership.resolve(w.actor('c'), transfer_id,
                                    {'action': 'decline', 'revision': seen['revision']})
    assert result['transfer']['state'] == 'declined'
    request = next(row for row in w.notices(claim=transfer_id) if row['id'] == transfer_notice['id'])
    assert request['read_at'] == first_read and request['is_read'] == 1
    resolved = w.notices(claim=transfer_id, kind='transfer_result')
    assert len(resolved) == 1 and resolved[0]['recipient_user_id'] == w.user('a')
    item = next(row for row in w.list('a', limit=50)['items'] if row['id'] == str(resolved[0]['id']))
    assert item['destination'] == {'kind': 'transfer', 'claim_id': str(transfer_id)}
    nonparticipant = w.notice('b', claim=transfer_id, individual=guitar, kind='transfer_result')
    item = next(row for row in w.list('b', limit=50)['items'] if row['id'] == str(nonparticipant))
    assert item['destination'] is None


def handoff_checks(w, ordinary):
    guitar = w.fixture['individual']
    stale = w.pending(ordinary)
    acquire = seed_acquire(w.db_owner, w.user('b'), guitar)
    review = w.pending(acquire)
    w.respond(review)
    with connect(w.settings, 'chronicle') as con:
        assert con.execute('SELECT current_owner_user_id FROM individuals WHERE id=%s',
                           (guitar,)).fetchone()['current_owner_user_id'] == w.user('b')
        classes = {row['user_id']: row['ownership_status'] for row in con.execute(
            'SELECT user_id,ownership_status FROM user_guitars WHERE individual_id=%s', (guitar,))}
        assert classes[w.user('a')] == 'former_owner' and classes[w.user('b')] == 'current_owner'
    assert w.owners.pending(w.actor('a'), guitar)['items'] == []
    w.unchanged(ClaimConflict, lambda: w.respond(stale))
    w.unchanged(ValueError, lambda: w.respond(review, name='b'))
    # Old recipient-owned history remains readable but cannot grant old authority.
    old_notice = next(row for row in w.notices(claim=ordinary, kind='claim_added'))
    old_item = next(row for row in w.list('a', limit=50)['items'] if row['id'] == str(old_notice['id']))
    assert old_item['destination'] is None
    before = w.snapshot()
    w.service.mark_read(w.actor('a'), old_notice['id'])
    read_changes_only(before, w.snapshot(), {old_notice['id']})
    # A new Claim by the former Owner is reviewable only by the new Owner.
    new = w.claim('a')
    current = w.pending(new['id'], name='b')
    w.respond(current, name='b')
    notice = w.notices(claim=int(new['id']), kind='claim_verified')
    assert len(notice) == 1 and notice[0]['recipient_user_id'] == w.user('a')
    assert notice[0]['actor_user_id'] == w.user('b')


def http_checks(w):
    class Verifier:
        accounts = w.accounts
        def verify(self, *, bearer_token):
            if bearer_token == 'unavailable':
                raise RuntimeError(PRIVATE)
            if bearer_token not in (*w.records, 'unverified'):
                raise PermissionError(PRIVATE)
            return VerifiedIdentity(ISSUER, 'a' if bearer_token == 'unverified' else bearer_token,
                                    '', bearer_token != 'unverified')
    api = FastAPI()
    api.include_router(notification_router(Verifier(), w.service))
    api.include_router(owner_router(Verifier(), w.owners))
    base = '/api/auth/notifications'
    notification, foreign = w.notice(), w.notice('b')
    headers = lambda name: {'Authorization': 'Bearer ' + name}
    def private(response):
        assert response.headers['cache-control'] == 'private, no-store'
        assert response.headers['vary'] == 'Authorization'
        assert response.headers['x-content-type-options'] == 'nosniff'
    def check(response, expected):
        assert response.status_code == expected, response.text
        private(response)
        if expected != 200:
            assert PRIVATE not in response.text and ISSUER not in response.text
    with TestClient(api) as client:
        before = w.snapshot()
        for name, code in ((None, 401), ('invalid', 401), ('unverified', 403), ('unavailable', 503)):
            auth = headers(name) if name else {}
            for path in (base, base + '/unread-count'):
                check(client.get(path, headers=auth), code)
            for path in (base + '/read-all', base + '/' + str(notification) + '/read'):
                check(client.post(path, headers=auth, json={}), code)
        assert w.snapshot() == before
        for path in (base, base + '/unread-count'):
            check(client.get(path, headers=headers('a')), 200)
        # Existing identifier parsing normalizes leading zeros on input.
        check(client.get(base + '?after=0' + str(notification), headers=headers('a')), 200)
        for query in ('?recipient_user_id=1', '?actor_user_id=1', '?limit=1&limit=2', '?after=0',
                      '?after=-1', '?after=9223372036854775808', '?limit=51',
                      '?limit=0', '?limit=1&after=1&unknown=1', '?after=' + '9' * 20):
            check(client.get(base + query, headers=headers('a')), 400)
        for path in (base, base + '/unread-count'):
            check(client.get(path + '?unexpected=x', headers=headers('a')), 400)
            check(client.request('GET', path, headers=headers('a'), content='{}'), 400)
        for notification_id in (foreign, BIG_ID + 999999):
            check(client.post(base + '/' + str(notification_id) + '/read', headers=headers('a'), json={}), 404)
        for target in ('0', '-1', 'NaN', '9223372036854775808', '9' * 20):
            check(client.post(base + '/' + target + '/read', headers=headers('a'), json={}), 400)
        for path in (base + '/read-all', base + '/' + str(notification) + '/read'):
            for body in ('null', '[]', 'false', '{"recipient_user_id":1}', '{"id":1,"id":2}', '{', ''):
                check(client.post(path, headers=headers('a') | {'Content-Type': 'application/json'}, content=body), 400)
            check(client.post(path, headers=headers('a') | {'Content-Type': 'application/json'},
                              content=' ' * 1023 + '{}'), 413)
            check(client.post(path, headers=headers('a'), content='{}'), 400)
            check(client.post(path + '?recipient_user_id=1', headers=headers('a'), json={}), 400)
            for extra, code in (({'Content-Encoding': 'gzip'}, 400),
                                ({'Origin': 'https://untrusted.invalid'}, 403),
                                ({'Sec-Fetch-Site': 'cross-site'}, 403)):
                check(client.post(path, headers=headers('a') | extra, json={}), code)
        assert w.snapshot() == before, 'Rejected HTTP input changed state'
        # Accepted HTTP writes retain the exact same recipient-only semantics.
        response = client.post(base + '/0' + str(notification) + '/read', headers=headers('a'), json={})
        check(response, 200)
        assert response.json()['id'] == str(notification) and response.json()['is_read'] is True
        check(client.post(base + '/read-all', headers=headers('a'), json={}), 200)
        visible = {int(row['id']) for row in w.list('a', limit=50)['items']}
        read_changes_only(before, w.snapshot(), visible)
        # Owner route uses the same atomic service, and a replay is an HTTP 409.
        claim = w.claim()
        review = w.pending(claim['id'])
        path = '/api/auth/guitars/' + str(w.fixture['individual']) + '/owner-responses/' + claim['id']
        data = {'stance': 'positive', 'revision': review['revision']}
        assert client.post(path, headers=headers('a'), json=data).status_code == 200
        before = w.snapshot()
        assert client.post(path, headers=headers('a'), json=data).status_code == 409
        assert w.snapshot() == before
        assert len(w.notices(claim=int(claim['id']), kind='claim_verified')) == 1


def run(port):
    prefix = 'ygctest_notifications_' + uuid.uuid4().hex[:10] + '_'
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
            for target in ('accounts', 'chronicle', 'operations'):
                with connect(settings, target) as con:
                    for query in ('CREATE TABLE notification_forbidden(id BIGINT)',
                                  'UPDATE ygc_schema_version SET version=version'):
                        def forbidden():
                            with con.transaction():
                                con.execute(query)
                        rejected(errors.InsufficientPrivilege, forbidden)
            with connect(owner, 'accounts') as con:
                con.execute("SELECT setval(pg_get_serial_sequence('account_records','id'),%s,false)", (BIG_ID + 1000,))
            with connect(owner, 'chronicle') as con:
                con.execute("SELECT setval(pg_get_serial_sequence('notifications','id'),%s,false)", (BIG_ID + 2000,))
            accounts, operations = PostgresAccounts(settings), PostgresOperations(settings)
            records = {name: accounts.ensure_identity(issuer=ISSUER, subject=name,
                display_name='Synthetic ' + name) for name in ('admin', 'a', 'b', 'c', 'banned', 'silent')}
            assert grant_first_admin(settings, records['admin']['app_user_id'], 'local-notification-test')
            accounts.drain_projection()
            admin = records['admin']['app_user_id']
            operations.set_mode(admin, mode='normal', message='', version=operations.details(admin)['version'])
            storage = Storage()
            fixture = seed(owner, records, storage)
            with connect(owner, 'chronicle') as con:
                # The Media suite intentionally leaves this individual with only
                # an inactive Media Claim. Notification projection-drift checks
                # rename its author, which correctly rebuilds every authored
                # individual, including inactive Claims. Supply complete active
                # identity evidence without activating its Media or adding any
                # owner, photos or notices. The separate absent scaffold has no
                # Claims or owner and is never selected by participant rebuilds.
                hidden = fixture['hidden']
                listing = con.execute('''INSERT INTO claims(individual_id,author_user_id,
                    claim_type,verification_status,occurred_at,created_at,updated_at)
                    VALUES(%s,%s,'listing','positive','2026-01-01','2026-01-01','2026-01-01')
                    RETURNING id''', (hidden, records['admin']['id'])).fetchone()['id']
                for field, value in (('manufacturer', 'Fender'), ('model', 'Telecaster'),
                                     ('serial_number', 'MEDIA-' + str(hidden))):
                    con.execute('''INSERT INTO claim_listing_items(claim_id,field_name,
                        value_text,created_at) VALUES(%s,%s,%s,'2026-01-01')''',
                        (listing, field, value))
                repo = BoundRepository(ObservationConnection(con))
                for individual in (fixture['individual'], fixture['other'], hidden):
                    repo._rebuild_individual_snapshot_in_connection(repo.connection, individual)
                assert con.execute('SELECT current_owner_user_id FROM individuals WHERE id=%s',
                                   (hidden,)).fetchone()['current_owner_user_id'] is None
                assert con.execute('SELECT status FROM claims WHERE id=%s',
                                   (fixture['hidden_claim'],)).fetchone()['status'] == 'inactive'
            w = Workflow(settings, owner, accounts, operations, records, fixture, storage)
            notification = inbox_checks(w)
            fence_checks(w, notification)
            concurrent_read_checks(w)
            ordinary = verification_checks(w)
            former_pair_checks(w)
            decline_and_side_effect_checks(w)
            http_checks(w)
            handoff_checks(w, ordinary)
            assert structure(owner, runtime) == original_structure, 'Notification work changed schema or runtime grants'
            print('PostgreSQL notification inbox: exact BIGINT recipient-only pagination/count/read, '
                  'canonical projection and BAN/SilentBAN/inactive fences, modes/maintenance, '
                  'concurrent first-read preservation, strict private HTTP, no Claim/Transfer/dispute '
                  'read side effects, atomic author notices/replay/rollback and handoff passed; '
                  'schema and runtime grants unchanged.')
        finally:
            for name in reversed(databases):
                system.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            system.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(runtime)))
